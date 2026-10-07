"""JSON-lines progress protocol shared with the Studio job runner.

Every line on stdout is one JSON object: progress lines
``{"stage": str, "message": str, "progress": float 0..1}`` and one final
``{"result": {...}}`` line. Human-readable detail goes to stderr or log files.
"""
from __future__ import annotations

import json
import sys
from typing import IO, Any


class Progress:
    def __init__(self, stream: IO[str] | None = None, *, start: float = 0.0, end: float = 1.0):
        self.stream = stream or sys.stdout
        self.start = start
        self.end = end

    def scaled(self, start: float, end: float) -> "Progress":
        """A sub-reporter mapping 0..1 onto [start, end] of this reporter's range."""
        span = self.end - self.start
        return Progress(self.stream, start=self.start + span * start, end=self.start + span * end)

    def emit(self, stage: str, message: str, progress: float) -> None:
        value = self.start + (self.end - self.start) * min(max(float(progress), 0.0), 1.0)
        line = {"stage": str(stage), "message": str(message), "progress": round(value, 4)}
        self.stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.stream.flush()

    def result(self, payload: dict[str, Any]) -> None:
        self.stream.write(json.dumps({"result": payload}, ensure_ascii=False) + "\n")
        self.stream.flush()


def validate_line(text: str) -> dict:
    """Parse one protocol line and check its shape; raises ValueError when invalid."""
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("line is not a JSON object")
    if "result" in obj:
        if set(obj) != {"result"} or not isinstance(obj["result"], dict):
            raise ValueError("result line must be {'result': {...}}")
        return obj
    if set(obj) != {"stage", "message", "progress"}:
        raise ValueError(f"unexpected keys {sorted(obj)}")
    if not isinstance(obj["stage"], str) or not isinstance(obj["message"], str):
        raise ValueError("stage and message must be strings")
    if not isinstance(obj["progress"], (int, float)) or not 0 <= obj["progress"] <= 1:
        raise ValueError("progress must be a number in 0..1")
    return obj
