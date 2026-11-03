import React, { useEffect, useState } from "react";
import { api, post, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Modal, SectionTitle } from "./components";

export default function Development({ scope, privateMode, privacyRevision, notify, onAsk }: {
  scope: string; privateMode: boolean; privacyRevision: number; notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [connections, setConnections] = useState<Json[]>([]);
  const [edit, setEdit] = useState<Json | null>(null);
  const [remove, setRemove] = useState<Json | null>(null);
  const [provider, setProvider] = useState("jira");
  const [target, setTarget] = useState("");
  const [query, setQuery] = useState("");
  const [evidence, setEvidence] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const context = { scope, privacy_revision: privacyRevision };
  useEffect(() => {
    const controller = new AbortController();
    api("/development?scope=" + scope, { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) { setConnections(result); setTarget((old) => result.find((x: Json) => x.provider === provider)?.allowed.includes(old) ? old : result.find((x: Json) => x.provider === provider)?.allowed[0] || ""); }
    }).catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope, refresh, provider]);
  async function action(run: () => Promise<unknown>) {
    setBusy(true); try { await run(); setRefresh((x) => x + 1); } catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  const configure = (kind: string) => { const old = connections.find((x) => x.provider === kind); setEdit({ provider: kind, site: "https://teamsystem.atlassian.net/", allowed: kind === "jira" ? ["BVTL"] : [], writes: false, ...old, token: "", allowed_text: (old?.allowed || (kind === "jira" ? ["BVTL"] : [])).join("\n") }); };
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("PROJECT CONTEXT")} title={tr("Jira and GitHub")}
      description={tr("Prepare stand-ups and reviews using explicitly allowed project sources.")} />
    <div className="assistant-actions">{["jira", "github"].map((kind) => <button className="btn" key={kind} disabled={privateMode} onClick={() => configure(kind)}>{tr(kind === "jira" ? "Configure Jira" : "Configure GitHub")}</button>)}
      <button className="btn primary" onClick={() => onAsk(tr("Prepare my stand-up from the connected Jira projects and GitHub repositories. Cite progress, open reviews and blockers, flag incomplete sources, and suggest next actions without publishing or changing anything."))}>{tr("Prepare stand-up")}</button>
    </div>
    <div className="assistant-card">
      <p>{tr("Jira uses dedicated OAuth with the official Rovo MCP server. GitHub uses a fine-grained token restricted to the repositories below. Writes default to off.")}</p>
      {connections.map((connection) => <article key={connection.provider}><strong>{connection.provider}</strong><p>{connection.allowed.join(", ")} · {tr(connection.writes ? "Writes enabled" : "Read only")}</p>
        {connection.server && <small>{connection.server}</small>}
        <div className="assistant-actions"><button className="btn" disabled={busy || privateMode} onClick={() => action(async () => { await post("/development/" + connection.provider + "/connect", context); notify(connection.provider === "jira" ? "Complete provider consent in your browser, then refresh Connections." : "Repository connection verified."); })}>{tr(connection.provider === "jira" ? "Connect Jira" : "Test GitHub connection")}</button><button className="btn" disabled={privateMode} onClick={() => setRemove(connection)}>{tr("Disconnect")}</button></div>
      </article>)}
    </div>
    <div className="assistant-card">
      <div className="assistant-actions">
        <select aria-label={tr("Provider")} value={provider} onChange={(e) => { setProvider(e.target.value); setEvidence(null); }}>{["jira", "github"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select>
        <select aria-label={tr("Allowed target")} value={target} onChange={(e) => { setTarget(e.target.value); setEvidence(null); }}>{(connections.find((x) => x.provider === provider)?.allowed || []).map((value: string) => <option key={value}>{value}</option>)}</select>
        {provider === "jira" && <input aria-label={tr("Jira search text")} maxLength={300} value={query} onChange={(e) => setQuery(e.target.value)} />}
        <button className="btn" disabled={busy || !target} onClick={() => action(async () => { setEvidence(await api(provider === "jira" ? "/development/jira/issues?" + new URLSearchParams({ scope, project: target, query }) : "/development/github/items?" + new URLSearchParams({ scope, repository: target }))); })}>{tr("Read project sources")}</button>
      </div>
      {(evidence?.issues || evidence?.items || []).map((item: Json) => <article key={item.key || item.number}><strong>{item.key || "#" + item.number} · {item.summary || item.title}</strong><p>{item.status || item.state} · {item.assignee || item.author}</p>
        <button className="btn" onClick={() => onAsk(provider === "jira" ? tr("Analyze Jira issue {key}: explain its requirements, open questions and next actions without changing it.", { key: item.key }) : tr("Review GitHub pull request {repository} #{number}: inspect changes and checks at the current revision, flag missing evidence and do not publish the review.", { repository: target, number: String(item.number) }))}>{tr(provider === "jira" ? "Analyze issue" : "Review pull request")}</button>
      </article>)}
      {(evidence?.next || evidence?.next_page || evidence?.partial) && <p>{tr("Only a bounded page is shown. Ask Jarvis to read further pages when needed.")}</p>}
    </div>
    {edit && <Modal title={tr(edit.provider === "jira" ? "Configure Jira" : "Configure GitHub")} onClose={() => setEdit(null)}><form className="assistant-form" onSubmit={(e) => { e.preventDefault(); action(async () => { await api("/development", { method: "PUT", body: JSON.stringify({ ...context, provider: edit.provider, site: edit.site, allowed: edit.allowed_text.split("\n").map((x: string) => x.trim()).filter(Boolean), token: edit.token, writes: edit.writes }) }); setEdit(null); }); }}>
      {edit.provider === "jira" ? <label>{tr("Jira Cloud site")}<input type="url" required value={edit.site} onChange={(e) => setEdit({ ...edit, site: e.target.value })} /></label> : <><label>{tr("Fine-grained GitHub token")}<input type="password" autoComplete="off" maxLength={2000} value={edit.token} onChange={(e) => setEdit({ ...edit, token: e.target.value })} /></label><p>{tr("Grant only selected repositories: metadata, issues, pull requests, contents, checks and commit statuses as needed. Leave the token blank to preserve it.")}</p></>}
      <label>{tr("Allowed projects or repositories, one per line")}<textarea required value={edit.allowed_text} onChange={(e) => setEdit({ ...edit, allowed_text: e.target.value })} /></label>
      <label><input type="checkbox" checked={edit.writes} onChange={(e) => setEdit({ ...edit, writes: e.target.checked })} />{tr("Enable issue creation and comments with approval")}</label>
      <button className="btn primary" disabled={busy || privateMode}>{tr("Save changes")}</button>
    </form></Modal>}
    {remove && <Modal title={tr("Disconnect")} onClose={() => setRemove(null)}><p>{remove.provider}</p><p>{tr("Local connection credentials will be removed. Revoke remote consent or tokens separately in your provider account.")}</p><button className="btn primary" disabled={busy} onClick={() => action(async () => { await api("/development/" + remove.provider, { method: "DELETE", body: JSON.stringify(context) }); setRemove(null); })}>{tr("Disconnect")}</button></Modal>}
  </div>;
}
