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
    ? "Sereno"
    : code <= 2
      ? "Parzialmente nuvoloso"
      : code === 3
        ? "Nuvoloso"
        : code <= 48
          ? "Nebbia"
          : code <= 67
            ? "Pioggia"
            : code <= 77
              ? "Neve"
              : code <= 82
                ? "Rovesci"
                : code <= 86
                  ? "Neve"
                  : "Temporali";

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
      notify("Attendi il caricamento delle impostazioni di privacy.", true);
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
        "Apri la shell macOS per il microfono e le capacità native.",
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
              ? "Una richiesta privata, senza cronologia…"
              : "Chiedimi qualcosa, oppure dimmi cosa vuoi fare…"
          }
          rows={text.split("\n").length > 2 ? 3 : 1}
          aria-label="Messaggio per Jarvis"
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
              title="Nuova conversazione"
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
              {privateMode ? "Privata" : "Sessione privata"}
            </button>
            <select
              aria-label="Ambito della conversazione"
              value={scope}
              disabled={!privacyReady}
              onChange={(e) => preference(privateMode, e.target.value)}
            >
              <option value="personal">Personale</option>
              <option value="work">Lavoro</option>
            </select>
          </div>
          <div className="composer-actions">
            {runningChat.length > 0 && (
              <button
                className="icon-btn"
                aria-label="Annulla il task corrente"
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
              aria-label="Parla con Jarvis"
              disabled={!privacyReady}
              onClick={() => native("listen")}
            >
              <Mic size={17} />
            </button>
            <button
              className="send-btn"
              disabled={!text.trim() || sending || !privacyReady}
              onClick={() => send()}
              aria-label="Invia messaggio"
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
          {profileLabels[status.profile] || "Collegamento al servizio"}
        </span>
        <label className="external-choice">
          <input
            type="checkbox"
            checked={external}
            onChange={(e) => setExternal(e.target.checked)}
          />
          Autorizza azioni esterne per questa richiesta
        </label>
      </div>
    </div>
  );
  if (!authenticated)
    return (
      <div className="connect-screen">
        <div className="brand-mark">J</div>
        <h1>Un collegamento privato.</h1>
        <p>
          Apri la dashboard dalla shell macOS o con <code>jarvis open</code>.
          <br />
          Puoi anche inserire il token locale della tua installazione.
        </p>
        <input
          type="password"
          autoComplete="off"
          placeholder="Token locale"
          aria-label="Token locale Jarvis"
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
          Collega questo browser <ArrowRight size={16} />
        </button>
        <small>Il token autentica soltanto il servizio sul tuo Mac.</small>
      </div>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => setPage("home")}
          aria-label="Home Jarvis"
        >
          <span className="brand-mark">J</span>
          <div>
            <strong>JARVIS</strong>
            <span>PERSONAL INTELLIGENCE</span>
          </div>
        </button>
        <button className="new-chat" onClick={newChat}>
          <Plus size={15} />
          Nuova conversazione<kbd>↵</kbd>
        </button>
        <nav aria-label="Navigazione principale">
          {(
            [
              { id: "home", label: "Panoramica", icon: LayoutDashboard },
              { id: "chat", label: "Conversazione", icon: MessageSquare },
              { id: "tasks", label: "Attività", icon: Workflow },
              { id: "routines", label: "Routine", icon: CalendarClock },
              { id: "memory", label: "Memoria", icon: Brain },
              { id: "integrations", label: "Connessioni", icon: Link2 },
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
          <span>CONVERSAZIONI RECENTI</span>
          <button
            className="icon-btn"
            aria-label="Nuova conversazione"
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
            <p>Il contesto comincia con una conversazione.</p>
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="brain-state">
            <Brain size={17} />
            <div>
              <strong>Second Brain</strong>
              <span>
                {status.memory?.connection === "connected"
                  ? "Collegato · fonti e revisioni"
                  : status.memory?.configured
                    ? "Configurato · da collegare"
                    : "Da configurare"}
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
            Impostazioni
          </button>
          <div className="owner">
            <span className="owner-avatar">
              <Computer size={16} />
            </span>
            <div>
              <strong>Il tuo workspace</strong>
              <small>Mac personale</small>
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
                  home: "Panoramica",
                  chat: "Conversazione",
                  tasks: "Attività",
                  routines: "Routine",
                  memory: "Memoria",
                  integrations: "Connessioni",
                  settings: "Impostazioni",
                }[page]
              }
            </span>
          </div>
          <div className="topbar-controls">
            <button
              className="icon-btn"
              aria-label="Impostazioni"
              onClick={() => openSettings("models")}
            >
              <Settings2 size={16} />
            </button>
            <button
              className="icon-btn emergency-button"
              aria-label="Arresto di emergenza"
              disabled={status.emergency_stop}
              title="Ferma task, strumenti, voce e telefonate"
              onClick={() =>
                post("/control/emergency", { stopped: true })
                  .then(() => {
                    refresh();
                    notify("Arresto di emergenza attivo.");
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
              {connection === "connected" ? "Servizio locale" : "Riconnessione"}
            </span>
            <button
              className="icon-btn"
              aria-label={
                theme === "dark" ? "Usa tema chiaro" : "Usa tema scuro"
              }
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <Sun size={16} />
            </button>
            <button
              className="icon-btn notification-button"
              aria-label="Notifiche"
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
                Interrompi voce
              </button>
            )}
            <button
              className={
                "mic-status " + (status.native?.muted ? "muted-mic" : "")
              }
              onClick={() => native(status.native?.muted ? "unmute" : "mute")}
              aria-label={
                status.native?.muted
                  ? "Riattiva microfono"
                  : "Disattiva microfono"
              }
            >
              {status.native?.muted ? <MicOff size={14} /> : <Mic size={14} />}
              <span>
                {status.native?.connected
                  ? status.native?.muted
                    ? "Microfono spento"
                    : ["unavailable", "permission_required"].includes(
                          voiceState,
                        )
                      ? "Voce indisponibile"
                      : "Voce attiva"
                  : "Voce da attivare"}
              </span>
            </button>
          </div>
        </header>
        {status.emergency_stop && (
          <div className="emergency-banner" role="alert">
            <span>
              Arresto di emergenza attivo. Task e strumenti sono sospesi.
            </span>
            <button
              className="btn"
              onClick={() =>
                post("/control/emergency", { stopped: false })
                  .then(refresh)
                  .catch((e) => notify(e.message, true))
              }
            >
              Riabilita il servizio
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
                  <span className="eyebrow">
                    IL TUO SPAZIO, SEMPRE CONNESSO
                  </span>
                  <h1>Un pensiero. Un’azione.</h1>
                  <p>Il contesto giusto, gli strumenti per andare avanti.</p>
                </div>
                <div className="date-chip">
                  <CalendarDays size={15} />
                  {new Intl.DateTimeFormat("it-IT", {
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
                      <strong>Cominciamo dal tuo modello.</strong>
                      <small>
                        Ollama, LM Studio oppure un provider cloud: scegli come
                        pensa Jarvis.
                      </small>
                    </span>
                  </div>
                  <button
                    className="btn"
                    onClick={() => openSettings("models")}
                  >
                    Configura <ArrowRight size={14} />
                  </button>
                </div>
              )}
              <div className="dashboard-grid">
                <aside className="dashboard-left">
                  <section className="widget weather-widget">
                    <div className="widget-heading">
                      <span>
                        <CloudSun size={16} />
                        IL METEO
                      </span>
                      <small>
                        {dashboard.weather?.stale
                          ? "Da aggiornare"
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
                            Percepita{" "}
                            <strong>
                              {Math.round(
                                dashboard.weather.current.apparent_temperature,
                              )}
                              °
                            </strong>
                          </span>
                          <span>
                            Vento{" "}
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
                            ? "Controllo il meteo…"
                            : "Il meteo, nella tua città."}
                        </h3>
                        <p>
                          {dashboard.weather?.message ||
                            "Imposta una località per avere informazioni reali e aggiornate."}
                        </p>
                        <button
                          className="text-btn"
                          onClick={() => openSettings("productivity")}
                        >
                          Scegli località <ArrowRight size={12} />
                        </button>
                      </div>
                    )}
                  </section>
                  <section className="widget agenda-widget">
                    <div className="widget-heading">
                      <span>
                        <CalendarDays size={15} />
                        LA TUA AGENDA
                      </span>
                      <button
                        className="icon-btn"
                        onClick={() => openSettings("productivity")}
                        aria-label="Configura calendario"
                      >
                        <ArrowUpRight size={14} />
                      </button>
                    </div>
                    {upcoming.length ? (
                      <div className="agenda-events">
                        {upcoming.map((e: Json, i: number) => (
                          <div className="agenda-event" key={e.id + "-" + i}>
                            <span>
                              {e.all_day ? "Giorno" : formatDate(e.start, true)}
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
                            ? "Un po’ di spazio libero."
                            : "I prossimi impegni, qui."}
                        </h3>
                        <p>
                          {dashboard.calendar?.state === "ready"
                            ? "Nessun evento nel periodo consultato."
                            : dashboard.calendar?.message ||
                              "Collega il calendario per vedere la giornata."}
                        </p>
                        <button
                          className="text-btn"
                          onClick={() => openSettings("productivity")}
                        >
                          Calendario <ArrowRight size={12} />
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
                      Parla con Jarvis<kbd>⌘ ⇧ J</kbd>
                    </button>
                    {!status.native?.connected && (
                      <button
                        className="text-btn"
                        onClick={() => openSettings("voice")}
                      >
                        Configura la voce
                      </button>
                    )}
                  </div>
                  <div className="quick-requests">
                    <span className="eyebrow">DA DOVE COMINCIAMO?</span>
                    <button
                      onClick={() =>
                        send(
                          "Che giornata mi aspetta? Controlla i miei impegni e le attività.",
                        )
                      }
                    >
                      <CalendarDays size={14} />
                      Uno sguardo alla giornata
                      <ArrowUpRight size={12} />
                    </button>
                    <button
                      onClick={() => {
                        setText("Fai una ricerca approfondita su ");
                        setPage("chat");
                        input.current?.focus();
                      }}
                    >
                      <Search size={14} />
                      Esploriamo un argomento
                      <ArrowUpRight size={12} />
                    </button>
                    <button
                      onClick={() => {
                        setText("Aiutami a lavorare sul progetto ");
                        setPage("chat");
                        input.current?.focus();
                      }}
                    >
                      <Code2 size={14} />
                      Lavoriamo sul codice
                      <ArrowUpRight size={12} />
                    </button>
                  </div>
                </section>
                <aside className="dashboard-right">
                  <section className="widget">
                    <div className="widget-heading">
                      <span>
                        <Workflow size={15} />
                        IL LAVORO IN CORSO
                      </span>
                      <button
                        className="icon-btn"
                        aria-label="Apri attività"
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
                        <h3>Pronto a fare spazio.</h3>
                        <p>
                          Ricerche, codice e verifiche continuano in background
                          mentre fai altro.
                        </p>
                        <span className="quiet-status">
                          <span className="tiny-dot" />
                          Nessuna attività aperta
                        </span>
                      </div>
                    )}
                  </section>
                  <section className="widget memory-widget">
                    <div className="widget-heading">
                      <span>
                        <Brain size={15} />
                        UNA MEMORIA CHE CONTINUA
                      </span>
                    </div>
                    <h3>Non ripartiamo da zero.</h3>
                    <p>
                      Preferenze, progetti e decisioni rimangono nel tuo Second
                      Brain.
                    </p>
                    <button
                      className="text-btn"
                      onClick={() => setPage("memory")}
                    >
                      Esplora la memoria <ArrowRight size={12} />
                    </button>
                  </section>
                  <div className="local-note">
                    <ShieldCheck size={15} />
                    <p>
                      Il servizio vive sul tuo Mac.
                      <br />
                      Sei tu a scegliere cosa collegare.
                    </p>
                  </div>
                  {approvals.length > 0 && (
                    <button
                      className="attention-mini"
                      onClick={() => setPage("tasks")}
                    >
                      <span className="attention-dot" />
                      {approvals.length} decisioni in attesa
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
                    "Modello da configurare"}
                </span>
                <span>
                  Il Mac deve essere sveglio per eseguire attività e chiamate.
                </span>
              </footer>
            </div>
          )}
          {page === "chat" && (
            <div className="chat-view">
              <div className="chat-heading">
                <div>
                  <span className="eyebrow">
                    UNA CONVERSAZIONE, MOLTE POSSIBILITÀ
                  </span>
                  <h1>
                    {privateMode
                      ? "Una sessione privata."
                      : conversations.find((c) => c.id === conversation)
                          ?.title || "Cosa facciamo insieme?"}
                  </h1>
                </div>
                <button className="btn ghost" onClick={newChat}>
                  <Plus size={14} />
                  Nuova
                </button>
              </div>
              <div className="message-list">
                {!visibleMessages.length && !runningChat.length && (
                  <div className="chat-welcome">
                    <span className="brand-mark">J</span>
                    <h2>Dimmi l’obiettivo.</h2>
                    <p>
                      Posso cercare, ricordare, programmare e usare gli
                      strumenti che hai collegato.
                    </p>
                    {privateMode && (
                      <span className="privacy-label">
                        <LockKeyhole size={13} />I contenuti non vengono
                        conservati.
                      </span>
                    )}
                  </div>
                )}
                {visibleMessages.map((m: Json) => (
                  <article className={"message message-" + m.role} key={m.id}>
                    <div className="message-avatar">
                      {m.role === "assistant" ? "J" : "TU"}
                    </div>
                    <div className="message-body">
                      <span className="message-author">
                        {m.role === "assistant" ? "Jarvis" : "Tu"}
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
                          ? "In attesa del motore"
                          : "Sto lavorando alla richiesta"}
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
                          "Ho preparato una proposta concreta. Verificala prima di proseguire."}
                      </p>
                      {t.state === "waiting_user" && (
                        <button
                          className="text-btn"
                          onClick={() => setPage("tasks")}
                        >
                          Apri decisione <ArrowRight size={13} />
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
            aria-label="Chiudi messaggio"
            onClick={() => setToast(null)}
          >
            <X size={13} />
          </button>
        </div>
      )}
      {showNotifications && (
        <Modal
          title="Le tue notifiche"
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
              <Empty icon={Bell} title="Tutto tranquillo">
                Le notifiche compariranno quando c’è un risultato o una
                decisione utile.
              </Empty>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
}
