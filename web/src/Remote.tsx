import { t as tr, useI18n } from "./i18n";
import React, { useEffect, useRef, useState } from "react";
import { Mic, Monitor, ShieldCheck, Smartphone, Square } from "lucide-react";
import { Capacitor } from "@capacitor/core";
import { PushNotifications } from "@capacitor/push-notifications";
import { api, post } from "./api";
import { Modal } from "./components";
import { nativePlugin, remoteClient, RemoteSessionExpired } from "./remoteClient";
import "./remote.css";
import { canonicalAudio } from "./remoteAudio";
import RemoteShared from "./RemoteShared";
import { randomId } from "./randomId";
import { companionVoice } from "./companionVoice";
import RemoteAuthorizations from "./RemoteAuthorizations";
import RemoteExecutor, { hasDesktopExecutor } from "./RemoteExecutor";

type Values = Record<string, any>;

export default function RemoteBootstrap({ children }: { children: React.ReactNode }) {
  useI18n();
  const [ready, setReady] = useState(false), [remote, setRemote] = useState(false), [connected, setConnected] = useState(false);
  const [retryConnection, setRetryConnection] = useState(false);
  const [error, setError] = useState(""), [address, setAddress] = useState(""), [code, setCode] = useState(""), [name, setName] = useState(tr("My device")), [busy, setBusy] = useState(false);
  async function initialize() {
    try {
      const enabled = await remoteClient.initialize();
      setRemote(enabled); setConnected(remoteClient.authenticated);
      setError(""); setRetryConnection(false);
      setAddress(remoteClient.credentials?.server_url || (remoteClient.vault ? "" : location.origin));
    } catch (e: any) {
      setRemote(true); setConnected(false); setError(e.message);
      setRetryConnection(!(e instanceof RemoteSessionExpired));
      setAddress(remoteClient.credentials?.server_url || "");
    }
    finally { setReady(true); }
  }
  useEffect(() => {
    void initialize();
    const logout = (event: Event) => { setConnected(false); setRetryConnection(false); setError((event as CustomEvent).detail?.revoked === false ? tr("Local credentials removed. The core could not confirm revocation; revoke this device from another administrator companion.") : ""); };
    const expired = () => { setConnected(false); setRetryConnection(false); setError(tr("Session expired or revoked. Pair this device again.")); };
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
  if (!connected && retryConnection) return <main className="connect-screen remote-connect">
    <ShieldCheck size={42} aria-hidden="true" />
    <h1>{tr("Your Jarvis, everywhere.")}</h1>
    <p role="alert">{tr(error)}</p>
    <button className="btn primary" onClick={() => { setReady(false); void initialize(); }}>{tr("Retry existing connection")}</button>
  </main>;
  if (!connected) return <main className="connect-screen remote-connect">
    <ShieldCheck size={42} aria-hidden="true" />
    <h1>{tr("Your Jarvis, everywhere.")}</h1><p>{tr("Connect this device to your core with a single-use pairing code.")}</p>
    <form onSubmit={pair}>
      <label>{tr("Jarvis server")}<input type="url" required placeholder="https://jarvis.example.com" value={address} onChange={e => setAddress(e.target.value)} autoCapitalize="none" autoCorrect="off" /></label>
      <label>{tr("Device name")}<input required maxLength={80} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>{tr("Pairing code")}<input type="password" required value={code} onChange={e => setCode(e.target.value)} autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} /></label>
    {error && <p role="alert">{tr(error)}</p>}
      <button className="btn primary" type="submit" disabled={busy}>{busy ? tr("Connecting…") : tr("Connect device")}</button>
    </form>
    <small>{tr("Use a companion code issued by the owner. Configure model API keys on the core after connecting.")}</small>
  </main>;
  return <div className="remote-shell"><RemoteTools />{children}</div>;
}

function RemoteTools() {
  const [panel, setPanel] = useState(false), [message, setMessage] = useState("");
  useEffect(() => {
    void companionVoice.attach().catch(error => setMessage(error.message));
    const open = () => { void companionVoice.control("listen").catch(error => setMessage(error.message)); };
    const record = () => { void companionVoice.stop(false); setPanel(true); };
    const stop = () => { setPanel(false); void companionVoice.stop(); };
    const mute = () => { void companionVoice.control("mute").catch(error => setMessage(error.message)); };
    const session = () => { setPanel(false); companionVoice.sessionChanged(); };
    window.addEventListener("jarvis-remote-voice", open);
    window.addEventListener("jarvis-companion-record", record);
    window.addEventListener("jarvis-emergency-stop", stop);
    window.addEventListener("jarvis-companion-mute", mute);
    window.addEventListener("jarvis-session-changed", session);
    return () => {
      companionVoice.detach();
      window.removeEventListener("jarvis-remote-voice", open);
      window.removeEventListener("jarvis-companion-record", record);
      window.removeEventListener("jarvis-emergency-stop", stop);
      window.removeEventListener("jarvis-companion-mute", mute);
      window.removeEventListener("jarvis-session-changed", session);
    };
  }, []);
  return <>
    <RemoteAuthorizations />
    <PushRegistration notify={setMessage} automatic />
    <RemoteShared notify={setMessage} />
    {message && <div className="remote-notice" role="status"><span>{tr(message)}</span><button className="btn ghost" onClick={() => setMessage("")}>{tr("Dismiss")}</button></div>}
    {panel && <Modal title={tr("Talk to Jarvis")} onClose={() => { setPanel(false); companionVoice.sessionChanged(); }}><div className="modal-body remote-panel"><RemoteVoice notify={setMessage} /></div></Modal>}
  </>;
}

export function RemoteConnection({ notify }: { notify: (message: string) => void }) {
  return <><h2>{tr("Remote core")}</h2><p className="remote-path">{remoteClient.credentials?.server_url}</p><p>{tr("This device identity:")} {remoteClient.credentials?.device_id}</p>
    <button className="btn" onClick={async () => { try { await companionVoice.control("mute"); await remoteClient.logout(); } catch (error: any) { notify(error.message); } }}>{tr("Revoke this device and sign out")}</button>
    <PushRegistration notify={notify} /></>;
}

export function RemoteDevices({ notify }: { notify: (s: string) => void }) {
  const [devices, setDevices] = useState<Values[]>([]), [jobs, setJobs] = useState<Values[]>([]), [code, setCode] = useState("");
  const bridge = window.jarvisCompanion;
  const desktopExecutor = hasDesktopExecutor(bridge) ? bridge : null;
  async function refresh() {
    try {
      const [d, j] = await Promise.all([remoteClient.json<Values[]>("devices"), remoteClient.json<Values[]>("jobs")]);
      setDevices(d); setJobs(j);
    } catch (e: any) { notify(e.message); }
  }
  useEffect(() => { void refresh(); const timer = setInterval(() => void refresh(), 5000); return () => clearInterval(timer); }, []);
  async function pairCode(kind: "companion" | "executor", owner = false) {
    try { const result = await remoteClient.json<{ code: string }>("pairing-codes", { kind, owner }); setCode(result.code); }
    catch (e: any) { notify(e.message); }
  }

  const pairingCodes = <>
    <div className="assistant-actions">
      <button className="btn" onClick={() => pairCode("companion")}>{tr("Companion code")}</button>
      <button className="btn" onClick={() => pairCode("companion", true)}>{tr("Administrator code")}</button>
      <button className="btn" onClick={() => pairCode("executor")}>{tr("Executor code for another computer")}</button>
    </div>
    {code && <label>{tr("Single-use code · expires in 10 minutes")}<input readOnly value={code} onFocus={e => e.currentTarget.select()} autoComplete="off" /></label>}
  </>;

  return <>
    {desktopExecutor && <RemoteExecutor bridge={desktopExecutor} onChange={refresh} />}
    {devices.length > 0 && <h3>{tr("Paired devices")}</h3>}
    {devices.map(device => <article className="remote-device" key={device.id}>
      <strong>{device.kind === "executor" ? <Monitor size={16} /> : <Smartphone size={16} />} {device.name}</strong>
      <span>{device.platform} · {device.revoked ? tr("Revoked") : device.kind === "executor" ? device.connected ? tr("Connected") : tr("Disconnected") : tr("Paired")}</span>
      {device.capabilities?.workspaces?.map((w: Values) => <small key={w.id}>{w.label} · {w.scope} {tr("· read")} {w.read ? tr("yes") : tr("no")}{tr(", write")} {w.write ? tr("yes") : tr("no")}{tr(", commands")} {w.command ? tr("yes") : tr("no")}</small>)}
      {device.capabilities?.native?.length > 0 && <small>{device.capabilities.native.join(", ")} · {device.capabilities.native_scope}</small>}
      {!device.revoked && device.kind === "executor" && <button className="btn" onClick={async () => { try { await remoteClient.json("session/executor", { device_id: device.id }); window.dispatchEvent(new Event("jarvis-session-changed")); notify(tr("Device selected for this conversation.")); } catch (e: any) { notify(e.message); } }}>{tr("Use in this conversation")}</button>}
      {!device.revoked && remoteClient.admin && <button className="btn" onClick={async () => { try { await remoteClient.json("devices/" + device.id + "/revoke", {}); await refresh(); } catch (e: any) { notify(e.message); } }}>{tr("Revoke")}</button>}
    </article>)}
    {remoteClient.admin && <section>
      {desktopExecutor ? <details className="executor-options">
        <summary>{tr("Pair another device")}</summary>
        {pairingCodes}
      </details> : <>
        <h3>{tr("Pair a device")}</h3>
        {pairingCodes}
      </>}
    </section>}
    <h3>{tr("Desktop jobs")}</h3>{!jobs.length && <p>{tr("No jobs. Request operations in chat after pairing an executor.")}</p>}
    {jobs.map(job => <article className="remote-device" key={job.id}><strong>{job.operation}</strong><span>{job.state}</span><small>{job.id}</small>{job.state === "unknown" && <><p>{tr("Verify the outcome on the device. Reconcile it before repeating the operation.")}</p>{job.task_id && <button className="btn" onClick={() => window.dispatchEvent(new Event("jarvis-remote-open-tasks"))}>{tr("Review task")}</button>}</>}{["queued", "delivered", "claimed", "running"].includes(job.state) && <button className="btn" onClick={async () => { try { await remoteClient.json("jobs/" + job.id + "/cancel", {}); await refresh(); } catch (e: any) { notify(e.message); } }}>{tr("Cancel")}</button>}</article>)}
  </>;
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
    <button className="btn" disabled={!text.trim() || busy} onClick={async () => { try { const session = await api("/voice/session"); const task = await post("/chat", { text, scope: session.scope, private: session.private, privacy_revision: session.revision, channel: "voice", request_id: randomId() }); setTaskId(task.id); setAnswer(""); setText(""); notify(tr("Request sent. The result will be available in tasks.")); } catch (e: any) { notify(e.message); } }}>{tr("Send to Jarvis")}</button>
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
