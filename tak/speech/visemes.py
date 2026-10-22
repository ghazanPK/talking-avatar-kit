"""Phonemes with durations -> words, phoneme segments and viseme keyframes.

Standard library only. The input is what the Kokoro worker reports for each
synthesised chunk: the phoneme string the model actually read (one model
token per character), the predicted duration of every token in frames
(``durations[0]`` and ``durations[-1]`` are the begin/end tokens) and the
number of audio samples. Kokoro predicts the duration of every phoneme, so
the timing comes from the model itself rather than from a forced aligner.

Phonemes map to the 15 Oculus visemes (``sil PP FF TH DD kk CH SS nn RR aa E I
O U``), which every avatar in this kit has as ``viseme_*`` morph targets.

The result (``timeline``) is a JSON object:

* ``words``: ``{"text", "start", "end", "phonemes"}`` in seconds;
* ``phonemes``: ``{"p", "start", "end", "viseme"}``; stress and length
  marks are folded into their phoneme, ``h`` takes the shape of the next
  sound, short gaps between words are shared by their neighbours;
* ``visemes``: merged segments ``{"viseme", "start", "end", "weight"}``;
* ``keys``: per morph target (``viseme_PP`` ...) a piecewise-linear curve
  ``[[t, w], ...]`` with anticipation and overlap (coarticulation), ready to
  sample at the audio time. Lip closures (``PP``) and lip-teeth contact
  (``FF``) hold their full weight for the whole consonant.
"""

from __future__ import annotations

import unicodedata
from typing import Iterable

TIMELINE_VERSION = 1
VISEMES = ("sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U")
FRAME_SAMPLES = 600  # Kokoro: one predicted duration frame = 600 samples at 24 kHz (25 ms)

# Single IPA (and misaki) symbols. Two-shape entries are diphthongs: the first
# shape takes 60 % of the duration.
PHONEME_VISEMES: dict[str, tuple[str, ...]] = {}
for _chars, _shape in (
    ("pbmɓ", ("PP",)), ("β", ("PP",)),
    ("fvɸ", ("FF",)), ("ʋ", ("FF",)),
    ("θð", ("TH",)),
    ("tdɾʈɖɽ", ("DD",)),
    ("kgɡŋxɣχqɢɴcɟ", ("kk",)),
    ("ʃʒʧʤɕʑʨʥʂʐ", ("CH",)),
    ("szʦʣçɧ", ("SS",)),
    ("nlɲɳʎɫɬɱ", ("nn",)),
    ("rɹɻʀʁɚɝʴ", ("RR",)),
    ("aɑɐæʌäᴀ", ("aa",)),
    ("eɛəɜᵊɘɞɤ", ("E",)),
    ("iɪɨᵻjʝ", ("I",)),
    ("oɔɒɵøœ", ("O",)),
    ("uʊwɯyʉɥɰ", ("U",)),
):
    for _c in _chars:
        PHONEME_VISEMES[_c] = _shape
# misaki diphthongs: A = eɪ, I = aɪ, O = oʊ (US), Q = əʊ (GB), W = aʊ, Y = ɔɪ
PHONEME_VISEMES.update({"A": ("E", "I"), "I": ("aa", "I"), "O": ("O", "U"), "Q": ("E", "U"),
                        "W": ("aa", "U"), "Y": ("O", "I")})
TRANSPARENT = set("hɦʰʔ")           # take the shape of the next sound
FOLD_NEXT = set("ˈˌ")               # stress marks: duration goes to the next phoneme
FOLD_PREV = set("ːˑʲʷˠˤ̃↓→↗↘ᵝꭧ")    # length, secondary articulation and tone marks
PAUSE = set(".,;:!?—…\"()“”«»¿¡-'")  # punctuation: silence

# Peak weight of each viseme (before stress/length scaling). Lip closures and
# lip-teeth contact must reach full weight; vowels stay below 1 so a
# following closure is not fighting a wide-open jaw.
PEAK = {"sil": 0.0, "PP": 1.0, "FF": 0.95, "TH": 0.7, "DD": 0.55, "kk": 0.5, "CH": 0.75, "SS": 0.6, "nn": 0.5,
        "RR": 0.6, "aa": 0.8, "E": 0.65, "I": 0.6, "O": 0.8, "U": 0.8}
