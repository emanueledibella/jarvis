import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Bell,
  Brain,
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronRight,
  CloudSun,
  Code2,
  Command,
  Computer,
  LayoutDashboard,
  Link2,
  LoaderCircle,
  LockKeyhole,
  MessageSquare,
  Mic,
  MicOff,
  OctagonX,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Sun,
  Terminal,
  Workflow,
  X,
} from "lucide-react";
import {
  api,
  eventStream,
  hasToken,
  patch,
  post,
  setToken,
  type Json,
} from "./api";
import {
  Badge,
  Empty,
  Modal,
  Orb,
  Text,
  formatDate,
  profileLabels,
} from "./components";
import { Tasks, Routines } from "./Activity";
import { Memory, Integrations } from "./Memory";
import Settings from "./Settings";

type Page =
  | "home"
  | "chat"
  | "tasks"
  | "routines"
  | "memory"
  | "integrations"
  | "settings";
const weatherNames = (code: number) =>
  code === 0
    ? "Clear"
    : code <= 2
      ? "Partly cloudy"
      : code === 3
        ? "Cloudy"
        : code <= 48
          ? "Fog"
          : code <= 67
            ? "Rain"
            : code <= 77
              ? "Snow"
              : code <= 82
                ? "Showers"
                : code <= 86
                  ? "Snow"
                  : "Thunderstorms";

