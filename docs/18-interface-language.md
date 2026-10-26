# Interface language

Open **Settings → Interface → Interface language** and choose **English** or **Italian**. In Italian the path is **Impostazioni → Interfaccia → Lingua dell’interfaccia**. The selection applies immediately and saves automatically; the main Save changes button is not required for this preference.

English remains the default for existing installations. The service stores `ui_language` in private settings. Reopening the app restores it, and settings events synchronize other open dashboards. A local browser preference prevents an unnecessary English flash while the authenticated service loads. If saving fails, the UI restores the previous language. Changing this field preserves other unsaved form edits.

## Independent language controls

| Setting | Purpose | Default |
| --- | --- | --- |
| `ui_language` / `JARVIS_UI_LANGUAGE` | All dashboard pages, labels, help text, status messages, locale formats and native Mac menus | `en` |
| `language` / `JARVIS_LANGUAGE` | Local wake/Apple recognition locale | `it-IT` |
| `response_language` / `JARVIS_RESPONSE_LANGUAGE` | Assistant response language; `auto` follows the user | `auto` |

Interface selection never changes recognition or response language and never starts a model, microphone, voice test or phone call. It does not interrupt an active voice session or invalidate weather/calendar caches. User conversations, memory content, task titles, code, identifiers and provider diagnostics retain their original text. Unknown diagnostic details appear behind a translated disclosure rather than being sent to a translation service.

## Environment configuration

```dotenv
# Uncomment only when the environment should control and lock the preference.
# JARVIS_UI_LANGUAGE=it
```

Only `en` and `it` are accepted. Environment precedence matches other settings; env-managed fields are disabled in the GUI. No credentials or additional services are required.

## Maintenance and verification

Application-owned strings use English source keys and the shared Italian catalog in `web/src/locales/it.json`. React subscribes to locale changes, while native Mac menus load the same catalog bundled as `Interface.it.json`. Do not translate user-provided content, machine-readable values, API payload keys or model/tool IDs. Keep interpolation placeholders unchanged.

Frontend tests cover real rendered pages in both languages, catalog completeness, status labels, numeric formatting, interpolation, immediate save, persistence and rollback. Backend tests cover validation, environment precedence, native synchronization and unchanged voice/cache settings. Native tests cover the shared catalog and English/Italian menu selection. These checks use synthetic data without paid model or carrier calls.

The [native CI matrix](https://github.com/emanueledibella/jarvis/actions/runs/40289020296) and [security gate](https://github.com/emanueledibella/jarvis/actions/runs/40289020314) passed for the released source. There are 119 collected Python tests (platform-specific skips), eight frontend tests and 40 Swift scenarios. Real-browser checks confirmed instant switching in both directions, persistence after reopening, unchanged unsaved model fields and the Italian layout. The [portable preview](https://github.com/emanueledibella/jarvis/releases/tag/v0.1.0-portable-preview.4) includes the same interface on Windows and Linux.