WEAK = {"ᵊ": 0.55, "ə": 0.7, "ᵻ": 0.7, "ɐ": 0.8, "β": 0.6, "ʋ": 0.6, "ɰ": 0.6, "ʝ": 0.8, "w": 0.85, "j": 0.75}
HOLD = {"PP", "FF"}                  # keep the full weight for the whole consonant

# Envelope (seconds). Lips move before the sound they shape.
LEAD = 0.03          # anticipation: shapes start this much before the acoustic onset
ATTACK = 0.06        # rise time (vowels and most consonants)
RELEASE = 0.08       # fall time
CLOSURE_ATTACK = 0.04
CLOSURE_RELEASE = 0.04  # the lips open around the audible release
MIN_CLOSURE = 0.05   # shortest full lip closure / lip-teeth contact
GAP_SILENCE = 0.12   # a pause between words shorter than this is shared by its neighbours


def classify(ch: str) -> tuple[str, ...] | None:
    """Viseme shape(s) for one phoneme symbol; None for marks and unknown symbols."""
    if ch in PHONEME_VISEMES:
        return PHONEME_VISEMES[ch]
    base = unicodedata.normalize("NFD", ch)[:1]
    if base != ch and base in PHONEME_VISEMES:
        return PHONEME_VISEMES[base]
    lower = ch.lower()
    if lower != ch and lower in PHONEME_VISEMES and ch not in "AIOQWY":
        return PHONEME_VISEMES[lower]
    return None


def _kind(ch: str) -> str:
    if ch.isspace():
        return "space"
    if ch in PAUSE:
        return "pause"
    if ch in FOLD_NEXT:
        return "next"
    if ch in FOLD_PREV or unicodedata.combining(ch):
        return "prev"
    if ch in TRANSPARENT:
        return "transparent"
    if classify(ch):
        return "phone"
    return "next" if not ch.isalpha() else "unknown"


def chunk_phonemes(phonemes: str, durations: list[float], offset: float, frame: float, shift_frames: float = 0.0) -> list[dict]:
    """Raw per-symbol timing for one chunk: ``[{"p", "start", "end", "kind"}]``."""
    symbols = list(phonemes)
    if len(durations) != len(symbols) + 2:
        raise ValueError(f"expected {len(symbols) + 2} durations for {len(symbols)} phonemes, got {len(durations)}")
    t = offset + max(0.0, durations[0] - shift_frames) * frame
    out = []
    for ch, d in zip(symbols, durations[1:-1]):
        span = max(0.0, float(d)) * frame
        out.append({"p": ch, "start": t, "end": t + span, "kind": _kind(ch)})
        t += span
    return out


def fold(raw: list[dict]) -> list[dict]:
    """Fold marks into phonemes and turn pauses into silence; returns phones and silences."""
    phones: list[dict] = []
    pending_start = None  # start inherited from stress marks / transparent sounds
    for item in raw:
        kind = item["kind"]
        if kind == "transparent":
            start = item["start"] if pending_start is None else pending_start
            pending_start = None
            phones.append({"p": item["p"], "start": start, "end": item["end"], "viseme": None, "transparent": True})
            continue
        if kind == "next":
            if pending_start is None:
                pending_start = item["start"]
            continue
        if kind == "prev":
            if phones:
                phones[-1]["end"] = item["end"]
                phones[-1]["p"] += item["p"]
            elif pending_start is None:
                pending_start = item["start"]
            continue
        if kind in ("space", "pause"):
            phones.append({"p": item["p"], "start": item["start"], "end": item["end"], "viseme": "sil", "kind": kind})
            pending_start = None
            continue
        shape = classify(item["p"]) or ("E",)  # unknown letters: a neutral half-open shape
        start = item["start"] if pending_start is None else pending_start
        pending_start = None
        phones.append({"p": item["p"], "start": start, "end": item["end"], "viseme": shape[0], "shapes": shape,
                       "weak": WEAK.get(item["p"], 1.0) * (0.6 if kind == "unknown" else 1.0)})
    # Transparent sounds (h, glottal stop) take the next phone's shape.
    for i, ph in enumerate(phones):
        if ph.get("transparent"):
            nxt = next((q for q in phones[i + 1:] if q.get("viseme") and q["viseme"] != "sil"), None)
            gap_break = any(q.get("viseme") == "sil" and q["end"] - q["start"] >= GAP_SILENCE for q in phones[i + 1:phones.index(nxt)]) if nxt else True
            if nxt and not gap_break:
                ph.update(viseme=nxt["viseme"], shapes=nxt["shapes"][:1], weak=0.6 * nxt["weak"])
            else:
                ph.update(viseme="sil", kind="space")
            ph.pop("transparent", None)
    return phones


