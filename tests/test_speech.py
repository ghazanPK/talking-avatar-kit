"""Speech: phoneme -> viseme timeline conversion, speech endpoints with a fake TTS
engine (no network, no PyTorch), and a real Kokoro test that runs only when the
speech environment from ``python -m tak speech setup`` exists."""
import http.client
import json
import sys
import threading
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak import __main__ as cli  # noqa: E402
from tak import server as srv  # noqa: E402
from tak import speech  # noqa: E402
from tak.speech import visemes as vz  # noqa: E402
from tak.speech.service import SpeechError, SpeechService  # noqa: E402

FRAME = 600 / 24000

# "Peter bought a box of fresh apples." as misaki (US English) would read it,
# with plausible Kokoro frame durations (25 ms each).
PHRASE = "pˈiɾəɹ bˈɔt ɐ bˈɑks ʌv fɹˈɛʃ ˈæpᵊlz."
TOKENS = [
    {"text": "Peter", "phonemes": "pˈiɾəɹ", "whitespace": True},
    {"text": "bought", "phonemes": "bˈɔt", "whitespace": True},
    {"text": "a", "phonemes": "ɐ", "whitespace": True},
    {"text": "box", "phonemes": "bˈɑks", "whitespace": True},
    {"text": "of", "phonemes": "ʌv", "whitespace": True},
    {"text": "fresh", "phonemes": "fɹˈɛʃ", "whitespace": True},
    {"text": "apples", "phonemes": "ˈæpᵊlz", "whitespace": False},
    {"text": ".", "phonemes": ".", "whitespace": False},
]


def durations_for(phonemes, consonant=3, vowel=4, space=1, pause=8, mark=1, bos=4, eos=6):
    out = [bos]
    for ch in phonemes:
        kind = vz._kind(ch)
        if kind == "space":
            out.append(space)
        elif kind == "pause":
            out.append(pause)
        elif kind in ("next", "prev"):
            out.append(mark)
        elif (vz.classify(ch) or ("x",))[0] in ("aa", "E", "I", "O", "U"):
            out.append(vowel)
        else:
            out.append(consonant)
    out.append(eos)
    return out


def chunk(phonemes=PHRASE, tokens=TOKENS, graphemes="Peter bought a box of fresh apples.", **kw):
    d = durations_for(phonemes, **kw)
    return {"graphemes": graphemes, "phonemes": phonemes, "durations": d, "samples": sum(d) * 600, "tokens": tokens}


# ---------------------------------------------------------------------------
# Conversion

def test_classify_covers_kokoro_symbols():
    for ch in "pbmfvθðtdɾkgŋʃʒʧʤszlnɹwjhaæɑɐʌəɚɛɪiʊuɔoᵊᵻAIOWYQ":
        kind = vz._kind(ch)
        assert kind in ("phone", "transparent"), ch
    assert vz.classify("p") == ("PP",) and vz.classify("b") == ("PP",) and vz.classify("m") == ("PP",)
    assert vz.classify("f") == ("FF",) and vz.classify("v") == ("FF",)
    assert vz.classify("A") == ("E", "I")  # misaki diphthong eɪ
    assert vz.classify("ã") == ("aa",)     # combining marks fall back to the base letter
    assert vz._kind("ˈ") == "next" and vz._kind("ː") == "prev" and vz._kind(",") == "pause"


def test_timeline_words_and_monotonic_phonemes():
    tl = vz.build_timeline([chunk()], text="Peter bought a box of fresh apples.", voice="af_heart")
    assert [w["text"] for w in tl["words"]] == ["Peter", "bought", "a", "box", "of", "fresh", "apples"]
    starts = [w["start"] for w in tl["words"]]
    assert starts == sorted(starts)
    assert all(w["end"] > w["start"] for w in tl["words"])
    assert tl["words"][0]["start"] == pytest.approx(4 * FRAME, abs=1e-3)  # after the begin token
    ph = tl["phonemes"]
    for a, b in zip(ph, ph[1:]):
        assert b["start"] >= a["start"] - 1e-9
        assert b["start"] == pytest.approx(a["end"], abs=2e-3)  # contiguous coverage
    assert tl["duration"] == pytest.approx(sum(chunk()["durations"]) * FRAME, abs=1e-3)
    assert ph[-1]["end"] <= tl["duration"]


def at_word_start(tl, word):
    """The viseme segment sounding when ``word`` starts (gaps between words are shared)."""
    ws = next(w for w in tl["words"] if w["text"] == word)["start"]
    return next(s for s in tl["visemes"] if s["start"] - 1e-6 <= ws < s["end"])


