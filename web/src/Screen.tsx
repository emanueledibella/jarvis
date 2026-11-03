import React, { useEffect, useState } from "react";
import { api, post, type Json } from "./api";
import { t as tr, useI18n } from "./i18n";
import { SectionTitle } from "./components";

export default function Screen({ scope, privacyRevision, sessionId, nativeAvailable, notify, onAsk }: {
  scope: string; privacyRevision: number; sessionId: string; nativeAvailable: boolean;
  notify: (message: string, error?: boolean) => void; onAsk: (prompt: string) => void;
}) {
  useI18n();
  const [capture, setCapture] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!capture) return; const timer = setTimeout(() => setCapture(null), 600000); return () => clearTimeout(timer); }, [capture]);
  async function choose() {
    setBusy(true);
    try { setCapture(await post("/screen/captures", { scope, privacy_revision: privacyRevision, session_id: sessionId })); }
    catch (e: any) { notify(e.message, true); } finally { setBusy(false); }
  }
  return <div className="page assistant-page">
    <SectionTitle eyebrow={tr("CHOOSE WHAT JARVIS SEES")} title={tr("Screen context")}
      description={tr("Choose one window for a single local capture. Nothing is monitored in the background.")} />
    <section className="assistant-card">
      <p>{tr("Captures stay in RAM for ten minutes. OCR runs locally. Asking for analysis sends extracted text to your selected model, which may be a cloud provider.")}</p>
      {!nativeAvailable && <p>{tr("Open the native Mac app, or upload a screenshot in Documents on this platform.")}</p>}
      <button className="btn primary" disabled={busy || !nativeAvailable} onClick={choose}>{tr(busy ? "Choose a window in the system picker…" : "Choose a window")}</button>
    </section>
    {capture && <section className="assistant-card">
      <h2>{tr("Local capture preview")}</h2>
      <img style={{ maxWidth: "100%", maxHeight: 480, objectFit: "contain" }} src={"data:image/jpeg;base64," + capture.image} alt={tr("Owner-selected window capture")} />
      <p>{tr("OCR confidence")}: {Math.round((capture.confidence || 0) * 100)}%</p>
      <p style={{ whiteSpace: "pre-wrap" }}>{capture.text}</p>
      <p>{tr("Text extraction can omit diagrams, controls and visual context.")}</p>
      <div className="assistant-actions">
        <button className="btn primary" onClick={() => onAsk(tr("Explain the window or error in capture {id}. Read the extracted text, flag recognition limits and suggest next steps without acting in applications.", { id: capture.id }))}>{tr("Explain this capture")}</button>
        <button className="btn" onClick={async () => { try { await api("/screen/captures/" + capture.id, { method: "DELETE", body: JSON.stringify({ scope, privacy_revision: privacyRevision, session_id: sessionId }) }); setCapture(null); } catch (e: any) { notify(e.message, true); } }}>{tr("Delete capture")}</button>
      </div>
    </section>}
  </div>;
}
