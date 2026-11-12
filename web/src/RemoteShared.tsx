import React, { useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { api, post } from "./api";
import { t as tr } from "./i18n";
import { nativePlugin, remoteClient } from "./remoteClient";

export default function RemoteShared({ notify }: { notify: (s: string) => void }) {
  const [items, setItems] = useState<Record<string, any>[]>([]), [busy, setBusy] = useState(false);
  async function refresh() {
    if (!Capacitor.isNativePlatform() || document.visibilityState === "hidden") return;
    try { setItems((await nativePlugin.shared()).items); } catch { /* Optional OS inbox may be empty or locked. */ }
  }
  useEffect(() => {
    void refresh(); const timer = setInterval(() => void refresh(), 4000);
    return () => clearInterval(timer);
  }, []);
  if (!items.length) return null;
  async function attach(item: Record<string, any>) {
    setBusy(true);
    const sessionId = remoteClient.sessionId;
    try {
      const session = await api("/voice/session");
      let content = item.content;
      if (typeof item.text === "string") {
        const bytes = new TextEncoder().encode(item.text);
        let raw = ""; for (const byte of bytes) raw += String.fromCharCode(byte);
        content = btoa(raw);
      }
      const source = await post("/documents", { name: item.name || "shared-source.txt", content,
        scope: session.scope, private: session.private, privacy_revision: session.revision, session_id: sessionId });
      if (remoteClient.sessionId !== sessionId) throw new Error(tr("Conversation changed. Review the uploaded source before attaching it."));
      const attached = window.dispatchEvent(new CustomEvent("jarvis-shared-source", {
        cancelable: true,
        detail: { id: source.id, name: source.name, sessionId, revision: session.revision },
      }));
      await nativePlugin.removeShared({ id: item.id }); await refresh();
      notify(tr(attached ? "Source attached. Write your request in chat." : "Source uploaded. Choose it from previously uploaded documents in chat."));
    } catch (e: any) { notify(e.message); } finally { setBusy(false); }
  }
  return <aside className="remote-shared" aria-label={tr("Shared sources")}>
    <strong>{tr("Shared sources")}</strong><p>{tr("Choose the current conversation and privacy, then attach. Sources waiting here expire after 15 minutes.")}</p>
    {items.map(item => <div key={item.id}><span>{item.name || String(item.text || "").slice(0, 180)}</span>
      <button className="btn" disabled={busy} onClick={() => void attach(item)}>{tr("Attach to this conversation")}</button>
      <button className="btn" disabled={busy} onClick={async () => { await nativePlugin.removeShared({ id: item.id }); await refresh(); }}>{tr("Discard")}</button>
    </div>)}
  </aside>;
}
