from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from game2apk.toolchain import ALLOWED_DOWNLOAD_HOSTS, COMPONENTS, _check_component, download_component, load_config, save_config


class _Response:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1):
        return self._stream.read(size)


class ToolchainTests(unittest.TestCase):
    def test_profile_config_is_user_path_friendly_and_only_paths(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "toolchain.json"
            save_config({"sdk_dir": "C:/sdk", "jdk_dir": "C:/jdk", "api_key": "must-not-persist"}, path)
            self.assertEqual(load_config(path), {"sdk_dir": "C:/sdk", "jdk_dir": "C:/jdk"})
            self.assertNotIn("api_key", json.loads(path.read_text(encoding="utf-8")))

    def test_download_requires_confirmation_and_rejects_unapproved_component(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                download_component("android_cmdline_tools", root, confirm=lambda _message: False)
        with self.assertRaises(ValueError):
            _check_component("unknown")
        self.assertEqual(_check_component("temurin_jdk17")["host"], COMPONENTS["temurin_jdk17"]["host"])
        self.assertTrue({component["host"] for component in COMPONENTS.values()} <= set(ALLOWED_DOWNLOAD_HOSTS))

    def test_download_extracts_archive_without_path_escape(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("cmdline-tools/latest/bin/sdkmanager.bat", "@echo off")
        with tempfile.TemporaryDirectory() as root:
            result = download_component(
                "android_cmdline_tools",
                root,
                confirm=lambda _message: True,
                opener=lambda *_args, **_kwargs: _Response(payload.getvalue()),
            )
            self.assertTrue((result.extracted_to / "cmdline-tools/latest/bin/sdkmanager.bat").is_file())


if __name__ == "__main__":
    unittest.main()
