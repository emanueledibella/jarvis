import React, { useEffect, useState } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { api, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, Modal, SectionTitle, formatDate } from "./components";

export const activityFields = (item: Json) => Object.fromEntries(
  ["title", "notes", "state", "priority", "estimated_minutes", "due_at", "project_id", "parent_id", "source_url"].map((key) => [key, item[key]]),
);
const empty = { title: "", notes: "", state: "open", priority: 2, estimated_minutes: null, due_at: null, project_id: null, parent_id: null, source_url: "" };
const localTime = (value: string | null) => value ? new Date(new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "";

export default function Organizer({ scope, privateMode, privacyRevision, notify, onAsk }: {
  scope: string; privateMode: boolean; privacyRevision: number;
  notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [data, setData] = useState<Json>({ activities: [], projects: [] });
  const [edit, setEdit] = useState<Json | null>(null);
  const [project, setProject] = useState<Json | null>(null);
  const [remove, setRemove] = useState<Json | null>(null);
  const [filter, setFilter] = useState("open");
  const [projectFilter, setProjectFilter] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [plan, setPlan] = useState<Json | null>(null);
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");
  const context = { scope, privacy_revision: privacyRevision };
  useEffect(() => {
    const controller = new AbortController();
    api("/organizer?scope=" + scope, { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope, refresh]);
  async function action(work: () => Promise<unknown>) {
    setBusy(true);
    try { await work(); setEdit(null); setProject(null); setRemove(null); setPlan(null); setRefresh((x) => x + 1); }
    catch (e: any) { notify(e.message, true); }
    finally { setBusy(false); }
  }
  function saveActivity(item: Json) {
    return api("/organizer/activities" + (item.id ? "/" + item.id : ""), {
      method: item.id ? "PUT" : "POST",
      body: JSON.stringify({ ...activityFields(item), ...context, revision: item.revision }),
    });
  }
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("PERSONAL ORGANIZATION")} title={tr("Activities and projects")}
      description={tr("Your commitments, separate from work executed by the agent.")}
      action={<button className="btn primary" disabled={privateMode} onClick={() => setEdit({ ...empty })}><Plus size={15} />{tr("New activity")}</button>} />
    {privateMode && <p>{tr("Leave the private session to save persistent changes.")}</p>}
    <div className="assistant-actions">
      <select aria-label={tr("Activity status")} value={filter} onChange={(e) => setFilter(e.target.value)}><option value="open">{tr("Outstanding")}</option><option value="completed">{tr("Completed")}</option><option value="all">{tr("All activities")}</option></select>
      <select aria-label={tr("Project")} value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}><option value="">{tr("All projects")}</option>{data.projects.map((p: Json) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <button className="btn" disabled={privateMode} onClick={() => setProject({ name: "", description: "" })}>{tr("New project")}</button>
      <button className="btn" onClick={() => setRefresh((x) => x + 1)} aria-label={tr("Refresh")}><RefreshCw size={15} /></button>
    </div>
    <div className="assistant-grid">
      <section className="assistant-card">
        <h2>{tr("Activities")}</h2>
        {data.activities.filter((item: Json) => (filter === "all" || (filter === "completed" ? item.state === "completed" : item.state !== "completed")) && (!projectFilter || item.project_id === projectFilter)).map((item: Json) => <article key={item.id}>
          <label><input type="checkbox" aria-label={tr("Select for planning")} checked={selected.includes(item.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} /> {item.title}</label>
          <p><Badge>{tr(item.state)}</Badge> · {tr("Priority")} {item.priority}{item.estimated_minutes && " · " + item.estimated_minutes + " min"}</p>
          {item.due_at && <p className={item.overdue ? "assistant-error" : ""}>{tr("Due")}: {formatDate(item.due_at)} {item.overdue && tr("Overdue")}</p>}
          <div className="assistant-actions">
            <button className="btn" disabled={privateMode || busy} onClick={() => action(() => saveActivity({ ...item, state: item.state === "completed" ? "open" : "completed" }))}>{tr(item.state === "completed" ? "Reopen" : "Complete")}</button>
            <button className="btn" disabled={privateMode} onClick={() => setEdit(item)}>{tr("Edit")}</button>
            <button className="btn" disabled={privateMode} onClick={() => setRemove({ ...item, kind: "activities", cascade: false })}>{tr("Delete")}</button>
          </div>
        </article>)}
      </section>
      <section className="assistant-card assistant-form">
        <h2>{tr("Plan selected activities")}</h2>
        <p>{tr("Uses your estimates and verified calendar coverage. Proposals do not create events.")}</p>
        <label>{tr("Window start (computer time zone)")}<input type="datetime-local" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} /></label>
        <label>{tr("Window end (computer time zone)")}<input type="datetime-local" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} /></label>
        <button className="btn" disabled={busy || !selected.length || !windowStart || !windowEnd} onClick={async () => {
          setBusy(true);
          try { setPlan(await api("/organizer/plan", { method: "POST", body: JSON.stringify({ scope, activity_ids: selected, start: new Date(windowStart).toISOString(), end: new Date(windowEnd).toISOString() }) })); }
          catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
        }}>{tr("Propose work blocks")}</button>
        {plan && <><p>{tr(plan.state === "proposed" ? "Work blocks proposed. Review before adding them to your calendar." : "Complete verified calendar coverage is required to propose free time.")}</p>
          {(plan.proposals || []).map((p: Json) => <article key={p.activity_id}><strong>{p.title}</strong><p>{formatDate(p.start)} — {formatDate(p.end)}</p><button className="btn" onClick={() => onAsk(tr("Review the proposed calendar block for activity {id}, from {start} to {end}. Read its details, recheck my calendar and request authorization before creating an event.", { id: p.activity_id, start: p.start, end: p.end }))}>{tr("Review calendar block")}</button></article>)}
          {!!plan.unscheduled?.length && <p>{tr("Some activities need an estimate or do not fit this window.")}</p>}
        </>}
        <h2>{tr("Projects")}</h2>
        {data.projects.map((p: Json) => <article key={p.id}><strong>{p.name}</strong><div className="assistant-actions"><button className="btn" disabled={privateMode} onClick={() => setProject(p)}>{tr("Edit")}</button><button className="btn" disabled={privateMode} onClick={() => setRemove({ ...p, kind: "projects" })}>{tr("Delete")}</button></div></article>)}
      </section>
    </div>
    {edit && <Modal title={tr(edit.id ? "Edit activity" : "New activity")} onClose={() => setEdit(null)}>
      <form className="assistant-form" onSubmit={(e) => { e.preventDefault(); action(() => saveActivity(edit)); }}>
        <label>{tr("Title")}<input required maxLength={300} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></label>
        <label>{tr("Notes")}<textarea maxLength={8000} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
        <label>{tr("Activity status")}<select value={edit.state} onChange={(e) => setEdit({ ...edit, state: e.target.value })}>{["open", "in_progress", "completed"].map((s) => <option key={s} value={s}>{tr(s)}</option>)}</select></label>
        <label>{tr("Priority")}<input type="number" min={1} max={4} value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: Number(e.target.value) })} /></label>
        <label>{tr("Estimated minutes")}<input type="number" min={5} max={1440} value={edit.estimated_minutes ?? ""} onChange={(e) => setEdit({ ...edit, estimated_minutes: e.target.value ? Number(e.target.value) : null })} /></label>
        <label>{tr("Due time (computer time zone)")}<input type="datetime-local" value={localTime(edit.due_at)} onChange={(e) => setEdit({ ...edit, due_at: e.target.value ? new Date(e.target.value).toISOString() : null })} /></label>
        <label>{tr("Project")}<select value={edit.project_id || ""} onChange={(e) => setEdit({ ...edit, project_id: e.target.value || null })}><option value="">{tr("No project")}</option>{data.projects.map((p: Json) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>{tr("Parent activity")}<select value={edit.parent_id || ""} onChange={(e) => setEdit({ ...edit, parent_id: e.target.value || null })}><option value="">{tr("No parent")}</option>{data.activities.filter((a: Json) => a.id !== edit.id).map((a: Json) => <option key={a.id} value={a.id}>{a.title}</option>)}</select></label>
        <label>{tr("Source link")}<input type="url" value={edit.source_url} onChange={(e) => setEdit({ ...edit, source_url: e.target.value })} /></label>
        <button className="btn primary" disabled={busy}>{tr("Save changes")}</button>
      </form>
    </Modal>}
    {project && <Modal title={tr("Project")} onClose={() => setProject(null)}><form className="assistant-form" onSubmit={(e) => { e.preventDefault(); action(() => api("/organizer/projects" + (project.id ? "/" + project.id : ""), { method: project.id ? "PUT" : "POST", body: JSON.stringify({ ...context, name: project.name, description: project.description, revision: project.revision }) })); }}>
      <label>{tr("Name")}<input required maxLength={160} value={project.name} onChange={(e) => setProject({ ...project, name: e.target.value })} /></label>
      <label>{tr("Description")}<textarea maxLength={2000} value={project.description} onChange={(e) => setProject({ ...project, description: e.target.value })} /></label>
      <button className="btn primary" disabled={busy}>{tr("Save changes")}</button>
    </form></Modal>}
    {remove && <Modal title={tr("Confirm deletion")} onClose={() => setRemove(null)}>
      <p>{remove.title || remove.name}</p><p>{tr(remove.kind === "projects" ? "Activities are kept and unassigned from this project." : "This removes the activity permanently.")}</p>
      {remove.kind === "activities" && <label><input type="checkbox" checked={remove.cascade} onChange={(e) => setRemove({ ...remove, cascade: e.target.checked })} />{tr("Also delete all subtasks")}</label>}
      <button className="btn primary" disabled={busy} onClick={() => action(() => api("/organizer/" + remove.kind + "/" + remove.id, { method: "DELETE", body: JSON.stringify({ ...context, revision: remove.revision, cascade: !!remove.cascade }) }))}>{tr("Delete")}</button>
    </Modal>}
  </div>;
}
