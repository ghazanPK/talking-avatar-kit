"""Studio settings and tool discovery (no network, no Blender)."""
import json
import sys
from pathlib import Path, PurePosixPath

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tak import platform as tp  # noqa: E402
from tak import settings as ts  # noqa: E402


# --------------------------------------------------------------------------- settings

def test_config_dir_xdg_and_appdata(tmp_path):
    assert ts.config_dir({"XDG_CONFIG_HOME": str(tmp_path)}, "posix") == tmp_path / "talking-avatar-kit"
    assert ts.config_dir({"APPDATA": str(tmp_path)}, "nt") == tmp_path / "talking-avatar-kit"
    assert ts.config_dir({"TAK_CONFIG_DIR": str(tmp_path), "XDG_CONFIG_HOME": "x"}, "posix") == tmp_path
    assert ts.settings_path({"XDG_CONFIG_HOME": str(tmp_path)}, "posix").name == "settings.json"


def test_load_defaults_save_and_merge(tmp_path):
    path = tmp_path / "cfg" / "settings.json"
    assert ts.load(path) == ts.DEFAULTS
    saved = ts.save({"blender_path": "  /opt/blender/blender ", "extra_avatar_dirs": "a\n\n b \n"}, path)
    assert saved["blender_path"] == "/opt/blender/blender"
    assert saved["extra_avatar_dirs"] == ["a", "b"]
    ts.save({"packs_dir": "packs"}, path)
    data = json.loads(path.read_text())
    assert data["blender_path"] == "/opt/blender/blender" and data["packs_dir"] == "packs"
    assert ts.load(path)["mpfb_profile_dir"] == ""


@pytest.mark.parametrize("bad", [{"unknown": 1}, {"blender_path": 3}, {"extra_avatar_dirs": [1]}, {"packs_dir": "a\x00b"}, []])
def test_validate_rejects(bad):
    with pytest.raises(ts.SettingsError):
        ts.validate(bad)


def test_corrupt_or_partial_file_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert ts.load(path) == ts.DEFAULTS
    path.write_text(json.dumps({"blender_path": 5, "packs_dir": "p", "other": True}))
    loaded = ts.load(path)
    assert loaded["blender_path"] == "" and loaded["packs_dir"] == "p" and "other" not in loaded


# --------------------------------------------------------------------------- platform

def test_is_wsl_from_proc_version():
    assert tp.is_wsl("Linux version 6.6.87.2-microsoft-standard-WSL2")
    assert not tp.is_wsl("Linux version 6.8.0-45-generic (buildd@lcy02)")


# Mounted-drive paths are assembled at run time so the source holds no machine-path literals.
MNT = "/mnt"


def test_path_conversion_with_and_without_wslpath(tmp_path):
    assert tp.to_windows_path(f"{MNT}/d/Tools/blender.exe", runner=lambda flag, p: None) == "D:\\Tools\\blender.exe"
    assert tp.to_windows_path("Q:\\already\\windows") == "Q:\\already\\windows"
    calls = []
    fake = lambda flag, p: calls.append((flag, p)) or "\\\\wsl$\\distro" + p.replace("/", "\\")
    out = tp.to_windows_path(tmp_path / "not" / "yet.glb", runner=fake)
    assert calls == [("-w", str(tmp_path))]
    assert out.endswith("\\not\\yet.glb")
    assert tp.to_wsl_path("C:\\Tools\\Blender", runner=lambda flag, p: None) == f"{MNT}/c/Tools/Blender"
    assert tp.to_wsl_path("relative/path") == "relative/path"


def test_convert_args_only_for_windows_exe_under_wsl(monkeypatch):
    monkeypatch.setattr(tp, "to_windows_path", lambda p: "WIN:" + str(p))
    args = ["--background", PurePosixPath("/data/in.blend"), "--", "x"]
    assert tp.convert_args("blender.exe", args, wsl=True) == ["--background", "WIN:/data/in.blend", "--", "x"]
    assert tp.convert_args("blender", args, wsl=True) == ["--background", "/data/in.blend", "--", "x"]
    assert tp.convert_args("blender.exe", args, wsl=False)[1] == "/data/in.blend"
    assert tp.tool_path("Blender.EXE", "/a/b", wsl=True) == "WIN:/a/b"


