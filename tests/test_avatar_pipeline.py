"""Avatar pipeline without Blender or network: specs, progress protocol, CLI, GLB checks, manifest, setup."""
import copy
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tak.pipeline import AVATARS_DIR, PACKS, cli, tools  # noqa: E402
from tak.pipeline import setup as tak_setup  # noqa: E402
from tak.pipeline.glb import Glb, GlbError  # noqa: E402
from tak.pipeline.manifest import build_manifest  # noqa: E402
from tak.pipeline.names import ARKIT, BASE_MATERIALS, FACE, GAME_ENGINE_BONES, VISEMES  # noqa: E402
from tak.pipeline.progress import Progress, validate_line  # noqa: E402
from tak.pipeline.spec import SpecError, load_spec, validate_spec  # noqa: E402
from tak.pipeline.validate import static_checks  # noqa: E402


# --------------------------------------------------------------------------- specs

def real_spec(slug="rowan"):
    return load_spec(AVATARS_DIR / slug / "spec.json")


SLUGS = ["amina", "elena", "minjun", "mira", "rowan"]


@pytest.mark.parametrize("slug", SLUGS)
def test_shipped_specs_are_valid(slug):
    spec = real_spec(slug)
    assert spec["slug"] == slug
    assert spec["rig"] == "game_engine"
    assert spec.get("look", "kit") in ("kit", "mpfb")
    slots = {c["slot"] for c in spec["clothes"]}
    assert "shoes" in slots and ("outfit" in slots or {"top", "bottom"} <= slots)


@pytest.mark.parametrize("slug", SLUGS)
def test_spec_has_no_machine_paths(slug):
    text = (AVATARS_DIR / slug / "spec.json").read_text(encoding="utf-8")
    assert ":\\" not in text and ":/" not in text.replace("https://", "") and "/mnt/" not in text


def test_kit_and_mpfb_looks():
    """Rowan and Mira keep the kit's skin pipeline (detail maps); the others MPFB's materials."""
    for slug in ("rowan", "mira"):
        spec = real_spec(slug)
        assert spec["look"] == "kit" and len(spec["skin"]["detail"]) == 6
    for slug in ("amina", "elena", "minjun"):
        assert real_spec(slug)["look"] == "mpfb"


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["clothes"][1].__setitem__("pack", "nopack"), "must be a pack installed by setup"),
    (lambda s: s["clothes"][1].pop("credit"), "credit is required"),
    (lambda s: s["hair"].pop("credit"), "hair.credit is required"),
    (lambda s: s["clothes"][1].__setitem__("cover", "maybe"), "cover must be one of"),
    (lambda s: s["clothes"][0].__setitem__("tucked", True), "tucked applies to the top only"),
    (lambda s: s["clothes"][2].__setitem__("recolor", [2, 0, 0]), "recolor must be"),
    (lambda s: s.__setitem__("look", "toon"), "look must be one of"),
    (lambda s: s.__setitem__("weights", {"body": "yes"}), "weights must be"),
    (lambda s: s.__setitem__("layering", 1), "layering must be"),
    (lambda s: s.__setitem__("persona", ""), "persona must be"),
])
def test_invalid_recipe_keys_are_rejected(mutate, message):
    spec = copy.deepcopy(real_spec("elena"))
    mutate(spec)
    with pytest.raises(SpecError) as info:
        validate_spec(spec, "elena")
    assert message in str(info.value)


def test_cc_by_credit_rule_follows_the_pack_licence():
    spec = copy.deepcopy(real_spec("rowan"))
    assert all("credit" not in c for c in spec["clothes"])  # CC0 community packs need no credit
    spec["clothes"][1]["pack"] = "skirts02"
    with pytest.raises(SpecError, match="credit is required"):
        validate_spec(spec, "rowan")


# --------------------------------------------------------------------------- packs

def test_pack_table():
    import re
    for key, meta in PACKS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]), key
        assert meta["url"].startswith("https://files2.makehumancommunity.org/"), key
        assert meta["url"].endswith("/" + meta["file"]), key
        assert meta["page"] == f"https://static.makehumancommunity.org/assets/assetpacks/{key}.html"
        assert meta["license"] in ("CC0", "CC-BY"), key
        assert meta["kind"] in ("system", "functional", "community"), key
    hashes = [meta["sha256"] for meta in PACKS.values()]
    assert len(hashes) == len(set(hashes))
    assert {"shirts01", "pants01", "suits01", "dress03", "hair02", "hair03", "shirts02", "skirts02",
            "skins02"} <= set(PACKS)


