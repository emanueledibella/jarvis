import React, { useEffect, useRef, useState } from "react";
import { api, post } from "./api";
import { t as tr, useI18n } from "./i18n";

export default function IntegrationConnect({ name, label, notify, onConnected, disabled = false }: {
  name: string; label: string; disabled?: boolean;
  notify: (message: string, error?: boolean) => void; onConnected?: () => void;
}) {
  useI18n();
  const [state, setState] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(false), generation = useRef(0), initiated = useRef(false);
  const callbacks = useRef({ notify, onConnected });
  callbacks.current = { notify, onConnected };
  async function refresh() {
    const revision = generation.current;
    try {
      const items = await api("/integrations");
      if (!alive.current || revision !== generation.current) return;
      const next = items.find((item: any) => item.name === name)?.status?.state || "not_connected";
      setState(next);
      if (initiated.current && ["connected", "error"].includes(next)) {
        initiated.current = false;
        callbacks.current.notify(next === "connected" ? "Connection and tools verified." : "Connection failed. Check the endpoint and browser consent, then retry.", next === "error");
        if (next === "connected") callbacks.current.onConnected?.();
      }
    } catch { /* The core's connection indicator reports transport failures. */ }
  }
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => { alive.current = false; generation.current++; };
  }, [name]);
  useEffect(() => {
    if (state !== "connecting") return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [state, name]);
  async function connect() {
    generation.current++;
    setBusy(true);
    try {
      const result = await post("/integrations/" + encodeURIComponent(name) + "/connect");
      if (!alive.current) return;
      initiated.current = true;
      setState(result.state);
      window.dispatchEvent(new Event("jarvis-integration-connect"));
    } catch (error: any) {
      if (alive.current) { setState("error"); callbacks.current.notify(error.message, true); }
    } finally { if (alive.current) setBusy(false); }
  }
  return <div className="integration-connect">
    <button className="btn" disabled={disabled || busy || state === "connecting"} onClick={() => void connect()}>{busy || state === "connecting" ? tr("Connecting…") : label}</button>
    {state === "connecting" && <p role="status">{tr("Waiting for the connection. If authorization is needed, a consent window will appear in Jarvis.")}</p>}
    {state === "connected" && <p role="status">{tr("Connection and tools verified.")}</p>}
    {state === "error" && <p className="error-text">{tr("Connection failed. Check the endpoint and browser consent, then retry.")}</p>}
  </div>;
}
