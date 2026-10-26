import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { authenticatedFetch } from "../src/serviceTrust.ts";

test("a local impostor never receives the bearer token", async () => {
  const seen: RequestInit[] = [];
  const fake = async (_path: unknown, options: RequestInit) => {
    seen.push(options);
    return Response.json({ proof: "0".repeat(64) });
  };
  await assert.rejects(
    authenticatedFetch(
      "browser-token-fixture",
      8765,
      "/api/status",
      {},
      fake as typeof fetch,
    ),
    /verification/,
  );
  assert.equal(seen.length, 1);
  assert.equal(new Headers(seen[0].headers).get("Authorization"), null);
  assert.equal(seen[0].redirect, "error");
});

test("an authenticated service receives the credential only after proving its key", async () => {
  const token = "browser-token-fixture";
  const seen: RequestInit[] = [];
  const server = async (path: string, options: RequestInit) => {
    seen.push(options);
    if (path.startsWith("/health")) {
      const nonce = new URL(path, "http://127.0.0.1").searchParams.get(
        "challenge",
      );
      return Response.json({
        proof: createHmac("sha256", token)
          .update(`jarvis-health:8765:${nonce}`)
          .digest("hex"),
      });
    }
    return Response.json({ state: "ready" });
  };
  const result = await authenticatedFetch(
    token,
    8765,
    "/api/status",
    {},
    server as typeof fetch,
  );
  assert.equal(result.status, 200);
  assert.equal(new Headers(seen[0].headers).get("Authorization"), null);
  assert.equal(
    new Headers(seen[1].headers).get("Authorization"),
    "Bearer " + token,
  );
  assert.equal(seen[1].redirect, "error");
});

test("verification rejects oversized responses before authenticating", async () => {
  let calls = 0;
  const fake = async () => {
    calls++;
    return new Response("x".repeat(5000));
  };
  await assert.rejects(
    authenticatedFetch(
      "browser-token-fixture",
      8765,
      "/api/status",
      {},
      fake as typeof fetch,
    ),
    /verification/,
  );
  assert.equal(calls, 1);
});
