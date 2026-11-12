import React, { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { t as tr } from "./i18n";

export type ScreenAttachment = { id: string; expiresAt: number };
export type ScreenCaptureState =
  "available" | "locked" | "executor_required" | "stopped" | "unavailable";
export type ScreenCaptureContext = {
  scope: string;
  privacy_revision: number;
  session_id: string;
};
type ScreenCapture = {
  id: string;
  image: string;
  text: string;
  confidence: number | null;
  expires_in: number;
};

const unavailableHint = {
  locked: "Unlock the Mac to choose a window, or attach a screenshot below.",
  executor_required:
    "To choose a window, select a connected Mac executor with window capture enabled. You can also attach a screenshot below.",
  stopped: "Window capture is paused by emergency stop.",
  unavailable: "To share what's on your screen, attach a screenshot below.",
};

export function deleteScreenCapture(id: string, context: ScreenCaptureContext) {
  return api("/screen/captures/" + encodeURIComponent(id), {
    method: "DELETE",
    body: JSON.stringify(context),
  });
}

export default function ScreenAttachmentPicker({
  state,
  context,
  disabled,
  isCurrent,
  onAttach,
  notify,
}: {
  state: ScreenCaptureState;
  context: ScreenCaptureContext;
  disabled: boolean;
  isCurrent: () => boolean;
  onAttach: (attachment: ScreenAttachment) => boolean;
  notify: (message: string, error?: boolean) => void;
}) {
  const [preview, setPreview] = useState<
    (ScreenCapture & ScreenAttachment) | null
  >(null);
  const [choosing, setChoosing] = useState(false);
  const pending = useRef<AbortController | null>(null);
  const unconfirmed = useRef<string | null>(null);

  useEffect(
    () => () => {
      pending.current?.abort();
      if (unconfirmed.current && isCurrent()) {
        void deleteScreenCapture(unconfirmed.current, context).catch(() => {});
      }
    },
    [],
  );

  useEffect(() => {
    if (!preview) return;
    const timer = setTimeout(
      () => {
        unconfirmed.current = null;
        setPreview(null);
        notify("The window capture expired. Choose it again.");
      },
      Math.max(0, preview.expiresAt - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [preview, notify]);

  async function choose() {
    if (pending.current || !isCurrent()) return;
    const controller = new AbortController();
    pending.current = controller;
    setChoosing(true);
    try {
      const capture = await api<ScreenCapture>("/screen/captures", {
        method: "POST",
        body: JSON.stringify(context),
        signal: controller.signal,
      });
      if (controller.signal.aborted || !isCurrent()) return;
      unconfirmed.current = capture.id;
      setPreview({
        ...capture,
        expiresAt: Date.now() + capture.expires_in * 1000,
      });
    } catch (error: any) {
      if (!controller.signal.aborted && isCurrent())
        notify(error.message, true);
    } finally {
      pending.current = null;
      if (!controller.signal.aborted) setChoosing(false);
    }
  }

  if (state !== "available")
    return (
      <p className="screen-attachment-hint">
        {tr(unavailableHint[state] ?? unavailableHint.unavailable)}
      </p>
    );

  return (
    <section className="assistant-card screen-attachment">
      <h3>{tr("Window capture")}</h3>
      {preview ? (
        <>
          <img
            className="screen-attachment-preview"
            src={"data:image/jpeg;base64," + preview.image}
            alt={tr("Owner-selected window capture")}
          />
          <p>
            {tr(
              "The capture expires after ten minutes. Sending your message shares only the recognized text with your selected model.",
            )}
          </p>
          {preview.text.trim() ? (
            <details>
              <summary>
                {tr("Recognized text")}
                {preview.confidence != null &&
                  ` · ${Math.round(preview.confidence * 100)}%`}
              </summary>
              <p className="screen-attachment-text">{preview.text}</p>
            </details>
          ) : (
            <p role="status">{tr("No text was recognized in this window.")}</p>
          )}
          <div className="assistant-actions">
            <button
              className="btn primary"
              disabled={disabled || !preview.text.trim()}
              onClick={() => {
                if (
                  Date.now() < preview.expiresAt &&
                  onAttach({ id: preview.id, expiresAt: preview.expiresAt })
                ) {
                  unconfirmed.current = null;
                }
              }}
            >
              {tr("Attach window")}
            </button>
            <button
              className="btn"
              onClick={() => {
                unconfirmed.current = null;
                setPreview(null);
                if (isCurrent())
                  void deleteScreenCapture(preview.id, context).catch((error) =>
                    notify(error.message, true),
                  );
              }}
            >
              {tr("Delete capture")}
            </button>
          </div>
        </>
      ) : (
        <>
          <button
            className="btn"
            disabled={disabled || choosing}
            onClick={() => void choose()}
          >
            {tr("Choose a window")}
          </button>
          {choosing && (
            <p role="status">
              {tr("Choose a window in the system picker on the Mac…")}
            </p>
          )}
        </>
      )}
    </section>
  );
}
