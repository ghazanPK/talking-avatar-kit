"""FBX export and Unity package (no Blender, no Unity): options, bone map, sidecar schema, Unity helpers."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import AVATARS_DIR, export, unity  # noqa: E402
from tak.pipeline.glb import Glb  # noqa: E402
from tak.pipeline.names import ARKIT, GAME_ENGINE_BONES, VISEMES  # noqa: E402

# UnityEngine.HumanTrait.BoneName (Unity 2022.3 / 6000.x), in HumanBodyBones order.
UNITY_HUMAN_BONES = (
    "Hips", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg", "LeftFoot", "RightFoot",
    "Spine", "Chest", "Neck", "Head", "LeftShoulder", "RightShoulder", "LeftUpperArm", "RightUpperArm",
    "LeftLowerArm", "RightLowerArm", "LeftHand", "RightHand", "LeftToes", "RightToes", "LeftEye",
    "RightEye", "Jaw",
    *(f"{side} {finger} {joint}" for side in ("Left", "Right")
      for finger in ("Thumb", "Index", "Middle", "Ring", "Little")
      for joint in ("Proximal", "Intermediate", "Distal")),
    "UpperChest",
)

SLUGS = export.available_avatars()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TAK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("UNITY", raising=False)


# --------------------------------------------------------------------------- options

def test_parse_export_args():
    args = export.parse_export_args(["fbx", "rowan", "mira", "--out", "out", "--unity-check",
                                     "--pipeline", "urp", "--no-verify"])
    assert args.slugs == ["rowan", "mira"]
    assert args.out == Path("out")
    assert args.unity_check and args.no_verify and not args.all
    assert args.pipeline == "urp"
    args = export.parse_export_args(["fbx", "--all", "--unity", "MyProject"])
    assert args.all and args.unity == Path("MyProject") and args.pipeline == "both"


@pytest.mark.parametrize("argv", [["obj", "rowan"], ["fbx", "--pipeline", "hdrp"], ["fbx", "--bogus"]])
def test_parse_export_args_rejects(argv):
    with pytest.raises(SystemExit) as exc:
        export.parse_export_args(argv)
    assert exc.value.code not in (0, None)


def test_export_main_errors_without_blender_work(capsys):
    assert export.export_main(["fbx"]) == 2
    assert export.export_main(["fbx", "nobody"]) == 2
    assert export.export_main(["fbx", "rowan", "--all"]) == 2
    assert export.export_main(["stl", "rowan"]) == 2
    assert export.export_main(["--help"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert all("result" in json.loads(ln) for ln in lines)


def test_cli_dispatch_knows_export():
    from tak import __main__ as tak_main
    from tak.pipeline import cli

    assert tak_main.PIPELINE_COMMANDS["export"] == "export_main"
    assert cli.COMMANDS["export"] is cli.export_main
    assert cli.export_main(["fbx", "nobody"]) == 2


def test_resolve_slugs_uses_built_glbs():
    assert {"rowan", "mira"} <= set(SLUGS)
    assert export.resolve_slugs([], True) == SLUGS
    assert export.resolve_slugs(["mira", "mira"], False) == ["mira"]
    with pytest.raises(ValueError):
        export.resolve_slugs(["nobody"], False)
    with pytest.raises(ValueError):
        export.resolve_slugs([], False)


# --------------------------------------------------------------------------- bone map

def test_humanoid_map_covers_game_engine_rig():
    mapped = list(export.HUMANOID_MAP.values())
    assert len(GAME_ENGINE_BONES) == 53
    assert len(mapped) == len(set(mapped)) == 52
    assert set(mapped) <= set(GAME_ENGINE_BONES)
    assert set(GAME_ENGINE_BONES) - set(mapped) == set(export.UNMAPPED_BONES) == {"Root"}
    assert set(export.HUMANOID_MAP) <= set(UNITY_HUMAN_BONES)
    assert set(export.UNITY_REQUIRED) <= set(export.HUMANOID_MAP)
    # Everything Unity can map except eyes and jaw (blendshapes on this rig).
    assert set(UNITY_HUMAN_BONES) - set(export.HUMANOID_MAP) == {"LeftEye", "RightEye", "Jaw"}
    mapping, unmapped = export.humanoid_map(GAME_ENGINE_BONES)
    assert mapping == export.HUMANOID_MAP and unmapped == ["Root"]


def test_csharp_default_map_matches_python():
    text = (ROOT / "unity" / "Editor" / "HumanoidSetup.cs").read_text(encoding="utf-8")
    for human, bone in export.HUMANOID_MAP.items():
        if " " in human:  # finger names are generated from the same tables in C#
            continue
        side = "Left" if human.startswith("Left") else "Right" if human.startswith("Right") else None
        if side:
            suffix = human[len(side):]
            assert f'map[side + "{suffix}"] = "{bone[:-1]}" + s;' in text, human
        else:
            assert f'["{human}"] = "{bone}"' in text, human
    for finger, bone in (("Thumb", "thumb"), ("Index", "index"), ("Middle", "middle"), ("Ring", "ring"),
                         ("Little", "pinky")):
        assert f'("{finger}", "{bone}")' in text


def test_csharp_face_names_match_python():
    text = (ROOT / "unity" / "Runtime" / "FaceShapes.cs").read_text(encoding="utf-8")
    arkit = re.search(r"Arkit =\s*\{(.*?)\};", text, re.S).group(1)
    visemes = re.search(r"Visemes =\s*\{(.*?)\};", text, re.S).group(1)
    assert tuple(re.findall(r'"([^"]+)"', arkit)) == ARKIT
    assert tuple(re.findall(r'"([^"]+)"', visemes)) == VISEMES
    enum = re.search(r"enum Viseme\s*\{(.*?)\}", text, re.S).group(1)
    assert ["viseme_" + v.strip() for v in enum.split(",") if v.strip()] == list(VISEMES)


# --------------------------------------------------------------------------- manifests and materials

def test_avatar_meta_kit_style():
    meta = export.avatar_meta({"name": "Rowan", "license": "CC-BY-4.0", "credit": "talking-avatar-kit by Ghazanfar Ali",
                               "attribution": "Rowan avatar, ..."}, "rowan")
    assert meta["license"]["id"] == "CC-BY-4.0"
    assert meta["license"]["url"].startswith("https://creativecommons.org/licenses/by/4.0")
    assert meta["license"]["attribution"] == "Rowan avatar, ..."


def test_avatar_meta_owner_style_and_defaults():
    meta = export.avatar_meta({"name": "Amina", "licenses": {"character_geometry_and_makehuman_assets": "CC0-1.0"},
                               "credits": ["dress by Someone, CC BY"], "attribution": "Amina: ...",
                               "rig": "MPFB game_engine", "facial_shape_keys": {"arkit": 52}}, "amina")
    assert meta["license"]["id"] == "CC-BY-4.0"
    assert meta["license"]["credits"] == ["dress by Someone, CC BY"]
    assert meta["license"]["components"] == {"character_geometry_and_makehuman_assets": "CC0-1.0"}
    bare = export.avatar_meta({"attribution": None}, "min_jun")
    assert bare["name"] == "Min Jun"
    assert bare["license"]["attribution"] == "Min Jun avatar, talking-avatar-kit by Ghazanfar Ali, licensed under CC BY 4.0."
    obj = export.avatar_meta({"licence": {"id": "CC0-1.0"}, "credits": "Someone"}, "x")
    assert obj["license"]["id"] == "CC0-1.0" and obj["license"]["credit"] == "Someone"


@pytest.mark.parametrize("slug", SLUGS)
def test_shipped_manifests_give_licence_and_credit(slug):
    meta = export.avatar_meta(export.load_manifest(slug), slug)
    assert meta["name"] and meta["license"]["credit"] and meta["license"]["attribution"]


def test_specular_f0():
    assert export.specular_f0({"pbrMetallicRoughness": {"metallicFactor": 0}}) is None
    mat = {"pbrMetallicRoughness": {"metallicFactor": 0},
           "extensions": {"KHR_materials_ior": {"ior": 1.5}, "KHR_materials_specular": {"specularFactor": 0.5}}}
    assert export.specular_f0(mat) == pytest.approx(0.02)
    mat["pbrMetallicRoughness"]["metallicFactor"] = 1
    assert export.specular_f0(mat) is None


@pytest.mark.parametrize("slug", SLUGS)
def test_material_plan_from_shipped_glb(slug):
    glb = Glb.load(AVATARS_DIR / slug / f"{slug}.glb")
    plan = export.material_plan(glb.json)
    assert {"skin", "eyes", "eyebrows", "eyelashes", "teeth", "tongue", "hair", "shoes"} <= set(plan)
    assert plan["hair"]["alpha_mode"] == "MASK" and 0 < plan["hair"]["alpha_cutoff"] < 1
    assert plan["eyelashes"]["alpha_mode"] == "BLEND"
    files = set(export.texture_files(glb.json).values())
    for spec in plan.values():
        for key in ("base_color", "normal", "metallic_roughness"):
            if key in spec:
                assert spec[key]["file"] in files
        if "unity_map" in spec:
            assert spec["unity_map"]["kind"] == ("specular_smoothness" if "specular_f0" in spec else "metallic_smoothness")
    roles = export.texture_roles(plan)
    assert all(r["normal_map"] == ("normal" in r["roles"]) for r in roles.values())
    assert all(r["color_space"] == "sRGB" for r in roles.values() if "base_color" in r["roles"])
    assert all(r["color_space"] == "linear" for r in roles.values() if r["roles"] == ["normal"])


def test_extract_textures_writes_unchanged_bytes(tmp_path):
    glb = Glb.load(AVATARS_DIR / "rowan" / "rowan.glb")
    out = export.extract_textures(glb, tmp_path)
    assert len(out) == len(glb.json["images"])
    for name, info in out.items():
        data = (tmp_path / name).read_bytes()
        assert len(data) == info["bytes"]
        assert data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- sidecar

def fake_info():
    skeleton = [{"name": "rowan", "parent": None, "position": [0, 0, 0], "rotation": [0, 0, 0, 1],
                 "scale": [1, 1, 1], "world_position": [0, 0, 0]},
                {"name": "Armature", "parent": "rowan", "position": [0, 0, 0], "rotation": [0, 0, 0, 1],
                 "scale": [1, 1, 1], "world_position": [0, 0, 0]}]
    for bone in GAME_ENGINE_BONES:
        skeleton.append({"name": bone, "parent": "Armature", "position": [0, 0.1, 0], "rotation": [0, 0, 0, 1],
                         "scale": [1, 1, 1], "world_position": [0, 0.1, 0], "world_tail": [0, 0.2, 0]})
    return {
        "armature": "Armature",
        "bones": list(GAME_ENGINE_BONES),
        "skeleton": skeleton,
        "meshes": [
            {"name": "Body", "vertices": 10, "triangles": 8, "materials": ["skin"], "blendshapes": list(ARKIT + VISEMES)},
            {"name": "Teeth", "vertices": 4, "triangles": 2, "materials": ["teeth"], "blendshapes": ["jawOpen"]},
            {"name": "Hair", "vertices": 4, "triangles": 2, "materials": ["hair"], "blendshapes": []},
        ],
        "bounds_unity": {"min": [-0.5, 0, -0.2], "max": [0.5, 1.8, 0.2]},
        "height_m": 1.8,
        "fbx_settings": {"add_leaf_bones": False},
        "blender": "5.2.2",
        "fbx_exporter": "5.13.0",
    }


def fake_plan():
    return {
        "skin": {"alpha_mode": "OPAQUE", "double_sided": False, "base_color_factor": [1, 1, 1, 1],
                 "base_color": {"file": "skin.jpg"}, "normal": {"file": "skin_n.jpg", "scale": 1.0},
                 "metallic_roughness": {"file": "skin_r.jpg"}, "metallic": 0.0, "roughness": 1.0,
                 "smoothness": 0.0, "specular_f0": 0.028,
                 "unity_map": {"kind": "specular_smoothness", "source": "skin_r.jpg",
                               "file": "skin_r_specular_smoothness.png"}},
        "teeth": {"alpha_mode": "OPAQUE", "base_color": {"file": "teeth.jpg"}, "metallic": 0.0, "roughness": 0.3,
                  "smoothness": 0.7},
        "hair": {"alpha_mode": "MASK", "alpha_cutoff": 0.4, "double_sided": True, "base_color": {"file": "hair.png"},
                 "metallic": 0.0, "roughness": 0.6, "smoothness": 0.4},
        "unused": {"alpha_mode": "OPAQUE"},
    }


def make_sidecar():
    meta = export.avatar_meta({"name": "Rowan"}, "rowan")
    return export.build_sidecar(meta, fake_info(), fake_plan(), {"skin.jpg": {"sha256": "0" * 64, "bytes": 3}},
                                slug="rowan", glb_path=Path("rowan.glb"), glb_sha256="1" * 64, glb_bytes=10,
                                fbx_path=Path("rowan.fbx"))


def test_sidecar_schema():
    sidecar = make_sidecar()
    assert export.check_sidecar(sidecar) == []
    assert set(export.REQUIRED_SIDECAR_KEYS) <= set(sidecar)
    assert sidecar["schema"] == export.SIDECAR_SCHEMA
    assert sidecar["rig"]["unmapped"] == ["Root"]
    assert len(sidecar["rig"]["humanoid"]) == 52
    assert sidecar["blendshapes"]["arkit"] == list(ARKIT)
    assert sidecar["blendshapes"]["visemes"] == list(VISEMES)
    assert set(sidecar["blendshapes"]["meshes"]) == {"Body", "Teeth"}
    assert set(sidecar["materials"]) == {"skin", "teeth", "hair"}  # unused materials are dropped
    skin = sidecar["materials"]["skin"]
    assert skin["base_color"]["file"] == "textures/skin.jpg"
    assert skin["specular_smoothness"]["file"] == "textures/skin_r_specular_smoothness.png"
    assert sidecar["materials"]["hair"]["alpha_cutoff"] == 0.4
    textures = {t["file"]: t for t in sidecar["textures"]}
    assert textures["textures/skin_n.jpg"]["normal_map"] is True
    assert textures["textures/skin_r_specular_smoothness.png"]["color_space"] == "sRGB"
    assert textures["textures/skin_r.jpg"]["color_space"] == "linear"
    json.dumps(sidecar)  # serialisable


@pytest.mark.parametrize("damage, message", [
    (lambda s: s["rig"]["bones"].remove("hand_l"), "lacks game_engine bones"),
    (lambda s: s["rig"]["humanoid"].pop("Hips"), "lacks required bones"),
    (lambda s: s["rig"]["humanoid"].update(Jaw="jaw"), "unknown bones"),
    (lambda s: s["blendshapes"]["visemes"].pop(), "visemes"),
    (lambda s: s["license"].update(attribution=""), "license.attribution"),
    (lambda s: s["materials"]["skin"]["base_color"].update(file="/abs/skin.jpg"), "not relative"),
    (lambda s: s.pop("units"), "missing key units"),
    (lambda s: s["rig"]["skeleton"][3].update(parent="nowhere"), "unknown parent"),
])
def test_sidecar_schema_problems(damage, message):
    sidecar = make_sidecar()
    damage(sidecar)
    problems = export.check_sidecar(sidecar)
    assert any(message in p for p in problems), problems


def test_existing_export_sidecars_are_valid():
    found = sorted(export.DEFAULT_OUT.glob(f"*/*{export.SIDECAR_SUFFIX}"))
    if not found:
        pytest.skip("no exports in build/export (run 'python -m tak export fbx --all')")
    for path in found:
        assert export.check_sidecar(json.loads(path.read_text(encoding="utf-8"))) == [], path.name


def test_verify_report():
    sidecar = make_sidecar()
    good = {"bones": list(GAME_ENGINE_BONES), "leaf_bones": [],
            "meshes": [{"name": m, "blendshapes": n} for m, n in sidecar["blendshapes"]["meshes"].items()],
            "height_m": 1.8, "faces_minus_y": True, "left_on_plus_x": True,
            "object_scales": {"Armature": [1, 1, 1]}, "materials": ["skin", "teeth", "hair"],
            "images": ["skin.jpg"], "images_missing": 0}
    assert export.verify_report(good, sidecar)["ok"]
    bad = dict(good, leaf_bones=["head_end"], height_m=180.0, object_scales={"Armature": [100, 100, 100]})
    failed = {c["check"] for c in export.verify_report(bad, sidecar)["checks"] if not c["ok"]}
    assert failed == {"bones", "scale", "object_scale"}


def test_fbx_path_check(tmp_path):
    fbx = tmp_path / "a.fbx"
    fbx.write_bytes(b"Kaydara FBX Binary\x00RelativeFilename\x00S\x10\x00\x00\x00textures/skin.jpg\x00" + bytes(range(256)))
    assert export.fbx_path_check(fbx)["ok"]
    fbx.write_bytes(b"textures/skin.jpg\x00FileName\x00C:\\Users\\me\\proj\\textures\\skin.jpg")
    result = export.fbx_path_check(fbx)
    assert not result["ok"] and "absolute" in result["detail"]


# --------------------------------------------------------------------------- Unity helpers

def test_unity_package_files():
    pkg = json.loads((ROOT / "unity" / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == unity.PACKAGE_NAME
    assert re.match(r"^\d+\.\d+\.\d+$", pkg["version"])
    assert pkg["license"] == "MIT"
    runtime = json.loads((ROOT / "unity" / "Runtime" / "TalkingAvatarKit.Runtime.asmdef").read_text(encoding="utf-8"))
    editor = json.loads((ROOT / "unity" / "Editor" / "TalkingAvatarKit.Editor.asmdef").read_text(encoding="utf-8"))
    assert editor["includePlatforms"] == ["Editor"] and runtime["name"] in editor["references"]
    check = (ROOT / "unity" / "Editor" / "AvatarCheck.cs").read_text(encoding="utf-8")
    assert "public static void RunBatch()" in check
    assert unity.CHECK_METHOD.rsplit(".", 1)[1] == "RunBatch"
    assert "namespace TalkingAvatarKit.Editor" in check
    guids = []
    for path in (ROOT / "unity").rglob("*"):
        # Git-installed (immutable) packages need committed .meta files or Unity ignores the assets.
        if path.suffix != ".meta":
            meta = path.with_name(path.name + ".meta")
            assert meta.is_file(), f"{path.relative_to(ROOT)} has no .meta file"
            guids.append(re.search(r"guid: ([0-9a-f]{32})", meta.read_text()).group(1))
        if path.is_file():
            assert not re.search(r"[A-Za-z]:[\\/](Users|Program Files)|/mnt/[a-z]/|/home/", path.read_text(errors="ignore")), path
    assert len(guids) == len(set(guids))


def test_find_unity_prefers_env_and_ignores_non_editors(tmp_path, monkeypatch):
    fake = tmp_path / "Hub" / "Editor" / "6000.3.25f1" / "Editor" / "Unity.exe"
    fake.parent.mkdir(parents=True)
    fake.write_text("")
    monkeypatch.setenv("UNITY", str(fake))
    assert unity.find_unity() == str(fake)
    assert unity.find_unity(str(fake)) == str(fake)
    assert unity.unity_version(str(fake)) == "6000.3.25f1"
    assert not unity.is_editor(fake)
    (fake.parent / "Data" / "Resources").mkdir(parents=True)
    assert unity.is_editor(fake)


def test_builtin_package_version(tmp_path):
    exe = tmp_path / "Editor" / "Unity.exe"
    pkg = exe.parent / "Data" / "Resources" / "PackageManager" / "BuiltInPackages" / "com.unity.render-pipelines.universal"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"version": "17.3.0"}')
    assert unity.builtin_package_version(str(exe), "com.unity.render-pipelines.universal") == "17.3.0"
    assert unity.builtin_package_version(str(exe), "com.unity.missing") is None


def test_prepare_check_project_and_install(tmp_path):
    out = tmp_path / "export"
    (out / "rowan" / "textures").mkdir(parents=True)
    (out / "rowan" / "rowan.fbx").write_bytes(b"fbx")
    (out / "rowan" / "rowan.tak.json").write_text("{}")
    (out / "rowan" / "LICENSE.md").write_text("licence")
    (out / "rowan" / "export.log").write_text("log")
    (out / "rowan" / "textures" / "skin.jpg").write_bytes(b"jpg")
    project = tmp_path / "project"
    info = unity.prepare_check_project(project, out, ["rowan"], str(tmp_path / "Unity.exe"), ["builtin"])
    assert info["avatars"] == ["rowan"]
    dest = project / unity.AVATARS_SUBDIR / "rowan"
    assert (dest / "rowan.fbx").is_file() and (dest / "textures" / "skin.jpg").is_file()
    assert not (dest / "export.log").exists()
    assert (project / "Packages" / unity.PACKAGE_NAME / "package.json").is_file()
    manifest = json.loads((project / "Packages" / "manifest.json").read_text())
    assert "com.unity.modules.animation" in manifest["dependencies"]
    assert "com.unity.render-pipelines.universal" not in manifest["dependencies"]
    with pytest.raises(FileNotFoundError):
        unity.copy_exports(out, ["mira"], tmp_path / "x")
    with pytest.raises(FileNotFoundError):
        unity.install_into_project(tmp_path / "not-a-project", out, ["rowan"])
    (tmp_path / "user" / "Assets").mkdir(parents=True)
    installed = unity.install_into_project(tmp_path / "user", out, ["rowan"])
    assert installed["avatars"] == ["Assets/TalkingAvatarKit/Avatars/rowan"]


def test_run_unity_check_without_unity(tmp_path, monkeypatch):
    monkeypatch.setattr(unity, "find_unity", lambda explicit=None: None)
    result = unity.run_unity_check(tmp_path, ["rowan"])
    assert result["ran"] is False and "UNITY" in result["error"]


def test_diagnose_log(tmp_path):
    log = tmp_path / "unity.log"
    log.write_text("start\n[Licensing::Client] Error: No valid Unity Editor license found.\nexit\n")
    assert unity.diagnose_log(log, 1).startswith("Unity licensing failed")
    log.write_text("Assets/X.cs(3,1): error CS1002: ; expected\n")
    assert "compile errors" in unity.diagnose_log(log, 1)
    assert unity.diagnose_log(tmp_path / "missing.log", 1).endswith("wrote no log")
    assert unity.diagnose_log(log, None) == "Unity timed out"


def test_summarize():
    report = {"pipelines": {"builtin": {"ok": False, "shader": "Standard", "log_errors": ["x"], "avatars": {
        "rowan": {"ok": True, "checks": []},
        "mira": {"ok": False, "checks": [{"check": "t_pose", "ok": False, "detail": "9 deg"}]}}}}}
    report["cross_pipeline"] = {"ok": False, "tolerance": 40, "avatars": {
        "mira": {"full": {"ok": False, "failed": ["hair 120"]}, "face": {"ok": True, "failed": []}}}}
    out = unity.summarize(report)
    summary = out["builtin"]
    assert summary["avatars"] == {"rowan": "ok", "mira": ["t_pose: 9 deg"]}
    assert summary["log_errors"] == 1
    assert out["cross_pipeline"] == {"ok": False, "tolerance": 40, "failed": {"mira/full": ["hair 120"]}}
