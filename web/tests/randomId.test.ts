import assert from "node:assert/strict";
import { test } from "node:test";
import { randomId } from "../src/randomId.ts";

test("WebView IDs use 16 secure bytes and preserve UUID v4 version and variant", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto")!;
  let calls = 0;
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: {
    getRandomValues(bytes: Uint8Array) {
      assert.ok(bytes instanceof Uint8Array);
      assert.equal(bytes.length, 16);
      calls++;
      return bytes.fill(255);
    },
  } });
  try {
    assert.equal(randomId(), "ffffffff-ffff-4fff-bfff-ffffffffffff");
    assert.equal(calls, 1);
  } finally { Object.defineProperty(globalThis, "crypto", descriptor); }
});

test("WebView IDs fail closed when the cryptographic RNG is unavailable", () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto")!;
  Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
  try { assert.throws(() => randomId(), /Secure random generation is unavailable/); }
  finally { Object.defineProperty(globalThis, "crypto", descriptor); }
});
