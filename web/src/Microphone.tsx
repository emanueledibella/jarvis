import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "./api";
import { Field } from "./components";
import { t as tr, useI18n } from "./i18n";

export type InputDevice = {
  uid: string;
  name: string;
  is_default: boolean;
  bluetooth: boolean;
};
type Catalog = { state: string; devices: InputDevice[] };
type Choice = {
  value: string;
  disabled: boolean;
  onChange: (uid: string) => void;
};

export function AudioInputPicker({
  value,
  disabled,
  onChange,
  devices,
}: Choice & { devices: InputDevice[] }) {
  useI18n();
  const missing = value && !devices.some((device) => device.uid === value);
  const options = [
    { value: "", label: tr("Follow macOS default input") },
    ...devices.map((device) => ({
      value: device.uid,
      label:
        device.name + (device.is_default ? " · " + tr("System default") : ""),
    })),
    ...(missing
      ? [{ value, label: tr("Saved microphone · not currently available") }]
      : []),
  ];
  return (
    <Field
      label={tr("Microphone")}
      value={value}
      options={options}
      disabled={disabled}
      onChange={onChange}
      help={tr(
        "Choose the input for Jarvis only. Other apps keep their own audio settings. Save changes to apply; an active voice conversation will end.",
      )}
    />
  );
}

export default function MicrophoneSettings({
  value,
  disabled,
  onChange,
  nativeAvailable,
  connected,
  inputMissing,
}: Choice & {
  nativeAvailable: boolean;
  connected: boolean;
  inputMissing: boolean;
}) {
  useI18n();
  const [catalog, setCatalog] = useState<Catalog>({
    state: "loading",
    devices: [],
  });
  const [loading, setLoading] = useState(false);
  async function refresh() {
    setLoading(true);
    try {
      setCatalog(await api<Catalog>("/voice/inputs"));
    } catch {
      setCatalog((current) => ({ ...current, state: "failed" }));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    let cancelled = false;
    if (!nativeAvailable || !connected) return;
    setLoading(true);
    api<Catalog>("/voice/inputs")
      .then((result) => {
        if (!cancelled) setCatalog(result);
      })
      .catch(() => {
        if (!cancelled)
          setCatalog((current) => ({ ...current, state: "failed" }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [nativeAvailable, connected]);
  return (
    <div className="microphone-settings">
      <AudioInputPicker
        value={value}
        onChange={onChange}
        devices={catalog.devices}
        disabled={
          disabled ||
          !nativeAvailable ||
          !connected ||
          loading ||
          catalog.state !== "ready"
        }
      />
      <div className="button-row">
        <button
          type="button"
          className="btn"
          disabled={!nativeAvailable || !connected || loading}
          onClick={refresh}
        >
          <RefreshCw size={14} className={loading ? "spin" : ""} />
          {tr("Refresh microphones")}
        </button>
      </div>
      {!nativeAvailable || catalog.state === "unsupported" ? (
        <p className="hint">
          {tr("Microphone selection requires the native Mac app.")}
        </p>
      ) : !connected || catalog.state === "app_required" ? (
        <p className="hint">
          {tr("Open the Jarvis Mac app to list microphones.")}
        </p>
      ) : catalog.state === "update_required" ? (
        <p className="hint">
          {tr("Update the Jarvis Mac app to choose a microphone.")}
        </p>
      ) : catalog.state === "failed" ? (
        <p className="hint" role="alert">
          {tr(
            "Could not list microphones. Refresh the list or reopen the Mac app.",
          )}
        </p>
      ) : null}
      {inputMissing && (
        <p className="hint" role="status">
          {tr(
            "The selected microphone is disconnected. Jarvis waits for it to return; it will not switch to another input.",
          )}
        </p>
      )}
    </div>
  );
}
