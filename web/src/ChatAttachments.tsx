import React, { useEffect, useRef, useState } from "react";
import { api, type Json } from "./api";
import AppleHealth, { type HealthAttachment } from "./AppleHealth";
import { Badge, Modal, formatDate } from "./components";
import { t as tr, useI18n } from "./i18n";
import ScreenAttachmentPicker, { type ScreenAttachment, type ScreenCaptureState } from "./ScreenAttachment";

export const MAX_DOCUMENT_ATTACHMENTS = 10;
export type DocumentAttachment = { id: string; name: string };
type StoredDocument = DocumentAttachment & {
  private?: boolean;
  created_at: string;
  expires_at?: string;
  sha256: string;
};
type TemporaryFile = { id: string; name: string; expires_at: string; private?: boolean };

export default function ChatAttachments({ scope, privateMode, privacyRevision, sessionId, selected, healthAttached, screenAttached, screenCapture, isCurrent, onSelect, onAttachHealth, onAttachScreen, onClose, notify }: {
  scope: string;
  privateMode: boolean;
  privacyRevision: number;
  sessionId: string;
  selected: DocumentAttachment[];
  healthAttached: boolean;
  screenAttached: boolean;
  screenCapture: ScreenCaptureState;
  isCurrent: () => boolean;
  onSelect: React.Dispatch<React.SetStateAction<DocumentAttachment[]>>;
  onAttachHealth: (attachment: HealthAttachment | null) => void;
  onAttachScreen: (attachment: ScreenAttachment) => boolean;
  onClose: () => void;
  notify: (message: string, error?: boolean) => void;
}) {
  useI18n();
  const [items, setItems] = useState<StoredDocument[]>([]);
  const [temporaryFiles, setTemporaryFiles] = useState<TemporaryFile[]>([]);
  const [source, setSource] = useState<Json | null>(null);
  const [remove, setRemove] = useState<StoredDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [retention, setRetention] = useState(30);
  const [refresh, setRefresh] = useState(0);
  const [showHealth, setShowHealth] = useState(false);
  const uploadRequest = useRef<AbortController | null>(null);
  const readRequests = useRef<AbortController | null>(null);
  const context = { scope, private: String(privateMode), session_id: sessionId };

  useEffect(() => {
    const controller = new AbortController();
    readRequests.current = controller;
    const query = new URLSearchParams(context);
    api<StoredDocument[]>("/documents?" + query, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setItems(result); })
      .catch(error => { if (!controller.signal.aborted) notify(error.message, true); });
    api<TemporaryFile[]>("/lab/files?" + query, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setTemporaryFiles(result); })
      .catch(() => {});
    return () => controller.abort();
  }, [scope, privateMode, sessionId, refresh]);

  useEffect(() => () => uploadRequest.current?.abort(), []);

  async function upload(files: FileList | null) {
    if (!files?.length || busy || uploadRequest.current) return;
    if (selected.length + files.length > MAX_DOCUMENT_ATTACHMENTS) {
      notify("Attach at most ten documents.", true);
      return;
    }
    const batch = Array.from(files);
    if (batch.some(file => file.size > 3_000_000)) {
      notify("Choose a file of at most 3 MB.", true);
      return;
    }
    const controller = new AbortController();
    uploadRequest.current = controller;
    setBusy(true);
    try {
      for (const file of batch) {
        const content = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onerror = () => reject(reader.error);
          reader.onload = () => resolve(String(reader.result).split(",")[1]);
          reader.readAsDataURL(file);
        });
        if (controller.signal.aborted) return;
        const { id, name } = await api<DocumentAttachment>("/documents", {
          method: "POST",
          signal: controller.signal,
          body: JSON.stringify({
            scope,
            private: privateMode,
            privacy_revision: privacyRevision,
            session_id: sessionId,
            name: file.name,
            content,
            retention_days: retention,
          }),
        });
        if (controller.signal.aborted) return;
        onSelect(current => current.length < MAX_DOCUMENT_ATTACHMENTS ? [...current, { id, name }] : current);
      }
    } catch (error: any) {
      if (!controller.signal.aborted) notify(error.message, true);
    } finally {
      uploadRequest.current = null;
      if (!controller.signal.aborted) {
        setBusy(false);
        setRefresh(current => current + 1);
      }
    }
  }

  async function read(id: string, part = 1) {
    try {
      setSource(await api("/documents/" + id + "?" + new URLSearchParams({ ...context, part: String(part) })));
    } catch (error: any) {
      notify(error.message, true);
    }
  }

  async function download(id: string) {
    const signal = readRequests.current?.signal;
    if (!signal || signal.aborted) return;
    try {
      const file = await api<{ content: string; mime: string; name: string }>(
        "/lab/files/" + encodeURIComponent(id) + "?" + new URLSearchParams(context), { signal },
      );
      if (signal.aborted) return;
      const bytes = Uint8Array.from(atob(file.content), character => character.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], { type: file.mime }));
      const link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error: any) {
      if (!signal.aborted) notify(error.message, true);
    }
  }

  if (source) return <Modal title={source.name} onClose={() => setSource(null)}>
    <div className="modal-body assistant-card">
      <Badge>{tr(source.state)}</Badge>
      {(source.warnings || []).map((warning: string, i: number) => <p key={i} role="status">{warning}</p>)}
      {source.parts.map((part: Json) => <article key={part.part}>
        <h3>{tr("Part")} {part.part}</h3>
        <small>{part.citation} · {part.method}{part.confidence != null && " · " + Math.round(part.confidence * 100) + "%"}</small>
        <p style={{ whiteSpace: "pre-wrap" }}>{part.text || tr("No text extracted from this part.")}</p>
      </article>)}
      {source.more && <button className="btn" onClick={() => read(source.id, source.parts.at(-1).part + 1)}>{tr("Next parts")}</button>}
    </div>
  </Modal>;

  if (remove) return <Modal title={tr("Confirm deletion")} onClose={() => setRemove(null)}>
    <div className="modal-body assistant-form">
      <p>{remove.name}</p>
      <p>{tr("Deletes the stored source extraction. Existing conversation results follow history retention.")}</p>
      <button className="btn primary" disabled={busy} onClick={async () => {
        setBusy(true);
        try {
          await api("/documents/" + remove.id, {
            method: "DELETE",
            body: JSON.stringify({ scope, privacy_revision: privacyRevision, session_id: sessionId }),
          });
          onSelect(current => current.filter(item => item.id !== remove.id));
          setRemove(null);
          setRefresh(current => current + 1);
        } catch (error: any) {
          notify(error.message, true);
        } finally {
          setBusy(false);
        }
      }}>{tr("Delete")}</button>
    </div>
  </Modal>;

  return <Modal title={tr("Add attachments")} onClose={onClose}>
    <div className="modal-body">
      <ScreenAttachmentPicker state={screenCapture} disabled={busy}
        context={{ scope, privacy_revision: privacyRevision, session_id: sessionId }}
        isCurrent={isCurrent} onAttach={onAttachScreen} notify={notify} />
      <div className="assistant-card assistant-form" onDragOver={event => event.preventDefault()} onDrop={event => {
        event.preventDefault();
        void upload(event.dataTransfer.files);
      }}>
        <label>{tr("Choose or drop documents or screenshots")}
          <input disabled={busy || selected.length >= MAX_DOCUMENT_ATTACHMENTS} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg" onChange={event => {
            void upload(event.target.files);
            event.target.value = "";
          }} />
        </label>
        <p>{tr("PDF, DOCX, text, PNG or JPEG. Maximum 3 MB and 30 PDF pages. Text is extracted locally; no automatic memory ingestion.")}</p>
        {privateMode ? <p>{tr("Private attachments stay in RAM for one hour and disappear after restart.")}</p> : <label>{tr("Delete after (days)")}
          <input type="number" min={1} max={365} disabled={busy} value={retention} onChange={event => setRetention(Number(event.target.value))} />
        </label>}
        {busy && <p role="status">{tr("Extracting document evidence…")}</p>}
      </div>
      {items.length > 0 && <details className="assistant-card">
        <summary>{tr("Previously uploaded documents")}</summary>
        {items.map(item => {
          const attached = selected.some(attachment => attachment.id === item.id);
          return <article key={item.id}>
            <label><input type="checkbox" checked={attached} disabled={busy || (!attached && selected.length >= MAX_DOCUMENT_ATTACHMENTS)} onChange={event => {
              const checked = event.target.checked;
              onSelect(current => checked ? [...current, { id: item.id, name: item.name }] : current.filter(attachment => attachment.id !== item.id));
            }} /> {item.name}</label>
            <p>{item.private && <Badge>{tr("Private")}</Badge>} {formatDate(item.created_at)} {item.expires_at && " — " + formatDate(item.expires_at)}</p>
            <small>SHA-256: {item.sha256}</small>
            <div className="assistant-actions">
              <button className="btn" disabled={busy} onClick={() => read(item.id)}>{tr("Read source")}</button>
              <button className="btn" disabled={busy || (privateMode && !item.private)} onClick={() => setRemove(item)}>{tr("Delete")}</button>
            </div>
          </article>;
        })}
      </details>}
      {temporaryFiles.length > 0 && <details className="assistant-card">
        <summary>{tr("Download temporary files")}</summary>
        <p>{tr("Temporary files expire after one hour. Private files stay in memory.")}</p>
        {temporaryFiles.map(file => <article key={file.id}>
          <p>{file.name} {file.private && <Badge>{tr("Private")}</Badge>}</p>
          <div className="assistant-actions">
            <small>{formatDate(file.expires_at)}</small>
            <button className="btn" aria-label={tr("Download {name}", { name: file.name })} onClick={() => void download(file.id)}>{tr("Download")}</button>
          </div>
        </article>)}
      </details>}
      <details className="assistant-card" onToggle={event => setShowHealth(event.currentTarget.open)}>
        <summary>{tr("Apple Health export (XML or ZIP, up to 64 MB)")}</summary>
        {showHealth && <AppleHealth scope={scope} privateMode={privateMode} privacyRevision={privacyRevision} notify={notify} onAttach={onAttachHealth} />}
      </details>
      <div className="assistant-actions">
        <Badge>{tr("Attached sources")} · {selected.length + Number(healthAttached) + Number(screenAttached)}</Badge>
        <button className="btn primary" disabled={busy} onClick={onClose}>{tr("Back to chat")}</button>
      </div>
    </div>
  </Modal>;
}
