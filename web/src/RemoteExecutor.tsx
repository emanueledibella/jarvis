import { useCallback, useEffect, useState, type FormEvent } from "react";
import { t as tr } from "./i18n";
import {
  remoteClient,
  type DesktopExecutorBridge,
  type DesktopExecutorStatus,
  type NativeBridge,
} from "./remoteClient";

const statusLabels: Record<DesktopExecutorStatus["state"], string> = {
  stopped: "Stopped",
  starting: "Starting executor…",
  connected: "Connected",
  reconnecting: "Reconnecting…",
  receipt_pending: "Sending job result…",
  pairing_required: "Pairing required",
  failed: "Executor start failed",
  configuration_required: "Check executor configuration",
};

export function hasDesktopExecutor(
  bridge?: NativeBridge,
): bridge is NativeBridge & DesktopExecutorBridge {
  return Boolean(
    bridge?.selectDirectory &&
    bridge.configureExecutor &&
    bridge.executorStatus &&
    bridge.setExecutorEnabled,
  );
}

export default function RemoteExecutor({
  bridge,
  onChange,
}: {
  bridge: DesktopExecutorBridge;
  onChange: () => void;
}) {
  const [status, setStatus] = useState<DesktopExecutorStatus | null>();
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState<
    "folder" | "pair" | "start" | "stop" | null
  >(null);
  const [error, setError] = useState("");
  const [directory, setDirectory] = useState("");
  const [scope, setScope] = useState("personal");
  const [write, setWrite] = useState(false);
  const [command, setCommand] = useState(false);
  const [prefixes, setPrefixes] = useState(
    "git status\ngit diff\nnpm test\nnpm run build",
  );
  const [calendarRead, setCalendarRead] = useState(false);
  const [calendarWrite, setCalendarWrite] = useState(false);
  const [screen, setScreen] = useState(false);
  const [code, setCode] = useState("");

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await bridge.executorStatus());
    } catch {
      setStatus(null);
    }
  }, [bridge]);

  useEffect(() => {
    void refreshStatus();
    const timer = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  const admin = remoteClient.admin;
  const native = [
    ...(calendarRead ? ["calendar.list"] : []),
    ...(calendarWrite
      ? ["calendar.create", "calendar.update", "calendar.delete"]
      : []),
    ...(screen ? ["screen.capture", "window.list", "window.action"] : []),
  ];
  const commands = prefixes
    .split("\n")
    .map((prefix) => prefix.trim())
    .filter(Boolean);
  const canPair =
    Boolean(directory || native.length) &&
    (!directory || !command || commands.length > 0) &&
    (admin || Boolean(code.trim()));
  const canManage = status?.configured && status.state !== "pairing_required";
  const statusLabel =
    status === undefined
      ? "Checking executor…"
      : status === null
        ? "Executor status unavailable"
        : status.configured
          ? statusLabels[status.state] || "Executor status unavailable"
          : "Not paired";

  async function run(
    action: NonNullable<typeof pending>,
    operation: () => Promise<void>,
  ) {
    if (pending) return;
    setPending(action);
    setError("");
    try {
      await operation();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setPending(null);
    }
  }

  function chooseFolder() {
    return run("folder", async () => {
      const chosen = await bridge.selectDirectory();
      if (chosen) setDirectory(chosen);
    });
  }

  function pair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canPair) return;
    return run("pair", async () => {
      const serverUrl = remoteClient.credentials!.server_url;
      const executorCode =
        code.trim() ||
        (
          await remoteClient.json<{ code: string }>("pairing-codes", {
            kind: "executor",
            owner: false,
          })
        ).code;
      await bridge.configureExecutor({
        server_url: serverUrl,
        code: executorCode,
        name: tr("Executor ") + bridge.platform,
        acknowledge_host_commands: Boolean(directory && command),
        native_scope: scope,
        native,
        workspaces: directory
          ? [
              {
                path: directory,
                label: directory.split(/[\\/]/).pop(),
                scope,
                read: true,
                write,
                command,
                commands,
              },
            ]
          : [],
      });
      setCode("");
      await refreshStatus();
      setEditing(false);
      onChange();
    });
  }

  function setEnabled(enabled: boolean) {
    return run(enabled ? "start" : "stop", async () => {
      await bridge.setExecutorEnabled(enabled);
      await refreshStatus();
      onChange();
    });
  }

  function changeEditing(value: boolean) {
    setEditing(value);
    setCode("");
    setError("");
  }

  const codeField = (
    <label className="executor-code-field">
      {tr("Executor code")}
      <input
        type="password"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        required={!admin}
      />
    </label>
  );

  return (
    <section className="executor-panel" aria-labelledby="executor-heading">
      <header className="executor-heading">
        <h3 id="executor-heading">{tr("Executor on this computer")}</h3>
        <span
          className="executor-status"
          data-state={status?.state}
          role="status"
        >
          {tr(statusLabel)}
        </span>
      </header>

      {status && canManage && !editing && (
        <div className="executor-actions">
          <button
            className={status.running ? "btn" : "btn primary"}
            type="button"
            disabled={!!pending}
            onClick={() => void setEnabled(!status.running)}
          >
            {pending === "start"
              ? tr("Starting executor…")
              : pending === "stop"
                ? tr("Stopping executor…")
                : status.running
                  ? tr("Stop executor")
                  : tr("Start executor")}
          </button>
          <button
            className="btn ghost"
            type="button"
            disabled={!!pending}
            onClick={() => changeEditing(true)}
          >
            {tr("Pair again")}
          </button>
        </div>
      )}

      {status && (!canManage || editing) && (
        <form className="executor-form" onSubmit={pair}>
          <fieldset className="executor-step" disabled={!!pending}>
            <legend>{tr("1. Folder and permissions")}</legend>
            <div className="executor-fields">
              <div className="executor-folder-row">
                <button
                  className="btn"
                  type="button"
                  onClick={() => void chooseFolder()}
                >
                  {directory
                    ? tr("Change folder")
                    : tr("Choose an authorized directory")}
                </button>
                <label>
                  {tr("Chat scope")}
                  <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                  >
                    <option value="personal">{tr("Personal")}</option>
                    <option value="work">{tr("Work")}</option>
                  </select>
                </label>
              </div>
              {directory ? (
                <>
                  <p className="executor-help remote-path">
                    {tr("Read access to {folder}", { folder: directory })}
                  </p>
                  <label>
                    <input
                      type="checkbox"
                      checked={write}
                      onChange={(e) => setWrite(e.target.checked)}
                    />
                    {tr("Allow approved writes")}
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={command}
                      onChange={(e) => setCommand(e.target.checked)}
                    />
                    <span>
                      {tr("Allow approved commands")}
                      <small className="executor-help">
                        {tr(
                          "Commands can run project code with your user permissions.",
                        )}
                      </small>
                    </span>
                  </label>
                  {command && (
                    <label>
                      {tr("Allowed command prefixes, one per line")}
                      <textarea
                        value={prefixes}
                        onChange={(e) => setPrefixes(e.target.value)}
                        rows={4}
                        placeholder="git status"
                        autoCapitalize="none"
                        spellCheck={false}
                        required
                      />
                    </label>
                  )}
                </>
              ) : (
                <p className="executor-help">
                  {tr("Choose a project folder to let Jarvis read its files.")}
                </p>
              )}
              {bridge.platform === "macos" && (
                <details className="executor-options">
                  <summary>{tr("Calendar and Mac windows (optional)")}</summary>
                  <div className="executor-fields">
                    <label>
                      <input
                        type="checkbox"
                        checked={calendarRead}
                        onChange={(e) => setCalendarRead(e.target.checked)}
                      />
                      {tr("Allow reading the macOS calendar")}
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={calendarWrite}
                        onChange={(e) => setCalendarWrite(e.target.checked)}
                      />
                      {tr("Allow approved macOS calendar changes")}
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={screen}
                        onChange={(e) => setScreen(e.target.checked)}
                      />
                      {tr(
                        "Allow window control and capturing chosen windows on the Mac",
                      )}
                    </label>
                  </div>
                </details>
              )}
            </div>
          </fieldset>

          <fieldset className="executor-step" disabled={!!pending}>
            <legend>{tr("2. Pairing and startup")}</legend>
            <div className="executor-fields">
              {admin ? (
                <>
                  <p className="executor-help">
                    {tr(
                      "Jarvis generates the code when you pair this computer.",
                    )}
                  </p>
                  <details
                    className="executor-options"
                    onToggle={(e) => {
                      if (!e.currentTarget.open) setCode("");
                    }}
                  >
                    <summary>{tr("Use a code you received")}</summary>
                    {codeField}
                  </details>
                </>
              ) : (
                <>
                  <p className="executor-help">
                    {tr("Ask a Jarvis administrator for an executor code.")}
                  </p>
                  {codeField}
                </>
              )}
              <div className="executor-actions">
                <button
                  className="btn primary"
                  type="submit"
                  disabled={!canPair}
                >
                  {pending === "pair"
                    ? tr("Pairing executor…")
                    : tr("Pair and start executor")}
                </button>
                {editing && (
                  <button
                    className="btn ghost"
                    type="button"
                    onClick={() => changeEditing(false)}
                  >
                    {tr("Cancel")}
                  </button>
                )}
              </div>
            </div>
          </fieldset>
        </form>
      )}
      {error && (
        <p className="executor-error" role="alert">
          {tr(error)}
        </p>
      )}
    </section>
  );
}
