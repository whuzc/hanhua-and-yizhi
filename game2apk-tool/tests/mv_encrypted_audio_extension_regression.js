"use strict";

// Static/runtime contract for the staged MV audio patch.  MV's mobile branch
// normally chooses .m4a and Decrypter maps it to .rpgmvm; this project ships
// encrypted OGG assets only, so encrypted audio must select .ogg -> .rpgmvo.
const fs = require("fs");
const path = require("path");

const patcherPath = path.join(__dirname, "..", "src", "game2apk", "patcher.py");
const patcher = fs.readFileSync(patcherPath, "utf8");
if (!patcher.includes("if (Decrypter.hasEncryptedAudio)")) {
  throw new Error("patcher is missing the encrypted-audio guard");
}
if (!patcher.includes("return '.ogg';")) {
  throw new Error("patcher does not force OGG for encrypted audio");
}

function audioFileExt({ encrypted, mobile, canPlayOgg }) {
  if (encrypted) return ".ogg";
  if (canPlayOgg && !mobile) return ".ogg";
  return ".m4a";
}

function encryptedExt(url) {
  const ext = url.split(".").pop();
  if (ext === "ogg") return url.slice(0, url.lastIndexOf(ext) - 1) + ".rpgmvo";
  if (ext === "m4a") return url.slice(0, url.lastIndexOf(ext) - 1) + ".rpgmvm";
  return url;
}

const mobileEncrypted = audioFileExt({ encrypted: true, mobile: true, canPlayOgg: false });
if (mobileEncrypted !== ".ogg") throw new Error("encrypted mobile audio selected .m4a");
if (encryptedExt("audio/bgm/title" + mobileEncrypted) !== "audio/bgm/title.rpgmvo") {
  throw new Error("encrypted mobile audio did not resolve to .rpgmvo");
}
if (encryptedExt("audio/bgm/title.m4a") !== "audio/bgm/title.rpgmvm") {
  throw new Error("control mapping for legacy .m4a changed unexpectedly");
}
if (audioFileExt({ encrypted: false, mobile: true, canPlayOgg: false }) !== ".m4a") {
  throw new Error("unencrypted mobile behavior changed");
}
if (audioFileExt({ encrypted: false, mobile: false, canPlayOgg: true }) !== ".ogg") {
  throw new Error("desktop OGG behavior changed");
}

console.log("MV encrypted-audio extension regression passed: mobile encrypted .ogg -> .rpgmvo");
