"""Deterministic input-bridge injection into a staged MV copy."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .cheat_catalog import validate_advanced_cheat_selection
from .config import write_android_config
from .errors import BlockedError
from .models import BuildConfig
from .security import atomic_write_text, assert_no_secrets, require_within


_CORE_SCRIPT = re.compile(
    r"<script\b(?=[^>]*\bsrc\s*=\s*[\"'](?:\./)?js/rpg_core\.js[\"'])[^>]*>\s*</script>",
    re.IGNORECASE,
)
_BRIDGE_SCRIPT = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"'](?:\./)?js/game2apk-input\.js[\"'][^>]*>\s*</script>", re.IGNORECASE)

# RPG Maker MV normally selects ``.m4a`` on mobile browsers.  That is not a
# safe capability test for Android WebView: many MV projects ship OGG-only
# audio (including unencrypted projects), while encrypted projects use the
# ``.rpgmvo`` form of OGG.  The generated per-file map below keeps the mobile
# request aligned with the actual staged asset, including non-ASCII names and
# projects that mix OGG/M4A.
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

_AUDIO_MAP_MARKER = "/* game2apk per-file audio extension map */"
_AUDIO_SUFFIX_TO_REQUEST = {
    ".ogg": ".ogg",
    ".rpgmvo": ".ogg",
    ".m4a": ".m4a",
    ".rpgmvm": ".m4a",
    ".mp3": ".mp3",
    ".wav": ".wav",
    ".webm": ".webm",
}
_AUDIO_SUFFIX_PRIORITY = {
    ".ogg": 0,
    ".rpgmvo": 0,
    ".m4a": 1,
    ".rpgmvm": 1,
    ".mp3": 2,
    ".wav": 3,
    ".webm": 4,
}


def _audio_extension_map(staged_www: Path) -> dict[str, str]:
    audio_root = staged_www / "audio"
    if not audio_root.is_dir():
        return {}
    selected: dict[str, tuple[int, str]] = {}
    for path in audio_root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.casefold()
        request_suffix = _AUDIO_SUFFIX_TO_REQUEST.get(suffix)
        if request_suffix is None:
            continue
        relative = path.relative_to(audio_root).as_posix()
        stem = relative[: -len(path.suffix)]
        candidate = (_AUDIO_SUFFIX_PRIORITY[suffix], request_suffix)
        previous = selected.get(stem)
        if previous is None or candidate[0] < previous[0]:
            selected[stem] = candidate
    return {stem: value[1] for stem, value in selected.items()}


def _append_audio_extension_map(managers: str, extension_map: dict[str, str], newline: str) -> str:
    if not extension_map or _AUDIO_MAP_MARKER in managers:
        return managers
    payload = json.dumps(extension_map, ensure_ascii=True, separators=(",", ":"))
    script = f"""
{_AUDIO_MAP_MARKER}
(function (map) {{
    var originalCreateBuffer = AudioManager.createBuffer;
    AudioManager.createBuffer = function (folder, name) {{
        var key = String(folder || '') + '/' + String(name || '');
        var preferred = map[key];
        if (!preferred) return originalCreateBuffer.apply(this, arguments);
        var previousAudioFileExt = this.audioFileExt;
        this.audioFileExt = function () {{ return preferred; }};
        try {{
            return originalCreateBuffer.apply(this, arguments);
        }} finally {{
            this.audioFileExt = previousAudioFileExt;
        }}
    }};
}})({payload});
"""
    return managers + script.replace("\n", newline)

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
    cheat.state = cheat.state || { god: false, freeShop: false, recall: null, godSnapshot: null, battleOverride: null };
    cheat.state.godSnapshot = cheat.state.godSnapshot || null;
    cheat.state.battleOverride = cheat.state.battleOverride || null;
    cheat.recallMapIds = [136, 97]; // 136 = 正式“事件回想”; 97 = test map
    cheat.customFields = [
      [600, '开发经验·淫乱'], [664, '淫乱 STUP'], [1402, 'ステEXP·淫乱'], [616, '卖春经验 STUP'],
      [581, '开发经验·胸'], [582, '开发经验·膣'], [583, '开发经验·尻'], [584, '开发经验·口'],
      [589, '精液'], [590, '露出'], [599, '评判'],
      [2010, '口感度'], [2011, '胸感度'], [2012, '尻感度'], [2013, '穴感度'],
      [2034, '口开发度'], [2035, '穴持久度'], [2036, '尻持久度'], [2037, '口持久度'],
      [2001, '淫臭'], [2085, '发情值'], [2086, '媚药侵染度'], [1990, '回想义务次数'], [1991, '回想义务金额']
    ];
    // Keep the old game's known fields as a fallback, but build the visible
    // advanced menu from the loaded MV database whenever possible.  This lets
    // the same APK template work with games that name libido/sensitivity,
    // development, affection, or other custom variables differently.
    cheat.legacyCustomFields = cheat.customFields.slice();
    cheat.customFields = cheat.customFields.slice();
    // Replaced at staging time with null (backward-compatible all) or a
    // validated array of numeric variable IDs selected in the desktop UI.
    cheat.selectedVariableIds = __GAME2APK_ADVANCED_CHEAT_VARIABLE_IDS__;
    cheat.switchFields = [];
    cheat.recallCandidates = [];
    cheat.dynamicCatalog = { variables: [], switches: [], recallMaps: [] };
    cheat.escapeHtml = function (value) {
      return String(value == null ? '' : value).replace(/[&<>\"']/g, function (ch) {
        return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' })[ch];
      });
    };
    cheat.classifyField = function (label) {
      var text = String(label || '').toLowerCase();
      if (/淫|エロ|lust|lewd|libido|色情/.test(text)) return '欲望';
      if (/感度|敏感|sensitivity|sensitive|胸|口|尻|穴/.test(text)) return '感度';
      if (/開発|开发|development|経験|exp|stup/.test(text)) return '成长';
      if (/好感|affection|love|亲密|信頼|信赖/.test(text)) return '关系';
      if (/回想|recollection|gallery|scene/.test(text)) return '回想';
      return '自定义';
    };
    // Prefer the translated System.json label.  If translation is disabled
    // and a Japanese editor label remains, show a useful Chinese category and
    // retain the source text only as a tooltip rather than exposing an opaque
    // Japanese control in the visible menu.
    cheat.displayLabel = function (field) {
      var id = field && field[0], raw = String(field && field[1] || '').trim();
      var category = String(field && field[2] || '自定义');
      if (!raw) return category + '（变量 ' + id + '）';
      var hasKana = /[\u3040-\u30ff\u31f0-\u31ff]/.test(raw);
      var hasHan = /[\u3400-\u9fff]/.test(raw);
      if (hasHan && !hasKana) return raw;
      return category + '（变量 ' + id + '）';
    };
    cheat.discover = function () {
      var variables = global.$dataSystem && global.$dataSystem.variables || [];
      var discovered = [], i, label;
      for (i = 1; i < variables.length && discovered.length < 256; i++) {
        label = String(variables[i] || '').trim();
        if (label) discovered.push([i, label, cheat.classifyField(label)]);
      }
      // If a title does not name its variables, preserve the prior game's
      // explicit safe list rather than exposing every numeric slot blindly.
      if (Array.isArray(cheat.selectedVariableIds)) {
        var selected = {};
        cheat.selectedVariableIds.forEach(function (id) { selected[String(id)] = true; });
        cheat.customFields = discovered.filter(function (field) { return !!selected[String(field[0])]; });
      } else {
        cheat.customFields = discovered.length ? discovered : cheat.legacyCustomFields.slice();
      }
      var switches = global.$dataSystem && global.$dataSystem.switches || [];
      cheat.switchFields = [];
      for (i = 1; i < switches.length && cheat.switchFields.length < 128; i++) {
        label = String(switches[i] || '').trim();
        if (label) cheat.switchFields.push([i, label]);
      }
      var infos = global.$dataMapInfos || [], maps = [];
      for (i = 1; i < infos.length; i++) {
        if (!infos[i] || !infos[i].name) continue;
        label = String(infos[i].name).trim();
        if (/回想|回憶|recollection|gallery|scene|event/i.test(label)) maps.push([i, label]);
      }
      // The current title's formal room is retained only when its map exists;
      // another game must opt in through a detected map name.
      if (!maps.length && infos[136] && infos[136].name) maps.push([136, String(infos[136].name)]);
      cheat.recallCandidates = maps;
      cheat.recallMapIds = maps.map(function (item) { return item[0]; });
      cheat.dynamicCatalog = { variables: cheat.customFields.slice(), switches: cheat.switchFields.slice(), recallMaps: maps.slice() };
      return cheat.dynamicCatalog;
    };
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
    cheat.applySwitches = function () {
      if (!global.$gameSwitches || !$gameSwitches.setValue) return;
      for (var i = 0; i < cheat.switchFields.length; i++) {
        var id = cheat.switchFields[i][0], e = document.getElementById('g2a-switch-' + id);
        if (e) $gameSwitches.setValue(id, !!e.checked);
      }
      cheat.refresh();
    };
    cheat.godValue = 999999;
    cheat.actorKey = function (a) { return a && a.actorId ? String(a.actorId()) : ''; };
    cheat.captureGodSnapshot = function () {
      if (cheat.state.godSnapshot) return;
      cheat.state.godSnapshot = {};
      actors().forEach(function (a) {
        var key = cheat.actorKey(a); if (!key) return;
        var plus = a._paramPlus || [];
        cheat.state.godSnapshot[key] = { naturalHp: a.hp, godHp: null, paramBase: [plus[0] || 0, plus[2] || 0, plus[3] || 0], paramDelta: [0, 0, 0] };
        [0, 2, 3].forEach(function (p, i) { cheat.state.godSnapshot[key].paramDelta[i] = Math.max(0, cheat.godValue - (plus[p] || 0)); });
      });
    };
    cheat.ensureGodEntry = function (a) {
      if (!cheat.state.godSnapshot) return null;
      var key = cheat.actorKey(a), entry = cheat.state.godSnapshot[key];
      if (!entry) {
        var plus = a._paramPlus || [];
        entry = cheat.state.godSnapshot[key] = { naturalHp: a.hp, godHp: null, paramBase: [plus[0] || 0, plus[2] || 0, plus[3] || 0], paramDelta: [0, 0, 0] };
        [0, 2, 3].forEach(function (p, i) { entry.paramDelta[i] = Math.max(0, cheat.godValue - (plus[p] || 0)); });
      }
      return entry;
    };
    cheat.restoreGodSnapshot = function () {
      var snap = cheat.state.godSnapshot; if (!snap) return;
      actors().forEach(function (a) {
        var s = snap[cheat.actorKey(a)]; if (!s) return;
        var hp = typeof s.naturalHp === 'number' ? s.naturalHp : a.hp, plus = a._paramPlus || [];
        [0, 2, 3].forEach(function (p, i) { plus[p] = Math.max(0, (plus[p] || 0) - (s.paramDelta[i] || 0)); });
        a._paramPlus = plus;
        if (a.refresh) a.refresh();
        if (a.setHp) a.setHp(clamp(hp, 0, a.mhp));
      });
      cheat.state.godSnapshot = null;
    };
    cheat.maintainGod = function (actor) {
      if (!cheat.state.god || cheat.state.battleOverride === 2 || !actor || !actor.isActor || !actor.isActor()) return;
      if (!actor._paramPlus) actor._paramPlus = [0, 0, 0, 0, 0, 0, 0, 0];
      var entry = cheat.ensureGodEntry(actor); if (!entry) return;
      // `_hp` is written directly below, so any value observed between two
      // maintenance passes came from the game (heal, scripted damage, or a
      // level/maximum-HP change). Preserve that natural value for restoration.
      if (entry.godHp !== null && actor._hp !== entry.godHp) entry.naturalHp = actor._hp;
      // Keep only the requested combat values elevated; the snapshot makes
      // this reversible when the toggle is switched off.
      [0, 2, 3].forEach(function (p, i) {
        var target = (entry.paramBase[i] || 0) + (entry.paramDelta[i] || 0);
        actor._paramPlus[p] = Math.max(actor._paramPlus[p] || 0, target);
      });
      actor._hp = actor.mhp;
      entry.godHp = actor._hp;
    };
    cheat.toggleGod = function (on) {
      on = !!on;
      if (on && !cheat.state.god) { cheat.captureGodSnapshot(); cheat.state.god = true; }
      else if (!on && cheat.state.god) { cheat.state.god = false; cheat.restoreGodSnapshot(); }
      cheat.installGod(); cheat.refresh();
    };
    cheat.installGod = function () {
      if (global.Game_Battler && Game_Battler.prototype.gainHp && !Game_Battler.prototype._game2apkGodHook) {
        var original = Game_Battler.prototype.gainHp;
        Game_Battler.prototype.gainHp = function (value) {
          if (cheat.state.god && this.isActor && this.isActor() && value < 0) { cheat.maintainGod(this); return; }
          original.call(this, value);
          if (cheat.state.god && this.isActor && this.isActor()) cheat.maintainGod(this);
        };
        Game_Battler.prototype._game2apkGodHook = true;
      }
      if (global.Game_Actor && Game_Actor.prototype.refresh && !Game_Actor.prototype._game2apkGodRefreshHook) {
        var refresh = Game_Actor.prototype.refresh;
        Game_Actor.prototype.refresh = function () {
          refresh.apply(this, arguments);
          cheat.maintainGod(this);
        };
        Game_Actor.prototype._game2apkGodRefreshHook = true;
      }
      if (global.BattleManager && BattleManager.update && !BattleManager._game2apkGodUpdateHook) {
        var update = BattleManager.update;
      BattleManager.update = function () {
          if (cheat.state.god) actors().forEach(cheat.maintainGod);
          update.apply(this, arguments);
          if (cheat.state.god) actors().forEach(cheat.maintainGod);
          cheat.refreshBattleControls();
        };
        BattleManager._game2apkGodUpdateHook = true;
      }
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
      var recallSelection = document.getElementById('g2a-recall-map');
      var targetId = recallSelection ? clamp(recallSelection.value, 1, 999999) : cheat.recallMapIds[0];
      if (cheat.recallMapIds.indexOf(targetId) < 0) targetId = cheat.recallMapIds[0];
      if (!targetId) { alert('未识别到回想/场景地图，请先检查游戏数据库命名。'); return; }
      var targetX = targetId === 136 ? 10 : 1, targetY = targetId === 136 ? 8 : 1;
      // Legacy safe target was reserveTransfer(136, 10, 8, 2, 0).
      $gamePlayer.reserveTransfer(targetId, targetX, targetY, 2, 0); cheat.close();
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
    cheat.isBattleActive = function () {
      var bm = global.BattleManager, sm = global.SceneManager, scene = sm && sm._scene;
      return !!(bm && scene && global.Scene_Battle && scene instanceof global.Scene_Battle &&
        bm._phase && bm._phase !== 'battleEnd' && bm._phase !== 'aborting');
    };
    cheat.forceBattleResult = function (result) {
      if (!cheat.isBattleActive()) { alert('该按钮仅能在战斗进行中使用。'); return false; }
      var bm = global.BattleManager;
      if (bm.isBattleEnd && bm.isBattleEnd()) return false;
      if (result === 0 && typeof bm.processVictory === 'function') {
        cheat.state.battleOverride = 0;
        bm.processVictory();
      } else if (result === 2 && typeof bm.processDefeat === 'function') {
        // Native updateBattleEnd uses all-dead to choose game-over/revive.  Set
        // HP to zero first so the normal defeat, callback, and canLose rules run.
        cheat.state.battleOverride = 2;
        if (global.$gameParty && $gameParty.members) $gameParty.members().forEach(function (a) { if (a.setHp) a.setHp(0); });
        bm.processDefeat();
      } else return false;
      cheat.close();
      return true;
    };
    cheat.refreshBattleControls = function () {
      var active = cheat.isBattleActive();
      ['g2a-win', 'g2a-lose'].forEach(function (id) { var e = document.getElementById(id); if (e) e.disabled = !active; });
      if (!active && cheat.state.battleOverride !== null) { cheat.state.battleOverride = null; }
    };
    cheat.refresh = function () {
      cheat.refreshBattleControls();
      var a = selectedActor(); if (!a) return;
      var vals = { level:a.level, exp:a.currentExp ? a.currentExp() : 0, hp:a.hp, mp:a.mp, atk:a.param(2), def:a.param(3), mat:a.param(4), mdf:a.param(5), agi:a.param(6), luk:a.param(7) };
      Object.keys(vals).forEach(function(k){setText('g2a-'+k, vals[k]);});
      if (global.$gameVariables) cheat.customFields.forEach(function(f){setText('g2a-var-'+f[0], $gameVariables.value(f[0]));});
      if (global.$gameSwitches) cheat.switchFields.forEach(function(f){var e=document.getElementById('g2a-switch-'+f[0]); if(e) e.checked=!!$gameSwitches.value(f[0]);});
      var g = document.getElementById('g2a-god'); if (g) g.checked = !!cheat.state.god;
    };
    cheat.close = function () { var p = document.getElementById('game2apk-cheat'); if (p) p.remove(); };
    cheat.toggle = function () {
      var old = document.getElementById('game2apk-cheat'); if (old) { old.remove(); return; }
      var p = document.createElement('div'); p.id='game2apk-cheat'; p.style.cssText='position:fixed;left:4%;top:4%;width:92%;max-height:88%;overflow:auto;z-index:2147483647;background:rgba(16,18,28,.96);color:#fff;padding:14px;border:2px solid #8ab4ff;border-radius:10px;font:14px sans-serif;box-sizing:border-box';
      cheat.discover();
      var a=actors(), h='<div style="font-size:18px;font-weight:bold">内置作弊器 <button id="g2a-close" style="float:right">关闭</button></div><p style="color:#ffd27f">修改后建议手动保存。高级变量仅开放白名单，数值限制为 0～999999。</p><button id="g2a-gold">获得 999999999 金币</button> <button id="g2a-shop">免费商店</button><label style="margin-left:12px"><input id="g2a-god" type="checkbox"> 无敌（HP/攻击/防御持续提升，可恢复）</label><hr><label>角色 <select id="g2a-actor">'+a.map(function(x,i){return '<option value="'+i+'">'+(x.name?x.name():('角色'+i))+'</option>';}).join('')+'</select></label><div id="g2a-fields"></div><button id="g2a-apply">应用角色数值</button><h4>高级/自定义数值（白名单）</h4><div id="g2a-custom"></div><button id="g2a-apply-custom">应用高级数值</button><hr><button id="g2a-recall">传送到正式回想房间（Map136）</button><small> 离开回想房间会自动返回进入前的位置。</small><hr><div><b>战斗作弊（仅战斗中可用）</b> <button id="g2a-win" disabled>战斗胜利</button> <button id="g2a-lose" disabled>战斗失败</button><small> 强制调用游戏原生战斗结束、奖励/失败及公共事件流程。</small></div>';
      p.innerHTML=h; document.body.appendChild(p);
      var recallButton = document.getElementById('g2a-recall');
      if (recallButton && cheat.recallCandidates.length) {
        var recallSelect = document.createElement('select'); recallSelect.id = 'g2a-recall-map';
        recallSelect.innerHTML = cheat.recallCandidates.map(function(item){return '<option value="'+item[0]+'">'+cheat.escapeHtml(item[1])+' (#'+item[0]+')</option>';}).join('');
        recallButton.parentNode.insertBefore(recallSelect, recallButton);
      } else if (recallButton) recallButton.disabled = true;
      var fields=[['level','等级'],['exp','经验'],['hp','HP'],['mp','MP'],['atk','攻击'],['def','防御'],['mat','魔攻'],['mdf','魔防'],['agi','敏捷'],['luk','幸运']];
      document.getElementById('g2a-fields').innerHTML=fields.map(function(f){return '<label style="display:inline-block;width:32%;margin:3px">'+f[1]+' <input id="g2a-'+f[0]+'" type="number" min="0" max="999999" style="width:75px"></label>';}).join('');
      document.getElementById('g2a-custom').innerHTML=cheat.customFields.map(function(f){var label=cheat.displayLabel(f); return '<label title="原始标签：'+cheat.escapeHtml(f[1])+'" style="display:inline-block;width:48%;margin:3px">'+cheat.escapeHtml(label)+' <input id="g2a-var-'+f[0]+'" type="number" min="0" max="999999" style="width:90px"></label>';}).join('');
      var switchContainer = document.getElementById('g2a-switches');
      if (!switchContainer) { switchContainer = document.createElement('div'); switchContainer.id = 'g2a-switches'; var customContainer = document.getElementById('g2a-custom'); if (customContainer && customContainer.parentNode) customContainer.parentNode.insertBefore(switchContainer, customContainer.nextSibling); }
      switchContainer.innerHTML=cheat.switchFields.length ? '<h4>自动识别开关（默认不修改）</h4>'+cheat.switchFields.map(function(f){var label=cheat.displayLabel(f); return '<label title="原始标签：'+cheat.escapeHtml(f[1])+'" style="display:inline-block;width:48%;margin:3px"><input id="g2a-switch-'+f[0]+'" type="checkbox"> '+cheat.escapeHtml(label)+'</label>';}).join('') : '<small>未发现已命名的游戏开关。</small>';
      var switchButton = document.getElementById('g2a-apply-switches');
      if (!switchButton) { switchButton = document.createElement('button'); switchButton.id = 'g2a-apply-switches'; switchButton.textContent = '应用开关'; if (switchContainer && switchContainer.parentNode) switchContainer.parentNode.insertBefore(switchButton, switchContainer.nextSibling); }
      document.getElementById('g2a-close').onclick=cheat.close; document.getElementById('g2a-gold').onclick=cheat.addGold; document.getElementById('g2a-shop').onclick=cheat.openShop; document.getElementById('g2a-god').onchange=function(){cheat.toggleGod(this.checked);}; document.getElementById('g2a-apply').onclick=cheat.applyActor; document.getElementById('g2a-apply-custom').onclick=cheat.applyCustom; switchButton.onclick=cheat.applySwitches; document.getElementById('g2a-actor').onchange=cheat.refresh; document.getElementById('g2a-recall').onclick=cheat.toRecall; document.getElementById('g2a-win').onclick=function(){cheat.forceBattleResult(0);}; document.getElementById('g2a-lose').onclick=function(){cheat.forceBattleResult(2);};
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
    newline = "\r\n" if "\r\n" in managers else "\n"
    patched = managers[: matches[0].start()] + _AUDIO_FILE_EXT_PATCH + managers[matches[0].end() :]
    extension_map = _audio_extension_map(staged_www)
    patched = _append_audio_extension_map(patched, extension_map, newline)
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
        selected_variable_ids = build_config.advanced_cheat_variable_ids
        config_data = {
            "schemaVersion": 1,
            "appName": build_config.app_name,
            "applicationId": build_config.application_id,
            "versionCode": build_config.version_code,
            "versionName": build_config.version_name,
            "control": build_config.control_config,
            "advancedCheatVariableIds": selected_variable_ids,
        }
    else:
        config_data = dict(build_config)
        selected_variable_ids = config_data.get("advancedCheatVariableIds")
    selected_variable_ids = validate_advanced_cheat_selection(root, selected_variable_ids)
    config_data["advancedCheatVariableIds"] = selected_variable_ids
    selected_variable_indexes = (
        None
        if selected_variable_ids is None
        else [int(item.split(":", 1)[1]) for item in selected_variable_ids]
    )
    assert_no_secrets(config_data)
    audio_extension_patched = _patch_encrypted_audio_extension(root)
    audio_extension_map = len(_audio_extension_map(root))
    newline = "\r\n" if "\r\n" in index else "\n"
    insertion = newline + "    <script type=\"text/javascript\" src=\"js/game2apk-input.js\"></script>"
    patched = index[: core_matches[0].end()] + insertion + index[core_matches[0].end() :]
    atomic_write_text(index_path, patched, encoding="utf-8-sig" if encoding == "utf-8-sig" else "utf-8")
    selection_marker = "__GAME2APK_ADVANCED_CHEAT_VARIABLE_IDS__"
    if BRIDGE_SOURCE.count(selection_marker) != 1:
        raise BlockedError("advanced cheat selection injection marker is invalid")
    bridge_source = BRIDGE_SOURCE.replace(
        selection_marker,
        json.dumps(selected_variable_indexes, ensure_ascii=True, separators=(",", ":")),
    )
    atomic_write_text(bridge_path, bridge_source.replace("\n", newline))
    config_path = root / "game2apk-config.json"
    write_android_config(config_path, config_data)
    return {
        "index": str(index_path),
        "bridge": str(bridge_path),
        "config": str(config_path),
        "injectionCount": 1,
        "encryptedAudioExtensionPatched": int(audio_extension_patched),
        "audioExtensionMapEntries": audio_extension_map,
    }
