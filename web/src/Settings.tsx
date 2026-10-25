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
          ? "Configured · leave blank to keep it"
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
      notify("Settings saved.");
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
          ? "Connection and tool calling verified."
          : "The model responded but did not make the requested tool call.",
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
        requires_approval: "Confirm launch at login in macOS settings.",
        denied:
          "Permission was not granted. You can change it in macOS settings.",
        not_registered: "Launch at login is not active.",
        enabled: "Launch at login is active.",
        disabled: "Launch at login is disabled.",
      };
      notify(
        result.error || states[result.state] || "Operation completed.",
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
    ["models", "Models"],
    ["voice", "Voice and presence"],
    ["memory", "Memory"],
    ["productivity", "Productivity"],
    ["security", "Autonomy and privacy"],
    ["phone", "Telephony"],
  ];
  return (
    <div className="page settings-page">
      <SectionTitle
        eyebrow="YOUR ASSISTANT, YOUR CHOICES"
        title="Settings"
        description="Models, connections, and boundaries. All under your control."
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
            Save changes
          </button>
        }
      />
      <div
        className="settings-tabs"
        role="tablist"
        aria-label="Settings sections"
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
          <KeyRound size={14} />
          Locked fields are set by the environment. Edit the env file and
          restart the service.
        </div>
      )}
      {tab === "models" && (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="card-heading">
              <Computer size={19} />
              <div>
                <h2>Local intelligence</h2>
                <p>The model runs on your Mac.</p>
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
                label: "LM Studio / OpenAI compatible",
              },
            ])}
            {field(
              "local_base_url",
              "Local endpoint",
              "url",
              "Ollama: http://127.0.0.1:11434 · LM Studio: http://127.0.0.1:1234/v1",
            )}
            <label className="field">
              <span>
                Local model{" "}
                {locked.includes("local_model") && <KeyRound size={11} />}
              </span>
              <input
                list="local-models"
                value={values.local_model || ""}
                onChange={(e) => change("local_model", e.target.value)}
                disabled={locked.includes("local_model")}
                placeholder="Select an installed model"
              />
              <datalist id="local-models">
                {models.local?.map((m: Json) => (
                  <option key={m.id} value={m.id} />
                ))}
              </datalist>
              <small>
                {models.local?.length
                  ? `${models.local.length} models detected in the local runtime.`
                  : "Start the runtime and detect models."}
              </small>
            </label>
            {field("local_api_key", "Runtime token, if required", "password")}
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
                Detect models
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
                Test tool calling
              </button>
            </div>
            <small className="hint">
              Save changes before testing. Models are never downloaded
              automatically.
            </small>
          </section>
          <section className="settings-card">
            <div className="card-heading">
              <Cloud size={19} />
              <div>
                <h2>Cloud intelligence</h2>
                <p>For tasks that need a remote model.</p>
              </div>
            </div>
            {field("cloud_provider", "Provider", "text", undefined, [
              { value: "openai", label: "OpenAI · Responses API" },
              { value: "anthropic", label: "Anthropic" },
              {
                value: "openai_compatible",
                label: "Other OpenAI-compatible provider",
              },
            ])}
            {field(
              "cloud_model",
              "Model ID",
              "text",
              "Use the exact ID available in your account.",
            )}
            {field(
              "cloud_api_key",
              "API key",
              "password",
              "Stored in private configuration; keychain:account references are also supported.",
            )}
            {field("cloud_base_url", "Custom endpoint, optional", "url")}
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
              Test connection and tools
            </button>
            <small className="hint">
              The test makes a short real request to the provider.
            </small>
          </section>
          <section className="settings-card full">
            <h2>Default profile</h2>
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
                      ? "No remote tools or cloud fallback"
                      : key === "local_connected"
                        ? "Local LLM, connected services enabled"
                        : key === "cloud"
                          ? "Selected cloud model"
                          : "Cloud when configured, otherwise local"}
                  </small>
                </button>
              ))}
            </div>
            <div className="form-grid">
              {field("max_output_tokens", "Response token limit", "number")}
              {field(
                "cloud_reasoning_effort",
                "OpenAI reasoning",
                "text",
                "Low prioritizes response time; this setting applies to GPT-5 and GPT-6 models.",
                [
                  { value: "low", label: "Low" },
                  { value: "medium", label: "Medium" },
                  { value: "high", label: "High" },
                  { value: "xhigh", label: "Extra high" },
                  { value: "max", label: "Max" },
                ],
              )}
              {field("max_agent_steps", "Agent step limit", "number")}
              {field(
                "task_timeout_seconds",
                "Maximum task duration, seconds",
                "number",
              )}
              {field(
                "model_request_timeout_seconds",
                "Model timeout, seconds",
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
                <h2>A voice within reach</h2>
                <p>
                  Microphone access and recognition are managed by the macOS
                  app.
                </p>
              </div>
            </div>
            {toggle("voice_enabled", "Enable voice")}
            {toggle("wake_enabled", "Voice activation")}
            {field(
              "wake_phrase",
              "Wake phrase",
              "text",
              "Detection uses on-device transcription with word boundaries.",
            )}
            {field(
              "language",
              "Recognition language",
              "text",
              "Example: it-IT. The language must support on-device recognition on this Mac. OpenAI detects the conversation language from audio after activation.",
            )}
            {field(
              "response_language",
              "Response language",
              "text",
              "Auto follows complete requests in Italian, English, or another supported language. Tool output and accents do not change the conversation language.",
              [
                { value: "auto", label: "Auto · follow the user" },
                { value: "it-IT", label: "Italian" },
                { value: "en-GB", label: "English" },
              ],
            )}
            {field(
              "tts_voice",
              "System voice, optional identifier",
              "text",
              "Leave blank to select a system voice automatically from the response language.",
            )}
            {field(
              "desktop_voice_provider",
              "Voice conversation",
              "text",
              undefined,
              [
                {
                  value: "apple",
                  label: "Apple · recognition and synthesis on Mac",
                },
                {
                  value: "openai_live",
                  label: "OpenAI Live · listening and natural speech",
                },
              ],
            )}
            {field("desktop_voice_model", "OpenAI voice model")}
            {field(
              "desktop_voice_duplex",
              "Microphone during playback",
              "text",
              "With speakers, input audio is gated during playback to prevent commands caused by echo. Press ⌘⇧J to take the floor again.",
              [
                { value: "gated", label: "Speakers · echo protection" },
                { value: "full", label: "Headphones · listen during playback" },
              ],
            )}
            {field("desktop_voice_name", "OpenAI voice", "text", undefined, [
              { value: "cedar", label: "Cedar" },
              { value: "marin", label: "Marin" },
              { value: "ash", label: "Ash" },
              { value: "verse", label: "Verse" },
              { value: "coral", label: "Coral" },
            ])}
            {field(
              "desktop_voice_api_key",
              "OpenAI voice API key, optional",
              "password",
              "Leave blank to use the OpenAI provider key configured under Models.",
            )}
            <small className="hint">
              Speech is generated by an AI model. With OpenAI Live, wake
              detection stays local; after activation, the command and
              conversation audio go to OpenAI with a short initial RAM buffer.
              Keep the lid open for the built-in microphone or choose an
              external input.
            </small>
            <div className="button-row">
              <button className="btn primary" onClick={() => native("enable")}>
                <Headphones size={15} />
                Enable voice and permissions
              </button>
              <button className="btn" onClick={() => native("listen")}>
                Test listening
              </button>
            </div>
          </section>
          <section className="settings-card">
            <h2>Conversation timing</h2>
            {field(
              "desktop_voice_max_session_seconds",
              "Maximum OpenAI session duration, seconds",
              "number",
            )}
            {field(
              "desktop_voice_idle_seconds",
              "OpenAI idle timeout, seconds",
              "number",
            )}
            {field(
              "desktop_voice_rate_usd_per_minute",
              "Voice rate in USD/minute for the budget",
              "number",
            )}
            {field("followup_seconds", "Follow-up window, seconds", "number")}
            {field(
              "end_of_turn_ms",
              "End-of-turn pause, milliseconds",
              "number",
            )}
            {field(
              "listen_timeout_seconds",
              "Maximum command duration, seconds",
              "number",
            )}
            {toggle(
              "voice_on_lock_screen",
              "Allow voice while the screen is locked",
              "Disabled by default.",
            )}
            <div className="info-box">
              <strong>⌘ ⇧ J</strong>
              <p>
                Global shortcut to start a turn. Closing the window keeps Jarvis
                in the menu bar.
              </p>
            </div>
            <div className="button-row">
              <button
                className="btn"
                onClick={() => native("autostart_enable")}
              >
                Launch at login
              </button>
              <button
                className="btn ghost"
                onClick={() => native("autostart_disable")}
              >
                Disable launch at login
              </button>
            </div>
            <small className="hint">
              The Mac must be awake. Sleep and shutdown suspend the assistant.
            </small>
          </section>
        </div>
      )}
      {tab === "memory" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Your Second Brain</h2>
            {field(
              "second_brain_url",
              "Endpoint MCP",
              "url",
              "Use your canonical memory installation.",
            )}
            {field("second_brain_auth", "Authentication", "text", undefined, [
              { value: "bearer", label: "Bearer token" },
              { value: "oauth", label: "OAuth with browser consent" },
              {
                value: "none",
                label: "None · only for servers explicitly protected elsewhere",
              },
            ])}
            {field("second_brain_token", "Dedicated token", "password")}
            {toggle(
              "second_brain_allow_corrections",
              "Enable corrections and retractions",
              "Requires separate OAuth consent with memory:write. Changes still require approval.",
            )}
            {field("memory_capture", "Memory capture", "text", undefined, [
              {
                value: "explicit_only",
                label: "Only when I ask to remember",
              },
              {
                value: "explicit_facts",
                label: "Relevant explicit facts from conversations",
              },
              { value: "off", label: "No new memory" },
            ])}
            {field(
              "memory_recall_token_budget",
              "Recall context budget",
              "number",
            )}
            <button
              className="btn"
              onClick={() =>
                post("/integrations/second_brain/connect")
                  .then(() =>
                    notify(
                      "Connection started. Complete browser consent if requested.",
                    ),
                  )
                  .catch((e) => notify(e.message, true))
              }
            >
              Connect Second Brain
            </button>
          </section>
          <section className="settings-card">
            <h2>Sources and continuity</h2>
            <p className="body-copy">
              Memories retain their source, revision, and quotations. Saving is
              asynchronous: a queued source is not yet a searchable memory.
            </p>
            <p className="body-copy">
              Private sessions exclude new memory, checkpoint content, and
              persistent messages. Retracting a memory preserves originals in
              Second Brain.
            </p>
            <div className="info-box">
              Do not reuse other applications' credentials. Configure a
              dedicated connection with only the required privileges.
            </div>
          </section>
        </div>
      )}
      {tab === "productivity" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Agenda</h2>
            {field("calendar_provider", "Calendar", "text", undefined, [
              { value: "disabled", label: "Not connected" },
              { value: "apple", label: "Apple Calendar · native on Mac" },
              { value: "ics", label: "ICS feed · read only" },
              { value: "google", label: "Google Calendar" },
              { value: "microsoft", label: "Microsoft 365 / Outlook" },
            ])}
            {values.calendar_provider === "apple" && (
              <button
                className="btn"
                onClick={() => native("calendar_authorize")}
              >
                Authorize Mac calendar
              </button>
            )}
            {values.calendar_provider === "ics" &&
              field("calendar_ics_url", "ICS feed URL", "url")}
            {["google", "microsoft"].includes(values.calendar_provider) && (
              <>
                {field("calendar_client_id", "OAuth client ID")}
                {field(
                  "calendar_client_secret",
                  "OAuth client secret, if required",
                  "password",
                )}
                {field(
                  "calendar_refresh_token",
                  "Refresh token",
                  "password",
                  "Refresh runs automatically when configured.",
                )}
                {field(
                  "calendar_access_token",
                  "Access token, temporary alternative",
                  "password",
                )}
                {values.calendar_provider === "microsoft" &&
                  field("calendar_tenant_id", "Microsoft tenant")}
              </>
            )}
            <small className="hint">
              Save the provider before authorizing the calendar.
            </small>
          </section>
          <section className="settings-card">
            <h2>Weather and search</h2>
            {field(
              "weather_location",
              "Weather location",
              "text",
              "A city you choose; no automatic geolocation.",
            )}
            {field(
              "weather_refresh_minutes",
              "Weather refresh, minutes",
              "number",
            )}
            {field("search_provider", "Search engine", "text", undefined, [
              {
                value: "duckduckgo",
                label: "Public DuckDuckGo · keyless, best effort",
              },
              { value: "brave", label: "Brave Search API" },
              { value: "tavily", label: "Tavily Search API" },
            ])}
            {field("search_api_key", "Search engine API key", "password")}
            <small className="hint">
              Weather uses Open-Meteo with attribution. The service may limit
              keyless search.
            </small>
          </section>
        </div>
      )}
      {tab === "security" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>Workspaces and commands</h2>
            {field(
              "workspace_roots",
              "Authorized folders, JSON array",
              "textarea",
              'Example: ["/absolute/path/projects/app"]. File tools exclude credentials and external symlinks.',
            )}
            {field(
              "command_execution",
              "Command execution",
              "text",
              undefined,
              [
                { value: "disabled", label: "Disabled" },
                {
                  value: "approval",
                  label: "Host · proposal requires approval",
                },
                { value: "sandbox", label: "macOS sandbox · no network" },
              ],
            )}
            {field(
              "command_timeout_seconds",
              "Command timeout, seconds",
              "number",
            )}
            <p className="body-copy">
              Command approval authorizes that specific action. Coding processes
              do not inherit provider API keys.
            </p>
          </section>
          <section className="settings-card">
            <h2>Privacy and limits</h2>
            {field(
              "transcript_retention_days",
              "Message retention, days",
              "number",
            )}
            {field(
              "operation_log_retention_days",
              "Event retention, days",
              "number",
            )}
            {field("monthly_budget_usd", "Monthly limit, USD", "number")}
            {field(
              "model_input_usd_per_million",
              "Input cost per million tokens, USD",
              "number",
            )}
            {field(
              "model_output_usd_per_million",
              "Output cost per million tokens, USD",
              "number",
            )}
            <small className="hint">
              Cloud input and output rates are required. Each request reserves
              an estimate before sending; the provider's final bill remains
              authoritative.
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
                <h2>Jarvis on the phone</h2>
                <p>Twilio Media Streams with two-way conversation.</p>
              </div>
            </div>
            {toggle(
              "telephony_enabled",
              "Enable telephony",
              "Requires a carrier, an HTTPS/WSS tunnel, and credit.",
            )}
            {field("telephony_account_id", "Twilio account SID")}
            {field("telephony_auth_token", "Twilio auth token", "password")}
            {field(
              "telephony_public_base_url",
              "Public telephony proxy URL",
              "url",
              "Expose only /telephony, not the entire local API.",
            )}
            {field("telephony_from_number", "Caller number, E.164")}
            {field("owner_phone_number", "Your verified number, E.164")}
            {field(
              "phone_pin",
              "Personal PIN, 4–8 digits",
              "password",
              "Required before discussing private data. Never sent to the model.",
            )}
          </section>
          <section className="settings-card">
            <h2>Call audio and limits</h2>
            {field(
              "phone_stt_provider",
              "Phone speech recognition",
              "text",
              undefined,
              [
                { value: "openai", label: "OpenAI · cloud audio" },
                {
                  value: "faster_whisper",
                  label: "Local faster-whisper · voice extra required",
                },
              ],
            )}
            {field(
              "phone_api_key",
              "OpenAI audio API key, if used",
              "password",
              "Separate from the reasoning provider. Without a key, TTS uses the system voice.",
            )}
            {field(
              "phone_max_call_seconds",
              "Maximum duration, seconds",
              "number",
            )}
            {field(
              "phone_local_tts_voice",
              "Mac phone voice, optional name",
              "text",
              "Example: Alice, if installed. This differs from the desktop voice ID.",
            )}
            {field(
              "phone_daily_budget_usd",
              "Maximum daily reservation, USD",
              "number",
            )}
            {field(
              "phone_minute_rate_usd",
              "Conservative rate, USD/min",
              "number",
            )}
            {field(
              "quiet_hours",
              "Quiet hours",
              "text",
              "Format: 22:00-08:00. No proactive calls outside policy.",
            )}
            <div className="info-box">
              Reservation for an outgoing call:{" "}
              {(
                Math.ceil((values.phone_max_call_seconds || 0) / 60) *
                (values.phone_minute_rate_usd || 0)
              ).toFixed(2)}{" "}
              USD. Check actual rates and save settings.
            </div>
            <Toggle
              checked={authorized}
              onChange={setAuthorized}
              label="I authorize a test call to my number"
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
                    reason: "Test call requested by the owner",
                  });
                  notify("Request sent to the carrier.");
                  setCalls(await api("/calls"));
                } catch (e: any) {
                  notify(e.message, true);
                }
              }}
            >
              <Phone size={14} />
              Start test call
            </button>
          </section>
          {!!calls.length && (
            <section className="settings-card full">
              <h2>Recent calls</h2>
              {calls.map((c) => (
                <React.Fragment key={c.id}>
                  <div className="list-row">
                    <div>
                      <strong>
                        {c.direction === "outbound"
                          ? "Outgoing call"
                          : "Incoming call"}
                      </strong>
                      <small>
                        {new Date(c.created_at).toLocaleString("en-GB")}
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
        The carrier may have received the request. Check its log before allowing
        another attempt.
      </p>
      <Field
        label="Call SID observed in the carrier log"
        value={sid}
        onChange={setSid}
        disabled={notCreated}
      />
      <Toggle
        label="I verified that the call was not created"
        checked={notCreated}
        onChange={setNotCreated}
      />
      <Field label="Verification outcome" value={note} onChange={setNote} />
      <Toggle
        label="I confirm that I checked the carrier log"
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
            notify("Call outcome reconciled.");
          } catch (e: any) {
            notify(e.message, true);
          } finally {
            setBusy(false);
          }
        }}
      >
        Record verified outcome
      </button>
    </section>
  );
}
