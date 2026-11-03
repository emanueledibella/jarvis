"use strict";
function trustedFrame(value) {
  try { const url = new URL(value); return url.protocol === "jarvis:" && url.hostname === "app" && !url.username && !url.password; } catch { return false; }
}
function safeExternal(value) {
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password; } catch { return false; }
}
function validateCredentials(value) {
  if (!value || typeof value !== "object" || JSON.stringify(value).length > 8192) throw new Error("Invalid credentials.");
  const url = new URL(value.server_url);
  if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("Use an HTTPS server origin.");
  if (!/^[0-9a-f-]{36}$/i.test(value.device_id) || !/^[0-9a-f-]{36}$/i.test(value.session_id) || typeof value.refresh_token !== "string" || value.refresh_token.length > 256) throw new Error("Invalid device credentials.");
  return value;
}
module.exports = { trustedFrame, safeExternal, validateCredentials };
