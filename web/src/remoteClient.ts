import { Capacitor, registerPlugin, type PluginListenerHandle } from "@capacitor/core";
import { randomId } from "./randomId";
import type { HealthMetric, HealthSnapshot } from "./appleHealthNative";

type RecordValue = Record<string, any>;
type Credentials = { server_url: string; device_id: string; refresh_token?: string; session_id: string; scopes?: string[] };
export interface NativeLiveBridge {
  voiceFinalizeRecognition(): Promise<void>;
  voiceBeginLive(options: { frame: number }): Promise<{ started: boolean }>;
  voiceReadLive(): Promise<{ audio: string }>;
  voicePlayLive(options: { audio: string; id: number }): Promise<{ output: number }>;
}
export interface NativeLivePlayback {
  voiceStartLivePlayback(): Promise<void>;
  voicePlayLive: NativeLiveBridge["voicePlayLive"];
}
type VoiceStart = { language: string; phrase: string; microphone: string; bufferLive?: boolean };
export interface DesktopExecutorStatus {
  state: "stopped" | "starting" | "connected" | "reconnecting" | "receipt_pending" | "pairing_required" | "failed" | "configuration_required";
  configured: boolean;
  running: boolean;
}
export interface DesktopExecutorBridge {
  platform: string;
  selectDirectory(): Promise<string | null>;
  configureExecutor(value: RecordValue): Promise<void>;
  executorStatus(): Promise<DesktopExecutorStatus>;
  setExecutorEnabled(enabled: boolean): Promise<void>;
}
export interface NativeBridge extends Partial<NativeLiveBridge & NativeLivePlayback & DesktopExecutorBridge> {
  platform: string;
  load(): Promise<Credentials | null>;
  save(value: Credentials): Promise<void>;
  clear(): Promise<void>;
  notify?(value: { sequence: number; created_at: string }): Promise<void>;
  voiceStart?(options: VoiceStart): Promise<void>;
  setVoiceEnabled?(options: { enabled: boolean; allowLocked: boolean }): Promise<void>;
  voiceStop?(): Promise<void>;
  voiceInputs?(): Promise<RecordValue>;
  voiceSpeak?(options: { text: string; language: string; voice: string }): Promise<void>;
  onVoice?(listener: (value: RecordValue) => void): () => void;
  setLaunchAtLogin?(enabled: boolean): Promise<RecordValue>;
}
declare global { interface Window { jarvisCompanion?: NativeBridge } }

interface NativePlugin extends NativeLiveBridge, NativeLivePlayback {
  addListener(event: "voice", listener: (value: RecordValue) => void): Promise<PluginListenerHandle>;
  voiceStart(options: VoiceStart): Promise<void>;
  voiceStop(): Promise<void>;
  voiceSpeak(options: { text: string; language: string; voice: string }): Promise<void>;
  voiceInputs(): Promise<RecordValue>;
  shared(): Promise<{ items: RecordValue[] }>;
  removeShared(options: { id: string }): Promise<void>;
  load(): Promise<{ value?: string }>;
  save(options: { value: string }): Promise<void>;
  clear(): Promise<void>;
  startRecording(): Promise<void>;
  stopRecording(): Promise<{ content: string; mime: string; seconds: number }>;
  healthStatus(): Promise<{ available: boolean }>;
  healthRead(options: { metrics: HealthMetric[]; days: number }): Promise<HealthSnapshot>;
  healthCancel(): Promise<void>;
}
export const nativePlugin = registerPlugin<NativePlugin>("JarvisNative");

function nativeVault(): NativeBridge | null {
  if (typeof window === "undefined") return null;
  if (window.jarvisCompanion) return window.jarvisCompanion;
  if (!Capacitor.isNativePlatform()) return null;
  return {
    platform: Capacitor.getPlatform(),
    async load() { const result = await nativePlugin.load(); return result.value ? JSON.parse(result.value) : null; },
    async save(value) { await nativePlugin.save({ value: JSON.stringify(value) }); },
    async clear() { await nativePlugin.clear(); },
  };
}

export function validateServerURL(value: string, development = false): string {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) throw new Error("Enter the server origin without a path or credentials.");
  if (url.protocol !== "https:" && !(development && url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname))) throw new Error("Use an HTTPS server address.");
  return url.origin;
}