def test_visemes_follow_the_sounds():
    tl = vz.build_timeline([chunk()])
    shapes = [s["viseme"] for s in tl["visemes"]]
    assert shapes[0] == "PP"                              # P of Peter
    words = {w["text"]: w for w in tl["words"]}
    # Lips closed at the start of "bought" and "box", lip-teeth at "fresh".
    for word, shape in (("Peter", "PP"), ("bought", "PP"), ("box", "PP"), ("fresh", "FF")):
        assert at_word_start(tl, word)["viseme"] == shape, word
    # The pause at the full stop is silence; the segment list covers the clip.
    assert tl["visemes"][-1]["viseme"] == "sil"
    for a, b in zip(tl["visemes"], tl["visemes"][1:]):
        assert b["start"] == pytest.approx(a["end"], abs=2e-3)
        assert not (a["viseme"] == b["viseme"])          # neighbours merged


def test_keyframes_anticipate_and_hold_closures():
    tl = vz.build_timeline([chunk()])
    keys = tl["keys"]
    assert set(keys) <= {f"viseme_{v}" for v in vz.VISEMES if v != "sil"}
    for name, pts in keys.items():
        times = [p[0] for p in pts]
        assert times == sorted(times), name
        assert all(0 <= p[1] <= 1 for p in pts), name
        assert pts[0][1] == 0 and pts[-1][1] == 0, name
    words = {w["text"]: w for w in tl["words"]}
    for word in ("Peter", "bought", "box"):
        b = at_word_start(tl, word)
        assert b["viseme"] == "PP"
        # Full closure during the whole consonant (shifted by the lead) ...
        for t in (b["start"] - tl["lead"] + 0.002, (b["start"] + b["end"]) / 2 - tl["lead"]):
            assert vz.sample(keys, t).get("viseme_PP", 0) == pytest.approx(1.0, abs=1e-3), word
        # ... and the lips are already closing before the word is heard.
        assert vz.sample(keys, words[word]["start"] - 0.02).get("viseme_PP", 0) > 0.3, word
    f = at_word_start(tl, "fresh")
    assert vz.sample(keys, (f["start"] + f["end"]) / 2 - tl["lead"])["viseme_FF"] > 0.9
    # Silence after the last word.
    assert vz.sample(keys, tl["duration"] - 0.01) == {}


def test_chunks_are_offset_by_their_audio():
    a = chunk("hˈɛloʊ.", tokens=None, graphemes="Hello.")
    b = chunk("ðˈɛɹ.", tokens=None, graphemes="There.")
    tl = vz.build_timeline([a, b])
    assert [w["text"] for w in tl["words"]] == ["Hello", "There"]  # punctuation stripped from labels
    assert tl["words"][1]["start"] == pytest.approx(a["samples"] / 24000 + 4 * FRAME, abs=1e-3)
    assert tl["duration"] == pytest.approx((a["samples"] + b["samples"]) / 24000, abs=1e-3)
    # h takes the shape of the following vowel instead of closing the mouth.
    assert tl["phonemes"][0]["viseme"] == "E"


def test_untokenised_languages_use_phoneme_words():
    tl = vz.build_timeline([chunk("ola ˈkomo ˈestas", tokens=None, graphemes="hola como estás")])
    assert [w["text"] for w in tl["words"]] == ["hola", "como", "estás"]
    tl = vz.build_timeline([chunk("koɲiʨiwa", tokens=None, graphemes="こんにちは")])
    assert [(w["text"], w["phonemes"]) for w in tl["words"]] == [("こんにちは", "koɲiʨiwa")]


def test_duration_mismatch_is_rejected():
    bad = chunk()
    bad["durations"] = bad["durations"][:-2]
    with pytest.raises(ValueError):
        vz.build_timeline([bad])


# ---------------------------------------------------------------------------
# Server endpoints with a fake engine

class FakeEngine:
    name = "fake"

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def available(self):
        return {"ok": self.ok, "python": "fake", "reason": None if self.ok else "Kokoro is not installed. Run: python -m tak speech setup"}

    def synthesize(self, text, voice, speed, out):
        if not self.ok:
            raise SpeechError("Kokoro is not installed. Run: python -m tak speech setup", 503)
        self.calls += 1
        c = chunk()
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x00" * c["samples"])
        return {"ok": True, "sample_rate": 24000, "samples": c["samples"], "chunks": [c]}

    def close(self):
        pass


@pytest.fixture()
def server(tmp_path):
    repo = tmp_path / "repo"
    (repo / "studio" / "talk").mkdir(parents=True)
    (repo / "studio" / "talk" / "index.html").write_text("<!doctype html><title>Talk</title>")
    server = srv.make_server(0, repo_root=repo, settings_file=tmp_path / "settings.json", python=sys.executable)
    server.speech = SpeechService(repo, engine=FakeEngine(), cache=tmp_path / "cache")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.runner.shutdown()
    server.server_close()


