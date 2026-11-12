"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

class CompanionVoice {
  constructor(app, emit) { this.app = app; this.emit = emit; this.pending = new Map(); this.sequence = 0; this.child = null; }
  request(command, options = {}) {
    if (!["start", "stop", "inputs", "speak", "finalize-recognition", "begin-live", "read-live", "start-live-playback", "play-live"].includes(command) || !options || typeof options !== "object" || JSON.stringify(options).length > (command === "play-live" ? 98000 : 20000)) return Promise.reject(new Error("Invalid voice command."));
    if (command === "start" && (typeof options.language !== "string" || options.language.length > 80 || typeof options.phrase !== "string" || options.phrase.length > 40 || typeof options.microphone !== "string" || options.microphone.length > 512)) return Promise.reject(new Error("Invalid speech options."));
    if (command === "speak" && (typeof options.text !== "string" || options.text.length > 4000 || typeof options.language !== "string" || options.language.length > 80 || typeof options.voice !== "string" || options.voice.length > 512)) return Promise.reject(new Error("Invalid speech options."));
    if (command === "begin-live" && (!Number.isSafeInteger(options.frame) || options.frame <= 0)) return Promise.reject(new Error("Invalid wake timestamp."));
    if (command === "play-live" && (typeof options.audio !== "string" || options.audio.length > 96000 || !Number.isSafeInteger(options.id))) return Promise.reject(new Error("Invalid voice audio."));
    if ((command.endsWith("-live") || command === "finalize-recognition") && !this.child) return Promise.reject(new Error("Listening was cancelled."));
    if (!this.child && command === "stop") return Promise.resolve({});
    if (!this.child) {
      if (process.platform !== "darwin") return Promise.reject(new Error("Native wake listening is unavailable on this desktop platform."));
      const binary = this.app.isPackaged ? path.join(process.resourcesPath, "native-helper", "JarvisCompanionVoice") : path.resolve(__dirname, "../../dist/native-helper/JarvisCompanionVoice");
      if (!fs.existsSync(binary)) return Promise.reject(new Error("Rebuild the companion native voice helper."));
      const environment = Object.fromEntries(["PATH", "HOME", "TMPDIR", "LANG"].filter(key => process.env[key]).map(key => [key, process.env[key]]));
      const child = spawn(binary, [], { stdio: ["pipe", "pipe", "pipe"], shell: false, env: environment });
      this.child = child;
      let buffer = "";
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", data => {
        buffer += data;
        const lines = buffer.split("\n"); buffer = lines.pop();
          if (buffer.length > 65536 || lines.some(line => line.length > 65536)) { this.close(); return; }
        for (const line of lines) {
          try {
            const value = JSON.parse(line);
            if (value.type === "reply") {
              const request = this.pending.get(value.id);
              if (request) { clearTimeout(request.timer); this.pending.delete(value.id); value.error ? request.reject(new Error(value.error)) : request.resolve(value.result); }
            } else if (["transcript", "ready", "recovering", "error", "level", "live_playback_finished"].includes(value.type)) this.emit(value);
          } catch { /* Private diagnostics are never forwarded. */ }
        }
      });
      child.stderr.on("data", () => {});
      child.stdin.on("error", () => this.close());
      child.once("error", () => this.close());
      child.once("exit", () => {
        if (this.child === child) { this.close(); this.emit({ type: "error", message: "The speech service stopped. Enable voice to reconnect." }); }
      });
    }
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("Voice operation timed out.")); if (command === "start") this.close(); }, command === "speak" ? 180000 : 60000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, command, options }) + "\n");
    });
  }
  close() {
    const child = this.child; this.child = null;
    if (child) { child.stdin.end(); child.kill(); }
    for (const request of this.pending.values()) { clearTimeout(request.timer); request.reject(new Error("Voice stopped.")); }
    this.pending.clear();
  }
}
module.exports = { CompanionVoice };