export class RemoteSessionExpired extends Error {}

export class RemoteClient {
  enabled = false;
  credentials: Credentials | null = null;
  access = "";
  expires = 0;
  vault = nativeVault();
  private refreshPromise: Promise<void> | null = null;
  private initialization: Promise<boolean> | null = null;
  private enrollment: Promise<void> | null = null;
  private persistence: Promise<void> = Promise.resolve();
  private conversationSessions = new Map<string, string>();
  conversationId: string | null = null;
  private get origin() { return this.credentials?.server_url || location.origin; }
  get authenticated() { return !!this.access && !!this.credentials; }
  get sessionId() { return this.credentials?.session_id || ""; }
  get admin() { return this.credentials?.scopes?.includes("admin") ?? false; }
  get platform() { return this.vault?.platform || "web"; }

  async discover(origin: string) {
    const response = await fetch(origin + "/remote/v1/info", { redirect: "error", cache: "no-store", signal: AbortSignal.timeout(8000) });
    const data = await response.json();
    if (!response.ok || data.service !== "jarvis-remote" || data.protocol !== 1 || data.public_url !== origin) throw new Error("This address is not a compatible Jarvis core.");
    return data;
  }

  initialize(): Promise<boolean> {
    if (!this.initialization) this.initialization = this.detect().catch(error => { this.initialization = null; throw error; });
    return this.initialization;
  }

  private async detect(): Promise<boolean> {
    if (window.__JARVIS_NATIVE__ && !this.vault) return false;
    const saved = this.vault ? (this.credentials ?? await this.vault.load()) : null;
    if (saved) {
      this.enabled = true;
      this.credentials = { ...saved, server_url: validateServerURL(saved.server_url, import.meta.env.DEV) };
      await this.discover(this.origin);
      // If the previous attempt received a rotated token but could not save
      // it, retry the write rather than loading and replaying the old token.
      if (this.authenticated && Date.now() < this.expires - 20_000) await this.persist();
      else await this.refresh();
      return true;
    }
    if (this.vault) { this.enabled = true; return true; }
    try { await this.discover(location.origin); }
    catch { return false; }
    this.enabled = true;
    this.credentials = { server_url: location.origin, device_id: "", session_id: sessionStorage.getItem("jarvis-remote-session") || randomId() };
    sessionStorage.setItem("jarvis-remote-session", this.sessionId);
    try { await this.refresh(); } catch { this.credentials = null; }
    return true;
  }

  enroll(address: string, code: string, name: string): Promise<void> {
    if (this.enrollment) return this.enrollment;
    this.enrollment = this.enrollDevice(address, code, name).finally(() => { this.enrollment = null; });
    return this.enrollment;
  }

