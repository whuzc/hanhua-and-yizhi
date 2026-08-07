"use strict";

// This is a small MV 1.6.1-style frame sampler. It deliberately fails if a
// pulse is changed from down to up before the first Input.update window.
const fs = require("fs");
const vm = require("vm");
const bridgePath = require("path").join(
  __dirname,
  "..",
  "templates",
  "android-rpgmv",
  "app",
  "src",
  "main",
  "assets",
  "www",
  "game2apk-input.js"
);

const window = {};
const context = { window, Number, isFinite };
vm.runInNewContext(fs.readFileSync(bridgePath, "utf8"), context, { filename: bridgePath });

const input = {
  keyMapper: { 13: "ok", 27: "escape", 65: "portrait", 88: "cancel", 37: "left", 38: "up", 39: "right", 40: "down" },
  _currentState: {},
  _previousState: {},
  _triggered: {},
  _onKeyDown(event) {
    const name = this.keyMapper[event.keyCode];
    if (name) this._currentState[name] = true;
  },
  _onKeyUp(event) {
    const name = this.keyMapper[event.keyCode];
    if (name) this._currentState[name] = false;
  },
  update() {
    this._triggered = {};
    Object.keys(this._currentState).forEach((name) => {
      this._triggered[name] = Boolean(this._currentState[name]) && !Boolean(this._previousState[name]);
    });
    this._previousState = Object.assign({}, this._currentState);
  },
  isPressed(name) { return Boolean(this._currentState[name]); },
  isTriggered(name) { return Boolean(this._triggered[name]); }
};
window.Input = input;
// The bridge reads Input at call time, like the real page does.
vm.runInNewContext(fs.readFileSync(bridgePath, "utf8"), context, { filename: bridgePath });

const bridge = window.Game2ApkInput;
if (!bridge || typeof bridge.keyDown !== "function" || typeof bridge.keyUp !== "function") {
  throw new Error("Game2ApkInput bridge did not load");
}

let now = 0;
const timers = [];
function schedule(callback, delay) { timers.push({ callback, due: now + delay }); }
function advanceTo(target) {
  now = target;
  for (let index = 0; index < timers.length;) {
    if (timers[index].due <= now) {
      const callback = timers.splice(index, 1)[0].callback;
      callback();
    } else {
      index += 1;
    }
  }
}
function pulse(keyCode) {
  if (!bridge.keyDown(keyCode)) throw new Error("keyDown was not delivered");
  schedule(() => {
    if (!bridge.keyUp(keyCode)) throw new Error("keyUp was not delivered");
  }, 40);
}

pulse(13);
advanceTo(16);
input.update();
if (!input.isPressed("ok") || !input.isTriggered("ok")) {
  throw new Error("Enter pulse was not visible in the first MV Input.update window");
}
advanceTo(40);
input.update();
if (input.isPressed("ok")) throw new Error("Enter pulse did not release after its minimum duration");

pulse(65);
advanceTo(16 + 40);
input.update();
if (!input.isPressed("portrait") || !input.isTriggered("portrait")) {
  throw new Error("A tap did not reach MV Input.keyMapper through the bridge");
}

for (const [keyCode, name] of [[88, "cancel"], [27, "escape"]]) {
  pulse(keyCode);
  advanceTo(now + 16);
  input.update();
  if (!input.isPressed(name) || !input.isTriggered(name)) {
    throw new Error(`${keyCode} tap did not remain visible for an MV frame`);
  }
  advanceTo(now + 40);
  input.update();
  if (input.isPressed(name)) throw new Error(`${keyCode} tap did not release`);
}

console.log("MV frame sampling regression passed: direction/action pulses visible before update, up after 40ms");
