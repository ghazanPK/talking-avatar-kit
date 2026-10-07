"""Subprocess job runner used by the Studio server.

Jobs run one at a time in a worker thread. Every output line is kept as raw
text; lines that are JSON objects are parsed as well. Progress lines follow
the pipeline contract ``{"stage": ..., "message": ..., "progress": 0..1}`` and
a final ``{"result": {...}}`` line carries the outcome.
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

MAX_LINES = 20000
TERMINATE_GRACE = 5.0

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED = "queued", "running", "succeeded", "failed", "cancelled"
FINISHED = (SUCCEEDED, FAILED, CANCELLED)


def parse_line(text: str) -> dict | None:
    """Parse a JSON object line; anything else returns None."""
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


@dataclass
class Job:
    id: str
    kind: str
    command: list[str]
    params: dict = field(default_factory=dict)
    cwd: str | None = None
    env: dict | None = None
    status: str = QUEUED
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    returncode: int | None = None
    stage: str | None = None
    message: str | None = None
    progress: float | None = None
    result: Any = None
    error: str | None = None
    lines: list[dict] = field(default_factory=list)
    dropped: int = 0
    cancel_requested: bool = False
    _process: subprocess.Popen | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_line(self, stream: str, raw: str) -> None:
        raw = raw.rstrip("\r\n")
        parsed = parse_line(raw)
        with self._lock:
            entry = {"n": self.dropped + len(self.lines), "t": round(time.time(), 3), "stream": stream, "raw": raw}
            if parsed is not None:
                entry["json"] = parsed
                if "stage" in parsed:
                    self.stage = str(parsed["stage"])
                if "message" in parsed:
                    self.message = str(parsed["message"])
                if isinstance(parsed.get("progress"), (int, float)):
                    self.progress = max(0.0, min(1.0, float(parsed["progress"])))
                if "result" in parsed:
                    self.result = parsed["result"]
            self.lines.append(entry)
            if len(self.lines) > MAX_LINES:
                drop = len(self.lines) - MAX_LINES
                del self.lines[:drop]
                self.dropped += drop

    def summary(self) -> dict:
        with self._lock:
            return {
                "id": self.id, "kind": self.kind, "params": self.params, "status": self.status,
                "created": self.created, "started": self.started, "finished": self.finished,
                "returncode": self.returncode, "stage": self.stage, "message": self.message,
                "progress": self.progress, "result": self.result, "error": self.error,
                "line_count": self.dropped + len(self.lines),
            }

    def detail(self, offset: int = 0) -> dict:
        data = self.summary()
        with self._lock:
            start = max(0, offset - self.dropped)
            data["offset"] = max(offset, self.dropped)
            data["lines"] = list(self.lines[start:])
            data["next_offset"] = self.dropped + len(self.lines)
            data["command"] = self.command
        return data


class JobRunner:
    """Runs submitted jobs sequentially in a background thread."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._queue: "queue.Queue[Job | None]" = queue.Queue()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._work, name="tak-jobs", daemon=True)
        self._worker.start()

    # -- public API ---------------------------------------------------------
    def submit(self, kind: str, command: list[str], params: dict | None = None,
               cwd: str | None = None, env: dict | None = None) -> Job:
        with self._lock:
            job = Job(id=f"{next(self._ids)}-{int(time.time())}", kind=kind, command=list(command),
                      params=dict(params or {}), cwd=cwd, env=env)
            self._jobs[job.id] = job
            self._order.append(job.id)
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            ids = list(reversed(self._order))
        return [self._jobs[i].summary() for i in ids]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        with job._lock:
            if job.status in FINISHED:
                return False
            job.cancel_requested = True
            if job.status == QUEUED:
                job.status = CANCELLED
                job.finished = time.time()
                return True
            process = job._process
        if process is not None:
            _terminate(process)
        return True

    def wait(self, job_id: str, timeout: float | None = None) -> Job | None:
        """Block until the job finishes (used by tests and scripts)."""
        deadline = None if timeout is None else time.time() + timeout
        job = self._jobs.get(job_id)
        while job is not None and job.status not in FINISHED:
            if deadline is not None and time.time() > deadline:
                break
            time.sleep(0.02)
        return job

    def shutdown(self) -> None:
        for job_id in list(self._order):
            self.cancel(job_id)
        self._queue.put(None)

    # -- worker -------------------------------------------------------------
    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            if job.status != QUEUED:
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        env = dict(os.environ)
        env.update(job.env or {})
        env.setdefault("PYTHONUNBUFFERED", "1")
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(job.command, cwd=job.cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
        except OSError as exc:
            with job._lock:
                job.status, job.error, job.finished = FAILED, f"could not start: {exc}", time.time()
            return
        with job._lock:
            if job.cancel_requested:
                cancelled_early = True
            else:
                cancelled_early = False
                job.status, job.started, job._process = RUNNING, time.time(), process
        if cancelled_early:
            _terminate(process)
        readers = [threading.Thread(target=_pump, args=(job, process.stdout, "stdout"), daemon=True),
                   threading.Thread(target=_pump, args=(job, process.stderr, "stderr"), daemon=True)]
        for reader in readers:
            reader.start()
        returncode = process.wait()
        for reader in readers:
            reader.join(timeout=5)
        with job._lock:
            job.returncode = returncode
            job.finished = time.time()
            job._process = None
            if job.cancel_requested:
                job.status = CANCELLED
            elif returncode == 0:
                job.status = SUCCEEDED
                if job.progress is not None:
                    job.progress = 1.0
            else:
                job.status = FAILED
                job.error = job.error or f"exit code {returncode}"


def _pump(job: Job, stream, name: str) -> None:
    try:
        for line in stream:
            job.add_line(name, line)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _terminate(process: subprocess.Popen) -> None:
    """Stop a process and its children: polite signal first, then kill."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=TERMINATE_GRACE)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
