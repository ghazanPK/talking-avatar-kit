"""Studio job runner: JSON progress lines, failures and cancellation."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tak.jobs import JobRunner, parse_line  # noqa: E402

SCRIPT = r"""
import json, sys
print(json.dumps({"stage": "load", "message": "reading spec", "progress": 0.25}), flush=True)
print("plain text line", flush=True)
print("warning on stderr", file=sys.stderr, flush=True)
print(json.dumps({"stage": "export", "message": "writing glb", "progress": 0.9}), flush=True)
print(json.dumps({"result": {"glb": "avatars/x/x.glb", "ok": True}}), flush=True)
"""


def test_parse_line():
    assert parse_line('{"stage": "a", "progress": 0.5}') == {"stage": "a", "progress": 0.5}
    assert parse_line("[1, 2]") is None
    assert parse_line("{broken") is None
    assert parse_line("text") is None


def test_job_success_progress_and_lines():
    runner = JobRunner()
    job = runner.submit("build", [sys.executable, "-c", SCRIPT], params={"slug": "x"})
    runner.wait(job.id, timeout=30)
    detail = job.detail()
    assert detail["status"] == "succeeded" and detail["returncode"] == 0
    assert detail["stage"] == "export" and detail["progress"] == 1.0
    assert detail["result"] == {"glb": "avatars/x/x.glb", "ok": True}
    raws = [line["raw"] for line in detail["lines"]]
    assert "plain text line" in raws
    assert any(line["stream"] == "stderr" for line in detail["lines"])
    assert sum("json" in line for line in detail["lines"]) == 3
    tail = job.detail(offset=detail["next_offset"] - 1)
    assert len(tail["lines"]) == 1
    assert runner.list()[0]["id"] == job.id
    runner.shutdown()


def test_job_failure_and_queue_order():
    runner = JobRunner()
    bad = runner.submit("build", [sys.executable, "-c", "import sys; sys.exit(3)"])
    good = runner.submit("check", [sys.executable, "-c", "print('ok')"])
    runner.wait(good.id, timeout=30)
    assert bad.status == "failed" and bad.returncode == 3 and "3" in bad.error
    assert good.status == "succeeded"
    assert bad.finished <= good.started
    runner.shutdown()


def test_missing_executable_fails_cleanly():
    runner = JobRunner()
    job = runner.submit("build", ["definitely-not-a-real-program-tak"])
    runner.wait(job.id, timeout=10)
    assert job.status == "failed" and "could not start" in job.error
    runner.shutdown()


def test_cancel_running_and_queued():
    runner = JobRunner()
    slow = runner.submit("build", [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(60)"])
    queued = runner.submit("build", [sys.executable, "-c", "print('never')"])
    deadline = time.time() + 20
    while slow.status != "running" and time.time() < deadline:
        time.sleep(0.02)
    assert runner.cancel(queued.id)
    assert queued.status == "cancelled"
    started = time.time()
    assert runner.cancel(slow.id)
    runner.wait(slow.id, timeout=20)
    assert slow.status == "cancelled"
    assert time.time() - started < 15
    assert not runner.cancel(slow.id)
    time.sleep(0.2)
    assert queued.started is None
    runner.shutdown()
