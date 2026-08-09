from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from game2apk.errors import CancelledError, ConfigurationError
from game2apk.models import InspectionReport, ToolchainInfo
from game2apk.web_frontend import BuildRequest, _parent_is_alive, create_server


def _report(source: Path) -> InspectionReport:
    return InspectionReport(
        source_root=str(source),
        www_root=str(source / "www"),
        engine="rpg-maker-mv",
        engine_version="1.6.1",
        title="Fixture",
        effective_width=816,
        effective_height=624,
        mv_default_width=816,
        mv_default_height=624,
        outer_window_width=None,
        outer_window_height=None,
        has_encrypted_images=False,
        has_encrypted_audio=False,
        encryption_key_present=False,
        file_count=1,
        total_bytes=1,
        extensions={},
        enabled_plugins=[],
        disabled_plugins=[],
        custom_keys=[],
    )


class _PipelineFixture:
    calls: list[str] = []

    def __init__(self, _root, progress=None, cancel_event=None):
        self.progress = progress or (lambda *_args: None)
        self.cancel_event = cancel_event or threading.Event()

    def inspect(self, source):
        type(self).calls.append("inspect")
        self.progress("inspect", 0.5, "checking fixture")
        return _report(Path(source))

    def stage(self, inspection):
        type(self).calls.append("stage")
        self.progress("stage", 0.5, "staging fixture")
        return SimpleNamespace(project_id="fixture", source_unchanged=True)

    def patch(self, _stage, _config):
        type(self).calls.append("patch")
        self.progress("patch", 1.0, "patching fixture")
        return {"injectionCount": 1}

    def translate(self, _stage, **_kwargs):
        type(self).calls.append("translate")
        return SimpleNamespace(to_dict=lambda: {"entriesApplied": 1})

    def build(self, _template, _stage, _config, *, api_key=None, **_kwargs):
        type(self).calls.append("build")
        self.progress("build", 0.5, f"secret must redact: {api_key}")
        return SimpleNamespace(
            return_code=0,
            apk_path="C:/fixture.apk",
            to_dict=lambda: {"returnCode": 0, "apkPath": "C:/fixture.apk"},
        )

    def sign(self, _result, _config, *, password=None):
        type(self).calls.append("sign")
        return {"signed": True, "passwordProtection": "Windows DPAPI"}

    def verify(self, _result, _config, *, install=False):
        type(self).calls.append("verify")
        return SimpleNamespace(
            signature_candidate=True,
            passed=True,
            to_dict=lambda: {"passed": True, "signatureCandidate": True},
        )

    def promote(self, _verification, _config):
        type(self).calls.append("promote")
        return Path("C:/dist/fixture-signed.apk")


class _BlockingPipeline(_PipelineFixture):
    def inspect(self, source):
        type(self).calls.append("inspect")
        while not self.cancel_event.wait(0.01):
            self.progress("inspect", 0.25, "waiting for cancellation")
        raise CancelledError("fixture cancellation")


def _toolchain(_template) -> ToolchainInfo:
    return ToolchainInfo("sdk", "jdk", "gradle", "wrapper", "aapt2", "zipalign", "apksigner", None, [])


class BackendServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "frontend").mkdir()
        (self.root / "frontend" / "index.html").write_text("<!doctype html><title>fixture</title>", encoding="utf-8")
        self.source = self.root / "source"
        self.source.mkdir()
        self.template = self.root / "template"
        self.template.mkdir()
        _PipelineFixture.calls = []
        _BlockingPipeline.calls = []
        self.server = create_server(
            self.root,
            idle_timeout_seconds=0,
            pipeline_factory=_PipelineFixture,
            toolchain_discoverer=_toolchain,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = self._session_cookie()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.close_jobs()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def _session_cookie(self) -> str:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("GET", "/")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        cookie = response.getheader("Set-Cookie")
        response.read()
        connection.close()
        self.assertIsNotNone(cookie)
        return str(cookie).split(";", 1)[0]

    def _post(self, path: str, payload: dict[str, object], *, authorized: bool = True) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers.update({"Cookie": self.cookie, "X-Game2Apk-Request": "1"})
        connection.request("POST", path, body=json.dumps(payload), headers=headers)
        response = connection.getresponse()
        status = response.status
        result = json.loads(response.read().decode("utf-8"))
        connection.close()
        return status, result

    def _job_until_terminal(self, job_id: str) -> dict[str, object]:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
            connection.request("GET", f"/api/jobs/{job_id}", headers={"Cookie": self.cookie, "X-Game2Apk-Request": "1"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))["job"]
            connection.close()
            if payload["status"] in {"completed", "failed", "cancelled"}:
                return payload
            time.sleep(0.02)
        self.fail("job did not reach a terminal state")

    def test_mutation_needs_a_same_origin_session_and_native_browse_is_bridgeable(self) -> None:
        status, payload = self._post("/api/inspect", {"source": str(self.source)}, authorized=False)
        self.assertEqual(status, 403)
        self.assertIn("error", payload)
        with mock.patch("game2apk.web_frontend.native_choose_directory", return_value=str(self.source)) as picker:
            status, payload = self._post("/api/browse", {"kind": "source"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["selected"])
        self.assertEqual(payload["path"], str(self.source.resolve()))
        picker.assert_called_once_with("source", None)

    def test_inspect_and_build_run_the_gui_pipeline_order_without_exposing_secrets(self) -> None:
        status, payload = self._post("/api/inspect", {"source": str(self.source)})
        self.assertEqual(status, 202)
        inspected = self._job_until_terminal(str(payload["job"]["id"]))
        self.assertEqual(inspected["status"], "completed")
        self.assertTrue(inspected["result"]["buildReady"])

        secret_api = "sk-super-private-fixture-key"
        secret_password = "fixture-sign-password"
        status, payload = self._post(
            "/api/build",
            {
                "source": str(self.source),
                "template": str(self.template),
                "app_name": "Fixture",
                "application_id": "com.fixture.game",
                "version_code": 1,
                "version_name": "1.0.0",
                "translate": True,
                "confirm": True,
                "api_key": secret_api,
                "sign_password": secret_password,
            },
        )
        self.assertEqual(status, 202)
        built = self._job_until_terminal(str(payload["job"]["id"]))
        self.assertEqual(built["status"], "completed")
        self.assertEqual(_PipelineFixture.calls, ["inspect", "inspect", "stage", "patch", "translate", "build", "sign", "verify", "promote"])
        public = json.dumps(built, ensure_ascii=False)
        self.assertNotIn(secret_api, public)
        self.assertNotIn(secret_password, public)
        self.assertEqual(Path(built["result"]["distApkPath"]), Path("C:/dist/fixture-signed.apk"))

    def test_cancelled_job_reports_cancelled_state(self) -> None:
        self.server.close_jobs()
        self.server.jobs = self.server.jobs.__class__(self.root, pipeline_factory=_BlockingPipeline, toolchain_discoverer=_toolchain)
        status, payload = self._post("/api/inspect", {"source": str(self.source)})
        self.assertEqual(status, 202)
        job_id = str(payload["job"]["id"])
        status, payload = self._post(f"/api/jobs/{job_id}/cancel", {})
        self.assertEqual(status, 200)
        cancelled = self._job_until_terminal(job_id)
        self.assertEqual(cancelled["status"], "cancelled")

    def test_build_request_requires_confirmation_and_never_serializes_secret_fields(self) -> None:
        with self.assertRaises(ConfigurationError):
            BuildRequest.from_payload(
                {
                    "source": str(self.source),
                    "template": str(self.template),
                    "translate": True,
                    "confirm": False,
                },
                self.root,
            )
        request = BuildRequest.from_payload(
            {
                "source": str(self.source),
                "template": str(self.template),
                "api_key": "sk-do-not-print-me",
                "sign_password": "do-not-print-me",
            },
            self.root,
        )
        self.assertNotIn("do-not-print-me", repr(request))
        self.assertTrue(request.thinking_enabled)
        self.assertEqual(request.reasoning_effort, "high")
        custom = BuildRequest.from_payload(
            {
                "source": str(self.source),
                "template": str(self.template),
                "thinking_enabled": False,
                "reasoning_effort": "max",
            },
            self.root,
        )
        self.assertFalse(custom.thinking_enabled)
        self.assertEqual(custom.reasoning_effort, "max")
        with self.assertRaises(ConfigurationError):
            BuildRequest.from_payload(
                {
                    "source": str(self.source),
                    "template": str(self.template),
                    "reasoning_effort": "medium",
                },
                self.root,
            )

    def test_toolchain_download_requires_confirmation_and_saves_selected_path(self) -> None:
        status, payload = self._post(
            "/api/download",
            {"component": "android_cmdline_tools", "destination": str(self.root), "confirm": False},
        )
        self.assertEqual(status, 400)
        self.assertIn("confirmation", str(payload.get("error", "")))
        extracted = self.root / "android-sdk"
        archive = self.root / "android-commandline-tools.zip"
        fake_result = SimpleNamespace(component="android_cmdline_tools", archive=archive, extracted_to=extracted)
        with (
            mock.patch("game2apk.web_frontend.download_component", return_value=fake_result) as downloader,
            mock.patch("game2apk.web_frontend.load_config", return_value={}),
            mock.patch("game2apk.web_frontend.save_config") as save_preferences,
            mock.patch("game2apk.web_frontend.health_payload", return_value={"ready": False, "missing": ["platform"]}),
        ):
            status, payload = self._post(
                "/api/download",
                {"component": "android_cmdline_tools", "destination": str(self.root), "confirm": True},
            )
            self.assertEqual(status, 202)
            completed = self._job_until_terminal(str(payload["job"]["id"]))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["extractedTo"], str(extracted))
        downloader.assert_called_once()
        save_preferences.assert_called_once_with({"sdk_dir": str(extracted)})

    @unittest.skipUnless(os.name == "nt", "Windows process-handle contract")
    def test_windows_parent_watcher_detects_an_exited_process(self) -> None:
        process = subprocess.Popen([os.environ.get("ComSpec", "cmd.exe"), "/c", "exit", "0"])
        process.wait(timeout=3)
        self.assertFalse(_parent_is_alive(process.pid))


if __name__ == "__main__":
    unittest.main()
