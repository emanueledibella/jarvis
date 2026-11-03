import { t as tr, useI18n } from "./i18n";
import React, { useEffect, useRef, useState } from "react";
import { Mic, Monitor, Settings2, ShieldCheck, Smartphone, Square, Unplug } from "lucide-react";
import { Capacitor } from "@capacitor/core";
import { PushNotifications } from "@capacitor/push-notifications";
import { api, post } from "./api";
import { Modal } from "./components";
import { nativePlugin, remoteClient } from "./remoteClient";
import "./remote.css";
import { canonicalAudio } from "./remoteAudio";
import RemoteShared from "./RemoteShared";

type Values = Record<string, any>;

export default function RemoteBootstrap({ children }: { children: React.ReactNode }) {
  useI18n();
  const [ready, setReady] = useState(false), [remote, setRemote] = useState(false), [connected, setConnected] = useState(false);
  const [error, setError] = useState(""), [address, setAddress] = useState(""), [code, setCode] = useState(""), [name, setName] = useState(tr("My device")), [busy, setBusy] = useState(false);
  async function initialize() {
    try {
      const enabled = await remoteClient.initialize();
      setRemote(enabled); setConnected(remoteClient.authenticated);
      setAddress(remoteClient.credentials?.server_url || (remoteClient.vault ? "" : location.origin));
    } catch (e: any) { setRemote(true); setError(e.message); setAddress(remoteClient.credentials?.server_url || ""); }
    finally { setReady(true); }
  }
  useEffect(() => {
    void initialize();
    const logout = (event: Event) => { setConnected(false); setError((event as CustomEvent).detail?.revoked === false ? tr("Local credentials removed. The core could not confirm revocation; revoke this device from another administrator companion.") : ""); };
    const expired = () => { setConnected(false); setError(tr("Session expired or revoked. Pair this device again.")); };
    window.addEventListener("jarvis-remote-logout", logout);
    window.addEventListener("jarvis-remote-session-expired", expired);
    return () => { window.removeEventListener("jarvis-remote-logout", logout); window.removeEventListener("jarvis-remote-session-expired", expired); };
  }, []);
  async function pair(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { await remoteClient.enroll(address, code, name); setCode(""); setConnected(true); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  if (!ready) return <div className="connect-screen" role="status">{tr("Connecting to Jarvis…")}</div>;
  if (!remote) return <>{children}</>;
  if (!connected) return <main className="connect-screen remote-connect">
    <ShieldCheck size={42} aria-hidden="true" />
    <h1>{tr("Your Jarvis, everywhere.")}</h1><p>{tr("Connect this device to your core with a single-use pairing code.")}</p>
    <form onSubmit={pair}>
      <label>{tr("Jarvis server")}<input type="url" required placeholder="https://jarvis.example.com" value={address} onChange={e => setAddress(e.target.value)} autoCapitalize="none" autoCorrect="off" /></label>
      <label>{tr("Device name")}<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>{tr("Pairing code")}<input type="password" required value={code} onChange={e => setCode(e.target.value)} autoComplete="off" autoCapitalize="none" spellCheck={false} /></label>
      {error && <p role="alert">{error}</p>}
      <button className="btn primary" type="submit" disabled={busy}>{busy ? tr("Connecting…") : tr("Connect device")}</button>
    </form>
    {remoteClient.credentials && <button className="btn" onClick={() => { setReady(false); void initialize(); }}>{tr("Retry existing connection")}</button>}
    <small>{tr("Use a companion code issued by the owner. Configure model API keys on the core after connecting.")}</small>
  </main>;
  return <div className="remote-shell"><RemoteTools />{children}</div>;
}

function RemoteTools() {
  const [panel, setPanel] = useState(""), [message, setMessage] = useState("");
  const [authorizations, setAuthorizations] = useState<Values[]>([]);
  useEffect(() => {
    if (!remoteClient.admin) return;
    const update = () => { void remoteClient.json<Values[]>("authorizations").then(setAuthorizations).catch(() => {}); };
    update(); const timer = setInterval(update, 5000); return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    const open = () => setPanel("voice");
    const stop = () => setPanel(value => value === "voice" ? "" : value);
    window.addEventListener("jarvis-remote-voice", open);
    window.addEventListener("jarvis-emergency-stop", stop);
    return () => { window.removeEventListener("jarvis-remote-voice", open); window.removeEventListener("jarvis-emergency-stop", stop); };
  }, []);
  return <>
    <PushRegistration notify={setMessage} automatic />
    <RemoteShared notify={setMessage} />
    <header className="remote-toolbar" aria-label={tr("Remote connection")}>
      <span><ShieldCheck size={15} /> {tr("Remote core")}</span>
      <div><button onClick={() => setPanel("devices")}><Monitor size={15} /> {tr("Devices")}</button>
        {remoteClient.admin && <button onClick={() => setPanel("model")}><Settings2 size={15} /> {tr("Model")}</button>}
        <button onClick={() => setPanel("voice")}><Mic size={15} /> {tr("Voice")}</button>
        {!!authorizations.length && <button onClick={() => setPanel("connection")}>{tr("Authorizations (")}{authorizations.length})</button>}
        <button aria-label={tr("Connection and sign out")} onClick={() => setPanel("connection")}><Unplug size={15} /></button>
      </div>
    </header>
    {panel && <Modal title={{ devices: tr("Devices and jobs"), model: tr("Core model"), voice: tr("Talk to Jarvis"), connection: tr("Connection") }[panel] || "Jarvis"} onClose={() => { setPanel(""); setMessage(""); }}>
      <div className="modal-body remote-panel">
        {panel === "devices" && <RemoteDevices notify={setMessage} />}
        {panel === "model" && <RemoteModelSettings notify={setMessage} />}
        {panel === "voice" && <RemoteVoice notify={setMessage} />}
        {panel === "connection" && <><p>{remoteClient.credentials?.server_url}</p><p>{tr("This device identity:")} {remoteClient.credentials?.device_id}</p>
          {authorizations.map(item => <article className="remote-device" key={item.name}><strong>{tr("Authorize")} {item.name}</strong><a className="btn" href={item.url} target="_blank" rel="noreferrer noopener">{tr("Open consent in the browser")}</a><small>{tr("Expires in")} {item.expires_in} {tr("seconds. Check the connection status after granting consent.")}</small></article>)}
          <button className="btn" onClick={async () => { try { await remoteClient.logout(); } catch (e: any) { setMessage(e.message); } }}>{tr("Revoke this device and sign out")}</button>
          <PushRegistration notify={setMessage} /></>}
        {message && <p role="status" className="remote-message">{message}</p>}
      </div>
    </Modal>}
  </>;
}

function RemoteDevices({ notify }: { notify: (s: string) => void }) {
  const [devices, setDevices] = useState<Values[]>([]), [jobs, setJobs] = useState<Values[]>([]), [code, setCode] = useState("");
  const [directory, setDirectory] = useState(""), [scope, setScope] = useState("personal"), [write, setWrite] = useState(false), [command, setCommand] = useState(false), [prefixes, setPrefixes] = useState("git status\ngit diff\nnpm test\nnpm run build"), [executorCode, setExecutorCode] = useState(""), [local, setLocal] = useState<Values>({});
  const bridge = window.jarvisCompanion;
  const [calendarRead, setCalendarRead] = useState(false), [calendarWrite, setCalendarWrite] = useState(false), [screen, setScreen] = useState(false);
  async function refresh() {
    try {
      const [d, j] = await Promise.all([remoteClient.json<Values[]>("devices"), remoteClient.json<Values[]>("jobs")]);
      setDevices(d); setJobs(j);
      if (bridge?.executorStatus) setLocal(await bridge.executorStatus());
    } catch (e: any) { notify(e.message); }
  }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, []);
  async function pairCode(kind: string, owner = false) {
    try { const result = await remoteClient.json("pairing-codes", { kind, owner }); setCode(result.code); }
    catch (e: any) { notify(e.message); }
  }
  async function configure() {
    try {
      await bridge?.configureExecutor?.({ server_url: remoteClient.credentials!.server_url, code: executorCode, name: tr("Executor ") + bridge.platform,
        acknowledge_host_commands: command, native_scope: scope,
        native: [...(calendarRead ? ["calendar.list"] : []), ...(calendarWrite ? ["calendar.create", "calendar.update", "calendar.delete"] : []), ...(screen ? ["screen.capture"] : [])],
        workspaces: directory ? [{ path: directory, label: directory.split(/[\\/]/).pop(), scope, read: true, write, command, commands: prefixes.split("\n").map(v => v.trim()).filter(Boolean) }] : [] });
      setExecutorCode(""); notify(tr("Executor configured with the selected permissions.")); await refresh();
    } catch (e: any) { notify(e.message); }
  }
  return <>
    {devices.map(device => <article className="remote-device" key={device.id}>
      <strong>{device.kind === "executor" ? <Monitor size={16} /> : <Smartphone size={16} />} {device.name}</strong>
      <span>{device.platform} · {device.revoked ? tr("Revoked") : device.kind === "executor" ? device.connected ? tr("Connected") : tr("Disconnected") : tr("Paired")}</span>
      {device.capabilities?.workspaces?.map((w: Values) => <small key={w.id}>{w.label} · {w.scope} {tr("· read")} {w.read ? tr("yes") : tr("no")}{tr(", write")} {w.write ? tr("yes") : tr("no")}{tr(", commands")} {w.command ? tr("yes") : tr("no")}</small>)}
      {device.capabilities?.native?.length > 0 && <small>{device.capabilities.native.join(", ")} · {device.capabilities.native_scope}</small>}
      {!device.revoked && device.kind === "executor" && <button className="btn" onClick={async () => { try { await remoteClient.json("session/executor", { device_id: device.id }); window.dispatchEvent(new Event("jarvis-session-changed")); notify(tr("Device selected for this conversation.")); } catch (e: any) { notify(e.message); } }}>{tr("Use in this conversation")}</button>}
      {!device.revoked && remoteClient.admin && <button className="btn" onClick={async () => { try { await remoteClient.json("devices/" + device.id + "/revoke", {}); await refresh(); } catch (e: any) { notify(e.message); } }}>{tr("Revoke")}</button>}
    </article>)}
    {remoteClient.admin && <section><h3>{tr("Pair a device")}</h3><div className="assistant-actions">
      <button className="btn" onClick={() => pairCode("companion")}>{tr("Companion code")}</button>
      <button className="btn" onClick={() => pairCode("companion", true)}>{tr("Administrator code")}</button>
      <button className="btn" onClick={() => pairCode("executor")}>{tr("Executor code")}</button>
    </div>{code && <label>{tr("Single-use code · expires in 10 minutes")}<input readOnly value={code} onFocus={e => e.currentTarget.select()} autoComplete="off" /></label>}</section>}
    {bridge?.selectDirectory && <section><h3>{tr("Executor on this computer")}</h3><p>{tr("Status:")} {local.state || tr("not configured")}{tr(". Permissions are granted on this computer.")}</p>
      <button className="btn" onClick={async () => { const value = await bridge.selectDirectory!(); if (value) setDirectory(value); }}>{tr("Choose an authorized directory")}</button>
      <p className="remote-path">{directory}</p>
      <label>{tr("Scope")}<select value={scope} onChange={e => setScope(e.target.value)}><option value="personal">{tr("Personal")}</option><option value="work">{tr("Work")}</option></select></label>
      <label><input type="checkbox" checked={write} onChange={e => setWrite(e.target.checked)} /> {tr("Allow approved writes")}</label>
      <label><input type="checkbox" checked={command} onChange={e => setCommand(e.target.checked)} /> {tr("I authorize approved commands that can execute project code with my user permissions")}</label>
      {command && <label>{tr("Allowed command prefixes, one per line")}<textarea value={prefixes} onChange={e => setPrefixes(e.target.value)} rows={4} /></label>}
      {bridge.platform === "macos" && <><label><input type="checkbox" checked={calendarRead} onChange={e => setCalendarRead(e.target.checked)} /> {tr("Allow reading the macOS calendar")}</label>
        <label><input type="checkbox" checked={calendarWrite} onChange={e => setCalendarWrite(e.target.checked)} /> {tr("Allow approved macOS calendar changes")}</label>
        <label><input type="checkbox" checked={screen} onChange={e => setScreen(e.target.checked)} /> {tr("Allow capturing a window chosen on the Mac for each request")}</label></>}
      <label>{tr("Executor code")}<input type="password" value={executorCode} onChange={e => setExecutorCode(e.target.value)} autoComplete="off" /></label>
      <button className="btn primary" disabled={(!directory && !calendarRead && !calendarWrite && !screen) || !executorCode} onClick={configure}>{tr("Pair and enable executor")}</button>
      <div className="assistant-actions"><button className="btn" onClick={async () => { await bridge.setExecutorEnabled?.(true); await refresh(); }}>{tr("Start in background")}</button><button className="btn" onClick={async () => { await bridge.setExecutorEnabled?.(false); await refresh(); }}>{tr("Stop executor")}</button></div>
    </section>}
    <h3>{tr("Desktop jobs")}</h3>{!jobs.length && <p>{tr("No jobs. Request operations in chat after pairing an executor.")}</p>}
    {jobs.map(job => <article className="remote-device" key={job.id}><strong>{job.operation}</strong><span>{job.state}</span><small>{job.id}</small>{job.state === "unknown" && <><p>{tr("Verify the outcome on the device. Reconcile it before repeating the operation.")}</p>{job.task_id && <button className="btn" onClick={() => window.dispatchEvent(new Event("jarvis-remote-open-tasks"))}>{tr("Review task")}</button>}</>}{["queued", "delivered", "claimed", "running"].includes(job.state) && <button className="btn" onClick={async () => { try { await remoteClient.json("jobs/" + job.id + "/cancel", {}); await refresh(); } catch (e: any) { notify(e.message); } }}>{tr("Cancel")}</button>}</article>)}
  </>;
}

