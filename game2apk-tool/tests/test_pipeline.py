from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from game2apk.builder import AsciiPathMapper, BuildService
from game2apk.config import build_config, default_control_config, load_android_config
from game2apk.errors import BlockedError, ConfigurationError
from game2apk.inspector import inspect_game
from game2apk.models import BuildConfig, ToolchainInfo
from game2apk.patcher import patch_staged_www
from game2apk.security import create_work_marker, redact_text, safe_remove_workdir
from game2apk.signing import SigningService
from game2apk.staging import StageService
from game2apk.translation import (
    FakeTransport,
    TranslationService,
    apply_translations,
    extract_safe_entries,
    validate_placeholders,
)
from game2apk.verifier import VerificationService


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "game"
        self.www = self.game / "www"
        (self.www / "js" / "plugins").mkdir(parents=True)
        (self.www / "data").mkdir(parents=True)
        (self.www / "img").mkdir(parents=True)
        (self.www / "save").mkdir(parents=True)
        (self.www / "index.html").write_text(
            '<html><script src="js/rpg_core.js"></script><script src="js/rpg_managers.js"></script></html>',
            encoding="utf-8",
        )
        (self.www / "js" / "rpg_core.js").write_text("// rpg_core.js v1.6.1\nGraphics.width = 816; Graphics.height = 624;", encoding="utf-8")
        (self.www / "js" / "rpg_managers.js").write_text("// browser-safe manager", encoding="utf-8")
        plugins = [
            {"name": "YEP_CoreEngine", "status": True, "parameters": {"Screen Width": "1024", "Screen Height": "768"}},
            {"name": "TMCommonEventKey", "status": True, "parameters": {"commonKeyA": "25", "commonKeyW": "294"}},
            {"name": "UTA_MessageSkip", "status": True, "parameters": {"Skip Key": "control"}},
        ]
        (self.www / "js" / "plugins.js").write_text("var $plugins =\n" + json.dumps(plugins) + ";", encoding="utf-8")
        for name in ("YEP_CoreEngine", "TMCommonEventKey", "UTA_MessageSkip"):
            (self.www / "js" / "plugins" / f"{name}.js").write_text("/* browser-safe */", encoding="utf-8")
        (self.www / "data" / "System.json").write_text(
            json.dumps({"gameTitle": "English Demo", "locale": "en_US", "terms": {"basic": ["Fight", "Escape"]}, "hasEncryptedImages": True, "hasEncryptedAudio": True, "encryptionKey": "must-not-be-reported"}),
            encoding="utf-8",
        )
        (self.www / "package.json").write_text(json.dumps({"name": "English Demo", "window": {"width": 816, "height": 624}}), encoding="utf-8")
        (self.www / "data" / "Actors.json").write_text(json.dumps([None, {"name": "Potion", "description": "A useful item", "note": "<do not translate>"}]), encoding="utf-8")
        (self.www / "data" / "Map001.json").write_text(
            json.dumps({"events": [None, {"pages": [{"list": [
                {"code": 101, "parameters": ["", 0, 0, 2, "Speaker"]},
                {"code": 401, "parameters": ["Hello world"]},
                {"code": 401, "parameters": ["Second line"]},
                {"code": 102, "parameters": [["Yes", "No"], 0, 0, 2, 0]},
                {"code": 105, "parameters": [0, 2, 2, False]},
                {"code": 405, "parameters": ["Scroll text"]},
                {"code": 405, "parameters": ["Second scroll line"]},
            ]}]}]}),
            encoding="utf-8",
        )
        (self.www / "img" / "ok.png").write_bytes(b"PNG")
        (self.www / "save" / "config.rpgsave").write_text("private", encoding="utf-8")
        (self.www / "old.rpgsave").write_text("private", encoding="utf-8")
        (self.www / "editor.tmp").write_text("temporary", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self) -> BuildConfig:
        data = build_config(control=default_control_config())
        return BuildConfig(data["appName"], data["applicationId"], data["versionCode"], data["versionName"], control_config=data["control"])

    def test_default_update_identity_and_version_are_monotonic(self) -> None:
        data = build_config(control=default_control_config())
        self.assertEqual(data["applicationId"], "com.game2apk.xianyaoshengcanver22")
        self.assertEqual(data["versionCode"], 4)
        self.assertEqual(data["versionName"], "1.0.3")

    def test_inspect_reports_mv_yep_resolution_keys_and_encryption_without_key(self) -> None:
        report = inspect_game(self.game)
        self.assertEqual(report.engine_version, "1.6.1")
        self.assertEqual((report.effective_width, report.effective_height), (1024, 768))
        self.assertEqual((report.mv_default_width, report.mv_default_height), (816, 624))
        self.assertEqual((report.outer_window_width, report.outer_window_height), (816, 624))
        self.assertTrue(report.encryption_key_present)
        serialized = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertNotIn("must-not-be-reported", serialized)
        self.assertIn({"key": "A", "common_event_id": 25, "plugin": "TMCommonEventKey", "source": "plugins.js"}, report.custom_keys)
        self.assertIn({"key": "W", "common_event_id": 294, "plugin": "TMCommonEventKey", "source": "plugins.js"}, report.custom_keys)
        self.assertTrue(any(item.get("key") == "Ctrl" and item.get("action") == "skip" for item in report.custom_keys))

    def test_unknown_engine_is_blocked(self) -> None:
        unknown = self.root / "unknown"
        unknown.mkdir()
        report = inspect_game(unknown)
        self.assertTrue(report.blocked)
        self.assertEqual(report.engine, "unknown")

    def test_stage_excludes_saves_and_preserves_source(self) -> None:
        before = {path.relative_to(self.game).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.game.rglob("*") if path.is_file()}
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        after = {path.relative_to(self.game).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.game.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        staged = Path(stage.staged_www)
        self.assertFalse((staged / "save").exists())
        self.assertFalse((staged / "old.rpgsave").exists())
        self.assertFalse((staged / "editor.tmp").exists())
        self.assertTrue((staged / "index.html").is_file())
        self.assertTrue(stage.source_unchanged)
        excluded = {item["path"]: item for item in stage.excluded_files}
        self.assertIn("save/config.rpgsave", excluded)
        self.assertIn("old.rpgsave", excluded)
        self.assertRegex(excluded["save/config.rpgsave"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertGreaterEqual(stage.source_file_count, stage.copied_file_count + 3)

    def test_build_rejects_malicious_manifest_before_external_android_delete(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        outside = self.root / "outside-run"
        external_staged = outside / "staged" / "www"
        external_staged.mkdir(parents=True)
        (external_staged / "index.html").write_text("not a valid owned stage", encoding="utf-8")
        external_android = outside / "android"
        external_android.mkdir(parents=True)
        sentinel = external_android / "DO-NOT-DELETE.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        forged = replace(stage, staged_www=str(external_staged), manifest_path=str(outside / "stage-manifest.json"))
        template = self.root / "template"
        template.mkdir()
        with self.assertRaises(BlockedError):
            BuildService().prepare_template(template, forged, self._config())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_marker_scoped_cleanup_rejects_unmarked_directory(self) -> None:
        report = inspect_game(self.game)
        work_base = self.root / ".work"
        stage = StageService().stage(report, work_base, minimum_free_bytes=0)
        work_dir = Path(stage.manifest_path).parents[2]
        safe_remove_workdir(work_dir, work_base, stage.project_id)
        self.assertFalse(work_dir.exists())
        unsafe = work_base / "unsafe"
        unsafe.mkdir(parents=True)
        with self.assertRaises(BlockedError):
            safe_remove_workdir(unsafe, work_base, "project-x")

    def test_patch_requires_unique_point_and_writes_versioned_config(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        result = patch_staged_www(stage.staged_www, self._config())
        self.assertEqual(result["injectionCount"], 1)
        index = Path(stage.staged_www, "index.html").read_text(encoding="utf-8")
        self.assertEqual(index.count("game2apk-input.js"), 1)
        self.assertEqual(load_android_config(Path(stage.staged_www, "game2apk-config.json"))["schemaVersion"], 1)
        controls = load_android_config(Path(stage.staged_www, "game2apk-config.json"))["buttons"]
        self.assertEqual(next(button["keyCode"] for button in controls if button["id"] == "portrait"), 65)
        Path(stage.staged_www, "index.html").write_text(index.replace('js/rpg_core.js', 'js/rpg_core.js"></script><script src="js/rpg_core.js'), encoding="utf-8")
        with self.assertRaises(BlockedError):
            patch_staged_www(stage.staged_www, self._config())

    def test_safe_extraction_and_placeholder_validation(self) -> None:
        entries = extract_safe_entries(self.www)
        kinds = {entry.kind for entry in entries}
        self.assertTrue({"database-field", "message", "choice", "scroll-text", "system-term"}.issubset(kinds))
        self.assertFalse(any("do not translate" in entry.source_text for entry in entries))
        message = next(entry for entry in entries if entry.kind == "message")
        self.assertEqual(len(message.segments), 2)
        self.assertTrue(any(entry.kind == "speaker-name" and entry.source_text == "Speaker" for entry in entries))
        scroll = next(entry for entry in entries if entry.kind == "scroll-text")
        self.assertEqual(scroll.segments, ["Scroll text", "Second scroll line"])
        self.assertTrue(validate_placeholders("HP \\N[1] %1", "生命 \\N[1] %1")[0])
        self.assertFalse(validate_placeholders("HP \\N[1]", "生命")[0])

    def test_japanese_kana_prevents_chinese_skip_heuristic(self) -> None:
        entries = extract_safe_entries(self.www)
        self.assertTrue(any("Hello world" in entry.source_text for entry in entries))
        from game2apk.models import TranslationEntry

        japanese = TranslationEntry("ja", "Map001.json", "message", "message", ["漢字かな混じりの文章"], ["/x"], "x", [[]])
        chinese = TranslationEntry("zh", "Map001.json", "message", "message", ["这是中文文本"], ["/x"], "y", [[]])
        from game2apk.translation import recommend_skip_translation

        self.assertFalse(recommend_skip_translation([japanese]))
        self.assertTrue(recommend_skip_translation([chinese]))
        mainly_chinese = TranslationEntry("mixed", "Map001.json", "message", "message", ["\u4e2d" * 200 + "\u3042\u3044"], ["/x"], "z", [[]])
        self.assertTrue(recommend_skip_translation([mainly_chinese]))

    def test_fake_translation_applies_and_cache_recovers(self) -> None:
        first_www = self.root / "first-www"
        second_www = self.root / "second-www"
        import shutil

        shutil.copytree(self.www, first_www)
        shutil.copytree(self.www, second_www)
        cache = self.root / "state" / "translation-memory.json"

        def responder(payload):
            items = json.loads(payload["messages"][-1]["content"].split("INPUT=", 1)[1])
            translated = [{"id": item["id"], "segments": [segment.replace("Hello", "你好").replace("Potion", "药水") for segment in item["segments"]]} for item in items]
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"translations": translated}, ensure_ascii=False)}}]}

        transport = FakeTransport(responder=responder)
        first = TranslationService().translate(first_www, model="deepseek-v4-flash", api_key="fake", transport=transport, memory_path=cache, confirmed_third_party=True, force=True)
        self.assertGreater(first.entries_applied, 0)
        self.assertGreater(len(transport.calls), 0)
        second_transport = FakeTransport(responder=lambda payload: self.fail("cache should avoid API chat"))
        second = TranslationService().translate(second_www, model="deepseek-v4-flash", api_key="fake", transport=second_transport, memory_path=cache, confirmed_third_party=True, force=True)
        self.assertGreater(second.entries_cached, 0)
        self.assertEqual(len(second_transport.calls), 0)
        self.assertIn("你好", (first_www / "data" / "Map001.json").read_text(encoding="utf-8"))

    def test_bad_translation_is_not_applied(self) -> None:
        entries = extract_safe_entries(self.www)
        entry = next(entry for entry in entries if entry.kind == "message")
        failures = apply_translations(self.www, [entry], {entry.entry_id: ["only one line"]})
        self.assertEqual(failures[0].reason, "segment count mismatch")
        self.assertIn("Hello world", (self.www / "data" / "Map001.json").read_text(encoding="utf-8"))

    def test_command_generation_and_log_redaction(self) -> None:
        command = BuildService()._command(str(self.root / "template with space" / "gradlew.bat"))
        self.assertEqual(command[0].lower().endswith("cmd.exe"), True)
        self.assertIn("assembleRelease", command)
        self.assertIn("--no-daemon", command)
        self.assertNotIn("sk-test-secret", redact_text("Bearer sk-test-secret"))
        self.assertIn("<redacted>", redact_text("Bearer sk-test-secret"))

    def test_subst_drive_choice_commands_and_cleanup(self) -> None:
        project_id = "project-ascii-test"
        project_dir = self.root / "中文" / project_id
        create_work_marker(project_dir, project_id, self.game)
        calls = []

        def runner(command):
            calls.append(command)
            if len(command) == 1:
                return 0, "S: => F:\\somewhere"
            return 0, ""

        with mock.patch("game2apk.builder._has_non_ascii", return_value=True):
            mapper = AsciiPathMapper(project_dir, project_id, runner=runner)
            with mapper:
                self.assertEqual(mapper.drive, "T")
                self.assertEqual(mapper.mapped_path(project_dir / "runs"), Path("T:\\") / "runs")
            self.assertFalse(mapper.active)
        self.assertEqual(calls[1][1:3], ["T:", str(project_dir)])
        self.assertEqual(calls[2][1:3], ["T:", "/D"])

    def test_subst_cleanup_runs_when_gradle_runner_fails(self) -> None:
        class FakeMapper:
            active = True

            def __init__(self):
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.closed = True

            def mapped_path(self, path):
                return Path(path)

        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        patch_staged_www(stage.staged_www, self._config())
        template = self.root / "template-failure"
        (template / "app" / "src" / "main").mkdir(parents=True)
        (template / "app" / "build.gradle").write_text("android {}", encoding="utf-8")
        mapper = FakeMapper()

        def failing_runner(*_args):
            raise RuntimeError("synthetic Gradle failure")

        with self.assertRaises(RuntimeError):
            BuildService(runner=failing_runner, mapper_factory=lambda *_args: mapper).build(
                template,
                stage,
                self._config(),
                toolchain=ToolchainInfo("sdk", "jdk", "gradle", str(template / "gradlew"), "aapt2", "zipalign", "apksigner", None, []),
            )
        self.assertTrue(mapper.closed)

    def test_config_rejects_unknown_schema(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_android_config(self.root / "missing.json")
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"schemaVersion": 99}), encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_android_config(bad)
        with self.assertRaises(ConfigurationError):
            build_config(version_code=0)

    def test_build_verify_fixture_end_to_end_without_real_gradle(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        patch_staged_www(stage.staged_www, self._config())
        template = self.root / "template"
        (template / "app" / "src" / "main" / "assets").mkdir(parents=True)
        (template / "app" / "src" / "main" / "res" / "values").mkdir(parents=True)
        (template / "app" / "build.gradle").write_text("plugins {}\nandroid { applicationId '@@APPLICATION_ID@@' versionCode @@VERSION_CODE@@ versionName '@@VERSION_NAME@@' }", encoding="utf-8")
        (template / "settings.gradle").write_text("rootProject.name = 'fixture'\ninclude ':app'\n", encoding="utf-8")
        (template / "app" / "src" / "main" / "res" / "values" / "strings.xml").write_text('<resources><string name="app_name">@@APP_NAME@@</string></resources>', encoding="utf-8")
        (template / "app" / "src" / "main" / "AndroidManifest.xml").write_text('<manifest package="@@APPLICATION_ID@@"><application android:debuggable="true" android:label="@string/app_name"/></manifest>', encoding="utf-8")

        def fake_runner(command, cwd, env, log_path, progress, cancel_event):
            apk = cwd / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
            apk.parent.mkdir(parents=True)
            with zipfile.ZipFile(apk, "w") as archive:
                for path in (cwd / "app" / "src" / "main" / "assets").rglob("*"):
                    if path.is_file():
                        archive.write(path, "assets/" + path.relative_to(cwd / "app" / "src" / "main" / "assets").as_posix())
            log_path.write_text("Gradle fake complete", encoding="utf-8")
            return 0, False

        toolchain = ToolchainInfo("sdk", "jdk", "gradle", str(template / "gradlew"), "aapt2", "zipalign", "apksigner", None, [])
        result = BuildService(runner=fake_runner).build(template, stage, self._config(), toolchain=toolchain)
        self.assertEqual(result.return_code, 0)
        self.assertTrue(result.apk_path)
        rendered_settings = Path(result.work_dir) / "settings.gradle"
        self.assertNotIn("android { androidResources", rendered_settings.read_text(encoding="utf-8"))
        def fake_tool(command):
            if "aapt2" in command[0]:
                return 0, "package: name='com.game2apk.xianyaoshengcanver22' versionCode='4' versionName='1.0.3'\napplication: label='Demo' icon='@drawable/game2apk_launcher'\ndebuggable=false"
            if "apksigner" in command[0]:
                return 0, "Verified using v2 scheme\nSigner #1 certificate SHA-256 digest: AA:BB"
            return 0, "Verification successful"

        with mock.patch("game2apk.verifier._run", side_effect=fake_tool):
            verified = VerificationService().verify(result.apk_path, toolchain, result.started_at_utc, expected_application_id=self._config().application_id, expected_version_code=4)
        self.assertTrue(verified.passed)
        self.assertTrue(verified.signature_candidate)
        self.assertFalse(verified.device["verified"])
        self.assertTrue(verified.permissions["passed"])
        self.assertTrue(verified.stage_assets["passed"])

    def test_signing_state_never_reports_plain_password(self) -> None:
        status = SigningService(self.root / ".state").status("com.game2apk.test")
        serialized = json.dumps(status, ensure_ascii=False)
        self.assertIn("keystoreExists", serialized)
        self.assertNotIn("password", status)


if __name__ == "__main__":
    unittest.main()
