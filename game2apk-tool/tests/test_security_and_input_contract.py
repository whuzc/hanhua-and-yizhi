from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from game2apk.builder import BuildService
from game2apk.cli import build_parser, main
from game2apk.config import build_config
from game2apk.security import read_secret_source, sanitized_child_environment
from game2apk.verifier import _stage_asset_check


class SecurityAndInputContractTests(unittest.TestCase):
    def test_cli_run_translation_is_opt_in(self) -> None:
        default = build_parser().parse_args(["run", "source", "--template", "template"])
        self.assertFalse(default.translate)
        selected = build_parser().parse_args(["run", "source", "--template", "template", "--translate"])
        self.assertTrue(selected.translate)

    def test_supported_help_uses_secret_sources_not_raw_values(self) -> None:
        for command in ("translate", "sign", "run"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                with self.assertRaises(SystemExit):
                    build_parser().parse_args([command, "--help"])
            text = output.getvalue()
            self.assertIn("-env NAME", text)
            self.assertIn("-stdin", text)
            self.assertIn("-prompt", text)
            self.assertNotIn("--api-key VALUE", text)
            self.assertNotIn("--password VALUE", text)
            self.assertNotIn("--sign-password VALUE", text)

    def test_old_raw_secret_flag_is_rejected_without_echo(self) -> None:
        canary = "CANARY-SECRET-MUST-NOT-ECHO"
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = main(["translate", "--www", "missing", "--api-key", canary])
        self.assertEqual(result, 2)
        self.assertNotIn(canary, error.getvalue())

    def test_env_stdin_and_hidden_prompt_sources_are_available(self) -> None:
        canary = "CANARY-IN-MEMORY-ONLY"
        with mock.patch.dict(os.environ, {"GAME2APK_TEST_SECRET": canary}, clear=False):
            self.assertEqual(
                read_secret_source(kind="test", env_name="GAME2APK_TEST_SECRET"),
                canary,
            )
        self.assertEqual(
            read_secret_source(kind="test", from_stdin=True, input_stream=io.StringIO(canary + "\n")),
            canary,
        )
        self.assertEqual(
            read_secret_source(kind="test", prompt=True, prompt_function=lambda _message: canary),
            canary,
        )

    def test_child_environment_and_safe_serialized_outputs_do_not_contain_canary(self) -> None:
        canary = "CANARY-SECRET-MUST-NOT-LEAK"
        with mock.patch.dict(os.environ, {"GAME2APK_API_KEY": canary}, clear=False):
            child_env = sanitized_child_environment()
        self.assertNotIn("GAME2APK_API_KEY", child_env)
        command = BuildService()._command("gradlew.bat")
        self.assertNotIn(canary, json.dumps(command))
        status = {"command": command, "environment": {"name": "GAME2APK_API_KEY"}}
        self.assertNotIn(canary, json.dumps(status))

    def test_duplicate_normalized_zip_name_is_a_verifier_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            apk = root / "candidate.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/www/same.txt", b"one")
                archive.writestr("assets/www/same.txt", b"two")
            manifest = root / "stage-manifest.json"
            manifest.write_text(json.dumps({
                "copiedFiles": [{"path": "same.txt", "sha256": "ignored"}],
            }), encoding="utf-8")
            result = _stage_asset_check(apk, manifest)
            self.assertFalse(result["passed"])
            self.assertTrue(result["actualNameCollisions"])
            self.assertTrue(result["normalizedNameCollisions"])

    def test_translation_data_allowlist_accepts_only_manifest_backed_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = b'{"message":"Hello"}'
            translated = b'{"message":"\xe4\xbd\xa0\xe5\xa5\xbd"}'
            apk = root / "candidate.apk"
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/www/data/Map001.json", translated)
            manifest = root / "stage-manifest.json"
            manifest.write_text(json.dumps({
                "copiedFiles": [{
                    "path": "data/Map001.json",
                    "sha256": hashlib.sha256(original).hexdigest(),
                }],
                "allowedModifiedFiles": ["data/Map001.json"],
            }), encoding="utf-8")
            result = _stage_asset_check(apk, manifest)
            self.assertTrue(result["passed"])
            self.assertIn("assets/www/data/Map001.json", result["modifiedAllowed"])

            manifest.write_text(json.dumps({
                "copiedFiles": [{
                    "path": "data/Map001.json",
                    "sha256": hashlib.sha256(original).hexdigest(),
                }],
                "allowedModifiedFiles": ["js/evil.js"],
            }), encoding="utf-8")
            unsafe = _stage_asset_check(apk, manifest)
            self.assertFalse(unsafe["passed"])
            self.assertIn("js/evil.js", unsafe["allowlistErrors"])

    def test_template_has_nonempty_default_launcher_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        icon = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "res" / "drawable" / "game2apk_launcher.xml").read_text(encoding="utf-8")
        self.assertIn('android:icon="@drawable/game2apk_launcher"', manifest)
        self.assertIn('android:roundIcon="@drawable/game2apk_launcher"', manifest)
        self.assertIn("<vector", icon)
        self.assertIn("pathData=", icon)

    def test_update_identity_and_webview_storage_contract_are_stable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = build_config()
        self.assertEqual(config["applicationId"], "com.game2apk.xianyaoshengcanver22")
        self.assertEqual(config["versionCode"], 9)
        self.assertEqual(config["versionName"], "1.4.0")

        gradle = (root / "templates" / "android-rpgmv" / "app" / "build.gradle").read_text(encoding="utf-8")
        self.assertIn("com.game2apk.xianyaoshengcanver22", gradle)
        self.assertIn("versionCode Integer.parseInt(requiredOrDefault('game2apkVersionCode', '9'))", gradle)
        self.assertIn("versionName requiredOrDefault('game2apkVersionName', '1.4.0')", gradle)

        activity = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "java" / "com" / "game2apk" / "rpgmv" / "MainActivity.java").read_text(encoding="utf-8")
        store = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "java" / "com" / "game2apk" / "rpgmv" / "OverlayStateStore.java").read_text(encoding="utf-8")
        self.assertIn("setDomStorageEnabled(true)", activity)
        self.assertIn("appassets.androidplatform.net", activity)
        self.assertNotRegex(activity, r"clear(?:Cache|History|FormData)|deleteAllData|deleteDatabase")
        self.assertIn('PREFS_NAME = "game2apk.overlay.v1"', store)
        self.assertNotRegex(store, r"clear\(\)|deleteDatabase|deleteAll")

    def test_bluetooth_audio_contract_uses_focus_without_route_permissions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        activity = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "java" / "com" / "game2apk" / "rpgmv" / "MainActivity.java").read_text(encoding="utf-8")
        self.assertIn("AudioManager.AUDIOFOCUS_GAIN)", activity)
        self.assertIn("AudioAttributes.USAGE_GAME", activity)
        self.assertIn("AudioAttributes.CONTENT_TYPE_MUSIC", activity)
        self.assertIn("resumeWebAudio();", activity)
        self.assertNotIn("BLUETOOTH_CONNECT", activity)
        self.assertNotIn("setBluetoothA2dpOn", activity)
        manifest = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertNotIn("BLUETOOTH", manifest)

    def test_cheat_overlay_and_whitelisted_mv_fields_are_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        overlay = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "java" / "com" / "game2apk" / "rpgmv" / "OverlayView.java").read_text(encoding="utf-8")
        config = (root / "templates" / "android-rpgmv" / "app" / "src" / "main" / "java" / "com" / "game2apk" / "rpgmv" / "Game2ApkConfig.java").read_text(encoding="utf-8")
        bridge = (root / "src" / "game2apk" / "patcher.py").read_text(encoding="utf-8")
        self.assertIn("CHEAT_HANDLE", overlay)
        for token in ("LAYOUT_HANDLE", "showLayoutMenu", "showButtonEditor", "addCustomButtonDialog", "saveButtons", "EDIT_BUTTON"):
            self.assertIn(token, overlay)
        self.assertIn("CUSTOM_BUTTON_ID", config)
        for token in ("Game2ApkCheat", "999999999", "recallMapIds = [136, 97]", "2010", "2034", "2085", "cheat.discover", "dynamicCatalog", "switchFields"):
            self.assertIn(token, bridge)

    def test_desktop_release_separates_console_backend_from_browser_launcher(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entry = (root / "src" / "game2apk" / "portable_entry.py").read_text(encoding="utf-8")
        spec = (root / "scripts" / "game2apk.spec").read_text(encoding="utf-8")
        launcher = (root / "src" / "game2apk" / "ui_launcher.py").read_text(encoding="utf-8")
        ui_spec = (root / "scripts" / "game2apk-ui.spec").read_text(encoding="utf-8")
        self.assertIn('"--backend"', entry)
        self.assertIn('"--cli"', entry)
        self.assertIn("console=True", spec)
        self.assertIn("game2apk-tool.exe", launcher)
        self.assertIn("CREATE_NO_WINDOW", launcher)
        self.assertIn("console=False", ui_spec)

    def test_desktop_ui_has_glass_liquid_motion_and_reduced_motion_switch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        visuals = (root / "src" / "game2apk" / "visuals.py").read_text(encoding="utf-8")
        gui = (root / "src" / "game2apk" / "gui.py").read_text(encoding="utf-8")
        for token in ("LiquidBackdrop", "GlassCard", "GlassButton", "apply_windows_backdrop", "GAME2APK_REDUCE_MOTION"):
            self.assertIn(token, visuals)
        self.assertIn("GlassCard", gui)
        self.assertIn("LiquidBackdrop", gui)
        self.assertIn("hover_fg", visuals)
        self.assertNotIn('attributes("-alpha", 0.98)', gui)


if __name__ == "__main__":
    unittest.main()
