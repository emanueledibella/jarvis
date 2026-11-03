import React, { useEffect, useState } from "react";
import { api, post, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { Badge, Modal, SectionTitle, formatDate } from "./components";

export default function Documents({ scope, privateMode, privacyRevision, sessionId, selected, onSelect, onAsk, notify }: {
  scope: string; privateMode: boolean; privacyRevision: number; sessionId: string; selected: string[];
  onSelect: (ids: string[]) => void; onAsk: (prompt: string, ids: string[]) => void; notify: (message: string, error?: boolean) => void;
}) {
  useI18n();
  const [items, setItems] = useState<Json[]>([]);
  const [source, setSource] = useState<Json | null>(null);
  const [remove, setRemove] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [retention, setRetention] = useState(30);
  const [refresh, setRefresh] = useState(0);
  const context = { scope, private: String(privateMode), session_id: sessionId };
  useEffect(() => {
    const controller = new AbortController();
    api("/documents?" + new URLSearchParams(context), { signal: controller.signal }).then(setItems)
      .catch((e) => { if (!controller.signal.aborted) notify(e.message, true); });
    return () => controller.abort();
  }, [scope, privateMode, sessionId, refresh]);
  async function upload(files: FileList | null) {
    if (!files?.length || busy) return;
    setBusy(true);
    try {
      for (const file of Array.from(files).slice(0, 10)) {
        if (file.size > 3_000_000) throw new Error("Choose a file of at most 3 MB.");
        const content = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader(); reader.onerror = reject; reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.readAsDataURL(file);
        });
        await post("/documents", { scope, private: privateMode, privacy_revision: privacyRevision, session_id: sessionId, name: file.name, content, retention_days: retention });
      }
      setRefresh((x) => x + 1);
    } catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  async function read(key: string, part = 1) {
    try { setSource(await api("/documents/" + key + "?" + new URLSearchParams({ ...context, part: String(part) }))); }
    catch (e: any) { notify(e.message, true); }
  }
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("SOURCE EVIDENCE")} title={tr("Documents")}
      description={tr("Attach documents to a conversation with verifiable source and part references.")} />
    <div className="assistant-card assistant-form" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}>
      <label>{tr("Choose or drop documents")}<input disabled={busy} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} /></label>
      <p>{tr("PDF, DOCX, text, PNG or JPEG. Maximum 3 MB and 30 PDF pages. Text is extracted locally; no automatic memory ingestion.")}</p>
      {privateMode ? <p>{tr("Private attachments stay in RAM for one hour and disappear after restart.")}</p> : <label>{tr("Delete after (days)")}<input type="number" min={1} max={365} value={retention} onChange={(e) => setRetention(Number(e.target.value))} /></label>}
      {busy && <p role="status">{tr("Extracting document evidence…")}</p>}
    </div>
    <div className="assistant-actions">
      <button className="btn primary" disabled={!selected.length} onClick={() => onAsk(tr("Summarize the attached documents, cite the relevant sections, and flag missing or uncertain text."), selected)}>{tr("Discuss selected documents")}</button>
      <button className="btn" disabled={selected.length !== 2} onClick={() => onAsk(tr("Compare the two attached documents. Explain meaningful text changes with section references and any limits of the comparison."), selected)}>{tr("Compare two sources")}</button>
    </div>
    <section className="assistant-card">
      {items.map((item) => <article key={item.id}>
        <label><input type="checkbox" checked={selected.includes(item.id)} disabled={!selected.includes(item.id) && selected.length >= 10} onChange={(e) => onSelect(e.target.checked ? [...selected, item.id] : selected.filter((id) => id !== item.id))} /> {item.name}</label>
        <p>{item.private && <Badge>{tr("Private")}</Badge>} {formatDate(item.created_at)} {item.expires_at && " — " + formatDate(item.expires_at)}</p>
        <small>SHA-256: {item.sha256}</small>
        <div className="assistant-actions"><button className="btn" onClick={() => read(item.id)}>{tr("Read source")}</button><button className="btn" disabled={busy || (privateMode && !item.private)} onClick={() => setRemove(item)}>{tr("Delete")}</button></div>
      </article>)}
    </section>
    {source && <Modal title={source.name} onClose={() => setSource(null)}>
      <Badge>{tr(source.state)}</Badge>
      {(source.warnings || []).map((warning: string, i: number) => <p key={i} role="status">{warning}</p>)}
      {source.parts.map((part: Json) => <article key={part.part}><h3>{tr("Part")} {part.part}</h3><small>{part.citation} · {part.method}{part.confidence != null && " · " + Math.round(part.confidence * 100) + "%"}</small><p style={{ whiteSpace: "pre-wrap" }}>{part.text || tr("No text extracted from this part.")}</p></article>)}
      {source.more && <button className="btn" onClick={() => read(source.id, source.parts.at(-1).part + 1)}>{tr("Next parts")}</button>}
    </Modal>}
    {remove && <Modal title={tr("Confirm deletion")} onClose={() => setRemove(null)}><p>{remove.name}</p><p>{tr("Deletes the stored source extraction. Existing conversation results follow history retention.")}</p>
      <button className="btn primary" disabled={busy} onClick={async () => {
        setBusy(true); try { await api("/documents/" + remove.id, { method: "DELETE", body: JSON.stringify({ scope, privacy_revision: privacyRevision, session_id: sessionId }) }); onSelect(selected.filter((id) => id !== remove.id)); setRemove(null); setRefresh((x) => x + 1); }
        catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
      }}>{tr("Delete")}</button>
    </Modal>}
  </div>;
}
