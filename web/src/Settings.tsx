import React, { useEffect, useState } from "react";
import {
  Check,
  Cloud,
  Computer,
  Headphones,
  KeyRound,
  LoaderCircle,
  Phone,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Volume2,
} from "lucide-react";
import { api, patch, post, type Json } from "./api";
import {
  Badge,
  Field,
  SectionTitle,
  Toggle,
  profileLabels,
} from "./components";

type Props = {
  notify: (text: string, error?: boolean) => void;
  onSaved: () => void;
  initial?: string;
};
export default function Settings({
  notify,
  onSaved,
  initial = "models",
}: Props) {
  const [tab, setTab] = useState(initial),
    [values, setValues] = useState<Json>({}),
    [changes, setChanges] = useState<Json>({}),
    [locked, setLocked] = useState<string[]>([]),
    [models, setModels] = useState<Json>({ local: [] }),
    [saving, setSaving] = useState(false),
    [testing, setTesting] = useState(""),
    [authorized, setAuthorized] = useState(false),
    [calls, setCalls] = useState<Json[]>([]);
  const load = () =>
    api("/settings").then((data) => {
      setValues(data.values);
      setLocked(data.locked);
      setChanges({});
    });
  useEffect(() => {
    load().catch((e) => notify(e.message, true));
    api("/models")
      .then(setModels)
      .catch(() => {});
    api("/calls")
      .then(setCalls)
      .catch(() => {});
  }, []);
  const change = (key: string, value: any) => {
    setValues((v) => ({ ...v, [key]: value }));
    setChanges((v) => ({ ...v, [key]: value }));
  };
  const field = (
    key: string,
    label: string,
    type = "text",
    help?: string,
    options?: { value: string; label: string }[],
  ) => (
    <Field
      key={key}
      label={label}
      value={
        Array.isArray(values[key])
          ? JSON.stringify(values[key], null, 2)
          : values[key]
      }
      type={type}
      onChange={(v) => change(key, v)}
      help={help}
      disabled={locked.includes(key)}
      placeholder={
        type === "password" && values[key + "_configured"]
          ? "Configurata · lascia vuoto per conservarla"
          : undefined
      }
      options={options}
    />
  );
  const toggle = (key: string, label: string, help?: string) => (
    <Toggle
      key={key}
      label={label}
      checked={Boolean(values[key])}
      help={help}
      disabled={locked.includes(key)}
      onChange={(v) => change(key, v)}
    />
  );
  async function save() {
    setSaving(true);
    try {
      await patch("/settings", changes);
      await load();
      notify("Impostazioni salvate.");
      onSaved();
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setSaving(false);
    }
  }
  async function test(profile: string) {
    setTesting(profile);
    try {
      const result = await post("/models/test", { profile });
      notify(
        result.tool_calling
          ? "Connessione e tool calling verificati."
          : "Il modello risponde ma non ha prodotto la chiamata tool richiesta.",
        !result.tool_calling,
      );
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setTesting("");
    }
  }
  async function native(action: string) {
    try {
      const result = await post("/voice/control", { action });
      const states: Record<string, string> = {
        requires_approval:
          "Conferma l’avvio al login nelle impostazioni di macOS.",
        denied:
          "Permesso non concesso. Puoi cambiarlo nelle impostazioni di macOS.",
        not_registered: "L’avvio al login non risulta attivo.",
        enabled: "Avvio al login attivo.",
        disabled: "Avvio al login disattivato.",
      };
      notify(
        result.error || states[result.state] || "Operazione completata.",
        Boolean(result.error) ||
          ["denied", "not_registered"].includes(result.state),
      );
      onSaved();
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  useEffect(() => {
    if (tab !== "phone") return;
    const timer = setInterval(
      () =>
        api("/calls")
          .then(setCalls)
          .catch(() => {}),
      5000,
    );
    return () => clearInterval(timer);
  }, [tab]);
  const tabs = [
    ["models", "Modelli"],
    ["voice", "Voce e presenza"],
    ["memory", "Memoria"],
    ["productivity", "Produttività"],
    ["security", "Autonomia e privacy"],
    ["phone", "Telefonia"],
  ];
  return (
    <div className="page settings-page">
      <SectionTitle
        eyebrow="IL TUO ASSISTENTE, LE TUE SCELTE"
        title="Impostazioni"
        description="Modelli, connessioni e confini. Tutto sotto il tuo controllo."
        action={
          <button
            className="btn primary"
            onClick={save}
            disabled={saving || !Object.keys(changes).length}
          >
            {saving ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Save size={15} />
            )}
            Salva modifiche
          </button>
        }
      />
      <div
        className="settings-tabs"
        role="tablist"
        aria-label="Sezioni impostazioni"
      >
        {tabs.map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            key={key}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {!!locked.length && (
        <div className="info-line">
          <KeyRound size={14} />I campi con il lucchetto sono imposti
          dall’ambiente. Modifica il file env e riavvia il servizio.
        </div>
      )}
      {tab === "models" && (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="card-heading">
              <Computer size={19} />
              <div>
                <h2>Intelligenza locale</h2>
                <p>Il modello gira sul tuo Mac.</p>
              </div>
              <Badge
                state={
                  models.local_state === "connected"
                    ? "connected"
                    : "not_connected"
                }
              />
            </div>
            {field("local_provider", "Runtime", "text", undefined, [
              { value: "ollama", label: "Ollama" },
              {
                value: "openai_compatible",
                label: "LM Studio / compatibile OpenAI",
              },
            ])}
            {field(
              "local_base_url",
              "Endpoint locale",
              "url",
              "Ollama: http://127.0.0.1:11434 · LM Studio: http://127.0.0.1:1234/v1",
            )}
            <label className="field">
              <span>
                Modello locale{" "}
                {locked.includes("local_model") && <KeyRound size={11} />}
              </span>
              <input
                list="local-models"
                value={values.local_model || ""}
                onChange={(e) => change("local_model", e.target.value)}
                disabled={locked.includes("local_model")}
                placeholder="Seleziona un modello installato"
              />
              <datalist id="local-models">
                {models.local?.map((m: Json) => (
                  <option key={m.id} value={m.id} />
                ))}
              </datalist>
              <small>
                {models.local?.length
                  ? `${models.local.length} modelli rilevati sul runtime locale.`
                  : "Avvia il runtime e rileva i modelli."}
              </small>
            </label>
            {field(
              "local_api_key",
              "Token del runtime, se richiesto",
              "password",
            )}
            <div className="button-row">
              <button
                className="btn"
                onClick={() =>
                  api("/models")
                    .then(setModels)
                    .catch((e) => notify(e.message, true))
                }
              >
                <RefreshCw size={14} />
                Rileva modelli
              </button>
              <button
                className="btn"
                disabled={!!testing}
                onClick={() => test("local_connected")}
              >
                {testing === "local_connected" ? (
                  <LoaderCircle size={14} className="spin" />
                ) : (
                  <ShieldCheck size={14} />
                )}
                Prova tool calling
              </button>
            </div>
            <small className="hint">
              Salva le modifiche prima della prova. Non vengono scaricati
              modelli automaticamente.
            </small>
          </section>
          <section className="settings-card">
            <div className="card-heading">
              <Cloud size={19} />
              <div>
                <h2>Intelligenza cloud</h2>
                <p>Per i lavori che richiedono un modello remoto.</p>
              </div>
            </div>
            {field("cloud_provider", "Provider", "text", undefined, [
              { value: "openai", label: "OpenAI · Responses API" },
              { value: "anthropic", label: "Anthropic" },
              {
                value: "openai_compatible",
                label: "Altro provider compatibile OpenAI",
              },
            ])}
            {field(
              "cloud_model",
              "ID del modello",
              "text",
              "Usa l’ID esatto disponibile nel tuo account.",
            )}
            {field(
              "cloud_api_key",
              "Chiave API",
              "password",
              "Conservata nella configurazione privata; puoi usare anche un riferimento keychain:account.",
            )}
            {field(
              "cloud_base_url",
              "Endpoint personalizzato, opzionale",
              "url",
            )}
            <button
              className="btn"
              disabled={!!testing}
              onClick={() => test("cloud")}
            >
              {testing === "cloud" ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <ShieldCheck size={14} />
              )}
              Prova connessione e tool
            </button>
            <small className="hint">
              La prova esegue una breve richiesta reale al provider.
            </small>
          </section>
          <section className="settings-card full">
            <h2>Profilo predefinito</h2>
            <div className="profile-options">
              {Object.entries(profileLabels).map(([key, label]) => (
                <button
                  key={key}
                  disabled={locked.includes("profile")}
                  onClick={() => change("profile", key)}
                  className={values.profile === key ? "selected" : ""}
                >
                  <span>{label}</span>
                  <small>
                    {key === "local_strict"
                      ? "Nessun tool remoto né fallback cloud"
                      : key === "local_connected"
                        ? "LLM locale, servizi connessi abilitati"
                        : key === "cloud"
                          ? "Modello cloud selezionato"
                          : "Cloud se configurato, altrimenti locale"}
                  </small>
                </button>
              ))}
            </div>
            <div className="form-grid">
              {field("max_output_tokens", "Limite token di risposta", "number")}
              {field("max_agent_steps", "Limite passi dell’agente", "number")}
              {field(
                "task_timeout_seconds",
                "Durata massima del task, secondi",
                "number",
              )}
              {field(
                "model_request_timeout_seconds",
                "Timeout del modello, secondi",
                "number",
              )}
            </div>
          </section>
        </div>
      )}
      {tab === "voice" && (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="card-heading">
              <Headphones size={19} />
              <div>
                <h2>Una voce sempre vicina</h2>
                <p>Microfono e riconoscimento sono gestiti dall’app macOS.</p>
              </div>
            </div>
            {toggle("voice_enabled", "Abilita il percorso vocale")}
            {toggle("wake_enabled", "Attivazione con la voce")}
            {field(
              "wake_phrase",
              "Parola di attivazione",
              "text",
              "La ricerca avviene nella trascrizione on-device, con confini di parola.",
            )}
            {field(
              "language",
              "Lingua",
              "text",
              "Esempio: it-IT. La lingua deve supportare il riconoscimento locale sul Mac.",
            )}
            {field(
              "tts_voice",
              "Voce di sistema, identificativo opzionale",
              "text",
              "Lascia vuoto per la voce italiana di sistema.",
            )}
            <div className="button-row">
              <button className="btn primary" onClick={() => native("enable")}>
                <Headphones size={15} />
                Abilita voce e permessi
              </button>
              <button className="btn" onClick={() => native("listen")}>
                Prova ascolto
              </button>
            </div>
          </section>
          <section className="settings-card">
            <h2>Ritmo della conversazione</h2>
            {field(
              "followup_seconds",
              "Finestra per continuare, secondi",
              "number",
            )}
            {field(
              "end_of_turn_ms",
              "Pausa di fine turno, millisecondi",
              "number",
            )}
            {field(
              "listen_timeout_seconds",
              "Durata massima di un comando, secondi",
              "number",
            )}
            {toggle(
              "voice_on_lock_screen",
              "Consenti voce con schermo bloccato",
              "Disattivata per impostazione predefinita.",
            )}
            <div className="info-box">
              <strong>⌘ ⇧ J</strong>
              <p>
                Scorciatoia globale per aprire un turno. Chiudere la finestra
                mantiene Jarvis nella barra dei menu.
              </p>
            </div>
            <div className="button-row">
              <button
                className="btn"
                onClick={() => native("autostart_enable")}
              >
                Avvia al login
              </button>
              <button
                className="btn ghost"
                onClick={() => native("autostart_disable")}
              >
                Disabilita avvio
              </button>
            </div>
            <small className="hint">
              Il Mac deve essere sveglio. Stop e spegnimento sospendono
              l’assistente.
            </small>
          </section>
        </div>
      )}
      {tab === "memory" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Il tuo Second Brain</h2>
            {field(
              "second_brain_url",
              "Endpoint MCP",
              "url",
              "Usa l’installazione canonica della tua memoria.",
            )}
            {field("second_brain_auth", "Autenticazione", "text", undefined, [
              { value: "bearer", label: "Token Bearer" },
              { value: "oauth", label: "OAuth con consenso nel browser" },
              {
                value: "none",
                label: "Nessuna · solo server esplicitamente protetto altrove",
              },
            ])}
            {field("second_brain_token", "Token dedicato", "password")}
            {toggle(
              "second_brain_allow_corrections",
              "Abilita correzioni e ritrattazioni",
              "Richiede un consenso OAuth separato con memory:write. Le modifiche restano soggette ad approvazione.",
            )}
            {field(
              "memory_capture",
              "Acquisizione dei ricordi",
              "text",
              undefined,
              [
                {
                  value: "explicit_only",
                  label: "Soltanto quando chiedo di ricordare",
                },
                {
                  value: "explicit_facts",
                  label: "Fatti espliciti pertinenti nelle conversazioni",
                },
                { value: "off", label: "Nessuna nuova memoria" },
              ],
            )}
            {field(
              "memory_recall_token_budget",
              "Budget di contesto per il recupero",
              "number",
            )}
            <button
              className="btn"
              onClick={() =>
                post("/integrations/second_brain/connect")
                  .then(() =>
                    notify(
                      "Connessione avviata. Completa il consenso nel browser se richiesto.",
                    ),
                  )
                  .catch((e) => notify(e.message, true))
              }
            >
              Connetti Second Brain
            </button>
          </section>
          <section className="settings-card">
            <h2>Fonti e continuità</h2>
            <p className="body-copy">
              I ricordi mantengono fonte, revisione e citazioni. Il salvataggio
              è asincrono: una fonte in coda non è ancora un ricordo
              ricercabile.
            </p>
            <p className="body-copy">
              La sessione privata esclude nuova memoria, contenuti dei
              checkpoint e messaggi persistenti. La ritrattazione di un ricordo
              conserva gli originali nel Second Brain.
            </p>
            <div className="info-box">
              Non riutilizzare credenziali di altre applicazioni. Configura una
              connessione dedicata con i soli privilegi necessari.
            </div>
          </section>
        </div>
      )}
      {tab === "productivity" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Agenda</h2>
            {field("calendar_provider", "Calendario", "text", undefined, [
              { value: "disabled", label: "Non collegato" },
              { value: "apple", label: "Apple Calendar · nativo Mac" },
              { value: "ics", label: "Feed ICS · sola lettura" },
              { value: "google", label: "Google Calendar" },
              { value: "microsoft", label: "Microsoft 365 / Outlook" },
            ])}
            {values.calendar_provider === "apple" && (
              <button
                className="btn"
                onClick={() => native("calendar_authorize")}
              >
                Autorizza il calendario del Mac
              </button>
            )}
            {values.calendar_provider === "ics" &&
              field("calendar_ics_url", "URL del feed ICS", "url")}
            {["google", "microsoft"].includes(values.calendar_provider) && (
              <>
                {field("calendar_client_id", "OAuth client ID")}
                {field(
                  "calendar_client_secret",
                  "OAuth client secret, se richiesto",
                  "password",
                )}
                {field(
                  "calendar_refresh_token",
                  "Refresh token",
                  "password",
                  "Il rinnovo avviene automaticamente quando configurato.",
                )}
                {field(
                  "calendar_access_token",
                  "Access token, alternativa temporanea",
                  "password",
                )}
                {values.calendar_provider === "microsoft" &&
                  field("calendar_tenant_id", "Tenant Microsoft")}
              </>
            )}
            <small className="hint">
              Salva il provider prima di autorizzare il calendario.
            </small>
          </section>
          <section className="settings-card">
            <h2>Meteo e ricerca</h2>
            {field(
              "weather_location",
              "Località meteo",
              "text",
              "Una città scelta da te; nessuna geolocalizzazione automatica.",
            )}
            {field(
              "weather_refresh_minutes",
              "Aggiornamento meteo, minuti",
              "number",
            )}
            {field("search_provider", "Motore di ricerca", "text", undefined, [
              {
                value: "duckduckgo",
                label: "DuckDuckGo pubblico · senza chiave, best effort",
              },
              { value: "brave", label: "Brave Search API" },
              { value: "tavily", label: "Tavily Search API" },
            ])}
            {field(
              "search_api_key",
              "Chiave del motore di ricerca",
              "password",
            )}
            <small className="hint">
              Il meteo usa Open-Meteo con attribuzione. La ricerca senza chiave
              può essere limitata dal servizio.
            </small>
          </section>
        </div>
      )}
      {tab === "security" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Workspace e comandi</h2>
            {field(
              "workspace_roots",
              "Cartelle autorizzate, array JSON",
              "textarea",
              'Esempio: ["/absolute/path/progetti/app"]. I tool file escludono credenziali e symlink esterni.',
            )}
            {field(
              "command_execution",
              "Esecuzione di comandi",
              "text",
              undefined,
              [
                { value: "disabled", label: "Disabilitata" },
                { value: "approval", label: "Host · proposta da approvare" },
                { value: "sandbox", label: "Sandbox macOS · senza rete" },
              ],
            )}
            {field(
              "command_timeout_seconds",
              "Timeout del comando, secondi",
              "number",
            )}
            <p className="body-copy">
              Una conferma sui comandi autorizza quell’azione concreta. Il
              motore non eredita le chiavi dei provider nel processo di coding.
            </p>
          </section>
          <section className="settings-card">
            <h2>Privacy e limiti</h2>
            {field(
              "transcript_retention_days",
              "Conservazione messaggi, giorni",
              "number",
            )}
            {field(
              "operation_log_retention_days",
              "Conservazione eventi, giorni",
              "number",
            )}
            {field("monthly_budget_usd", "Soglia mensile, USD", "number")}
            {field(
              "model_input_usd_per_million",
              "Costo input per milione token, USD",
              "number",
            )}
            {field(
              "model_output_usd_per_million",
              "Costo output per milione token, USD",
              "number",
            )}
            <small className="hint">
              Per il cloud le tariffe input e output sono obbligatorie. Ogni
              richiesta prenota una stima prima dell’invio; il consuntivo
              dell’operatore resta il riferimento.
            </small>
          </section>
        </div>
      )}
      {tab === "phone" && (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="card-heading">
              <Phone size={19} />
              <div>
                <h2>Jarvis al telefono</h2>
                <p>Twilio Media Streams con dialogo bidirezionale.</p>
              </div>
            </div>
            {toggle(
              "telephony_enabled",
              "Abilita la telefonia",
              "Richiede operatore, tunnel HTTPS/WSS e credito.",
            )}
            {field("telephony_account_id", "Account SID Twilio")}
            {field("telephony_auth_token", "Auth token Twilio", "password")}
            {field(
              "telephony_public_base_url",
              "URL pubblico del proxy telefonico",
              "url",
              "Esporre soltanto /telephony, non l’intera API locale.",
            )}
            {field("telephony_from_number", "Numero chiamante, E.164")}
            {field("owner_phone_number", "Il tuo numero verificato, E.164")}
            {field(
              "phone_pin",
              "PIN personale, 4–8 cifre",
              "password",
              "Richiesto prima di parlare di dati privati. Non viene passato al modello.",
            )}
          </section>
          <section className="settings-card">
            <h2>Audio e limiti delle chiamate</h2>
            {field(
              "phone_stt_provider",
              "Riconoscimento telefonico",
              "text",
              undefined,
              [
                { value: "openai", label: "OpenAI · audio cloud" },
                {
                  value: "faster_whisper",
                  label: "faster-whisper locale · extra voice richiesto",
                },
              ],
            )}
            {field(
              "phone_api_key",
              "Chiave OpenAI per audio, se usata",
              "password",
              "Distinta dal provider del ragionamento. Senza chiave il TTS usa la voce di sistema.",
            )}
            {field(
              "phone_max_call_seconds",
              "Durata massima, secondi",
              "number",
            )}
            {field(
              "phone_local_tts_voice",
              "Voce Mac per il telefono, nome opzionale",
              "text",
              "Esempio: Alice, se installata. È distinta dall’ID vocale del desktop.",
            )}
            {field(
              "phone_daily_budget_usd",
              "Riserva massima giornaliera, USD",
              "number",
            )}
            {field(
              "phone_minute_rate_usd",
              "Tariffa prudenziale, USD/min",
              "number",
            )}
            {field(
              "quiet_hours",
              "Orari silenziosi",
              "text",
              "Formato 22:00-08:00. Nessuna chiamata proattiva fuori policy.",
            )}
            <div className="info-box">
              Riserva per una chiamata in uscita:{" "}
              {(
                Math.ceil((values.phone_max_call_seconds || 0) / 60) *
                (values.phone_minute_rate_usd || 0)
              ).toFixed(2)}{" "}
              USD. Verifica le tariffe reali e salva le impostazioni.
            </div>
            <Toggle
              checked={authorized}
              onChange={setAuthorized}
              label="Autorizzo una chiamata di prova al mio numero"
            />
            <button
              className="btn"
              disabled={!authorized}
              onClick={async () => {
                setAuthorized(false);
                try {
                  await post("/calls/owner", {
                    authorized: true,
                    request_id: crypto.randomUUID(),
                    reason: "Chiamata di prova richiesta dal proprietario",
                  });
                  notify("Richiesta inviata all’operatore.");
                  setCalls(await api("/calls"));
                } catch (e: any) {
                  notify(e.message, true);
                }
              }}
            >
              <Phone size={14} />
              Avvia chiamata di prova
            </button>
          </section>
          {!!calls.length && (
            <section className="settings-card full">
              <h2>Chiamate recenti</h2>
              {calls.map((c) => (
                <React.Fragment key={c.id}>
                  <div className="list-row">
                    <div>
                      <strong>
                        {c.direction === "outbound"
                          ? "Chiamata in uscita"
                          : "Chiamata in ingresso"}
                      </strong>
                      <small>
                        {new Date(c.created_at).toLocaleString("it-IT")}
                      </small>
                    </div>
                    <Badge state={c.state} />
                  </div>
                  {c.state === "unknown" && (
                    <CallReview
                      call={c}
                      notify={notify}
                      onDone={() => api("/calls").then(setCalls)}
                    />
                  )}
                </React.Fragment>
              ))}
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function CallReview({
  call,
  notify,
  onDone,
}: {
  call: Json;
  notify: (text: string, error?: boolean) => void;
  onDone: () => void;
}) {
  const [sid, setSid] = useState(""),
    [note, setNote] = useState(""),
    [notCreated, setNotCreated] = useState(false),
    [verified, setVerified] = useState(false),
    [busy, setBusy] = useState(false);
  return (
    <section className="subform">
      <p className="body-copy">
        L’operatore potrebbe aver ricevuto la richiesta. Verifica il registro
        prima di consentire un nuovo tentativo.
      </p>
      <Field
        label="Call SID osservato nell’operatore"
        value={sid}
        onChange={setSid}
        disabled={notCreated}
      />
      <Toggle
        label="Ho verificato che la chiamata non è stata creata"
        checked={notCreated}
        onChange={setNotCreated}
      />
      <Field label="Esito della verifica" value={note} onChange={setNote} />
      <Toggle
        label="Confermo di aver verificato il registro dell’operatore"
        checked={verified}
        onChange={setVerified}
      />
      <button
        className="btn"
        disabled={
          !verified || note.trim().length < 5 || busy || (!notCreated && !sid)
        }
        onClick={async () => {
          setBusy(true);
          try {
            await post("/calls/" + call.id + "/reconcile", {
              verified: true,
              provider_id: sid,
              not_created: notCreated,
              note,
            });
            onDone();
            notify("Esito della chiamata riconciliato.");
          } catch (e: any) {
            notify(e.message, true);
          } finally {
            setBusy(false);
          }
        }}
      >
        Registra l’esito verificato
      </button>
    </section>
  );
}
