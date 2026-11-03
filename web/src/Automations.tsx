import React, { useEffect, useState } from "react";
import { api, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, Modal, SectionTitle, formatDate } from "./components";

const defaults = { title: "", source: "calendar", event: "changed", target: "", query: "", interval_seconds: 300, cooldown_seconds: 900, lead_minutes: 30, action: "notify", prompt: "", delivery: "desktop", enabled: true };
export default function Automations({ scope, privateMode, privacyRevision, notify, onAsk }: {
  scope: string; privateMode: boolean; privacyRevision: number; notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [data, setData] = useState<Json>({ rules: [], events: [] });
  const [edit, setEdit] = useState<Json | null>(null);
  const [preview, setPreview] = useState<Json | null>(null);
  const [deleting, setDeleting] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const context = { scope, privacy_revision: privacyRevision };
  useEffect(() => {
    const controller = new AbortController();
    const load = () => api("/automations?scope=" + scope, { signal: controller.signal }).then(setData).catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    load();
    const timer = setInterval(load, 30000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [scope, refresh]);
  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    try { await work(); setRefresh((x) => x + 1); }
    catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  const save = (rule: Json) => api("/automations" + (rule.id ? "/" + rule.id : ""), { method: rule.id ? "PUT" : "POST", body: JSON.stringify({ ...context, ...Object.fromEntries(Object.keys(defaults).map((key) => [key, rule[key]])), revision: rule.revision }) });
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("WHEN THINGS CHANGE")} title={tr("Automations")}
      description={tr("React to verified changes with notifications or read-only analysis.")}
      action={<button className="btn primary" disabled={privateMode} onClick={() => { setEdit({ ...defaults }); setPreview(null); }}>{tr("New automation")}</button>} />
    <p>{tr("The first check establishes a quiet baseline. Unchanged sources stay quiet. Event history is kept for seven days.")}</p>
    <div className="assistant-grid"><section className="assistant-card">
      <h2>{tr("Rules")}</h2>
      {data.rules.map((row: Json) => <article key={row.id}>
        <strong>{row.title}</strong> <Badge>{tr(row.enabled ? "Enabled" : "Paused")}</Badge><p>{tr(row.config.source)} · {tr(row.config.event)} · {formatDate(row.next_check)}</p>
        {row.error && <p role="status">{tr("Source check failed; the previous baseline is preserved.")} {row.error}</p>}
        <div className="assistant-actions">
          <button className="btn" disabled={privateMode || busy} onClick={() => action(() => save({ ...row.config, id: row.id, revision: row.revision, enabled: !row.enabled }))}>{tr(row.enabled ? "Pause" : "Resume")}</button>
          <button className="btn" disabled={privateMode} onClick={() => { setEdit({ ...row.config, id: row.id, revision: row.revision }); setPreview(null); }}>{tr("Edit")}</button>
          <button className="btn" disabled={privateMode} onClick={() => setDeleting(row)}>{tr("Delete")}</button>
        </div>
      </article>)}
    </section><section className="assistant-card">
      <h2>{tr("Recent source events")}</h2>
      {data.events.map((event: Json) => <article key={event.id}>
        <strong>{data.rules.find((r: Json) => r.id === event.rule_id)?.title || tr("Source changes")}</strong>
        <p>{formatDate(event.created_at)} · {event.data.count} {tr("changes")}</p>
        <details><summary>{tr("Review source data")}</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(event.data, null, 2)}</pre></details>
        <button className="btn" onClick={() => onAsk(tr("Explain automation event {id}. Read its sources and suggest next actions without making changes.", { id: event.id }))}>{tr("Explain this event")}</button>
      </article>)}
    </section></div>
    {edit && <Modal title={tr("Automation rule")} onClose={() => setEdit(null)}><form className="assistant-form" onSubmit={(e) => { e.preventDefault(); action(async () => { await save(edit); setEdit(null); }); }}>
      <label>{tr("Title")}<input required maxLength={200} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></label>
      <label>{tr("Source")}<select value={edit.source} onChange={(e) => setEdit({ ...edit, source: e.target.value, event: "changed", target: "" })}>{["calendar", "directory", "mail", "jira", "github", "home_assistant"].map((x) => <option key={x} value={x}>{tr(x)}</option>)}</select></label>
      <label>{tr("Event condition")}<select value={edit.event} onChange={(e) => setEdit({ ...edit, event: e.target.value })}>{(edit.source === "calendar" ? ["changed", "added", "conflict", "imminent"] : ["changed", "added"]).map((x) => <option key={x} value={x}>{tr(x)}</option>)}</select></label>
      {edit.source !== "calendar" && <label>{tr("Exact source target")}<input required maxLength={1000} value={edit.target} onChange={(e) => setEdit({ ...edit, target: e.target.value })} /><small>{tr("Directory: an authorized workspace path. Mail: account ID. Jira: allowed project key. GitHub: owner/repository.")}</small></label>}
      {["mail", "jira", "github", "home_assistant"].includes(edit.source) && <label>{tr("Source search or Home Assistant JSON arguments")}<input maxLength={500} value={edit.query} onChange={(e) => setEdit({ ...edit, query: e.target.value })} /></label>}
      {(["interval_seconds", "cooldown_seconds", "lead_minutes"] as const).map((field) => <label key={field}>{tr({ interval_seconds: "Check interval (seconds)", cooldown_seconds: "Notification cooldown (seconds)", lead_minutes: "Imminent threshold (minutes)" }[field])}<input type="number" min={field === "lead_minutes" ? 1 : 60} max={field === "lead_minutes" ? 120 : field === "interval_seconds" ? 86400 : 604800} value={edit[field]} onChange={(e) => setEdit({ ...edit, [field]: Number(e.target.value) })} /></label>)}
      <label>{tr("Action")}<select value={edit.action} onChange={(e) => setEdit({ ...edit, action: e.target.value })}><option value="notify">{tr("Notify only")}</option><option value="analyze">{tr("Analyze without changes")}</option></select></label>
      {edit.action === "analyze" && <label>{tr("Owner analysis instruction")}<textarea required maxLength={4000} value={edit.prompt} onChange={(e) => setEdit({ ...edit, prompt: e.target.value })} /></label>}
      <label>{tr("Delivery")}<select value={edit.delivery} onChange={(e) => setEdit({ ...edit, delivery: e.target.value })}><option value="desktop">{tr("Desktop")}</option><option value="voice">{tr("Voice")}</option></select></label>
      <p>{tr("Voice alerts respect quiet hours, mute and lock. Analysis tasks cannot send messages, modify files or change records.")}</p>
      <div className="assistant-actions"><button className="btn" type="button" disabled={busy || privateMode} onClick={() => action(async () => { setPreview(await api("/automations/preview", { method: "POST", body: JSON.stringify({ ...context, ...Object.fromEntries(Object.keys(defaults).map((key) => [key, edit[key]])) }) })); })}>{tr("Preview source")}</button><button className="btn primary" disabled={busy || privateMode}>{tr("Save changes")}</button></div>
      {preview && <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(preview, null, 2)}</pre>}
    </form></Modal>}
    {deleting && <Modal title={tr("Confirm deletion")} onClose={() => setDeleting(null)}><p>{deleting.title}</p><p>{tr("The rule and its local event history will be removed.")}</p><button className="btn primary" disabled={busy} onClick={() => action(async () => { await api("/automations/" + deleting.id, { method: "DELETE", body: JSON.stringify({ ...context, revision: deleting.revision }) }); setDeleting(null); })}>{tr("Delete")}</button></Modal>}
  </div>;
}
