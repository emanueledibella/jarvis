import { Capacitor, registerPlugin } from "@capacitor/core";

type RecordValue = Record<string, any>;
type Credentials = { server_url: string; device_id: string; refresh_token?: string; session_id: string; scopes?: string[] };
export interface NativeBridge {
  platform: string;
  load(): Promise<Credentials | null>;
  save(value: Credentials): Promise<void>;
  clear(): Promise<void>;
  selectDirectory?(): Promise<string | null>;
  configureExecutor?(value: RecordValue): Promise<void>;
  executorStatus?(): Promise<RecordValue>;
  setExecutorEnabled?(enabled: boolean): Promise<void>;
  notify?(value: { sequence: number; created_at: string }): Promise<void>;
}
declare global { interface Window { jarvisCompanion?: NativeBridge } }

interface NativePlugin {
  shared(): Promise<{ items: RecordValue[] }>;
  removeShared(options: { id: string }): Promise<void>;
  load(): Promise<{ value?: string }>;
  save(options: { value: string }): Promise<void>;
  clear(): Promise<void>;
  startRecording(): Promise<void>;
  stopRecording(): Promise<{ content: string; mime: string; seconds: number }>;
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

export class RemoteClient {
  enabled = false;
  credentials: Credentials | null = null;
  access = "";
  expires = 0;
  vault = nativeVault();
  private refreshPromise: Promise<void> | null = null;
  private initialization: Promise<boolean> | null = null;
  private persistence: Promise<void> = Promise.resolve();
  private conversationSessions = new Map<string, string>();
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
    const saved = this.vault ? await this.vault.load() : null;
    if (saved) {
      this.enabled = true;
      this.credentials = { ...saved, server_url: validateServerURL(saved.server_url, import.meta.env.DEV) };
      await this.discover(this.origin);
      await this.refresh();
      return true;
    }
    if (this.vault) { this.enabled = true; return true; }
    try { await this.discover(location.origin); }
    catch { return false; }
    this.enabled = true;
    this.credentials = { server_url: location.origin, device_id: "", session_id: sessionStorage.getItem("jarvis-remote-session") || crypto.randomUUID() };
    sessionStorage.setItem("jarvis-remote-session", this.sessionId);
    try { await this.refresh(); } catch { this.credentials = null; }
    return true;
  }

  async enroll(address: string, code: string, name: string) {
    const origin = validateServerURL(address, import.meta.env.DEV);
    await this.discover(origin);
    const response = await fetch(origin + "/remote/v1/pair", {
      method: "POST", redirect: "error", credentials: this.vault ? "omit" : "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code: code.trim(), name: name.trim(), platform: this.platform }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Pairing failed.");
    if (result.kind !== "companion") throw new Error("Use a companion pairing code, not an executor code.");
    this.credentials = { server_url: origin, device_id: result.device_id, session_id: crypto.randomUUID(), scopes: result.scopes, ...(result.refresh_token ? { refresh_token: result.refresh_token } : {}) };
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
    const session = id ? this.conversationSessions.get(id) || crypto.randomUUID() : crypto.randomUUID();
    if (id) this.conversationSessions.set(id, session);
    this.credentials.session_id = session;
    await this.persist();
  }

  bindConversation(id: string) {
    this.conversationSessions.set(id, this.sessionId);
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
          throw new Error("Session expired or revoked. Pair this device again.");
        }
        throw new Error("The core is temporarily unavailable. Retry the connection.");
      }
      this.credentials = { server_url: this.origin, session_id: this.sessionId || crypto.randomUUID(), ...this.credentials, device_id: result.device_id, scopes: result.scopes, ...(result.refresh_token ? { refresh_token: result.refresh_token } : {}) };
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
