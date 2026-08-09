"""Opt-in local browser shell for the desktop release.

The browser shell is intentionally a visual/status frontend.  It only binds
to loopback and exposes a read-only toolchain health endpoint; build, signing,
translation and file selection remain in the canonical Tk application.  This
keeps the shareable release safe while making a future WebView/Tauri bridge a
small, auditable seam instead of coupling browser JavaScript to secrets.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .toolchain import discover_configured, missing_components


class _Handler(BaseHTTPRequestHandler):
    server_version = "game2apk-local-shell/1"

    @property
    def root(self) -> Path:
        return Path(self.server.frontend_root).resolve()  # type: ignore[attr-defined]

    @property
    def tool_root(self) -> Path:
        return Path(self.server.tool_root).resolve()  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            try:
                info = discover_configured(str(self.tool_root / "templates" / "android-rpgmv"))
                missing = missing_components(info)
                self._json({"ready": not missing, "missing": missing, "sdk_dir": info.sdk_dir or "", "jdk_dir": info.jdk_dir or "", "gradle_user_home": info.gradle_user_home or ""})
            except Exception as exc:
                self._json({"ready": False, "missing": ["toolchain check failed"], "error": str(exc)}, 200)
            return
        if path in {"", "/"}:
            path = "/index.html"
        self._serve_file(path)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        # The visual shell deliberately does not execute a build.  Returning
        # 202 makes the boundary explicit to any future WebView bridge.
        if urlparse(self.path).path == "/api/inspect":
            self._json({"accepted": True, "mode": "visual-shell", "message": "Use the desktop GUI for local inspection."}, 202)
            return
        self._json({"error": "endpoint not found"}, 404)

    def _serve_file(self, request_path: str) -> None:
        candidate = (self.root / request_path.lstrip("/"))
        try:
            candidate = candidate.resolve()
            candidate.relative_to(self.root)
        except (OSError, ValueError):
            self._json({"error": "invalid path"}, 400)
            return
        if not candidate.is_file():
            self._json({"error": "not found"}, 404)
            return
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(tool_root: str | Path, *, open_browser: bool = True) -> None:
    frontend_root = Path(tool_root).resolve() / "frontend"
    if not frontend_root.is_dir():
        raise FileNotFoundError(f"frontend assets are missing: {frontend_root}")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.frontend_root = str(frontend_root)  # type: ignore[attr-defined]
    server.tool_root = str(Path(tool_root).resolve())  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{server.server_port}/"
    if open_browser:
        webbrowser.open(url, new=1)
    print(f"game2apk visual shell: {url}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # KeyboardInterrupt arrives on the serve_forever thread; calling
        # ``shutdown`` from that same thread deadlocks BaseServer.  The loop
        # has already been interrupted, so closing the listening socket is
        # sufficient here (tests call shutdown from a separate thread).
        server.server_close()
