from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from game2apk.resource_pack import (  # noqa: E402
    create_resource_pack,
    plan_resource_pack,
)
from game2apk.verifier import _critical_assets, _stage_resource_pack_check  # noqa: E402


class ResourcePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.www = self.root / "www"
        (self.www / "js").mkdir(parents=True)
        (self.www / "data").mkdir()
        (self.www / "save").mkdir()
        (self.www / "index.html").write_text("<!doctype html>", encoding="utf-8")
        (self.www / "js" / "rpg_core.js").write_text("window.RPGCore = true;", encoding="utf-8")
        (self.www / "js" / "game2apk-input.js").write_text("window.Game2ApkInput = {};", encoding="utf-8")
        (self.www / "data" / "System.json").write_text("{}", encoding="utf-8")
        (self.www / "save" / "global.rpgsave").write_text("must not ship", encoding="utf-8")
        (self.www / "discard.rpgsave").write_text("must not ship", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_small_project_stays_in_apk_mode(self) -> None:
        plan = plan_resource_pack(self.www)
        self.assertFalse(plan.enabled)
        self.assertGreater(plan.file_count, 0)

    def test_large_project_creates_zip64_pack_and_verifier_accepts_manifest(self) -> None:
        # Make the threshold tiny so the fixture exercises the same branch as
        # a multi-gigabyte game without allocating gigabytes in the test.
        with mock.patch("game2apk.resource_pack.APK_SAFE_PAYLOAD_BYTES", 1):
            plan = plan_resource_pack(self.www)
        self.assertTrue(plan.enabled)

        pack = self.root / "resource-pack" / "resources.g2ares"
        artifact = create_resource_pack(
            self.www,
            pack,
            project_id="fixture-project",
            source_snapshot_sha256="a" * 64,
        )
        self.assertEqual(artifact.file_name, "resources.g2ares")
        self.assertTrue(pack.is_file())
        with zipfile.ZipFile(pack) as archive:
            names = set(archive.namelist())
            self.assertIn("www/index.html", names)
            self.assertIn("www/js/rpg_core.js", names)
            self.assertNotIn("www/save/global.rpgsave", names)
            self.assertNotIn("www/discard.rpgsave", names)
            manifest = json.loads(archive.read("game2apk-resource.json"))
        config = {**plan.to_dict(), "mode": "external", **artifact.config_dict()}
        checked = _stage_resource_pack_check(pack, config)
        self.assertTrue(checked["passed"], checked)
        self.assertEqual(manifest["projectId"], "fixture-project")
        self.assertEqual(manifest["fileCount"], artifact.file_count)

    def test_external_apk_does_not_require_bridge_in_apk_assets(self) -> None:
        apk = self.root / "external.apk"
        resource_config = {
            "schemaVersion": 1,
            "projectId": "fixture-project",
            "fileName": "resources.g2ares",
            "fileCount": 10,
            "sourceBytes": 20,
            "packBytes": 30,
            "packSha256": "a" * 64,
            "entryRoot": "www",
            "startPath": "index.html",
        }
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("assets/www/index.html", "<html></html>")
            archive.writestr("assets/www/js/rpg_core.js", "window.RPGCore=true;")
            archive.writestr("assets/game2apk/config.json", "{}")
            archive.writestr("assets/game2apk/resource-pack.json", json.dumps(resource_config))
        checked = _critical_assets(apk)
        self.assertTrue(checked["passed"], checked)
        self.assertNotIn("assets/www/js/game2apk-input.js", checked["required"])


if __name__ == "__main__":
    unittest.main()
