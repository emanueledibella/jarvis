import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

let vite: any, Client: any, SessionExpired: any, validate: any;
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
  Client = module.RemoteClient; SessionExpired = module.RemoteSessionExpired; validate = module.validateServerURL;
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

test("a temporarily unavailable vault can reconnect the same iPhone without a pairing code", async () => {
  const client = new Client();
  let unlocked = false;
  let refreshes = 0;
  client.vault = {
    platform: "ios",
    load: async () => { if (!unlocked) throw new Error("The iPhone is locked."); return { ...saved }; },
    save: async () => {},
    clear: async () => { throw new Error("Do not erase the pairing"); },
  };
  globalThis.fetch = async (input: any, options: any) => {
    if (String(input).endsWith("/info")) return Response.json({ service: "jarvis-remote", protocol: 1, public_url: saved.server_url });
    assert.equal(String(input), saved.server_url + "/remote/v1/refresh");
    assert.equal(JSON.parse(options.body).refresh_token, saved.refresh_token);
    refreshes++;
    return Response.json({ access_token: "restored-access", refresh_token: "rotated", device_id: saved.device_id, scopes: saved.scopes, expires_in: 300 });
  };
  await assert.rejects(client.initialize(), (error: any) => !(error instanceof SessionExpired) && /locked/.test(error.message));
  assert.equal(refreshes, 0);
  unlocked = true;
  assert.equal(await client.initialize(), true);
  assert.equal(client.authenticated, true);
  assert.equal(client.credentials.device_id, saved.device_id);
  assert.equal(refreshes, 1);
});

test("a failed vault write retries the rotated token save without replaying the old token", async () => {
  const client = new Client();
  let refreshes = 0;
  let saves = 0;
  client.vault = {
    platform: "ios",
    load: async () => ({ ...saved }),
    save: async (value: any) => {
      assert.equal(value.refresh_token, "rotated");
      if (++saves === 1) throw new Error("Vault is temporarily unavailable.");
    },
    clear: async () => {},
  };
  globalThis.fetch = async (input: any) => {
    if (String(input).endsWith("/info")) return Response.json({ service: "jarvis-remote", protocol: 1, public_url: saved.server_url });
    refreshes++;
    if (refreshes > 1) return Response.json({ detail: "Refresh replay detected." }, { status: 403 });
    return Response.json({ access_token: "restored-access", refresh_token: "rotated", device_id: saved.device_id, scopes: saved.scopes, expires_in: 300 });
  };
  await assert.rejects(client.initialize(), /temporarily unavailable/);
  assert.equal(await client.initialize(), true);
  assert.equal(client.authenticated, true);
  assert.equal(refreshes, 1);
  assert.equal(saves, 2);
});

test("native enrollment works without the secure-context randomUUID convenience API", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto")!;
  const random = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: { getRandomValues: random } });
  const persisted: any[] = [];
  const client = new Client();
  client.vault = { platform: "ios", load: async () => null, save: async (value: any) => { persisted.push(value); }, clear: async () => {} };
  let enrollments = 0;
  globalThis.fetch = async (input: any) => {
    if (String(input).endsWith("/info")) return Response.json({ service: "jarvis-remote", protocol: 1, public_url: saved.server_url });
    enrollments++;
    return Response.json({ kind: "companion", access_token: "synthetic-access", refresh_token: "synthetic-refresh", device_id: saved.device_id, scopes: saved.scopes, expires_in: 300 });
  };
  try {
    await client.enroll(saved.server_url, "synthetic-one-use-code", "Phone");
    assert.equal(enrollments, 1);
    assert.equal(persisted.length, 1);
    assert.match(persisted[0].session_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.equal(client.authenticated, true);
  } finally { Object.defineProperty(globalThis, "crypto", descriptor); }
});

test("overlapping enrollment submissions consume a one-use code only once", async () => {
  const client = new Client();
  let enrollments = 0;
  globalThis.fetch = async (input: any) => {
    if (String(input).endsWith("/info")) return Response.json({ service: "jarvis-remote", protocol: 1, public_url: saved.server_url });
    enrollments++;
    if (enrollments > 1) return Response.json({ detail: "Pairing code is invalid, expired or already used" }, { status: 403 });
    return Response.json({ kind: "companion", access_token: "synthetic-access", refresh_token: "synthetic-refresh", device_id: saved.device_id, scopes: saved.scopes, expires_in: 300 });
  };
  await Promise.all([client.enroll(saved.server_url, "synthetic-one-use-code", "Phone"), client.enroll(saved.server_url, "synthetic-one-use-code", "Phone")]);
  assert.equal(enrollments, 1);
  assert.equal(client.authenticated, true);
});

test("missing secure randomness fails before a pairing code can be consumed", async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto")!;
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
  let requests = 0;
  globalThis.fetch = async () => { requests++; throw new Error("Pairing must not be sent"); };
  try {
    await assert.rejects(new Client().enroll(saved.server_url, "synthetic-one-use-code", "Phone"), /Secure random generation is unavailable/);
    assert.equal(requests, 0);
  } finally { Object.defineProperty(globalThis, "crypto", descriptor); }
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
