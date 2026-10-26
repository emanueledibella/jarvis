import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { fileURLToPath } from "node:url";
import { after, before, test } from "node:test";
import { createServer } from "vite";
import React from "react";
import italian from "../src/locales/it.json" with { type: "json" };
import { renderToStaticMarkup } from "react-dom/server";

let vite: any, locale: any, controls: any;
const fixtureToken = "interface-language-test-fixture-no-secret";
let savedLanguage = "en",
  rejectSave = false;
const payloads: any[] = [];
const storage = new Map<string, string>();
const originalFetch = globalThis.fetch;

before(async () => {
  Object.assign(globalThis, {
    location: new URL("http://127.0.0.1:8765/"),
    window: { __JARVIS_TOKEN__: fixtureToken },
    history: { replaceState() {} },
    sessionStorage: { removeItem() {} },
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    },
    document: { documentElement: { lang: "en" } },
  });
  globalThis.fetch = async (input, options) => {
    const url = new URL(String(input), "http://127.0.0.1:8765");
    if (url.pathname === "/health") {
      assert.equal(new Headers(options?.headers).get("Authorization"), null);
      const proof = createHmac("sha256", fixtureToken)
        .update("jarvis-health:8765:" + url.searchParams.get("challenge"))
        .digest("hex");
      return Response.json({ proof });
    }
    assert.equal(
      url.pathname,
      "/api/settings",
      "Locale selection must not start models, audio or other actions",
    );
    if (options?.method === "PATCH") {
      const body = JSON.parse(String(options.body));
      payloads.push(body);
      if (rejectSave)
        return Response.json(
          { detail: "fixture update failed" },
          { status: 503 },
        );
      assert.deepEqual(Object.keys(body), ["ui_language"]);
      savedLanguage = body.ui_language;
    }
    return Response.json({
      values: {
        ui_language: savedLanguage,
        language: "it-IT",
        response_language: "auto",
      },
      locked: [],
    });
  };
  vite = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    configFile: false,
    server: { middlewareMode: true, watch: null, ws: false },
    optimizeDeps: { noDiscovery: true, include: [] },
    esbuild: { jsx: "automatic" },
  });
  locale = await vite.ssrLoadModule("/src/localization.ts");
  controls = await vite.ssrLoadModule("/src/i18n.ts");
});

after(async () => {
  globalThis.fetch = originalFetch;
  await vite?.close();
});

test("actual dashboard, settings tabs, tasks, routines and memory render in both languages", async () => {
  const { default: App } = await vite.ssrLoadModule("/src/App.tsx");
  const { default: Settings } = await vite.ssrLoadModule("/src/Settings.tsx");
  const { Tasks, Routines } = await vite.ssrLoadModule("/src/Activity.tsx");
  const { Memory, Integrations } = await vite.ssrLoadModule("/src/Memory.tsx");
  const { Badge, Orb, stateLabels, profileLabels, ErrorMessage } =
    await vite.ssrLoadModule("/src/components.tsx");
  const props = {
    tasks: [],
    schedules: [],
    approvals: [],
    refresh() {},
    notify() {},
    onSaved() {},
    openSettings() {},
  };
  const render = (type: any, props = {}) =>
    renderToStaticMarkup(React.createElement(type, props));
  locale.setInterfaceLanguage("it");
  const dashboard = render(App);
  for (const label of [
    "Il tuo centro di comando",
    "Panoramica",
    "Conversazione",
    "Attività",
    "Routine",
    "Impostazioni",
    "La tua giornata",
  ])
    assert.ok(
      dashboard.toLowerCase().includes(label.toLowerCase()),
      "Missing dashboard label: " + label,
    );
  for (const tab of [
    "interface",
    "models",
    "voice",
    "memory",
    "productivity",
    "security",
    "phone",
  ]) {
    const html = render(Settings, { ...props, initial: tab });
    assert.ok(
      html.includes("Impostazioni") && html.includes("Salva modifiche"),
    );
    assert.ok(!html.includes("YOUR ASSISTANT, YOUR CHOICES"));
    if (tab === "interface")
      assert.ok(
        html.includes("Lingua dell’interfaccia") &&
          html.includes('value="it" selected=""'),
      );
  }
  assert.ok(render(Tasks, props).includes("DAL PIANO AL RISULTATO"));
  assert.ok(render(Routines, props).includes("Routine e promemoria"));
  assert.ok(render(Memory, props).includes("La tua memoria"));
  assert.ok(render(Integrations, props).includes("Connessioni"));
  assert.ok(render(Orb, { state: "armed" }).includes("Sono qui."));
  assert.ok(
    render(Badge, { state: "waiting_user" }).includes("Serve una decisione"),
  );
  for (const value of [
    ...Object.values(stateLabels),
    ...Object.values(profileLabels),
  ] as string[])
    assert.ok(
      Object.hasOwn(italian, value),
      "Missing state/profile translation: " + value,
    );
  const userTitle = "Settings <project> stays unchanged";
  const task = {
    id: "fixture",
    title: userTitle,
    state: "running",
    created_at: "2026-01-01T12:00:00Z",
    profile: "cloud",
  };
  assert.ok(
    render(Tasks, { ...props, tasks: [task] }).includes(
      "Settings &lt;project&gt; stays unchanged",
    ),
  );
  const diagnostic = render(ErrorMessage, {
    message: "provider fixture <script>alert(1)</script>",
  });
  assert.ok(
    diagnostic.includes("Dettagli tecnici") &&
      diagnostic.includes("&lt;script&gt;") &&
      !diagnostic.includes("<script>"),
  );
  locale.setInterfaceLanguage("en");
  assert.ok(render(App).includes("Your command center"));
  assert.ok(render(Settings, props).includes("Interface language"));
  assert.ok(render(Orb, { state: "armed" }).includes("I am here."));
});

test("selection changes immediately, persists only ui_language, and rolls back on failure", async () => {
  locale.setInterfaceLanguage("en");
  const pending = controls.saveInterfaceLanguage("it");
  assert.equal(locale.getInterfaceLanguage(), "it");
  await pending;
  assert.equal(savedLanguage, "it");
  assert.equal(storage.get("jarvis-ui-language"), "it");
  assert.equal(document.documentElement.lang, "it");
  assert.deepEqual(payloads.at(-1), { ui_language: "it" });
  locale.setInterfaceLanguage("en");
  await controls.syncInterfaceLanguage();
  assert.equal(
    locale.getInterfaceLanguage(),
    "it",
    "A reopened dashboard restores the server preference",
  );
  await controls.saveInterfaceLanguage("en");
  rejectSave = true;
  await assert.rejects(controls.saveInterfaceLanguage("it"));
  assert.equal(
    locale.getInterfaceLanguage(),
    "en",
    "A failed save must restore the previous language",
  );
  assert.equal(savedLanguage, "en");
  assert.equal(storage.get("jarvis-ui-language"), "en");
  rejectSave = false;
});
