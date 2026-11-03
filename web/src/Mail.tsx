import React, { useEffect, useState } from "react";
import { Mail as MailIcon, Plus, RefreshCw } from "lucide-react";
import { api, post, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, Modal, SectionTitle } from "./components";

const recipients = (value: string) => value.split(/[,;]/).map((x) => x.trim()).filter(Boolean);
const draftFields = (value: Json) => Object.fromEntries(["account_id", "to", "cc", "bcc", "subject", "body", "reply_message_id"].map((key) => [key, ["to", "cc", "bcc"].includes(key) ? recipients(value[key + "_text"] ?? value[key].join(",")) : value[key]]));
export default function Mail({ scope, privateMode, privacyRevision, notify, onAsk }: {
  scope: string; privateMode: boolean; privacyRevision: number; notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [accounts, setAccounts] = useState<Json[]>([]);
  const [drafts, setDrafts] = useState<Json[]>([]);
  const [selected, setSelected] = useState("");
  const [messages, setMessages] = useState<Json>({ messages: [], next: "" });
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<Json | null>(null);
  const [account, setAccount] = useState<Json | null>(null);
  const [draft, setDraft] = useState<Json | null>(null);
  const [review, setReview] = useState<Json | null>(null);
  const [confirmation, setConfirmation] = useState<Json | null>(null);
  const [consent, setConsent] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const context = { scope, privacy_revision: privacyRevision };
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api("/mail/accounts?scope=" + scope, { signal: controller.signal }), api("/mail/drafts?scope=" + scope, { signal: controller.signal })])
      .then(([a, d]) => { if (!controller.signal.aborted) { setAccounts(a); setDrafts(d); setSelected((old) => a.some((x: Json) => x.id === old) ? old : a[0]?.id || ""); } })
      .catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope, refresh]);
  useEffect(() => { setMessages({ messages: [], next: "" }); setMessage(null); }, [selected]);
  async function work(run: () => Promise<unknown>) {
    setBusy(true);
    try { await run(); setRefresh((x) => x + 1); }
    catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  async function load(cursor = "") {
    if (!selected) return;
    await work(async () => {
      const result = await api("/mail/accounts/" + selected + "/messages?" + new URLSearchParams({ scope, query, cursor }));
      setMessages(result);
    });
  }
  const newDraft = () => setDraft({ account_id: selected, to: [], cc: [], bcc: [], subject: "", body: "", reply_message_id: null });
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("CONNECTED MAIL")} title={tr("Mail")}
      description={tr("Read your messages and review local drafts before sending.")}
      action={<button className="btn" disabled={privateMode} onClick={() => setAccount({ provider: "gmail", label: "", client_id: "", client_secret: "", sending: false })}><Plus size={15} />{tr("Add mail account")}</button>} />
    {privateMode && <p>{tr("Leave the private session to save persistent changes.")}</p>}
    <div className="assistant-card">
      <p>{tr("Use dedicated OAuth app credentials. Gmail needs a Desktop client and Gmail API enabled. Microsoft needs delegated User.Read, Mail.Read and optional Mail.Send. Register this loopback redirect:")}</p>
      <code>http://127.0.0.1:{location.port || "8765"}/oauth/mail/callback</code>
      {accounts.map((item) => <article key={item.id}><strong>{item.label}</strong> · {item.email_address || item.provider} <Badge>{tr(item.connected ? "Connected" : "Not connected")}</Badge>
        <div className="assistant-actions">
          <button className="btn" disabled={privateMode || busy} onClick={() => work(async () => { setConsent((await post("/mail/accounts/" + item.id + "/connect", context)).url); })}>{tr("Connect")}</button>
          <button className="btn" disabled={privateMode} onClick={() => setAccount({ ...item, client_secret: "" })}>{tr("Configure")}</button>
          <button className="btn" disabled={privateMode} onClick={() => setConfirmation({ kind: "account", item })}>{tr("Disconnect")}</button>
        </div>
      </article>)}
      {consent && <p><a className="btn primary" href={consent} target="_blank" rel="noreferrer">{tr("Open provider consent")}</a></p>}
      <button className="btn" onClick={() => setRefresh((x) => x + 1)}><RefreshCw size={15} />{tr("Refresh connection")}</button>
    </div>
    <div className="assistant-actions">
      <select aria-label={tr("Mail account")} value={selected} onChange={(e) => setSelected(e.target.value)}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select>
      <input aria-label={tr("Search mail")} maxLength={500} value={query} onChange={(e) => setQuery(e.target.value)} />
      <button className="btn" disabled={!selected || busy} onClick={() => load()}>{tr("Read messages")}</button>
      <button className="btn" disabled={!selected || privateMode} onClick={newDraft}><MailIcon size={15} />{tr("New draft")}</button>
      <button className="btn" disabled={!selected} onClick={() => onAsk(tr("Help me triage mail from account {account}. Read relevant messages, distinguish explicit requests from inferred urgency, cite sources and suggest replies or activities. Do not send or save anything.", { account: selected }))}>{tr("Help me triage")}</button>
    </div>
    <div className="assistant-grid">
      <section className="assistant-card">
        <h2>{tr("Messages")}</h2>
        {messages.messages.map((item: Json) => <article key={item.id}><button className="btn" onClick={() => work(async () => setMessage(await api("/mail/accounts/" + selected + "/messages/" + encodeURIComponent(item.id) + "?scope=" + scope)))}>{item.subject || tr("No subject")}</button><p>{item.from}</p><p>{item.snippet}</p></article>)}
        {!!messages.next && <button className="btn" disabled={busy} onClick={() => load(messages.next)}>{tr("Next page")}</button>}
        {message && <article><h3>{message.subject}</h3><p>{message.from}</p><p style={{ whiteSpace: "pre-wrap" }}>{message.body}</p>{message.truncated && <p>{tr("Message content is truncated.")}</p>}
          <button className="btn" disabled={privateMode} onClick={() => { const from = message.from.match(/<([^>]+)>/)?.[1] || message.from; setDraft({ account_id: selected, to: [from], cc: [], bcc: [], subject: /^re:/i.test(message.subject) ? message.subject : "Re: " + message.subject, body: "", reply_message_id: message.id }); }}>{tr("Reply with a draft")}</button>
          <button className="btn" onClick={() => onAsk(tr("Suggest a reply to message {message} from mail account {account}, using the relevant context. Show me the text without sending or saving it.", { message: message.id, account: selected }))}>{tr("Suggest a reply")}</button>
        </article>}
      </section>
      <section className="assistant-card">
        <h2>{tr("Local drafts")}</h2>
        {drafts.map((item) => <article key={item.id}><strong>{item.content.subject || tr("No subject")}</strong><p>{item.content.to.join(", ")}</p><Badge>{tr(item.state)}</Badge>
          <div className="assistant-actions">
            {item.state === "draft" && <button className="btn" disabled={privateMode} onClick={() => setDraft({ ...item.content, id: item.id, revision: item.revision })}>{tr("Edit")}</button>}
            <button className="btn" onClick={() => setReview(item)}>{tr("Review draft")}</button>
            {!["sending", "unknown"].includes(item.state) && <button className="btn" disabled={privateMode} onClick={() => setConfirmation({ kind: "draft", item })}>{tr("Delete")}</button>}
          </div>
        </article>)}
      </section>
    </div>
    {account && <Modal title={tr("Mail account")} onClose={() => setAccount(null)}><form className="assistant-form" onSubmit={(e) => { e.preventDefault(); work(async () => { const { id, provider, label, client_id, client_secret, sending } = account; await post("/mail/accounts", { ...context, id, provider, label, client_id, client_secret, sending }); setAccount(null); setConsent(""); }); }}>
      <label>{tr("Provider")}<select value={account.provider} onChange={(e) => setAccount({ ...account, provider: e.target.value })}><option value="gmail">Gmail</option><option value="microsoft">Microsoft</option></select></label>
      {(["label", "client_id", "client_secret"] as const).map((field) => <label key={field}>{tr({ label: "Account label", client_id: "OAuth client ID", client_secret: "OAuth client secret" }[field])}<input required={field !== "client_secret"} type={field === "client_secret" ? "password" : "text"} autoComplete="off" maxLength={field === "client_secret" ? 1000 : 300} value={account[field]} onChange={(e) => setAccount({ ...account, [field]: e.target.value })} /></label>)}
      <label><input type="checkbox" checked={account.sending} onChange={(e) => setAccount({ ...account, sending: e.target.checked })} />{tr("Allow sending with separate provider consent")}</label>
      <p>{tr("Changing credentials or send permission requires a new connection. Blank secrets preserve the previous value.")}</p>
      <button className="btn primary" disabled={busy}>{tr("Save changes")}</button>
    </form></Modal>}
    {draft && <Modal title={tr("Local draft")} onClose={() => setDraft(null)}><form className="assistant-form" onSubmit={(e) => { e.preventDefault(); work(async () => { await api("/mail/drafts" + (draft.id ? "/" + draft.id : ""), { method: draft.id ? "PUT" : "POST", body: JSON.stringify({ ...context, ...draftFields(draft), revision: draft.revision }) }); setDraft(null); }); }}>
      <label>{tr("Mail account")}<select value={draft.account_id} onChange={(e) => setDraft({ ...draft, account_id: e.target.value, reply_message_id: null })}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
      {["to", "cc", "bcc"].map((field) => <label key={field}>{field.toUpperCase()}<input value={draft[field + "_text"] ?? draft[field].join(", ")} onChange={(e) => setDraft({ ...draft, [field + "_text"]: e.target.value })} /></label>)}
      <label>{tr("Subject")}<input maxLength={300} value={draft.subject} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} /></label>
      <label>{tr("Message body")}<textarea maxLength={50000} value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></label>
      <button className="btn primary" disabled={busy}>{tr("Save local draft")}</button>
    </form></Modal>}
    {review && <Modal title={tr("Review draft")} onClose={() => setReview(null)}>
      <p>{accounts.find((a) => a.id === review.account_id)?.email_address}</p>
      {["to", "cc", "bcc"].map((field) => <p key={field}>{field.toUpperCase()}: {review.content[field].join(", ")}</p>)}
      <h3>{review.content.subject}</h3><p style={{ whiteSpace: "pre-wrap" }}>{review.content.body}</p><p>{tr("Draft revision")}: {review.revision}</p>
      {review.state === "draft" && <button className="btn primary" disabled={busy || privateMode} onClick={() => work(async () => { await post("/mail/drafts/" + review.id + "/send", { ...context, revision: review.revision, sha256: review.sha256 }); setReview(null); notify("Message accepted by provider. Delivery is not yet verified."); })}>{tr("Send this exact message")}</button>}
      {review.state === "unknown" && <><p>{tr("Verify the provider Sent folder before resolving this uncertain result. Do not retry without evidence.")}</p>
        <textarea aria-label={tr("Verification evidence")} value={review.evidence || ""} onChange={(e) => setReview({ ...review, evidence: e.target.value })} />
        {["accepted", "not_executed"].map((outcome) => <button className="btn" key={outcome} disabled={busy || privateMode || (review.evidence || "").length < 10} onClick={() => work(async () => { await post("/mail/drafts/" + review.id + "/reconcile", { ...context, revision: review.revision, sha256: review.sha256, outcome, evidence: review.evidence }); setReview(null); })}>{tr(outcome === "accepted" ? "Verified accepted" : "Verified not sent")}</button>)}
      </>}
    </Modal>}
    {confirmation && <Modal title={tr("Confirm deletion")} onClose={() => setConfirmation(null)}><p>{confirmation.item.label || confirmation.item.content?.subject}</p><p>{tr("This removes local connection data or the selected draft. Provider consent can be revoked separately in your account.")}</p>
      <button className="btn primary" disabled={busy} onClick={() => work(async () => { const item = confirmation.item; await api("/mail/" + (confirmation.kind === "account" ? "accounts/" : "drafts/") + item.id, { method: "DELETE", body: JSON.stringify({ ...context, ...(confirmation.kind === "draft" ? { revision: item.revision, sha256: item.sha256 } : {}) }) }); setConfirmation(null); })}>{tr("Delete")}</button>
    </Modal>}
  </div>;
}
