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
      notify("Source queued. Adoption will be checked separately.");
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
        eyebrow="CONTINUITY, WITH SOURCES"
        title="Your memory"
        description="Preferences, decisions, and context in the Second Brain you already created."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            Remember something
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
            The memory ledger remains separate from chat history and task state.
          </p>
        </div>
        <Badge
          state={status.configured ? status.connection?.state : "not_connected"}
        />
      </div>
      {!status.configured ? (
        <Empty
          icon={Link2}
          title="Connect your memory"
          action={
            <button className="btn" onClick={() => openSettings("memory")}>
              Set up Second Brain
            </button>
          }
        >
          Use a dedicated endpoint and credential. Memories are never simulated.
        </Empty>
      ) : (
        <>
          <div className="search-memory">
            <Search size={18} />
            <input
              aria-label="Search memories"
              placeholder="What did we decide about…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && query.trim()) recall();
              }}
            />
            <select
              aria-label="Memory scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="personal">Personal</option>
              <option value="work">Work</option>
            </select>
            <button
              className="btn"
              disabled={busy || !query.trim()}
              onClick={recall}
            >
              {busy ? <LoaderCircle size={14} className="spin" /> : "Search"}
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
                          ? "Conflicting sources"
                          : m.epistemic === "inferred"
                            ? "Inference"
                            : "Explicit source"}
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
                          {e.title || e.source_id} · revision {e.revision}
                          <ArrowUpRight size={12} />
                        </button>
                        <code>{e.source_id}</code>
                      </div>
                    ))}
                  </article>
                ))
              ) : (
                <Empty icon={Search} title="No relevant memory">
                  A search without results does not prove that a decision was
                  made.
                </Empty>
              )}
            </section>
          )}
        </>
      )}
      <div className="subsection-heading">
        <h2>Sources being processed</h2>
        <button
          className="icon-btn"
          onClick={load}
          aria-label="Refresh memory status"
        >
          <RefreshCw size={15} />
        </button>
      </div>
      {status.outbox?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Request</th>
                <th>Status</th>
                <th>Source / revision</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {status.outbox.map((o: Json) => (
                <tr key={o.id}>
                  <td>
                    {formatDate(o.created_at)}
                    <small>{o.attempts} checks</small>
                  </td>
                  <td>
                    <Badge state={o.state} />
                    {o.detail?.warnings?.length > 0 && (
                      <small>{o.detail.warnings.join(" · ")}</small>
                    )}
                  </td>
                  <td>
                    <code>{o.source_id || "Unconfirmed delivery"}</code>
                    {o.revision && <small>Revision {o.revision}</small>}
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
                        Check again
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
          No pending sources. New writes will appear here with their actual
          state.
        </p>
      )}
      {adding && (
        <Modal
          title="A source for Second Brain"
          onClose={() => setAdding(false)}
        >
          <div className="modal-body">
            <Field
              label="Original text to remember"
              type="textarea"
              value={note}
              onChange={setNote}
              help="Save explicit information. Assumptions and proposals do not become personal facts."
            />
            <Field
              label="Scope"
              value={scope}
              onChange={setScope}
              options={[
                { value: "personal", label: "Personal" },
                { value: "work", label: "Work" },
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
              Queue source
            </button>
          </div>
        </Modal>
      )}
      {source && (
        <Modal
          title={source.title || "Original source"}
          onClose={() => setSource(null)}
        >
          <div className="modal-body">
            <small>
              Source {source.source_id} · revision {source.revision}
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
        "Server registered. Connect to discover its tools, then enable the ones you need.",
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
        eyebrow="TOOLS AND PERMISSIONS"
        title="Connections"
        description="Local and MCP tools, with explicit provenance and permissions."
        action={
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Plus size={15} />
            Add MCP server
          </button>
        }
      />
      <div className="integration-grid">
        <section className="integration-card">
          <div className="integration-icon">
            <Brain size={26} />
          </div>
          <h2>Second Brain</h2>
          <p>Personal memory with sources and revisions.</p>
          <button className="btn" onClick={() => openSettings("memory")}>
            Set up memory
          </button>
        </section>
        <section className="integration-card">
          <div className="integration-icon">
            <Database size={26} />
          </div>
          <h2>Mac tools</h2>
          <p>Files, commands, voice, calendar, and persistent tasks.</p>
          <Badge state="connected">Local gateway</Badge>
          <button className="text-btn" onClick={() => openSettings("security")}>
            Workspaces and autonomy <ArrowUpRight size={13} />
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
              {item.transport === "stdio" ? "Local process" : "Streamable HTTP"}{" "}
              · {item.auth}
            </small>
            <button
              className="btn"
              onClick={() =>
                post("/integrations/" + item.name + "/connect")
                  .then(() => {
                    notify("Connection started.");
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
              Connect / verify
            </button>
            {item.status?.error && (
              <small className="error-text">
                {item.status.error}. Check the endpoint and authorization.
              </small>
            )}
            {item.status?.tools?.length > 0 && (
              <details>
                <summary>{item.status.tools.length} tools discovered</summary>
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
                          <option value="off">Disabled</option>
                          <option value="read">Read</option>
                          <option value="write">Write · controlled</option>
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
        Discovering a tool does not automatically grant permission to execute
        actions.
      </div>
      {adding && (
        <Modal title="Connect an MCP server" onClose={() => setAdding(false)}>
          <div className="modal-body">
            <Field
              label="Server name"
              value={name}
              onChange={setName}
              help="Letters, numbers, and hyphens. Second Brain has a dedicated configuration."
            />
            <Field
              label="Configuration"
              type="textarea"
              value={spec}
              onChange={setSpec}
              help="An HTTP URL or an absolute command with args. Secrets may use env:VARIABLE_NAME references; classify tools after discovery."
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
              Register server
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