export function RemoteModelSettings({ notify }: { notify: (s: string) => void }) {
  const [values, setValues] = useState<Values>({}), [changes, setChanges] = useState<Values>({}), [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState("");
  async function load() { const result = await api("/settings"); setValues(result.values); setRevision(result.revision); setChanges({}); }
  useEffect(() => { void load().catch(e => notify(e.message)); }, []);
  const value = (name: string) => changes[name] ?? values[name] ?? "";
  async function save() {
    setBusy(true);
    try { await api("/settings", { method: "PATCH", body: JSON.stringify(changes), headers: { "If-Match": '"' + revision + '"' } }); await load(); notify(tr("Core configuration updated. New jobs will use these settings.")); }
    catch (e: any) { notify(e.message); } finally { setBusy(false); }
  }
  if (!remoteClient.admin) return <p>{tr("Changing models requires an administrator device.")}</p>;
  return <section className="remote-form"><p>{tr("Keys are stored on the server and are not returned to apps.")}</p>
    <label>Provider<select value={value("cloud_provider")} onChange={e => setChanges({ ...changes, cloud_provider: e.target.value })}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="openai_compatible">OpenAI-compatible</option></select></label>
    {[["cloud_model", tr("Model")], ["cloud_base_url", tr("Custom endpoint (optional)")], ["cloud_api_key", values.cloud_api_key_configured ? tr("New API key (a key is already configured)") : "API key"], ["desktop_voice_api_key", tr("OpenAI voice API key (optional when already using OpenAI)")]].map(([key, label]) => <label key={key}>{label}<input type={key.includes("key") ? "password" : "text"} autoComplete="off" value={key.includes("key") ? changes[key] || "" : value(key)} onChange={e => setChanges({ ...changes, [key]: e.target.value })} /></label>)}
    {[["model_input_usd_per_million", tr("USD per million input tokens")], ["model_output_usd_per_million", tr("USD per million output tokens")], ["monthly_budget_usd", tr("Estimated monthly budget USD")]].map(([key, label]) => <label key={key}>{label}<input type="number" min="0" step="0.001" value={value(key)} onChange={e => setChanges({ ...changes, [key]: Number(e.target.value) })} /></label>)}
    <details><summary>{tr("Core preferences and services")}</summary>
      <label>{tr("Interface language")}<select value={value("ui_language")} onChange={e => setChanges({ ...changes, ui_language: e.target.value })}><option value="en">English</option><option value="it">Italiano</option></select></label>
      <label>{tr("Response language")}<select value={value("response_language")} onChange={e => setChanges({ ...changes, response_language: e.target.value })}><option value="auto">Auto</option><option value="en">English</option><option value="it">Italiano</option></select></label>
      {[["timezone", tr("Timezone")], ["weather_location", tr("Weather location")], ["weather_latitude", tr("Latitude")], ["weather_longitude", tr("Longitude")], ["quiet_hours", tr("Quiet hours (HH:MM-HH:MM)")], ["second_brain_url", tr("Second Brain MCP URL")], ["calendar_ics_url", tr("ICS calendar URL")]].map(([key, label]) => <label key={key}>{label}<input value={value(key)} onChange={e => setChanges({ ...changes, [key]: key.startsWith("weather_l") && key !== "weather_location" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value })} /></label>)}
      <label>{tr("Calendar")}<select value={value("calendar_provider")} onChange={e => setChanges({ ...changes, calendar_provider: e.target.value })}>{["disabled", "apple", "ics", "google", "microsoft"].map(name => <option key={name}>{name}</option>)}</select></label>
      <p>{tr("Apple calendar requires a connected, authorized Mac. Cloud calendars continue to work when the Mac is off.")}</p>
      {[["calendar_access_token", tr("Calendar token")], ["calendar_refresh_token", tr("Calendar refresh token")], ["calendar_client_id", tr("Calendar client ID")], ["calendar_client_secret", tr("Calendar client secret")], ["calendar_tenant_id", tr("Calendar tenant")], ["second_brain_token", tr("Second Brain token")], ["search_api_key", tr("Search API key")]].map(([key, label]) => <label key={key}>{label}<input type={key.endsWith("id") ? "text" : "password"} autoComplete="off" placeholder={values[key + "_configured"] ? tr("Configured") : ""} value={changes[key] ?? (key.endsWith("id") ? value(key) : "")} onChange={e => setChanges({ ...changes, [key]: e.target.value })} /></label>)}
      <label>{tr("Second Brain authentication")}<select value={value("second_brain_auth")} onChange={e => setChanges({ ...changes, second_brain_auth: e.target.value })}>{["oauth", "bearer", "none"].map(name => <option key={name}>{name}</option>)}</select></label>
      <button className="btn" onClick={async () => { try { await post("/integrations/second_brain/connect", {}); notify(tr("Connection started. Open authorizations to complete consent.")); } catch (e: any) { notify(e.message); } }}>{tr("Connect Second Brain")}</button>
      <label>{tr("Memory")}<select value={value("memory_capture")} onChange={e => setChanges({ ...changes, memory_capture: e.target.value })}>{["explicit_only", "explicit_facts", "off"].map(name => <option key={name}>{name}</option>)}</select></label>
      {[["max_output_tokens", tr("Response token limit")], ["max_parallel_tasks", tr("Concurrent tasks")], ["transcript_retention_days", tr("Transcript retention (days)")], ["operation_log_retention_days", tr("Operation retention (days)")]].map(([key, label]) => <label key={key}>{label}<input type="number" min="1" value={value(key)} onChange={e => setChanges({ ...changes, [key]: Number(e.target.value) })} /></label>)}
      {[["phone_stt_model", tr("Transcription model")], ["phone_tts_model", tr("Speech model")], ["phone_tts_voice", tr("Synthetic voice")]].map(([key, label]) => <label key={key}>{label}<input value={value(key)} onChange={e => setChanges({ ...changes, [key]: e.target.value })} /></label>)}
    </details>
    <button className="btn primary" disabled={busy || !revision || !Object.keys(changes).length} onClick={save}>{tr("Save on core")}</button>
    <button className="btn" disabled={busy} onClick={() => void load().catch(e => notify(e.message))}>{tr("Reload settings")}</button>
    <button className="btn" disabled={busy} onClick={async () => { setBusy(true); try { const result = await post("/models/test", { profile: "cloud" }); notify(JSON.stringify(result)); } catch (e: any) { notify(e.message); } finally { setBusy(false); } }}>{tr("Test model and tools · uses API")}</button>
  </section>;
}

function RemoteVoice({ notify }: { notify: (s: string) => void }) {
  const alive = useRef(true);
  const startingRecording = useRef(false);
  const [recording, setRecording] = useState(false), [busy, setBusy] = useState(false), [text, setText] = useState("");
  const recordingRef = useRef(false), [taskId, setTaskId] = useState(""), [answer, setAnswer] = useState("");
  const playback = useRef<HTMLAudioElement | null>(null), playbackURL = useRef("");
  const recorder = useRef<MediaRecorder | null>(null), chunks = useRef<Blob[]>([]), started = useRef(0), timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; if (timer.current) clearTimeout(timer.current); recorder.current?.stream.getTracks().forEach(t => t.stop()); if (Capacitor.isNativePlatform() && recordingRef.current) void nativePlugin.stopRecording().catch(() => {}); playback.current?.pause(); if (playbackURL.current) URL.revokeObjectURL(playbackURL.current); }; }, []);
  useEffect(() => {
    if (!taskId) return;
    const timer = setInterval(() => { void api("/tasks/" + taskId + "/detail").then(result => {
      if (["succeeded", "failed", "cancelled"].includes(result.task.state)) { setAnswer(result.task.result || result.task.error || tr("Task completed.")); clearInterval(timer); }
    }).catch(e => { notify(e.message); clearInterval(timer); }); }, 1000);
    return () => clearInterval(timer);
  }, [taskId]);
  async function start() {
    if (startingRecording.current || recordingRef.current) return;
    startingRecording.current = true;
    setBusy(true);
    try {
      if ((await api("/status")).emergency_stop) throw new Error(tr("Emergency stop is active."));
      if (!alive.current) return;
      playback.current?.pause();
      if (Capacitor.isNativePlatform()) { await nativePlugin.startRecording(); if (!alive.current) { await nativePlugin.stopRecording(); return; } }
      else {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        if (!alive.current) { stream.getTracks().forEach(track => track.stop()); return; }
        const r = new MediaRecorder(stream); recorder.current = r; chunks.current = [];
        r.ondataavailable = e => { if (e.data.size) chunks.current.push(e.data); };
        r.start();
      }
      started.current = Date.now(); recordingRef.current = true; setRecording(true); timer.current = setTimeout(() => void stop(), 60_000);
    } catch (e: any) { notify(e.message); }
    finally { startingRecording.current = false; if (alive.current) setBusy(false); }
  }
  async function stop() {
    if (timer.current) clearTimeout(timer.current);
    setBusy(true);
    try {
      let payload;
      if (Capacitor.isNativePlatform()) payload = await nativePlugin.stopRecording();
      else {
        const r = recorder.current!;
        await new Promise<void>(resolve => { r.onstop = () => resolve(); r.stop(); });
        const blob = new Blob(chunks.current, { type: r.mimeType }); r.stream.getTracks().forEach(t => t.stop());
        const content = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onerror = reject; reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.readAsDataURL(blob); });
        payload = { content, mime: blob.type, seconds: Math.min(60, (Date.now() - started.current) / 1000) };
      }
      recordingRef.current = false; setRecording(false);
      const audio = await canonicalAudio(payload);
      if (!alive.current) return;
      const result = await remoteClient.json("voice/transcribe", audio);
      if (alive.current) setText(result.text);
    } catch (e: any) { recordingRef.current = false; setRecording(false); notify(e.message); }
    finally { setBusy(false); }
  }
  return <section className="remote-form"><p>{tr("Explicit recording up to one minute. Transcription uses the core provider and budget.")}</p>
    <button className="btn primary" disabled={busy} onClick={() => void (recording ? stop() : start())}>{recording ? <Square size={16} /> : <Mic size={16} />}{recording ? tr("Stop and transcribe") : tr("Record request")}</button>
    <label>{tr("Transcribed request · you can edit it")}<textarea rows={5} value={text} onChange={e => setText(e.target.value)} /></label>
    <button className="btn" disabled={!text.trim() || busy} onClick={async () => { try { const session = await api("/voice/session"); const task = await post("/chat", { text, scope: session.scope, private: session.private, privacy_revision: session.revision, channel: "voice", request_id: crypto.randomUUID() }); setTaskId(task.id); setAnswer(""); setText(""); notify(tr("Request sent. The result will be available in tasks.")); } catch (e: any) { notify(e.message); } }}>{tr("Send to Jarvis")}</button>
    {answer && <><p>{answer}</p><button className="btn" disabled={busy || recording} onClick={async () => { setBusy(true); try {
      const result = await remoteClient.json("voice/speak", { text: answer.slice(0, 4000) });
      if (!alive.current) return;
      playback.current?.pause(); if (playbackURL.current) URL.revokeObjectURL(playbackURL.current);
      playbackURL.current = URL.createObjectURL(new Blob([Uint8Array.from(atob(result.content), c => c.charCodeAt(0))], { type: result.mime }));
      playback.current = new Audio(playbackURL.current); await playback.current.play();
    } catch (e: any) { notify(e.message); } finally { setBusy(false); } }}>{tr("Read response · uses API")}</button><button className="btn" onClick={() => playback.current?.pause()}>{tr("Stop voice")}</button></>}
  </section>;
}

