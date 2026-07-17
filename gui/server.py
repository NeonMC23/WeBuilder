#!/usr/bin/env python3
"""Local, dependency-free backend for the WeBuilder visual editor.

The server binds to loopback by default, serves the vanilla GUI, exposes a
small JSON API, calls the existing build engine directly, and serves generated
preview files from the same origin.
"""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlsplit

ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import build as engine  # noqa: E402  (ROOT_DIR must be available first)

GUI_VERSION = "2.0.0"
MAX_JSON_BODY = 8 * 1024 * 1024
MAX_UPLOAD_BODY = 64 * 1024 * 1024
MAX_UPLOAD_FILE = 25 * 1024 * 1024
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class GUIError(RuntimeError):
    """An expected API error with an HTTP status."""

    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.status = int(status)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GUIError(f"File not found: {path}", HTTPStatus.NOT_FOUND) from exc
    except json.JSONDecodeError as exc:
        raise GUIError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise GUIError(f"Unable to read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GUIError(f"The root value in {path} must be a JSON object")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(unquote(value).replace("\\", "/").lstrip("/"))
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise GUIError("Unsafe path", HTTPStatus.BAD_REQUEST)
    return path


def _resolve_under(root: Path, relative: str) -> Path:
    safe = _safe_relative_path(relative)
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*safe.parts).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise GUIError("Unsafe path", HTTPStatus.BAD_REQUEST)
    return candidate


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@dataclass(frozen=True)
class DiscoveredPlugin:
    name: str
    path: Path
    origin: str


