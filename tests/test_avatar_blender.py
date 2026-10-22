"""Real avatar builds with headless Blender and MPFB (skipped when they are not available).

Builds Rowan (kit look, CC0 community garments, ray-cast cover) and Amina (MPFB look,
CC BY community dress and hair) into a temporary folder (avatars/ is not touched),
runs the static GLB checks and the Blender re-import check, and compares the result
with the shipped GLB: same bones, morph targets, materials, vertex counts and height.
Enable by installing Blender (found through BLENDER, PATH, the Studio settings or the
standard folders) and running ``python -m tak setup``.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import AVATARS_DIR, BLENDER_SCRIPTS, PACKS, tools  # noqa: E402
from tak.pipeline.glb import Glb  # noqa: E402
from tak.pipeline.setup import installed_repo, pack_installed, read_record  # noqa: E402
from tak.pipeline.spec import load_spec  # noqa: E402
from tak.pipeline.validate import blender_checks, static_checks  # noqa: E402

BLENDER = tools.find_blender()
MPFB = installed_repo(tools.profile_dir())
PACKS_READY = all(pack_installed(key, read_record(), tools.profile_dir()) for key in PACKS)

pytestmark = pytest.mark.skipif(not (BLENDER and MPFB and PACKS_READY),
                                reason="needs Blender and 'python -m tak setup' (MPFB + packs)")


def summary(path):
    gltf = Glb.load(path).json
    nodes = gltf["nodes"]
    meshes = {}
    lo, hi = 1e9, -1e9
    for node in nodes:
        if "mesh" in node:
            mesh = gltf["meshes"][node["mesh"]]
            acc = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
            lo, hi = min(lo, acc["min"][1]), max(hi, acc["max"][1])
            meshes[node["name"]] = (acc["count"], sorted(mesh.get("extras", {}).get("targetNames", [])))
    return {"bones": [nodes[j]["name"] for j in gltf["skins"][0]["joints"]], "meshes": meshes,
            "materials": sorted(m["name"] for m in gltf["materials"]), "height": round(hi - lo, 3)}


@pytest.mark.parametrize("slug", ["rowan", "amina"])
def test_real_build_matches_the_shipped_avatar(tmp_path, slug):
    spec_path = AVATARS_DIR / slug / "spec.json"
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
    glb = tmp_path / f"{slug}.glb"
    static = static_checks(glb, spec)
    assert static["ok"], static["failures"]
    reimport = blender_checks(glb, spec, BLENDER)
    assert reimport["ok"], reimport["failures"]
    assert summary(glb) == summary(AVATARS_DIR / slug / f"{slug}.glb")
