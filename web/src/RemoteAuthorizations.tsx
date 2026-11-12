import React, { useEffect, useState } from "react";
import { Modal } from "./components";
import { remoteClient } from "./remoteClient";
import { t as tr, useI18n } from "./i18n";
import { validAuthorizations, type Authorization } from "./authorizationPolicy";

export function ConsentLinks({ items }: { items: Authorization[] }) {
  useI18n();
  return <div className="modal-body remote-panel">
    <p>{tr("Open the browser to review and complete consent, then return to Jarvis. The connection is not complete yet.")}</p>
    {validAuthorizations(items).map(item => <article className="remote-device" key={item.url}>
      <strong>{tr("Authorize")} {item.name === "second_brain" ? "Second Brain" : item.name}</strong>
      <span className="remote-path">{new URL(item.url).origin}</span>
      <a className="btn primary" href={item.url} target="_blank" rel="noreferrer noopener">{tr("Open consent in the browser")}</a>
      <small>{tr("Expires in")} {Math.ceil(item.expires_in)} {tr("seconds. Check the connection status after granting consent.")}</small>
    </article>)}
  </div>;
}

export default function RemoteAuthorizations() {
  useI18n();
  const [items, setItems] = useState<Authorization[]>([]);
  const [dismissed, setDismissed] = useState("");
  useEffect(() => {
    if (!remoteClient.admin) return;
    let alive = true, busy = false;
    const update = async () => {
      if (busy) return;
      busy = true;
      try {
        const result = await remoteClient.json("authorizations");
        if (alive) setItems(validAuthorizations(result));
      } catch { if (alive) setItems([]); }
      finally { busy = false; }
    };
    void update();
    const timer = window.setInterval(() => void update(), 2000);
    window.addEventListener("jarvis-integration-connect", update);
    return () => { alive = false; window.clearInterval(timer); window.removeEventListener("jarvis-integration-connect", update); };
  }, []);
  const key = items.map(item => item.url).join("\n");
  if (!items.length) return null;
  return <>
    <div className="remote-notice" role="status">
      <span>{tr("Browser consent is required to finish connecting.")}</span>
      <button className="btn" onClick={() => setDismissed("")}>{tr("Review authorization")}</button>
    </div>
    {dismissed !== key && <Modal title={tr("Authorize connection")} onClose={() => setDismissed(key)}><ConsentLinks items={items} /></Modal>}
  </>;
}
