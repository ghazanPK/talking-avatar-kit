"""Speech service used by the local server (standard library only).

Kokoro runs in a persistent worker subprocess (:mod:`tak.speech.worker`)
started with the speech interpreter: ``TAK_SPEECH_PYTHON``, the speech venv
``.tak/speech-venv``, or the current interpreter when it can import Kokoro.
Clips are cached in ``.tak/cache/speech/<key>.wav`` with the worker's raw
phoneme report next to them; the timeline is rebuilt from that report on
every request, so changes to the viseme conversion apply to cached clips.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

from . import (DEFAULT_VOICE, LANGUAGES, REPO_ROOT, cache_dir, current_python_has_kokoro, is_voice, models_dir,
               speech_python, voice_list)
from .visemes import build_timeline

MAX_TEXT = 2000
SPEED_RANGE = (0.5, 2.0)
ENGINE_ID = "kokoro-82m-v1.0"
SETUP_COMMAND = "python -m tak speech setup"
KEY_CHARS = set("0123456789abcdef")
REQUEST_TIMEOUT = 600  # the first request may download the model (about 330 MB)
# The audio runs about three frames (75 ms) ahead of the cumulative predicted
# durations; Kokoro's own word timestamps use the same correction. Measured on
# bilabial stop closures and releases, see docs/talking.md.
SHIFT_FRAMES = float(os.environ.get("TAK_SPEECH_SHIFT_FRAMES", "3"))


class SpeechError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Engine(Protocol):
    name: str

    def available(self) -> dict: ...

    def synthesize(self, text: str, voice: str, speed: float, out: Path) -> dict: ...

    def close(self) -> None: ...


class WorkerEngine:
    """Kokoro in a long-lived subprocess speaking JSON lines."""

    name = "kokoro"

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.counter = 0
        self._probe: tuple[float, dict] | None = None
        self.stderr_tail: list[str] = []

    def python(self) -> str | None:
        found = speech_python(self.repo_root)
        if found:
            return found
        return sys.executable if current_python_has_kokoro() else None

    def available(self) -> dict:
        now = time.monotonic()
        if self._probe and now - self._probe[0] < 30:
            return self._probe[1]
        python = self.python()
        if not python:
            info = {"ok": False, "python": None,
                    "reason": f"Kokoro is not installed. Run: {SETUP_COMMAND}"}
        else:
            from .cli import probe
            data = probe(python, self.repo_root)
            info = {"ok": bool(data.get("ok")), "python": python, "versions": data.get("versions"),
                    "languages": data.get("languages"), "reason": None if data.get("ok") else
                    f"The speech environment is incomplete ({data.get('error') or 'missing packages'}). Run: {SETUP_COMMAND}"}
        self._probe = (now, info)
        return info

    def _start(self) -> subprocess.Popen:
        python = self.python()
        if not python:
            raise SpeechError(f"Kokoro is not installed. Run: {SETUP_COMMAND}", 503)
        env = dict(os.environ)
        env.setdefault("TAK_KOKORO_DIR", str(models_dir(self.repo_root)))
        env["PYTHONPATH"] = str(self.repo_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.setdefault("PYTHONUNBUFFERED", "1")
        proc = subprocess.Popen([python, "-m", "tak.speech.worker", "--serve"], cwd=str(self.repo_root), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._drain, args=(proc,), daemon=True).start()
        line = proc.stdout.readline()
        if not line:
            proc.wait(timeout=10)
            raise SpeechError("The Kokoro worker did not start: " + " | ".join(self.stderr_tail[-5:]), 503)
        return proc

    def _drain(self, proc: subprocess.Popen) -> None:
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                self.stderr_tail = (self.stderr_tail + [line])[-40:]
                if os.environ.get("TAK_STUDIO_VERBOSE"):
                    print(f"[speech] {line}", file=sys.stderr)

    def synthesize(self, text: str, voice: str, speed: float, out: Path) -> dict:
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self.proc = self._start()
            self.counter += 1
            request = {"id": self.counter, "text": text, "voice": voice, "speed": speed, "out": str(out)}
            result: dict = {}

            def exchange():
                self.proc.stdin.write(json.dumps(request) + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
                result["line"] = line

            t = threading.Thread(target=exchange, daemon=True)
            t.start()
            t.join(REQUEST_TIMEOUT)
            if t.is_alive() or not result.get("line"):
                self._kill()
                raise SpeechError("The Kokoro worker stopped responding: " + " | ".join(self.stderr_tail[-5:]), 503)
            data = json.loads(result["line"])
            if not data.get("ok"):
                raise SpeechError(f"Kokoro failed: {data.get('error')}", 500)
            return data

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.proc = None

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
        self.proc = None


class SpeechService:
    def __init__(self, repo_root: Path = REPO_ROOT, engine: Engine | None = None, cache: Path | None = None):
        self.repo_root = Path(repo_root)
        self.engine = engine or WorkerEngine(self.repo_root)
        self.cache = Path(cache) if cache else cache_dir(self.repo_root)
        self.lock = threading.Lock()

    def status(self) -> dict:
        info = self.engine.available()
        folder = models_dir(self.repo_root)
        return {
            "available": bool(info.get("ok")),
            "engine": self.engine.name,
            "model": ENGINE_ID,
            "reason": info.get("reason"),
            "setup_command": SETUP_COMMAND,
            "python": info.get("python"),
            "versions": info.get("versions"),
            "g2p": info.get("languages"),
            "weights_downloaded": (folder / "kokoro-v1_0.pth").is_file(),
            "languages": [{"code": c, "tag": l["tag"], "name": l["name"]} for c, l in LANGUAGES.items()],
            "default_voice": DEFAULT_VOICE,
            "note": "Korean is not covered by Kokoro.",
        }

    def voices(self) -> dict:
        folder = models_dir(self.repo_root) / "voices"
        voices = voice_list()
        for v in voices:
            v["downloaded"] = (folder / f"{v['id']}.pt").is_file()
        return {"voices": voices, "default": DEFAULT_VOICE}

    @staticmethod
    def key(text: str, voice: str, speed: float) -> str:
        blob = json.dumps({"engine": ENGINE_ID, "text": text, "voice": voice, "speed": round(speed, 3)}, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def validate(self, text, voice, speed) -> tuple[str, str, float]:
        if not isinstance(text, str) or not text.strip():
            raise SpeechError("text must be a non-empty string")
        text = text.strip()
        if len(text) > MAX_TEXT:
            raise SpeechError(f"text is limited to {MAX_TEXT} characters")
        voice = voice or DEFAULT_VOICE
        if not is_voice(voice):
            raise SpeechError(f"unknown voice {voice!r}; see /api/speech/voices")
        try:
            speed = float(speed if speed is not None else 1.0)
        except (TypeError, ValueError):
            raise SpeechError("speed must be a number") from None
        if not SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]:
            raise SpeechError(f"speed must be between {SPEED_RANGE[0]} and {SPEED_RANGE[1]}")
        return text, voice, speed

    def say(self, text, voice=None, speed=None) -> dict:
        text, voice, speed = self.validate(text, voice, speed)
        key = self.key(text, voice, speed)
        wav, raw_path = self.cache / f"{key}.wav", self.cache / f"{key}.raw.json"
        cached = wav.is_file() and raw_path.is_file()
        raw = None
        if cached:
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = False
        if not cached:
            self.cache.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            raw = self.engine.synthesize(text, voice, speed, wav)
            raw = {"chunks": raw["chunks"], "sample_rate": raw.get("sample_rate", 24000), "samples": raw.get("samples"),
                   "seconds": round(time.monotonic() - started, 3)}
            if not wav.is_file():
                raise SpeechError("the speech engine wrote no audio", 500)
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
        timeline = build_timeline(raw["chunks"], sample_rate=raw.get("sample_rate", 24000), shift_frames=SHIFT_FRAMES,
                                  text=text, voice=voice, speed=speed, language=LANGUAGES[voice[0]]["tag"])
        return {"id": key, "cached": cached, "wav_path": wav, "audio_url": f"/api/speech/audio/{key}.wav",
                "synthesis_seconds": raw.get("seconds"), "timeline": timeline}

    def audio_path(self, name: str) -> Path | None:
        if not name.endswith(".wav"):
            return None
        key = name[:-4]
        if len(key) != 32 or not set(key) <= KEY_CHARS:
            return None
        path = self.cache / name
        return path if path.is_file() else None

    def close(self) -> None:
        self.engine.close()
