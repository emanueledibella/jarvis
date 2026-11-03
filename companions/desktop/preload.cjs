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
});
ipcRenderer.on("notification:open", () => window.dispatchEvent(new Event("jarvis-remote-open-tasks")));
