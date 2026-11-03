"use strict";
const { app, BrowserWindow, protocol, net, ipcMain, safeStorage, dialog, shell, Tray, Menu, nativeImage, Notification } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { spawn } = require("node:child_process");
const { trustedFrame, safeExternal, validateCredentials } = require("./security.cjs");

protocol.registerSchemesAsPrivileged([{ scheme: "jarvis", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } }]);
app.enableSandbox();
if (process.platform === "win32") app.setAppUserModelId("it.jarvis.companion");
if (!app.requestSingleInstanceLock()) app.quit();
let window, tray, executor, quitting = false, currentStatus = { state: "stopped" };
const selectedDirectories = new Set();
const storePath = () => path.join(app.getPath("userData"), "companion.vault");
const agentDirectory = () => path.join(app.getPath("userData"), "executor");
const statePath = () => path.join(app.getPath("userData"), "desktop.json");
const uiRoot = () => app.isPackaged ? path.join(process.resourcesPath, "ui") : path.resolve(__dirname, "../../web/dist");
function privateWrite(filename, content) {
  fs.mkdirSync(path.dirname(filename), { recursive: true, mode: 0o700 });
  const temporary = filename + ".tmp";
  fs.writeFileSync(temporary, content, { mode: 0o600 });
  fs.renameSync(temporary, filename);
}
function vaultLoad() {
  if (!fs.existsSync(storePath())) return null;
  if (!safeStorage.isEncryptionAvailable()) throw new Error("Il deposito credenziali del sistema non è disponibile.");
  return validateCredentials(JSON.parse(safeStorage.decryptString(fs.readFileSync(storePath()))));
}
function state() { try { return JSON.parse(fs.readFileSync(statePath(), "utf8")); } catch { return { executorEnabled: false }; } }
function handle(name, operation) {
  ipcMain.handle(name, async (event, value) => {
    if (!trustedFrame(event.senderFrame?.url) || event.sender !== window?.webContents) throw new Error("Untrusted caller.");
    return operation(value);
  });
}
function executorCommand() {
  if (app.isPackaged) return { binary: path.join(process.resourcesPath, "executor", "JarvisExecutor", process.platform === "win32" ? "JarvisExecutor.exe" : "JarvisExecutor"), prefix: [] };
  const root = path.resolve(__dirname, "../..");
  return { binary: path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"), prefix: ["-m", "jarvis.executor"] };
}
function launchExecutor(extra = [], input) {
  const { binary, prefix } = executorCommand();
  if (!fs.existsSync(binary)) throw new Error("Esecutore non incluso nella distribuzione. Ricostruisci il pacchetto desktop.");
  const environment = Object.fromEntries(["PATH", "HOME", "SystemRoot", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE"].filter(k => process.env[k]).map(k => [k, process.env[k]]));
  const child = spawn(binary, [...prefix, "--data-dir", agentDirectory(), ...extra], { shell: false, windowsHide: true, stdio: ["pipe", "pipe", "pipe"], env: { ...environment, JARVIS_EXECUTOR_MANAGED: "1", LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false" } });
  if (input) child.stdin.end(JSON.stringify(input));
  return child;
}
function startExecutor() {
  if (executor) return;
  if (!fs.existsSync(path.join(agentDirectory(), "executor.json"))) throw new Error("Configura prima l’esecutore.");
  currentStatus = { state: "starting" };
  const child = launchExecutor(); executor = child;
  let buffer = "";
  child.stdout.on("data", bytes => {
    buffer = (buffer + bytes.toString()).slice(-8192);
    const lines = buffer.split("\n"); buffer = lines.pop();
    for (const line of lines) {
      try { const value = JSON.parse(line); if (value.type === "executor.status") currentStatus = { state: value.state }; } catch { /* Only bounded protocol status is consumed. */ }
    }
  });
  child.stderr.on("data", () => { /* Private process diagnostics are not forwarded to the renderer. */ });
  child.on("error", () => { currentStatus = { state: "failed" }; });
  child.on("exit", () => { if (executor === child) { executor = null; if (currentStatus.state !== "pairing_required") currentStatus = { state: "stopped" }; } });
}
async function stopExecutor() {
  const child = executor;
  if (!child) return;
  child.stdin.write('{"type":"shutdown"}\n');
  await new Promise(resolve => {
    const timer = setTimeout(() => { child.kill(); resolve(); }, 5000);
    child.once("exit", () => { clearTimeout(timer); resolve(); });
  });
  if (executor === child) executor = null;
  currentStatus = { state: "stopped" };
}
async function createWindow() {
  window = new BrowserWindow({ width: 1320, height: 900, minWidth: 390, minHeight: 650, show: false,
    title: "Jarvis Companion", backgroundColor: "#07131d",
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, allowRunningInsecureContent: false, spellcheck: true } });
  window.webContents.setWindowOpenHandler(({ url }) => { if (safeExternal(url)) void shell.openExternal(url); return { action: "deny" }; });
  window.webContents.on("will-navigate", (event, url) => { if (!trustedFrame(url)) { event.preventDefault(); if (safeExternal(url)) void shell.openExternal(url); } });
  window.webContents.session.setPermissionRequestHandler((contents, permission, callback, details) => {
    callback(contents === window.webContents && window.isVisible() && trustedFrame(contents.getURL()) && permission === "media" && details.mediaTypes?.length > 0 && details.mediaTypes.every(type => type === "audio"));
  });
  window.on("close", event => { if (!quitting) { event.preventDefault(); window.hide(); } });
  await window.loadURL("jarvis://app/index.html");
  if (!process.argv.includes("--background")) window.show();
  if (process.env.JARVIS_COMPANION_SMOKE === "1") {
    await new Promise(resolve => setTimeout(resolve, 1500));
    const file = path.resolve(__dirname, "../../output/companion-smoke.png");
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, (await window.webContents.capturePage()).toPNG());
    quitting = true; app.quit();
  }
}

app.whenReady().then(async () => {
  protocol.handle("jarvis", async request => {
    const url = new URL(request.url);
    if (url.host !== "app") return new Response("Denied", { status: 403 });
    const root = uiRoot();
    const filename = path.resolve(root, "." + decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname));
    if (!filename.startsWith(root + path.sep) || !fs.existsSync(filename) || !fs.statSync(filename).isFile()) return new Response("Not found", { status: 404 });
    const response = await net.fetch(pathToFileURL(filename).toString());
    const headers = new Headers(response.headers);
    headers.set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https: wss:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-src 'none'");
    headers.set("Referrer-Policy", "no-referrer");
    return new Response(response.body, { status: response.status, headers });
  });
  handle("vault:load", () => vaultLoad());
  handle("vault:save", value => { validateCredentials(value); if (!safeStorage.isEncryptionAvailable()) throw new Error("Deposito credenziali non disponibile."); privateWrite(storePath(), safeStorage.encryptString(JSON.stringify(value))); });
  handle("vault:clear", () => { if (fs.existsSync(storePath())) fs.unlinkSync(storePath()); });
  handle("executor:directory", async () => {
    const result = await dialog.showOpenDialog(window, { title: "Cartella autorizzata per Jarvis", properties: ["openDirectory"] });
    if (result.canceled) return null;
    const chosen = fs.realpathSync(result.filePaths[0]); selectedDirectories.add(chosen); return chosen;
  });
  handle("executor:configure", async value => {
    if (!value || JSON.stringify(value).length > 16000 || value.server_url !== vaultLoad()?.server_url || !Array.isArray(value.workspaces) || value.workspaces.some(w => !selectedDirectories.has(fs.realpathSync(w.path)))) throw new Error("Seleziona cartelle locali e il server già abbinato.");
    await stopExecutor();
    if (value.native?.length) {
      if (process.platform !== "darwin") throw new Error("Le capacità native richiedono macOS.");
      value.native_helper = app.isPackaged ? path.join(process.resourcesPath, "native-helper", "JarvisNativeHelper") : path.resolve(__dirname, "../../dist/native-helper/JarvisNativeHelper");
    } else { delete value.native_helper; }
    const child = launchExecutor(["--configure"], value);
    await new Promise((resolve, reject) => { child.stderr.on("data", () => {}); child.once("error", reject); child.once("exit", code => code === 0 ? resolve() : reject(new Error("Configurazione esecutore non riuscita. Verifica codice, permessi e deposito credenziali."))); });
    privateWrite(statePath(), JSON.stringify({ ...state(), executorEnabled: true }));
    app.setLoginItemSettings({ openAtLogin: true, args: ["--background"] });
    startExecutor();
  });
  handle("executor:status", () => currentStatus);
  handle("notification:show", value => {
    if (!value || !Number.isSafeInteger(value.sequence) || value.sequence < 1 || typeof value.created_at !== "string" || value.created_at.length > 64) throw new Error("Invalid notification metadata.");
    const credentials = vaultLoad();
    if (!credentials) return;
    const saved = state(), seen = saved.lastNotifications || {};
    if (value.sequence <= (seen[credentials.device_id] || 0)) return;
    seen[credentials.device_id] = value.sequence;
    privateWrite(statePath(), JSON.stringify({ ...saved, lastNotifications: Object.fromEntries(Object.entries(seen).slice(-25)) }));
    const created = Date.parse(value.created_at);
    if (!Number.isFinite(created) || Date.now() - created > 300000 || created - Date.now() > 30000 || (window.isVisible() && window.isFocused()) || !Notification.isSupported()) return;
    const notification = new Notification({ title: "Jarvis", body: "Hai un aggiornamento. Apri Jarvis per i dettagli." });
    notification.on("click", () => { window.show(); window.focus(); window.webContents.send("notification:open"); });
    notification.show();
  });
  handle("executor:enabled", async value => {
    if (typeof value !== "boolean") throw new Error("Invalid state.");
    if (value) startExecutor(); else await stopExecutor();
    privateWrite(statePath(), JSON.stringify({ ...state(), executorEnabled: value }));
    app.setLoginItemSettings({ openAtLogin: value, args: ["--background"] });
  });
  await createWindow();
  const iconPath = app.isPackaged ? path.join(process.resourcesPath, "jarvis.png") : path.resolve(__dirname, "../../assets/jarvis-icon.png");
  tray = new Tray(nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 }));
  tray.setToolTip("Jarvis Companion");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Apri Jarvis", click: () => window.show() },
    { label: "Ferma esecutore", click: () => void stopExecutor() },
    { type: "separator" }, { label: "Esci", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("click", () => window.show());
  if (state().executorEnabled) { try { startExecutor(); } catch { currentStatus = { state: "configuration_required" }; } }
});
app.on("second-instance", () => { window?.show(); window?.focus(); });
app.on("activate", () => window?.show());
app.on("window-all-closed", () => {});
app.on("before-quit", event => {
  quitting = true;
  if (executor) { event.preventDefault(); void stopExecutor().finally(() => app.quit()); }
});
