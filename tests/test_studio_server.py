"""Studio HTTP server: static files, JSON API and render-save path safety."""
import base64
import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tak import __main__ as cli  # noqa: E402
from tak import server as srv  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "studio").mkdir(parents=True)
    (repo / "studio" / "index.html").write_text("<!doctype html><title>Studio</title>")
    (repo / "studio" / "js").mkdir()
    (repo / "studio" / "js" / "app.js").write_text("export {};")
    avatars = repo / "avatars"
    (avatars / "rowan").mkdir(parents=True)
    (avatars / "rowan" / "rowan.glb").write_bytes(b"glTF" + b"\x00" * 16)
    (avatars / "rowan" / "manifest.json").write_text(json.dumps({"slug": "rowan", "name": "Rowan", "file": "rowan.glb"}))
    (avatars / "rowan" / "spec.json").write_text("{}")
    (avatars / "rowan" / "preview.png").write_bytes(PNG)
    (avatars / "mira").mkdir()
    (avatars / "mira" / "mira.glb").write_bytes(b"glTF")
    (avatars / "broken").mkdir()
    (avatars / "broken" / "manifest.json").write_text("{nope")
    (avatars / "empty").mkdir()
    (avatars / "unbuilt").mkdir()
    (avatars / "unbuilt" / "spec.json").write_text("{}")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "dev.glb").write_bytes(b"glTF-dev")
    settings_file = tmp_path / "config" / "settings.json"
    settings_file.parent.mkdir()
    settings_file.write_text(json.dumps({"extra_avatar_dirs": [str(extra)]}))
    monkeypatch.setattr(srv.tak_platform, "describe", lambda settings=None, with_version=True: {"platform": "test", "blender": {"found": False, "candidates": []}})
    monkeypatch.setattr(srv.tak_platform, "find_blender", lambda settings=None, **kw: None)
    server = srv.make_server(0, repo_root=repo, settings_file=settings_file, python=sys.executable)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.runner.shutdown()
    server.server_close()


def call(server, method, path, body=None, headers=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=30)
    hdrs = dict(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=hdrs)
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    ctype = response.getheader("Content-Type") or ""
    return response.status, (json.loads(payload) if ctype.startswith("application/json") else payload), ctype


def test_binds_loopback_only(studio):
    assert studio.server_address[0] == "127.0.0.1"


def test_static_files_and_traversal(studio):
    status, body, ctype = call(studio, "GET", "/")
    assert status == 200 and b"Studio" in body and ctype.startswith("text/html")
    status, _, ctype = call(studio, "GET", "/js/app.js")
    assert status == 200 and ctype.startswith("text/javascript")
    status, body, ctype = call(studio, "GET", "/avatars/rowan/rowan.glb")
    assert status == 200 and ctype == "model/gltf-binary" and body.startswith(b"glTF")
    assert call(studio, "GET", "/extra/0/dev.glb")[1] == b"glTF-dev"
    for path in ["/../settings.json", "/avatars/../studio/index.html", "/%2e%2e/%2e%2e/etc/passwd",
                 "/extra/5/dev.glb", "/avatars/rowan/..%5c..%5cstudio%5cindex.html", "/missing.js"]:
        assert call(studio, "GET", path)[0] == 404, path


def test_foreign_host_header_rejected(studio):
    status, body, _ = call(studio, "GET", "/api/avatars", headers={"Host": "evil.example:80"})
    assert status == 403
    assert call(studio, "GET", "/api/avatars", headers={"Host": "localhost:1234"})[0] == 200


def test_avatars_scan(studio):
    status, body, _ = call(studio, "GET", "/api/avatars")
    assert status == 200
    by_id = {a["id"]: a for a in body["avatars"]}
    assert set(by_id) == {"avatars/rowan", "avatars/mira", "avatars/broken", "avatars/unbuilt", "extra0/dev"}
    assert by_id["avatars/unbuilt"]["glb_url"] is None and by_id["avatars/unbuilt"]["has_spec"]
    rowan = by_id["avatars/rowan"]
    assert rowan["glb_url"] == "/avatars/rowan/rowan.glb" and rowan["name"] == "Rowan"
    assert rowan["preview_url"] == "/avatars/rowan/preview.png" and rowan["has_spec"]
    assert by_id["avatars/mira"]["manifest"] is None and by_id["avatars/mira"]["glb_url"] == "/avatars/mira/mira.glb"
    assert by_id["avatars/broken"]["manifest_error"] and by_id["avatars/broken"]["glb_url"] is None
    assert by_id["extra0/dev"]["glb_url"] == "/extra/0/dev.glb"


def test_avatars_scan_tolerates_missing_folders(tmp_path):
    assert srv.scan_avatars(tmp_path, [str(tmp_path / "nope")]) == []


