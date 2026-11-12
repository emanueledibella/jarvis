import React, { useEffect, useState } from "react";
import { Headphones, Mic, MicOff, RefreshCw } from "lucide-react";
import { companionVoice, useCompanionVoice } from "./companionVoice";
import { Field, Toggle } from "./components";
import { t as tr } from "./i18n";
import { remoteClient } from "./remoteClient";

export default function CompanionVoiceSettings({
  notify,
}: {
  notify: (message: string, error?: boolean) => void;
}) {
  const voice = useCompanionVoice();
  const [busy, setBusy] = useState(false),
    [catalog, setCatalog] = useState<Record<string, any>>({ devices: [] });
  const refresh = () => {
    void companionVoice
      .inputs()
      .then(setCatalog)
      .catch((error) => notify(error.message, true));
  };
  useEffect(refresh, []);
  async function control(action: string) {
    setBusy(true);
    try {
      await companionVoice.control(action);
      refresh();
    } catch (error: any) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  const devices = catalog.devices || [];
  return (
    <section className="settings-card companion-voice-settings">
      <div className="card-heading">
        <Headphones size={19} />
        <div>
          <h2>{tr("Voice on this device")}</h2>
          <p>{tr("Say Jarvis to start a conversation.")}</p>
        </div>
      </div>
      <Toggle
        label={tr("Listen on this device")}
        checked={voice.enabled}
        disabled={busy || !voice.supported}
        onChange={(enabled) => void control(enabled ? "enable" : "mute")}
        help={tr(
          "Wake recognition stays on this device. Enable microphone and speech recognition permissions once.",
        )}
      />
      <p className="info-line" role="status">
        {voice.state === "armed"
          ? tr("Listening for Jarvis")
          : voice.state === "listening" || voice.state === "followup"
            ? tr("Listening")
            : voice.state === "speaking"
              ? tr("Jarvis is speaking")
              : voice.state === "processing"
                ? tr("Working on it.")
                : voice.state === "recovering"
                  ? tr("Recovering voice…")
                  : tr("Microphone off")}
      </p>
      {voice.error && (
        <p className="hint" role="alert">
          {tr(voice.error)}
        </p>
      )}
      {voice.supported ? (
        <>
          <Field
            label={tr("Microphone")}
            value={voice.microphone}
            disabled={busy || catalog.state === "system_default"}
            options={[
              { value: "", label: tr("System default") },
              ...devices.map((device: any) => ({
                value: device.uid,
                label: device.name,
              })),
              ...(voice.microphone &&
              !devices.some((device: any) => device.uid === voice.microphone)
                ? [
                    {
                      value: voice.microphone,
                      label: tr("Saved microphone · not currently available"),
                    },
                  ]
                : []),
            ]}
            onChange={(uid) => {
              void companionVoice
                .selectMicrophone(uid)
                .catch((error) => notify(error.message, true));
            }}
            help={tr("Microphone selection applies only to this device.")}
          />
          <div className="button-row">
            <button
              className="btn primary"
              disabled={busy}
              onClick={() => void control("listen")}
            >
              <Mic size={15} />
              {tr("Talk to Jarvis")}
            </button>
            <button
              className="btn"
              disabled={busy}
              onClick={() => void control("mute")}
            >
              <MicOff size={15} />
              {tr("Mute microphone")}
            </button>
            <button className="btn" onClick={refresh}>
              <RefreshCw size={14} />
              {tr("Refresh microphones")}
            </button>
          </div>
        </>
      ) : (
        <p className="hint">
          {tr(
            "On-device wake listening is unavailable here. Use manual recording to talk to Jarvis.",
          )}
        </p>
      )}
      <div className="button-row">
        <button
          className="btn"
          onClick={() =>
            window.dispatchEvent(new Event("jarvis-companion-record"))
          }
        >
          <Mic size={15} />
          {tr("Record request")}
        </button>
      </div>
      <small className="hint">
        {remoteClient.platform === "macos"
          ? tr(
              "The Mac must be awake. Closing the window keeps wake listening in the menu bar. Use ⌘⇧J to talk.",
            )
          : tr(
              "On mobile, wake listening works while Jarvis is open. It pauses in the background and resumes when you return.",
            )}
      </small>
    </section>
  );
}