def test_every_spec_pack_is_installed_by_setup():
    used = {}
    for slug in SLUGS:
        spec = real_spec(slug)
        for block in [spec["hair"], *spec["clothes"]]:
            if "pack" in block:
                assert block["pack"] in PACKS
                assert block["asset"] in PACKS[block["pack"]]["uses"], (slug, block["asset"])
                used.setdefault(block["pack"], set()).add(block["asset"])
        if spec["skin"]["material"] in PACKS["skins02"]["uses"]:
            used.setdefault("skins02", set()).add(spec["skin"]["material"])
    for key, meta in PACKS.items():
        if meta["kind"] == "community":
            assert set(meta["uses"]) == used.get(key, set()), key


def test_installed_pack_is_skipped_without_its_archive(tmp_path):
    profile = tmp_path / "profile"
    data = tak_setup.user_data_dir(profile)
    (data / "packs").mkdir(parents=True)
    (data / "packs" / "hair02.json").write_text("{}", encoding="utf-8")
    record = {"packs": {"hair02": {"sha256": PACKS["hair02"]["sha256"], "pack_json": "hair02"}}}
    assert tak_setup.pack_installed("hair02", record, profile)
    record["packs"]["hair02"]["sha256"] = "0" * 64
    assert not tak_setup.pack_installed("hair02", record, profile)


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["body"].__setitem__("age", 1.5), "body.age"),
    (lambda s: s["body"].pop("height"), "body.height is required"),
    (lambda s: s["body"]["race"].update(african=0, asian=0, caucasian=0), "must not all be zero"),
    (lambda s: s.__setitem__("rig", "rigify"), "rig must be"),
    (lambda s: s["hair"].__setitem__("asset", "../../etc"), "hair.asset"),
    (lambda s: s["clothes"].append({"asset": "x", "slot": "shoes"}), "slots must be unique"),
    (lambda s: s["textures"].__setitem__("skin_max", 3000), "textures.skin_max"),
    (lambda s: s["checks"].__setitem__("height_m", [2.0, 1.0]), "checks.height_m"),
    (lambda s: s["eyes"].__setitem__("mesh", "cyclops"), "eyes needs mesh"),
    (lambda s: s.__setitem__("schema_version", 2), "schema_version"),
    (lambda s: s["skin"].__setitem__("tint", [1.2, 1, 1]), "skin.tint"),
])
def test_invalid_specs_are_rejected(mutate, message):
    spec = copy.deepcopy(real_spec())
    mutate(spec)
    with pytest.raises(SpecError) as info:
        validate_spec(spec, "rowan")
    assert message in str(info.value)


def test_spec_slug_must_match_folder():
    with pytest.raises(SpecError, match="does not match its folder"):
        validate_spec(copy.deepcopy(real_spec()), "mira")


def test_load_spec_reports_bad_json(tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "spec.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SpecError, match="not valid JSON"):
        load_spec(folder / "spec.json")


# --------------------------------------------------------------------------- progress protocol

def test_progress_lines_follow_the_protocol():
    stream = io.StringIO()
    progress = Progress(stream)
    progress.emit("setup", "start", 0.0)
    sub = progress.scaled(0.5, 1.0)
    sub.emit("build", "half way", 0.5)
    sub.emit("build", "clamped", 7)
    progress.result({"ok": True})
    lines = stream.getvalue().splitlines()
    parsed = [validate_line(line) for line in lines]
    assert parsed[1]["progress"] == 0.75
    assert parsed[2]["progress"] == 1.0
    assert parsed[-1] == {"result": {"ok": True}}


@pytest.mark.parametrize("line", [
    '{"stage": "x", "message": "m"}',
    '{"stage": "x", "message": "m", "progress": 1.5}',
    '{"stage": 1, "message": "m", "progress": 0.1}',
    '{"result": [1]}',
    '[1, 2]',
])
def test_invalid_protocol_lines(line):
    with pytest.raises(ValueError):
        validate_line(line)


def test_parse_marker():
    assert tools.parse_marker('TAK {"event": "result", "a": 1}') == {"event": "result", "a": 1}
    assert tools.parse_marker("TAK [1]") is None
    assert tools.parse_marker("Blender 5.2 started") is None


# --------------------------------------------------------------------------- CLI argument handling

def run_cli(func, argv, capsys):
    code = func(argv)
    out, err = capsys.readouterr()
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    return code, lines, err


def test_build_requires_slugs_or_all(capsys):
    code, lines, err = run_cli(cli.build_main, [], capsys)
    assert code == 2 and "--all" in err
    assert lines[-1]["result"]["ok"] is False


def test_build_rejects_unknown_slug(capsys):
    code, lines, err = run_cli(cli.build_main, ["nobody"], capsys)
    assert code == 2 and "unknown avatar" in err
    assert "rowan" in lines[-1]["result"]["error"]


def test_build_rejects_slugs_with_all(capsys):
    code, _, err = run_cli(cli.build_main, ["rowan", "--all"], capsys)
    assert code == 2 and "not both" in err


def test_build_bad_option(capsys):
    code = cli.build_main(["--frobnicate"])
    assert code == 2


def test_help_exits_zero(capsys):
    assert cli.build_main(["--help"]) == 0
    assert "usage" in capsys.readouterr().out


def test_resolve_slugs_all():
    assert cli.resolve_slugs([], True) == SLUGS


def test_setup_with_missing_packs_dir(tmp_path, capsys):
    code, lines, _ = run_cli(cli.setup_main, ["--packs-dir", str(tmp_path / "missing"), "--no-verify"], capsys)
    assert code == 1
    assert all(validate_line(json.dumps(line)) for line in lines)
    assert "is not a folder" in lines[-1]["result"]["error"]


def test_check_prints_tool_report(capsys, monkeypatch):
    monkeypatch.setattr(tools, "find_blender", lambda explicit=None: None)
    assert cli.check_main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) >= {"python", "blender", "mpfb", "packs", "profile", "ready"}
    assert report["python"]["ok"] is True
    assert report["blender"]["ok"] is False and report["ready"] is False


