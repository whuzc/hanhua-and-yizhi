from __future__ import annotations

import json
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_static_shell_contains_glass_motion_and_accessibility_contract(self) -> None:
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertIn("backdrop-filter", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":active", css)
        self.assertIn("ambient", html)
        self.assertIn("/api/health", js)
        self.assertIn("textContent = detail", js)
        self.assertNotIn("report.innerHTML", js)
        self.assertNotIn(".rpgsave", html + css + js)
        self.assertNotIn("api_key", html + css + js)

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
