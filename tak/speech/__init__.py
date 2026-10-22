"""Optional speech: Kokoro text-to-speech with phoneme timing and viseme tracks.

The Studio core stays standard-library only. Kokoro (PyTorch) runs in its own
virtual environment under ``.tak/speech-venv`` (``python -m tak speech
setup``) and is driven through a worker subprocess (:mod:`tak.speech.worker`).
Model weights are downloaded on first use into ``.tak/models/`` and never
committed.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

KOKORO_REPO = "hexgrad/Kokoro-82M"
KOKORO_CONFIG = "config.json"
KOKORO_WEIGHTS = "kokoro-v1_0.pth"
SAMPLE_RATE = 24000
DEFAULT_VOICE = "af_heart"

# Kokoro language codes (first letter of a voice id) and the extra G2P
# dependencies each needs. Korean is not covered by Kokoro.
LANGUAGES = {
    "a": {"tag": "en-US", "name": "English (US)", "extra": "en"},
    "b": {"tag": "en-GB", "name": "English (UK)", "extra": "en"},
    "e": {"tag": "es", "name": "Spanish", "extra": "espeak"},
    "f": {"tag": "fr-FR", "name": "French", "extra": "espeak"},
    "h": {"tag": "hi", "name": "Hindi", "extra": "espeak"},
    "i": {"tag": "it", "name": "Italian", "extra": "espeak"},
    "p": {"tag": "pt-BR", "name": "Portuguese (Brazil)", "extra": "espeak"},
    "j": {"tag": "ja", "name": "Japanese", "extra": "ja"},
    "z": {"tag": "zh", "name": "Mandarin Chinese", "extra": "zh"},
}

# Kokoro v1.0 voices (hexgrad/Kokoro-82M, VOICES.md). Voice files are
# downloaded on first use.
VOICES = {
    "a": ["af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova",
          "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
          "am_michael", "am_onyx", "am_puck", "am_santa"],
    "b": ["bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
    "e": ["ef_dora", "em_alex", "em_santa"],
    "f": ["ff_siwis"],
    "h": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
    "i": ["if_sara", "im_nicola"],
    "p": ["pf_dora", "pm_alex", "pm_santa"],
    "j": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
    "z": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"],
}


def voice_list() -> list[dict]:
    out = []
    for code, names in VOICES.items():
        lang = LANGUAGES[code]
        for name in names:
            out.append({"id": name, "lang": code, "language": lang["tag"], "language_name": lang["name"],
                        "gender": "female" if name[1] == "f" else "male",
                        "label": f"{name.split('_', 1)[1].capitalize()} ({lang['tag']}, {'female' if name[1] == 'f' else 'male'})"})
    return out


def is_voice(name: object) -> bool:
    return isinstance(name, str) and len(name) > 3 and name[0] in VOICES and name in VOICES[name[0]]


def tak_dir(repo_root: Path | None = None) -> Path:
    return Path(os.environ.get("TAK_SPEECH_HOME") or (Path(repo_root or REPO_ROOT) / ".tak"))


def venv_dir(repo_root: Path | None = None) -> Path:
    override = os.environ.get("TAK_SPEECH_VENV")
    return Path(override) if override else tak_dir(repo_root) / "speech-venv"


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def models_dir(repo_root: Path | None = None) -> Path:
    override = os.environ.get("TAK_KOKORO_DIR")
    return Path(override) if override else tak_dir(repo_root) / "models" / "Kokoro-82M"


def cache_dir(repo_root: Path | None = None) -> Path:
    return tak_dir(repo_root) / "cache" / "speech"


def speech_python(repo_root: Path | None = None) -> str | None:
    """Interpreter that can import Kokoro: ``TAK_SPEECH_PYTHON``, then the speech venv."""
    override = os.environ.get("TAK_SPEECH_PYTHON")
    if override:
        return override
    candidate = venv_python(venv_dir(repo_root))
    return str(candidate) if candidate.is_file() else None


def current_python_has_kokoro() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("kokoro") is not None
    except (ImportError, ValueError):
        return False


__all__ = ["REPO_ROOT", "KOKORO_REPO", "SAMPLE_RATE", "DEFAULT_VOICE", "LANGUAGES", "VOICES", "voice_list", "is_voice",
           "tak_dir", "venv_dir", "venv_python", "models_dir", "cache_dir", "speech_python", "current_python_has_kokoro"]