# --------------------------------------------------------------------------- tools

def test_windows_path_conversion_under_wsl(monkeypatch):
    monkeypatch.setattr(tools, "is_wsl", lambda: True)
    mount = "/mnt/" + "e"  # built up so the text holds no machine path
    converted = tools.to_tool_path(mount + "/kit/avatars/x.glb", "blender.exe")
    assert converted == "E:\\kit\\avatars\\x.glb"
    assert tools.to_tool_path(mount + "/kit", "blender") == str(Path(mount + "/kit").resolve())
    assert tools.from_windows_path("D:\\tools\\blender.exe") == "/mnt/" + "d/tools/blender.exe"


# --------------------------------------------------------------------------- GLB checks and manifest

def make_glb(path, *, joints=GAME_ENGINE_BONES, body_targets=FACE, extra_material=None, height=1.9,
             weights=(0.5, 0.25, 0.25, 0.0), default_weight=0.0, clothes=("top", "bottom", "shoes")):
    """Write a small skinned GLB with the structure of a kit avatar (two vertices per mesh)."""
    bin_data = bytearray()
    accessors, views = [], []

    def add(values, fmt, kind, minmax=False):
        offset = len(bin_data)
        for row in values:
            bin_data.extend(struct.pack("<" + fmt * len(row), *row))
        while len(bin_data) % 4:
            bin_data.append(0)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(bin_data) - offset})
        acc = {"bufferView": len(views) - 1, "componentType": 5126 if fmt == "f" else 5121,
               "count": len(values), "type": kind}
        if minmax:
            acc["min"] = [min(r[i] for r in values) for i in range(3)]
            acc["max"] = [max(r[i] for r in values) for i in range(3)]
        accessors.append(acc)
        return len(accessors) - 1

    nodes = [{"name": name} for name in joints]
    meshes, materials = [], []
    mesh_specs = [("Body", "skin", list(body_targets))] + [
        (name.capitalize(), name, []) for name in BASE_MATERIALS if name != "skin"] + [
        (slot.capitalize(), slot, []) for slot in clothes]
    if extra_material:
        mesh_specs.append(("Extra", extra_material, []))
    for name, material, targets in mesh_specs:
        pos = add([(0.0, 0.0, 0.0), (0.1, height, 0.05)], "f", "VEC3", minmax=True)
        jnt = add([(0, 1, 2, 3)] * 2, "B", "VEC4")
        wts = add([weights] * 2, "f", "VEC4")
        materials.append({"name": material, "alphaMode": {"eyebrows": "BLEND", "eyelashes": "BLEND",
                                                           "hair": "MASK"}.get(material, "OPAQUE")})
        prim = {"attributes": {"POSITION": pos, "JOINTS_0": jnt, "WEIGHTS_0": wts},
                "material": len(materials) - 1}
        mesh = {"name": name, "primitives": [prim]}
        if targets:
            prim["targets"] = [{"POSITION": pos} for _ in targets]
            mesh["extras"] = {"targetNames": targets}
            mesh["weights"] = [default_weight] * len(targets)
        meshes.append(mesh)
        nodes.append({"name": name, "mesh": len(meshes) - 1, "skin": 0})
    gltf = {"asset": {"version": "2.0"}, "nodes": nodes, "meshes": meshes, "materials": materials,
            "skins": [{"joints": list(range(len(joints)))}], "accessors": accessors,
            "bufferViews": views, "buffers": [{"byteLength": len(bin_data)}], "images": []}
    body = json.dumps(gltf).encode()
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body) + 8 + len(bin_data)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(body), 0x4E4F534A)
                     + body + struct.pack("<II", len(bin_data), 0x004E4942) + bytes(bin_data))
    return path


