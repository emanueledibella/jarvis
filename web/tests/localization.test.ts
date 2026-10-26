import assert from "node:assert/strict";
import fs from "node:fs";
import { afterEach, test } from "node:test";
import italian from "../src/locales/it.json" with { type: "json" };
import {
  getInterfaceLanguage,
  isInterfaceLanguage,
  setInterfaceLanguage,
  subscribeLanguage,
  t,
  translate,
  uiLocale,
  formatNumber,
} from "../src/localization.ts";

afterEach(() => setInterfaceLanguage("en"));

test("language selection updates labels and locale and can return to English", () => {
  let changes = 0;
  const unsubscribe = subscribeLanguage(() => changes++);
  setInterfaceLanguage("it");
  assert.equal(t("Settings"), "Impostazioni");
  assert.equal(t("Interface language"), "Lingua dell’interfaccia");
  assert.equal(uiLocale(), "it-IT");
  assert.equal(formatNumber(12345.5, 2), "12.345,50");
  assert.equal(t("  Save changes  "), "  Salva modifiche  ");
  setInterfaceLanguage("en");
  assert.equal(t("Settings"), "Settings");
  assert.equal(formatNumber(12345.5, 2), "12,345.50");
  assert.equal(changes, 2);
  unsubscribe();
});

test("catalog preserves interpolation and original technical data without interpreting it", () => {
  assert.equal(
    translate("{count} open task. Every action has a verifiable state.", "it", {
      count: 1,
    }),
    "1 attività aperta. Ogni azione ha uno stato verificabile.",
  );
  assert.equal(
    translate(
      "{count} open tasks. Every action has a verifiable state.",
      "it",
      { count: 2 },
    ),
    "2 attività aperte. Ogni azione ha uno stato verificabile.",
  );
  assert.equal(
    translate("Private note {value0}", "it", {
      value0: "<script>{value1}</script>",
    }),
    "Private note <script>{value1}</script>",
  );
  assert.equal(translate("provider_model_123", "it"), "provider_model_123");
  setInterfaceLanguage("it");
  assert.equal(
    t("Service unavailable (503)."),
    "Servizio non disponibile (503).",
  );
  assert.equal(
    t("Invalid fields: ui_language"),
    "Campi non validi: ui_language",
  );
  for (const value of ["it-IT", "../it", "fr", "constructor", undefined])
    assert.equal(isInterfaceLanguage(value), false);
  assert.equal(getInterfaceLanguage(), "it");
});

test("every literal UI message has Italian copy and the same placeholders", async () => {
  const { parseAst } = await import("rolldown/parseAst");
  const messages = italian as Record<string, string>;
  const seen = new Set<string>();
  const inspect = (expression: any) => {
    if (expression?.type === "Literal" && typeof expression.value === "string")
      seen.add(expression.value.trim());
    else if (expression?.type === "ConditionalExpression") {
      inspect(expression.consequent);
      inspect(expression.alternate);
    }
  };
  const walk = (node: any) => {
    if (!node || typeof node !== "object") return;
    if (node.type === "CallExpression" && node.callee?.name === "tr")
      inspect(node.arguments[0]);
    if (node.type === "CallExpression" && node.callee?.name === "notify")
      inspect(node.arguments[0]);
    for (const [key, value] of Object.entries(node))
      if (!["loc", "range"].includes(key)) {
        if (Array.isArray(value)) value.forEach(walk);
        else if (value && typeof value === "object") walk(value);
      }
  };
  const directory = new URL("../src/", import.meta.url);
  for (const name of fs
    .readdirSync(directory)
    .filter((name) => name.endsWith(".tsx"))) {
    walk(
      parseAst(fs.readFileSync(new URL(name, directory), "utf8"), {
        lang: "tsx",
      }),
    );
  }
  for (const key of seen)
    assert.ok(
      Object.hasOwn(messages, key),
      "Missing Italian UI message: " + key,
    );
  for (const [key, value] of Object.entries(messages)) {
    assert.ok(value.trim(), "Empty Italian message: " + key);
    const placeholders = (s: string) =>
      [...s.matchAll(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g)].map((m) => m[1]).sort();
    assert.deepEqual(
      placeholders(value),
      placeholders(key),
      "Translation changes placeholders: " + key,
    );
  }
  assert.ok(
    seen.size > 450,
    "The coverage check must inspect the full application.",
  );
});
