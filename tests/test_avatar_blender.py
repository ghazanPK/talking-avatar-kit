"""Real avatar build with headless Blender and MPFB (skipped when they are not available).

Builds Rowan into a temporary folder (the repository's avatars/ is not
touched), then runs the static GLB checks and the Blender re-import check.
Enable by installing Blender (found through BLENDER, PATH, the Studio settings
or the standard folders) and running ``python -m tak setup``.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import AVATARS_DIR, BLENDER_SCRIPTS, tools  # noqa: E402
from tak.pipeline.setup import installed_repo  # noqa: E402
from tak.pipeline.spec import load_spec  # noqa: E402
from tak.pipeline.validate import blender_checks, static_checks  # noqa: E402

BLENDER = tools.find_blender()
MPFB = installed_repo(tools.profile_dir())

pytestmark = pytest.mark.skipif(not (BLENDER and MPFB),
                                reason="needs Blender and 'python -m tak setup' (MPFB + packs)")


def test_real_build_and_reimport(tmp_path):
    spec_path = AVATARS_DIR / "rowan" / "spec.json"
    events = []
    for line in tools.run_blender(BLENDER, BLENDER_SCRIPTS / "build_avatar.py",
                                  ["--spec", tools.PathArg(spec_path), "--out-dir", tools.PathArg(tmp_path)],
                                  profile=tools.profile_dir()):
        data = tools.parse_marker(line)
        if data:
            events.append(data)
    result = next(e for e in events if e.get("event") == "result")
    assert len(result["bones"]) == 53
    assert len(result["morphs"]["Body"]) == 67
    assert "eyeBlinkLeft" in result["morphs"]["Eyelashes"]
    assert "jawOpen" in result["morphs"]["Teeth"]
    spec = load_spec(spec_path)
    glb = tmp_path / "rowan.glb"
    static = static_checks(glb, spec)
    assert static["ok"], static["failures"]
    reimport = blender_checks(glb, spec, BLENDER)
    assert reimport["ok"], reimport["failures"]
