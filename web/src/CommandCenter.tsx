import { t as tr, useI18n, uiLocale } from "./i18n";
import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  AudioLines,
  Brain,
  CalendarDays,
  Check,
  ChevronRight,
  Cloud,
  CloudSun,
  Code2,
  Computer,
  Layers3,
  MessageSquare,
  Mic,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import type { Json } from "./api";
import { Badge, Orb, formatDate, profileLabels } from "./components";

export function SystemClock({ timezone }: { timezone?: string }) {
  const language = useI18n();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) setNow(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);
  const formats = useMemo(
    () => ({
      date: new Intl.DateTimeFormat(uiLocale(), {
        timeZone: timezone,
        weekday: "short",
        day: "numeric",
        month: "short",
      }),
      time: new Intl.DateTimeFormat(uiLocale(), {
        timeZone: timezone,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
    }),
    [timezone, language],
  );
  return (
    <time className="system-clock" dateTime={now.toISOString()}>
      <span>{formats.date.format(now)}</span>
      <strong>{formats.time.format(now)}</strong>
    </time>
  );
}

export function VoiceSignal({ level = 0 }: { level?: number }) {
  useI18n();
  const amplitude = Math.max(
    0,
    Math.min(1, Number.isFinite(level) ? level : 0),
  );
  return (
    <span className="signal-bars" aria-hidden="true">
      {Array.from({ length: 25 }, (_, i) => (
        <i
          key={i}
          style={{ height: 2 + amplitude * (5 + Math.sin(i * 1.73) ** 2 * 19) }}
        />
      ))}
    </span>
  );
}

export function selectedModel(status: Json): string {
  if (status.profile === "cloud")
    return status.models?.cloud || tr("Choose a cloud model");
  if (status.profile === "hybrid" && status.models?.cloud_configured)
    return status.models.cloud;
  return status.models?.local || tr("Choose a local model");
}

function weatherName(code: number) {
  if (code === 0) return "Clear skies";
  if (code <= 2) return "Partly cloudy";
  if (code === 3) return "Cloudy";
  if (code <= 48) return "Fog";
  if (code <= 67) return "Rain";
  if (code <= 77) return "Snow";
  if (code <= 82) return "Showers";
  if (code <= 86) return "Snow";
  return "Thunderstorms";
}

const memoryPoints = [
  [22, 66],
  [54, 34],
  [84, 56],
  [112, 24],
  [147, 42],
  [177, 20],
  [210, 49],
  [242, 37],
  [272, 67],
  [123, 81],
  [187, 87],
  [64, 91],
];

type Destination = "tasks" | "routines" | "memory" | "integrations";
type Props = {
  status: Json;
  dashboard: Json;
  tasks: Json[];
  schedules: Json[];
  approvals: Json[];
  connection: string;
  orbState: string;
  audio: { input: number; output: number };
  composer: React.ReactNode;
  onPage: (page: Destination) => void;
  onSettings: (section: string) => void;
  onListen: () => void;
  onNewChat: () => void;
  onCompose: (prompt: string) => void;
};

export default function CommandCenter({
  status,
  dashboard,
  tasks,
  schedules,
  approvals,
  connection,
  orbState,
  audio,
  composer,
  onPage,
  onSettings,
  onListen,
  onNewChat,
  onCompose,
}: Props) {
  useI18n();
  const activeTasks = tasks.filter((t) =>
    ["queued", "running", "waiting_user"].includes(t.state),
  );
  const portableText = status.platform?.native_voice === false;
  const routines = schedules.filter((s) => s.enabled);
  const memoryConnected = status.memory?.connection === "connected";
  const mcp = Object.values(status.mcp || {}) as Json[];
  const connectedMcp = mcp.filter((server) => server.state === "connected");
  const enabledTools = connectedMcp.reduce(
    (count, server) =>
      count + (server.tools || []).filter((tool: Json) => tool.enabled).length,
    0,
  );
  const upcoming = (dashboard.calendar?.events || [])
    .filter(
      (event: Json) =>
        !event.start ||
        new Date(event.end || event.start).getTime() >= Date.now(),
    )
    .slice(0, 2);
  const weather = dashboard.weather || {};
  const online = connection === "connected" && !status.emergency_stop;
  const voiceReady =
    status.native?.connected &&
    !status.native?.muted &&
    ["armed", "listening", "speaking", "followup"].includes(orbState);
  const level =
    orbState === "speaking" ? audio.output : voiceReady ? audio.input : 0;

  return (
    <div className="command-center">
      <div className="command-heading">
        <div>
          <span className="eyebrow">
            {tr("PERSONAL INTELLIGENCE / OVERVIEW")}
          </span>
          <h1>
            {tr("Your command center")}
            <span>.</span>
          </h1>
        </div>
        <span className={"service-pill " + (online ? "is-online" : "")}>
          <span className="tiny-dot" />
          {status.emergency_stop
            ? tr("Service suspended")
            : online
              ? tr("Service online")
              : tr("Connecting")}
        </span>
      </div>

      <div className="command-grid">
        <section
          className="hud-panel core-panel"
          aria-label={tr("Jarvis voice core")}
        >
          <header className="hud-heading">
            <span>
              <AudioLines size={14} />{" "}
              {portableText ? tr("ASSISTANT CORE") : tr("VOICE & PRESENCE")}
            </span>
            <span className="panel-index">{tr("01 / CORE")}</span>
          </header>
          <div className="core-body">
            <div className="core-copy">
              <span className="core-kicker">
                <span className={"tiny-dot " + (!voiceReady ? "off" : "")} />
                {portableText
                  ? tr("TEXT CONVERSATION")
                  : voiceReady
                    ? tr("A VOICE WITHIN REACH")
                    : tr("READY TO CONNECT")}
              </span>
              <h2>
                {tr("A little more")}
                <br />
                {tr(" possible")}
                <span>.</span>
              </h2>
              <p>
                {tr("Your ideas, the right context,")}
                <br className="desktop-break" />
                {tr(" and a way forward.")}
              </p>
              <button
                className="btn primary talk-button"
                onClick={portableText ? onNewChat : onListen}
              >
                {portableText ? <MessageSquare size={15} /> : <Mic size={15} />}{" "}
                {portableText
                  ? tr("Start a conversation")
                  : tr("Talk to Jarvis")}{" "}
                {!portableText && <span>{tr("⌘ ⇧ J")}</span>}
              </button>
              <button className="text-btn core-chat" onClick={onNewChat}>
                {tr("Or start with a message ")}
                <ArrowUpRight size={13} />
              </button>
            </div>
            <div className="core-visual">
              <Orb
                state={
                  portableText
                    ? activeTasks.some((t) => t.state === "running")
                      ? "processing"
                      : "text_ready"
                    : orbState
                }
                level={level}
                interruptible={Boolean(status.native?.barge_in)}
              />
            </div>
          </div>
          <div className="core-footnote">
            <span>
              <ShieldCheck size={12} />{" "}
              {status.native?.on_device
                ? tr("Wake detection on your Mac")
                : tr("Voice settings under your control")}
            </span>
            <VoiceSignal level={level} />
            <button
              onClick={() => onSettings(portableText ? "models" : "voice")}
            >
              {portableText ? tr("Model settings") : tr("Voice settings")}{" "}
              <ChevronRight size={11} />
            </button>
          </div>
        </section>

        <section
          className="hud-panel day-panel"
          aria-label={tr("Weather and calendar")}
        >
          <header className="hud-heading">
            <span>
              <CalendarDays size={14} />
              {tr(" YOUR DAY")}
            </span>
            <button
              className="icon-btn"
              aria-label={tr("Configure weather and calendar")}
              onClick={() => onSettings("productivity")}
            >
              <ArrowUpRight size={14} />
            </button>
          </header>
          {weather.state === "ready" ? (
            <div className="day-weather">
              <CloudSun size={38} strokeWidth={1.2} />
              <strong>
                {Math.round(weather.current.temperature_2m)}
                <sup>°</sup>
              </strong>
              <div>
                <h3>{tr(weatherName(weather.current.weather_code))}</h3>
                <p>{weather.location}</p>
              </div>
              <span className="weather-detail">
                {tr("Feels like ")}
                {Math.round(weather.current.apparent_temperature)}
                {tr("° · Wind ")}
                {Math.round(weather.current.wind_speed_10m)}
                {tr(" km/h")}
                {weather.stale ? tr(" · Needs refresh") : ""}
              </span>
              <a
                className="weather-attribution"
                href="https://open-meteo.com/"
                target="_blank"
                rel="noopener noreferrer"
              >
                {tr("Open-Meteo · ")}
                {formatDate(weather.updated_at, true)}{" "}
                <ArrowUpRight size={10} />
              </a>
            </div>
          ) : (
            <div className="day-weather weather-empty">
              <CloudSun size={35} strokeWidth={1.1} />
              <div>
                <h3>
                  {weather.state === "loading"
                    ? tr("Checking the weather…")
                    : tr("A window to your day.")}
                </h3>
                <p>
                  {tr(
                    weather.message || "Add your city for the local forecast.",
                  )}
                </p>
              </div>
              <button
                className="text-btn"
                onClick={() => onSettings("productivity")}
              >
                {tr("Set weather location ")}
                <ArrowRight size={12} />
              </button>
            </div>
          )}
          <div className="day-agenda">
            <span className="eyebrow">{tr("UP NEXT")}</span>
            {upcoming.length > 0 ? (
              upcoming.map((event: Json, i: number) => (
                <div className="day-event" key={event.id || i}>
                  <time>
                    {event.all_day
                      ? tr("All day")
                      : formatDate(event.start, true)}
                  </time>
                  <div>
                    <h3>{event.title}</h3>
                    <small>
                      {event.calendar || dashboard.calendar.provider}
                    </small>
                  </div>
                </div>
              ))
            ) : (
              <div className="agenda-empty">
                <span className="timeline-marker" />
                <div>
                  <h3>
                    {dashboard.calendar?.state === "ready"
                      ? tr("A little room to breathe.")
                      : tr("Bring your calendar along.")}
                  </h3>
                  <p>
                    {dashboard.calendar?.state === "ready"
                      ? tr("No upcoming events in this view.")
                      : (dashboard.calendar?.message &&
                          tr(dashboard.calendar.message)) ||
                        tr("Your next events, in one place.")}
                  </p>
                </div>
              </div>
            )}
            <button
              className="text-btn"
              onClick={() => onSettings("productivity")}
            >
              {dashboard.calendar?.state === "ready"
                ? tr("Calendar settings")
                : tr("Connect calendar")}{" "}
              <ArrowRight size={12} />
            </button>
          </div>
        </section>

        <section
          className="hud-panel missions-panel"
          aria-label={tr("Task activity")}
        >
          <header className="hud-heading">
            <span>
              <Workflow size={14} />
              {tr(" TASK ACTIVITY")}
            </span>
            <button
              className="icon-btn"
              aria-label={tr("View all tasks")}
              onClick={() => onPage("tasks")}
            >
              <ArrowUpRight size={14} />
            </button>
          </header>
          <div className="mission-metrics">
            <button onClick={() => onPage("tasks")}>
              <strong>{String(activeTasks.length).padStart(2, "0")}</strong>
              <span>{tr("Active tasks")}</span>
            </button>
            <button
              className={approvals.length ? "has-decisions" : ""}
              onClick={() => onPage("tasks")}
            >
              <strong>{String(approvals.length).padStart(2, "0")}</strong>
              <span>{tr("Decisions")}</span>
            </button>
            <button onClick={() => onPage("routines")}>
              <strong>{String(routines.length).padStart(2, "0")}</strong>
              <span>{tr("Routines on")}</span>
            </button>
          </div>
          {activeTasks.length ? (
            <div className="mission-list">
              {activeTasks.slice(0, 2).map((task) => (
                <button key={task.id} onClick={() => onPage("tasks")}>
                  <span>{task.title}</span>
                  <Badge state={task.state} />
                </button>
              ))}
            </div>
          ) : (
            <div className="mission-clear">
              <span>
                <Check size={13} />
              </span>
              <p>
                {tr("All clear.")}
                <br />
                <strong>{tr("Ready for your next idea.")}</strong>
              </p>
              <button
                aria-label={tr("Start a new conversation")}
                onClick={onNewChat}
              >
                <ArrowUpRight size={16} />
              </button>
            </div>
          )}
        </section>

        <section
          className="hud-panel context-panel"
          aria-label={tr("Second Brain memory")}
        >
          <header className="hud-heading">
            <span>
              <Brain size={14} />
              {tr(" SECOND BRAIN")}
            </span>
            <span
              className={
                "inline-status " + (memoryConnected ? "is-online" : "")
              }
            >
              <span className="tiny-dot" />
              {memoryConnected ? tr("Connected") : tr("Not connected")}
            </span>
          </header>
          <div className="memory-constellation" aria-hidden="true">
            <svg viewBox="0 0 300 110" fill="none">
              <path d="M22 66 54 34 84 56 112 24 147 42 177 20 210 49 242 37 272 67M84 56 123 81 147 42 187 87 210 49M22 66 64 91 84 56M123 81 187 87" />
              {memoryPoints.map(([cx, cy], i) => (
                <circle key={i} cx={cx} cy={cy} r={i % 3 === 0 ? 3 : 2} />
              ))}
            </svg>
            <span>{tr("CONTEXT, CONNECTED")}</span>
          </div>
          <div className="context-bottom">
            <p>
              {memoryConnected
                ? tr("A memory that picks up where you left off.")
                : tr("Connect your memories, projects and ideas.")}
            </p>
            <button
              className="text-btn"
              onClick={() =>
                memoryConnected ? onPage("memory") : onSettings("memory")
              }
            >
              {memoryConnected
                ? tr("Explore memory")
                : tr("Connect Second Brain")}{" "}
              <ArrowRight size={12} />
            </button>
          </div>
        </section>

        <section
          className="hud-panel systems-panel"
          aria-label={tr("Configured models and connected tools")}
        >
          <header className="hud-heading">
            <span>
              <Layers3 size={14} />
              {tr(" CONNECTED SYSTEMS")}
            </span>
            <span className="panel-index">{tr("02 / TOOLS")}</span>
          </header>
          <div className="system-links">
            <button onClick={() => onSettings("models")}>
              <span className="system-icon">
                <Cloud size={15} />
              </span>
              <span>
                <strong>{tr("Cloud intelligence")}</strong>
                <small title={status.models?.cloud}>
                  {status.models?.cloud || tr("Choose a model")}
                </small>
              </span>
              <span
                className={
                  "system-tag " +
                  (status.models?.cloud_configured ? "configured" : "")
                }
              >
                {status.models?.cloud_configured
                  ? tr("Configured")
                  : tr("Set up")}
              </span>
            </button>
            <button onClick={() => onSettings("models")}>
              <span className="system-icon violet">
                <Computer size={15} />
              </span>
              <span>
                <strong>{tr("Local intelligence")}</strong>
                <small title={status.models?.local}>
                  {status.models?.local || tr("Choose a model")}
                </small>
              </span>
              <span
                className={
                  "system-tag " + (status.models?.local ? "configured" : "")
                }
              >
                {status.models?.local ? tr("Configured") : tr("Set up")}
              </span>
            </button>
            <button onClick={() => onPage("integrations")}>
              <span className="system-icon mint">
                <Layers3 size={15} />
              </span>
              <span>
                <strong>{tr("MCP tools")}</strong>
                <small>
                  {tr("Tools enabled: {tools} · Connected servers: {servers}", {
                    tools: enabledTools,
                    servers: connectedMcp.length,
                  })}
                </small>
              </span>
              <ChevronRight size={13} />
            </button>
          </div>
        </section>
      </div>

      <div className="command-shortcuts" aria-label={tr("Start a request")}>
        <span className="eyebrow">{tr("MAKE A START")}</span>
        {[
          {
            icon: CalendarDays,
            label: tr("Plan my day"),
            prompt: "Help me plan my day using my calendar and tasks.",
          },
          {
            icon: Search,
            label: tr("Explore a topic"),
            prompt: "Research in depth: ",
          },
          {
            icon: Code2,
            label: tr("Work on code"),
            prompt: "Help me work on the project ",
          },
        ].map(({ icon: Icon, label, prompt }) => (
          <button key={tr(label)} onClick={() => onCompose(tr(prompt))}>
            <Icon size={14} />
            {tr(label)}
            <ArrowUpRight size={12} />
          </button>
        ))}
      </div>
      {composer}
      <footer className="command-footer">
        <span>
          <span className="tiny-dot" />
          {tr(profileLabels[status.profile] || "Loading profile")}
          <i />
          {selectedModel(status)}
        </span>
        <span>
          <ShieldCheck size={11} />{" "}
          {portableText
            ? tr("Your computer. Your controls.")
            : tr("Your Mac. Your controls.")}
        </span>
      </footer>
    </div>
  );
}