export default function App() {
  const [authenticated, setAuthenticated] = useState(hasToken()),
    [entryToken, setEntryToken] = useState(""),
    [page, setPage] = useState<Page>("home"),
    [settingsSection, setSettingsSection] = useState("models"),
    [status, setStatus] = useState<Json>({
      native: {},
      models: {},
      memory: {},
    }),
    [tasks, setTasks] = useState<Json[]>([]),
    [schedules, setSchedules] = useState<Json[]>([]),
    [approvals, setApprovals] = useState<Json[]>([]),
    [notifications, setNotifications] = useState<Json[]>([]),
    [conversations, setConversations] = useState<Json[]>([]),
    [dashboard, setDashboard] = useState<Json>({
      weather: { state: "loading" },
      calendar: { state: "loading", events: [] },
    }),
    [conversation, setConversation] = useState<string | null>(null),
    [messages, setMessages] = useState<Json[]>([]),
    [deltas, setDeltas] = useState<Record<string, string>>({}),
    [text, setText] = useState(""),
    [privateMode, setPrivateMode] = useState(false),
    [scope, setScope] = useState("personal"),
    [privacyReady, setPrivacyReady] = useState(false),
    [external, setExternal] = useState(false),
    [sending, setSending] = useState(false),
    [connection, setConnection] = useState("connecting"),
    [audio, setAudio] = useState({ input: 0, output: 0 }),
    [toast, setToast] = useState<{ message: string; error: boolean } | null>(
      null,
    ),
    [showNotifications, setShowNotifications] = useState(false),
    [theme, setTheme] = useState(
      localStorage.getItem("jarvis-theme") || "dark",
    );
  const currentConversation = useRef(conversation),
    privateRef = useRef(privateMode),
    scopeRef = useRef(scope),
    privacyRevision = useRef(-1),
    submission = useRef<{ signature: string; id: string } | null>(null),
    refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null),
    input = useRef<HTMLTextAreaElement>(null),
    bottom = useRef<HTMLDivElement>(null);
  currentConversation.current = conversation;
  privateRef.current = privateMode;
  scopeRef.current = scope;
  const notify = useCallback((message: string, error = false) => {
    setToast({ message, error });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 7000);
  }, []);
  const refresh = useCallback(() => {
    if (!hasToken()) return;
    Promise.allSettled([
      api("/status").then(setStatus),
      api("/tasks").then(setTasks),
      api("/schedules").then(setSchedules),
      api("/approvals").then(setApprovals),
      api("/notifications").then(setNotifications),
      api("/conversations").then(setConversations),
    ]).then(() => {
      if (currentConversation.current && !privateRef.current)
        api("/conversations/" + currentConversation.current + "/messages")
          .then(setMessages)
          .catch(() => {});
    });
  }, []);
  const loadDashboard = useCallback(
    () =>
      api("/dashboard")
        .then(setDashboard)
        .catch((e) => {
          setDashboard({
            weather: { state: "error", message: e.message },
            calendar: { state: "error", events: [], message: e.message },
          });
        }),
    [],
  );
  function applyPreference(value: Json) {
    if (value.revision < privacyRevision.current) return;
    const changed =
      privateRef.current !== value.private || scopeRef.current !== value.scope;
    privacyRevision.current = value.revision;
    privateRef.current = value.private;
    scopeRef.current = value.scope;
    setPrivateMode(value.private);
    setScope(value.scope);
    setPrivacyReady(true);
    if (changed) {
      setConversation(null);
      setMessages([]);
    }
  }
  function syncPreference() {
    api("/voice/session")
      .then(applyPreference)
      .catch(() => setPrivacyReady(false));
  }
  async function preference(privateValue: boolean, scopeValue: string) {
    setPrivacyReady(false);
    try {
      applyPreference(
        await post("/voice/session", {
          private: privateValue,
          scope: scopeValue,
        }),
      );
      return true;
    } catch (e: any) {
      notify(e.message, true);
      return false;
    }
  }
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("jarvis-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (authenticated) syncPreference();
  }, [authenticated]);
  useEffect(() => {
    const update = () =>
      document.documentElement.classList.toggle(
        "window-hidden",
        document.hidden,
      );
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  useEffect(() => {
    if (!authenticated) return;
    refresh();
    loadDashboard();
    const controller = new AbortController();
    eventStream((event) => {
      if (event.type === "connection") {
        setConnection(event.data.state);
        if (event.data.state === "connected") syncPreference();
      } else if (event.type === "voice.session.updated") {
        syncPreference();
      } else if (event.type === "audio.level") setAudio(event.data);
      else if (event.type === "assistant.delta") {
        setDeltas((current) => ({
          ...current,
          [event.task_id]: (current[event.task_id] || "") + event.data.text,
        }));
      } else {
        if (event.type === "voice.state")
          setStatus((current) => ({
            ...current,
            native: { ...current.native, ...event.data, connected: true },
          }));
        if (refreshTimer.current) clearTimeout(refreshTimer.current);
        refreshTimer.current = setTimeout(refresh, 200);
      }
    }, controller.signal);
    const interval = setInterval(refresh, 10000);
    const weatherInterval = setInterval(loadDashboard, 5 * 60000);
    return () => {
      controller.abort();
      clearInterval(interval);
      clearInterval(weatherInterval);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [authenticated]);
  useEffect(() => {
    if (conversation && !privateMode)
      api("/conversations/" + conversation + "/messages")
        .then(setMessages)
        .catch((e) => notify(e.message, true));
    else setMessages([]);
  }, [conversation, privateMode]);
  useEffect(() => {
    if (page === "chat")
      bottom.current?.scrollIntoView({
        block: "end",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
  }, [messages, deltas, page]);
  const openSettings = (section: string) => {
    setSettingsSection(section);
    setPage("settings");
  };
  const activeTasks = tasks.filter((t) =>
    ["queued", "running", "waiting_user"].includes(t.state),
  );
  const chatTasks = tasks
    .filter((t) => t.conversation_id === conversation)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const runningChat = chatTasks.filter((t) =>
    ["queued", "running"].includes(t.state),
  );
  const visibleMessages = privateMode
    ? chatTasks.flatMap((t) => [
        { id: t.id + "u", role: "user", content: t.prompt },
        ...(t.result
          ? [{ id: t.id + "a", role: "assistant", content: t.result }]
          : []),
      ])
    : messages;
  const voiceState = status.native?.voice_state || "unavailable";
  const orbState =
    voiceState === "muted" && activeTasks.some((t) => t.state === "running")
      ? "processing"
      : voiceState;
  const unread = notifications.filter((n) => !n.read).length;
  const notConfigured =
    !status.models?.local && !status.models?.cloud_configured;
  const upcoming = (dashboard.calendar?.events || [])
    .filter(
      (e: Json) =>
        !e.start || new Date(e.start).getTime() >= Date.now() - 86400000,
    )
    .slice(0, 3);
  async function send(value = text) {
    if (!value.trim() || sending) return;
    if (!privacyReady) {
      notify("Wait for privacy settings to load.", true);
      return;
    }
    setSending(true);
    try {
      const signature = JSON.stringify([
        value,
        conversation,
        scope,
        privateMode,
        external,
      ]);
      if (submission.current?.signature !== signature)
        submission.current = { signature, id: crypto.randomUUID() };
      const task = await post("/chat", {
        text: value,
        conversation_id: conversation,
        scope,
        private: privateMode,
        external_authorized: external,
        privacy_revision: privacyRevision.current,
        request_id: submission.current.id,
      });
      submission.current = null;
      setConversation(task.conversation_id);
      setText("");
      setExternal(false);
      setPage("chat");
      refresh();
    } catch (e: any) {
      notify(e.message, true);
    } finally {
      setSending(false);
    }
  }
  async function native(action: string) {
    if (!status.native?.connected) {
      openSettings("voice");
      notify(
        "Open the macOS app for microphone and native capabilities.",
        true,
      );
      return;
    }
    try {
      await post("/voice/control", {
        action,
        ...(action === "listen" ? { private: privateMode, scope } : {}),
      });
      refresh();
    } catch (e: any) {
      notify(e.message, true);
    }
  }
  function newChat() {
    setConversation(null);
    setMessages([]);
    setText("");
    setPage("chat");
    input.current?.focus();
  }
  async function chooseConversation(c: Json) {
    if (!(await preference(false, c.scope))) return;
    setConversation(c.id);
    setPage("chat");
  }
  const composer = (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={
            privateMode
              ? "A private request, without history…"
              : "Ask a question, or tell me what you want to do…"
          }
          rows={text.split("\n").length > 2 ? 3 : 1}
          aria-label="Message to Jarvis"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <div className="composer-bottom">
          <div className="composer-options">
            <button
              title="New conversation"
              className="icon-btn"
              onClick={newChat}
            >
              <Plus size={17} />
            </button>
            <button
              className={"composer-option " + (privateMode ? "active" : "")}
              disabled={!privacyReady}
              onClick={() => preference(!privateMode, scope)}
              aria-pressed={privateMode}
            >
              <LockKeyhole size={13} />
              {privateMode ? "Private" : "Private session"}
            </button>
            <select
              aria-label="Conversation scope"
              value={scope}
              disabled={!privacyReady}
              onChange={(e) => preference(privateMode, e.target.value)}
            >
              <option value="personal">Personal</option>
              <option value="work">Work</option>
            </select>
          </div>
          <div className="composer-actions">
            {runningChat.length > 0 && (
              <button
                className="icon-btn"
                aria-label="Cancel the current task"
                onClick={() =>
                  post(
                    "/tasks/" +
                      runningChat[runningChat.length - 1].id +
                      "/cancel",
                  )
                    .then(refresh)
                    .catch((e) => notify(e.message, true))
                }
              >
                <Square size={15} />
              </button>
            )}
            <button
              className="icon-btn"
              aria-label="Talk to Jarvis"
              disabled={!privacyReady}
              onClick={() => native("listen")}
            >
              <Mic size={17} />
            </button>
            <button
              className="send-btn"
              disabled={!text.trim() || sending || !privacyReady}
              onClick={() => send()}
              aria-label="Send message"
            >
              {sending ? (
                <LoaderCircle size={17} className="spin" />
              ) : (
                <ArrowUp size={19} />
              )}
            </button>
          </div>
        </div>
      </div>
      <div className="composer-caption">
        <span>
          <span className="tiny-dot" />
          {profileLabels[status.profile] || "Service connection"}
        </span>
        <label className="external-choice">
          <input
            type="checkbox"
            checked={external}
            onChange={(e) => setExternal(e.target.checked)}
          />
          Authorize external actions for this request
        </label>
      </div>
    </div>
  );
  if (!authenticated)
    return (
      <div className="connect-screen">
        <img className="brand-mark brand-logo" src="/jarvis.svg" alt="" />
        <h1>A private connection.</h1>
        <p>
          Open the dashboard from the macOS app or with <code>jarvis open</code>
          .
          <br />
          You can also enter this installation's local token.
        </p>
        <input
          type="password"
          autoComplete="off"
          placeholder="Local token"
          aria-label="Jarvis local token"
          value={entryToken}
          onChange={(e) => setEntryToken(e.target.value)}
        />
        <button
          className="btn primary"
          disabled={!entryToken.trim()}
          onClick={() => {
            setToken(entryToken.trim());
            setAuthenticated(true);
            setEntryToken("");
          }}
        >
          Connect this browser <ArrowRight size={16} />
        </button>
        <small>The token authenticates only the service on your Mac.</small>
      </div>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => setPage("home")}
          aria-label="Jarvis home"
        >
          <img className="brand-mark brand-logo" src="/jarvis.svg" alt="" />
          <div>
            <strong>JARVIS</strong>
            <span>PERSONAL INTELLIGENCE</span>
          </div>
        </button>
        <button className="new-chat" onClick={newChat}>
          <Plus size={15} />
          New conversation<kbd>↵</kbd>
        </button>
        <nav aria-label="Main navigation">
          {(
            [
              { id: "home", label: "Overview", icon: LayoutDashboard },
              { id: "chat", label: "Conversation", icon: MessageSquare },
              { id: "tasks", label: "Tasks", icon: Workflow },
              { id: "routines", label: "Routines", icon: CalendarClock },
              { id: "memory", label: "Memory", icon: Brain },
              { id: "integrations", label: "Connections", icon: Link2 },
            ] as { id: Page; label: string; icon: any }[]
          ).map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "active" : ""}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={16} />
              <span>{item.label}</span>
              {item.id === "tasks" && activeTasks.length > 0 && (
                <b>{activeTasks.length}</b>
              )}
              {item.id === "tasks" && approvals.length > 0 && (
                <span className="attention-dot" />
              )}
            </button>
          ))}
        </nav>
        <div className="recent-heading">
          <span>RECENT CONVERSATIONS</span>
          <button
            className="icon-btn"
            aria-label="New conversation"
            onClick={newChat}
          >
            <Plus size={13} />
          </button>
        </div>
        <div className="recent-list">
          {conversations.slice(0, 6).map((c) => (
            <button
              key={c.id}
              className={
                conversation === c.id && page === "chat" ? "selected" : ""
              }
              onClick={() => chooseConversation(c)}
            >
              <MessageSquare size={12} />
              <span>{c.title}</span>
            </button>
          ))}
          {!conversations.length && <p>Context starts with a conversation.</p>}
        </div>
        <div className="sidebar-bottom">
          <div className="brain-state">
            <Brain size={17} />
            <div>
              <strong>Second Brain</strong>
              <span>
                {status.memory?.connection === "connected"
                  ? "Connected · sources and revisions"
                  : status.memory?.configured
                    ? "Configured · not connected"
                    : "Needs setup"}
              </span>
            </div>
            <span
              className={
                "tiny-dot " +
                (status.memory?.connection !== "connected" ? "off" : "")
              }
            />
          </div>
          <button
            className={"settings-link " + (page === "settings" ? "active" : "")}
            onClick={() => openSettings("models")}
          >
            <Settings2 size={16} />
            Settings
          </button>
          <div className="owner">
            <span className="owner-avatar">
              <Computer size={16} />
            </span>
            <div>
              <strong>Your workspace</strong>
              <small>Personal Mac</small>
            </div>
            <ShieldCheck size={14} />
          </div>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={12} />
            <span>
              {
                {
                  home: "Overview",
                  chat: "Conversation",
                  tasks: "Tasks",
                  routines: "Routines",
                  memory: "Memory",
                  integrations: "Connections",
                  settings: "Settings",
                }[page]
              }
            </span>
          </div>
          <div className="topbar-controls">
            <button
              className="icon-btn"
              aria-label="Settings"
              onClick={() => openSettings("models")}
            >
              <Settings2 size={16} />
            </button>
            <button
              className="icon-btn emergency-button"
              aria-label="Emergency stop"
              disabled={status.emergency_stop}
              title="Stop tasks, tools, voice, and calls"
              onClick={() =>
                post("/control/emergency", { stopped: true })
                  .then(() => {
                    refresh();
                    notify("Emergency stop is active.");
                  })
                  .catch((e) => notify(e.message, true))
              }
            >
              <OctagonX size={17} />
            </button>
            <span
              className={
                "connection " + (connection === "connected" ? "online" : "")
              }
            >
              <span className="tiny-dot" />
              {connection === "connected" ? "Local service" : "Reconnecting"}
            </span>
            <button
              className="icon-btn"
              aria-label={
                theme === "dark" ? "Use light theme" : "Use dark theme"
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <Sun size={16} />
            </button>
            <button
              className="icon-btn notification-button"
              aria-label="Notifications"
              onClick={() => {
                setShowNotifications(true);
                post("/notifications/read")
                  .then(refresh)
                  .catch(() => {});
              }}
            >
              <Bell size={17} />
              {unread > 0 && <i />}
            </button>
            <span className="topbar-divider" />
            {voiceState === "speaking" && (
              <button className="btn" onClick={() => native("stop")}>
                <Square size={13} />
                Stop speaking
              </button>
            )}
            <button
              className={
                "mic-status " + (status.native?.muted ? "muted-mic" : "")
              }
              onClick={() => native(status.native?.muted ? "unmute" : "mute")}
              aria-label={
                status.native?.muted ? "Unmute microphone" : "Mute microphone"
              }
            >
              {status.native?.muted ? <MicOff size={14} /> : <Mic size={14} />}
              <span>
                {status.native?.connected
                  ? status.native?.muted
                    ? "Microphone off"
                    : ["unavailable", "permission_required"].includes(
                          voiceState,
                        )
                      ? "Voice unavailable"
                      : voiceState === "recovering"
                        ? "Recovering voice…"
                        : "Voice active"
                  : "Voice needs activation"}
              </span>
            </button>
          </div>
        </header>
        {status.emergency_stop && (
          <div className="emergency-banner" role="alert">
            <span>
              Emergency stop is active. Tasks and tools are suspended.
            </span>
            <button
              className="btn"
              onClick={() =>
                post("/control/emergency", { stopped: false })
                  .then(refresh)
                  .catch((e) => notify(e.message, true))
              }
            >
              Re-enable service
            </button>
          </div>
        )}
        <div
          className={"content-area " + (page === "chat" ? "chat-content" : "")}
        >
          {page === "home" && (
            <div className="dashboard">
              <div className="dashboard-title">
                <div>
                  <span className="eyebrow">YOUR SPACE, ALWAYS CONNECTED</span>
                  <h1>A thought. An action.</h1>
                  <p>The right context and the tools to move forward.</p>
                </div>
                <div className="date-chip">
                  <CalendarDays size={15} />
                  {new Intl.DateTimeFormat("en-GB", {
                    weekday: "short",
                    day: "numeric",
                    month: "long",
                  }).format(new Date())}
                </div>
              </div>
              {notConfigured && (
                <div className="setup-banner">
                  <div>
                    <Computer size={20} />
                    <span>
                      <strong>Start with your model.</strong>
                      <small>
                        Ollama, LM Studio, or a cloud provider: choose how
                        Jarvis thinks.
                      </small>
                    </span>
                  </div>
                  <button
                    className="btn"
                    onClick={() => openSettings("models")}
                  >
                    Configure <ArrowRight size={14} />
                  </button>
                </div>
              )}
              <div className="dashboard-grid">
                <aside className="dashboard-left">
                  <section className="widget weather-widget">
                    <div className="widget-heading">
                      <span>
                        <CloudSun size={16} />
                        WEATHER
                      </span>
                      <small>
                        {dashboard.weather?.stale
                          ? "Needs refresh"
                          : dashboard.weather?.state === "ready"
                            ? "Open-Meteo"
                            : ""}
                      </small>
                    </div>
                    {dashboard.weather?.state === "ready" ? (
                      <>
                        <div className="weather-temperature">
                          {Math.round(dashboard.weather.current.temperature_2m)}
                          <span>°</span>
                          <CloudSun size={48} strokeWidth={1} />
                        </div>
                        <h3>
                          {weatherNames(dashboard.weather.current.weather_code)}
                        </h3>
                        <p>{dashboard.weather.location}</p>
                        <div className="weather-metrics">
                          <span>
                            Feels like{" "}
                            <strong>
                              {Math.round(
                                dashboard.weather.current.apparent_temperature,
                              )}
                              °
                            </strong>
                          </span>
                          <span>
                            Wind{" "}
                            <strong>
                              {Math.round(
                                dashboard.weather.current.wind_speed_10m,
                              )}{" "}
                              km/h
                            </strong>
                          </span>
                        </div>
                        <a
                          className="source-link"
                          href="https://open-meteo.com/"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Open-Meteo ·{" "}
                          {formatDate(dashboard.weather.updated_at, true)}
                          <ArrowUpRight size={10} />
                        </a>
                      </>
                    ) : (
                      <div className="widget-unconfigured">
                        <CloudSun size={34} strokeWidth={1} />
                        <h3>
                          {dashboard.weather?.state === "loading"
                            ? "Checking the weather…"
                            : "The weather in your city."}
                        </h3>
                        <p>
                          {dashboard.weather?.message ||
                            "Set a location for real, current information."}
                        </p>
                        <button
                          className="text-btn"
                          onClick={() => openSettings("productivity")}
                        >
                          Choose location <ArrowRight size={12} />
                        </button>
                      </div>
                    )}
                  </section>
                  <section className="widget agenda-widget">
                    <div className="widget-heading">
                      <span>
                        <CalendarDays size={15} />
                        YOUR AGENDA
                      </span>
                      <button
                        className="icon-btn"
                        onClick={() => openSettings("productivity")}
                        aria-label="Set up calendar"
                      >
                        <ArrowUpRight size={14} />
                      </button>
                    </div>
                    {upcoming.length ? (
                      <div className="agenda-events">
                        {upcoming.map((e: Json, i: number) => (
                          <div className="agenda-event" key={e.id + "-" + i}>
                            <span>
                              {e.all_day ? "Day" : formatDate(e.start, true)}
                            </span>
                            <div>
                              <h3>{e.title}</h3>
                              <small>
                                {e.calendar ||
                                  e.location?.displayName ||
                                  e.location ||
                                  dashboard.calendar.provider}
                              </small>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="widget-unconfigured">
                        <h3>
                          {dashboard.calendar?.state === "ready"
                            ? "Some room to breathe."
                            : "Your next events, right here."}
                        </h3>
                        <p>
                          {dashboard.calendar?.state === "ready"
                            ? "No events in the selected period."
                            : dashboard.calendar?.message ||
                              "Connect your calendar to see your day."}
                        </p>
                        <button
                          className="text-btn"
                          onClick={() => openSettings("productivity")}
                        >
                          Calendar <ArrowRight size={12} />
                        </button>
                      </div>
                    )}
                  </section>
                </aside>
                <section className="dashboard-center">
                  <Orb
                    state={orbState}
                    level={orbState === "speaking" ? audio.output : audio.input}
                  />
                  <div className="voice-actions">
                    <button className="btn" onClick={() => native("listen")}>
                      <Mic size={14} />
                      Talk to Jarvis<kbd>⌘ ⇧ J</kbd>
                    </button>
                    {!status.native?.connected && (
                      <button
                        className="text-btn"
                        onClick={() => openSettings("voice")}
                      >
                        Set up voice
                      </button>
                    )}
                  </div>
                  <div className="quick-requests">
                    <span className="eyebrow">WHERE SHALL WE START?</span>
                    <button
                      onClick={() =>
                        send(
                          "What does my day look like? Check my events and tasks.",
                        )
                      }
                    >
                      <CalendarDays size={14} />
                      A look at your day
                      <ArrowUpRight size={12} />
                    </button>
                    <button
                      onClick={() => {
                        setText("Research in depth: ");
                        setPage("chat");
                        input.current?.focus();
                      }}
                    >
                      <Search size={14} />
                      Explore a topic
                      <ArrowUpRight size={12} />
                    </button>
                    <button
                      onClick={() => {
                        setText("Help me work on the project ");
                        setPage("chat");
                        input.current?.focus();
                      }}
                    >
                      <Code2 size={14} />
                      Work on code
                      <ArrowUpRight size={12} />
                    </button>
                  </div>
                </section>
                <aside className="dashboard-right">
                  <section className="widget">
                    <div className="widget-heading">
                      <span>
                        <Workflow size={15} />
                        WORK IN PROGRESS
                      </span>
                      <button
                        className="icon-btn"
                        aria-label="Open tasks"
                        onClick={() => setPage("tasks")}
                      >
                        <ArrowUpRight size={14} />
                      </button>
                    </div>
                    {activeTasks.length ? (
                      <div className="compact-tasks">
                        {activeTasks.slice(0, 3).map((t) => (
                          <button key={t.id} onClick={() => setPage("tasks")}>
                            <span className="compact-task-icon">
                              {t.state === "running" ? (
                                <LoaderCircle size={15} className="spin" />
                              ) : (
                                <Workflow size={15} />
                              )}
                            </span>
                            <span>
                              <strong>{t.title}</strong>
                              <small>
                                <Badge state={t.state} />
                              </small>
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="widget-unconfigured">
                        <h3>Ready to make room.</h3>
                        <p>
                          Research, coding, and checks continue in the
                          background while you do something else.
                        </p>
                        <span className="quiet-status">
                          <span className="tiny-dot" />
                          No open tasks
                        </span>
                      </div>
                    )}
                  </section>
                  <section className="widget memory-widget">
                    <div className="widget-heading">
                      <span>
                        <Brain size={15} />
                        MEMORY THAT CONTINUES
                      </span>
                    </div>
                    <h3>Pick up where we left off.</h3>
                    <p>
                      Preferences, projects, and decisions stay in your Second
                      Brain.
                    </p>
                    <button
                      className="text-btn"
                      onClick={() => setPage("memory")}
                    >
                      Explore memory <ArrowRight size={12} />
                    </button>
                  </section>
                  <div className="local-note">
                    <ShieldCheck size={15} />
                    <p>
                      The service lives on your Mac.
                      <br />
                      You choose what to connect.
                    </p>
                  </div>
                  {approvals.length > 0 && (
                    <button
                      className="attention-mini"
                      onClick={() => setPage("tasks")}
                    >
                      <span className="attention-dot" />
                      {approvals.length} pending decisions
                      <ArrowRight size={13} />
                    </button>
                  )}
                </aside>
              </div>
              {composer}
              <footer className="dashboard-footer">
                <span>
                  <span className="tiny-dot" />
                  {status.models?.local ||
                    status.models?.cloud ||
                    "Model needs setup"}
                </span>
                <span>Your Mac must be awake to run tasks and calls.</span>
              </footer>
            </div>
          )}
          {page === "chat" && (
            <div className="chat-view">
              <div className="chat-heading">
                <div>
                  <span className="eyebrow">
                    ONE CONVERSATION, MANY POSSIBILITIES
                  </span>
                  <h1>
                    {privateMode
                      ? "A private session."
                      : conversations.find((c) => c.id === conversation)
                          ?.title || "What shall we work on?"}
                  </h1>
                </div>
                <button className="btn ghost" onClick={newChat}>
                  <Plus size={14} />
                  New
                </button>
              </div>
              <div className="message-list">
                {!visibleMessages.length && !runningChat.length && (
                  <div className="chat-welcome">
                    <img
                      className="brand-mark brand-logo"
                      src="/jarvis.svg"
                      alt=""
                    />
                    <h2>Tell me the goal.</h2>
                    <p>
                      I can search, remember, code, and use your connected
                      tools.
                    </p>
                    {privateMode && (
                      <span className="privacy-label">
                        <LockKeyhole size={13} />
                        Content is not retained.
                      </span>
                    )}
                  </div>
                )}
                {visibleMessages.map((m: Json) => (
                  <article className={"message message-" + m.role} key={m.id}>
                    <div className="message-avatar">
                      {m.role === "assistant" ? "J" : "YOU"}
                    </div>
                    <div className="message-body">
                      <span className="message-author">
                        {m.role === "assistant" ? "Jarvis" : "You"}
                      </span>
                      <Text value={m.content} />
                    </div>
                  </article>
                ))}
                {runningChat.map((t) => (
                  <article className="message message-assistant" key={t.id}>
                    <div className="message-avatar">J</div>
                    <div className="message-body">
                      <div className="message-working">
                        <LoaderCircle size={13} className="spin" />
                        {t.state === "queued"
                          ? "Waiting for the engine"
                          : "Working on your request"}
                      </div>
                      {deltas[t.id] && <Text value={deltas[t.id]} />}
                    </div>
                  </article>
                ))}
                {chatTasks
                  .filter((t) => ["failed", "waiting_user"].includes(t.state))
                  .map((t) => (
                    <div className="chat-alert" key={t.id}>
                      <Badge state={t.state} />
                      <p>
                        {t.error ||
                          "I prepared a concrete proposal. Review it before continuing."}
                      </p>
                      {t.state === "waiting_user" && (
                        <button
                          className="text-btn"
                          onClick={() => setPage("tasks")}
                        >
                          Open decision <ArrowRight size={13} />
                        </button>
                      )}
                    </div>
                  ))}
                <div ref={bottom} />
              </div>
              {composer}
            </div>
          )}
          {page === "tasks" && (
            <Tasks
              tasks={tasks}
              schedules={schedules}
              approvals={approvals}
              refresh={refresh}
              notify={notify}
            />
          )}{" "}
          {page === "routines" && (
            <Routines
              tasks={tasks}
              schedules={schedules}
              approvals={approvals}
              refresh={refresh}
              notify={notify}
            />
          )}{" "}
          {page === "memory" && (
            <Memory notify={notify} openSettings={openSettings} />
          )}{" "}
          {page === "integrations" && (
            <Integrations notify={notify} openSettings={openSettings} />
          )}{" "}
          {page === "settings" && (
            <Settings
              key={settingsSection}
              initial={settingsSection}
              notify={notify}
              onSaved={() => {
                refresh();
                loadDashboard();
              }}
            />
          )}
        </div>
      </main>
      {toast && (
        <div className={"toast " + (toast.error ? "error" : "")} role="status">
          {toast.error ? <X size={15} /> : <Check size={15} />}
          <span>{toast.message}</span>
          <button
            className="icon-btn"
            aria-label="Dismiss message"
            onClick={() => setToast(null)}
          >
            <X size={13} />
          </button>
        </div>
      )}
      {showNotifications && (
        <Modal
          title="Your notifications"
          onClose={() => setShowNotifications(false)}
        >
          <div className="modal-body">
            {notifications.length ? (
              notifications.map((n) => (
                <article className="notification-row" key={n.id}>
                  <Bell size={17} />
                  <div>
                    <h3>{n.title}</h3>
                    <p>{n.body}</p>
                    <small>{formatDate(n.created_at)}</small>
                  </div>
                </article>
              ))
            ) : (
              <Empty icon={Bell} title="All quiet">
                Notifications appear when there is a useful result or decision.
              </Empty>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
