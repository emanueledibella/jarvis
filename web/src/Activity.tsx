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
        eyebrow="DAL PIANO AL RISULTATO"
        title="Attività"
        description={`${active.length} attività aperte. Ogni azione ha uno stato verificabile.`}
      />
      {!!approvals.length && (
        <section className="attention-section">
          <h2>Le tue decisioni</h2>
          {approvals.map((a) => (
            <div className="approval-card" key={a.id}>
              <div>
                <Badge state="waiting_user" />
                <h3>{a.tool}</h3>
                <pre>{JSON.stringify(a.arguments, null, 2)}</pre>
                <small>Valida fino alle {formatDate(a.expires_at, true)}</small>
              </div>
              <div className="button-row">
                <button className="btn" onClick={() => decision(a.id, false)}>
                  Rifiuta
                </button>
                <button
                  className="btn primary"
                  onClick={() => decision(a.id, true)}
                >
                  <Check size={14} />
                  Approva questa azione
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
                  {t.private ? " · Sessione privata" : ""}
                </span>
              </div>
              <Badge state={t.state} />
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <Empty icon={Workflow} title="Un obiettivo diventa un’attività">
          Chiedi a Jarvis una ricerca, una modifica al codice o una verifica.
          Qui seguirai il lavoro.
        </Empty>
      )}
      {selected && (
        <Modal title={selected.title} onClose={() => setSelected(null)}>
          <div className="modal-body">
            <div className="button-row">
              <Badge state={selected.state} />
              <span className="muted">
                {selected.model || "Modello non ancora avviato"}
              </span>
            </div>
            {selected.error && (
              <div className="error-box">{selected.error}</div>
            )}
            {selected.result && <Text value={selected.result} />}
            {!!detail.plan?.length && (
              <>
                <h3 className="detail-heading">Piano del task</h3>
                <ol className="event-timeline">
                  {detail.plan.map((item: Json, i: number) => (
                    <li key={i}>
                      <span>{item.content}</span>
                      <strong>
                        {item.status === "completed"
                          ? "Completato"
                          : item.status === "in_progress"
                            ? "In corso"
                            : "Da eseguire"}
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
                  Sospendi
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
                  Annulla il task
                </button>
              )}
              {selected.state === "paused" && (
                <button
                  className="btn"
                  onClick={() => action(selected, "resume")}
                >
                  <Play size={14} />
                  Riprendi checkpoint
                </button>
              )}
            </div>
            <h3 className="detail-heading">Passaggi osservati</h3>
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
              <p className="muted">
                I passaggi appariranno durante l’esecuzione.
              </p>
            )}
            {!!detail.tool_results?.length && (
              <>
                <h3 className="detail-heading">Risultati degli strumenti</h3>
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
                <h3 className="detail-heading">File prodotti o modificati</h3>
                {detail.artifacts.map((item: Json) => (
                  <p className="endpoint" key={item.id}>
                    {item.path}
                  </p>
                ))}
              </>
            )}
            {detail.effects?.some((e: Json) => e.state === "unknown") && (
              <div className="error-box">
                Un effetto ha esito incerto. Verifica il sistema destinazione
                prima di ripeterlo.
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
        label="Esito verificato sul sistema originale"
        value={outcome}
        onChange={setOutcome}
        options={[
          { value: "succeeded", label: "Eseguito · conserva il risultato" },
          {
            value: "not_executed",
            label: "Non eseguito · consenti un nuovo tentativo",
          },
        ]}
      />
      {outcome === "succeeded" && (
        <Field
          label="Risultato osservato, JSON"
          value={result}
          onChange={setResult}
          type="textarea"
        />
      )}
      <Toggle
        label="Ho verificato l’esito prima di registrarlo"
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
            notify(
              "Esito registrato. Nessuna azione ripetuta automaticamente.",
            );
          } catch (e: any) {
            notify(e.message, true);
          }
        }}
      >
        Registra verifica
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
      expression: "tra 20 minuti",
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
      notify("Routine salvata con la sua prossima scadenza.");
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="page">
      <SectionTitle
        eyebrow="IL TEMPO, CON INTENZIONE"
        title="Routine e promemoria"
        description="Scadenze persistenti, controlli silenziosi e attività quotidiane."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            Nuova routine
          </button>
        }
      />
      <div className="info-line">
        <Clock3 size={14} />
        Le esecuzioni richiedono il Mac sveglio. Al risveglio si applica la
        regola di recupero scelta.
      </div>
      {schedules.length ? (
        <div className="routine-grid">
          {schedules.map((s) => (
            <section className="routine-card" key={s.id}>
              <div className="routine-heading">
                <CalendarClock size={20} />
                <Badge state={s.enabled ? "connected" : "paused"}>
                  {s.enabled ? "Attiva" : "In pausa"}
                </Badge>
              </div>
              <h2>{s.title}</h2>
              <p>{s.prompt || s.expression}</p>
              <div className="routine-next">
                <span>PROSSIMA ESECUZIONE</span>
                <strong>{formatDate(s.next_run_at)}</strong>
              </div>
              <div className="routine-meta">
                <span>
                  {s.mode === "monitor"
                    ? "Monitor"
                    : s.mode === "agent"
                      ? "Agente"
                      : "Promemoria"}
                </span>
                <span>
                  {s.notify === "phone"
                    ? "Telefono"
                    : s.notify === "voice"
                      ? "Voce"
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
                  Modifica
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
                  {s.enabled ? "Sospendi" : "Riattiva"}
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
                    Conferma eliminazione
                  </button>
                ) : (
                  <button
                    className="icon-btn"
                    aria-label={"Elimina " + s.title}
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
        <Empty
          icon={CalendarClock}
          title="Lascia a Jarvis le cose da ricordare"
        >
          Crea un promemoria senza usare un modello, oppure una routine agentica
          con un obiettivo preciso.
        </Empty>
      )}
      {adding && (
        <Modal title="Una nuova routine" onClose={() => setAdding(false)}>
          <div className="modal-body">
            <Field
              label="Nome"
              value={form.title}
              onChange={(v) => set("title", v)}
            />
            <div className="form-grid">
              <Field
                label="Cosa deve fare"
                value={form.mode}
                onChange={(v) => set("mode", v)}
                options={[
                  { value: "reminder", label: "Inviare un promemoria" },
                  { value: "agent", label: "Eseguire un lavoro con l’agente" },
                  {
                    value: "monitor",
                    label: "Controllare un valore JSON sul web",
                  },
                ]}
              />
              <Field
                label="Quando"
                value={form.kind}
                onChange={(v) => set("kind", v)}
                options={[
                  { value: "at", label: "Una volta · data o frase" },
                  { value: "interval", label: "Ogni intervallo · secondi" },
                  { value: "cron", label: "Ricorrenza cron" },
                ]}
              />
            </div>
            <Field
              label={
                form.kind === "at"
                  ? "Data o scadenza"
                  : form.kind === "interval"
                    ? "Intervallo, secondi"
                    : "Espressione cron"
              }
              value={form.expression}
              onChange={(v) => set("expression", v)}
              help={
                form.kind === "at"
                  ? "Esempio: domani alle 09:00, oppure 2026-10-25T09:00:00+01:00"
                  : form.kind === "interval"
                    ? "Minimo 60 secondi."
                    : "Esempio: 0 9 * * 1-5 per i giorni lavorativi."
              }
            />
            <Field
              label={
                form.mode === "agent"
                  ? "Obiettivo completo dell’agente"
                  : "Messaggio o descrizione"
              }
              value={form.prompt}
              onChange={(v) => set("prompt", v)}
              type="textarea"
              help="I job devono essere comprensibili senza dipendere dalla chat corrente."
            />
            {form.mode === "monitor" && (
              <section className="subform">
                <Field
                  label="URL JSON pubblico"
                  value={form.monitor.url}
                  onChange={(v) => set("monitor", { ...form.monitor, url: v })}
                />
                <Field
                  label="Percorso nel JSON"
                  value={form.monitor.json_path}
                  onChange={(v) =>
                    set("monitor", { ...form.monitor, json_path: v })
                  }
                  help="Esempio: status oppure results.0.price"
                />
                <div className="form-grid">
                  <Field
                    label="Condizione"
                    value={form.monitor.operator}
                    onChange={(v) =>
                      set("monitor", { ...form.monitor, operator: v })
                    }
                    options={[
                      { value: "changed", label: "Il valore cambia" },
                      { value: "equals", label: "È uguale a" },
                      { value: "contains", label: "Contiene" },
                      { value: "gte", label: "È maggiore o uguale a" },
                      { value: "lte", label: "È minore o uguale a" },
                    ]}
                  />
                  {form.monitor.operator !== "changed" && (
                    <Field
                      label="Valore atteso"
                      value={form.monitor.expected ?? ""}
                      onChange={(v) =>
                        set("monitor", { ...form.monitor, expected: v })
                      }
                    />
                  )}
                </div>
                <small className="hint">
                  La prima lettura stabilisce il riferimento per “cambia”.
                  Nessuna notifica quando il valore resta uguale.
                </small>
              </section>
            )}
            <div className="form-grid">
              <Field
                label="Fuso orario"
                value={form.timezone}
                onChange={(v) => set("timezone", v)}
              />
              <Field
                label="Notifica"
                value={form.notify}
                onChange={(v) => set("notify", v)}
                options={[
                  { value: "desktop", label: "Desktop" },
                  { value: "voice", label: "Voce sul Mac" },
                  { value: "phone", label: "Telefonata al proprietario" },
                ]}
              />
              <Field
                label="Profilo AI"
                value={form.profile}
                onChange={(v) => set("profile", v)}
                options={Object.entries(profileLabels).map(
                  ([value, label]) => ({ value, label }),
                )}
              />
              <Field
                label="Se il Mac era in stop"
                value={form.misfire_policy}
                onChange={(v) => set("misfire_policy", v)}
                options={[
                  { value: "coalesce", label: "Recupera una sola esecuzione" },
                  { value: "skip", label: "Salta se fuori tolleranza" },
                  { value: "run_once", label: "Esegui una volta al rientro" },
                ]}
              />
            </div>
            {form.notify === "phone" && (
              <Toggle
                label="Autorizzo questa routine a chiamare il mio numero"
                help="Restano validi orari silenziosi, budget e limiti. Le chiamate scadute non vengono recuperate al risveglio."
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
              Salva routine
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
