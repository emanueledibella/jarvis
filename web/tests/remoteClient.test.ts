import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

let vite: any, Client: any, validate: any;
const originalFetch = globalThis.fetch;
const saved = { server_url: "https://jarvis.example", device_id: "10000000-0000-4000-8000-000000000001", session_id: "10000000-0000-4000-8000-000000000002", refresh_token: "synthetic-refresh", scopes: ["read", "chat", "control", "admin"] };
const writes: any[] = [];

before(async () => {
  Object.assign(globalThis, { location: new URL("https://jarvis.example/"), window: {
    jarvisCompanion: { platform: "macos", load: async () => ({ ...saved }), save: async (value: any) => { writes.push(structuredClone(value)); }, clear: async () => {}, },
    dispatchEvent() {},
  } });
  vite = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false,
    server: { middlewareMode: true, watch: null, ws: false }, optimizeDeps: { noDiscovery: true, include: [] } });
  const module = await vite.ssrLoadModule("/src/remoteClient.ts");
  Client = module.RemoteClient; validate = module.validateServerURL;
});
after(async () => { globalThis.fetch = originalFetch; await vite?.close(); });

test("remote transport requires TLS and accepts loopback HTTP only explicitly", () => {
  for (const value of ["http://jarvis.example", "https://u:p@jarvis.example", "https://jarvis.example/api", "https://jarvis.example/#token", "javascript:alert(1)"])
    assert.throws(() => validate(value));
  assert.equal(validate("https://jarvis.example/"), "https://jarvis.example");
  assert.throws(() => validate("http://127.0.0.1:8765"));
  assert.equal(validate("http://127.0.0.1:8765", true), "http://127.0.0.1:8765");
});

test("parallel initialization rotates once and persists only native refresh credentials", async () => {
  let refreshes = 0;
  globalThis.fetch = async (input: any, options: any) => {
    if (String(input).endsWith("/info")) return Response.json({ service: "jarvis-remote", protocol: 1, public_url: saved.server_url });
    assert.equal(String(input), saved.server_url + "/remote/v1/refresh");
    assert.equal(options.redirect, "error");
    refreshes++;
    return Response.json({ access_token: "synthetic-access", refresh_token: "rotated", device_id: saved.device_id, scopes: saved.scopes, expires_in: 300 });
  };
  const client = new Client();
  assert.deepEqual(await Promise.all([client.initialize(), client.initialize(), client.initialize()]), [true, true, true]);
  assert.equal(refreshes, 1);
  assert.equal(client.admin, true);
  assert.equal(writes.at(-1).refresh_token, "rotated");
  assert.equal(writes.at(-1).access_token, undefined);
});

test("a 401 retry retains the originating conversation after switching conversations", async () => {
  const client = new Client(); client.credentials = { ...saved }; client.access = "old"; client.expires = Date.now() + 300000;
  let release: any; const refreshStarted = new Promise<void>(resolve => { release = resolve; });
  let resume: any; const canRefresh = new Promise<void>(resolve => { resume = resolve; });
  const sessions: string[] = [];
  globalThis.fetch = async (input: any, options: any) => {
    if (String(input).endsWith("/refresh")) {
      release(); await canRefresh;
      return Response.json({ access_token: "new", refresh_token: "next", expires_in: 300, device_id: saved.device_id, scopes: saved.scopes });
    }
    sessions.push(new Headers(options.headers).get("X-Jarvis-Session")!);
    return sessions.length === 1 ? Response.json({ detail: "expired" }, { status: 401 }) : Response.json({ ok: true });
  };
  const request = client.request("/api/tasks");
  await refreshStarted;
  await client.selectConversation("second-conversation");
  assert.notEqual(client.sessionId, saved.session_id);
  resume();
  assert.equal((await request).status, 200);
  assert.deepEqual(sessions, [saved.session_id, saved.session_id]);
});

test("offline sign out removes local credentials without claiming server revocation", async () => {
  let cleared = false, event: any;
  const client = new Client(); client.credentials = { ...saved }; client.access = "synthetic"; client.expires = Date.now() + 300000;
  client.vault = { clear: async () => { cleared = true; } };
  globalThis.fetch = async () => { throw new TypeError("synthetic network offline"); };
  const dispatch = window.dispatchEvent;
  window.dispatchEvent = (value: any) => { event = value; return true; };
  try {
    await client.logout();
    assert.equal(cleared, true);
    assert.equal(client.authenticated, false);
    assert.equal(event.detail.revoked, false);
  } finally { window.dispatchEvent = dispatch; }
});