def _segments(phones: list[dict]) -> list[dict]:
    """Viseme segments: diphthongs split, short gaps shared, identical neighbours merged."""
    segs: list[dict] = []
    for ph in phones:
        v = ph["viseme"]
        if v == "sil":
            segs.append({"viseme": "sil", "start": ph["start"], "end": ph["end"], "weight": 0.0, "pause": ph.get("kind") == "pause"})
            continue
        shapes = ph["shapes"]
        start, end = ph["start"], ph["end"]
        dur = end - start
        weight = PEAK[shapes[0]] * ph.get("weak", 1.0)
        # Very short vowels and approximants do not reach their full target.
        if dur < 0.06 and shapes[0] not in HOLD:
            weight *= 0.75 + 0.25 * dur / 0.06
        if len(shapes) == 2:
            mid = start + 0.6 * dur
            segs.append({"viseme": shapes[0], "start": start, "end": mid, "weight": round(weight, 3)})
            segs.append({"viseme": shapes[1], "start": mid, "end": end, "weight": round(PEAK[shapes[1]] * ph.get("weak", 1.0) * 0.85, 3)})
        else:
            segs.append({"viseme": shapes[0], "start": start, "end": end, "weight": round(weight, 3)})
    # Short silences between words are coarticulation, not pauses: share them.
    out: list[dict] = []
    for i, s in enumerate(segs):
        if s["viseme"] == "sil" and not s.get("pause") and s["end"] - s["start"] < GAP_SILENCE and 0 < i < len(segs) - 1 \
                and segs[i - 1]["viseme"] != "sil" and segs[i + 1]["viseme"] != "sil":
            mid = (s["start"] + s["end"]) / 2
            if out:
                out[-1]["end"] = mid
            segs[i + 1]["start"] = mid
            continue
        if out and out[-1]["viseme"] == s["viseme"] and abs(out[-1]["end"] - s["start"]) < 1e-6:
            out[-1]["end"] = s["end"]
            out[-1]["weight"] = max(out[-1]["weight"], s["weight"])
            continue
        out.append(dict(s))
    for s in out:
        s.pop("pause", None)
    return out


def keyframes(segments: list[dict], duration: float, lead: float = LEAD) -> dict[str, list[list[float]]]:
    """Piecewise-linear weight curves per ``viseme_*`` morph.

    Each segment rises before its onset (anticipation ``lead`` plus the
    attack), holds, and releases after its end, so neighbouring shapes
    overlap. Curves of the same viseme are combined with ``max``.
    """
    curves: dict[str, list[tuple[float, float, float, float, float]]] = {}
    for s in segments:
        v = s["viseme"]
        if v == "sil" or s["weight"] <= 0:
            continue
        on, off = s["start"] - lead, s["end"] - lead
        dur = max(1e-3, off - on)
        if v in HOLD:
            # Lips close ahead of the sound and stay closed until the release
            # is heard, for at least MIN_CLOSURE so a closure shows on screen.
            attack, release = CLOSURE_ATTACK, CLOSURE_RELEASE
            hold_on, hold_off = on, max(s["end"] - CLOSURE_RELEASE / 2, on + MIN_CLOSURE)
        else:
            attack, release = ATTACK, RELEASE
            core = min(0.4 * dur, 0.05)
            hold_on, hold_off = on + core, max(on + core, off - core)
        curves.setdefault(v, []).append((max(0.0, hold_on - attack), hold_on, hold_off, min(duration, hold_off + release), s["weight"]))
    keys: dict[str, list[list[float]]] = {}
    for v, envs in curves.items():
        times = sorted({round(t, 4) for env in envs for t in env[:4]})
        points = []
        for t in times:
            w = max(_trapezoid(env, t) for env in envs)
            points.append([round(t, 3), round(w, 3)])
        keys[f"viseme_{v}"] = _simplify(points)
    return keys


def _trapezoid(env, t: float) -> float:
    a, b, c, d, w = env
    if t <= a or t >= d:
        return 0.0
    if t < b:
        return w * (t - a) / max(1e-6, b - a)
    if t <= c:
        return w
    return w * (d - t) / max(1e-6, d - c)


