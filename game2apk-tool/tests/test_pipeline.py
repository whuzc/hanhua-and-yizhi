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

from game2apk.builder import ALIYUN_GRADLE_DISTRIBUTION, OFFICIAL_GRADLE_DISTRIBUTION, AsciiPathMapper, BuildService
from game2apk.cheat_catalog import (
    advanced_cheat_catalog,
    normalize_advanced_cheat_variable_ids,
)
from game2apk.config import build_config, default_control_config, load_android_config
from game2apk.errors import BlockedError, ConfigurationError
from game2apk.inspector import inspect_game
from game2apk.models import BuildConfig, ToolchainInfo, TranslationFailure, TranslationReport
from game2apk.patcher import patch_staged_www
from game2apk.pipeline import PipelineService
from game2apk.security import create_work_marker, redact_text, safe_cleanup_run_artifacts, safe_remove_workdir
from game2apk.signing import SigningService
from game2apk.staging import StageService
from game2apk.translation import (
    FakeTransport,
    TranslationService,
    apply_translations,
    extract_safe_entries,
    filter_non_chinese_entries,
    translation_language_profile,
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
        (self.www / "js" / "rpg_managers.js").write_text(
            """AudioManager.audioFileExt = function() {
    if (WebAudio.canPlayOgg() && !Utils.isMobileDevice()) {
        return '.ogg';
    } else {
        return '.m4a';
    }
};
""",
            encoding="utf-8",
        )
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
        self.assertEqual(data["versionCode"], 9)
        self.assertEqual(data["versionName"], "1.4.0")

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

    def test_stage_resume_reuses_only_matching_prebuild_checkpoint(self) -> None:
        report = inspect_game(self.game)
        work_base = self.root / ".work"
        first = StageService().stage(report, work_base, minimum_free_bytes=0, resume_key="resume-key")
        StageService.mark_prepared(first)

        resumed = StageService().stage(
            report,
            work_base,
            minimum_free_bytes=0,
            resume=True,
            resume_key="resume-key",
        )
        self.assertTrue(resumed.resumed_from_existing)
        self.assertEqual(resumed.run_id, first.run_id)
        self.assertEqual(resumed.staged_www, first.staged_www)

        fresh = StageService().stage(
            report,
            work_base,
            minimum_free_bytes=0,
            resume=True,
            resume_key="different-key",
        )
        self.assertFalse(fresh.resumed_from_existing)
        self.assertNotEqual(fresh.run_id, first.run_id)

    def test_template_uses_aliyun_gradle_distribution_and_maven_fallbacks(self) -> None:
        template = Path(__file__).resolve().parents[1] / "templates" / "android-rpgmv"
        wrapper = (template / "gradle" / "wrapper" / "gradle-wrapper.properties").read_text(encoding="utf-8")
        settings = (template / "settings.gradle").read_text(encoding="utf-8")
        self.assertIn(
            "mirrors.aliyun.com/gradle/distributions/v8.11.1/gradle-8.11.1-bin.zip",
            wrapper,
        )
        self.assertIn("maven.aliyun.com/repository/google", settings)
        self.assertIn("maven.aliyun.com/repository/public", settings)
        self.assertIn("maven.aliyun.com/repository/gradle-plugin", settings)

    def test_gradle_wrapper_mirror_failure_can_fallback_to_official_url(self) -> None:
        log = self.root / "gradle.log"
        log.write_text(
            f"Downloading {ALIYUN_GRADLE_DISTRIBUTION}\nCould not install Gradle distribution: connection reset\n",
            encoding="utf-8",
        )
        self.assertTrue(BuildService._mirror_download_failed(log))
        properties = self.root / "gradle-wrapper.properties"
        escaped_mirror = ALIYUN_GRADLE_DISTRIBUTION.replace(":", r"\:")
        properties.write_text(f"distributionUrl={escaped_mirror}\n", encoding="utf-8")
        self.assertTrue(BuildService._switch_to_official_distribution(properties))
        self.assertIn(OFFICIAL_GRADLE_DISTRIBUTION.replace(":", r"\:"), properties.read_text(encoding="utf-8"))
        log.write_text(
            f"Downloading {ALIYUN_GRADLE_DISTRIBUTION}\nCould not resolve all files for configuration ':classpath'\n",
            encoding="utf-8",
        )
        self.assertFalse(BuildService._mirror_download_failed(log))

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

    def test_run_cleanup_removes_generated_copies_but_can_keep_checkpoint(self) -> None:
        report = inspect_game(self.game)
        work_base = self.root / ".work"
        stage = StageService().stage(report, work_base, minimum_free_bytes=0)
        run_dir = Path(stage.manifest_path).parent
        android_www = run_dir / "android" / "app" / "src" / "main" / "assets" / "www"
        android_www.mkdir(parents=True)
        (android_www / "duplicate.bin").write_bytes(b"generated copy")
        pack_dir = run_dir / "resource-pack"
        pack_dir.mkdir()
        (pack_dir / "demo.g2ares").write_bytes(b"generated pack")

        removed = safe_cleanup_run_artifacts(run_dir, work_base, stage.project_id, remove_staged=False)
        self.assertEqual(set(removed), {"android", "resource-pack"})
        self.assertTrue(Path(stage.staged_www).is_dir())
        self.assertFalse((run_dir / "android").exists())
        self.assertFalse((run_dir / "resource-pack").exists())
        self.assertTrue((run_dir / "stage-manifest.json").is_file())

        # A successful promotion is allowed to discard the resumable copy as
        # well; audit JSON/log files remain in the run directory.
        removed_final = safe_cleanup_run_artifacts(run_dir, work_base, stage.project_id, remove_staged=True)
        self.assertEqual(removed_final, ("staged",))
        self.assertFalse(Path(stage.staged_www).exists())
        self.assertTrue((run_dir / "stage-manifest.json").is_file())

    def test_promote_cleans_successful_run_copies(self) -> None:
        from types import SimpleNamespace

        report = inspect_game(self.game)
        work_base = self.root / ".work"
        stage = StageService().stage(report, work_base, minimum_free_bytes=0)
        run_dir = Path(stage.manifest_path).parent
        (run_dir / "android" / "app" / "src" / "main" / "assets" / "www").mkdir(parents=True)
        (run_dir / "resource-pack").mkdir()
        fake_report = SimpleNamespace(
            report_path=str(run_dir / "verification-report.json"),
            apk_path=str(run_dir / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release-signed.apk"),
        )
        (run_dir / "verification-report.json").write_text("{}", encoding="utf-8")
        with mock.patch("game2apk.pipeline.VerificationService.promote", return_value=self.root / "dist" / "demo-signed.apk"):
            promoted = PipelineService(self.root).promote(fake_report, self._config())
        self.assertEqual(promoted, self.root / "dist" / "demo-signed.apk")
        self.assertFalse((run_dir / "staged").exists())
        self.assertFalse((run_dir / "android").exists())
        self.assertFalse((run_dir / "resource-pack").exists())
        self.assertTrue((run_dir / "stage-manifest.json").is_file())

    def test_pipeline_build_exception_cleans_generated_children_and_keeps_stage(self) -> None:
        report = inspect_game(self.game)
        work_base = self.root / ".work"
        stage = StageService().stage(report, work_base, minimum_free_bytes=0)
        run_dir = Path(stage.manifest_path).parent
        (run_dir / "android" / "partial").mkdir(parents=True)
        (run_dir / "resource-pack").mkdir()
        with mock.patch("game2apk.pipeline.BuildService") as builder_cls:
            builder_cls.return_value.build.side_effect = RuntimeError("synthetic wrapper failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic wrapper failure"):
                PipelineService(self.root).build(self.root / "template", stage, self._config())
        self.assertFalse((run_dir / "android").exists())
        self.assertFalse((run_dir / "resource-pack").exists())
        self.assertTrue(Path(stage.staged_www).is_dir())

    def test_patch_requires_unique_point_and_writes_versioned_config(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        result = patch_staged_www(stage.staged_www, self._config())
        self.assertEqual(result["injectionCount"], 1)
        self.assertEqual(result["encryptedAudioExtensionPatched"], 1)
        managers = Path(stage.staged_www, "js", "rpg_managers.js").read_text(encoding="utf-8")
        self.assertIn("if (Decrypter.hasEncryptedAudio)", managers)
        self.assertIn("return '.ogg';", managers)
        # The non-encrypted desktop branch remains intact.
        self.assertIn("!Utils.isMobileDevice()", managers)
        self.assertIn("return '.m4a';", managers)
        index = Path(stage.staged_www, "index.html").read_text(encoding="utf-8")
        self.assertEqual(index.count("game2apk-input.js"), 1)
        self.assertEqual(load_android_config(Path(stage.staged_www, "game2apk-config.json"))["schemaVersion"], 1)
        controls = load_android_config(Path(stage.staged_www, "game2apk-config.json"))["buttons"]
        self.assertEqual(next(button["keyCode"] for button in controls if button["id"] == "portrait"), 65)
        Path(stage.staged_www, "index.html").write_text(index.replace('js/rpg_core.js', 'js/rpg_core.js"></script><script src="js/rpg_core.js'), encoding="utf-8")
        with self.assertRaises(BlockedError):
            patch_staged_www(stage.staged_www, self._config())

    def test_patch_maps_mobile_audio_to_the_actual_staged_extension(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        audio = Path(stage.staged_www, "audio", "bgm")
        audio.mkdir(parents=True)
        (audio / "Theme6.ogg").write_bytes(b"OggS")
        (audio / "Theme6.m4a").write_bytes(b"m4a")
        result = patch_staged_www(stage.staged_www, self._config())
        self.assertEqual(result["audioExtensionMapEntries"], 1)
        managers = Path(stage.staged_www, "js", "rpg_managers.js").read_text(encoding="utf-8")
        self.assertIn("game2apk per-file audio extension map", managers)
        self.assertIn('"bgm/Theme6":".ogg"', managers)

    def test_advanced_cheat_selection_is_normalized_and_injected(self) -> None:
        system_path = self.www / "data" / "System.json"
        system = json.loads(system_path.read_text(encoding="utf-8"))
        system["variables"] = ["", "欲望", "", "好感度", "未选择"]
        system["switches"] = ["", "回想解锁"]
        system_path.write_text(json.dumps(system, ensure_ascii=False), encoding="utf-8")
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        data = build_config(
            control=default_control_config(),
            advanced_cheat_variable_ids=["variable:3", "variable:1", "variable:3"],
        )
        config = BuildConfig(
            data["appName"],
            data["applicationId"],
            data["versionCode"],
            data["versionName"],
            control_config=data["control"],
            advanced_cheat_variable_ids=data["advancedCheatVariableIds"],
        )
        self.assertEqual(config.advanced_cheat_variable_ids, ["variable:1", "variable:3"])
        patch_staged_www(stage.staged_www, config)
        bridge = Path(stage.staged_www, "js", "game2apk-input.js").read_text(encoding="utf-8")
        self.assertIn("cheat.selectedVariableIds = [1,3];", bridge)
        self.assertNotIn("__GAME2APK_ADVANCED_CHEAT_VARIABLE_IDS__", bridge)
        # Switch discovery remains independent and is not filtered by the
        # numeric-variable selection contract.
        self.assertIn("cheat.switchFields.push([i, label])", bridge)

    def test_advanced_cheat_selection_rejects_non_discoverable_ids(self) -> None:
        system_path = self.www / "data" / "System.json"
        system = json.loads(system_path.read_text(encoding="utf-8"))
        system["variables"] = ["", "有效变量"]
        system_path.write_text(json.dumps(system, ensure_ascii=False), encoding="utf-8")
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)
        config = replace(self._config(), advanced_cheat_variable_ids=["variable:2"])
        with self.assertRaisesRegex(ConfigurationError, "not discoverable"):
            patch_staged_www(stage.staged_www, config)

    def test_advanced_cheat_catalog_keeps_stable_ids_across_translation(self) -> None:
        source = self.root / "catalog-source"
        translated = self.root / "catalog-translated"
        (source / "data").mkdir(parents=True)
        (translated / "data").mkdir(parents=True)
        (source / "data" / "System.json").write_text(
            json.dumps({"variables": ["", "発情中", "", "Affection"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (translated / "data" / "System.json").write_text(
            json.dumps({"variables": ["", "发情中", "", "Affection"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        catalog = advanced_cheat_catalog(source, translated_www=translated, status="ready")
        self.assertEqual([item["id"] for item in catalog["items"]], ["variable:1", "variable:3"])
        self.assertEqual(catalog["items"][0]["sourceLabel"], "発情中")
        self.assertEqual(catalog["items"][0]["translatedLabel"], "发情中")
        self.assertEqual(catalog["items"][0]["displayLabel"], "发情中")

    def test_advanced_cheat_id_contract_distinguishes_default_and_empty(self) -> None:
        self.assertIsNone(normalize_advanced_cheat_variable_ids(None))
        self.assertEqual(normalize_advanced_cheat_variable_ids([]), [])
        self.assertEqual(
            normalize_advanced_cheat_variable_ids(["variable:12", "variable:2", "variable:12"]),
            ["variable:2", "variable:12"],
        )
        with self.assertRaises(ConfigurationError):
            normalize_advanced_cheat_variable_ids(["switch:1"])

    def test_advanced_cheat_selection_changes_prepared_stage_resume_key(self) -> None:
        report = inspect_game(self.game)
        service = PipelineService(self.root)
        template = self.root / "template-resume-key"
        template.mkdir()
        all_variables = self._config()
        no_variables = replace(all_variables, advanced_cheat_variable_ids=[])
        common = {
            "translate": False,
            "thinking_enabled": True,
            "reasoning_effort": "low",
        }
        self.assertNotEqual(
            service.build_resume_key(report, template, all_variables, **common),
            service.build_resume_key(report, template, no_variables, **common),
        )

    def test_cheat_catalog_preview_translates_disposable_copy_only(self) -> None:
        system_path = self.www / "data" / "System.json"
        system = json.loads(system_path.read_text(encoding="utf-8"))
        system.update(
            {
                "locale": "ja_JP",
                "variables": ["", "発情中"],
                "switches": [""],
            }
        )
        system_path.write_text(json.dumps(system, ensure_ascii=False), encoding="utf-8")
        original_bytes = system_path.read_bytes()
        inspection = inspect_game(self.game)

        def responder(payload):
            items = json.loads(payload["messages"][-1]["content"].split("INPUT=", 1)[1])
            translated = [
                {"id": item["id"], "segments": ["发情中"]}
                for item in items
            ]
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"translations": translated}, ensure_ascii=False)},
                    }
                ]
            }

        catalog, translation = PipelineService(self.root).preview_cheat_catalog(
            inspection,
            model="deepseek-v4-flash",
            api_key="fake",
            transport=FakeTransport(responder=responder),
            confirmed_third_party=True,
            thinking_enabled=False,
        )
        self.assertIsNotNone(translation)
        self.assertEqual(catalog["status"], "ready")
        self.assertEqual(catalog["items"][0]["id"], "variable:1")
        self.assertEqual(catalog["items"][0]["sourceLabel"], "発情中")
        self.assertEqual(catalog["items"][0]["translatedLabel"], "发情中")
        self.assertEqual(system_path.read_bytes(), original_bytes)
        # Cheat-label preview must not deserialize or overwrite the potentially
        # huge body translation cache. It owns a separate cache for labels.
        self.assertTrue((self.root / ".state" / "cheat-label-translation-memory.json").is_file())
        self.assertFalse((self.root / ".state" / "translation-memory.json").exists())

    def test_body_pass_does_not_invalidate_cheat_preview_cache(self) -> None:
        """A previewed label is applied from cache during build, without a second API call."""

        from types import SimpleNamespace

        system_path = self.www / "data" / "System.json"
        system = json.loads(system_path.read_text(encoding="utf-8"))
        system.update(
            {
                "locale": "ja_JP",
                "variables": ["", "\u767a\u60c5\u4e2d"],
                "switches": [""],
            }
        )
        system_path.write_text(json.dumps(system, ensure_ascii=False), encoding="utf-8")

        def responder(payload):
            items = json.loads(payload["messages"][-1]["content"].split("INPUT=", 1)[1])
            translated = [
                {"id": item["id"], "segments": ["\u53d1\u60c5\u4e2d"]}
                for item in items
            ]
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"translations": translated}, ensure_ascii=False)},
                    }
                ]
            }

        service = PipelineService(self.root)
        inspection = inspect_game(self.game)
        _catalog, preview = service.preview_cheat_catalog(
            inspection,
            model="deepseek-v4-flash",
            api_key="fake",
            transport=FakeTransport(responder=responder),
            confirmed_third_party=True,
            thinking_enabled=False,
        )
        self.assertIsNotNone(preview)
        # The ordinary full-text pass runs after the UI preview in a real
        # build.  It must leave System.json labels untouched so their strict
        # cache keys still match the preview result.
        stage = SimpleNamespace(staged_www=str(self.www), manifest_path=None)
        service.translate(
            stage,
            api_key="fake",
            transport=FakeTransport(),
            confirmed_third_party=True,
            force=True,
            thinking_enabled=False,
        )
        final_transport = FakeTransport(responder=lambda _payload: self.fail("preview cache should avoid API chat"))
        final = service.translate_cheat_labels(
            stage,
            api_key="fake",
            transport=final_transport,
            confirmed_third_party=True,
            thinking_enabled=False,
        )
        self.assertEqual(final.api_requests, 0)
        self.assertGreaterEqual(final.entries_cached, 1)
        self.assertEqual(final_transport.calls, [])

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

    def test_system_variable_and_switch_labels_are_translation_entries(self) -> None:
        labels_www = self.root / "labels-www"
        (labels_www / "data").mkdir(parents=True)
        (labels_www / "data" / "System.json").write_text(
            json.dumps(
                {
                    "gameTitle": "Label demo",
                    "terms": {},
                    "variables": ["", "淫乱等级", "Sensitivity"],
                    "switches": ["", "回想解锁", "Gallery unlocked"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        entries = extract_safe_entries(labels_www)
        labels = {(entry.kind, entry.locations[0], entry.source_text) for entry in entries}
        self.assertIn(("system-variable", "/variables/1", "淫乱等级"), labels)
        self.assertIn(("system-variable", "/variables/2", "Sensitivity"), labels)
        self.assertIn(("system-switch", "/switches/1", "回想解锁"), labels)
        self.assertIn(("system-switch", "/switches/2", "Gallery unlocked"), labels)

    def test_japanese_locale_triggers_strict_cheat_pass_for_han_only_labels(self) -> None:
        from types import SimpleNamespace

        labels_www = self.root / "ja-labels-www"
        (labels_www / "data").mkdir(parents=True)
        (labels_www / "data" / "System.json").write_text(
            json.dumps(
                {
                    "locale": "ja_JP",
                    "gameTitle": "Demo",
                    "terms": {},
                    "variables": ["", "拘束中", "淫乱"],
                    "switches": ["", "屋外"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        stage = SimpleNamespace(staged_www=str(labels_www))
        self.assertTrue(PipelineService(self.root).cheat_labels_need_translation(stage))

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

    def test_translation_language_profile_explains_chinese_default(self) -> None:
        entries = extract_safe_entries(self.www)
        profile = translation_language_profile(entries)
        self.assertGreater(profile["characters"], 0)
        self.assertFalse(profile["defaultTranslate"])
        self.assertTrue(profile["translationRecommended"])
        from game2apk.models import TranslationEntry

        chinese = TranslationEntry("zh", "Map001.json", "message", "message", ["这是中文文本"], ["/x"], "y", [[]])
        chinese_profile = translation_language_profile([chinese])
        self.assertTrue(chinese_profile["likelyChinese"])
        self.assertFalse(chinese_profile["translationRecommended"])

    def test_translation_only_sends_non_chinese_blocks_and_protects_mixed_context(self) -> None:
        from game2apk.models import TranslationEntry
        from game2apk.translation import _protect_provider_segment, _restore_protected_segment

        chinese = TranslationEntry("zh-only", "Map001.json", "message", "message", ["\u4e2d\u6587\u5bf9\u8bdd"], ["/x"], "zh", [[]])
        english = TranslationEntry("en-only", "Map001.json", "message", "message", ["Hello world"], ["/x"], "en", [[]])
        mixed = TranslationEntry("mixed", "Map001.json", "message", "message", ["\u4e2d\u6587 Hello"], ["/x"], "mixed", [[]])
        selected = filter_non_chinese_entries([chinese, english, mixed])
        self.assertEqual([entry.entry_id for entry in selected], ["en-only", "mixed"])

        protected = _protect_provider_segment(mixed.segments[0])
        self.assertIn("__G2A_KEEP_HAN_000__", protected)
        restored, error = _restore_protected_segment(mixed.segments[0], "__G2A_KEEP_HAN_000__ hello")
        self.assertIsNone(error)
        self.assertEqual(restored, "\u4e2d\u6587 hello")

        import shutil

        filtered_www = self.root / "filtered-www"
        (filtered_www / "data").mkdir(parents=True)
        (filtered_www / "data" / "System.json").write_text(
            json.dumps({"gameTitle": "\u4e2d\u6587\u6e38\u620f", "terms": {"basic": ["Fight"]}}, ensure_ascii=False),
            encoding="utf-8",
        )
        transport = FakeTransport()
        report = TranslationService().translate(
            filtered_www,
            model="deepseek-v4-flash",
            api_key="fake",
            transport=transport,
            memory_path=self.root / "state" / "translation-memory.json",
            confirmed_third_party=True,
            force=True,
        )
        self.assertEqual(report.source_entries_total, 2)
        self.assertEqual(report.entries_total, 1)
        self.assertEqual(report.entries_skipped_chinese, 1)
        self.assertEqual(report.entries_applied, 1)
        self.assertEqual(report.modified_files, ["data/System.json"])
        payload_items = json.loads(transport.calls[0]["messages"][-1]["content"].split("INPUT=", 1)[1])
        self.assertEqual(len(payload_items), 1)
        self.assertNotIn("\u4e2d\u6587", json.dumps(payload_items, ensure_ascii=False))

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

    def test_pipeline_records_translation_allowlist_in_stage_manifest(self) -> None:
        report = inspect_game(self.game)
        stage = StageService().stage(report, self.root / ".work", minimum_free_bytes=0)

        def responder(payload):
            items = json.loads(payload["messages"][-1]["content"].split("INPUT=", 1)[1])
            translated = [
                {"id": item["id"], "segments": [segment.replace("Hello", "你好") for segment in item["segments"]]}
                for item in items
            ]
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"translations": translated}, ensure_ascii=False)}}]}

        translation = PipelineService(self.root).translate(
            stage,
            model="deepseek-v4-flash",
            api_key="fake",
            transport=FakeTransport(responder=responder),
            confirmed_third_party=True,
            force=True,
        )
        self.assertIn("data/Map001.json", translation.modified_files)
        manifest = json.loads(Path(stage.manifest_path).read_text(encoding="utf-8"))
        self.assertIn("data/Map001.json", manifest["allowedModifiedFiles"])

    def test_body_translation_failures_continue_with_warning(self) -> None:
        from types import SimpleNamespace

        report = TranslationReport(
            schema_version=1,
            source_language="ja",
            target_language="zh-CN",
            model="deepseek-v4-flash",
            entries_total=50,
            entries_applied=49,
            entries_cached=0,
            failures=[TranslationFailure("body-49", "synthetic untranslated block", "原文")],
            report_path=str(self.root / "body-report.json"),
        )
        progress: list[tuple[str, float, str]] = []
        progress_sink = lambda stage_name, fraction, message: progress.append((stage_name, fraction, message))
        with mock.patch("game2apk.pipeline.TranslationService") as service_cls:
            service_cls.return_value.translate.return_value = report
            result = PipelineService(self.root, progress=progress_sink).translate(
                SimpleNamespace(staged_www=str(self.www), manifest_path=None),
                api_key="not-a-real-key",
            )
        self.assertIs(result, report)
        self.assertTrue(report.continued_with_failures)
        self.assertEqual(report.failure_count, 1)
        self.assertAlmostEqual(report.failure_ratio, 0.02)
        self.assertTrue(any("正文" in message and "保留原文" in message for _stage, _fraction, message in progress))
        persisted = json.loads((self.root / "body-report.json").read_text(encoding="utf-8"))
        self.assertTrue(persisted["continuedWithFailures"])
        self.assertEqual(persisted["failureCount"], 1)

    def test_body_translation_many_failures_do_not_block_artifact(self) -> None:
        from types import SimpleNamespace

        report = TranslationReport(
            schema_version=1,
            source_language="ja",
            target_language="zh-CN",
            model="deepseek-v4-flash",
            entries_total=50,
            entries_applied=0,
            entries_cached=0,
            failures=[
                TranslationFailure(f"body-{index}", "synthetic provider truncation", "原文")
                for index in range(50)
            ],
            report_path=str(self.root / "body-report-many-failures.json"),
        )
        progress: list[tuple[str, float, str]] = []
        progress_sink = lambda stage_name, fraction, message: progress.append((stage_name, fraction, message))
        with mock.patch("game2apk.pipeline.TranslationService") as service_cls:
            service_cls.return_value.translate.return_value = report
            result = PipelineService(self.root, progress=progress_sink).translate(
                SimpleNamespace(staged_www=str(self.www), manifest_path=None),
                api_key="not-a-real-key",
            )
        self.assertIs(result, report)
        self.assertTrue(report.continued_with_failures)
        self.assertEqual(report.failure_count, 50)
        self.assertAlmostEqual(report.failure_ratio, 1.0)
        self.assertTrue(any("正文" in message and "继续构建" in message for _stage, _fraction, message in progress))

    def test_cheat_label_failures_do_not_block_artifact(self) -> None:
        from types import SimpleNamespace

        report = TranslationReport(
            schema_version=1,
            source_language="ja",
            target_language="zh-CN",
            model="deepseek-v4-flash",
            entries_total=50,
            entries_applied=0,
            entries_cached=0,
            failures=[
                TranslationFailure(f"label-{index}", "synthetic label failure", "ラベル")
                for index in range(50)
            ],
            report_path=str(self.root / "label-report.json"),
        )
        progress: list[tuple[str, float, str]] = []
        progress_sink = lambda stage_name, fraction, message: progress.append((stage_name, fraction, message))
        with mock.patch("game2apk.pipeline.TranslationService") as service_cls:
            service_cls.return_value.translate.return_value = report
            result = PipelineService(self.root, progress=progress_sink).translate_cheat_labels(
                SimpleNamespace(staged_www=str(self.www), manifest_path=None),
                api_key="not-a-real-key",
            )
        self.assertIs(result, report)
        self.assertTrue(report.continued_with_failures)
        self.assertAlmostEqual(report.failure_ratio, 1.0)
        self.assertTrue(any("作弊标签" in message and "保留原文" in message for _stage, _fraction, message in progress))

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
                return 0, "package: name='com.game2apk.xianyaoshengcanver22' versionCode='9' versionName='1.4.0'\napplication: label='Demo' icon='@drawable/game2apk_launcher'\ndebuggable=false"
            if "apksigner" in command[0]:
                return 0, "Verified using v2 scheme\nSigner #1 certificate SHA-256 digest: AA:BB"
            return 0, "Verification successful"

        with mock.patch("game2apk.verifier._run", side_effect=fake_tool):
            verified = VerificationService().verify(result.apk_path, toolchain, result.started_at_utc, expected_application_id=self._config().application_id, expected_version_code=9)
            self.assertTrue(verified.passed)
            self.assertTrue(verified.signature_candidate)
            self.assertFalse(verified.device["verified"])
            self.assertTrue(verified.permissions["passed"])
            self.assertTrue(verified.stage_assets["passed"])

    def test_signing_renames_gradle_unsigned_output_after_signing(self) -> None:
        apk = self.root / "app-release-unsigned.apk"
        apk.write_bytes(b"not-a-real-apk")
        idsig = Path(str(apk) + ".idsig")
        idsig.write_bytes(b"signature-id")
        keystore = self.root / "game2apk.keystore"
        keystore.write_bytes(b"keystore")
        service = SigningService(self.root / ".state")

        with mock.patch.object(
            service,
            "_ensure_keystore",
            return_value=({"keystore": str(keystore)}, "secret"),
        ):
            report = service.sign_apk(
                apk,
                "com.game2apk.test",
                apksigner="apksigner",
                runner=lambda _command: (0, "signed"),
            )

        signed = self.root / "app-release-signed.apk"
        self.assertFalse(apk.exists())
        self.assertTrue(signed.exists())
        self.assertFalse(idsig.exists())
        self.assertTrue(Path(str(signed) + ".idsig").exists())
        self.assertEqual(report["inputApk"], str(apk.resolve()))
        self.assertEqual(report["finalSignedApk"], str(signed.resolve()))
        self.assertEqual(report["outputRole"], "final signed release APK")

    def test_signing_state_never_reports_plain_password(self) -> None:
        status = SigningService(self.root / ".state").status("com.game2apk.test")
        serialized = json.dumps(status, ensure_ascii=False)
        self.assertIn("keystoreExists", serialized)
        self.assertNotIn("password", status)


if __name__ == "__main__":
    unittest.main()
