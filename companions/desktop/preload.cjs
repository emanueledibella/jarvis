"use strict";
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("jarvisCompanion", {
  platform: process.platform === "darwin" ? "macos" : "windows",
  load: () => ipcRenderer.invoke("vault:load"),
  save: value => ipcRenderer.invoke("vault:save", value),
  clear: () => ipcRenderer.invoke("vault:clear"),
  selectDirectory: () => ipcRenderer.invoke("executor:directory"),
  configureExecutor: value => ipcRenderer.invoke("executor:configure", value),
  executorStatus: () => ipcRenderer.invoke("executor:status"),
  setExecutorEnabled: enabled => ipcRenderer.invoke("executor:enabled", enabled),
  notify: value => ipcRenderer.invoke("notification:show", value),
  voiceStart: options => ipcRenderer.invoke("voice:start", options),
  setVoiceEnabled: options => ipcRenderer.invoke("voice:enabled", options),
  voiceStop: () => ipcRenderer.invoke("voice:stop"),
  voiceFinalizeRecognition: () => ipcRenderer.invoke("voice:finalize-recognition"),
  voiceBeginLive: options => ipcRenderer.invoke("voice:begin-live", options),
  voiceReadLive: () => ipcRenderer.invoke("voice:read-live"),
  voiceStartLivePlayback: () => ipcRenderer.invoke("voice:start-live-playback"),
  voicePlayLive: options => ipcRenderer.invoke("voice:play-live", options),
  voiceInputs: () => ipcRenderer.invoke("voice:inputs"),
  voiceSpeak: options => ipcRenderer.invoke("voice:speak", options),
  setLaunchAtLogin: enabled => ipcRenderer.invoke("voice:autostart", enabled),
  onVoice: listener => {
    const receive = (_event, value) => listener(value);
    ipcRenderer.on("voice:event", receive);
    return () => ipcRenderer.removeListener("voice:event", receive);
  },
});
ipcRenderer.on("notification:open", () => window.dispatchEvent(new Event("jarvis-remote-open-tasks")));
ipcRenderer.on("voice:listen", () => window.dispatchEvent(new Event("jarvis-remote-voice")));
ipcRenderer.on("voice:mute", () => window.dispatchEvent(new Event("jarvis-companion-mute")));