  private async enrollDevice(address: string, code: string, name: string) {
    const origin = validateServerURL(address, import.meta.env.DEV);
    // Prepare the session before consuming the server's one-use code.
    const sessionId = randomId();
    await this.discover(origin);
    const response = await fetch(origin + "/remote/v1/pair", {
      method: "POST", redirect: "error", credentials: this.vault ? "omit" : "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.trim(), name: name.trim(), platform: this.platform }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Pairing failed.");
    if (result.kind !== "companion") throw new Error("Use a companion pairing code, not an executor code.");
    this.credentials = { server_url: origin, device_id: result.device_id, session_id: sessionId, scopes: result.scopes, ...(result.refresh_token ? { refresh_token: result.refresh_token } : {}) };
    this.access = result.access_token;
    this.expires = Date.now() + result.expires_in * 1000;
    this.enabled = true;
    await this.persist();
  }

  private async persist() {
    const save = async () => {
      if (this.vault && this.credentials) await this.vault.save(this.credentials);
      else if (this.credentials) sessionStorage.setItem("jarvis-remote-session", this.sessionId);
    };
    this.persistence = this.persistence.then(save, save);
    return this.persistence;
  }

  async selectConversation(id?: string) {
    if (!this.credentials) return;
    const session = id ? this.conversationSessions.get(id) || randomId() : randomId();
    if (id) this.conversationSessions.set(id, session);
    this.credentials.session_id = session;
    this.conversationId = id || null;
    await this.persist();
    window.dispatchEvent(new Event("jarvis-session-changed"));
  }

  bindConversation(id: string) {
    this.conversationId = id;
    this.conversationSessions.set(id, this.sessionId);
  }

  async voiceSocket() {
    if (Date.now() > this.expires - 20_000) await this.refresh();
    const url = new URL(this.origin + "/remote/v1/voice/live");
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url);
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { socket.close(); reject(new Error("Voice connection timed out.")); }, 8000);
      socket.onopen = () => { clearTimeout(timer); resolve(); };
      socket.onerror = () => { clearTimeout(timer); reject(new Error("Voice connection unavailable.")); };
      socket.onclose = () => { clearTimeout(timer); reject(new Error("Voice connection closed.")); };
    });
    // Tokens stay out of URLs, logs, localStorage and native speech processes.
    socket.send(JSON.stringify({ type: "authenticate", access_token: this.access, session_id: this.sessionId }));
    return socket;
  }

  async refresh() {
    if (this.refreshPromise) return this.refreshPromise;
    const perform = async () => {
      const response = await fetch(this.origin + "/remote/v1/refresh", {
        method: "POST", redirect: "error", credentials: this.vault ? "omit" : "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(this.vault ? { refresh_token: this.credentials?.refresh_token } : {}),
      });
      const result = await response.json();
      if (!response.ok) {
        if ([401, 403].includes(response.status)) {
          this.access = "";
          window.dispatchEvent(new Event("jarvis-remote-session-expired"));
          throw new RemoteSessionExpired("Session expired or revoked. Pair this device again.");
        }
        throw new Error("The core is temporarily unavailable. Retry the connection.");
      }
      this.credentials = { server_url: this.origin, session_id: this.sessionId || randomId(), ...this.credentials, device_id: result.device_id, scopes: result.scopes, ...(result.refresh_token ? { refresh_token: result.refresh_token } : {}) };
      this.access = result.access_token;
      this.expires = Date.now() + result.expires_in * 1000;
      await this.persist();
    };
    this.refreshPromise = (!this.vault && typeof navigator !== "undefined" && navigator.locks
      ? navigator.locks.request("jarvis-remote-refresh:" + this.origin, perform)
      : perform()).finally(() => { this.refreshPromise = null; });
    return this.refreshPromise;
  }

  async request(path: string, options: RequestInit = {}, retry = true, sessionId = this.sessionId): Promise<Response> {
    if (!path.startsWith("/api/") && !path.startsWith("/remote/v1/")) throw new Error("Unsupported core route.");
    if (Date.now() > this.expires - 20_000) await this.refresh();
    const url = new URL(this.origin + path);
    for (const name of ["session_id", "attachment_session"]) if (url.searchParams.has(name)) url.searchParams.set(name, sessionId);
    let body = options.body;
    if (typeof body === "string") {
      try {
        const value = JSON.parse(body);
        for (const name of ["session_id", "attachment_session"]) if (name in value) value[name] = sessionId;
        body = JSON.stringify(value);
      } catch { /* Non-JSON uploads keep their original body. */ }
    }
    const headers = new Headers(options.headers);
    headers.set("Authorization", "Bearer " + this.access);
    headers.set("X-Jarvis-Session", sessionId);
    const response = await fetch(url, { ...options, body, headers, redirect: "error", cache: "no-store", credentials: "omit" });
    if (response.status === 401 && retry) { await this.refresh(); return this.request(path, options, false, sessionId); }
    return response;
  }

  async json<T = RecordValue>(path: string, body?: unknown, method?: string): Promise<T> {
    const response = await this.request("/remote/v1/" + path, { method: method || (body === undefined ? "GET" : "POST"), headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "The core could not complete this operation.");
    return result;
  }

  async logout() {
    let revoked = !this.authenticated;
    if (this.authenticated) {
      try { await this.json("devices/" + this.credentials!.device_id + "/revoke", {}); revoked = true; }
      catch { /* Forgetting local credentials must also work when the server is offline. */ }
    }
    await this.vault?.clear();
    this.access = ""; this.credentials = null; this.expires = 0;
    window.dispatchEvent(new CustomEvent("jarvis-remote-logout", { detail: { revoked } }));
  }
}

export const remoteClient = new RemoteClient();
