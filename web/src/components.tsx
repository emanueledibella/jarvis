import { t as tr, useI18n, uiLocale } from "./i18n";
import React, { useEffect, useRef, useId } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronRight,
  Circle,
  LoaderCircle,
  LockKeyhole,
  Mic,
  MicOff,
  Radio,
  X,
} from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Json } from "./api";

export const stateLabels: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  waiting_user: "Decision needed",
  paused: "Paused",
  succeeded: "Completed",
  failed: "Needs review",
  cancelled: "Cancelled",
  cancelling: "Stopping",
  unknown: "Uncertain outcome",
  pending: "Pending",
  indexed: "Indexed",
  queued_memory: "Source saved",
  stored_pending_extraction: "Extraction pending",
  needs_review: "Needs review",
  delivery_error: "Delivery needs retry",
  stored_with_warnings: "With warnings",
  superseded: "Newer revision",
  connected: "Connected",
  not_connected: "Not connected",
  connecting: "Connecting…",
  error: "Error",
  accepted: "Accepted",
  initiated: "Call starting",
  ringing: "Ringing",
  answered: "Answered",
  in_progress: "Call in progress",
  "in-progress": "Call in progress",
  creating: "Call starting",
  canceled: "Cancelled",
  "no-answer": "No answer",
  verified_not_created: "Verified not created",
  not_configured: "Needs setup",
  completed: "Completed",
  busy: "Busy",
  no_answer: "No answer",
  blocked: "Blocked",
  unavailable: "Unavailable",
  armed: "Ready for Jarvis",
  listening: "Listening",
  speaking: "Speaking",
  followup: "Ready to continue",
  muted: "Microphone muted",
  recovering: "Restoring listening.",
  permission_required: "Permissions required",
  locked: "Session protected.",
};
export const profileLabels: Record<string, string> = {
  local_strict: "Strict offline",
  local_connected: "Connected local",
  cloud: "Cloud",
  hybrid: "Hybrid",
};
export function formatDate(value?: string, short = false) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(+date)
    ? value
    : new Intl.DateTimeFormat(
        uiLocale(),
        short
          ? { hour: "2-digit", minute: "2-digit" }
          : {
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            },
      ).format(date);
}
export function Badge({
  state,
  children,
}: {
  state?: string;
  children?: React.ReactNode;
}) {
  useI18n();
  return (
    <span className={"badge badge-" + (state || "neutral")}>
      {state === "running" || state === "connecting" ? (
        <LoaderCircle size={12} className="spin" />
      ) : state === "succeeded" || state === "indexed" ? (
        <Check size={12} />
      ) : state === "failed" || state === "unknown" ? (
        <AlertCircle size={12} />
      ) : (
        <Circle size={6} fill="currentColor" />
      )}
      {children || tr(stateLabels[state || ""] || state || "")}
    </span>
  );
}
export function Empty({
  icon: Icon = Circle,
  title,
  children,
  action,
}: {
  icon?: any;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  useI18n();
  return (
    <div className="empty">
      <Icon size={25} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
export function SectionTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  useI18n();
  return (
    <div className="section-title">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  useI18n();
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current
      ?.querySelector<HTMLElement>(
        'button, input, select, textarea, [tabindex="0"]',
      )
      ?.focus();
    return () => previous?.focus();
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            const nodes = Array.from(
              panel.current?.querySelectorAll<HTMLElement>(
                'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex="0"]',
              ) || [],
            );
            const first = nodes[0],
              last = nodes[nodes.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <header>
          <h2>{title}</h2>
          <button
            className="icon-btn"
            onClick={onClose}
            aria-label={tr("Close window")}
          >
            <X size={19} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function Text({ value }: { value: string }) {
  useI18n();
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
              <ArrowUpRight size={12} />
            </a>
          ),
        }}
      >
        {value}
      </Markdown>
    </div>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  const language = useI18n();
  const localized = tr(message);
  if (language === "en" || localized !== message) return <>{localized}</>;
  return (
    <>
      {tr("The operation could not be completed.")}
      <details className="diagnostic-details">
        <summary>{tr("Technical details")}</summary>
        <pre>{message}</pre>
      </details>
    </>
  );
}
export function Orb({
  state = "unavailable",
  level = 0,
  small = false,
  interruptible = false,
}: {
  state?: string;
  level?: number;
  small?: boolean;
  interruptible?: boolean;
}) {
  useI18n();
  const descriptions: Record<string, [string, string]> = {
    text_ready: ["Ready to help.", "Write a request to begin."],
    armed: ["I am here.", "Say “Jarvis” to begin."],
    listening: [
      "I am listening.",
      "Voice input is active; your configured provider processes the conversation.",
    ],
    processing: ["Working on it.", "Follow the steps in Tasks."],
    speaking: [
      "An answer, with context.",
      interruptible
        ? "You can interrupt while I speak."
        : "Press ⌘⇧J to stop playback and speak.",
    ],
    followup: ["Go ahead.", "Continue without repeating “Jarvis”."],
    muted: ["Ready when you are.", "The microphone is muted."],
    recovering: [
      "Restoring listening.",
      "Local recognition will resume in a few seconds.",
    ],
    connecting: ["Just a moment.", "Preparing the voice conversation."],
    unavailable: ["Ready for the first step.", "Set up voice or type below."],
    permission_required: [
      "Voice is waiting for you.",
      "Grant permissions in the Voice section.",
    ],
    locked: ["Session protected.", "Listening resumes after unlock."],
  };
  const [title, detail] = descriptions[state] || descriptions.unavailable;
  const safeLevel = Math.max(
    0,
    Math.min(1, Number.isFinite(level) ? level : 0),
  );
  return (
    <div className={"orb-block " + (small ? "orb-small" : "")}>
      <div
        className={"orb orb-" + state}
        style={
          {
            "--level": safeLevel,
            "--pulse": 1 + safeLevel * 0.14,
          } as React.CSSProperties
        }
        role="img"
        aria-label={tr("Jarvis: ") + tr(title)}
      >
        <div className="orb-haze" />
        <svg
          className="reactor-orbits"
          viewBox="0 0 320 320"
          fill="none"
          aria-hidden="true"
        >
          <circle cx="160" cy="160" r="151" strokeDasharray="2 7" />
          <ellipse
            cx="160"
            cy="160"
            rx="143"
            ry="68"
            transform="rotate(-32 160 160)"
          />
          <ellipse
            cx="160"
            cy="160"
            rx="143"
            ry="68"
            transform="rotate(32 160 160)"
          />
          <path d="M160 0v17m0 286v17M0 160h17m286 0h17M48 48l9 9m206 206 9 9M48 272l9-9M263 57l9-9" />
          <circle className="reactor-satellite" cx="40" cy="199" r="3" />
          <circle className="reactor-satellite" cx="280" cy="121" r="3" />
        </svg>
        <div className="orb-ring ring-a" />
        <div className="orb-ticks" />
        <div className="orb-ring ring-b" />
        <div className="orb-ring ring-c" />
        <div className="orb-core">
          <span className="reactor-name">{tr("JARVIS")}</span>
          <small>{tr("VOICE LINK")}</small>
          <div className="spectrum" aria-hidden="true">
            {Array.from({ length: 13 }, (_, i) => (
              <i
                key={i}
                style={{
                  height: 3 + safeLevel * (5 + Math.sin(i * 1.9) ** 2 * 18),
                }}
              />
            ))}
          </div>
        </div>
        <span className="orb-cross cross-top" />
        <span className="orb-cross cross-bottom" />
      </div>
      <div className="orb-state">
        <span className="eyebrow">
          {state === "armed"
            ? tr("LOCAL VOICE READY")
            : state === "speaking"
              ? tr("VOICE OUTPUT")
              : state === "listening"
                ? tr("VOICE INPUT")
                : state === "processing"
                  ? tr("WORKING")
                  : tr("PERSONAL INTELLIGENCE")}
        </span>
        <h2>{tr(title)}</h2>
        <p>{tr(detail)}</p>
      </div>
    </div>
  );
}
export function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  help,
  disabled = false,
  options,
}: {
  label: string;
  value: any;
  onChange: (v: any) => void;
  type?: string;
  placeholder?: string;
  help?: string;
  disabled?: boolean;
  options?: { value: string; label: string }[];
}) {
  useI18n();
  const helpId = useId();
  const accessibility = {
    "aria-label": label,
    "aria-describedby": help ? helpId : undefined,
  };
  return (
    <label className="field">
      <span>
        {label}
        {disabled && <LockKeyhole size={11} />}
      </span>
      {options ? (
        <select
          {...accessibility}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {tr(o.label)}
            </option>
          ))}
        </select>
      ) : type === "textarea" ? (
        <textarea
          {...accessibility}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
        />
      ) : (
        <input
          {...accessibility}
          type={type}
          value={value ?? ""}
          onChange={(e) =>
            onChange(
              type === "number"
                ? e.target.value === ""
                  ? ""
                  : Number(e.target.value)
                : e.target.value,
            )
          }
          placeholder={placeholder}
          disabled={disabled}
        />
      )}
      {help && <small id={helpId}>{help}</small>}
    </label>
  );
}
export function Toggle({
  checked,
  onChange,
  label,
  help,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  help?: string;
  disabled?: boolean;
}) {
  useI18n();
  return (
    <label className="toggle-row">
      <div>
        <span>{label}</span>
        {help && <small>{help}</small>}
      </div>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
    </label>
  );
}
