"""Local Studio server: static files from ``studio/`` plus a small JSON API.

Standard library only. Binds to 127.0.0.1; requests with a foreign Host
header are refused, and state-changing requests must send JSON, so other web
pages cannot drive the API.

API (all JSON):

* ``GET  /api/avatars``            avatars from ``avatars/*/`` and extra folders
* ``GET  /api/check``              ``python -m tak check`` output plus Studio discovery
* ``GET  /api/settings``           settings, defaults and file location
* ``PUT  /api/settings``           update settings (partial object)
* ``GET  /api/jobs``               job summaries, newest first
* ``POST /api/jobs``               ``{"kind": "build", "slug": ...}`` (also ``"all": true``),
                                   ``{"kind": "setup"}``, ``{"kind": "check"}``
* ``GET  /api/jobs/<id>?offset=N`` job status and log lines from ``N``
* ``POST /api/jobs/<id>/cancel``   cancel (also ``DELETE /api/jobs/<id>``)
* ``GET  /api/renders``            saved render sets under ``build/renders/``
* ``POST /api/renders``            ``{"slug", "label", "name", "data_url"}`` (PNG) or ``"json"``
* ``GET  /api/speech/status``      optional Kokoro speech: installed, languages, setup command
* ``GET  /api/speech/voices``      Kokoro voices
* ``POST /api/speech/say``         ``{"text", "voice", "speed"}`` -> audio URL and timeline
* ``GET  /api/speech/audio/<id>.wav`` synthesised clip (cached in ``.tak/cache/speech``)

Files: ``/avatars/...`` (repository avatars), ``/extra/<n>/...`` (extra avatar
folder ``n`` from the settings), ``/renders/...`` (``build/renders``).
"""

from __future__ import annotations

import base64
import binascii
import importlib.util
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__
from . import platform as tak_platform
from . import settings as tak_settings
from .jobs import JobRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8750
MAX_BODY = 64 * 1024 * 1024
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PNG_PREFIX = "data:image/png;base64,"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CHECK_TIMEOUT = 180

MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".hdr": "application/octet-stream",
    ".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
    ".ico": "image/x-icon", ".webp": "image/webp",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Helpers (pure functions, unit tested)

def safe_join(base: Path, *parts: str) -> Path | None:
    """Join ``parts`` under ``base``; None if the result escapes ``base``."""
    base = Path(base).resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def render_target(renders_dir: Path, slug: str, label: str, name: str, ext: str = ".png") -> Path:
    """Validated output path ``renders_dir/slug/label/name.ext``."""
    for field_name, value in (("slug", slug), ("label", label), ("name", name)):
        if not isinstance(value, str) or not SEGMENT.match(value) or ".." in value:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"invalid {field_name}: use letters, digits, '.', '_' or '-'")
    if name.lower().endswith(ext):
        name = name[: -len(ext)]
    target = safe_join(renders_dir, slug, label, name + ext)
    if target is None:
        raise ApiError(HTTPStatus.BAD_REQUEST, "path escapes the render folder")
    return target


def decode_png_data_url(data_url: Any) -> bytes:
    if not isinstance(data_url, str) or not data_url.startswith(PNG_PREFIX):
        raise ApiError(HTTPStatus.BAD_REQUEST, "data_url must be a data:image/png;base64 URL")
    try:
        data = base64.b64decode(data_url[len(PNG_PREFIX):], validate=True)
    except (binascii.Error, ValueError):
        raise ApiError(HTTPStatus.BAD_REQUEST, "data_url is not valid base64") from None
    if not data.startswith(PNG_MAGIC):
        raise ApiError(HTTPStatus.BAD_REQUEST, "data_url does not contain a PNG image")
    return data


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: {exc}"