def failed(result):
    return {c["check"] for c in result["checks"] if not c["ok"]}


def test_static_checks_pass_for_a_complete_avatar(tmp_path):
    result = static_checks(make_glb(tmp_path / "rowan.glb"), real_spec())
    assert result["ok"], result["failures"]
    assert len(result["info"]["bones"]) == 53


@pytest.mark.parametrize("kwargs, check", [
    ({"joints": GAME_ENGINE_BONES[:-1]}, "skeleton"),
    ({"body_targets": FACE[:-1]}, "morph_targets"),
    ({"body_targets": FACE + ("smirk",)}, "morph_names"),
    ({"height": 1.2}, "height"),
    ({"weights": (0.5, 0.2, 0.0, 0.0)}, "skin_weights"),
    ({"default_weight": 1.0}, "morph_defaults"),
])
def test_static_checks_catch_problems(tmp_path, kwargs, check):
    result = static_checks(make_glb(tmp_path / "rowan.glb", **kwargs), real_spec())
    assert check in failed(result)


def test_static_checks_file_size_and_materials(tmp_path):
    spec = copy.deepcopy(real_spec())
    spec["checks"]["max_bytes"] = 100
    spec["clothes"].append({"asset": "fedora01", "slot": "hat"})
    result = static_checks(make_glb(tmp_path / "rowan.glb"), spec)
    assert {"file_size", "materials"} <= failed(result)


def test_static_checks_reject_non_glb(tmp_path):
    path = tmp_path / "x.glb"
    path.write_bytes(b"not a glb at all, just text")
    result = static_checks(path, real_spec())
    assert not result["ok"] and "glb" in failed(result)
    with pytest.raises(GlbError):
        Glb(b"short")


def test_manifest_contents(tmp_path):
    glb = make_glb(tmp_path / "rowan.glb")
    build = {"versions": {"blender": "5.2.2", "mpfb": "2.0.17", "gltf_exporter": "5.2.40"},
             "height_m": 1.9, "weight_fixes": {"thumb_base_l": 40}}
    install = {"packs": {k: {"sha256": "0" * 64} for k in PACKS}}
    manifest = build_manifest(real_spec(), glb, build=build, install=install)
    assert manifest["license"] == "CC-BY-4.0"
    assert manifest["credit"] == "talking-avatar-kit by Ghazanfar Ali"
    assert manifest["bytes"] == glb.stat().st_size and len(manifest["sha256"]) == 64
    assert manifest["rig"]["bone_count"] == 53 and manifest["rig"]["bones"][0] == "Root"
    assert manifest["morph_targets"]["arkit"] == list(ARKIT)
    assert manifest["morph_targets"]["visemes"] == list(VISEMES)
    assert manifest["morph_targets"]["count"] == 67
    assert {m["slot"] for m in manifest["materials"]} >= set(BASE_MATERIALS) | {"top", "bottom", "shoes"}
    assert manifest["generator"]["mpfb"] == "2.0.17"
    assert set(manifest["generator"]["makehuman_packs_sha256"]) == set(PACKS)
    assert manifest["preview"] == "preview.png"
    text = json.dumps(manifest)
    assert str(tmp_path) not in text


@pytest.mark.parametrize("slug", SLUGS)
def test_shipped_manifests_match_their_glbs(slug):
    import hashlib
    folder = AVATARS_DIR / slug
    if not (folder / "manifest.json").is_file():
        pytest.skip("avatars not built")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    data = (folder / manifest["file"]).read_bytes()
    assert manifest["sha256"] == hashlib.sha256(data).hexdigest()
    assert manifest["bytes"] == len(data)
    assert static_checks(folder / manifest["file"], load_spec(folder / "spec.json"))["ok"]