def call(server, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    ctype = response.getheader("Content-Type") or ""
    return response.status, (json.loads(payload) if ctype.startswith("application/json") else payload), ctype


def test_speech_status_and_voices(server):
    status, data, _ = call(server, "GET", "/api/speech/status")
    assert status == 200 and data["available"] is True
    assert data["setup_command"] == "python -m tak speech setup"
    assert {"en-US", "en-GB"} <= {lang["tag"] for lang in data["languages"]}
    assert "Korean" in data["note"]
    status, data, _ = call(server, "GET", "/api/speech/voices")
    ids = [v["id"] for v in data["voices"]]
    assert status == 200 and "af_heart" in ids and "bf_emma" in ids and data["default"] == "af_heart"


def test_speech_say_returns_audio_and_timeline(server):
    status, data, _ = call(server, "POST", "/api/speech/say", {"text": "Peter bought a box of fresh apples.", "voice": "bf_emma", "speed": 1.1})
    assert status == 200, data
    assert data["cached"] is False and "wav_path" not in data
    tl = data["timeline"]
    assert tl["voice"] == "bf_emma" and tl["language"] == "en-GB" and tl["speed"] == 1.1
    assert len(tl["words"]) == 7 and "viseme_PP" in tl["keys"]
    status, wav, ctype = call(server, "GET", data["audio_url"])
    assert status == 200 and ctype == "audio/wav" and wav[:4] == b"RIFF"
    status, again, _ = call(server, "POST", "/api/speech/say", {"text": "Peter bought a box of fresh apples.", "voice": "bf_emma", "speed": 1.1})
    assert again["cached"] is True and again["id"] == data["id"]
    assert server.speech.engine.calls == 1


@pytest.mark.parametrize("body,needle", [
    ({"text": ""}, "text"),
    ({"text": "hi", "voice": "xx_nobody"}, "voice"),
    ({"text": "hi", "voice": "../etc"}, "voice"),
    ({"text": "hi", "speed": 9}, "speed"),
    ({"text": "x" * 2001}, "2000"),
])
def test_speech_say_validation(server, body, needle):
    status, data, _ = call(server, "POST", "/api/speech/say", body)
    assert status == 400 and needle in data["error"]


def test_speech_audio_path_is_safe(server):
    for path in ("/api/speech/audio/..%2F..%2Fsettings.json", "/api/speech/audio/abc.wav", "/api/speech/audio/" + "g" * 32 + ".wav"):
        status, _, _ = call(server, "GET", path)
        assert status == 404


def test_speech_unavailable_reports_setup(server):
    server.speech = SpeechService(server.repo_root, engine=FakeEngine(ok=False), cache=server.repo_root / "cache")
    status, data, _ = call(server, "GET", "/api/speech/status")
    assert data["available"] is False and "python -m tak speech setup" in data["reason"]
    status, data, _ = call(server, "POST", "/api/speech/say", {"text": "Hello"})
    assert status == 503 and "setup" in data["error"]


def test_talk_page_is_served(server):
    status, body, ctype = call(server, "GET", "/talk/")
    assert status == 200 and b"Talk" in body and ctype.startswith("text/html")


def test_cli_lists_speech_and_demo(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "demo" in out and "speech" in out
    assert cli.main(["speech", "--help"]) == 0
    assert "setup" in capsys.readouterr().out
    assert cli.main(["speech", "voices"]) == 0
    assert "af_heart" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Real Kokoro (only with the speech environment)

def _speech_ready():
    # setup writes .tak/speech-install.json once everything is installed
    python = speech.speech_python(ROOT)
    return python is not None and (speech.tak_dir(ROOT) / "speech-install.json").is_file()


@pytest.mark.skipif(not _speech_ready(), reason="speech environment not installed (python -m tak speech setup)")
def test_real_kokoro_timeline(tmp_path):
    service = SpeechService(ROOT, cache=tmp_path)
    try:
        clip = service.say("Peter bought a box of fresh apples.", "af_heart", 1.0)
    finally:
        service.close()
    tl = clip["timeline"]
    with wave.open(str(clip["wav_path"])) as w:
        seconds = w.getnframes() / w.getframerate()
    assert tl["duration"] == pytest.approx(seconds, abs=0.03)
    assert [w["text"] for w in tl["words"]][:3] == ["Peter", "bought", "a"]
    assert tl["visemes"][0]["viseme"] in ("sil", "PP")
    assert any(s["viseme"] == "FF" for s in tl["visemes"])
