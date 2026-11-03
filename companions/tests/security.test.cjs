const { test } = require("node:test");
const assert = require("node:assert/strict");
const { trustedFrame, safeExternal, validateCredentials } = require("../desktop/security.cjs");
test("IPC trusts only the bundled app, external navigation only credential-free HTTPS", () => {
  assert.equal(trustedFrame("jarvis://app/index.html"), true);
  for (const url of ["https://app/", "jarvis://evil/", "file:///tmp/app", "jarvis://user@app/index.html", "javascript:alert(1)"]) assert.equal(trustedFrame(url), false);
  assert.equal(safeExternal("https://example.com/oauth?state=fixture"), true);
  for (const url of ["file:///secret", "javascript:alert(1)", "http://example.com", "https://user:secret@example.com"]) assert.equal(safeExternal(url), false);
});
test("vault records bind credentials to a TLS origin and explicit device/session", () => {
  const value = { server_url: "https://jarvis.example", device_id: "12345678-1234-1234-1234-123456789abc", session_id: "12345678-1234-1234-1234-123456789abc", refresh_token: "synthetic" };
  assert.equal(validateCredentials(value), value);
  assert.throws(() => validateCredentials({ ...value, server_url: "https://evil.example/path" }));
  assert.throws(() => validateCredentials({ ...value, server_url: "http://jarvis.example" }));
});
