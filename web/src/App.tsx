import {
  t as tr,
  useI18n,
  uiLocale,
  formatNumber,
  syncInterfaceLanguage,
} from "./i18n";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUp,
  Bell,
  Brain,
  CalendarClock,
  Check,
  ChevronRight,
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
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Sun,
  Workflow,
  X,
} from "lucide-react";
import { api, eventStream, hasToken, post, setToken, type Json } from "./api";
import {
  Badge,
  Empty,
  ErrorMessage,
  Modal,
  Text,
  formatDate,
  profileLabels,
} from "./components";
import { Tasks, Routines } from "./Activity";
import { Memory, Integrations } from "./Memory";
import Settings from "./Settings";
import CommandCenter, { SystemClock, VoiceSignal } from "./CommandCenter";
import brandIcon from "./assets/jarvis.svg";

type Page =
  | "home"
  | "chat"
  | "tasks"
  | "routines"
  | "memory"
  | "integrations"
  | "settings";

export default function App() {
  useI18n();
  const [authenticated, setAuthenticated] = useState(hasToken()),
    [entryToken, setEntryToken] = useState(""),
    [page, setPage] = useState<Page>("home"),
    [settingsSection, setSettingsSection] = useState("interface"),
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
    if (authenticated) {
      syncPreference();
      syncInterfaceLanguage().catch(() => {});
    }
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
        if (event.data.state === "connected") {
          syncPreference();
          syncInterfaceLanguage().catch(() => {});
        }
      } else if (event.type === "settings.updated") {
        syncInterfaceLanguage().catch(() => {});
        refresh();
      } else if (event.type === "voice.session.updated") {
        syncPreference();
      } else if (event.type === "audio.level") setAudio(event.data);
      else if (event.type === "assistant.delta") {
        setDeltas((current) => ({
          ...current,
          [event.task_id]: (current[event.task_id] || "") + event.data.text,
        }));
      } else {
        // Replayed events can predate the status snapshot. Refresh the current
        // native state instead of briefly showing an old microphone state.
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
  const portableText = status.platform?.native_voice === false;
  const orbState =
    voiceState === "muted" && activeTasks.some((t) => t.state === "running")
      ? "processing"
      : voiceState;
  const unread = notifications.filter((n) => !n.read).length;
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
    if (portableText) {
      notify(
        "Desktop voice requires the native macOS app. Use text on this platform.",
      );
      return;
    }
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
              ? tr("A private request, without history…")
              : tr("Ask a question, or tell me what you want to do…")
          }
          rows={text.split("\n").length > 2 ? 3 : 1}
          aria-label={tr("Message to Jarvis")}
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
              title={tr("New conversation")}
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
              {privateMode ? tr("Private") : tr("Private session")}
            </button>
            <select
              aria-label={tr("Conversation scope")}
              value={scope}
              disabled={!privacyReady}
              onChange={(e) => preference(privateMode, e.target.value)}
            >
              <option value="personal">{tr("Personal")}</option>
              <option value="work">{tr("Work")}</option>
            </select>
          </div>
          <div className="composer-actions">
            {runningChat.length > 0 && (
              <button
                className="icon-btn"
                aria-label={tr("Cancel the current task")}
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
              aria-label={tr("Talk to Jarvis")}
              disabled={!privacyReady || portableText}
              onClick={() => native("listen")}
            >
              <Mic size={17} />
            </button>
            <button
              className="send-btn"
              disabled={!text.trim() || sending || !privacyReady}
              onClick={() => send()}
              aria-label={tr("Send message")}
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
          {tr(profileLabels[status.profile] || "Service connection")}
        </span>
        <label
          className="external-choice"
          title={tr(
            "Actions after reading outside content, and queries containing private context, still need a specific approval.",
          )}
        >
          <input
            type="checkbox"
            checked={external}
            onChange={(e) => setExternal(e.target.checked)}
          />
          {tr("Preauthorize direct actions")}
        </label>
      </div>
    </div>
  );
  if (!authenticated)
    return (
      <div className="connect-screen">
        <img className="brand-mark brand-logo" src={brandIcon} alt="" />
        <h1>{tr("A private connection.")}</h1>
        <p>
          {tr("Open the dashboard from the macOS app or with ")}
          <code>{tr("jarvis open")}</code>
          .
          <br />
          {tr("You can also enter this installation's local token.")}
        </p>
        <input
          type="password"
          autoComplete="off"
          placeholder={tr("Local token")}
          aria-label={tr("Jarvis local token")}
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
          {tr("Connect this browser ")}
          <ArrowRight size={16} />
        </button>
        <small>
          {tr("The token authenticates only the service on your computer.")}
        </small>
      </div>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => setPage("home")}
          aria-label={tr("Jarvis home")}
        >
          <img className="brand-mark brand-logo" src={brandIcon} alt="" />
          <div>
            <strong>{tr("JARVIS")}</strong>
            <span>{tr("PERSONAL INTELLIGENCE")}</span>
          </div>
        </button>
        <button className="new-chat" onClick={newChat}>
          <Plus size={15} />
          {tr("New conversation")}
          <kbd>↵</kbd>
        </button>
        <span className="nav-label eyebrow">{tr("WORKSPACE")}</span>
        <nav aria-label={tr("Main navigation")}>
          {(
            [
              { id: "home", label: tr("Overview"), icon: LayoutDashboard },
              { id: "chat", label: tr("Conversation"), icon: MessageSquare },
              { id: "tasks", label: tr("Tasks"), icon: Workflow },
              { id: "routines", label: tr("Routines"), icon: CalendarClock },
              { id: "memory", label: tr("Memory"), icon: Brain },
              { id: "integrations", label: tr("Connections"), icon: Link2 },
            ] as { id: Page; label: string; icon: any }[]
          ).map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "active" : ""}
              aria-label={item.label}
              aria-current={page === item.id ? "page" : undefined}
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
          <span>{tr("RECENT CONVERSATIONS")}</span>
          <button
            className="icon-btn"
            aria-label={tr("New conversation")}
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
          {!conversations.length && (
            <p>{tr("Context starts with a conversation.")}</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <button
            className="sidebar-voice"
            onClick={() => openSettings("voice")}
            aria-label={tr("Open voice settings")}
          >
            <span className="eyebrow">
              {tr("VOICE CHANNEL")}{" "}
              <span
                className={
                  "tiny-dot " +
                  (status.native?.muted || !status.native?.connected
                    ? "off"
                    : "")
                }
              />
            </span>
            <VoiceSignal
              level={
                status.native?.muted ||
                !status.native?.connected ||
                !["armed", "listening", "speaking", "followup"].includes(
                  voiceState,
                )
                  ? 0
                  : voiceState === "speaking"
                    ? audio.output
                    : audio.input
              }
            />
            <span>
              <Mic size={12} />
              {!status.native?.connected
                ? tr("Not connected")
                : status.native?.muted
                  ? tr("Microphone muted")
                  : voiceState === "speaking"
                    ? tr("Jarvis is speaking")
                    : voiceState === "armed"
                      ? tr("Listening for Jarvis")
                      : voiceState === "listening" || voiceState === "followup"
                        ? tr("Listening")
                        : tr("Open voice settings")}
            </span>
          </button>
          <div className="brain-state">
            <Brain size={17} />
            <div>
              <strong>{tr("Second Brain")}</strong>
              <span>
                {status.memory?.connection === "connected"
                  ? tr("Connected · sources and revisions")
                  : status.memory?.configured
                    ? tr("Configured · not connected")
                    : tr("Needs setup")}
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
            onClick={() => openSettings("interface")}
          >
            <Settings2 size={16} />
            {tr("Settings")}
          </button>
          <div className="owner">
            <span className="owner-avatar">
              <Computer size={16} />
            </span>
            <div>
              <strong>{tr("Your workspace")}</strong>
              <small>
                {portableText ? tr("Local computer") : tr("Personal Mac")}
              </small>
            </div>
            <ShieldCheck size={14} />
          </div>
        </div>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            {tr("Workspace ")}
            <ChevronRight size={12} />
            <span>
              {
                {
                  home: tr("Overview"),
                  chat: tr("Conversation"),
                  tasks: tr("Tasks"),
                  routines: tr("Routines"),
                  memory: tr("Memory"),
                  integrations: tr("Connections"),
                  settings: tr("Settings"),
                }[page]
              }
            </span>
          </div>
          <SystemClock timezone={status.timezone} />
          <div className="topbar-controls">
            <button
              className="icon-btn"
              aria-label={tr("Settings")}
              onClick={() => openSettings("interface")}
            >
              <Settings2 size={16} />
            </button>
            <button
              className="icon-btn emergency-button"
              aria-label={tr("Emergency stop")}
              disabled={status.emergency_stop}
              title={tr("Stop tasks, tools, voice, and calls")}
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
              {connection === "connected"
                ? tr("Local service")
                : tr("Reconnecting")}
            </span>
            <button
              className="icon-btn"
              aria-label={
                theme === "dark" ? tr("Use light theme") : tr("Use dark theme")
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <Sun size={16} />
            </button>
            <button
              className="icon-btn notification-button"
              aria-label={tr("Notifications")}
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
                {tr("Stop speaking")}
              </button>
            )}
            <button
              className={
                "mic-status " + (status.native?.muted ? "muted-mic" : "")
              }
              onClick={() =>
                portableText
                  ? newChat()
                  : native(status.native?.muted ? "unmute" : "mute")
              }
              aria-label={
                portableText
                  ? tr("Open text conversation")
                  : status.native?.muted
                    ? tr("Unmute microphone")
                    : tr("Mute microphone")
              }
            >
              {portableText ? (
                <MessageSquare size={14} />
              ) : status.native?.muted ? (
                <MicOff size={14} />
              ) : (
                <Mic size={14} />
              )}
              <span>
                {portableText
                  ? tr("Text mode")
                  : status.native?.connected
                    ? status.native?.muted
                      ? tr("Microphone off")
                      : ["unavailable", "permission_required"].includes(
                            voiceState,
                          )
                        ? tr("Voice unavailable")
                        : voiceState === "recovering"
                          ? tr("Recovering voice…")
                          : tr("Voice active")
                    : tr("Voice needs activation")}
              </span>
            </button>
          </div>
        </header>
        {status.emergency_stop && (
          <div className="emergency-banner" role="alert">
            <span>
              {tr("Emergency stop is active. Tasks and tools are suspended.")}
            </span>
            <button
              className="btn"
              onClick={() =>
                post("/control/emergency", { stopped: false })
                  .then(refresh)
                  .catch((e) => notify(e.message, true))
              }
            >
              {tr("Re-enable service")}
            </button>
          </div>
        )}
        <div
          className={"content-area " + (page === "chat" ? "chat-content" : "")}
        >
          {page === "home" && (
            <CommandCenter
              status={status}
              dashboard={dashboard}
              tasks={tasks}
              schedules={schedules}
              approvals={approvals}
              connection={connection}
              orbState={orbState}
              audio={audio}
              composer={composer}
              onPage={setPage}
              onSettings={openSettings}
              onListen={() => native("listen")}
              onNewChat={newChat}
              onCompose={(prompt) => {
                setText(prompt);
                setPage("chat");
                setTimeout(() => input.current?.focus(), 0);
              }}
            />
          )}
          {page === "chat" && (
            <div className="chat-view">
              <div className="chat-heading">
                <div>
                  <span className="eyebrow">
                    {tr("ONE CONVERSATION, MANY POSSIBILITIES")}
                  </span>
                  <h1>
                    {privateMode
                      ? tr("A private session.")
                      : conversations.find((c) => c.id === conversation)
                          ?.title || tr("What shall we work on?")}
                  </h1>
                </div>
                <button className="btn ghost" onClick={newChat}>
                  <Plus size={14} />
                  {tr("New")}
                </button>
              </div>
              <div className="message-list">
                {!visibleMessages.length && !runningChat.length && (
                  <div className="chat-welcome">
                    <img
                      className="brand-mark brand-logo"
                      src={brandIcon}
                      alt=""
                    />
                    <h2>{tr("Tell me the goal.")}</h2>
                    <p>
                      {tr(
                        "I can search, remember, code, and use your connected tools.",
                      )}
                    </p>
                    {privateMode && (
                      <span className="privacy-label">
                        <LockKeyhole size={13} />
                        {tr("Content is not retained.")}
                      </span>
                    )}
                  </div>
                )}
                {visibleMessages.map((m: Json) => (
                  <article className={"message message-" + m.role} key={m.id}>
                    <div className="message-avatar">
                      {m.role === "assistant" ? tr("J") : tr("YOU")}
                    </div>
                    <div className="message-body">
                      <span className="message-author">
                        {m.role === "assistant" ? tr("Jarvis") : tr("You")}
                      </span>
                      <Text value={m.content} />
                    </div>
                  </article>
                ))}
                {runningChat.map((t) => (
                  <article className="message message-assistant" key={t.id}>
                    <div className="message-avatar">{tr("J")}</div>
                    <div className="message-body">
                      <div className="message-working">
                        <LoaderCircle size={13} className="spin" />
                        {t.state === "queued"
                          ? tr("Waiting for the engine")
                          : tr("Working on your request")}
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
                      <div className="body-copy">
                        {t.error ? (
                          <ErrorMessage message={t.error} />
                        ) : (
                          tr(
                            "I prepared a concrete proposal. Review it before continuing.",
                          )
                        )}
                      </div>
                      {t.state === "waiting_user" && (
                        <button
                          className="text-btn"
                          onClick={() => setPage("tasks")}
                        >
                          {tr("Open decision ")}
                          <ArrowRight size={13} />
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
              platform={status.platform}
              nativeVoice={status.native}
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
          <div className="toast-copy">
            {toast.error ? (
              <ErrorMessage message={toast.message} />
            ) : (
              tr(toast.message)
            )}
          </div>
          <button
            className="icon-btn"
            aria-label={tr("Dismiss message")}
            onClick={() => setToast(null)}
          >
            <X size={13} />
          </button>
        </div>
      )}
      {showNotifications && (
        <Modal
          title={tr("Your notifications")}
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
              <Empty icon={Bell} title={tr("All quiet")}>
                {tr(
                  "Notifications appear when there is a useful result or decision.",
                )}
              </Empty>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
