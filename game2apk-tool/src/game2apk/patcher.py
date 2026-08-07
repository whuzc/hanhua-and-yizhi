"""Deterministic input-bridge injection into a staged MV copy."""

from __future__ import annotations

import re
from pathlib import Path

from .config import write_android_config
from .errors import BlockedError
from .models import BuildConfig
from .security import atomic_write_text, assert_no_secrets, require_within


_CORE_SCRIPT = re.compile(
    r"<script\b(?=[^>]*\bsrc\s*=\s*[\"'](?:\./)?js/rpg_core\.js[\"'])[^>]*>\s*</script>",
    re.IGNORECASE,
)
_BRIDGE_SCRIPT = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"'](?:\./)?js/game2apk-input\.js[\"'][^>]*>\s*</script>", re.IGNORECASE)

BRIDGE_SOURCE = r"""/* game2apk-tool input bridge, schema-compatible with Android v1. */
(function (global) {
  'use strict';
  var bridge = global.Game2ApkInput = global.Game2ApkInput || {};
  bridge.configUrl = 'game2apk-config.json';
  bridge._keyEvent = function (keyCode, type) {
    if (!global.Input) return false;
    var handler = type === 'up' ? global.Input._onKeyUp : global.Input._onKeyDown;
    if (typeof handler !== 'function') return false;
    handler.call(global.Input, { keyCode: Number(keyCode), which: Number(keyCode), preventDefault: function () {} });
    return true;
  };
  bridge.keyDown = function (keyCode) { return bridge._keyEvent(keyCode, 'down'); };
  bridge.keyUp = function (keyCode) { return bridge._keyEvent(keyCode, 'up'); };
  bridge.getConfig = function () { return global.GAME2APK_CONFIG || null; };
  global.game2apkInputBridge = bridge;
}(window));
"""


def _assert_staged(staged_www: Path) -> None:
    for parent in (staged_www, *staged_www.parents):
        if (parent / ".game2apk-work-marker.json").is_file():
            return
    raise BlockedError("patching requires a marker-protected .work staging directory")


def _read_index(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            return text, encoding
        except UnicodeDecodeError:
            continue
    raise BlockedError(f"index.html is not a supported text encoding: {path}")


def patch_staged_www(staged_www: str | Path, build_config: BuildConfig | dict) -> dict[str, str | int]:
    root = Path(staged_www).resolve(strict=True)
    _assert_staged(root)
    index_path = root / "index.html"
    core_path = root / "js" / "rpg_core.js"
    if not index_path.is_file() or not core_path.is_file():
        raise BlockedError("staged MV copy is missing index.html or js/rpg_core.js")
    index, encoding = _read_index(index_path)
    core_matches = list(_CORE_SCRIPT.finditer(index))
    bridge_matches = list(_BRIDGE_SCRIPT.finditer(index))
    if len(core_matches) != 1:
        raise BlockedError(f"expected exactly one rpg_core.js injection point, found {len(core_matches)}")
    if bridge_matches:
        raise BlockedError("game2apk-input.js is already referenced; refusing duplicate injection")
    bridge_path = root / "js" / "game2apk-input.js"
    if bridge_path.exists():
        raise BlockedError("game2apk-input.js already exists in staging; refusing overwrite")
    if isinstance(build_config, BuildConfig):
        config_data = {
            "schemaVersion": 1,
            "appName": build_config.app_name,
            "applicationId": build_config.application_id,
            "versionCode": build_config.version_code,
            "versionName": build_config.version_name,
            "control": build_config.control_config,
        }
    else:
        config_data = dict(build_config)
    assert_no_secrets(config_data)
    newline = "\r\n" if "\r\n" in index else "\n"
    insertion = newline + "    <script type=\"text/javascript\" src=\"js/game2apk-input.js\"></script>"
    patched = index[: core_matches[0].end()] + insertion + index[core_matches[0].end() :]
    atomic_write_text(index_path, patched, encoding="utf-8-sig" if encoding == "utf-8-sig" else "utf-8")
    atomic_write_text(bridge_path, BRIDGE_SOURCE.replace("\n", newline))
    config_path = root / "game2apk-config.json"
    write_android_config(config_path, config_data)
    return {"index": str(index_path), "bridge": str(bridge_path), "config": str(config_path), "injectionCount": 1}