function PushRegistration({ notify, automatic = false }: { notify: (s: string) => void; automatic?: boolean }) {
  const listeners = useRef<{ remove(): Promise<void> }[]>([]);
  const started = useRef(false);
  useEffect(() => {
    if (automatic && Capacitor.isNativePlatform()) void PushNotifications.checkPermissions().then(permission => {
      if (permission.receive === "granted") void register(false);
    }).catch(() => {});
  }, []);
  useEffect(() => () => { for (const listener of listeners.current) void listener.remove(); }, []);
  async function register(requestPermission = true) {
    try {
      if (!automatic) { window.dispatchEvent(new Event("jarvis-enable-push")); return; }
      if (started.current) return;
      const permission = await (requestPermission ? PushNotifications.requestPermissions() : PushNotifications.checkPermissions());
      if (permission.receive !== "granted") throw new Error(tr("Notification permission was not granted."));
      started.current = true;
      listeners.current.push(await PushNotifications.addListener("registration", async token => {
        try { const result = await remoteClient.json("push", { platform: Capacitor.getPlatform(), token: token.value }); if (requestPermission) notify(result.provider_configured ? tr("Device registered for notifications.") : tr("Token saved. Configure APNs or FCM on the core to send notifications.")); }
        catch (e: any) { notify(e.message); }
      }));
      listeners.current.push(await PushNotifications.addListener("registrationError", () => { started.current = false; notify(tr("Push registration failed. Check the distribution configuration.")); }));
      listeners.current.push(await PushNotifications.addListener("pushNotificationActionPerformed", () => window.dispatchEvent(new Event("jarvis-remote-open-tasks"))));
      await PushNotifications.register();
    } catch (e: any) { notify(e.message); }
  }
  useEffect(() => {
    if (!automatic) return;
    const enable = () => { void register(); };
    window.addEventListener("jarvis-enable-push", enable);
    return () => window.removeEventListener("jarvis-enable-push", enable);
  }, []);
  return automatic || !Capacitor.isNativePlatform() ? null : <button className="btn" onClick={() => void register()}>{tr("Enable push notifications")}</button>;
}
