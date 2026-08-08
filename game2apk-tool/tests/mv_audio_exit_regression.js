"use strict";

// Regression seam for the Android bridge: MV WebAudio must be resumed after a
// real game gesture, and SceneManager.exit/window.close must request the native
// Activity instead of merely changing browser state.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const bridgePath = path.join(
  __dirname, "..", "templates", "android-rpgmv", "app", "src", "main",
  "assets", "www", "game2apk-input.js"
);
const listeners = {};
const resumed = [];
const primed = [];
const audioContext = {
  state: "suspended",
  resume() {
    resumed.push(true);
    this.state = "running";
    return { catch() {} };
  }
};
const window = {
  WebAudio: {
    _context: audioContext,
    _onTouchStart() { primed.push(true); }
  },
  SceneManager: { exit() { throw new Error("original exit should be replaced"); } },
  location: { href: "https://appassets.androidplatform.net/assets/www/index.html" },
  close() { throw new Error("original close should be replaced"); },
  document: { addEventListener(type, callback) { listeners[type] = callback; } }
};
vm.runInNewContext(fs.readFileSync(bridgePath, "utf8"), {
  window,
  Number,
  isFinite,
  Boolean,
  setTimeout() { throw new Error("exit hook should install synchronously in MV"); }
}, { filename: bridgePath });

if (!window.Game2ApkInput || !window.SceneManager._game2apkExitHook) {
  throw new Error("exit hook did not install");
}
if (typeof listeners.touchstart !== "function") {
  throw new Error("audio touch unlock listener did not install");
}
listeners.touchstart();
if (resumed.length !== 1 || audioContext.state !== "running") {
  throw new Error("suspended WebAudio context was not resumed");
}
if (primed.length !== 1) {
  throw new Error("MV WebAudio unlock source was not primed");
}
window.location.href = "reset";
window.SceneManager.exit();
if (window.location.href !== "game2apk://exit") {
  throw new Error("SceneManager.exit did not request native Activity exit");
}
window.location.href = "reset";
window.close();
if (window.location.href !== "game2apk://exit") {
  throw new Error("window.close did not request native Activity exit");
}

console.log("MV audio/exit regression passed: AudioContext resumed and native exit URI requested");
