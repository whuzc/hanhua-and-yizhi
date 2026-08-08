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

# RPG Maker MV normally selects ``.m4a`` on mobile browsers.  Encrypted MV
# games distributed by this tool contain only ``.rpgmvo`` (the encrypted
# form of OGG), so that default produces a ``.rpgmvm`` request and a 404 in
# Android WebView.  Keep the patch narrowly scoped to encrypted audio: the
# original desktop/unencrypted extension selection remains unchanged.
_AUDIO_FILE_EXT = re.compile(
    r"AudioManager\.audioFileExt\s*=\s*function\s*\(\)\s*\{"
    r"\s*if\s*\(WebAudio\.canPlayOgg\(\)\s*&&\s*!Utils\.isMobileDevice\(\)\)\s*\{"
    r"\s*return\s*['\"]\.ogg['\"]\s*;\s*\}"
    r"\s*else\s*\{\s*return\s*['\"]\.m4a['\"]\s*;\s*\}"
    r"\s*\}\s*;",
    re.IGNORECASE,
)

_AUDIO_FILE_EXT_PATCH = """AudioManager.audioFileExt = function() {
    // Android WebView reports a mobile user agent, but this project ships
    // encrypted OGG assets (*.rpgmvo), not encrypted M4A (*.rpgmvm).
    if (Decrypter.hasEncryptedAudio) {
        return '.ogg';
    }
    if (WebAudio.canPlayOgg() && !Utils.isMobileDevice()) {
        return '.ogg';
    } else {
        return '.m4a';
    }
};"""

BRIDGE_SOURCE = r"""/* game2apk-tool input bridge, schema-compatible with Android v1. */
(function (global) {
  'use strict';
  var bridge = global.Game2ApkInput = global.Game2ApkInput || {};
  bridge.configUrl = 'game2apk-config.json';
  bridge._resumeAudioContext = function (context) {
    if (!context || typeof context.resume !== 'function' || context.state !== 'suspended') return;
    try {
      var result = context.resume();
      if (result && typeof result.catch === 'function') result.catch(function () {});
    } catch (_) {}
  };
  bridge.unlockAudio = function () {
    var webAudio = global.WebAudio;
    if (webAudio && webAudio._context) {
      bridge._resumeAudioContext(webAudio._context);
      // MV's own unlock handler primes a zero-length source.  Keep that
      // step for Android WebView/Bluetooth routes as well; it is harmless
      // when the context is already unlocked.
      if (typeof webAudio._onTouchStart === 'function') {
        try { webAudio._onTouchStart(); } catch (_) {}
      }
    }
    return true;
  };
  bridge.requestExit = function () {
    try {
      global.location.href = 'game2apk://exit';
      return true;
    } catch (_) {
      return false;
    }
  };
  bridge._keyEvent = function (keyCode, type) {
    if (!global.Input) return false;
    if (type !== 'up') bridge.unlockAudio();
    var handler = type === 'up' ? global.Input._onKeyUp : global.Input._onKeyDown;
    if (typeof handler !== 'function') return false;
    handler.call(global.Input, { keyCode: Number(keyCode), which: Number(keyCode), preventDefault: function () {} });
    return true;
  };
  bridge.keyDown = function (keyCode) { return bridge._keyEvent(keyCode, 'down'); };
  bridge.keyUp = function (keyCode) { return bridge._keyEvent(keyCode, 'up'); };
  bridge.getConfig = function () { return global.GAME2APK_CONFIG || null; };
  bridge.installExitHook = function () {
    var manager = global.SceneManager;
    if (manager && typeof manager.exit === 'function' && !manager._game2apkExitHook) {
      manager.exit = function () { return bridge.requestExit(); };
      manager._game2apkExitHook = true;
    }
    if (typeof global.close === 'function' && !global._game2apkCloseHook) {
      global.close = function () { return bridge.requestExit(); };
      global._game2apkCloseHook = true;
    }
    return Boolean(manager && manager._game2apkExitHook);
  };
  if (global.document && global.document.addEventListener) {
    global.document.addEventListener('touchstart', bridge.unlockAudio, { passive: true });
    global.document.addEventListener('pointerdown', bridge.unlockAudio, { passive: true });
    global.document.addEventListener('keydown', bridge.unlockAudio, { passive: true });
    global.document.addEventListener('visibilitychange', bridge.unlockAudio, { passive: true });
  }
  if (global.addEventListener) {
    global.addEventListener('focus', bridge.unlockAudio, { passive: true });
  }
  bridge.installExitHook();
  if (global.setTimeout) {
    (function retryExitHook(attempts) {
      if (bridge.installExitHook() || attempts <= 0) return;
      global.setTimeout(function () { retryExitHook(attempts - 1); }, 50);
    }(40));
  }
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


def _patch_encrypted_audio_extension(staged_www: Path) -> bool:
    """Force encrypted MV audio to use the OGG/RPGMVO asset family.

    The source game is never touched: ``staged_www`` is the marker-protected
    copy created by the staging pipeline.  A missing managers script is
    allowed for generic/non-MV inputs, while an unexpected MV implementation
    fails closed instead of silently shipping the known mobile 404 behavior.
    """

    managers_path = staged_www / "js" / "rpg_managers.js"
    if not managers_path.is_file():
        return False
    managers, encoding = _read_index(managers_path)
    matches = list(_AUDIO_FILE_EXT.finditer(managers))
    if len(matches) != 1:
        raise BlockedError(
            f"expected exactly one RPG Maker MV AudioManager.audioFileExt implementation, found {len(matches)}"
        )
    patched = managers[: matches[0].start()] + _AUDIO_FILE_EXT_PATCH + managers[matches[0].end() :]
    newline = "\r\n" if "\r\n" in managers else "\n"
    atomic_write_text(
        managers_path,
        patched.replace("\r\n", "\n").replace("\n", newline),
        encoding="utf-8-sig" if encoding == "utf-8-sig" else "utf-8",
    )
    return True


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
    audio_extension_patched = _patch_encrypted_audio_extension(root)
    newline = "\r\n" if "\r\n" in index else "\n"
    insertion = newline + "    <script type=\"text/javascript\" src=\"js/game2apk-input.js\"></script>"
    patched = index[: core_matches[0].end()] + insertion + index[core_matches[0].end() :]
    atomic_write_text(index_path, patched, encoding="utf-8-sig" if encoding == "utf-8-sig" else "utf-8")
    atomic_write_text(bridge_path, BRIDGE_SOURCE.replace("\n", newline))
    config_path = root / "game2apk-config.json"
    write_android_config(config_path, config_data)
    return {
        "index": str(index_path),
        "bridge": str(bridge_path),
        "config": str(config_path),
        "injectionCount": 1,
        "encryptedAudioExtensionPatched": int(audio_extension_patched),
    }
