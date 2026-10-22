"""Real FBX export with Blender and import check with Unity (skipped unless BLENDER / UNITY are set).

    BLENDER=/path/to/blender python -m pytest tests/test_export_tools.py
    BLENDER=... UNITY=/path/to/Unity python -m pytest tests/test_export_tools.py

The Blender test exports Rowan into a temporary folder and re-imports the FBX;
the Unity test also imports it in a scratch Unity project in batch mode
(build/unity-check/test/project) and validates it with the built-in pipeline.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import export, unity  # noqa: E402
from tak.pipeline.names import ARKIT, VISEMES  # noqa: E402
from tak.pipeline.tools import find_blender  # noqa: E402

BLENDER = find_blender(os.environ["BLENDER"]) if os.environ.get("BLENDER") else None
UNITY = unity.find_unity() if os.environ.get("UNITY") else None

needs_blender = pytest.mark.skipif(not BLENDER, reason="set BLENDER to a Blender 4.2+ executable")
needs_unity = pytest.mark.skipif(not (BLENDER and UNITY), reason="set BLENDER and UNITY (Unity editor executable)")


@pytest.fixture(scope="module")
def rowan_export(tmp_path_factory):
    if not BLENDER:
        pytest.skip("set BLENDER")
    out = tmp_path_factory.mktemp("export")
    result = export.export_avatar("rowan", out_root=out, blender=BLENDER)
    return out, result


@needs_blender
def test_blender_export_and_reimport(rowan_export):
    out, result = rowan_export
    assert result["ok"], result
    assert result["verify"]["ok"], result["verify"]
    assert result["fbx_paths"]["ok"]
    sidecar = json.loads((out / "rowan" / "rowan.tak.json").read_text(encoding="utf-8"))
    assert export.check_sidecar(sidecar) == []
    assert sidecar["blendshapes"]["arkit"] == list(ARKIT)
    assert sidecar["blendshapes"]["visemes"] == list(VISEMES)
    assert len(sidecar["blendshapes"]["meshes"]["Body"]) == 67
    for tex in sidecar["textures"]:
        assert (out / "rowan" / tex["file"]).is_file()
    # The armature node is identity in Unity space (no -90 degree root rotation).
    armature = next(e for e in sidecar["rig"]["skeleton"] if e["name"] == sidecar["rig"]["armature"])
    assert armature["rotation"] == pytest.approx([0, 0, 0, 1], abs=1e-5)


@needs_unity
def test_unity_batch_check(rowan_export):
    out, _ = rowan_export
    result = unity.run_unity_check(out, ["rowan"], pipelines=("builtin",),
                                   project=unity.CHECK_ROOT / "test" / "project")
    assert result["ran"]
    assert result["ok"], result.get("summary") or result.get("error")
