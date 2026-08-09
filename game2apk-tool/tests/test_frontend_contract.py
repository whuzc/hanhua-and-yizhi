from __future__ import annotations

import json
import threading
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    @staticmethod
    def _fake_report(source: Path):
        from game2apk.models import InspectionReport

        return InspectionReport(
            source_root=str(source),
            www_root=str(source),
            engine="RPG Maker MV",
            engine_version="1.6.1",
            title="fixture",
            effective_width=816,
            effective_height=624,
            mv_default_width=816,
            mv_default_height=624,
            outer_window_width=816,
            outer_window_height=624,
            has_encrypted_images=False,
            has_encrypted_audio=False,
            encryption_key_present=False,
            file_count=1,
            total_bytes=1,
            extensions={},
            enabled_plugins=[],
            disabled_plugins=[],
            custom_keys=[],
            status="compatible",
        )

    def test_backend_session_polling_and_fake_inspect_job(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from game2apk.web_frontend import LocalBackendServer

        class FakePipeline:
            def __init__(self, _root, progress=None, cancel_event=None):
                self.progress = progress or (lambda *_args: None)

            def inspect(self, source):
                self.progress("inspect", 1.0, "inspection complete")
                return self_report(Path(source))

        def self_report(source: Path):
            return self._fake_report(source)

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            server = LocalBackendServer(
                ("127.0.0.1", 0),
                ROOT,
                frontend_root=ROOT / "frontend",
                idle_timeout_seconds=0,
                pipeline_factory=FakePipeline,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(method: str, path: str, *, cookie: str = "", body: dict | None = None, header: bool = False, origin: str | None = None):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                headers = {"Accept": "application/json"}
                if cookie:
                    headers["Cookie"] = cookie
                if header:
                    headers["X-Game2Apk-Request"] = "1"
                if origin:
                    headers["Origin"] = origin
                encoded = None
                if body is not None:
                    encoded = json.dumps(body).encode("utf-8")
                    headers["Content-Type"] = "application/json"
                connection.request(method, path, body=encoded, headers=headers)
                response = connection.getresponse()
                payload = response.read().decode("utf-8")
                try:
                    result = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    result = {}
                cookie_header = response.getheader("Set-Cookie", "")
                connection.close()
                return response.status, result, cookie_header

            try:
                status, _payload, cookie_header = request("GET", "/")
                self.assertEqual(status, 200)
                cookie = cookie_header.split(";", 1)[0]
                self.assertTrue(cookie.startswith("game2apk_session="))
                status, _payload, _ = request("GET", "/api/jobs/missing", cookie=cookie)
                self.assertEqual(status, 404)
                status, payload, _ = request("POST", "/api/inspect", cookie=cookie, header=True, body={"source": str(source)})
                self.assertEqual(status, 202)
                job_id = payload["job"]["id"]
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    status, payload, _ = request("GET", f"/api/jobs/{job_id}", cookie=cookie)
                    self.assertEqual(status, 200)
                    if payload["job"]["status"] == "completed":
                        self.assertEqual(payload["job"]["result"]["buildReady"], True)
                        break
                    time.sleep(0.02)
                else:
                    self.fail("fake inspect job did not finish")
                status, _payload, _ = request("POST", "/api/heartbeat", cookie=cookie, header=True, origin="http://evil.example")
                self.assertEqual(status, 403)
            finally:
                server.close_jobs()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_static_shell_contains_glass_motion_and_accessibility_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("backdrop-filter", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":active", css)
        self.assertIn("ambient", html)
        self.assertIn("/api/health", js)
        self.assertIn("/api/browse", js)
        self.assertIn("/api/download", js)
        self.assertIn("/api/inspect", js)
        self.assertIn("/api/build", js)
        self.assertIn("/api/jobs/", js)
        self.assertIn("/api/heartbeat", js)
        self.assertIn("X-Game2Apk-Request", js)
        self.assertIn("downloadToolchain", js)
        self.assertIn("setText(description, detail)", js)
        self.assertNotIn("report.innerHTML", js)
        self.assertNotIn(".rpgsave", html + css + js)
        self.assertNotIn("api_key", html + css + js)

    def test_launcher_rejects_non_loopback_ready_urls(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from game2apk.ui_launcher import LauncherError, _ready_url_from_line

        self.assertEqual(
            _ready_url_from_line('{"event":"ready","url":"http://127.0.0.1:3210/"}'),
            "http://127.0.0.1:3210/",
        )
        self.assertEqual(
            _ready_url_from_line('{"event":"READY","url":"http://localhost:3211/"}'),
            "http://localhost:3211/",
        )
        self.assertIsNone(_ready_url_from_line("backend is starting"))
        with self.assertRaises(LauncherError):
            _ready_url_from_line('{"event":"ready","url":"https://example.test/"}')

    def test_local_server_rejects_path_traversal_and_reports_health(self) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "src"))
        from game2apk.web_frontend import _Handler, ThreadingHTTPServer

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.frontend_root = str(ROOT / "frontend")
        server.tool_root = str(ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn("ready", json.loads(response.read().decode("utf-8")))
            connection.close()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/../pyproject.toml")
            response = connection.getresponse()
            self.assertIn(response.status, {400, 404})
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
