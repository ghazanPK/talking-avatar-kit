"""``python -m tak speech <command>``: set up and use the optional Kokoro speech.

Commands:

* ``setup``   create ``.tak/speech-venv`` and install Kokoro (CPU PyTorch by
  default), the English G2P model and the default voices; then synthesise a
  test sentence. ``--check`` only reports what is installed or missing.
* ``status``  print the speech status as JSON (what the server reports).
* ``voices``  list the Kokoro voices as JSON.
* ``say``     synthesise text to a WAV file plus a ``.json`` timeline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import (DEFAULT_VOICE, KOKORO_REPO, LANGUAGES, REPO_ROOT, models_dir, speech_python, tak_dir, venv_dir,
               venv_python, voice_list)

SUPPORTED_PY = ((3, 10), (3, 12))  # Kokoro 0.9 supports Python 3.10 to 3.12
KOKORO_REQ = "kokoro>=0.9.4,<1.0"
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
SPACY_MODEL = "en_core_web_sm"
LANG_EXTRAS = {"ja": "misaki[ja]", "zh": "misaki[zh]"}


def say(message: str) -> None:
    print(f"[speech] {message}", flush=True)


def _py_version(python: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run([python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        major, minor = out.stdout.split()
        return int(major), int(minor)
    except ValueError:
        return None


def _supported(version: tuple[int, int] | None) -> bool:
    return version is not None and SUPPORTED_PY[0] <= version <= SUPPORTED_PY[1]


def find_base_python(explicit: str | None = None) -> tuple[str | None, list[str]]:
    """A Python 3.10-3.12 to create the venv from: --python, this one, then PATH."""
    tried = []
    candidates: list[list[str]] = []
    if explicit:
        candidates.append([explicit])
    else:
        candidates.append([sys.executable])
        for minor in (12, 11, 10):
            exe = shutil.which(f"python3.{minor}")
            if exe:
                candidates.append([exe])
        if os.name == "nt" and shutil.which("py"):
            for minor in (12, 11, 10):
                candidates.append(["py", f"-3.{minor}"])
    for cmd in candidates:
        if len(cmd) == 1:
            version = _py_version(cmd[0])
            tried.append(f"{cmd[0]} ({'.'.join(map(str, version)) if version else 'not runnable'})")
            if _supported(version):
                return cmd[0], tried
        else:  # Windows launcher: resolve to the real interpreter
            try:
                out = subprocess.run(cmd + ["-c", "import sys; print(sys.executable)"], capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                continue
            exe = out.stdout.strip()
            if out.returncode == 0 and exe and _supported(_py_version(exe)):
                return exe, tried
            tried.append(" ".join(cmd))
    return None, tried


def _run(cmd: list[str], **kw) -> int:
    say("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], **kw).returncode


def probe(python: str | None, repo_root: Path) -> dict:
    """Ask the speech interpreter what it can import (no model loading)."""
    if not python:
        return {"python": None, "ok": False}
    code = (
        "import json, importlib.util as u, sys\n"
        "mods = ['torch', 'kokoro', 'misaki', 'soundfile', 'spacy', 'espeakng_loader', 'phonemizer', 'huggingface_hub', 'pyopenjtalk', 'fugashi', 'jieba', 'pypinyin', 'cn2an']\n"
        "found = {m: bool(u.find_spec(m)) for m in mods}\n"
        "ver = {}\n"
        "try:\n  import importlib.metadata as md\n"
        "  for d in ('torch', 'kokoro', 'misaki', 'spacy', 'en-core-web-sm'):\n"
        "    try: ver[d] = md.version(d)\n    except Exception: pass\n"
        "except Exception: pass\n"
        "print(json.dumps({'python': sys.version.split()[0], 'modules': found, 'versions': ver}))\n"
    )
    try:
        out = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=120, cwd=str(repo_root))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"python": python, "ok": False, "error": str(exc)}
    try:
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"python": python, "ok": False, "error": (out.stderr or out.stdout).strip()[-800:]}
    mods = data["modules"]
    data["path"] = python
    data["ok"] = all(mods.get(m) for m in ("torch", "kokoro", "misaki", "soundfile", "huggingface_hub"))
    data["languages"] = {
        "en": bool(mods.get("spacy") and data["versions"].get("en-core-web-sm")),
        "espeak": bool(mods.get("espeakng_loader") and mods.get("phonemizer")),
        "ja": bool(mods.get("pyopenjtalk") or mods.get("fugashi")),
        "zh": bool(mods.get("jieba") and mods.get("pypinyin")),
    }
    return data


def install_record_path(repo_root: Path) -> Path:
    return tak_dir(repo_root) / "speech-install.json"


def model_files(repo_root: Path) -> dict:
    folder = models_dir(repo_root)
    voices = sorted(p.stem for p in (folder / "voices").glob("*.pt")) if (folder / "voices").is_dir() else []
    return {"dir": str(folder), "config": (folder / "config.json").is_file(),
            "weights": (folder / "kokoro-v1_0.pth").is_file(), "voices": voices}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def setup_main(argv: list[str], repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(prog="python -m tak speech setup",
                                     description="Install the optional Kokoro speech into .tak/speech-venv.")
    parser.add_argument("--check", action="store_true", help="only report what is installed or missing")
    parser.add_argument("--python", help="Python 3.10-3.12 used to create the venv (default: this one or python3.12/3.11/3.10 on PATH)")
    parser.add_argument("--lang", default="", help="extra G2P languages to install: ja, zh (comma separated)")
    parser.add_argument("--torch-index", default=None, help=f"PyTorch package index (default {TORCH_CPU_INDEX} on Linux and Windows)")
    parser.add_argument("--voices", default=f"{DEFAULT_VOICE},bf_emma", help="voices to download now (others download on first use)")
    parser.add_argument("--no-download", action="store_true", help="do not download the model now")
    parser.add_argument("--no-test", action="store_true", help="skip the test synthesis")
    args = parser.parse_args(argv)

    venv = venv_dir(repo_root)
    python = speech_python(repo_root)
    status = probe(python, repo_root)
    if args.check:
        report = {"venv": str(venv), "speech_python": python, "probe": status, "models": model_files(repo_root)}
        print(json.dumps(report, indent=2))
        missing = [] if status.get("ok") else ["speech packages (run: python -m tak speech setup)"]
        if not model_files(repo_root)["weights"]:
            missing.append("Kokoro weights (downloaded on first use or by setup)")
        print("missing: " + (", ".join(missing) if missing else "nothing"))
        return 0 if not missing else 1

    extras = [x.strip() for x in args.lang.split(",") if x.strip()]
    unknown = [x for x in extras if x not in LANG_EXTRAS]
    if unknown:
        parser.error(f"--lang supports {', '.join(LANG_EXTRAS)}; Spanish, French, Hindi, Italian and Portuguese need nothing extra")

    if not os.environ.get("TAK_SPEECH_PYTHON") and not venv_python(venv).is_file():
        base, tried = find_base_python(args.python)
        if not base:
            say("No Python 3.10, 3.11 or 3.12 found (Kokoro does not support other versions yet). Tried: " + "; ".join(tried))
            say("Install one and pass it with --python PATH.")
            return 2
        say(f"Creating {venv} with {base}")
        venv.parent.mkdir(parents=True, exist_ok=True)
        if _run([base, "-m", "venv", str(venv)]) != 0:
            return 1
    python = speech_python(repo_root)
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check"]
    status = probe(python, repo_root)
    mods = status.get("modules", {})
    if not mods.get("torch"):
        index = args.torch_index
        if index is None and sys.platform != "darwin":
            index = TORCH_CPU_INDEX
        if _run(pip + ["torch"] + (["--index-url", index] if index else [])) != 0:
            say("Installing PyTorch failed.")
            return 1
    packages = [] if mods.get("kokoro") and mods.get("soundfile") else [KOKORO_REQ, "soundfile"]
    packages += [LANG_EXTRAS[x] for x in extras]
    if packages and _run(pip + packages) != 0:
        say("Installing Kokoro failed.")
        return 1
    status = probe(python, repo_root)
    if not status["languages"].get("en"):
        # misaki's English G2P needs the small spaCy pipeline; install it now
        # instead of on the first request.
        if _run([python, "-m", "spacy", "download", SPACY_MODEL]) != 0:
            say(f"Could not install the spaCy model {SPACY_MODEL}; English G2P will try again on first use.")
    status = probe(python, repo_root)
    if not status.get("ok"):
        say("Speech packages are still incomplete: " + json.dumps(status.get("modules")))
        return 1

    record = {"installed": time.strftime("%Y-%m-%dT%H:%M:%S"), "python": status.get("python"),
              "versions": status.get("versions"), "languages": status.get("languages"), "model_repo": KOKORO_REPO}
    if not args.no_download:
        voices = [v.strip() for v in args.voices.split(",") if v.strip()]
        say(f"Downloading {KOKORO_REPO} (weights and voices {', '.join(voices)}) into {models_dir(repo_root)}")
        code = _run([python, "-m", "tak.speech.worker", "--download", ",".join(voices)], cwd=str(repo_root))
        if code != 0:
            say("Model download failed; it is retried on first use.")
            return 1
        folder = models_dir(repo_root)
        record["files"] = {p.relative_to(folder).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                           for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix in (".json", ".pth", ".pt")}
    if not args.no_test and not args.no_download:
        out = tak_dir(repo_root) / "cache" / "speech" / "setup-test.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        code = _run([python, "-m", "tak.speech.worker", "--say", "Hello, the speech setup works.", "--voice", DEFAULT_VOICE,
                     "--out", str(out)], cwd=str(repo_root))
        if code != 0:
            say("Test synthesis failed.")
            return 1
        record["test"] = {"wav": out.name, "bytes": out.stat().st_size}
    path = install_record_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    say("Speech is ready. Start the demo with: python -m tak demo")
    return 0


def status_main(argv: list[str], repo_root: Path = REPO_ROOT) -> int:
    from .service import SpeechService
    print(json.dumps(SpeechService(repo_root).status(), indent=2))
    return 0


def voices_main(argv: list[str]) -> int:
    print(json.dumps({"voices": voice_list()}, indent=2))
    return 0


def say_main(argv: list[str], repo_root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(prog="python -m tak speech say", description="Synthesise text to WAV plus a timeline JSON.")
    parser.add_argument("text")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--out", required=True, help="output .wav path; the timeline goes next to it as .json")
    args = parser.parse_args(argv)
    from .service import SpeechError, SpeechService
    service = SpeechService(repo_root)
    try:
        clip = service.say(args.text, args.voice, args.speed)
    except SpeechError as exc:
        print(f"speech: {exc}", file=sys.stderr)
        return 1
    finally:
        service.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clip["wav_path"], out)
    out.with_suffix(".json").write_text(json.dumps(clip["timeline"], indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"wav": str(out), "timeline": str(out.with_suffix(".json")), "duration": clip["timeline"]["duration"],
                      "cached": clip["cached"]}))
    return 0


USAGE = """usage: python -m tak speech <command>

commands:
  setup     install Kokoro into .tak/speech-venv (--check only reports)
  status    print the speech status as JSON
  voices    list the Kokoro voices
  say       synthesise text to WAV plus a timeline JSON (--voice, --speed, --out)
"""


def speech_main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0 if argv else 1
    command, rest = argv[0], argv[1:]
    if command == "setup":
        return setup_main(rest)
    if command == "status":
        return status_main(rest)
    if command == "voices":
        return voices_main(rest)
    if command == "say":
        return say_main(rest)
    print(f"unknown speech command: {command}\n", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2