def _avatar_entry(folder: Path, url_prefix: str, source: str, root_label: str) -> dict | None:
    """Describe ``folder`` (``<slug>/`` with manifest and/or ``<slug>.glb``)."""
    slug = folder.name
    manifest, error = _read_json(folder / "manifest.json")
    if manifest is not None and not isinstance(manifest, dict):
        manifest, error = None, "manifest.json is not a JSON object"
    glb_name = None
    if isinstance(manifest, dict):
        for key in ("file", "glb", "path"):
            value = manifest.get(key)
            if isinstance(value, str) and value.lower().endswith(".glb") and "/" not in value and "\\" not in value:
                glb_name = value
                break
    if glb_name is None or not (folder / glb_name).is_file():
        glb_name = f"{slug}.glb" if (folder / f"{slug}.glb").is_file() else None
    if glb_name is None:
        others = sorted(p.name for p in folder.glob("*.glb"))
        glb_name = others[0] if others else None
    has_spec = (folder / "spec.json").is_file()
    if manifest is None and glb_name is None and error is None and not has_spec:
        return None
    preview = None
    for candidate in ([manifest.get("preview")] if isinstance(manifest, dict) else []) + ["preview.png"]:
        if isinstance(candidate, str) and SEGMENT.match(candidate) and (folder / candidate).is_file():
            preview = candidate
            break
    glb_path = folder / glb_name if glb_name else None
    return {
        "id": f"{source}/{slug}",
        "slug": slug,
        "name": (manifest or {}).get("name") or slug.replace("-", " ").replace("_", " ").title(),
        "source": source,
        "location": root_label,
        "glb_url": f"{url_prefix}/{slug}/{glb_name}" if glb_name else None,
        "bytes": glb_path.stat().st_size if glb_path else None,
        "preview_url": f"{url_prefix}/{slug}/{preview}" if preview else None,
        "manifest": manifest,
        "manifest_error": error,
        "has_spec": has_spec,
    }


def scan_avatars(repo_root: Path, extra_dirs: list[str] | None = None) -> list[dict]:
    """Avatars in ``repo_root/avatars`` and each extra folder; tolerates anything missing."""
    found: list[dict] = []
    avatars = repo_root / "avatars"
    if avatars.is_dir():
        for folder in sorted(p for p in avatars.iterdir() if p.is_dir() and SLUG.match(p.name)):
            entry = _avatar_entry(folder, "/avatars", "avatars", "avatars")
            if entry:
                found.append(entry)
    for index, raw in enumerate(extra_dirs or []):
        root = Path(raw).expanduser()
        if not root.is_absolute():
            root = repo_root / root
        if not root.is_dir():
            continue
        source, prefix = f"extra{index}", f"/extra/{index}"
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and SEGMENT.match(p.name)):
            entry = _avatar_entry(folder, prefix, source, raw)
            if entry:
                found.append(entry)
        for glb in sorted(p for p in root.glob("*.glb") if SEGMENT.match(p.name)):
            found.append({
                "id": f"{source}/{glb.stem}", "slug": glb.stem,
                "name": glb.stem.replace("-", " ").replace("_", " ").title(),
                "source": source, "location": raw, "glb_url": f"{prefix}/{glb.name}",
                "bytes": glb.stat().st_size, "preview_url": None, "manifest": None,
                "manifest_error": None, "has_spec": False,
            })
    return found


def scan_renders(renders_dir: Path) -> list[dict]:
    sets = []
    if not renders_dir.is_dir():
        return sets
    for slug_dir in sorted(p for p in renders_dir.iterdir() if p.is_dir()):
        for label_dir in sorted(p for p in slug_dir.iterdir() if p.is_dir()):
            files = sorted(p.name for p in label_dir.iterdir() if p.suffix.lower() in (".png", ".json"))
            index, _ = _read_json(label_dir / "index.json")
            sets.append({
                "slug": slug_dir.name, "label": label_dir.name,
                "url": f"/renders/{slug_dir.name}/{label_dir.name}/",
                "files": files, "index": index if isinstance(index, dict) else None,
                "modified": max((p.stat().st_mtime for p in label_dir.iterdir()), default=None),
            })
    return sets


def pipeline_available() -> bool:
    try:
        return importlib.util.find_spec("tak.pipeline.cli") is not None
    except (ImportError, ValueError):
        return False


