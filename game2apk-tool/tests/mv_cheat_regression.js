const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const bridge = fs.readFileSync(path.join(root, 'src', 'game2apk', 'patcher.py'), 'utf8');
for (const token of [
  'Game2ApkCheat', '999999999', '$gameParty._gold = 999999999', 'Scene_Shop', 'buyingPrice',
  'gainHp', 'changeLevel', '2010', '2034', '2085', 'reserveTransfer',
  'recallMapIds = [136, 97]'
]) {
  if (!bridge.includes(token)) throw new Error(`missing cheat contract: ${token}`);
}
if (!bridge.includes('reserveTransfer(136, 10, 8, 2, 0)')) {
  throw new Error('formal recall room must use safe Map136 staging tile (10,8)');
}
if (bridge.includes('Game2ApkCheat.*eval') || bridge.includes('eval(')) {
  throw new Error('cheat bridge must not use eval');
}
console.log('mv cheat regression passed');