class GUIState:
    """Thread-safe project state shared by all HTTP request handlers."""

    def __init__(
        self,
        input_path: str | Path,
        output_dir: str | Path,
        plugin_paths: Sequence[str | Path] | None = None,
    ) -> None:
        self.input_path = Path(input_path).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.project_dir = self.input_path.parent
        self.assets_dir = self.project_dir / "assets"
        self.state_dir = self.project_dir / ".webuilder"
        self.settings_path = self.state_dir / "gui.json"
        self.backup_dir = self.state_dir / "backups"
        self._lock = threading.RLock()
        self._build_lock = threading.Lock()
        self.revision = 0
        self.last_build_success: bool | None = None
        self.last_build_time: str | None = None
        raw_plugins: Sequence[str | Path]
        if isinstance(plugin_paths, (str, Path)):
            raw_plugins = [plugin_paths]
        else:
            raw_plugins = plugin_paths or []
        self._explicit_plugins = [
            Path(path).expanduser().resolve() for path in raw_plugins
        ]
        for plugin_path in self._explicit_plugins:
            if not plugin_path.is_file():
                raise GUIError(f"Plugin file not found: {plugin_path}")
            if plugin_path.suffix.lower() != ".json" or not PLUGIN_NAME_RE.fullmatch(plugin_path.stem):
                raise GUIError(f"Invalid plugin path: {plugin_path}")
        self.enabled_plugins = self._load_enabled_plugins()

        if not self.input_path.is_file():
            raise GUIError(f"Build configuration not found: {self.input_path}")
        if self.output_dir == self.input_path or self.output_dir in self.input_path.parents:
            raise GUIError(
                "The output directory must be dedicated; it cannot be the project directory "
                "or one of its parents"
            )

    # ---------------------------- persisted state -------------------------

    def _load_enabled_plugins(self) -> list[str]:
        explicit_names = [path.stem for path in self._explicit_plugins]
        if explicit_names:
            return list(dict.fromkeys(explicit_names))
        try:
            settings = _read_json_file(self.settings_path)
        except GUIError:
            return []
        enabled = settings.get("enabled_plugins", [])
        if not isinstance(enabled, list):
            return []
        return [
            name
            for name in enabled
            if isinstance(name, str) and PLUGIN_NAME_RE.fullmatch(name)
        ]

    def _save_settings(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": GUI_VERSION,
            "enabled_plugins": self.enabled_plugins,
        }
        self._atomic_write(self.settings_path, _json_bytes(payload))

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _backup_build_file(self) -> None:
        if not self.input_path.is_file():
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        milliseconds = int((time.time() % 1) * 1000)
        backup = self.backup_dir / f"build-{timestamp}-{milliseconds:03d}.json"
        shutil.copy2(self.input_path, backup)
        backups = sorted(self.backup_dir.glob("build-*.json"), reverse=True)
        for old_backup in backups[20:]:
            old_backup.unlink(missing_ok=True)

    # ------------------------------ project -------------------------------

    def load_config(self) -> dict[str, Any]:
        with self._lock:
            return _read_json_file(self.input_path)

    @staticmethod
    def _validate_draft_config(config: Any) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise GUIError("The configuration root must be an object")
        meta = config.get("meta", {})
        if not isinstance(meta, dict):
            raise GUIError("The 'meta' field must be an object")
        assets = config.get("assets", [])
        if not isinstance(assets, list) or any(not isinstance(item, str) for item in assets):
            raise GUIError("The 'assets' field must be an array of strings")
        pages = config.get("pages")
        if not isinstance(pages, list):
            raise GUIError("The 'pages' field must be an array")
        for index, page in enumerate(pages):
            if not isinstance(page, dict):
                raise GUIError(f"Page #{index + 1} must be an object")
            if not isinstance(page.get("path"), str):
                raise GUIError(f"Page #{index + 1} must define a string 'path'")
            if not isinstance(page.get("components", []), list):
                raise GUIError(f"Page #{index + 1} components must be an array")
        return config

    def save_config(self, config: Any) -> dict[str, Any]:
        validated = self._validate_draft_config(config)
        serialized = _json_bytes(validated)
        with self._lock:
            previous = self.input_path.read_bytes() if self.input_path.exists() else b""
            if serialized != previous:
                self._backup_build_file()
                self._atomic_write(self.input_path, serialized)
        return copy.deepcopy(validated)

    # ------------------------------- plugins ------------------------------

    def discover_plugins(self) -> dict[str, DiscoveredPlugin]:
        discovered: dict[str, DiscoveredPlugin] = {}
        locations: list[tuple[Path, str]] = [
            (ROOT_DIR / "plugins", "bundled"),
            (self.project_dir / "plugins", "project"),
        ]
        for directory, origin in locations:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                if not PLUGIN_NAME_RE.fullmatch(path.stem):
                    continue
                # Project plugins override bundled examples with the same name.
                discovered[path.stem] = DiscoveredPlugin(path.stem, path.resolve(), origin)
        # Explicit CLI paths have the highest priority.
        for explicit in self._explicit_plugins:
            if explicit.is_file() and PLUGIN_NAME_RE.fullmatch(explicit.stem):
                discovered[explicit.stem] = DiscoveredPlugin(
                    explicit.stem, explicit, "command line"
                )
        return discovered

    def enabled_plugin_paths(self) -> list[Path]:
        discovered = self.discover_plugins()
        return [
            discovered[name].path
            for name in self.enabled_plugins
            if name in discovered
        ]

    def plugin_inventory(self) -> list[dict[str, Any]]:
        discovered = self.discover_plugins()
        inventory: list[dict[str, Any]] = []
        for name, plugin in sorted(discovered.items()):
            item: dict[str, Any] = {
                "name": name,
                "path": str(plugin.path),
                "origin": plugin.origin,
                "enabled": name in self.enabled_plugins,
                "valid": True,
                "version": None,
                "components": 0,
                "themes": 0,
                "shortcuts": 0,
                "error": None,
            }
            try:
                _, infos = engine.load_library_with_plugins([plugin.path])
                info = infos[0]
                item.update(
                    version=info.version,
                    components=info.component_count,
                    themes=info.theme_count,
                    shortcuts=info.shortcut_count,
                )
            except Exception as exc:  # Inventory should report, not fail entirely.
                item["valid"] = False
                item["error"] = str(exc)
            inventory.append(item)
        return inventory

    def set_enabled_plugins(self, names: Any) -> list[str]:
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise GUIError("'enabled' must be an array of plugin names")
        discovered = self.discover_plugins()
        unknown = sorted(set(names) - set(discovered))
        if unknown:
            raise GUIError(f"Unknown plugins: {', '.join(unknown)}")
        invalid = {
            item["name"]: item["error"]
            for item in self.plugin_inventory()
            if item["name"] in names and not item["valid"]
        }
        if invalid:
            raise GUIError(
                "Invalid plugins: "
                + "; ".join(f"{name}: {error}" for name, error in invalid.items())
            )
        with self._lock:
            self.enabled_plugins = list(dict.fromkeys(names))
            self._save_settings()
        return self.enabled_plugins

    # ---------------------------- library catalog -------------------------

    def merged_library(self) -> tuple[dict[str, Any], list[engine.PluginInfo]]:
        try:
            return engine.load_library_with_plugins(self.enabled_plugin_paths())
        except engine.ConfigurationError as exc:
            raise GUIError(str(exc)) from exc

    def component_catalog(self) -> list[dict[str, Any]]:
        library, _ = self.merged_library()
        catalog: list[dict[str, Any]] = []
        for type_name, definition in library.get("components", {}).items():
            if not isinstance(definition, dict):
                continue
            variants = definition.get("variants", {})
            default_variant = definition.get("default_variant")
            if not default_variant and variants:
                default_variant = next(iter(variants))
            base_required = [
                item for item in definition.get("required", []) if isinstance(item, str)
            ]
            variant_entries: list[dict[str, Any]] = []
            for variant_name, variant in variants.items():
                if not isinstance(variant, dict):
                    continue
                required = list(
                    dict.fromkeys(
                        base_required
                        + [
                            item
                            for item in variant.get("required", [])
                            if isinstance(item, str)
                        ]
                    )
                )
                defaults: dict[str, Any] = {}
                if isinstance(definition.get("defaults"), dict):
                    defaults = _deep_merge(defaults, definition["defaults"])
                if isinstance(variant.get("defaults"), dict):
                    defaults = _deep_merge(defaults, variant["defaults"])
                variant_entries.append(
                    {
                        "name": variant_name,
                        "required": required,
                        "defaults": defaults,
                        "interactive": bool(
                            str(definition.get("js", "")).strip()
                            or str(variant.get("js", "")).strip()
                        ),
                    }
                )
            namespace = type_name.split(":", 1)[0] if ":" in type_name else "core"
            catalog.append(
                {
                    "type": type_name,
                    "namespace": namespace,
                    "description": str(definition.get("description", "")),
                    "defaultVariant": default_variant,
                    "acceptsChildren": definition.get("accepts_children", True) is not False,
                    "required": base_required,
                    "defaults": copy.deepcopy(definition.get("defaults", {})),
                    "variants": variant_entries,
                }
            )
        return catalog

    def theme_catalog(self) -> list[dict[str, str]]:
        library, _ = self.merged_library()
        themes: list[dict[str, str]] = []
        for name, definition in library.get("themes", {}).items():
            if not isinstance(definition, dict):
                continue
            themes.append(
                {
                    "name": name,
                    "label": str(definition.get("label", name)),
                    "namespace": name.split(":", 1)[0] if ":" in name else "core",
                }
            )
        return themes

    # ------------------------------- assets -------------------------------

    def list_assets(self) -> list[dict[str, Any]]:
        configured = self.load_config().get("assets", [])
        configured_set = {
            item.removeprefix("assets/") for item in configured if isinstance(item, str)
        }
        assets: list[dict[str, Any]] = []
        if not self.assets_dir.is_dir():
            return assets
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
        for path in sorted(self.assets_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.assets_dir).as_posix()
            assets.append(
                {
                    "path": relative,
                    "size": path.stat().st_size,
                    "configured": relative in configured_set,
                    "isImage": path.suffix.lower() in image_extensions,
                    "url": "/project-assets/" + "/".join(
                        part.replace(" ", "%20") for part in PurePosixPath(relative).parts
                    ),
                }
            )
        return assets

    def add_asset_references(self, references: Sequence[str]) -> None:
        config = self.load_config()
        assets = config.setdefault("assets", [])
        if not isinstance(assets, list):
            assets = []
            config["assets"] = assets
        for reference in references:
            if reference not in assets:
                assets.append(reference)
        self.save_config(config)

    def upload_assets(self, files: Sequence[tuple[str, bytes]], directory: str) -> list[str]:
        if not files:
            raise GUIError("No files were uploaded")
        target_directory = self.assets_dir
        if directory.strip():
            target_directory = _resolve_under(self.assets_dir, directory.strip())
        target_directory.mkdir(parents=True, exist_ok=True)
        uploaded: list[str] = []
        for original_name, content in files:
            if len(content) > MAX_UPLOAD_FILE:
                raise GUIError(f"File is larger than 25 MB: {original_name}")
            filename = Path(original_name.replace("\\", "/")).name
            filename = re.sub(r"[^A-Za-z0-9._ -]+", "-", filename).strip(". ")
            if not filename:
                raise GUIError("An uploaded file has no safe filename")
            destination = target_directory / filename
            stem, suffix = destination.stem, destination.suffix
            counter = 1
            while destination.exists():
                destination = target_directory / f"{stem}-{counter}{suffix}"
                counter += 1
            destination.write_bytes(content)
            relative = destination.relative_to(self.assets_dir).as_posix()
            uploaded.append(relative)
        self.add_asset_references(uploaded)
        return uploaded

    def delete_asset(self, reference: str) -> None:
        target = _resolve_under(self.assets_dir, reference.removeprefix("assets/"))
        if not target.is_file():
            raise GUIError(f"Asset not found: {reference}", HTTPStatus.NOT_FOUND)
        target.unlink()
        config = self.load_config()
        assets = config.get("assets", [])
        if isinstance(assets, list):
            normalized = reference.removeprefix("assets/")
            config["assets"] = [
                item
                for item in assets
                if not (
                    isinstance(item, str)
                    and item.removeprefix("assets/") == normalized
                )
            ]
            self.save_config(config)
        parent = target.parent
        while parent != self.assets_dir and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    # -------------------------------- build -------------------------------

    def read_logs(self) -> list[dict[str, Any]]:
        log_path = self.output_dir / "log.json"
        try:
            logs = json.loads(log_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        return logs if isinstance(logs, list) else []

    def run_build(self) -> dict[str, Any]:
        if not self._build_lock.acquire(blocking=False):
            raise GUIError("A build is already running", HTTPStatus.CONFLICT)
        started = time.perf_counter()
        try:
            success = engine.build_site(
                self.input_path,
                self.output_dir,
                plugin_paths=self.enabled_plugin_paths(),
                quiet=True,
            )
            duration_ms = round((time.perf_counter() - started) * 1000)
            logs = self.read_logs()
            with self._lock:
                self.last_build_success = success
                self.last_build_time = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                if success:
                    self.revision += 1
            config = self.load_config()
            first_page = "index.html"
            pages = config.get("pages", [])
            if pages and isinstance(pages[0], dict):
                first_page = str(pages[0].get("path", first_page))
            return {
                "success": success,
                "revision": self.revision,
                "durationMs": duration_ms,
                "logs": logs,
                "previewUrl": f"/preview/{first_page}?revision={self.revision}",
            }
        finally:
            self._build_lock.release()

    def status(self) -> dict[str, Any]:
        return {
            "version": GUI_VERSION,
            "engineVersion": engine.VERSION,
            "project": str(self.project_dir),
            "input": str(self.input_path),
            "output": str(self.output_dir),
            "revision": self.revision,
            "lastBuildSuccess": self.last_build_success,
            "lastBuildTime": self.last_build_time,
            "enabledPlugins": self.enabled_plugins,
        }


class GUIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for GUI assets, APIs, and generated previews."""

    server_version = "WeBuilderGUI/2.0"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args: Any, state: GUIState, **kwargs: Any) -> None:
        self.state = state
        super().__init__(*args, **kwargs)

    def log_message(self, message_format: str, *args: Any) -> None:
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(message_format, *args)

    # ------------------------------ responses -----------------------------

    def _common_headers(self, content_type: str, length: int, cache: str = "no-store") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8", len(body))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, exc: Exception) -> None:
        status = exc.status if isinstance(exc, GUIError) else HTTPStatus.INTERNAL_SERVER_ERROR
        message = str(exc) if isinstance(exc, GUIError) else f"Internal server error: {exc}"
        self._send_json({"ok": False, "error": message}, status)

    def _send_file(
        self,
        path: Path,
        *,
        cache: str = "no-cache",
        inject_preview: bool = False,
    ) -> None:
        if not path.is_file():
            raise GUIError("File not found", HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        content = path.read_bytes()
        if inject_preview and path.suffix.lower() in (".html", ".htm"):
            document = content.decode("utf-8")
            bridge = """<style data-webuilder-gui>
[data-wb-gui-selected] { outline: 3px solid #7c5cff !important; outline-offset: 3px !important; }
</style>
<script data-webuilder-gui>
window.addEventListener('message', (event) => {
  if (event.origin !== location.origin || event.data?.type !== 'webuilder:select') return;
  document.querySelectorAll('[data-wb-gui-selected]').forEach((node) => node.removeAttribute('data-wb-gui-selected'));
  if (!event.data.instance) return;
  const node = [...document.querySelectorAll('[data-wb-instance]')].find((item) => item.dataset.wbInstance === event.data.instance);
  if (node) { node.setAttribute('data-wb-gui-selected', ''); node.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
});
</script>"""
            document = document.replace("</body>", bridge + "\n</body>", 1)
            content = document.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self._common_headers(content_type, len(content), cache)
        if path == STATIC_DIR / "index.html":
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'",
            )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    # ------------------------------- input --------------------------------

    def _read_body(self, maximum: int = MAX_JSON_BODY) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise GUIError("Invalid Content-Length") from exc
        if length <= 0:
            raise GUIError("Request body is required")
        if length > maximum:
            raise GUIError("Request body is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return self.rfile.read(length)

    def _read_json(self) -> Any:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise GUIError("Content-Type must be application/json")
        try:
            return json.loads(self._read_body().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GUIError(f"Invalid JSON request: {exc}") from exc

    def _read_uploads(self) -> list[tuple[str, bytes]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise GUIError("Content-Type must be multipart/form-data")
        body = self._read_body(MAX_UPLOAD_BODY)
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: "
            + content_type.encode("utf-8")
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + body
        )
        files: list[tuple[str, bytes]] = []
        if not message.is_multipart():
            raise GUIError("Malformed multipart request")
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            filename = part.get_filename()
            if filename:
                files.append((filename, part.get_payload(decode=True) or b""))
        return files

    # -------------------------------- GET ---------------------------------

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_get()

    def do_GET(self) -> None:  # noqa: N802
        self._handle_get()

    def _handle_get(self) -> None:
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/api/status":
                self._send_json({"ok": True, "status": self.state.status()})
            elif path == "/api/load-build":
                self._send_json(
                    {
                        "ok": True,
                        "config": self.state.load_config(),
                        "revision": self.state.revision,
                    }
                )
            elif path == "/api/components":
                self._send_json({"ok": True, "components": self.state.component_catalog()})
            elif path == "/api/themes":
                self._send_json({"ok": True, "themes": self.state.theme_catalog()})
            elif path == "/api/plugins":
                self._send_json({"ok": True, "plugins": self.state.plugin_inventory()})
            elif path == "/api/assets":
                self._send_json({"ok": True, "assets": self.state.list_assets()})
            elif path == "/api/logs":
                self._send_json({"ok": True, "logs": self.state.read_logs()})
            elif path in ("/api/build", "/api/preview"):
                raise GUIError("Use POST for build operations", HTTPStatus.METHOD_NOT_ALLOWED)
            elif path == "/" or path == "/index.html":
                self._send_file(STATIC_DIR / "index.html", cache="no-store")
            elif path.startswith("/static/"):
                self._send_file(_resolve_under(STATIC_DIR, path.removeprefix("/static/")))
            elif path.startswith("/project-assets/"):
                self._send_file(
                    _resolve_under(
                        self.state.assets_dir, path.removeprefix("/project-assets/")
                    )
                )
            elif path.startswith("/preview/"):
                self._serve_preview(path.removeprefix("/preview/"))
            elif path.startswith(("/css/", "/js/", "/assets/")):
                self._send_file(_resolve_under(self.state.output_dir, path.lstrip("/")))
            else:
                raise GUIError("Not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error_json(exc)

    def _serve_preview(self, relative: str) -> None:
        relative = relative or "index.html"
        if not PurePosixPath(relative).suffix:
            html_candidate = relative.rstrip("/") + ".html"
            candidate = _resolve_under(self.state.output_dir, html_candidate)
            relative = html_candidate if candidate.is_file() else relative
        target = _resolve_under(self.state.output_dir, relative)
        if target.is_dir():
            target = target / "index.html"
        self._send_file(target, cache="no-store", inject_preview=True)

    # ------------------------------- POST ---------------------------------

    def _validate_mutating_request(self) -> None:
        host_header = self.headers.get("Host", "")
        host = urlsplit(f"//{host_header}").hostname
        if not host:
            self.close_connection = True
            raise GUIError("Missing Host header", HTTPStatus.FORBIDDEN)
        if host != "localhost":
            try:
                ipaddress.ip_address(host)
            except ValueError as exc:
                self.close_connection = True
                raise GUIError("Untrusted Host header", HTTPStatus.FORBIDDEN) from exc
        origin_header = self.headers.get("Origin")
        if origin_header:
            origin = urlsplit(origin_header)
            origin_host = origin.hostname
            request_port = urlsplit(f"//{host_header}").port
            origin_port = origin.port or (443 if origin.scheme == "https" else 80)
            expected_port = request_port or 80
            if origin_host != host or origin_port != expected_port:
                self.close_connection = True
                raise GUIError("Cross-origin request rejected", HTTPStatus.FORBIDDEN)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._validate_mutating_request()
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/api/save":
                payload = self._read_json()
                config = payload.get("config") if isinstance(payload, dict) and "config" in payload else payload
                saved = self.state.save_config(config)
                self._send_json({"ok": True, "config": saved})
            elif path in ("/api/build", "/api/preview"):
                # Accept an optional empty JSON body for fetch wrappers.
                self._send_json({"ok": True, **self.state.run_build()})
            elif path == "/api/plugins":
                payload = self._read_json()
                enabled = payload.get("enabled") if isinstance(payload, dict) else None
                names = self.state.set_enabled_plugins(enabled)
                self._send_json(
                    {
                        "ok": True,
                        "enabled": names,
                        "plugins": self.state.plugin_inventory(),
                        "components": self.state.component_catalog(),
                        "themes": self.state.theme_catalog(),
                    }
                )
            elif path == "/api/upload-assets":
                query = parse_qs(parsed.query)
                directory = query.get("directory", ["images"])[0]
                uploaded = self.state.upload_assets(self._read_uploads(), directory)
                self._send_json(
                    {
                        "ok": True,
                        "uploaded": uploaded,
                        "assets": self.state.list_assets(),
                        "config": self.state.load_config(),
                    },
                    HTTPStatus.CREATED,
                )
            elif path == "/api/delete-asset":
                payload = self._read_json()
                reference = payload.get("path") if isinstance(payload, dict) else None
                if not isinstance(reference, str):
                    raise GUIError("A string asset 'path' is required")
                self.state.delete_asset(reference)
                self._send_json(
                    {
                        "ok": True,
                        "assets": self.state.list_assets(),
                        "config": self.state.load_config(),
                    }
                )
            else:
                raise GUIError("Endpoint not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_error_json(exc)


class GUIHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_gui(
    input_path: str | Path = "build.json",
    output_dir: str | Path = "./build",
    plugin_paths: Sequence[str | Path] | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> int:
    """Start the visual editor and block until Ctrl+C."""
    try:
        state = GUIState(input_path, output_dir, plugin_paths)
        handler = partial(GUIRequestHandler, state=state)
        server = GUIHTTPServer((host, port), handler)
    except (GUIError, OSError) as exc:
        print(f"Unable to start WeBuilder GUI: {exc}", file=sys.stderr)
        return 2

    actual_port = int(server.server_address[1])
    browser_host = "localhost" if host in ("0.0.0.0", "::", "127.0.0.1") else host
    url = f"http://{browser_host}:{actual_port}/"
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  WeBuilder GUI v{GUI_VERSION}: {url}")
    print(f"  Project: {state.project_dir}")
    print(f"  Build config: {state.input_path}")
    print(f"  Output: {state.output_dir}")
    print("  Press Ctrl+C to stop.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    if open_browser:
        timer = threading.Timer(0.35, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping WeBuilder GUI…")
    finally:
        server.server_close()
    return 0


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="WeBuilder GUI",
        description="Start the local WeBuilder v2 visual editor.",
    )
    parser.add_argument("--input", default="build.json", help="path to build.json")
    parser.add_argument("--output", default="./build", help="generated site directory")
    parser.add_argument(
        "--plugin",
        action="append",
        nargs="+",
        default=[],
        metavar="PLUGIN_JSON",
        help="initially enabled plugin files; may be repeated",
    )
    parser.add_argument("--host", default="127.0.0.1", help="server bind address")
    parser.add_argument("--port", type=int, default=8080, help="server port; 0 selects a free port")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--version", action="version", version=f"WeBuilder GUI {GUI_VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_argument_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        print("--port must be between 0 and 65535", file=sys.stderr)
        return 2
    plugins = [item for group in args.plugin for item in group]
    return run_gui(
        args.input,
        args.output,
        plugins,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
