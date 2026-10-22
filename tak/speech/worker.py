"""Kokoro worker: runs inside the speech virtual environment.

Started by :class:`tak.speech.service.SpeechService` as
``<speech python> -m tak.speech.worker --serve``; it reads one JSON request
per line on stdin and answers with one JSON line on stdout:

* request ``{"id", "text", "voice", "speed", "out"}`` writes a 24 kHz mono
  WAV to ``out`` and answers ``{"id", "ok": true, "sample_rate", "samples",
  "chunks": [{"graphemes", "phonemes", "durations", "samples", "tokens"}]}``
  where ``phonemes`` is the exact string the model read (one model token per
  character) and ``durations`` the predicted frames per token including the
  begin/end tokens;
* errors answer ``{"id", "ok": false, "error"}``.

Other modes: ``--download af_heart,bf_emma`` fetches the weights and voices
from the Hugging Face Hub into the models folder, ``--say TEXT --voice V
--out FILE`` synthesises once.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import wave
from pathlib import Path

from . import KOKORO_CONFIG, KOKORO_REPO, KOKORO_WEIGHTS, SAMPLE_RATE, is_voice, models_dir


class Kokoro:
    def __init__(self, folder: Path | None = None, device: str | None = None):
        self.folder = Path(folder or models_dir())
        self.device = device or os.environ.get("TAK_SPEECH_DEVICE") or "cpu"
        self.model = None
        self.pipelines: dict[str, object] = {}
        self.lock = threading.Lock()

    # files ----------------------------------------------------------------------
    def fetch(self, filename: str) -> Path:
        target = self.folder / filename
        if target.is_file():
            return target
        from huggingface_hub import hf_hub_download
        self.folder.mkdir(parents=True, exist_ok=True)
        print(f"downloading {KOKORO_REPO}/{filename}", file=sys.stderr, flush=True)
        return Path(hf_hub_download(repo_id=KOKORO_REPO, filename=filename, local_dir=str(self.folder)))

    def voice_path(self, voice: str) -> Path:
        if not is_voice(voice):
            raise ValueError(f"unknown Kokoro voice {voice!r}")
        return self.fetch(f"voices/{voice}.pt")

    def load(self):
        if self.model is None:
            from kokoro import KModel
            config, weights = self.fetch(KOKORO_CONFIG), self.fetch(KOKORO_WEIGHTS)
            self.model = KModel(repo_id=KOKORO_REPO, config=str(config), model=str(weights)).to(self.device).eval()
        return self.model

    def pipeline(self, lang: str):
        if lang not in self.pipelines:
            from kokoro import KPipeline
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id=KOKORO_REPO, model=self.load(), device=self.device)
        return self.pipelines[lang]

    # synthesis --------------------------------------------------------------------
    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> tuple[list, list[dict]]:
        import numpy as np
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty text")
        voice_file = self.voice_path(voice)
        with self.lock:
            model = self.load()
            pipe = self.pipeline(voice[0])
            pieces, chunks = [], []
            for result in pipe(text, voice=str(voice_file), speed=float(speed)):
                audio = result.audio
                if audio is None:
                    continue
                pcm = audio.detach().cpu().numpy().astype("float32")
                pred = result.pred_dur
                ps = "".join(ch for ch in (result.phonemes or "") if ch in model.vocab)
                durations = [int(x) for x in pred.detach().cpu().tolist()] if pred is not None else None
                if durations is None or len(durations) != len(ps) + 2:
                    raise RuntimeError(f"phoneme durations do not match the phonemes ({len(ps)} phonemes)")
                tokens = None
                if result.tokens:
                    tokens = [{"text": t.text, "phonemes": "".join(ch for ch in (t.phonemes or "") if ch in model.vocab),
                               "whitespace": bool(t.whitespace)} for t in result.tokens]
                chunks.append({"graphemes": result.graphemes, "phonemes": ps, "durations": durations,
                               "samples": int(pcm.shape[0]), "tokens": tokens})
                pieces.append(pcm)
            if not pieces:
                raise RuntimeError("Kokoro produced no audio (check the G2P installation for this language)")
            return np.concatenate(pieces), chunks


def write_wav(path: Path, pcm) -> None:
    import numpy as np
    data = (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data)
    os.replace(tmp, path)


def handle(engine: Kokoro, request: dict) -> dict:
    rid = request.get("id")
    try:
        if request.get("op") == "ping":
            return {"id": rid, "ok": True, "pong": True}
        pcm, chunks = engine.synthesize(request["text"], request["voice"], request.get("speed", 1.0))
        write_wav(Path(request["out"]), pcm)
        return {"id": rid, "ok": True, "sample_rate": SAMPLE_RATE, "samples": int(pcm.shape[0]), "chunks": chunks}
    except Exception as exc:  # reported to the server, which keeps running
        return {"id": rid, "ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


def serve() -> int:
    # Libraries may print; keep the protocol channel clean.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr
    engine = Kokoro()
    protocol.write(json.dumps({"ready": True}) + "\n")
    protocol.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            protocol.write(json.dumps({"ok": False, "error": "bad JSON"}) + "\n")
            protocol.flush()
            continue
        protocol.write(json.dumps(handle(engine, request)) + "\n")
        protocol.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tak.speech.worker")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--download", metavar="VOICES")
    parser.add_argument("--say")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if args.serve:
        return serve()
    engine = Kokoro()
    if args.download is not None:
        engine.fetch(KOKORO_CONFIG)
        engine.fetch(KOKORO_WEIGHTS)
        for voice in filter(None, (v.strip() for v in args.download.split(","))):
            engine.voice_path(voice)
        print(json.dumps({"models": str(engine.folder)}))
        return 0
    if args.say:
        if not args.out:
            parser.error("--say needs --out")
        result = handle(engine, {"id": 0, "text": args.say, "voice": args.voice, "speed": args.speed, "out": args.out})
        print(json.dumps({k: v for k, v in result.items() if k != "chunks"} | {"chunks": len(result.get("chunks") or [])}))
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