@pytest.mark.parametrize("slug", SLUGS)
def test_shipped_manifest_credits_follow_the_spec(slug):
    """Every CC BY part is credited in the manifest exactly as its spec words it."""
    from tak.pipeline.manifest import attribution
    from tak.pipeline.spec import credits, pack_license
    spec = real_spec(slug)
    manifest = json.loads((AVATARS_DIR / slug / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["license"] == "CC-BY-4.0" and manifest["credit"] == "talking-avatar-kit by Ghazanfar Ali"
    assert manifest["credits"] == credits(spec)
    assert manifest["attribution"] == attribution(spec)
    assert manifest["outfit"] == [c["asset"] for c in spec["clothes"]]
    for line in manifest["credits"]:
        assert line in manifest["attribution"] and line.endswith("CC BY")
    parts = manifest["source_assets"]["parts"]
    cc_by = [p for p in parts if str(p["license"]).startswith("CC-BY")]
    for part in cc_by:
        assert part.get("credit") in manifest["credits"], part
        assert part["author"] and part["author"] in part["credit"]
        assert pack_license(part["pack"]) == "CC-BY"
    assert ("credited_community_assets" in manifest["licenses"]) == bool(cc_by)
    if not cc_by:
        assert manifest["credits"] == []


def test_manifest_credits_for_cc_by_parts(tmp_path):
    spec = real_spec("elena")
    glb = make_glb(tmp_path / "elena.glb")
    parts = {"hair": {"pack": "hair02", "author": "Elvaerwyn", "license": "CC-BY"},
             "top": {"pack": "shirts02", "author": "Mindfront", "license": "CC-BY"}}
    manifest = build_manifest(spec, glb, parts=parts)
    assert manifest["credits"] == [c["credit"] for c in spec["clothes"] if "credit" in c] + [spec["hair"]["credit"]]
    assert manifest["attribution"].startswith("Elena avatar, talking-avatar-kit by Ghazanfar Ali, licensed under "
                                              "CC BY 4.0. Built with MPFB from CC0 MakeHuman assets. skirt ")
    assert manifest["attribution"].endswith("(MakeHuman community, hair02), CC BY.")
    by_part = {p["part"]: p for p in manifest["source_assets"]["parts"]}
    assert by_part["top"]["author"] == "Mindfront" and by_part["top"]["credit"].startswith("sweater")
    assert by_part["bottom"]["license"] == "CC-BY"  # from the pack table when no metadata is given
    assert by_part["skin"]["license"] == "CC0" and by_part["skin"]["pack"] == "makehuman_system_assets"
    assert manifest["persona"] == spec["persona"]


# --------------------------------------------------------------------------- setup (offline)

def test_pack_install_and_idempotence(tmp_path):
    archive = tmp_path / "visemes02.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("packs/visemes02.json", "{}")
        zf.writestr("targets/visemes/viseme_aa.target", "# empty")
    profile = tmp_path / "profile"
    warnings = []
    first = tak_setup.install_pack("visemes02", archive, profile, {}, warnings)
    data = tak_setup.user_data_dir(profile)
    assert (data / "targets" / "visemes" / "viseme_aa.target").is_file()
    assert first["pack_json"] == "visemes02" and not first["skipped"]
    assert warnings and "differs from the reference" in warnings[0]
    again = tak_setup.install_pack("visemes02", archive, profile, {"packs": {"visemes02": first}}, [])
    assert again["skipped"]


def test_pack_without_manifest_is_rejected(tmp_path):
    archive = tmp_path / "faceunits01.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "no pack json")
    with pytest.raises(tak_setup.SetupError, match="not an MPFB asset pack"):
        tak_setup.install_pack("faceunits01", archive, tmp_path / "p", {}, [])


def test_archive_path_traversal_is_rejected(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("packs/x.json", "{}")
        zf.writestr("../../outside.txt", "nope")
    with zipfile.ZipFile(archive) as zf, pytest.raises(tak_setup.SetupError, match="unsafe path"):
        tak_setup._safe_extract(zf, zf.infolist(), tmp_path / "target")


def test_mpfb_archive_layout_is_checked(tmp_path):
    archive = tmp_path / "mpfb2-v2.0.17.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("something/else.txt", "x")
    with pytest.raises(tak_setup.SetupError, match="does not contain"):
        tak_setup.install_mpfb(archive, tmp_path / "profile", {}, [])


def test_locate_archive_prefers_packs_dir(tmp_path):
    (tmp_path / "visemes02.zip").write_bytes(b"zip")
    found = tak_setup.locate_archive("visemes02.zip", "https://invalid.example/none.zip", tmp_path, None,
                                     lambda m, p: None)
    assert found == tmp_path / "visemes02.zip"
