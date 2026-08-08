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

  /* In-game cheat panel.  It is deliberately implemented in the staged
     page, so it uses MV's own save/runtime objects and never touches files. */
  (function installCheat() {
    var cheat = global.Game2ApkCheat = global.Game2ApkCheat || {};
    cheat.state = cheat.state || { god: false, freeShop: false, recall: null };
    cheat.recallMapIds = [136, 97]; // 136 = 正式“事件回想”; 97 = test map
    cheat.customFields = [
      [600, '开发经验·淫乱'], [664, '淫乱 STUP'], [1402, 'ステEXP·淫乱'], [616, '卖春经验 STUP'],
      [581, '开发经验·胸'], [582, '开发经验·膣'], [583, '开发经验·尻'], [584, '开发经验·口'],
      [589, '精液'], [590, '露出'], [599, '评判'],
      [2010, '口感度'], [2011, '胸感度'], [2012, '尻感度'], [2013, '穴感度'],
      [2034, '口开发度'], [2035, '穴持久度'], [2036, '尻持久度'], [2037, '口持久度'],
      [2001, '淫臭'], [2085, '发情值'], [2086, '媚药侵染度'], [1990, '回想义务次数'], [1991, '回想义务金额']
    ];
    function finite(v, fallback) { v = Number(v); return isFinite(v) ? v : fallback; }
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, Math.floor(finite(v, lo)))); }
    function actors() { return global.$gameParty && $gameParty.members ? $gameParty.members() : []; }
    function selectedActor() { var a = actors(); return a[clamp((document.getElementById('g2a-actor') || {}).value, 0, Math.max(0, a.length - 1))]; }
    function setText(id, value) { var e = document.getElementById(id); if (e) e.value = value; }
    cheat.addGold = function () { if (global.$gameParty) {
      // YEP CoreEngine may cap maxGold at 99,999,999.  This deliberate
      // one-shot assignment bypasses that cap while retaining MV's save field.
      if (typeof $gameParty._gold === 'number') $gameParty._gold = 999999999;
      else $gameParty.gainGold(999999999);
      cheat.refresh();
    } };
    cheat.applyActor = function () {
      var a = selectedActor(); if (!a) return;
      var level = clamp((document.getElementById('g2a-level') || {}).value, 1, a.maxLevel ? a.maxLevel() : 99);
      if (a.changeLevel) a.changeLevel(level, false);
      if (a.changeExp && document.getElementById('g2a-exp')) a.changeExp(clamp(document.getElementById('g2a-exp').value, 0, 2147483647), false);
      if (a.setHp) a.setHp(clamp(document.getElementById('g2a-hp').value, 0, 999999));
      if (a.setMp) a.setMp(clamp(document.getElementById('g2a-mp').value, 0, 999999));
      var names = ['atk','def','mat','mdf','agi','luk'];
      for (var i = 0; i < names.length; i++) { var p = i + 2, e = document.getElementById('g2a-' + names[i]); if (e && a.addParam) a.addParam(p, clamp(e.value, 0, 999999) - (a.param ? a.param(p) : 0)); }
      if (a.refresh) a.refresh(); if (global.$gamePlayer && $gamePlayer.refresh) $gamePlayer.refresh(); cheat.refresh();
    };
    cheat.applyCustom = function () {
      if (!global.$gameVariables || !$gameVariables.setValue) return;
      for (var i = 0; i < cheat.customFields.length; i++) { var id = cheat.customFields[i][0], e = document.getElementById('g2a-var-' + id); if (e) $gameVariables.setValue(id, clamp(e.value, 0, 999999)); }
      cheat.refresh();
    };
    cheat.toggleGod = function (on) { cheat.state.god = !!on; cheat.installGod(); cheat.refresh(); };
    cheat.installGod = function () {
      if (!global.Game_Battler || !Game_Battler.prototype.gainHp || Game_Battler.prototype._game2apkGodHook) return;
      var original = Game_Battler.prototype.gainHp;
      Game_Battler.prototype.gainHp = function (value) {
        if (cheat.state.god && this.isActor && this.isActor() && value < 0) { this.setHp(this.mhp); return; }
        original.call(this, value);
        if (cheat.state.god && this.isActor && this.isActor() && this.hp <= 0) { this.setHp(this.mhp); this.removeState && this.removeState(1); }
      };
      Game_Battler.prototype._game2apkGodHook = true;
    };
    cheat.installRecall = function () {
      if (!global.Game_Player || !Game_Player.prototype.reserveTransfer || Game_Player.prototype._game2apkRecallHook) return;
      var original = Game_Player.prototype.reserveTransfer;
      Game_Player.prototype.reserveTransfer = function (mapId, x, y, d, fade) {
        var current = global.$gameMap && $gameMap.mapId ? $gameMap.mapId() : 0;
        if (cheat.state.recall && cheat.recallMapIds.indexOf(current) >= 0 && cheat.recallMapIds.indexOf(mapId) < 0) {
          var r = cheat.state.recall; cheat.state.recall = null; mapId = r.mapId; x = r.x; y = r.y; d = r.direction; fade = r.fade;
        }
        return original.call(this, mapId, x, y, d, fade);
      };
      Game_Player.prototype._game2apkRecallHook = true;
    };
    cheat.toRecall = function () {
      if (!global.$gamePlayer || !global.$gameMap || !$gameMap.mapId) return;
      if (cheat.recallMapIds.indexOf($gameMap.mapId()) >= 0) return;
      cheat.state.recall = { mapId: $gameMap.mapId(), x: $gamePlayer.x, y: $gamePlayer.y, direction: $gamePlayer.direction(), fade: 0 };
      // Map136 is the formal event-recall room.  (10,8) is a passable
      // staging tile, deliberately not an Action Button event tile.
      $gamePlayer.reserveTransfer(136, 10, 8, 2, 0); cheat.close();
    };
    cheat.installShop = function () {
      if (!global.Scene_Shop || Scene_Shop.prototype._game2apkShopHook) return;
      var price = Scene_Shop.prototype.buyingPrice, terminate = Scene_Shop.prototype.terminate || function () {};
      Scene_Shop.prototype.buyingPrice = function () { return cheat.state.freeShop ? 0 : price.call(this); };
      Scene_Shop.prototype.terminate = function () { cheat.state.freeShop = false; terminate.call(this); };
      Scene_Shop.prototype._game2apkShopHook = true;
    };
    cheat.openShop = function () {
      cheat.installShop(); if (!global.Scene_Shop || !global.SceneManager || !$dataItems) return;
      var goods = [], i;
      for (i = 1; i < $dataItems.length; i++) if ($dataItems[i]) goods.push([0, i, 0, 0]);
      for (i = 1; i < $dataWeapons.length; i++) if ($dataWeapons[i]) goods.push([1, i, 0, 0]);
      for (i = 1; i < $dataArmors.length; i++) if ($dataArmors[i]) goods.push([2, i, 0, 0]);
      alert('免费商店：请按需购买，短时间大量购买可能导致游戏卡顿或崩溃。购买数量不设上限。');
      cheat.state.freeShop = true; cheat.close(); SceneManager.push(Scene_Shop); SceneManager.prepareNextScene(goods, true);
    };
    cheat.refresh = function () {
      var a = selectedActor(); if (!a) return;
      var vals = { level:a.level, exp:a.currentExp ? a.currentExp() : 0, hp:a.hp, mp:a.mp, atk:a.param(2), def:a.param(3), mat:a.param(4), mdf:a.param(5), agi:a.param(6), luk:a.param(7) };
      Object.keys(vals).forEach(function(k){setText('g2a-'+k, vals[k]);});
      if (global.$gameVariables) cheat.customFields.forEach(function(f){setText('g2a-var-'+f[0], $gameVariables.value(f[0]));});
      var g = document.getElementById('g2a-god'); if (g) g.checked = !!cheat.state.god;
    };
    cheat.close = function () { var p = document.getElementById('game2apk-cheat'); if (p) p.remove(); };
    cheat.toggle = function () {
      var old = document.getElementById('game2apk-cheat'); if (old) { old.remove(); return; }
      var p = document.createElement('div'); p.id='game2apk-cheat'; p.style.cssText='position:fixed;left:4%;top:4%;width:92%;max-height:88%;overflow:auto;z-index:2147483647;background:rgba(16,18,28,.96);color:#fff;padding:14px;border:2px solid #8ab4ff;border-radius:10px;font:14px sans-serif;box-sizing:border-box';
      var a=actors(), h='<div style="font-size:18px;font-weight:bold">内置作弊器 <button id="g2a-close" style="float:right">关闭</button></div><p style="color:#ffd27f">修改后建议手动保存。高级变量仅开放白名单，数值限制为 0～999999。</p><button id="g2a-gold">获得 999999999 金币</button> <button id="g2a-shop">免费商店</button><label style="margin-left:12px"><input id="g2a-god" type="checkbox"> 无敌（锁定角色HP）</label><hr><label>角色 <select id="g2a-actor">'+a.map(function(x,i){return '<option value="'+i+'">'+(x.name?x.name():('角色'+i))+'</option>';}).join('')+'</select></label><div id="g2a-fields"></div><button id="g2a-apply">应用角色数值</button><h4>高级/自定义数值（白名单）</h4><div id="g2a-custom"></div><button id="g2a-apply-custom">应用高级数值</button><hr><button id="g2a-recall">传送到正式回想房间（Map136）</button><small> 离开回想房间会自动返回进入前的位置。</small>';
      p.innerHTML=h; document.body.appendChild(p);
      var fields=[['level','等级'],['exp','经验'],['hp','HP'],['mp','MP'],['atk','攻击'],['def','防御'],['mat','魔攻'],['mdf','魔防'],['agi','敏捷'],['luk','幸运']];
      document.getElementById('g2a-fields').innerHTML=fields.map(function(f){return '<label style="display:inline-block;width:32%;margin:3px">'+f[1]+' <input id="g2a-'+f[0]+'" type="number" min="0" max="999999" style="width:75px"></label>';}).join('');
      document.getElementById('g2a-custom').innerHTML=cheat.customFields.map(function(f){return '<label style="display:inline-block;width:48%;margin:3px">'+f[1]+' <input id="g2a-var-'+f[0]+'" type="number" min="0" max="999999" style="width:90px"></label>';}).join('');
      document.getElementById('g2a-close').onclick=cheat.close; document.getElementById('g2a-gold').onclick=cheat.addGold; document.getElementById('g2a-shop').onclick=cheat.openShop; document.getElementById('g2a-god').onchange=function(){cheat.toggleGod(this.checked);}; document.getElementById('g2a-apply').onclick=cheat.applyActor; document.getElementById('g2a-apply-custom').onclick=cheat.applyCustom; document.getElementById('g2a-actor').onchange=cheat.refresh; document.getElementById('g2a-recall').onclick=cheat.toRecall;
      p.addEventListener('touchstart',function(e){e.stopPropagation();},{passive:false}); p.addEventListener('pointerdown',function(e){e.stopPropagation();}); cheat.refresh();
    };
    if (global.setTimeout) (function retry(n){ cheat.installGod(); cheat.installRecall(); cheat.installShop(); if(n>0) setTimeout(function(){retry(n-1);},250); }(40));
  }());
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