def test_settings_roundtrip(studio):
    status, body, _ = call(studio, "GET", "/api/settings")
    assert status == 200 and body["settings"]["blender_path"] == ""
    status, body, _ = call(studio, "PUT", "/api/settings", {"blender_path": "blender-custom", "packs_dir": "p"})
    assert status == 200 and body["settings"]["blender_path"] == "blender-custom"
    assert json.loads(Path(studio.settings_file).read_text())["packs_dir"] == "p"
    assert call(studio, "PUT", "/api/settings", {"nonsense": 1})[0] == 400
    assert call(studio, "PUT", "/api/settings", raw=b"blender_path=x", headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415


def test_render_save_and_listing(studio):
    status, body, _ = call(studio, "POST", "/api/renders", {"slug": "rowan", "label": "before", "name": "bind__full", "data_url": PNG_URL})
    assert status == 201 and body["path"] == "build/renders/rowan/before/bind__full.png"
    saved = Path(studio.renders_dir) / "rowan" / "before" / "bind__full.png"
    assert saved.read_bytes() == PNG
    status, body, _ = call(studio, "POST", "/api/renders", {"slug": "rowan", "label": "before", "name": "index", "json": {"poses": ["bind"]}})
    assert status == 201 and body["path"].endswith("index.json")
    status, body, _ = call(studio, "GET", "/api/renders")
    assert body["sets"][0]["label"] == "before" and body["sets"][0]["index"] == {"poses": ["bind"]}
    assert call(studio, "GET", "/renders/rowan/before/bind__full.png")[1] == PNG


@pytest.mark.parametrize("fields", [
    {"slug": "..", "label": "x", "name": "a"},
    {"slug": "rowan", "label": "../../etc", "name": "a"},
    {"slug": "rowan", "label": "x", "name": "../escape"},
    {"slug": "rowan", "label": "x", "name": "a/b"},
    {"slug": "rowan", "label": "x", "name": "a\\b"},
    {"slug": "/abs", "label": "x", "name": "a"},
    {"slug": "rowan", "label": "x", "name": ".hidden"},
    {"slug": "rowan", "label": "x", "name": ""},
    {"slug": 3, "label": "x", "name": "a"},
])
def test_render_save_rejects_unsafe_names(studio, fields):
    status, body, _ = call(studio, "POST", "/api/renders", {**fields, "data_url": PNG_URL})
    assert status == 400
    assert not any(p.is_file() for p in Path(studio.repo_root).rglob("*.png") if "renders" in p.parts)


def test_render_save_rejects_non_png(studio):
    not_png = "data:image/png;base64," + base64.b64encode(b"GIF89a....").decode()
    for data_url in [not_png, "data:image/jpeg;base64,AAAA", "data:image/png;base64,%%%", 5]:
        assert call(studio, "POST", "/api/renders", {"slug": "a", "label": "b", "name": "c", "data_url": data_url})[0] == 400


def test_render_target_helper(tmp_path):
    assert srv.render_target(tmp_path, "rowan", "after", "face.png") == (tmp_path / "rowan" / "after" / "face.png").resolve()
    with pytest.raises(srv.ApiError):
        srv.render_target(tmp_path, "rowan", "..", "x")
    assert srv.safe_join(tmp_path, "..", "x") is None


def test_jobs_api_validation(studio):
    assert call(studio, "POST", "/api/jobs", {"kind": "rm -rf"})[0] == 400
    assert call(studio, "POST", "/api/jobs", {"kind": "build", "slug": "../x"})[0] == 400
    assert call(studio, "POST", "/api/jobs", {"kind": "build"})[0] == 400
    assert call(studio, "GET", "/api/jobs/does-not-exist")[0] == 404
    assert call(studio, "GET", "/api/jobs")[1] == {"jobs": []}


def test_job_command_mapping(studio):
    kind, command, params = studio.job_command({"kind": "build", "slug": "rowan"})
    assert command[-3:] == ["tak", "build", "rowan"] and params == {"slug": "rowan"}
    assert studio.job_command({"kind": "build", "all": True})[1][-2:] == ["build", "--all"]
    assert studio.job_command({"kind": "check"})[1][-1] == "check"


def test_job_runs_and_streams(studio):
    status, job, _ = call(studio, "POST", "/api/jobs", {"kind": "check"})
    assert status == 202
    studio.runner.wait(job["id"], timeout=60)
    status, detail, _ = call(studio, "GET", f"/api/jobs/{job['id']}?offset=0")
    assert status == 200 and detail["status"] in ("succeeded", "failed")
    assert detail["command"][-2:] == ["tak", "check"]
    status, again, _ = call(studio, "GET", f"/api/jobs/{job['id']}?offset={detail['next_offset']}")
    assert again["lines"] == []
    assert call(studio, "POST", f"/api/jobs/{job['id']}/cancel", {})[1]["cancelled"] is False


def test_check_without_pipeline(studio, monkeypatch):
    monkeypatch.setattr(srv, "pipeline_available", lambda: False)
    status, body, _ = call(studio, "GET", "/api/check")
    assert status == 200 and body["pipeline_available"] is False
    assert body["check"] is None and "not installed" in body["message"]
    assert body["studio"]["platform"] == "test"


def test_parse_check_output():
    assert srv.parse_check_output('{"a": 1}') == {"a": 1}
    assert srv.parse_check_output('log line\n{"stage": "x"}\n{"ok": true}') == {"ok": True}
    assert srv.parse_check_output("") is None


def test_cli_dispatch(monkeypatch, capsys):
    assert cli.main(["--help"]) == 0
    assert cli.main(["frobnicate"]) == 2

    def missing(name):
        raise ModuleNotFoundError("No module named 'tak.pipeline.cli'", name="tak.pipeline.cli")
    monkeypatch.setattr(cli.importlib, "import_module", missing)
    assert cli.main(["check"]) == 2
    assert "avatar pipeline" in capsys.readouterr().err

    calls = []

    class Fake:
        @staticmethod
        def build_main(argv):
            calls.append(argv)
            return 0
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: Fake)
    assert cli.main(["build", "rowan", "--x"]) == 0 and calls == [["rowan", "--x"]]
    assert cli.main(["setup"]) == 2  # Fake has no setup_main
