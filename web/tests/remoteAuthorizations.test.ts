import assert from "node:assert/strict";
import { test } from "node:test";
import { validAuthorizations } from "../src/authorizationPolicy.ts";

test("OAuth links preserve state and PKCE query values for an explicit browser click", () => {
  const value = { name: "second_brain", url: "https://memory.example/authorize?state=fixture%2Bnonce&code_challenge=fixture", expires_in: 180 };
  assert.deepEqual(validAuthorizations([value]), [value]);
  assert.equal(new URL(validAuthorizations([value])[0].url).searchParams.get("state"), "fixture+nonce");
});

test("expired, oversized, credential-bearing and non-HTTPS consent links are not displayed", () => {
  const value = { name: "second_brain", url: "https://memory.example/authorize", expires_in: 60 };
  const invalid = [null, {}, { ...value, expires_in: 0 }, { ...value, expires_in: -1 }, { ...value, expires_in: Infinity }, { ...value, expires_in: 181 },
    { ...value, url: "javascript:alert(1)" }, { ...value, url: "http://memory.example" }, { ...value, url: "https://user:secret@memory.example" },
    { ...value, url: "https://memory.example/" + "x".repeat(16_384) }, { ...value, name: "x".repeat(129) }];
  assert.deepEqual(validAuthorizations(invalid), []);
  assert.deepEqual(validAuthorizations({ authorizations: [value] }), []);
  assert.equal(validAuthorizations(Array(30).fill(value)).length, 10);
});