def _simplify(points: list[list[float]]) -> list[list[float]]:
    """Drop duplicate times and collinear interior points."""
    out: list[list[float]] = []
    for p in points:
        if out and abs(out[-1][0] - p[0]) < 1e-9:
            out[-1][1] = max(out[-1][1], p[1])
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        (t0, w0), (t1, w1), (t2, w2) = out[i - 1], out[i], out[i + 1]
        if t2 > t0 and abs(w0 + (w2 - w0) * (t1 - t0) / (t2 - t0) - w1) < 1e-3:
            out.pop(i)
        else:
            i += 1
    return out


def sample(keys: dict[str, list[list[float]]], t: float) -> dict[str, float]:
    """Weights at time ``t`` (same interpolation as the browser rig)."""
    out = {}
    for name, pts in keys.items():
        if not pts or t <= pts[0][0] or t >= pts[-1][0]:
            continue
        lo, hi = 0, len(pts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        (t0, w0), (t1, w1) = pts[lo], pts[hi]
        w = w0 + (w1 - w0) * (t - t0) / max(1e-9, t1 - t0)
        if w > 1e-4:
            out[name] = w
    return out


def _word_spans(phonemes: str, tokens: list[dict] | None) -> list[tuple[int, int, str]]:
    """Character spans ``(i0, i1, text)`` of words in the chunk's phoneme string."""
    spans = []
    if tokens:
        cursor, ok = 0, True
        for tok in tokens:
            tp = "".join(tok.get("phonemes") or "")
            if not tp:
                continue
            while cursor < len(phonemes) and phonemes[cursor].isspace():
                cursor += 1
            if phonemes.startswith(tp, cursor):
                if any(ch.isalnum() for ch in tok.get("text", "")):
                    spans.append((cursor, cursor + len(tp), tok.get("text", "")))
                cursor += len(tp)
            else:
                ok = False
                break
        if ok and spans:
            return spans
        spans = []
    i = 0
    while i < len(phonemes):
        if _kind(phonemes[i]) in ("space", "pause"):
            i += 1
            continue
        j = i
        while j < len(phonemes) and _kind(phonemes[j]) not in ("space", "pause"):
            j += 1
        spans.append((i, j, phonemes[i:j]))
        i = j
    return spans


def build_timeline(chunks: Iterable[dict], *, sample_rate: int = 24000, frame_samples: int = FRAME_SAMPLES,
                   shift_frames: float = 0.0, lead: float = LEAD, text: str = "", voice: str = "", speed: float = 1.0,
                   language: str = "") -> dict:
    """Combine worker chunks into one timeline (see the module docstring)."""
    frame = frame_samples / sample_rate
    offset = 0.0
    words, phones_all, raw_all = [], [], []
    for chunk in chunks:
        ps = chunk["phonemes"]
        raw = chunk_phonemes(ps, chunk["durations"], offset, frame, shift_frames)
        raw_all.extend(raw)
        graphemes = [g.strip(".,;:!?¡¿\"'()«»“”…—-") or g for g in (chunk.get("graphemes") or "").split()]
        spans = _word_spans(ps, chunk.get("tokens"))
        if not chunk.get("tokens") and len(graphemes) == len(spans):
            spans = [(a, b, g) for (a, b, _), g in zip(spans, graphemes)]
        for a, b, label in spans:
            if b > a:
                words.append({"text": label, "start": round(raw[a]["start"], 3), "end": round(raw[b - 1]["end"], 3),
                              "phonemes": ps[a:b]})
        phones_all.extend(fold(raw))
        samples = chunk.get("samples")
        offset += samples / sample_rate if samples else (sum(chunk["durations"]) * frame)
    duration = round(offset, 3)
    segments = _segments(phones_all)
    timeline = {
        "version": TIMELINE_VERSION,
        "duration": duration,
        "sample_rate": sample_rate,
        "text": text, "voice": voice, "speed": speed, "language": language,
        "visemes_set": "oculus15",
        "lead": lead,
        "words": words,
        "phonemes": [{"p": p["p"], "start": round(p["start"], 3), "end": round(p["end"], 3), "viseme": p["viseme"]}
                     for p in phones_all if p["end"] > p["start"] or p["viseme"] != "sil"],
        "visemes": [{"viseme": s["viseme"], "start": round(s["start"], 3), "end": round(s["end"], 3), "weight": s["weight"]}
                    for s in segments],
        "keys": keyframes(segments, duration, lead),
    }
    return timeline


__all__ = ["VISEMES", "PHONEME_VISEMES", "TIMELINE_VERSION", "classify", "build_timeline", "keyframes", "sample", "fold",
           "chunk_phonemes"]
