import React, { useEffect, useRef, useState } from "react";
import { api, post, type Json } from "./api";
import { Modal, SectionTitle, formatDate } from "./components";
import { t as tr, useI18n } from "./i18n";
import { healthMetrics, iosHealth, type HealthMetric, type HealthSnapshot } from "./appleHealthNative";

export type HealthAttachment = { id: string; name: string };

export default function AppleHealth({ scope, privateMode, privacyRevision, notify, onAsk, onAttach }: {
  scope: string; privateMode: boolean; privacyRevision: number;
  notify: (message: string, error?: boolean) => void;
  onAsk?: (prompt: string) => void;
  onAttach?: (attachment: HealthAttachment | null) => void;
}) {
  useI18n();
  const [status, setStatus] = useState<Json>({});
  const [summary, setSummary] = useState<Json | null>(null);
  const [days, setDays] = useState(90);
  const [metric, setMetric] = useState("steps");
  const [start, setStart] = useState(new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10));
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [remove, setRemove] = useState(false);
  const [nativeAvailable, setNativeAvailable] = useState(false);
  const [nativeDays, setNativeDays] = useState(7);
  const [selected, setSelected] = useState<HealthMetric[]>(["steps", "sleep_minutes"]);
  const [preview, setPreview] = useState<{ snapshot: HealthSnapshot; revision: number } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    if (!onAttach && iosHealth.supported()) void iosHealth.available().then(value => { if (alive.current) setNativeAvailable(value); }).catch(() => {});
    const discard = () => { if (document.visibilityState === "hidden") setPreview(null); };
    document.addEventListener("visibilitychange", discard);
    return () => {
      alive.current = false;
      document.removeEventListener("visibilitychange", discard);
      if (!onAttach && iosHealth.supported()) void iosHealth.cancel().catch(() => {});
    };
  }, []);
  useEffect(() => {
    if (!preview) return;
    const timer = window.setTimeout(() => setPreview(null), 15 * 60_000);
    return () => window.clearTimeout(timer);
  }, [preview]);
  const context = { scope, privacy_revision: privacyRevision, revision: status.revision || 0, allow_cloud: !!status.allow_cloud };
  async function refresh() { const result = await api("/apple-health?scope=personal"); if (alive.current) setStatus(result); }
  useEffect(() => {
    const controller = new AbortController();
    if (scope === "personal") api("/apple-health?scope=personal", { signal: controller.signal }).then(setStatus).catch(e => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope]);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try { await action(); if (alive.current) await refresh(); } catch (e: any) { if (alive.current) notify(e.message, true); } finally { if (alive.current) setBusy(false); }
  }
  const confirmRemoval = <>
    <p>{tr("Delete imported health summaries and revoke cloud access? Existing conversations keep their normal history retention.")}</p>
    <div className="assistant-actions">
      <button className="btn primary" disabled={busy} onClick={() => void run(async () => {
        await api("/apple-health", { method: "DELETE", body: JSON.stringify(context) });
        if (alive.current) {
          setRemove(false);
          setSummary(null);
          onAttach?.(null);
        }
      })}>{tr("Delete")}</button>
      {onAttach && <button className="btn" disabled={busy} onClick={() => setRemove(false)}>{tr("Cancel")}</button>}
    </div>
  </>;
  return <div className={onAttach ? "health-page" : "page assistant-page health-page"}>
    {!onAttach && <SectionTitle eyebrow={tr("PERSONAL DATA")} title={tr("Apple Health")}
      description={tr("Read selected Apple Health categories on iPhone or import an export to inspect daily summaries.")} />}
    {scope !== "personal" ? <p>{tr("Apple Health is available only in the personal scope.")}</p> : <>
      {!onAttach && iosHealth.supported() && <section className="assistant-card assistant-form">
        <h2>{tr("Connect Apple Health on this iPhone")}</h2>
        <p>{tr("Choose categories and allow read access in the iOS permission sheet. Daily summaries stay on this iPhone until you press Share with Jarvis.")}</p>
        <div className="health-categories">{healthMetrics.map(value => <label className="health-consent" key={value}>
          <input type="checkbox" checked={selected.includes(value)} disabled={busy || privateMode} onChange={e => {
            setPreview(null);
            setSelected(current => e.target.checked ? [...current, value] : current.filter(item => item !== value));
          }} /> {tr(value)}
        </label>)}</div>
        <label>{tr("Read the last (days)")}<input type="number" min={1} max={90} disabled={busy || privateMode} value={nativeDays} onChange={e => { setNativeDays(Number(e.target.value)); setPreview(null); }} /></label>
        <button className="btn primary" disabled={!nativeAvailable || busy || privateMode || !selected.length || !Number.isInteger(nativeDays) || nativeDays < 1 || nativeDays > 90} onClick={() => void run(async () => {
          setPreview(null);
          const revision = status.revision || 0;
          const snapshot = await iosHealth.read(selected, nativeDays);
          if (alive.current && document.visibilityState !== "hidden") setPreview({ snapshot, revision });
        })}>{tr("Read and preview on iPhone")}</button>
        {!nativeAvailable && <p>{tr("Apple Health is unavailable on this device or this companion needs updating.")}</p>}
        <p>{tr("iOS does not reveal which read permissions were denied. Empty categories may mean missing data or restricted access. Manage permissions in Health → profile → Apps → Jarvis.")}</p>
        {preview && <>
          <h3>{tr("Local preview · not shared yet")}</h3>
          <p>{preview.snapshot.first_date} — {preview.snapshot.last_date} · {preview.snapshot.timezone} · {preview.snapshot.rows.length} {tr("daily groups")}</p>
          <div className="health-preview"><table><thead><tr><th>{tr("Date")}</th><th>{tr("Metric")}</th><th>{tr("Source")}</th><th>{tr("Value")}</th></tr></thead><tbody>
            {preview.snapshot.rows.map((row, i) => <tr key={i}><td>{row.date}</td><td>{tr(row.metric)}</td><td>{row.source}</td><td>{row.value} {row.unit}</td></tr>)}
          </tbody></table></div>
          {!preview.snapshot.rows.length && <p>{tr("No readable samples in the selected categories and period. Existing summaries on the core have not changed.")}</p>}
          <p>{tr("Sharing replaces the previous summary on your core. Only these daily groups are sent. Refresh manually to include new data; there is no background sharing.")}</p>
          <div className="assistant-actions">
            <button className="btn primary" disabled={busy || privateMode || !preview.snapshot.rows.length} onClick={() => void run(async () => {
              const value = preview;
              setPreview(null);
              await post("/apple-health/native", { scope, privacy_revision: privacyRevision, revision: value.revision, snapshot: value.snapshot });
              setSummary(null);
              notify(tr("Health summaries shared with your core."));
            })}>{tr("Share with Jarvis")}</button>
            <button className="btn" disabled={busy} onClick={() => setPreview(null)}>{tr("Discard preview")}</button>
          </div>
        </>}
      </section>}
      <section className="assistant-card assistant-form">
        <h2>{tr("Import an export")}</h2>
        <p>{tr("On iPhone: Health → profile picture → Export All Health Data. Choose the exported ZIP or export.xml here.")}</p>
        <p>{tr("The raw export is processed in an isolated worker and discarded. Importing replaces the previous summary. Direct HealthKit sharing is available in the iOS companion.")}</p>
        <label>{tr("Import the last (days)")}<input type="number" min={1} max={365} disabled={busy || privateMode} value={days} onChange={e => setDays(Number(e.target.value))} /></label>
        <label>{tr("Apple Health export (XML or ZIP, up to 64 MB)")}<input type="file" accept=".zip,.xml" disabled={busy || privateMode} onChange={e => {
          const file = e.target.files?.[0]; e.target.value = "";
          if (!file) return;
          void run(async () => {
            if (file.size > 64_000_000) throw new Error("Choose an Apple Health export of at most 64 MB.");
            const body = new FormData(); body.append("export", file);
            const imported = await api("/apple-health/import?" + new URLSearchParams({ scope, privacy_revision: String(privacyRevision), days: String(days) }), { method: "POST", body });
            if (alive.current) {
              setSummary(null);
              onAttach?.({ id: imported.id, name: file.name });
            }
          });
        }} /></label>
        {privateMode && <p>{tr("Health imports and settings changes are unavailable in a private session.")}</p>}
        {status.imported_at && <p>{tr("Imported")}: {formatDate(status.imported_at)} · {status.first_date} — {status.last_date} · {status.source}</p>}
        {status.sources?.length > 0 && <p>{tr("Sources")}: {status.sources.join(", ")}</p>}
        <label className="health-consent"><input type="checkbox" checked={!!status.allow_cloud} disabled={busy || privateMode} onChange={e => {
          const allowed = e.target.checked;
          void run(async () => { await post("/apple-health/consent", { ...context, allow_cloud: allowed }); });
        }} /> {tr("Allow health summaries to be sent to cloud models")}</label>
        <p>{tr("Cloud access is disabled by default. Health readings are not automatically added to Second Brain.")}</p>
        <div className="assistant-actions">
          {onAttach && <button className="btn primary" disabled={busy || !status.id} onClick={() => onAttach({ id: status.id, name: tr("Apple Health") })}>{tr("Attach health summary")}</button>}
          <button className="btn" disabled={busy || privateMode || !status.id || remove} onClick={() => setRemove(true)}>{tr("Delete health data")}</button>
        </div>
        {onAttach && remove && <div role="group" aria-label={tr("Delete health data")}>{confirmRemoval}</div>}
      </section>
      {onAsk && <section className="assistant-card assistant-form">
        <label>{tr("Metric")}<select value={metric} onChange={e => setMetric(e.target.value)}>
          {healthMetrics.map(m => <option value={m} key={m}>{tr(m)}</option>)}
        </select></label>
        <label>{tr("From")}<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label>
        <label>{tr("To")}<input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label>
        <div className="assistant-actions">
          <button className="btn primary" disabled={busy || !status.id} onClick={() => void run(async () => {
            setSummary(await api("/apple-health/summary?" + new URLSearchParams({ scope, start, end, metric })));
          })}>{tr("Read summary")}</button>
          <button className="btn" disabled={busy || !status.id} onClick={() => onAsk(tr("Summarize my imported Apple Health readings for this period, cite the source revision and distinguish missing data and overlapping sources:") + " " + start + " — " + end + "; " + metric)}>{tr("Discuss with Jarvis")}</button>
        </div>
        {summary && <>
          {summary.warnings.map((warning: string) => <p key={warning}>{tr(warning)}</p>)}
          <div style={{ overflowX: "auto" }}><table><thead><tr><th>{tr("Date")}</th><th>{tr("Source")}</th><th>{tr("Value")}</th><th>{tr("Aggregation")}</th></tr></thead>
            <tbody>{summary.rows.map((row: Json, i: number) => <tr key={i}><td>{row.date}</td><td>{row.source}</td><td>{row.value} {row.unit}</td><td>{tr(row.aggregation)} ({row.count})</td></tr>)}</tbody></table></div>
          {!summary.rows.length && <p>{tr("No recorded data in this period.")}</p>}
          <small>{summary.source_id} · {tr("Revision")} {summary.revision}</small>
        </>}
      </section>}
      {busy && <p role="status">{tr("Processing health data…")}</p>}
      {!onAttach && remove && <Modal title={tr("Delete health data")} onClose={() => setRemove(false)}>{confirmRemoval}</Modal>}
    </>}
  </div>;
}
