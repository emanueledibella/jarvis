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
        "en-GB",
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
      {children || stateLabels[state || ""] || state}
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
            aria-label="Close window"
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
export function Orb({
  state = "unavailable",
  level = 0,
  small = false,
}: {
  state?: string;
  level?: number;
  small?: boolean;
}) {
  const descriptions: Record<string, [string, string]> = {
    armed: ["I am here.", "Say “Jarvis” to begin."],
    listening: [
      "I am listening.",
      "Voice input is active; your configured provider processes the conversation.",
    ],
    processing: ["Working on it.", "Follow the steps in Tasks."],
    speaking: ["An answer, with context.", "You can interrupt while I speak."],
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
  return (
    <div className={"orb-block " + (small ? "orb-small" : "")}>
      <div
        className={"orb orb-" + state}
        style={
          {
            "--level": Math.min(1, level),
            "--pulse": 1 + Math.min(1, level) * 0.14,
          } as React.CSSProperties
        }
        role="img"
        aria-label={"Jarvis: " + title}
      >
        <div className="orb-haze" />
        <div className="orb-ring ring-a" />
        <div className="orb-ticks" />
        <div className="orb-ring ring-b" />
        <div className="orb-ring ring-c" />
        <div className="orb-core">
          <span>J</span>
          <div className="spectrum" aria-hidden="true">
            {Array.from({ length: 13 }, (_, i) => (
              <i
                key={i}
                style={{
                  height:
                    4 + Math.sin(i * 1.9) ** 2 * 6 + level * ((i % 3) + 1) * 8,
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
            ? "LOCAL VOICE READY"
            : state === "speaking"
              ? "VOICE OUTPUT"
              : state === "listening"
                ? "VOICE INPUT"
                : state === "processing"
                  ? "WORKING"
                  : "PERSONAL INTELLIGENCE"}
        </span>
        <h2>{title}</h2>
        <p>{detail}</p>
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
              {o.label}
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
