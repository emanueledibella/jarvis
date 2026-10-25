import React, { useState, useEffect } from "react";
import {
  CalendarClock,
  Check,
  ChevronRight,
  Clock3,
  Code2,
  ExternalLink,
  FileText,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  Search,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { api, patch, post, type Json } from "./api";
import {
  Badge,
  Empty,
  Field,
  Modal,
  SectionTitle,
  Text,
  Toggle,
  formatDate,
  profileLabels,
} from "./components";

type Props = {
  tasks: Json[];
  schedules: Json[];
  approvals: Json[];
  refresh: () => void;
  notify: (message: string, error?: boolean) => void;
};
export function Tasks({ tasks, approvals, refresh, notify }: Props) {
  const [selected, setSelected] = useState<Json | null>(null),
    [detail, setDetail] = useState<Json>({ events: [], effects: [] });
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const timer = setInterval(
      () =>
        api("/tasks/" + selected.id + "/detail")
          .then((data) => {
            if (active) {
              setDetail(data);
              setSelected(data.task);
            }
          })
          .catch(() => {}),
      2000,
    );
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selected?.id]);
  async function open(task: Json) {
    setSelected(task);
    try {
      const data = await api("/tasks/" + task.id + "/detail");
      setDetail(data);
      setSelected(data.task);
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  async function action(task: Json, operation: string) {
    try {
      await post("/tasks/" + task.id + "/" + operation);
      refresh();
      setSelected(null);
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  async function decision(id: string, approved: boolean) {
    try {
      await post("/approvals/" + id, { approved });
      refresh();
      setSelected(null);
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  const active = tasks.filter((t) =>
    ["running", "queued", "waiting_user"].includes(t.state),
  );
  return (
    <div className="page">
      <SectionTitle
        eyebrow="FROM PLAN TO RESULT"
        title="Tasks"
        description={`${active.length} open tasks. Every action has a verifiable state.`}
      />
      {!!approvals.length && (
        <section className="attention-section">
          <h2>Your decisions</h2>
          {approvals.map((a) => (
            <div className="approval-card" key={a.id}>
              <div>
                <Badge state="waiting_user" />
                <h3>{a.tool}</h3>
                <pre>{JSON.stringify(a.arguments, null, 2)}</pre>
                <small>Valid until {formatDate(a.expires_at, true)}</small>
              </div>
              <div className="button-row">
                <button className="btn" onClick={() => decision(a.id, false)}>
                  Reject
                </button>
                <button
                  className="btn primary"
                  onClick={() => decision(a.id, true)}
                >
                  <Check size={14} />
                  Approve this action
                </button>
              </div>
            </div>
          ))}
        </section>
      )}
      {tasks.length ? (
        <div className="task-list">
          {tasks.map((t) => (
            <button className="task-row" key={t.id} onClick={() => open(t)}>
              <div className="task-icon">
                {t.state === "running" ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <Workflow size={18} />
                )}
              </div>
              <div className="task-row-main">
                <h3>{t.title}</h3>
                <span>
                  {formatDate(t.created_at)} · {profileLabels[t.profile]}
                  {t.private ? " · Private session" : ""}
                </span>
              </div>
              <Badge state={t.state} />
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <Empty icon={Workflow} title="An objective becomes a task">
          Ask Jarvis to research, edit code, or check something. Follow the work
          here.
        </Empty>
      )}
      {selected && (
        <Modal title={selected.title} onClose={() => setSelected(null)}>
          <div className="modal-body">
            <div className="button-row">
              <Badge state={selected.state} />
              <span className="muted">
                {selected.model || "Model has not started yet"}
              </span>
            </div>
            {selected.error && (
              <div className="error-box">{selected.error}</div>
            )}
            {selected.result && <Text value={selected.result} />}
            {!!detail.plan?.length && (
              <>
                <h3 className="detail-heading">Task plan</h3>
                <ol className="event-timeline">
                  {detail.plan.map((item: Json, i: number) => (
                    <li key={i}>
                      <span>{item.content}</span>
                      <strong>
                        {item.status === "completed"
                          ? "Completed"
                          : item.status === "in_progress"
                            ? "In progress"
                            : "To do"}
                      </strong>
                    </li>
                  ))}
                </ol>
              </>
            )}
            <div className="button-row">
              {["running", "queued"].includes(selected.state) && (
                <button
                  className="btn"
                  onClick={() => action(selected, "pause")}
                >
                  <Pause size={14} />
                  Pause
                </button>
              )}
              {["running", "queued", "waiting_user"].includes(
                selected.state,
              ) && (
                <button
                  className="btn danger"
                  onClick={() => action(selected, "cancel")}
                >
                  <X size={14} />
                  Cancel task
                </button>
              )}
              {selected.state === "paused" && (
                <button
                  className="btn"
                  onClick={() => action(selected, "resume")}
                >
                  <Play size={14} />
                  Resume checkpoint
                </button>
              )}
            </div>
            <h3 className="detail-heading">Observed steps</h3>
            {detail.events.length ? (
              <ol className="event-timeline">
                {detail.events
                  .filter(
                    (e: Json) =>
                      !["assistant.delta", "audio.level"].includes(e.type),
                  )
                  .map((e: Json) => (
                    <li key={e.id}>
                      <span>{e.type.replaceAll(".", " · ")}</span>
                      <strong>{e.data?.tool || e.data?.state || ""}</strong>
                      <small>{formatDate(e.created_at, true)}</small>
                    </li>
                  ))}
              </ol>
            ) : (
              <p className="muted">Steps will appear during execution.</p>
            )}
            {!!detail.tool_results?.length && (
              <>
                <h3 className="detail-heading">Tool results</h3>
                {detail.tool_results.map((item: Json, i: number) => (
                  <details key={i}>
                    <summary>{item.name}</summary>
                    <pre className="tool-output">{item.content}</pre>
                  </details>
                ))}
              </>
            )}
            {!!detail.artifacts?.length && (
              <>
                <h3 className="detail-heading">Files created or modified</h3>
                {detail.artifacts.map((item: Json) => (
                  <p className="endpoint" key={item.id}>
                    {item.path}
                  </p>
                ))}
              </>
            )}
            {detail.effects?.some((e: Json) => e.state === "unknown") && (
              <div className="error-box">
                An effect has an uncertain outcome. Check the destination system
                before retrying it.
              </div>
            )}
            {detail.effects
              ?.filter((e: Json) => e.state === "unknown")
              .map((effect: Json) => (
                <EffectReview
                  key={effect.operation_key}
                  effect={effect}
                  notify={notify}
                  onDone={() => open(selected)}
                />
              ))}
          </div>
        </Modal>
      )}
    </div>
  );
}

function EffectReview({
  effect,
  notify,
  onDone,
}: {
  effect: Json;
  notify: (text: string, error?: boolean) => void;
  onDone: () => void;
}) {
  const [result, setResult] = useState("{}"),
    [outcome, setOutcome] = useState("succeeded"),
    [verified, setVerified] = useState(false);
  return (
    <section className="subform">
      <h3>{effect.tool}</h3>
      <Field
        label="Outcome verified in the original system"
        value={outcome}
        onChange={setOutcome}
        options={[
          { value: "succeeded", label: "Executed · retain the result" },
          {
            value: "not_executed",
            label: "Not executed · allow another attempt",
          },
        ]}
      />
      {outcome === "succeeded" && (
        <Field
          label="Observed result, JSON"
          value={result}
          onChange={setResult}
          type="textarea"
        />
      )}
      <Toggle
        label="I verified the outcome before recording it"
        checked={verified}
        onChange={setVerified}
      />
      <button
        className="btn"
        disabled={!verified}
        onClick={async () => {
          try {
            await post("/effects/" + effect.operation_key + "/reconcile", {
              verified: true,
              outcome,
              result: JSON.parse(result),
            });
            onDone();
            notify("Outcome recorded. No action was repeated automatically.");
          } catch (e: any) {
            notify(e.message, true);
          }
        }}
      >
        Record verification
      </button>
    </section>
  );
}

export function Routines({ schedules, refresh, notify }: Props) {
  const [adding, setAdding] = useState(false),
    [editing, setEditing] = useState(""),
    [deleting, setDeleting] = useState(""),
    [saving, setSaving] = useState(false),
    [form, setForm] = useState<Json>({
      title: "",
      expression: "in 20 minutes",
      kind: "at",
      mode: "reminder",
      prompt: "",
      timezone: "Europe/Rome",
      profile: "local_connected",
      scope: "personal",
      notify: "desktop",
      call_authorized: false,
      misfire_policy: "coalesce",
      monitor: { url: "", json_path: "", operator: "changed", expected: null },
    });
  const set = (key: string, value: any) =>
    setForm((v) => ({ ...v, [key]: value }));
  async function save() {
    setSaving(true);
    try {
      const body = {
        ...form,
        monitor: form.mode === "monitor" ? form.monitor : null,
      };
      if (editing) await patch("/schedules/" + editing, body);
      else await post("/schedules", body);
      setAdding(false);
      setEditing("");
      refresh();
      notify("Routine saved with its next due time.");
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="page">
      <SectionTitle
        eyebrow="TIME, WITH PURPOSE"
        title="Routines and reminders"
        description="Persistent deadlines, quiet checks, and everyday tasks."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            New routine
          </button>
        }
      />
      <div className="info-line">
        <Clock3 size={14} />
        Execution requires an awake Mac. The selected recovery rule applies
        after wake.
      </div>
      {schedules.length ? (
        <div className="routine-grid">
          {schedules.map((s) => (
            <section className="routine-card" key={s.id}>
              <div className="routine-heading">
                <CalendarClock size={20} />
                <Badge state={s.enabled ? "connected" : "paused"}>
                  {s.enabled ? "Active" : "Paused"}
                </Badge>
              </div>
              <h2>{s.title}</h2>
              <p>{s.prompt || s.expression}</p>
              <div className="routine-next">
                <span>NEXT RUN</span>
                <strong>{formatDate(s.next_run_at)}</strong>
              </div>
              <div className="routine-meta">
                <span>
                  {s.mode === "monitor"
                    ? "Monitor"
                    : s.mode === "agent"
                      ? "Agent"
                      : "Reminder"}
                </span>
                <span>
                  {s.notify === "phone"
                    ? "Phone"
                    : s.notify === "voice"
                      ? "Voice"
                      : "Desktop"}
                </span>
                <span>{s.timezone}</span>
              </div>
              <div className="button-row">
                <button
                  className="btn"
                  onClick={() => {
                    setEditing(s.id);
                    setForm({
                      ...s,
                      call_authorized: Boolean(s.call_authorized),
                      monitor: JSON.parse(s.monitor || "{}"),
                    });
                    setAdding(true);
                  }}
                >
                  Edit
                </button>
                <button
                  className="btn"
                  onClick={() =>
                    patch("/schedules/" + s.id, { enabled: !s.enabled })
                      .then(refresh)
                      .catch((e) => notify(e.message, true))
                  }
                >
                  {s.enabled ? <Pause size={13} /> : <Play size={13} />}
                  {s.enabled ? "Pause" : "Resume"}
                </button>
                {deleting === s.id ? (
                  <button
                    className="btn danger"
                    onClick={() =>
                      api("/schedules/" + s.id, { method: "DELETE" })
                        .then(() => {
                          refresh();
                          setDeleting("");
                        })
                        .catch((e) => notify(e.message, true))
                    }
                  >
                    Confirm deletion
                  </button>
                ) : (
                  <button
                    className="icon-btn"
                    aria-label={"Delete " + s.title}
                    onClick={() => setDeleting(s.id)}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <Empty icon={CalendarClock} title="Let Jarvis remember the details">
          Create a reminder without a model, or an agent routine with a clear
          objective.
        </Empty>
      )}
      {adding && (
        <Modal title="A new routine" onClose={() => setAdding(false)}>
          <div className="modal-body">
            <Field
              label="Name"
              value={form.title}
              onChange={(v) => set("title", v)}
            />
            <div className="form-grid">
              <Field
                label="What it should do"
                value={form.mode}
                onChange={(v) => set("mode", v)}
                options={[
                  { value: "reminder", label: "Send a reminder" },
                  { value: "agent", label: "Run an agent task" },
                  {
                    value: "monitor",
                    label: "Monitor a JSON value on the web",
                  },
                ]}
              />
              <Field
                label="When"
                value={form.kind}
                onChange={(v) => set("kind", v)}
                options={[
                  { value: "at", label: "Once · date or phrase" },
                  { value: "interval", label: "Every interval · seconds" },
                  { value: "cron", label: "Cron recurrence" },
                ]}
              />
            </div>
            <Field
              label={
                form.kind === "at"
                  ? "Date or due time"
                  : form.kind === "interval"
                    ? "Interval, seconds"
                    : "Cron expression"
              }
              value={form.expression}
              onChange={(v) => set("expression", v)}
              help={
                form.kind === "at"
                  ? "Example: tomorrow at 09:00, or 2026-10-25T09:00:00+01:00"
                  : form.kind === "interval"
                    ? "Minimum 60 seconds."
                    : "Example: 0 9 * * 1-5 for weekdays."
              }
            />
            <Field
              label={
                form.mode === "agent"
                  ? "Complete agent objective"
                  : "Message or description"
              }
              value={form.prompt}
              onChange={(v) => set("prompt", v)}
              type="textarea"
              help="Jobs must be understandable without relying on the current chat."
            />
            {form.mode === "monitor" && (
              <section className="subform">
                <Field
                  label="Public JSON URL"
                  value={form.monitor.url}
                  onChange={(v) => set("monitor", { ...form.monitor, url: v })}
                />
                <Field
                  label="JSON path"
                  value={form.monitor.json_path}
                  onChange={(v) =>
                    set("monitor", { ...form.monitor, json_path: v })
                  }
                  help="Example: status or results.0.price"
                />
                <div className="form-grid">
                  <Field
                    label="Condition"
                    value={form.monitor.operator}
                    onChange={(v) =>
                      set("monitor", { ...form.monitor, operator: v })
                    }
                    options={[
                      { value: "changed", label: "The value changes" },
                      { value: "equals", label: "Equals" },
                      { value: "contains", label: "Contains" },
                      { value: "gte", label: "Greater than or equal to" },
                      { value: "lte", label: "Less than or equal to" },
                    ]}
                  />
                  {form.monitor.operator !== "changed" && (
                    <Field
                      label="Expected value"
                      value={form.monitor.expected ?? ""}
                      onChange={(v) =>
                        set("monitor", { ...form.monitor, expected: v })
                      }
                    />
                  )}
                </div>
                <small className="hint">
                  The first read establishes the baseline for “changes”. No
                  notification is sent while the value stays the same.
                </small>
              </section>
            )}
            <div className="form-grid">
              <Field
                label="Time zone"
                value={form.timezone}
                onChange={(v) => set("timezone", v)}
              />
              <Field
                label="Notification"
                value={form.notify}
                onChange={(v) => set("notify", v)}
                options={[
                  { value: "desktop", label: "Desktop" },
                  { value: "voice", label: "Voice on Mac" },
                  { value: "phone", label: "Phone call to the owner" },
                ]}
              />
              <Field
                label="AI profile"
                value={form.profile}
                onChange={(v) => set("profile", v)}
                options={Object.entries(profileLabels).map(
                  ([value, label]) => ({ value, label }),
                )}
              />
              <Field
                label="If the Mac was asleep"
                value={form.misfire_policy}
                onChange={(v) => set("misfire_policy", v)}
                options={[
                  { value: "coalesce", label: "Recover one run" },
                  { value: "skip", label: "Skip outside the tolerance window" },
                  { value: "run_once", label: "Run once on return" },
                ]}
              />
            </div>
            {form.notify === "phone" && (
              <Toggle
                label="I authorize this routine to call my number"
                help="Quiet hours, budgets, and limits still apply. Expired calls are not recovered after wake."
                checked={form.call_authorized}
                onChange={(v) => set("call_authorized", v)}
              />
            )}
            <button
              className="btn primary"
              disabled={saving || !form.title.trim()}
              onClick={save}
            >
              {saving ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Check size={14} />
              )}
              Save routine
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
