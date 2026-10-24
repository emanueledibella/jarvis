import React, { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Brain,
  Check,
  Database,
  Link2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { api, post, type Json } from "./api";
import {
  Badge,
  Empty,
  Field,
  Modal,
  SectionTitle,
  Text,
  formatDate,
} from "./components";

type Props = {
  notify: (message: string, error?: boolean) => void;
  openSettings: (section: string) => void;
};
export function Memory({ notify, openSettings }: Props) {
  const [status, setStatus] = useState<Json>({ outbox: [] }),
    [query, setQuery] = useState(""),
    [scope, setScope] = useState("personal"),
    [result, setResult] = useState<Json | null>(null),
    [busy, setBusy] = useState(false),
    [adding, setAdding] = useState(false),
    [note, setNote] = useState(""),
    [source, setSource] = useState<Json | null>(null);
  const load = () =>
    api("/memory/status")
      .then(setStatus)
      .catch((e) => notify(e.message, true));
  useEffect(() => {
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);
  async function recall() {
    setBusy(true);
    try {
      setResult(await post("/memory/recall", { text: query, scope }));
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function remember() {
    setBusy(true);
    try {
      await post("/memory/remember", { text: note, scope });
      notify("Fonte accodata. L’adozione verrà controllata separatamente.");
      setAdding(false);
      setNote("");
      load();
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page">
      <SectionTitle
        eyebrow="CONTINUITÀ, CON LE SUE FONTI"
        title="La tua memoria"
        description="Preferenze, decisioni e contesto nel Second Brain che hai già creato."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            Ricorda qualcosa
          </button>
        }
      />
      <div className="memory-banner">
        <div className="large-icon">
          <Brain size={27} />
        </div>
        <div>
          <h2>Second Brain</h2>
          <p>
            Il registro dei ricordi resta distinto dalla cronologia e dallo
            stato dei task.
          </p>
        </div>
        <Badge
          state={status.configured ? status.connection?.state : "not_connected"}
        />
      </div>
      {!status.configured ? (
        <Empty
          icon={Link2}
          title="Collega la tua memoria"
          action={
            <button className="btn" onClick={() => openSettings("memory")}>
              Configura Second Brain
            </button>
          }
        >
          Usa un endpoint e una credenziale dedicati. Nessun ricordo viene
          simulato.
        </Empty>
      ) : (
        <>
          <div className="search-memory">
            <Search size={18} />
            <input
              aria-label="Cerca nei ricordi"
              placeholder="Cosa avevamo deciso su…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && query.trim()) recall();
              }}
            />
            <select
              aria-label="Ambito dei ricordi"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="personal">Personale</option>
              <option value="work">Lavoro</option>
            </select>
            <button
              className="btn"
              disabled={busy || !query.trim()}
              onClick={recall}
            >
              {busy ? <LoaderCircle size={14} className="spin" /> : "Cerca"}
            </button>
          </div>
          {result && (
            <section className="memory-results">
              {result.memories?.length ? (
                result.memories.map((m: Json) => (
                  <article className="memory-result" key={m.id}>
                    <div className="button-row">
                      <Badge
                        state={m.conflicts?.length ? "unknown" : "connected"}
                      >
                        {m.conflicts?.length
                          ? "Fonti in conflitto"
                          : m.epistemic === "inferred"
                            ? "Deduzione"
                            : "Fonte esplicita"}
                      </Badge>
                      <small>{m.scope}</small>
                    </div>
                    <p>{m.statement || m.value}</p>
                    {m.evidence?.map((e: Json, i: number) => (
                      <div className="evidence" key={i}>
                        <blockquote>{e.quote}</blockquote>
                        <button
                          onClick={() =>
                            api(
                              "/memory/source/" +
                                e.source_id +
                                "?revision=" +
                                e.revision,
                            )
                              .then(setSource)
                              .catch((error) => notify(error.message, true))
                          }
                        >
                          {e.title || e.source_id} · revisione {e.revision}
                          <ArrowUpRight size={12} />
                        </button>
                        <code>{e.source_id}</code>
                      </div>
                    ))}
                  </article>
                ))
              ) : (
                <Empty icon={Search} title="Nessun ricordo pertinente">
                  Una ricerca senza risultati non dimostra che una decisione sia
                  stata presa.
                </Empty>
              )}
            </section>
          )}
        </>
      )}
      <div className="subsection-heading">
        <h2>Fonti in elaborazione</h2>
        <button
          className="icon-btn"
          onClick={load}
          aria-label="Aggiorna stato memoria"
        >
          <RefreshCw size={15} />
        </button>
      </div>
      {status.outbox?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Richiesta</th>
                <th>Stato</th>
                <th>Fonte / revisione</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {status.outbox.map((o: Json) => (
                <tr key={o.id}>
                  <td>
                    {formatDate(o.created_at)}
                    <small>{o.attempts} verifiche</small>
                  </td>
                  <td>
                    <Badge state={o.state} />
                    {o.detail?.warnings?.length > 0 && (
                      <small>{o.detail.warnings.join(" · ")}</small>
                    )}
                  </td>
                  <td>
                    <code>{o.source_id || "Consegna non confermata"}</code>
                    {o.revision && <small>Revisione {o.revision}</small>}
                  </td>
                  <td>
                    {["delivery_error", "needs_review"].includes(o.state) && (
                      <button
                        className="btn"
                        onClick={() =>
                          post("/memory/" + o.id + "/retry")
                            .then(load)
                            .catch((e) => notify(e.message, true))
                        }
                      >
                        Ricontrolla
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          Nessuna fonte in attesa. Le nuove scritture compariranno qui con il
          loro stato reale.
        </p>
      )}
      {adding && (
        <Modal
          title="Una fonte per il Second Brain"
          onClose={() => setAdding(false)}
        >
          <div className="modal-body">
            <Field
              label="Testo originale da ricordare"
              type="textarea"
              value={note}
              onChange={setNote}
              help="Salva informazioni esplicite. Ipotesi e proposte non diventano fatti personali."
            />
            <Field
              label="Ambito"
              value={scope}
              onChange={setScope}
              options={[
                { value: "personal", label: "Personale" },
                { value: "work", label: "Lavoro" },
              ]}
            />
            <button
              className="btn primary"
              disabled={busy || !note.trim()}
              onClick={remember}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Check size={14} />
              )}
              Accoda fonte
            </button>
          </div>
        </Modal>
      )}
      {source && (
        <Modal
          title={source.title || "Fonte originale"}
          onClose={() => setSource(null)}
        >
          <div className="modal-body">
            <small>
              Fonte {source.source_id} · revisione {source.revision}
            </small>
            <Text value={source.text || JSON.stringify(source, null, 2)} />
          </div>
        </Modal>
      )}
    </div>
  );
}

export function Integrations({ notify, openSettings }: Props) {
  const [items, setItems] = useState<Json[]>([]),
    [adding, setAdding] = useState(false),
    [name, setName] = useState(""),
    [spec, setSpec] = useState(
      '{\n  "url": "https://example.com/mcp",\n  "auth": "oauth",\n  "read_tools": [],\n  "write_tools": []\n}',
    ),
    [busy, setBusy] = useState(false);
  const load = () =>
    api("/integrations")
      .then(setItems)
      .catch((e) => notify(e.message, true));
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);
  async function save() {
    setBusy(true);
    try {
      const servers: Json = {};
      for (const item of items.filter((x) => x.name !== "second_brain"))
        servers[item.name] = {
          url: item.url,
          command: item.command,
          args: item.args,
          read_tools: item.read_tools,
          write_tools: item.write_tools,
          auth: item.auth,
        };
      servers[name] = JSON.parse(spec);
      await api("/integrations/mcp/config", {
        method: "PUT",
        body: JSON.stringify({ servers }),
      });
      setAdding(false);
      load();
      notify(
        "Server registrato. Connettilo per scoprire i tool, poi abilita quelli necessari.",
      );
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function policy(item: Json, tool: string, risk: string) {
    try {
      const servers: Json = {};
      for (const current of items.filter((x) => x.name !== "second_brain")) {
        const reads = current.read_tools.filter(
            (x: string) => x !== tool || current.name !== item.name,
          ),
          writes = current.write_tools.filter(
            (x: string) => x !== tool || current.name !== item.name,
          );
        if (current.name === item.name && risk === "read") reads.push(tool);
        if (current.name === item.name && risk === "write") writes.push(tool);
        servers[current.name] = {
          url: current.url,
          command: current.command,
          args: current.args,
          auth: current.auth,
          read_tools: reads,
          write_tools: writes,
        };
      }
      await api("/integrations/mcp/config", {
        method: "PUT",
        body: JSON.stringify({ servers }),
      });
      await post("/integrations/" + item.name + "/connect");
      load();
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  return (
    <div className="page">
      <SectionTitle
        eyebrow="STRUMENTI E PERMESSI"
        title="Connessioni"
        description="Tool locali e MCP, con provenienza e permessi espliciti."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            Aggiungi server MCP
          </button>
        }
      />
      <div className="integration-grid">
        <section className="integration-card">
          <div className="integration-icon">
            <Brain size={26} />
          </div>
          <h2>Second Brain</h2>
          <p>Memoria personale con fonti e revisioni.</p>
          <button className="btn" onClick={() => openSettings("memory")}>
            Configura memoria
          </button>
        </section>
        <section className="integration-card">
          <div className="integration-icon">
            <Database size={26} />
          </div>
          <h2>Tool del Mac</h2>
          <p>File, comandi, voce, calendario e task persistenti.</p>
          <Badge state="connected">Gateway locale</Badge>
          <button className="text-btn" onClick={() => openSettings("security")}>
            Workspace e autonomia <ArrowUpRight size={13} />
          </button>
        </section>
        {items.map((item) => (
          <section className="integration-card" key={item.name}>
            <div className="card-heading">
              <div className="integration-icon">
                <Link2 size={25} />
              </div>
              <Badge state={item.status?.state} />
            </div>
            <h2>{item.name}</h2>
            <p className="endpoint">{item.url || item.command}</p>
            <small>
              {item.transport === "stdio"
                ? "Processo locale"
                : "Streamable HTTP"}{" "}
              · {item.auth}
            </small>
            <button
              className="btn"
              onClick={() =>
                post("/integrations/" + item.name + "/connect")
                  .then(() => {
                    notify("Connessione avviata.");
                    load();
                  })
                  .catch((e) => notify(e.message, true))
              }
            >
              {item.status?.state === "connecting" ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <RefreshCw size={14} />
              )}
              Connetti / verifica
            </button>
            {item.status?.error && (
              <small className="error-text">
                {item.status.error}. Verifica endpoint e autorizzazione.
              </small>
            )}
            {item.status?.tools?.length > 0 && (
              <details>
                <summary>{item.status.tools.length} tool scoperti</summary>
                <div className="tools-policy">
                  {item.status.tools.map((tool: Json) => (
                    <label key={tool.name}>
                      <span title={tool.description}>{tool.name}</span>
                      {item.name === "second_brain" ? (
                        <Badge
                          state={tool.enabled ? "connected" : "not_connected"}
                        >
                          {tool.risk}
                        </Badge>
                      ) : (
                        <select
                          aria-label={"Policy " + tool.name}
                          value={
                            item.read_tools.includes(tool.name)
                              ? "read"
                              : item.write_tools.includes(tool.name)
                                ? "write"
                                : "off"
                          }
                          onChange={(e) =>
                            policy(item, tool.name, e.target.value)
                          }
                        >
                          <option value="off">Disabilitato</option>
                          <option value="read">Lettura</option>
                          <option value="write">Scrittura · controllata</option>
                        </select>
                      )}
                    </label>
                  ))}
                </div>
              </details>
            )}
          </section>
        ))}
      </div>
      <div className="info-line">
        <ShieldCheck size={15} />
        Un tool scoperto non riceve automaticamente il permesso di eseguire
        azioni.
      </div>
      {adding && (
        <Modal title="Collega un server MCP" onClose={() => setAdding(false)}>
          <div className="modal-body">
            <Field
              label="Nome del server"
              value={name}
              onChange={setName}
              help="Lettere, numeri, trattini. Second Brain ha una configurazione dedicata."
            />
            <Field
              label="Configurazione"
              type="textarea"
              value={spec}
              onChange={setSpec}
              help="URL HTTP oppure command assoluto con args. I segreti possono essere riferimenti env:NOME_VARIABILE; i tool vanno classificati dopo la scoperta."
            />
            <button
              className="btn primary"
              onClick={save}
              disabled={busy || !name}
            >
              {busy ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Link2 size={14} />
              )}
              Registra server
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