def _candidates(**kw):
    defaults = dict(settings={}, env={}, which=lambda name: None, wsl=False, os_name="posix",
                    sys_platform="linux", get_windows_env=lambda name: None, globber=lambda pattern: [],
                    exists=lambda path: False)
    defaults.update(kw)
    return tp.blender_candidates(**defaults)


def test_discovery_order_settings_env_path():
    found = _candidates(settings={"blender_path": "/s/blender"}, env={"BLENDER": "/e/blender"},
                        which=lambda name: "/usr/bin/blender" if name == "blender" else None,
                        exists=lambda p: p != "/s/blender")
    assert [(c["source"], c["path"]) for c in found] == [("settings", "/s/blender"), ("env:BLENDER", "/e/blender"), ("PATH", "/usr/bin/blender")]
    assert [c["exists"] for c in found] == [False, True, True]


def test_find_blender_returns_first_existing(monkeypatch):
    monkeypatch.setattr(tp, "blender_candidates", lambda settings=None, **kw: [
        {"path": "a", "source": "settings", "exists": False}, {"path": "b", "source": "PATH", "exists": True}])
    assert tp.find_blender({})["path"] == "b"
    monkeypatch.setattr(tp, "blender_candidates", lambda settings=None, **kw: [])
    assert tp.find_blender({}) is None


def test_windows_standard_folders_from_environment():
    env = {"ProgramFiles": "PF", "ProgramFiles(x86)": "PF86", "LOCALAPPDATA": "LA"}
    globbed = {
        str(Path("PF", "Blender Foundation", "Blender*", "blender.exe")): [
            str(Path("PF", "Blender Foundation", "Blender 4.2", "blender.exe")),
            str(Path("PF", "Blender Foundation", "Blender 4.10", "blender.exe"))],
        str(Path("LA", "Programs", "Blender Foundation", "Blender*", "blender.exe")): [
            str(Path("LA", "Programs", "Blender Foundation", "Blender 5.0", "blender.exe"))],
    }
    found = _candidates(os_name="nt", get_windows_env=env.get, globber=lambda pattern: globbed.get(pattern, []))
    paths = [c["path"] for c in found]
    assert paths.index(str(Path("PF", "Blender Foundation", "Blender 4.10", "blender.exe"))) < \
        paths.index(str(Path("PF", "Blender Foundation", "Blender 4.2", "blender.exe")))
    assert str(Path("PF86", "Steam", "steamapps", "common", "Blender", "blender.exe")) in paths
    assert str(Path("LA", "Programs", "Blender Foundation", "Blender 5.0", "blender.exe")) in paths
    assert all(c["source"] == "standard" for c in found)


def test_wsl_converts_windows_settings_path_and_dedupes(monkeypatch):
    monkeypatch.setattr(tp, "_run_wslpath", lambda flag, p: None)
    found = _candidates(wsl=True, settings={"blender_path": "E:/Apps/Blender/blender.exe"},
                        env={"BLENDER": f"{MNT}/e/Apps/Blender/blender.exe"})
    assert found[0]["path"] == f"{MNT}/e/Apps/Blender/blender.exe"
    assert len([c for c in found if c["path"] == found[0]["path"]]) == 1


def test_macos_application_folder():
    found = _candidates(sys_platform="darwin", env={"HOME": "/home-dir"})
    assert any(c["path"].endswith("Blender.app/Contents/MacOS/Blender") for c in found)


def test_parse_blender_version():
    assert tp.parse_blender_version("Blender 4.2.3 LTS\n\tbuild date: ...") == "4.2.3"
    assert tp.parse_blender_version("Blender 5.2\n") == "5.2"
    assert tp.parse_blender_version("nothing") is None
