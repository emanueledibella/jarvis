import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Phone, Power } from "lucide-react";
import { api, post, type Json } from "./api";
import { Badge } from "./components";
import { t as tr, useI18n } from "./i18n";

type PanelProps = {
  status: Json;
  action: string;
  locked: boolean;
  onStart: () => void;
  onStop: () => void;
};

export function TelephonyTunnelPanel({
  status,
  action,
  locked,
  onStart,
  onStop,
}: PanelProps) {
  useI18n();
  const active = ["starting", "running", "stopping"].includes(status.state);
  const starting = status.state === "starting" || action === "start";
  const stopping = status.state === "stopping" || action === "stop";
  const labels: Record<string, string> = {
    loading: "Checking telephony…",
    stopped: "Telephony off",
    starting: "Starting telephony…",
    running: "Telephony active",
    stopping: "Stopping telephony…",
    error: "Telephony needs attention",
  };
  return (
    <div className="telephony-connection">
      <div className="info-box" role="status" aria-live="polite">
        <Badge state={status.state === "running" ? "connected" : status.state}>
          {tr(labels[status.state] || "Telephony off")}
        </Badge>
        <p>
          {tr(
            "Jarvis starts and stops the secure connection for you. Quitting Jarvis also closes the connection.",
          )}
        </p>
        {status.state === "starting" && (
          <p>
            {tr(
              "Creating and checking the connection. This may take up to three minutes.",
            )}
          </p>
        )}
        {status.state === "running" && status.public_url && (
          <label className="field">
            <span>{tr("Current public telephony URL")}</span>
            <input type="url" readOnly value={status.public_url} />
          </label>
        )}
        {status.inbound_configured && (
          <p>{tr("Incoming calls are connected to the current URL.")}</p>
        )}
      </div>
      {status.error && (
        <p className="hint" role="alert">
          {tr(status.error)}
        </p>
      )}
      {status.dependencies &&
        (!status.dependencies.caddy || !status.dependencies.cloudflared) && (
          <p className="hint" role="alert">
            {tr(
              "Install Caddy and cloudflared before activating managed telephony.",
            )}
          </p>
        )}
      <div className="button-row">
        <button
          type="button"
          className="btn primary"
          onClick={onStart}
          disabled={
            Boolean(action) || active || locked || status.state === "loading"
          }
        >
          {starting ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Phone size={15} />
          )}
          {tr("Activate telephony")}
        </button>
        <button
          type="button"
          className="btn"
          onClick={onStop}
          disabled={Boolean(action) || stopping || !active}
        >
          {stopping ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Power size={15} />
          )}
          {tr("Deactivate telephony")}
        </button>
      </div>
      <p className="hint">
        {tr(
          "Activation saves your changes. Incoming call webhooks are updated automatically when incoming calls are enabled. No call is placed.",
        )}
      </p>
    </div>
  );
}

export default function TelephonyConnection({
  prepare,
  onChanged,
  notify,
  locked,
}: {
  prepare: () => Promise<void>;
  onChanged: (enabled: boolean) => void;
  notify: (text: string, error?: boolean) => void;
  locked: boolean;
}) {
  const [status, setStatus] = useState<Json>({ state: "loading" });
  const [action, setAction] = useState("");
  const revision = useRef(0);
  useEffect(() => {
    const abort = new AbortController();
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      const current = revision.current;
      try {
        const result = await api("/telephony/status", { signal: abort.signal });
        if (!abort.signal.aborted && current === revision.current)
          setStatus(result);
      } catch {
        if (!abort.signal.aborted && current === revision.current)
          setStatus((previous) => ({
            ...previous,
            state: previous.state === "loading" ? "error" : previous.state,
            error: "Could not read the telephony status.",
          }));
      } finally {
        pending = false;
      }
    }
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      abort.abort();
      clearInterval(timer);
    };
  }, []);
  async function control(selected: "start" | "stop") {
    setAction(selected);
    revision.current += 1;
    try {
      if (selected === "start") await prepare();
      const result = await post("/telephony/" + selected);
      setStatus(result);
      onChanged(selected === "start");
      notify(
        selected === "start" ? "Telephony is starting." : "Telephony is off.",
      );
    } catch (error: any) {
      notify(error.message, true);
    } finally {
      revision.current += 1;
      setAction("");
    }
  }
  return (
    <TelephonyTunnelPanel
      status={status}
      action={action}
      locked={locked}
      onStart={() => control("start")}
      onStop={() => control("stop")}
    />
  );
}
