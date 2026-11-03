import React, { useEffect, useState } from "react";
import { CalendarDays, RefreshCw, Save } from "lucide-react";
import { api, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, SectionTitle, formatDate } from "./components";

type Props = {
  scope: string;
  privateMode: boolean;
  privacyRevision: number;
  notify: (message: string, error?: boolean) => void;
  onAsk: (prompt: string) => void;
};

export default function Today({ scope, privateMode, privacyRevision, notify, onAsk }: Props) {
  useI18n();
  const [data, setData] = useState<Json | null>(null);
  const [prefs, setPrefs] = useState<Json | null>(null);
  const [priorities, setPriorities] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    Promise.all([
      api("/today?scope=" + scope, { signal: controller.signal }),
      api("/today/preferences?scope=" + scope, { signal: controller.signal }),
    ]).then(([overview, settings]) => {
      if (controller.signal.aborted) return;
      setData(overview);
      setPrefs(settings);
      setPriorities(settings.priorities.join("\n"));
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [scope, refresh, privacyRevision]);

  async function save() {
    if (!prefs) return;
    setBusy(true);
    try {
      const result = await api("/today/preferences", {
        method: "PUT",
        body: JSON.stringify({
          ...prefs, scope, privacy_revision: privacyRevision,
          priorities: priorities.split("\n").map((x) => x.trim()).filter(Boolean),
        }),
      });
      setPrefs(result);
      setRefresh((x) => x + 1);
      notify("Today settings saved.");
    } catch (e: any) { notify(e.message, true); }
    finally { setBusy(false); }
  }
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("YOUR DAY")} title={tr("Today")}
      description={tr("Priorities, commitments and work in the selected scope.")}
      action={<button className="btn" onClick={() => setRefresh((x) => x + 1)}><RefreshCw size={15} />{tr("Refresh")}</button>} />
    {error && <p role="alert">{tr(error)}</p>}
    {!data && !error && <p role="status">{tr("Loading…")}</p>}
    {data && <>
      <p>{data.date} · {data.timezone} · <Badge>{tr(scope)}</Badge></p>
      <div className="assistant-actions">
        <button className="btn primary" onClick={() => onAsk(tr("Prepare my daily briefing from my priorities, calendar, reminders and activities. Flag incomplete information and suggest next steps without making changes."))}>{tr("Brief me")}</button>
        <button className="btn" onClick={() => onAsk(tr("Help me prepare for my next meeting: check my agenda and relevant earlier decisions, summarize the context and open questions, and give me a preparation checklist. Do not change records or send messages."))}><CalendarDays size={15} />{tr("Prepare next meeting")}</button>
        <button className="btn" onClick={() => onAsk(tr("Prepare my evening recap: distinguish completed work from open activities and suggest priorities for tomorrow. Flag incomplete information without changing anything."))}>{tr("Evening recap")}</button>
      </div>
      <div className="assistant-grid">
        <section className="assistant-card">
          <h2>{tr("Outstanding activities")}</h2>
          {(data.organizer?.activities || []).filter((item: Json) => item.state !== "completed").slice(0, 10).map((item: Json) => <article key={item.id}><strong>{item.title}</strong>{item.due_at && <p>{formatDate(item.due_at)} {item.overdue && tr("Overdue")}</p>}</article>)}
          <h2>{tr("Calendar")}</h2>
          <p>{tr("Source status")}: {tr(data.calendar.state || "available")}</p>
          {(data.calendar.analysis?.state === "partial" || data.calendar.partial || data.calendar.truncated) && <p role="status">{tr("Calendar coverage is incomplete. Availability cannot be guaranteed.")}</p>}
          {!!data.calendar.analysis?.conflicts?.length && <p role="status">{tr("Overlapping commitments need attention.")}</p>}
          {(data.calendar.events || []).map((event: Json, i: number) => <article key={i}>
            <strong>{event.title}</strong><p>{event.all_day ? tr("All day") : formatDate(event.start)}{event.end && " — " + formatDate(event.end)}</p>
          </article>)}
          {!data.calendar.events?.length && <p>{tr("No events returned by this source.")}</p>}
        </section>
        <section className="assistant-card">
          <h2>{tr("Weather")}</h2>
          <p>{tr("Source status")}: {tr(data.weather.state || "available")}</p>
          {data.weather.current?.temperature_2m != null && <p>{data.weather.current.temperature_2m} °C</p>}
          <h2>{tr("Reminders")}</h2>
          {data.reminders.map((item: Json) => <article key={item.id}><strong>{item.title}</strong><p>{formatDate(item.next_run_at)}</p></article>)}
          {!data.reminders.length && <p>{tr("No reminders due today.")}</p>}
          <h2>{tr("Recent work")}</h2>
          {data.work.map((item: Json) => <article key={item.id}><strong>{item.title}</strong> <Badge>{tr(item.state)}</Badge></article>)}
        </section>
      </div>
    </>}
    {prefs && <form className="assistant-card assistant-form" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <h2>{tr("Priorities and briefings")}</h2>
      <label>{tr("Three priorities, one per line")}<textarea value={priorities} maxLength={902} onChange={(e) => setPriorities(e.target.value)} disabled={privateMode || busy} /></label>
      <div className="assistant-actions">
        {(["calendar", "weather", "morning", "evening"] as const).map((field) => <label key={field}>
          <input type="checkbox" checked={prefs[field]} disabled={privateMode || busy} onChange={(e) => setPrefs({ ...prefs, [field]: e.target.checked })} />
          {tr({ calendar: "Include calendar", weather: "Include weather", morning: "Morning briefing", evening: "Evening briefing" }[field])}
        </label>)}
      </div>
      <div className="assistant-actions">
        <label>{tr("Morning time")}<input type="time" value={prefs.morning_time} disabled={privateMode || busy} onChange={(e) => setPrefs({ ...prefs, morning_time: e.target.value })} /></label>
        <label>{tr("Evening time")}<input type="time" value={prefs.evening_time} disabled={privateMode || busy} onChange={(e) => setPrefs({ ...prefs, evening_time: e.target.value })} /></label>
        <label>{tr("Delivery")}<select value={prefs.delivery} disabled={privateMode || busy} onChange={(e) => setPrefs({ ...prefs, delivery: e.target.value })}>
          <option value="desktop">{tr("Desktop")}</option><option value="voice">{tr("Voice")}</option>
        </select></label>
      </div>
      <p>{tr("Briefings run only while Jarvis is awake. Missed briefings are skipped. Connected calendar accounts are shared sources.")}</p>
      {privateMode && <p>{tr("Leave the private session to save persistent changes.")}</p>}
      <button className="btn primary" disabled={privateMode || busy}><Save size={15} />{tr("Save changes")}</button>
    </form>}
  </div>;
}
