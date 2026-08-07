"use strict";

// Integration-shaped MV touch regression. It models the public TouchInput,
// Window_ChoiceList, Game_Temp, and Game_Player touch contracts so coordinate
// mapping and raw-touch semantics are checked without a device or live game.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.join(__dirname, "..");
const bridgePath = path.join(root, "templates", "android-rpgmv", "app", "src", "main", "assets", "www", "game2apk-input.js");
const configPath = path.join(root, "templates", "android-rpgmv", "app", "src", "main", "assets", "game2apk", "config.json");
const bridgeSource = fs.readFileSync(bridgePath, "utf8");
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));

if (bridgeSource.includes("keyCode === 17") || bridgeSource.includes("keyCode === 87")) {
  throw new Error("legacy Ctrl/W global mapping remains in the MV bridge");
}
const buttonKeys = Object.fromEntries(config.buttons.map((button) => [button.id, button.keyCode]));
for (const [id, keyCode] of Object.entries({ up: 38, down: 40, left: 37, right: 39, confirm: 13, cancel: 88, esc: 27, portrait: 65 })) {
  if (buttonKeys[id] !== keyCode) throw new Error(`unexpected ${id} key code`);
}
if (Object.hasOwn(config, "joystick") || Object.hasOwn(config, "tap")) {
  throw new Error("legacy joystick/tap config remains");
}

const window = {};
const input = {
  keyMapper: { 13: "ok", 27: "escape", 65: "portrait", 88: "cancel" },
  _currentState: {},
  _onKeyDown(event) { const name = this.keyMapper[event.keyCode]; if (name) this._currentState[name] = true; },
  _onKeyUp(event) { const name = this.keyMapper[event.keyCode]; if (name) this._currentState[name] = false; }
};
window.Input = input;
vm.runInNewContext(bridgeSource, { window, Number, isFinite }, { filename: bridgePath });
for (const keyCode of [13, 88, 27, 65]) {
  if (!window.Game2ApkInput.keyDown(keyCode) || !window.Game2ApkInput.keyUp(keyCode)) {
    throw new Error(`action key ${keyCode} did not reach MV Input`);
  }
}

class TouchInputFixture {
  constructor() { this._pressed = false; this._pressedTime = 0; this._triggered = false; this._x = 0; this._y = 0; }
  _onTouchStart(x, y) { this._pressed = true; this._pressedTime = 0; this._triggered = true; this._x = x; this._y = y; }
  _onTouchMove(x, y) { this._x = x; this._y = y; }
  _onTouchEnd(x, y) { this._x = x; this._y = y; this._pressed = false; }
  update() { this._triggered = false; if (this._pressed) this._pressedTime += 1; }
  isPressed() { return this._pressed; }
  isTriggered() { return this._triggered; }
  isLongPressed() { return this._pressed && this._pressedTime >= 24; }
  isRepeated() { return this.isTriggered() || (this._pressed && this._pressedTime >= 24); }
}

class RawWebViewTouchFixture {
  constructor(touchInput, contentRect) { this.input = touchInput; this.rect = contentRect; this.events = []; }
  map(screenX, screenY) {
    return { x: (screenX - this.rect.left) / this.rect.scale, y: (screenY - this.rect.top) / this.rect.scale };
  }
  start(screenX, screenY) { const p = this.map(screenX, screenY); this.events.push("start"); this.input._onTouchStart(p.x, p.y); }
  move(screenX, screenY) { const p = this.map(screenX, screenY); this.events.push("move"); this.input._onTouchMove(p.x, p.y); }
  end(screenX, screenY) { const p = this.map(screenX, screenY); this.events.push("end"); this.input._onTouchEnd(p.x, p.y); }
}

const scale = Math.min(1920 / 1024, 1080 / 768);
const contentRect = { left: (1920 - 1024 * scale) / 2, top: 0, scale };
const touchInput = new TouchInputFixture();
const webTouch = new RawWebViewTouchFixture(touchInput, contentRect);

class ChoiceListFixture {
  constructor() { this.top = 300; this.rowHeight = 80; this.index = 0; this.confirmed = null; }
  onTouchEnd(x, y) {
    const hit = Math.floor((y - this.top) / this.rowHeight);
    if (hit >= 0 && hit < 3) { this.index = hit; this.confirmed = hit; }
  }
}
const choice = new ChoiceListFixture();
const optionTwo = { x: 512, y: 380 };
const optionTwoScreen = { x: contentRect.left + optionTwo.x * scale, y: optionTwo.y * scale };
webTouch.start(optionTwoScreen.x, optionTwoScreen.y);
webTouch.end(optionTwoScreen.x, optionTwoScreen.y);
choice.onTouchEnd(touchInput._x, touchInput._y);
if (choice.index !== 1 || choice.confirmed !== 1) {
  throw new Error(`choice touch selected ${choice.index}/${choice.confirmed}, expected option 2`);
}
if (webTouch.events.join(",") !== "start,end") throw new Error("choice touch was not passed raw once");

const gameTemp = { destination: null, setDestination(x, y) { this.destination = { x, y }; } };
const gamePlayer = { dashRequested: false, triggerCount: 0, triggerTouchAction() { this.triggerCount += 1; } };
function mapTouch(screenX, screenY, npc) {
  const p = webTouch.map(screenX, screenY);
  gameTemp.setDestination(Math.round(p.x), Math.round(p.y));
  gamePlayer.dashRequested = true; // MV's default destination movement dashes.
  if (npc && Math.abs(gameTemp.destination.x - npc.x) <= 1 && Math.abs(gameTemp.destination.y - npc.y) <= 1) {
    gamePlayer.triggerTouchAction();
  }
}
mapTouch(contentRect.left + 700 * scale, 500 * scale);
if (!gameTemp.destination || gameTemp.destination.x !== 700 || !gamePlayer.dashRequested) {
  throw new Error("map touch did not set destination with dash");
}
mapTouch(contentRect.left + 750 * scale, 500 * scale, { x: 750, y: 500 });
if (gamePlayer.triggerCount !== 1) throw new Error("NPC touch interaction did not trigger");

webTouch.start(contentRect.left + 400 * scale, 450 * scale);
for (let frame = 0; frame < 30; frame += 1) touchInput.update();
if (!touchInput.isPressed() || !touchInput.isLongPressed() || !touchInput.isRepeated()) {
  throw new Error("single-finger long press did not remain in MV TouchInput");
}
webTouch.end(contentRect.left + 400 * scale, 450 * scale);

console.log("MV touch regression passed: letterbox choice hit option 2, map destination/dash/NPC, raw long press");