def parse_check_output(text: str) -> Any:
    """Whole stdout as JSON, else the last JSON object line."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Server

class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, repo_root: Path = REPO_ROOT, settings_file: Path | None = None,
                 studio_dir: Path | None = None, python: str | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.studio_dir = Path(studio_dir).resolve() if studio_dir else self.repo_root / "studio"
        self.renders_dir = self.repo_root / "build" / "renders"
        self.settings_file = Path(settings_file) if settings_file else tak_settings.settings_path()
        self.python = python or sys.executable
        self.runner = JobRunner()
        self._check_lock = threading.Lock()
        self._speech = None
        self._speech_lock = threading.Lock()
        super().__init__(address, StudioHandler)

    # speech (optional Kokoro, see tak/speech) ---------------------------------
    @property
    def speech(self):
        with self._speech_lock:
            if self._speech is None:
                from .speech.service import SpeechService
                self._speech = SpeechService(self.repo_root)
            return self._speech

    @speech.setter
    def speech(self, service) -> None:
        self._speech = service

    def close_speech(self) -> None:
        if self._speech is not None:
            self._speech.close()

    # settings ---------------------------------------------------------------
    def load_settings(self) -> dict:
        return tak_settings.load(self.settings_file)

    def extra_dir(self, index: int) -> Path | None:
        dirs = self.load_settings().get("extra_avatar_dirs") or []
        if not 0 <= index < len(dirs):
            return None
        root = Path(dirs[index]).expanduser()
        return root if root.is_absolute() else self.repo_root / root

    # subprocesses -------------------------------------------------------------
    def tool_env(self) -> dict:
        """Environment for pipeline subprocesses: the configured Blender becomes BLENDER."""
        env = {"TAK_CONFIG_DIR": str(self.settings_file.parent)}
        blender = tak_platform.find_blender(self.load_settings())
        if blender and blender["source"] == "settings":
            env["BLENDER"] = blender["path"]
        return env

    def job_command(self, payload: dict) -> tuple[str, list[str], dict]:
        kind = payload.get("kind")
        base = [self.python, "-m", "tak"]
        if kind == "build":
            if payload.get("all") is True:
                return kind, base + ["build", "--all"], {"all": True}
            slug = payload.get("slug")
            if not isinstance(slug, str) or not SLUG.match(slug):
                raise ApiError(HTTPStatus.BAD_REQUEST, "build needs a slug (lowercase letters, digits, '-', '_') or all=true")
            return kind, base + ["build", slug], {"slug": slug}
        if kind == "setup":
            settings = self.load_settings()
            args = ["setup"]
            blender = tak_platform.find_blender(settings)
            if blender:
                args += ["--blender", blender["path"]]
            if settings.get("packs_dir"):
                args += ["--packs-dir", settings["packs_dir"]]
            return kind, base + args, {}
        if kind == "check":
            return kind, base + ["check"], {}
        raise ApiError(HTTPStatus.BAD_REQUEST, "kind must be 'build', 'setup' or 'check'")

    def run_check(self) -> dict:
        settings = self.load_settings()
        studio = tak_platform.describe(settings)
        studio["settings_file"] = str(self.settings_file)
        report: dict[str, Any] = {"studio": studio, "pipeline_available": pipeline_available()}
        if not report["pipeline_available"]:
            report["check"] = None
            report["message"] = "The avatar pipeline (tak.pipeline) is not installed in this checkout; only Studio discovery is shown."
            return report
        env = dict(os.environ)
        env.update(self.tool_env())
        with self._check_lock:
            try:
                out = subprocess.run([self.python, "-m", "tak", "check"], cwd=str(self.repo_root), env=env,
                                     capture_output=True, text=True, timeout=CHECK_TIMEOUT,
                                     stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                report.update(check=None, message=f"`python -m tak check` timed out after {CHECK_TIMEOUT} s")
                return report
            except OSError as exc:
                report.update(check=None, message=f"`python -m tak check` could not start: {exc}")
                return report
        report["check"] = parse_check_output(out.stdout)
        report["returncode"] = out.returncode
        if out.stderr.strip():
            report["stderr"] = out.stderr.strip()[-4000:]
        if report["check"] is None:
            report["message"] = "`python -m tak check` printed no JSON"
        return report


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer
    server_version = f"tak-studio/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        if os.environ.get("TAK_STUDIO_VERBOSE"):
            super().log_message(fmt, *args)

    # dispatch -----------------------------------------------------------------
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            if not self._host_allowed():
                raise ApiError(HTTPStatus.FORBIDDEN, "host not allowed")
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = parse_qs(url.query)
            if path.startswith("/api/"):
                self._api(method, path[len("/api/"):].strip("/"), query)
            elif method in ("GET", "HEAD"):
                self._static(path, head=method == "HEAD")
            else:
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
        except ApiError as exc:
            self._json({"error": exc.message}, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # pragma: no cover - last resort
            try:
                self._json({"error": f"internal error: {exc.__class__.__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except OSError:
                pass

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return True
        name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        return name in ("127.0.0.1", "localhost", "[::1]")

    # responses --------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str, head: bool = False, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data, indent=None, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> Any:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send Content-Type: application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(HTTPStatus.BAD_REQUEST, "bad Content-Length") from None
        if length <= 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "empty body")
        if length > MAX_BODY:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(HTTPStatus.BAD_REQUEST, "body is not valid JSON") from None

    # static files -----------------------------------------------------------
    def _static(self, path: str, head: bool = False) -> None:
        srv = self.server
        parts = [p for p in path.split("/") if p]
        if any(p in ("..", ".") or "\\" in p or ":" in p for p in parts):
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        if parts[:1] == ["avatars"]:
            base, rest = srv.repo_root / "avatars", parts[1:]
        elif parts[:1] == ["renders"]:
            base, rest = srv.renders_dir, parts[1:]
        elif parts[:1] == ["extra"] and len(parts) >= 2 and parts[1].isdigit():
            base, rest = srv.extra_dir(int(parts[1])), parts[2:]
            if base is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        else:
            base, rest = srv.studio_dir, parts or ["index.html"]
        if not rest:
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        target = safe_join(base, *rest)
        if target is not None and target.is_dir():
            target = target / "index.html"
        if target is None or not target.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        ctype = MIME.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, target.read_bytes(), ctype, head=head)

    # API ----------------------------------------------------------------------
    def _api(self, method: str, route: str, query: dict) -> None:
        srv = self.server
        parts = route.split("/") if route else []
        if parts == ["avatars"] and method == "GET":
            settings = srv.load_settings()
            self._json({"avatars": scan_avatars(srv.repo_root, settings.get("extra_avatar_dirs"))})
        elif parts == ["check"] and method == "GET":
            self._json(srv.run_check())
        elif parts == ["settings"] and method == "GET":
            self._json(self._settings_payload())
        elif parts == ["settings"] and method == "PUT":
            try:
                tak_settings.save(self._body(), srv.settings_file)
            except tak_settings.SettingsError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from None
            self._json(self._settings_payload())
        elif parts == ["jobs"] and method == "GET":
            self._json({"jobs": srv.runner.list()})
        elif parts == ["jobs"] and method == "POST":
            payload = self._body()
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "expected a JSON object")
            kind, command, params = srv.job_command(payload)
            job = srv.runner.submit(kind, command, params=params, cwd=str(srv.repo_root), env=srv.tool_env())
            data = job.summary()
            if not pipeline_available():
                data["warning"] = "tak.pipeline is not installed; the job will report that and stop"
            self._json(data, HTTPStatus.ACCEPTED)
        elif len(parts) == 2 and parts[0] == "jobs" and method == "GET":
            job = srv.runner.get(parts[1])
            if job is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "no such job")
            try:
                offset = max(0, int((query.get("offset") or ["0"])[0]))
            except ValueError:
                raise ApiError(HTTPStatus.BAD_REQUEST, "offset must be an integer") from None
            self._json(job.detail(offset))
        elif (len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel" and method == "POST") or \
                (len(parts) == 2 and parts[0] == "jobs" and method == "DELETE"):
            job = srv.runner.get(parts[1])
            if job is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "no such job")
            if method == "POST":
                self._body_optional()
            cancelled = srv.runner.cancel(job.id)
            self._json({"cancelled": cancelled, "job": job.summary()})
        elif parts == ["renders"] and method == "GET":
            self._json({"sets": scan_renders(srv.renders_dir)})
        elif parts == ["renders"] and method == "POST":
            self._json(self._save_render(self._body()), HTTPStatus.CREATED)
        elif parts == ["info"] and method == "GET":
            self._json({"version": __version__, "pipeline_available": pipeline_available(),
                        "platform": tak_platform.platform_name()})
        elif parts[:1] == ["speech"]:
            self._speech_api(method, parts[1:])
        else:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no API route {method} /api/{route}")

    def _speech_api(self, method: str, parts: list[str]) -> None:
        from .speech.service import SpeechError
        srv = self.server
        try:
            if parts == ["status"] and method == "GET":
                self._json(srv.speech.status())
            elif parts == ["voices"] and method == "GET":
                self._json(srv.speech.voices())
            elif parts == ["say"] and method == "POST":
                payload = self._body()
                if not isinstance(payload, dict):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "expected a JSON object")
                clip = srv.speech.say(payload.get("text"), payload.get("voice"), payload.get("speed"))
                clip.pop("wav_path", None)
                self._json(clip)
            elif len(parts) == 2 and parts[0] == "audio" and method in ("GET", "HEAD"):
                path = srv.speech.audio_path(parts[1])
                if path is None:
                    raise ApiError(HTTPStatus.NOT_FOUND, "no such clip")
                self._send(HTTPStatus.OK, path.read_bytes(), "audio/wav", head=method == "HEAD")
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, f"no API route {method} /api/speech/{'/'.join(parts)}")
        except SpeechError as exc:
            raise ApiError(exc.status, str(exc)) from None

    def _body_optional(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self._body()

    def _settings_payload(self) -> dict:
        srv = self.server
        return {"settings": srv.load_settings(), "defaults": tak_settings.DEFAULTS,
                "path": str(srv.settings_file), "repo_root": str(srv.repo_root)}

    def _save_render(self, payload: Any) -> dict:
        srv = self.server
        if not isinstance(payload, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "expected a JSON object")
        if "json" in payload:
            target = render_target(srv.renders_dir, payload.get("slug"), payload.get("label"), payload.get("name"), ".json")
            data = (json.dumps(payload["json"], indent=2, sort_keys=True) + "\n").encode("utf-8")
            if len(data) > 4 * 1024 * 1024:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "JSON too large")
        else:
            target = render_target(srv.renders_dir, payload.get("slug"), payload.get("label"), payload.get("name"))
            data = decode_png_data_url(payload.get("data_url"))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        rel = target.relative_to(srv.renders_dir).as_posix()
        return {"path": f"build/renders/{rel}", "url": f"/renders/{rel}", "bytes": len(data)}


def make_server(port: int = DEFAULT_PORT, repo_root: Path = REPO_ROOT, settings_file: Path | None = None,
                python: str | None = None) -> StudioServer:
    return StudioServer(("127.0.0.1", port), repo_root=repo_root, settings_file=settings_file, python=python)


def serve(port: int = DEFAULT_PORT, open_browser: bool = True, page: str = "/", label: str = "Studio") -> int:
    try:
        server = make_server(port)
    except OSError as exc:
        print(f"Could not start the {label} on 127.0.0.1:{port}: {exc}. Try another port with --port.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}{page}"
    print(f"talking-avatar-kit {label} {__version__} running at {url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.5, _open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping the Studio.", flush=True)
    finally:
        server.runner.shutdown()
        server.close_speech()
        server.server_close()
    return 0


def _open(url: str) -> None:
    try:
        if tak_platform.is_wsl():
            # The Linux side often has no browser; hand the URL to Windows.
            for opener in (["wslview", url], ["explorer.exe", url]):
                try:
                    subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except OSError:
                    continue
        webbrowser.open(url)
    except Exception:
        pass
