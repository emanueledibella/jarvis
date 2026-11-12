import Lighting from "./Lighting";
import MicrophoneSettings from "./Microphone";
import TelephonyConnection from "./TelephonyConnection";
import CompanionVoiceSettings from "./CompanionVoiceSettings";
import PersonalitySettings from "./PersonalitySettings";
import { companionVoice } from "./companionVoice";
import IntegrationConnect from "./IntegrationConnect";
import { remoteClient } from "./remoteClient";
import { RemoteDevices, RemoteConnection } from "./Remote";
import {
  t as tr,
  useI18n,
  uiLocale,
  formatNumber,
  saveInterfaceLanguage,
} from "./i18n";
import React, { useEffect, useState } from "react";
import { randomId } from "./randomId";
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
import { api, post, type Json } from "./api";
import {
  Badge,
  Field,
  SectionTitle,
  Toggle,
  profileLabels,
} from "./components";

type Props = {
  platform?: Json;
  nativeVoice?: Json;
  notify: (text: string, error?: boolean) => void;
  onSaved: () => void;
  initial?: string;
};
export default function Settings({
  platform,
  nativeVoice,
  notify,
  onSaved,
  initial = "interface",
}: Props) {
  const language = useI18n();
  const [savingLanguage, setSavingLanguage] = useState(false);
  const remote = remoteClient.enabled;
  const [revision, setRevision] = useState("");
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
      setLocked(data.locked || []);
      setRevision(data.revision || "");
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
      label={tr(label)}
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
          ? tr("Configured · leave blank to keep it")
          : undefined
      }
      options={options}
    />
  );
  const toggle = (key: string, label: string, help?: string) => (
    <Toggle
      key={key}
      label={tr(label)}
      checked={Boolean(values[key])}
      help={help}
      disabled={locked.includes(key)}
      onChange={(v) => change(key, v)}
    />
  );
  async function saveChanges() {
    if (!Object.keys(changes).length) return;
    await api("/settings", { method: "PATCH", body: JSON.stringify(changes),
      ...(remote ? { headers: { "If-Match": '"' + revision + '"' } } : {}) });
    await load();
    if (remote) await companionVoice.reload();
  }
  async function save() {
    setSaving(true);
    try {
      await saveChanges();
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
    if (remote && action === "calendar_authorize") { setTab("devices"); return; }
    try {
      const result = remote ? await companionVoice.control(action) : await post("/voice/control", { action });
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
  const personality = values.response_personality;
  const tabs = [
    ["interface", "Interface"],
    ["models", "Models"],
    ["voice", "Voice and presence"],
    ...(personality ? [["personality", "Personality"]] : []),
    ["memory", "Memory"],
    ["productivity", "Productivity"],
    ["lighting", "Lights and devices"],
    ["security", "Autonomy and privacy"],
    ["phone", "Telephony"],
    ...(remote ? [["devices", "Devices and jobs"], ["connection", "Connection"]] : []),
  ];
  return (
    <div className="page settings-page">
      <SectionTitle
        eyebrow={tr("YOUR ASSISTANT, YOUR CHOICES")}
        title={tr("Settings")}
        description={tr(
          "Models, connections, and boundaries. All under your control.",
        )}
        action={
          <div className="button-row">{remote && <button className="btn" disabled={saving} onClick={() => void load().catch(error => notify(error.message, true))}><RefreshCw size={15} />{tr("Reload settings")}</button>}<button
            className="btn primary"
            onClick={save}
            disabled={saving || !Object.keys(changes).length || (remote && (!remoteClient.admin || !revision))}
          >
            {saving ? (
              <LoaderCircle size={15} className="spin" />
            ) : (
              <Save size={15} />
            )}
            {tr("Save changes")}
          </button></div>
        }
      />
      <div
        className="settings-tabs"
        role="tablist"
        aria-label={tr("Settings sections")}
      >
        {tabs.map(([key, label]) => (
          <button
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            key={key}
            onClick={() => setTab(key)}
          >
            {tr(label)}
          </button>
        ))}
      </div>
      {remote && <div className="info-line"><ShieldCheck size={14} />{remoteClient.admin ? tr("Shared preferences are saved on the core. Microphone permission and input stay on this device.") : tr("Shared settings are read-only. Pair an administrator device to change them; voice on this device remains under your control.")}</div>}
      {!remote && !!locked.length && (
        <div className="info-line">
          <KeyRound size={14} />
          {tr(
            "Locked fields are set by the environment. Edit the env file and restart the service.",
          )}
        </div>
      )}
      {remote && tab === "devices" && <div className="settings-card remote-panel"><RemoteDevices notify={notify} /></div>}
      {remote && tab === "connection" && <div className="settings-card remote-panel"><RemoteConnection notify={notify} /></div>}
      {tab === "personality" && personality && (
        <div className="settings-grid">
          <PersonalitySettings
            profile={personality}
            disabled={saving || locked.includes("response_personality")}
            onChange={(profile) => change("response_personality", profile)}
          />
        </div>
      )}
      {tab === "interface" && (
        <div className="settings-grid">
          <section className="settings-card">
            <div className="card-heading">
              <Settings2 size={19} />
              <div>
                <h2>{tr("Language and interface")}</h2>
                <p>{tr("Choose the language for every Jarvis screen.")}</p>
              </div>
            </div>
            <Field
              label={tr("Interface language")}
              value={language}
              options={[
                { value: "en", label: tr("English") },
                { value: "it", label: tr("Italian") },
              ]}
              disabled={
                savingLanguage ||
                !values.ui_language ||
                locked.includes("ui_language")
              }
              onChange={async (value) => {
                setSavingLanguage(true);
                try {
                  const result = await saveInterfaceLanguage(value, remote ? revision : undefined);
                  if (remote) { const current = await api("/settings"); setRevision(current.revision); }
                  setValues((current) => ({
                    ...current,
                    ui_language: result.values.ui_language,
                  }));
                  notify("Interface language saved.");
                } catch (error: any) {
                  notify(error.message, true);
                } finally {
                  setSavingLanguage(false);
                }
              }}
              help={tr(
                "Changes apply immediately and are saved automatically. Voice recognition and conversation language stay independent.",
              )}
            />
            {savingLanguage && (
              <span className="info-line">
                <LoaderCircle size={14} className="spin" />
                {tr("Saving language…")}
              </span>
            )}
          </section>
        </div>
      )}
      {tab === "models" && (
        <div className="settings-grid">
          {!remote && <section className="settings-card">
            <div className="card-heading">
              <Computer size={19} />
              <div>
                <h2>{tr("Local intelligence")}</h2>
                <p>{tr("The model runs on your computer.")}</p>
              </div>
              <Badge
                state={
                  models.local_state === "connected"
                    ? "connected"
                    : "not_connected"
                }
              />
            </div>
            {field("local_provider", tr("Runtime"), "text", undefined, [
              { value: "ollama", label: tr("Ollama") },
              {
                value: "openai_compatible",
                label: tr("LM Studio / OpenAI compatible"),
              },
            ])}
            {field(
              "local_base_url",
              tr("Local endpoint"),
              "url",
              tr(
                "Ollama: http://127.0.0.1:11434 · LM Studio: http://127.0.0.1:1234/v1",
              ),
            )}
            <label className="field">
              <span>
                {tr("Local model")}{" "}
                {locked.includes("local_model") && <KeyRound size={11} />}
              </span>
              <input
                list="local-models"
                value={values.local_model || ""}
                onChange={(e) => change("local_model", e.target.value)}
                disabled={locked.includes("local_model")}
                placeholder={tr("Select an installed model")}
              />
              <datalist id="local-models">
                {models.local?.map((m: Json) => (
                  <option key={m.id} value={m.id} />
                ))}
              </datalist>
              <small>
                {models.local?.length
                  ? tr("{value0} models detected in the local runtime.", {
                      value0: models.local.length,
                    })
                  : tr("Start the runtime and detect models.")}
              </small>
            </label>
            {field(
              "local_api_key",
              tr("Runtime token, if required"),
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
                {tr("Detect models")}
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
                {tr("Test tool calling")}
              </button>
            </div>
            <small className="hint">
              {tr(
                "Save changes before testing. Models are never downloaded automatically.",
              )}
            </small>
          </section>}
          <section className="settings-card">
            <div className="card-heading">
              <Cloud size={19} />
              <div>
                <h2>{tr("Cloud intelligence")}</h2>
                <p>{tr("For tasks that need a remote model.")}</p>
              </div>
            </div>
            {field("cloud_provider", tr("Provider"), "text", undefined, [
              { value: "openai", label: tr("OpenAI · Responses API") },
              { value: "anthropic", label: tr("Anthropic") },
              {
                value: "openai_compatible",
                label: tr("Other OpenAI-compatible provider"),
              },
            ])}
            {field(
              "cloud_model",
              tr("Model ID"),
              "text",
              tr("Use the exact ID available in your account."),
            )}
            {field(
              "cloud_api_key",
              tr("API key"),
              "password",
              tr(
                remote ? "Keys are encrypted on the core and are never returned to companion apps." : "Stored in private configuration; keychain:account references are also supported.",
              ),
            )}
            {field("cloud_base_url", tr("Custom endpoint, optional"), "url")}
            <button
              className="btn"
              disabled={!!testing || (remote && !remoteClient.admin)}
              onClick={() => test("cloud")}
            >
              {testing === "cloud" ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <ShieldCheck size={14} />
              )}
              {tr("Test connection and tools")}
            </button>
            <small className="hint">
              {tr("The test makes a short real request to the provider.")}
            </small>
          </section>
          <section className="settings-card full">
            <h2>{tr("Default profile")}</h2>
            <div className="profile-options">
              {Object.entries(profileLabels).map(([key, label]) => (
                <button
                  key={key}
                  disabled={locked.includes("profile")}
                  onClick={() => change("profile", key)}
                  className={values.profile === key ? "selected" : ""}
                >
                  <span>{tr(label)}</span>
                  <small>
                    {key === "local_strict"
                      ? tr("No remote tools or cloud fallback")
                      : key === "local_connected"
                        ? tr("Local LLM, connected services enabled")
                        : key === "cloud"
                          ? tr("Selected cloud model")
                          : tr("Cloud when configured, otherwise local")}
                  </small>
                </button>
              ))}
            </div>
            <div className="form-grid">
              {field("max_output_tokens", tr("Response token limit"), "number")}
              {field(
                "cloud_reasoning_effort",
                tr("OpenAI reasoning"),
                "text",
                tr(
                  "Low prioritizes response time; this setting applies to GPT-5 and GPT-6 models.",
                ),
                [
                  { value: "low", label: tr("Low") },
                  { value: "medium", label: tr("Medium") },
                  { value: "high", label: tr("High") },
                  { value: "xhigh", label: tr("Extra high") },
                  { value: "max", label: tr("Max") },
                ],
              )}
              {toggle("python_sandbox_enabled", tr("Allow the agent to use isolated Python"))}
              {toggle("browser_enabled", tr("Allow the agent to use an isolated browser"))}
              {field("max_agent_steps", tr("Agent step limit"), "number")}
              {field("max_parallel_tasks", tr("Concurrent tasks"), "number")}
              {field(
                "task_timeout_seconds",
                tr("Maximum task duration, seconds"),
                "number",
              )}
              {field(
                "model_request_timeout_seconds",
                tr("Model timeout, seconds"),
                "number",
              )}
            </div>
          </section>
        </div>
      )}
      {tab === "lighting" && (
        <>
          <section className="settings-card">
            {toggle("lighting_enabled", tr("Enable lighting integration"))}
          </section>
          <Lighting notify={notify} />
        </>
      )}
      {tab === "voice" && (
        <div className={remote ? "settings-grid voice-settings-grid" : "settings-grid"}>
          {remote && <CompanionVoiceSettings notify={notify} />}
          <section className="settings-card voice-shared-settings">
            <div className="card-heading">
              <Headphones size={19} />
              <div>
                <h2>{tr("A voice within reach")}</h2>
                <p>
                  {tr(
                    remote ? "Voice preferences are shared across your companions. Each device manages its microphone permission." : "Microphone access and recognition are managed by the macOS app.",
                  )}
                </p>
              </div>
            </div>
            {!remote && platform?.native_voice === false && (
              <p className="info-line">
                {tr(
                  "This portable build supports text conversations. Native wake detection and desktop audio are available in the macOS app. Telephony is configured separately.",
                )}
              </p>
            )}
            {toggle("voice_enabled", tr("Enable voice"))}
            {toggle("wake_enabled", tr("Voice activation"))}
            {!remote && <MicrophoneSettings
              value={values.microphone_device_uid || ""}
              disabled={locked.includes("microphone_device_uid")}
              onChange={(uid) => change("microphone_device_uid", uid)}
              nativeAvailable={platform?.native_voice !== false}
              connected={Boolean(nativeVoice?.connected)}
              inputMissing={nativeVoice?.input_device_state === "missing"}
            />}
            {field(
              "wake_phrase",
              tr("Wake phrase"),
              "text",
              tr(
                "Detection uses on-device transcription with word boundaries.",
              ),
            )}
            {field(
              "language",
              tr("Recognition language"),
              "text",
              tr(
                remote ? "Example: it-IT. Install on-device recognition for this language on each companion. OpenAI detects conversation language after activation." : "Example: it-IT. The language must support on-device recognition on this Mac. OpenAI detects the conversation language from audio after activation.",
              ),
            )}
            {field(
              "response_language",
              tr("Response language"),
              "text",
              tr(
                "Auto follows complete requests in Italian, English, or another supported language. Tool output and accents do not change the conversation language.",
              ),
              [
                { value: "auto", label: tr("Auto · follow the user") },
                { value: "it-IT", label: tr("Italian") },
                { value: "en-GB", label: tr("English") },
              ],
            )}
            {field(
              "tts_voice",
              tr("System voice, optional identifier"),
              "text",
              tr(
                "Leave blank to select a system voice automatically from the response language.",
              ),
            )}
            {field(
              "desktop_voice_provider",
              tr("Voice conversation"),
              "text",
              undefined,
              [
                {
                  value: "apple",
                  label: tr(remote ? "System · on-device recognition and speech" : "Apple · recognition and synthesis on Mac"),
                },
                {
                  value: "openai_live",
                  label: tr("OpenAI Live · listening and natural speech"),
                },
              ],
            )}
            {field("desktop_voice_model", tr("OpenAI voice model"))}
            {field(
              "desktop_voice_duplex",
              tr("Microphone during playback"),
              "text",
              tr(
                "Automatic interruption uses local echo cancellation to distinguish your speech from Jarvis. Unsupported devices keep input protected during playback. ⌘⇧J always lets you take the floor.",
              ),
              [
                {
                  value: "echo_cancelled",
                  label: tr("Automatic · interrupt by speaking"),
                },
                { value: "gated", label: tr("Speakers · echo protection") },
                {
                  value: "full",
                  label: tr("Headphones · listen during playback"),
                },
              ],
            )}
            {values.desktop_voice_duplex === "echo_cancelled" &&
              values.desktop_voice_provider === "openai_live" &&
              !remote && platform?.native_voice !== false && (
                <p className="info-line" role="status">
                  {nativeVoice?.barge_in
                    ? tr(
                        "Echo cancellation and spoken interruption are active.",
                      )
                    : nativeVoice?.echo_cancellation === "active"
                      ? tr("Local echo cancellation is active.")
                      : nativeVoice?.microphone === "authorized" &&
                          !nativeVoice?.muted
                        ? tr(
                            "Automatic interruption is unavailable on this audio device. Echo protection remains on; use ⌘⇧J to speak.",
                          )
                        : tr(
                            "Enable voice to activate echo cancellation and spoken interruption.",
                          )}
                </p>
              )}
            {field(
              "desktop_voice_name",
              tr("OpenAI voice name or custom ID"),
              "text",
              tr(
                "Use a built-in name such as cedar, marin, ash, ballad or verse, or the voice_… ID of a saved GPT-Live voice.",
              ),
            )}
            {field(
              "desktop_voice_style",
              tr("Vocal style"),
              "textarea",
              tr(
                "Describe timbre, pacing and delivery. For a saved custom voice, keep its original description here.",
              ),
            )}
            {field(
              "desktop_voice_api_key",
              tr("OpenAI voice API key, optional"),
              "password",
              tr(
                "Leave blank to use the OpenAI provider key configured under Models.",
              ),
            )}
            <small className="hint">
              {tr(
                remote ? "Wake detection stays on this device. With OpenAI Live, conversation audio is sent through your core to OpenAI only after activation. System voice sends the recognized request to the core and speaks its answer locally." : "Speech is generated by an AI model. With OpenAI Live, wake detection stays local; after activation, the command and conversation audio go to OpenAI with a short initial RAM buffer. Keep the lid open for the built-in microphone or choose an external input.",
              )}
            </small>
            {!remote && <div className="button-row">
              <button className="btn primary" onClick={() => native("enable")}>
                <Headphones size={15} />
                {tr("Enable voice and permissions")}
              </button>
              <button className="btn" onClick={() => native("listen")}>
                {tr("Test listening")}
              </button>
            </div>}
          </section>
          <section className="settings-card">
            <h2>{tr("Conversation timing")}</h2>
            {field(
              "desktop_voice_max_session_seconds",
              tr("Maximum OpenAI session duration, seconds"),
              "number",
            )}
            {field(
              "desktop_voice_idle_seconds",
              tr("OpenAI idle timeout, seconds"),
              "number",
            )}
            {field(
              "desktop_voice_rate_usd_per_minute",
              tr("Voice rate in USD/minute for the budget"),
              "number",
            )}
            {field(
              "followup_seconds",
              tr("Follow-up window, seconds"),
              "number",
            )}
            {field(
              "end_of_turn_ms",
              tr("End-of-turn pause, milliseconds"),
              "number",
            )}
            {field(
              "listen_timeout_seconds",
              tr("Wait for speech, seconds"),
              "number",
              tr("Listening stays active while you speak. OpenAI session duration has its own limit above."),
            )}
            {toggle(
              "voice_on_lock_screen",
              tr("Allow voice while the screen is locked"),
              tr("Disabled by default."),
            )}
            {(!remote || ["macos", "windows"].includes(remoteClient.platform)) && <><div className="info-box">
              <strong>{tr("⌘ ⇧ J")}</strong>
              <p>
                {tr(
                  "Global shortcut to start a turn. Closing the window keeps Jarvis in the menu bar.",
                )}
              </p>
            </div>
            <div className="button-row">
              <button
                className="btn"
                onClick={() => native("autostart_enable")}
              >
                {tr("Launch at login")}
              </button>
              <button
                className="btn ghost"
                onClick={() => native("autostart_disable")}
              >
                {tr("Disable launch at login")}
              </button>
            </div>
            <small className="hint">
              {tr(
                "The Mac must be awake. Sleep and shutdown suspend the assistant.",
              )}
            </small></>}
          </section>
        </div>
      )}
      {tab === "memory" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>{tr("Your Second Brain")}</h2>
            {field(
              "second_brain_url",
              tr("Endpoint MCP"),
              "url",
              tr("Use your canonical memory installation."),
            )}
            {field(
              "second_brain_auth",
              tr("Authentication"),
              "text",
              undefined,
              [
                { value: "bearer", label: tr("Bearer token") },
                { value: "oauth", label: tr("OAuth with browser consent") },
                {
                  value: "none",
                  label: tr(
                    "None · only for servers explicitly protected elsewhere",
                  ),
                },
              ],
            )}
            {field("second_brain_token", tr("Dedicated token"), "password")}
            {toggle(
              "second_brain_allow_corrections",
              tr("Enable corrections and retractions"),
              tr(
                "Requires separate OAuth consent with memory:write. Enabled Second Brain operations run without confirmation.",
              ),
            )}
            {field("memory_capture", tr("Memory capture"), "text", undefined, [
              {
                value: "explicit_only",
                label: tr("Only when I ask to remember"),
              },
              {
                value: "explicit_facts",
                label: tr("Relevant explicit facts from conversations"),
              },
              { value: "off", label: tr("No new memory") },
            ])}
            {field(
              "memory_recall_token_budget",
              tr("Recall context budget"),
              "number",
            )}
            <IntegrationConnect name="second_brain" label={tr("Connect Second Brain")} notify={notify} disabled={remote && !remoteClient.admin} />
          </section>
          <section className="settings-card">
            <h2>{tr("Sources and continuity")}</h2>
            <p className="body-copy">
              {tr(
                "Memories retain their source, revision, and quotations. Saving is asynchronous: a queued source is not yet a searchable memory.",
              )}
            </p>
            <p className="body-copy">
              {tr(
                "Private sessions exclude new memory, checkpoint content, and persistent messages. Retracting a memory preserves originals in Second Brain.",
              )}
            </p>
            <div className="info-box">
              {tr(
                "Do not reuse other applications' credentials. Configure a dedicated connection with only the required privileges.",
              )}
            </div>
          </section>
        </div>
      )}
      {tab === "productivity" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>{tr("Agenda")}</h2>
            {field("calendar_provider", tr("Calendar"), "text", undefined, [
              { value: "disabled", label: tr("Not connected") },
              { value: "apple", label: tr("Apple Calendar · native on Mac") },
              { value: "ics", label: tr("ICS feed · read only") },
              { value: "google", label: tr("Google Calendar") },
              { value: "microsoft", label: tr("Microsoft 365 / Outlook") },
            ])}
            {values.calendar_provider === "apple" && (
              <button
                className="btn"
                onClick={() => native("calendar_authorize")}
              >
                {tr("Authorize Mac calendar")}
              </button>
            )}
            {values.calendar_provider === "ics" &&
              field("calendar_ics_url", tr("ICS feed URL"), "url")}
            {["google", "microsoft"].includes(values.calendar_provider) && (
              <>
                {field("calendar_client_id", tr("OAuth client ID"))}
                {field(
                  "calendar_client_secret",
                  tr("OAuth client secret, if required"),
                  "password",
                )}
                {field(
                  "calendar_refresh_token",
                  tr("Refresh token"),
                  "password",
                  tr("Refresh runs automatically when configured."),
                )}
                {field(
                  "calendar_access_token",
                  tr("Access token, temporary alternative"),
                  "password",
                )}
                {values.calendar_provider === "microsoft" &&
                  field("calendar_tenant_id", tr("Microsoft tenant"))}
              </>
            )}
            <small className="hint">
              {tr("Save the provider before authorizing the calendar.")}
            </small>
          </section>
          <section className="settings-card">
            <h2>{tr("Weather and search")}</h2>
            {field(
              "weather_location",
              tr("Weather location"),
              "text",
              tr("A city you choose; no automatic geolocation."),
            )}
            {field(
              "weather_refresh_minutes",
              tr("Weather refresh, minutes"),
              "number",
            )}
            {field("search_provider", tr("Search engine"), "text", undefined, [
              {
                value: "duckduckgo",
                label: tr("Public DuckDuckGo · keyless, best effort"),
              },
              { value: "brave", label: tr("Brave Search API") },
              { value: "tavily", label: tr("Tavily Search API") },
            ])}
            {field("search_api_key", tr("Search engine API key"), "password")}
            <small className="hint">
              {tr(
                "Weather uses Open-Meteo with attribution. The service may limit keyless search.",
              )}
            </small>
          </section>
        </div>
      )}
      {tab === "security" && (
        <div className="settings-grid">
          <section className="settings-card">
            <h2>{tr("Workspaces and commands")}</h2>
            {remote && <div className="info-box"><p>{tr("Authorize computer folders and commands in Devices and jobs. These host settings are managed by the server administrator.")}</p><button className="btn" onClick={() => setTab("devices")}>{tr("Devices and jobs")}</button></div>}
            {field(
              "workspace_roots",
              tr("Authorized folders, JSON array"),
              "textarea",
              tr(
                'Example: ["/absolute/path/projects/app"]. File tools exclude credentials and external symlinks.',
              ),
            )}
            {field(
              "command_execution",
              tr("Command execution"),
              "text",
              undefined,
              [
                { value: "disabled", label: tr("Disabled") },
                {
                  value: "approval",
                  label: tr("Host · proposal requires approval"),
                },
                { value: "sandbox", label: tr("macOS sandbox · no network") },
              ],
            )}
            {field(
              "command_timeout_seconds",
              tr("Command timeout, seconds"),
              "number",
            )}
            <p className="body-copy">
              {tr(
                "Command approval authorizes that specific action. Coding processes do not inherit provider API keys.",
              )}
            </p>
          </section>
          <section className="settings-card">
            <h2>{tr("Privacy and limits")}</h2>
            {field(
              "transcript_retention_days",
              tr("Message retention, days"),
              "number",
            )}
            {field(
              "operation_log_retention_days",
              tr("Event retention, days"),
              "number",
            )}
            {field("monthly_budget_usd", tr("Monthly limit, USD"), "number")}
            {field(
              "model_input_usd_per_million",
              tr("Input cost per million tokens, USD"),
              "number",
            )}
            {field(
              "model_output_usd_per_million",
              tr("Output cost per million tokens, USD"),
              "number",
            )}
            <small className="hint">
              {tr(
                "Cloud input and output rates are required. Each request reserves an estimate before sending; the provider's final bill remains authoritative.",
              )}
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
                <h2>{tr("Jarvis on the phone")}</h2>
                <p>{tr("Twilio Media Streams with two-way conversation.")}</p>
              </div>
            </div>
            {field(
              "telephony_tunnel_mode",
              tr("Connection management"),
              "text",
              tr(
                remote
                  ? "These settings are saved on the remote core. Jarvis uses the core's public HTTPS address to connect to Twilio."
                  : "Choose Jarvis to activate and deactivate telephony without terminal commands.",
              ),
              [
                { value: "managed", label: tr(remote ? "Managed by the remote core" : "Managed by Jarvis") },
                { value: "external", label: tr("External proxy") },
              ],
            )}
            {values.telephony_tunnel_mode === "managed" ? remote && !remoteClient.admin ? <p className="hint">{tr("An administrator device is required to manage telephony.")}</p> : (
              <TelephonyConnection
                locked={
                  locked.includes("telephony_enabled") &&
                  !values.telephony_enabled
                }
                prepare={async () => {
                  if (Object.keys(changes).length) {
                    await saveChanges();
                  }
                }}
                onChanged={async (enabled) => {
                  const currentSettings = await api("/settings");
                  setRevision(currentSettings.revision || "");
                  setValues((current) => ({
                    ...current,
                    telephony_enabled: currentSettings.values.telephony_enabled ?? enabled,
                  }));
                  setChanges((current) => {
                    const next = { ...current };
                    delete next.telephony_enabled;
                    return next;
                  });
                  onSaved();
                }}
                notify={notify}
              />
            ) : (
              <>
                {toggle(
                  "telephony_enabled",
                  tr("Enable telephony"),
                  tr("Requires a carrier, an HTTPS/WSS tunnel, and credit."),
                )}
                {field(
                  "telephony_public_base_url",
                  tr("Public telephony proxy URL"),
                  "url",
                  tr("Expose only /telephony, not the entire local API."),
                )}
              </>
            )}
            {field("telephony_account_id", tr("Twilio account SID"))}
            {field("telephony_auth_token", tr("Twilio auth token"), "password")}
            {field("telephony_from_number", tr("Caller number, E.164"))}
            {field("owner_phone_number", tr("Your verified number, E.164"))}
            {toggle(
              "phone_inbound_enabled",
              tr("Allow incoming calls to Jarvis"),
              tr(
                "Enable only if you want to call Jarvis yourself. Incoming calls always require a PIN.",
              ),
            )}
            {toggle(
              "phone_pin_enabled",
              tr("Require a PIN when Jarvis calls me"),
              tr(
                "When off, whoever answers your configured number can speak with Jarvis immediately.",
              ),
            )}
            {field(
              "phone_pin",
              tr("Personal PIN, 6–8 digits"),
              "password",
              tr(
                "Incoming calls always require this PIN. Outgoing calls follow the checkbox above. Never sent to the model.",
              ),
            )}
          </section>
          <section className="settings-card">
            <h2>{tr("Call audio and limits")}</h2>
            {values.desktop_voice_provider === "openai_live" ? (
              <div className="info-box">
                <strong>{tr("Same voice as the desktop")}</strong>
                <p>
                  {tr(
                    "Calls use the voice, vocal style, conversation language and OpenAI key configured for desktop voice.",
                  )}
                </p>
              </div>
            ) : (
              <>
                {field(
                  "phone_stt_provider",
                  tr("Phone speech recognition"),
                  "text",
                  undefined,
                  [
                    { value: "openai", label: tr("OpenAI · cloud audio") },
                    {
                      value: "faster_whisper",
                      label: tr("Local faster-whisper · voice extra required"),
                    },
                  ],
                )}
                {field(
                  "phone_api_key",
                  tr("OpenAI audio API key, if used"),
                  "password",
                  tr(
                    "Separate from the reasoning provider. Without a key, TTS uses the system voice.",
                  ),
                )}
              </>
            )}
            {field(
              "phone_max_call_seconds",
              tr("Maximum duration, seconds"),
              "number",
            )}
            {remote && <details className="settings-details"><summary>{tr("Manual recording")}</summary>
              {field("phone_stt_model", tr("Transcription model"))}
              {field("phone_tts_model", tr("Speech model"))}
              {field("phone_tts_voice", tr("Synthetic voice"))}
            </details>}
            {values.desktop_voice_provider !== "openai_live" &&
              field(
                "phone_local_tts_voice",
                tr("Mac phone voice, optional name"),
                "text",
                tr(
                  "Example: Alice, if installed. This differs from the desktop voice ID.",
                ),
              )}
            {field(
              "phone_daily_budget_usd",
              tr("Maximum daily reservation, USD"),
              "number",
            )}
            {field(
              "phone_minute_rate_usd",
              tr("Conservative rate, USD/min"),
              "number",
            )}
            {field(
              "quiet_hours",
              tr("Quiet hours"),
              "text",
              tr("Format: 22:00-08:00. No proactive calls outside policy."),
            )}
            <div className="info-box">
              {tr("Reservation for an outgoing call:")}{" "}
              {formatNumber(
                Math.ceil((values.phone_max_call_seconds || 0) / 60) *
                  (values.phone_minute_rate_usd || 0),
                2,
              )}{" "}
              {tr("USD. Check actual rates and save settings.")}
            </div>
            <Toggle
              checked={authorized}
              onChange={setAuthorized}
              label={tr("I authorize a test call to my number")}
            />
            <button
              className="btn"
              disabled={!authorized}
              onClick={async () => {
                setAuthorized(false);
                try {
                  await post("/calls/owner", {
                    authorized: true,
                    request_id: randomId(),
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
              {tr("Start test call")}
            </button>
          </section>
          {!!calls.length && (
            <section className="settings-card full">
              <h2>{tr("Recent calls")}</h2>
              {calls.map((c) => (
                <React.Fragment key={c.id}>
                  <div className="list-row">
                    <div>
                      <strong>
                        {c.direction === "outbound"
                          ? tr("Outgoing call")
                          : tr("Incoming call")}
                      </strong>
                      <small>
                        {new Date(c.created_at).toLocaleString(uiLocale())}
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
  useI18n();
  const [sid, setSid] = useState(""),
    [note, setNote] = useState(""),
    [notCreated, setNotCreated] = useState(false),
    [verified, setVerified] = useState(false),
    [busy, setBusy] = useState(false);
  return (
    <section className="subform">
      <p className="body-copy">
        {tr(
          "The carrier may have received the request. Check its log before allowing another attempt.",
        )}
      </p>
      <Field
        label={tr("Call SID observed in the carrier log")}
        value={sid}
        onChange={setSid}
        disabled={notCreated}
      />
      <Toggle
        label={tr("I verified that the call was not created")}
        checked={notCreated}
        onChange={setNotCreated}
      />
      <Field
        label={tr("Verification outcome")}
        value={note}
        onChange={setNote}
      />
      <Toggle
        label={tr("I confirm that I checked the carrier log")}
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
        {tr("Record verified outcome")}
      </button>
    </section>
  );
}
