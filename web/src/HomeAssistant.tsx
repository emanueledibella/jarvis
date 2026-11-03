import React, { useEffect, useState } from "react";
import { api, post, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, Modal, SectionTitle } from "./components";

function HomeResult({ result }: { result: Json }) {
  const data = result.verification?.data?.data || result.data;
  const entities: Json[] = Array.isArray(data?.entities) ? data.entities : [];
  return <div role="status">
    {result.state === "accepted" && <p>{tr("Home Assistant accepted the command. State verification is separate from acceptance.")}</p>}
    {result.verification && <p>{tr(result.verification.state === "readback" ? "Current state was read after the command." : "Current state could not be verified. Check Home Assistant before repeating the command.")}</p>}
    {entities.map((entity, index) => <article key={entity.entity_id || index}><strong>{entity.name || entity.entity_id}</strong><p>{String(entity.state ?? tr("Unknown"))}</p></article>)}
    <details><summary>{tr("Review server response")}</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(result, null, 2)}</pre></details>
  </div>;
}

export default function HomeAssistant({ scope, privateMode, privacyRevision, notify, onAsk }: {
  scope: string; privateMode: boolean; privacyRevision: number; notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [config, setConfig] = useState<Json | null>(null);
  const [tools, setTools] = useState<Json[]>([]);
  const [history, setHistory] = useState<Json[]>([]);
  const [selected, setSelected] = useState("");
  const [argumentsText, setArgumentsText] = useState("{}");
  const [result, setResult] = useState<Json | null>(null);
  const [proposal, setProposal] = useState<Json | null>(null);
  const [removing, setRemoving] = useState(false);
  const [reconcile, setReconcile] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const context = { scope, privacy_revision: privacyRevision };
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api("/home-assistant?scope=" + scope, { signal: controller.signal }), api("/home-assistant/history?scope=" + scope, { signal: controller.signal })]).then(([value, actions]) => {
      if (!controller.signal.aborted) {
        setConfig({ url: "https://homeassistant.local:8123/api/mcp", auth: "bearer", allow_insecure_lan: false, tls_ca_file: "", oauth_client_metadata_url: "", oauth_callback_port: 8766, read_tools: [], write_tools: [], ...value, token: "" });
        setHistory(actions);
        setTools(value.status?.tools || []);
      }
    }).catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope, refresh]);
  async function action(run: () => Promise<unknown>) {
    setBusy(true); try { await run(); } catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  function payload() {
    return { ...context, ...Object.fromEntries(["url", "auth", "token", "allow_insecure_lan", "tls_ca_file", "oauth_client_metadata_url", "oauth_callback_port", "read_tools", "write_tools"].map((key) => [key, config?.[key]])) };
  }
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("YOUR CONNECTED HOME")} title="Home Assistant"
      description={tr("Connect the MCP server you control and explicitly choose its tool permissions.")} />
    <section className="assistant-card">
      <ol>
        <li>{tr("In Home Assistant, add the Model Context Protocol Server integration and copy its MCP URL.")}</li>
        <li>{tr("Disable Expose all LLM APIs, select the intended Assist API, and expose only the devices Jarvis should access.")}</li>
        <li>{tr("Review whether the server requires an administrator. Use the narrowest account and entity exposure appropriate for your home.")}</li>
        <li>{tr("Choose OAuth browser consent or create a dedicated long-lived token under your Home Assistant profile security settings.")}</li>
        <li>{tr("Save, connect and discover tools. Newly discovered tools are disabled until you grant them.")}</li>
      </ol>
      <a href="https://www.home-assistant.io/integrations/mcp_server/" target="_blank" rel="noreferrer">{tr("Official Home Assistant setup")}</a>
    </section>
    {config && <form className="assistant-card assistant-form" onSubmit={(e) => { e.preventDefault(); action(async () => { await api("/home-assistant", { method: "PUT", body: JSON.stringify(payload()) }); setRefresh((x) => x + 1); notify("Home Assistant configuration saved."); }); }}>
      <h2>{tr("Connection")}</h2>
      <label>{tr("MCP server URL")}<input type="url" required maxLength={2000} value={config.url} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, url: e.target.value })} /></label>
      <label>{tr("Authentication")}<select value={config.auth} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, auth: e.target.value })}><option value="bearer">{tr("Dedicated bearer token")}</option><option value="oauth">{tr("OAuth browser consent")}</option></select></label>
      {config.auth === "bearer" ? <label>{tr("Home Assistant token")}<input type="password" autoComplete="off" maxLength={4000} value={config.token} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, token: e.target.value })} /><small>{tr("Blank preserves a token only for the same endpoint and authentication mode.")}</small></label> : <>
        <label>{tr("Local OAuth callback port")}<input type="number" min={1024} max={65535} value={config.oauth_callback_port} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, oauth_callback_port: Number(e.target.value) })} /></label>
        <label>{tr("Public OAuth client metadata URL (optional)")}<input type="url" value={config.oauth_client_metadata_url} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, oauth_client_metadata_url: e.target.value })} /></label>
        <p>{tr("Default OAuth uses a loopback client ID and callback on the same host and port. If your server requires a public client metadata document, it must declare the exact loopback callback.")}</p>
      </>}
      <label>{tr("CA certificate file (optional)")}<input value={config.tls_ca_file} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, tls_ca_file: e.target.value })} /></label>
      <label><input type="checkbox" checked={config.allow_insecure_lan} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, allow_insecure_lan: e.target.checked })} />{tr("Allow unencrypted HTTP to an explicitly chosen private IPv4 LAN address")}</label>
      {config.allow_insecure_lan && <p role="status">{tr("HTTP sends credentials and home data without encryption. Only literal RFC1918 addresses are allowed; use HTTPS when available.")}</p>}
      <div className="assistant-actions">
        <button className="btn primary" disabled={privateMode || busy}>{tr("Save changes")}</button>
        <button className="btn" type="button" disabled={!config.configured || privateMode || busy} onClick={() => action(async () => { await post("/home-assistant/connect", context); notify("Complete provider consent if requested, then discover tools."); })}>{tr("Connect")}</button>
        <button className="btn" type="button" disabled={!config.configured || busy} onClick={() => action(async () => setTools(await api("/home-assistant/tools?scope=" + scope)))}>{tr("Discover tools")}</button>
        <button className="btn" type="button" disabled={!config.configured || privateMode || busy} onClick={() => setRemoving(true)}>{tr("Disconnect")}</button>
      </div>
      <h2>{tr("Tool permissions")}</h2>
      <p>{tr("Read grants are limited to known read-only tools. Other tools can change devices and require action review. Save permission changes before use.")}</p>
      {tools.map((tool) => {
        const read = config.known_read_tools?.includes(tool.name) || ["GetLiveContext", "HassGetState", "HassGetWeather", "GetDateTime", "GetCurrentTime"].includes(tool.name);
        const field = read ? "read_tools" : "write_tools";
        return <article key={tool.name}><label><input type="checkbox" checked={config[field].includes(tool.name)} disabled={privateMode || busy} onChange={(e) => setConfig({ ...config, [field]: e.target.checked ? [...config[field], tool.name] : config[field].filter((x: string) => x !== tool.name) })} />{tool.name} <Badge>{tr(read ? "Read only" : "Action with approval")}</Badge></label>
          <p>{tool.description}</p><details><summary>{tr("Inspect argument schema")}</summary><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(tool.schema, null, 2)}</pre></details>
        </article>;
      })}
    </form>}
    {config?.configured && <section className="assistant-card assistant-form">
      <h2>{tr("Use a permitted tool")}</h2>
      <select aria-label={tr("Home Assistant tool")} value={selected} onChange={(e) => { setSelected(e.target.value); setArgumentsText("{}"); setResult(null); }}><option value="">{tr("Choose a tool")}</option>{tools.filter((t) => config.read_tools.includes(t.name) || config.write_tools.includes(t.name)).map((t) => <option key={t.name}>{t.name}</option>)}</select>
      <label>{tr("Exact arguments (JSON)")}<textarea maxLength={12000} value={argumentsText} onChange={(e) => setArgumentsText(e.target.value)} /></label>
      <div className="assistant-actions">
        <button className="btn primary" disabled={!selected || busy || (config.write_tools.includes(selected) && privateMode)} onClick={() => action(async () => {
          const arguments_ = JSON.parse(argumentsText);
          if (!arguments_ || Array.isArray(arguments_) || typeof arguments_ !== "object") throw new Error("Arguments must be a JSON object.");
          const call = { ...context, tool: selected, arguments: arguments_ };
          if (config.read_tools.includes(selected)) setResult(await post("/home-assistant/read", call));
          else setProposal(await post("/home-assistant/proposals", call));
        })}>{tr(config.read_tools.includes(selected) ? "Read state" : "Review action")}</button>
        <button className="btn" onClick={() => onAsk(tr("Read the permitted Home Assistant state and explain the relevant devices and sensors. Do not change any devices."))}>{tr("Ask about my home")}</button>
      </div>
      {result && <HomeResult result={result} />}
    </section>}
    <section className="assistant-card">
      <h2>{tr("Recent home actions")}</h2>
      <button className="btn" onClick={() => setRefresh((x) => x + 1)}>{tr("Refresh")}</button>
      {history.map((item) => <article key={item.id}><strong>{item.tool}</strong> <Badge>{tr(item.state)}</Badge><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(item.arguments, null, 2)}</pre>
        {item.state === "unknown" && <button className="btn" disabled={privateMode} onClick={() => setReconcile({ ...item, evidence: "" })}>{tr("Verify uncertain result")}</button>}
      </article>)}
    </section>
    {proposal && <Modal title={tr("Review Home Assistant action")} onClose={() => setProposal(null)}>
      <h3>{proposal.tool}</h3><pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(proposal.arguments, null, 2)}</pre>
      <p>{tr("This can change physical devices. Approval binds these exact arguments and current permissions for five minutes.")}</p>
      <button className="btn primary" disabled={busy || privateMode} onClick={() => action(async () => { setResult(await post("/home-assistant/proposals/" + proposal.id + "/execute", { ...context, sha256: proposal.sha256 })); setProposal(null); setRefresh((x) => x + 1); })}>{tr("Execute this exact action")}</button>
    </Modal>}
    {removing && <Modal title={tr("Disconnect")} onClose={() => setRemoving(false)}><p>{tr("Remove the local Home Assistant connection and grants. Revoke the provider token or consent separately if needed.")}</p><button className="btn primary" disabled={busy} onClick={() => action(async () => { await api("/home-assistant", { method: "DELETE", body: JSON.stringify(context) }); setRemoving(false); setTools([]); setRefresh((x) => x + 1); })}>{tr("Disconnect")}</button></Modal>}
    {reconcile && <Modal title={tr("Verify uncertain result")} onClose={() => setReconcile(null)}><p>{tr("Check the actual device state and Home Assistant logs before choosing an outcome. No retry occurs automatically.")}</p><textarea aria-label={tr("Verification evidence")} minLength={10} maxLength={1000} value={reconcile.evidence} onChange={(e) => setReconcile({ ...reconcile, evidence: e.target.value })} />
      {["accepted", "not_executed"].map((outcome) => <button className="btn" key={outcome} disabled={busy || reconcile.evidence.length < 10} onClick={() => action(async () => { await post("/home-assistant/history/" + reconcile.id + "/reconcile", { ...context, outcome, evidence: reconcile.evidence }); setReconcile(null); setRefresh((x) => x + 1); })}>{tr(outcome === "accepted" ? "Verified accepted" : "Verified not executed")}</button>)}
    </Modal>}
  </div>;
}
