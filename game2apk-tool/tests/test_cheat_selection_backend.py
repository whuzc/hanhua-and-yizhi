from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class CheatSelectionBackendTests(unittest.TestCase):
    def test_build_request_normalizes_selected_variable_ids(self) -> None:
        from game2apk.errors import ConfigurationError
        from game2apk.web_frontend import BuildRequest

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            template = root / "template"
            source.mkdir()
            template.mkdir()
            request = BuildRequest.from_payload(
                {
                    "source": str(source),
                    "template": str(template),
                    "advancedCheatVariableIds": ["variable:8", "variable:2", "variable:8"],
                },
                ROOT,
            )
            self.assertEqual(
                request.config.advanced_cheat_variable_ids,
                ["variable:2", "variable:8"],
            )
            with self.assertRaises(ConfigurationError):
                BuildRequest.from_payload(
                    {
                        "source": str(source),
                        "template": str(template),
                        "advancedCheatVariableIds": ["switch:2"],
                    },
                    ROOT,
                )

    def test_cheat_catalog_endpoint_returns_translated_labels_without_secret(self) -> None:
        from game2apk.models import InspectionReport
        from game2apk.web_frontend import LocalBackendServer

        canary = "catalog-secret-canary"

        class FakePipeline:
            def __init__(self, _root, progress=None, cancel_event=None):
                self.progress = progress or (lambda *_args: None)

            def inspect(self, source):
                source = Path(source)
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

            def cheat_labels_need_translation_at(self, _www_root):
                return True

            def preview_cheat_catalog(self, _report, **kwargs):
                self.progress("translate", 1.0, "labels ready")
                self_test.assertEqual(kwargs["api_key"], canary)
                return (
                    {
                        "status": "ready",
                        "items": [
                            {
                                "id": "variable:1",
                                "kind": "variable",
                                "index": 1,
                                "sourceLabel": "発情中",
                                "translatedLabel": "发情中",
                                "displayLabel": "发情中",
                            }
                        ],
                    },
                    None,
                )

        self_test = self
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            server = LocalBackendServer(
                ("127.0.0.1", 0),
                ROOT,
                frontend_root=ROOT / "frontend",
                idle_timeout_seconds=0,
                pipeline_factory=FakePipeline,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(method: str, path: str, *, cookie: str = "", body=None, header: bool = False):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                headers = {"Accept": "application/json"}
                if cookie:
                    headers["Cookie"] = cookie
                if header:
                    headers["X-Game2Apk-Request"] = "1"
                encoded = None
                if body is not None:
                    encoded = json.dumps(body).encode("utf-8")
                    headers["Content-Type"] = "application/json"
                connection.request(method, path, body=encoded, headers=headers)
                response = connection.getresponse()
                raw = response.read().decode("utf-8")
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    payload = {}
                cookie_header = response.getheader("Set-Cookie", "")
                status = response.status
                connection.close()
                return status, payload, cookie_header

            try:
                status, _payload, cookie_header = request("GET", "/")
                self.assertEqual(status, 200)
                cookie = cookie_header.split(";", 1)[0]
                status, payload, _ = request(
                    "POST",
                    "/api/cheat-catalog",
                    cookie=cookie,
                    header=True,
                    body={"source": str(source), "confirm": True, "apiKey": canary},
                )
                self.assertEqual(status, 202)
                job_id = payload["job"]["id"]
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    _status, payload, _ = request("GET", f"/api/jobs/{job_id}", cookie=cookie)
                    job = payload["job"]
                    if job["status"] == "completed":
                        item = job["result"]["cheatCatalog"]["items"][0]
                        self.assertEqual(item["id"], "variable:1")
                        self.assertEqual(item["displayLabel"], "发情中")
                        self.assertNotIn(canary, json.dumps(job, ensure_ascii=False))
                        break
                    time.sleep(0.02)
                else:
                    self.fail("cheat catalog job did not finish")
            finally:
                server.close_jobs()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
