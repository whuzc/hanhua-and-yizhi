const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const bridge = fs.readFileSync(path.join(root, 'src', 'game2apk', 'patcher.py'), 'utf8');
for (const token of [
  'Game2ApkCheat', '999999999', '$gameParty._gold = 999999999', 'Scene_Shop', 'buyingPrice',
  'gainHp', 'changeLevel', '2010', '2034', '2085', 'reserveTransfer',
  'processVictory', 'processDefeat', 'g2a-win', 'g2a-lose', 'isBattleActive',
  'paramDelta', 'naturalHp', 'godHp', 'battleOverride', 'refreshBattleControls', '仅能在战斗进行中使用',
  'recallMapIds = [136, 97]', 'cheat.discover', 'dynamicCatalog', 'classifyField', 'displayLabel',
  'switchFields', 'recallCandidates', '自动识别'
]) {
  if (!bridge.includes(token)) throw new Error(`missing cheat contract: ${token}`);
}
if (!bridge.includes('reserveTransfer(136, 10, 8, 2, 0)')) {
  throw new Error('formal recall room must use safe Map136 staging tile (10,8)');
}
if (!bridge.includes('members().forEach(function (a) { if (a.setHp) a.setHp(0); })')) {
  throw new Error('forced defeat must enter native all-dead defeat flow');
}
if (bridge.includes('a._paramPlus = s.paramPlus.slice()')) {
  throw new Error('god toggle must not overwrite the complete old paramPlus snapshot');
}
if (!bridge.includes('entry.naturalHp = actor._hp') || !bridge.includes('clamp(hp, 0, a.mhp)')) {
  throw new Error('god toggle must track natural HP and clamp it after removing the HP boost');
}
if (!bridge.includes("title=\"原始标签：") || !bridge.includes('var label=cheat.displayLabel(f)')) {
  throw new Error('advanced cheat controls must display translated/category labels with source tooltip');
}
if (bridge.includes('Game2ApkCheat.*eval') || bridge.includes('eval(')) {
  throw new Error('cheat bridge must not use eval');
}
console.log('mv cheat regression passed');
