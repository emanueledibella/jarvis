import {
  t as tr,
  useI18n,
  uiLocale,
  formatNumber,
  syncInterfaceLanguage,
} from "./i18n";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { randomId } from "./randomId";
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
  Paperclip,
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
  voicePhase,
} from "./components";
import { Tasks, Routines } from "./Activity";
import { Memory, Integrations } from "./Memory";
import Settings from "./Settings";
import CommandCenter, { SystemClock, VoiceSignal } from "./CommandCenter";
import brandIcon from "./assets/jarvis.svg";
import Today from "./Today";
import Organizer from "./Organizer";
import Mail from "./Mail";
import Automations from "./Automations";
import ChatAttachments, { MAX_DOCUMENT_ATTACHMENTS, type DocumentAttachment } from "./ChatAttachments";
import { deleteScreenCapture, type ScreenAttachment } from "./ScreenAttachment";
import Development from "./Development";
import HomeAssistant from "./HomeAssistant";
import AppleHealth, { type HealthAttachment } from "./AppleHealth";
import { iosHealth } from "./appleHealthNative";
import "./assistant.css";
import { remoteClient } from "./remoteClient";
import { companionVoice, useCompanionVoice } from "./companionVoice";

type Page =
  | "home"
  | "today"
  | "organizer"
  | "mail"
  | "automations"
  | "development"
  | "homeAssistant"
  | "appleHealth"
  | "chat"
  | "tasks"
  | "routines"
  | "memory"
  | "integrations"
  | "settings";

export default function App() {
  useI18n();
  const [attachments, setAttachments] = useState<DocumentAttachment[]>([]);
  const [healthAttachment, setHealthAttachment] = useState<HealthAttachment | null>(null);
  const [screenAttachment, setScreenAttachment] = useState<ScreenAttachment | null>(null);
  const [showAttachments, setShowAttachments] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [, setSessionRevision] = useState(-1);
  const attachmentSession = useRef(randomId());
  const attachmentDraft = useRef(0);
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;
  const showAppleHealth = iosHealth.supported();
  const [authenticated, setAuthenticated] = useState(hasToken()),
    [entryToken, setEntryToken] = useState(""),
    [page, setPage] = useState<Page>("home"),
    [settingsSection, setSettingsSection] = useState("interface"),
    [serviceStatus, setStatus] = useState<Json>({
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
    [serviceAudio, setAudio] = useState({ input: 0, output: 0 }),
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
  const companion = useCompanionVoice();
  const audio = remoteClient.enabled ? { input: companion.input, output: companion.output } : serviceAudio;
  const status = remoteClient.enabled ? {
    ...serviceStatus,
    platform: { ...serviceStatus.platform, native_voice: companion.supported },
    native: { ...serviceStatus.native, connected: companion.supported, muted: companion.muted, voice_state: companion.state },
  } : serviceStatus;
  const refreshStatus = useCallback(() => {
    const session = remoteClient.sessionId, revision = privacyRevision.current;
    return api("/status").then(value => {
      if (session === remoteClient.sessionId && revision === privacyRevision.current) setStatus(value);
    });
  }, []);
  const refresh = useCallback(() => {
    if (!hasToken()) return;
    Promise.allSettled([
      refreshStatus(),
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
  }, [refreshStatus]);
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
  function resetAttachments() {
    attachmentDraft.current++;
    setAttachments([]);
    setHealthAttachment(null);
    setScreenAttachment(null);
    setShowAttachments(false);
  }
  function applyPreference(value: Json) {
    if (remoteClient.enabled && value.client_session_id && value.client_session_id !== remoteClient.sessionId) return;
    if (value.revision < privacyRevision.current) return;
    const changed =
      privateRef.current !== value.private || scopeRef.current !== value.scope;
    const revisionChanged = value.revision !== privacyRevision.current;
    privacyRevision.current = value.revision;
    setSessionRevision(value.revision);
    privateRef.current = value.private;
    scopeRef.current = value.scope;
    setPrivateMode(value.private);
    setScope(value.scope);
    setPrivacyReady(true);
    if (revisionChanged) {
      setScreenAttachment(null);
      setStatus(current => ({ ...current, screen_capture: undefined }));
      void refreshStatus().catch(() => {});
    }
    if (changed) {
      if (remoteClient.enabled) { remoteClient.conversationId = null; window.dispatchEvent(new Event("jarvis-session-changed")); }
      resetAttachments();
      attachmentSession.current = randomId();
      setConversation(null);
      setMessages([]);
    }
  }
  function syncPreference() {
    api("/voice/session")
      .then(applyPreference)
      .catch(() => setPrivacyReady(false));
  }
  useEffect(() => {
    const openTasks = () => { setPage("tasks"); };
    const shared = (event: Event) => {
      const source = (event as CustomEvent).detail;
      if (typeof source?.id !== "string" || typeof source.name !== "string") return;
      if (source.sessionId !== remoteClient.sessionId || source.revision !== privacyRevision.current ||
          attachmentsRef.current.length >= MAX_DOCUMENT_ATTACHMENTS) {
        event.preventDefault();
        return;
      }
      setAttachments(items => {
        if (items.length >= MAX_DOCUMENT_ATTACHMENTS || items.some(item => item.id === source.id)) return items;
        return [...items, { id: source.id, name: source.name }];
      });
      setPage("chat");
    };
    const voiceTask = (event: Event) => {
      const task = (event as CustomEvent).detail;
      if (!task?.conversation_id) return;
      if (task.conversation_id !== currentConversation.current) resetAttachments();
      setConversation(task.conversation_id);
      refresh();
    };
    window.addEventListener("jarvis-session-changed", syncPreference);
    window.addEventListener("jarvis-remote-open-tasks", openTasks);
    window.addEventListener("jarvis-shared-source", shared);
    window.addEventListener("jarvis-companion-task", voiceTask);
    return () => { window.removeEventListener("jarvis-session-changed", syncPreference); window.removeEventListener("jarvis-remote-open-tasks", openTasks); window.removeEventListener("jarvis-shared-source", shared); window.removeEventListener("jarvis-companion-task", voiceTask); };
  }, []);
  async function preference(privateValue: boolean, scopeValue: string) {
    setPrivacyReady(false);
    if (remoteClient.enabled) await companionVoice.stop(false);
    try {
      applyPreference(
        await post("/voice/session", {
          private: privateValue,
          scope: scopeValue,
        }),
      );
      if (remoteClient.enabled) companionVoice.sessionChanged();
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
    let settingsTimer: ReturnType<typeof setTimeout> | undefined;
    eventStream((event) => {
      if (event.type === "connection") {
        setConnection(event.data.state);
        if (event.data.state === "connected") {
          syncPreference();
          syncInterfaceLanguage().catch(() => {});
        }
      } else if (event.type === "settings.updated") {
        // Replayed events all invalidate the same current settings snapshot.
        if (settingsTimer !== undefined) return;
        settingsTimer = setTimeout(() => {
          settingsTimer = undefined;
          syncInterfaceLanguage().catch(() => {});
          if (remoteClient.enabled) {
            void companionVoice.reload().catch((error) => {
              if (!controller.signal.aborted) notify(error.message, true);
            });
          }
          refresh();
        }, 200);
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
      clearTimeout(settingsTimer);
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
  const voiceState = !status.native?.connected
    ? "unavailable"
    : status.emergency_stop
      ? "muted"
      : status.native.voice_state || "unavailable";
  const portableText = status.platform?.native_voice === false;
  const { Icon: VoiceIcon, tone: voiceTone, label: voiceLabel } =
    voicePhase(voiceState);
  const voiceLevel =
    voiceState === "speaking"
      ? audio.output
      : !status.native?.muted &&
          ["armed", "listening", "followup"].includes(voiceState)
        ? audio.input
        : 0;
  const unread = notifications.filter((n) => !n.read).length;
  useEffect(() => { if (status.emergency_stop) window.dispatchEvent(new Event("jarvis-emergency-stop")); }, [status.emergency_stop]);
  useEffect(() => {
    if (!screenAttachment) return;
    const timer = setTimeout(() => {
      setScreenAttachment(current => current?.id === screenAttachment.id ? null : current);
      notify("The window capture expired. Choose it again.");
    }, Math.max(0, screenAttachment.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [screenAttachment, notify]);
  async function send(value = text) {
    if (!value.trim() || sending) return;
    if (!privacyReady) {
      notify("Wait for privacy settings to load.", true);
      return;
    }
    const attachedIds = page === "chat" ? attachments.map(item => item.id) : [];
    const healthSource = page === "chat" ? healthAttachment : null;
    const screenSource = page === "chat" ? screenAttachment : null;
    if (screenSource && screenSource.expiresAt <= Date.now()) {
      setScreenAttachment(null);
      notify("The window capture expired. Choose it again.", true);
      return;
    }
    const draft = attachmentDraft.current;
    const session = remoteClient.sessionId;
    const revision = privacyRevision.current;
    const isCurrentDraft = () => draft === attachmentDraft.current &&
      session === remoteClient.sessionId && revision === privacyRevision.current;
    setSending(true);
    try {
      let requestText = value;
      if (healthSource) {
        const summary = await api("/apple-health?scope=personal");
        if (!isCurrentDraft()) return;
        if (summary.id !== healthSource.id) {
          throw new Error("The Apple Health summary changed. Attach the current summary.");
        }
        const cloud = !status.profile || status.profile === "cloud" ||
          (status.profile === "hybrid" && status.models?.cloud_configured);
        if (cloud && !summary.allow_cloud) {
          throw new Error("Enable cloud access for health summaries in Add attachments before sending.");
        }
        requestText += "\n\n" + tr("Attached Apple Health summary from {start} to {end}, source {id}. Verify the source ID before using its readings.", {
          start: summary.first_date,
          end: summary.last_date,
          id: summary.id,
        });
      }
      const signature = JSON.stringify([
        requestText,
        conversation,
        scope,
        privateMode,
        external,
        attachedIds,
        screenSource?.id,
        session,
        draft,
      ]);
      if (submission.current?.signature !== signature)
        submission.current = { signature, id: randomId() };
      const task = await post("/chat", {
        text: requestText,
        conversation_id: conversation,
        scope,
        private: privateMode,
        external_authorized: external,
        privacy_revision: revision,
        request_id: submission.current.id,
        attachment_ids: attachedIds,
        attachment_session: attachmentSession.current,
        ...(screenSource ? { screen_capture_id: screenSource.id } : {}),
      });
      submission.current = null;
      if (!isCurrentDraft()) {
        refresh();
        return;
      }
      if (remoteClient.enabled) remoteClient.bindConversation(task.conversation_id);
      setConversation(task.conversation_id);
      if (screenSource) setScreenAttachment(current => current?.id === screenSource.id ? null : current);
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
    if (remoteClient.enabled) {
      try { await companionVoice.control(action); } catch (error: any) { notify(error.message, true); }
      return;
    }
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
  async function newChat() {
    resetAttachments();
    if (remoteClient.enabled) {
      setPrivacyReady(false);
      await remoteClient.selectConversation();
      privacyRevision.current = -1;
      if (!(await preference(privateMode, scope))) return;
    }
    setConversation(null);
    setMessages([]);
    setText("");
    setPage("chat");
    input.current?.focus();
  }
  async function chooseConversation(c: Json) {
    if (c.id !== currentConversation.current) resetAttachments();
    if (remoteClient.enabled) {
      setPrivacyReady(false);
      await remoteClient.selectConversation(c.id);
      privacyRevision.current = -1;
    }
    if (!(await preference(false, c.scope))) return;
    setConversation(c.id);
    setPage("chat");
  }
  const pickerDraft = attachmentDraft.current;
  const pickerSession = remoteClient.sessionId;
  const pickerRevision = privacyRevision.current;
  const pickerIsCurrent = () => pickerDraft === attachmentDraft.current &&
    pickerSession === remoteClient.sessionId && pickerRevision === privacyRevision.current;
  const screenContext = { scope, privacy_revision: pickerRevision, session_id: attachmentSession.current };
  const windowAttachment = screenAttachment ? { id: screenAttachment.id, name: tr("Selected window") } : null;
  const composer = (
    <div className="composer-wrap">
      <div className="composer">
        {page === "chat" && (attachments.length > 0 || healthAttachment || windowAttachment) && (
          <ul className="chat-attachments" aria-label={tr("Attached sources")}>
            {[...attachments, ...(healthAttachment ? [healthAttachment] : []), ...(windowAttachment ? [windowAttachment] : [])].map(item => (
              <li key={item.id}>
                <span title={item.name}>{item.name}</span>
                <button className="icon-btn" disabled={sending} aria-label={tr("Remove attachment {name}", { name: item.name })} onClick={() => {
                  if (item.id === windowAttachment?.id) {
                    setScreenAttachment(null);
                    void deleteScreenCapture(item.id, screenContext).catch(error => {
                      if (pickerIsCurrent()) notify(error.message, true);
                    });
                  } else if (item.id === healthAttachment?.id) setHealthAttachment(null);
                  else setAttachments(current => current.filter(attachment => attachment.id !== item.id));
                }}><X size={14} /></button>
              </li>
            ))}
          </ul>
        )}
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
            {page === "chat" && <button
              className="icon-btn"
              aria-label={tr("Add attachments")}
              title={tr("Add attachments")}
              disabled={!privacyReady || sending}
              onClick={() => { setShowAttachments(true); void refreshStatus().catch(() => {}); }}
            ><Paperclip size={17} /></button>}
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
              disabled={!privacyReady || (portableText && !remoteClient.enabled)}
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
              { id: "today", label: tr("Today"), icon: Sun },
              { id: "organizer", label: tr("Activities"), icon: Check },
              { id: "mail", label: tr("Mail"), icon: MessageSquare },
              { id: "appleHealth", label: tr("Apple Health"), icon: Sun },
              { id: "development", label: tr("Jira and GitHub"), icon: Workflow },
              { id: "homeAssistant", label: "Home Assistant", icon: Sun },
              { id: "chat", label: tr("Conversation"), icon: MessageSquare },
              { id: "tasks", label: tr("Tasks"), icon: Workflow },
              { id: "routines", label: tr("Routines"), icon: CalendarClock },
              { id: "automations", label: tr("Automations"), icon: Bell },
              { id: "memory", label: tr("Memory"), icon: Brain },
              { id: "integrations", label: tr("Connections"), icon: Link2 },
            ] as { id: Page; label: string; icon: any }[]
          ).filter(item => item.id !== "appleHealth" || showAppleHealth).map((item) => (
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
            data-voice-tone={voiceTone}
            onClick={() => openSettings("voice")}
            aria-label={tr("Open voice settings")}
            title={tr(voiceLabel)}
          >
            <span className="eyebrow">
              {tr("VOICE CHANNEL")}
              <VoiceIcon
                className="sidebar-voice-icon"
                size={15}
                aria-hidden="true"
              />
            </span>
            <VoiceSignal level={voiceLevel} />
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
                {remoteClient.enabled ? tr("Remote core") : portableText ? tr("Local computer") : tr("Personal Mac")}
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
                  today: tr("Today"),
                  organizer: tr("Activities"),
                  mail: tr("Mail"),
                  appleHealth: tr("Apple Health"),
                  development: tr("Jira and GitHub"),
                  homeAssistant: "Home Assistant",
                  automations: tr("Automations"),
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
              onClick={() => {
                window.dispatchEvent(new Event("jarvis-emergency-stop"));
                void post("/control/emergency", { stopped: true })
                  .then(() => {
                    refresh();
                    notify("Emergency stop is active.");
                  })
                  .catch((e) => notify(e.message, true));
              }}
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
                ? (remoteClient.enabled ? tr("Remote core") : tr("Local service"))
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
                portableText && !remoteClient.enabled
                  ? newChat()
                  : native(status.native?.muted ? "unmute" : "mute")
              }
              aria-label={
                portableText && !remoteClient.enabled
                  ? tr("Open text conversation")
                  : status.native?.muted
                    ? tr("Unmute microphone")
                    : tr("Mute microphone")
              }
            >
              {portableText && !remoteClient.enabled ? (
                <MessageSquare size={14} />
              ) : status.native?.muted ? (
                <MicOff size={14} />
              ) : (
                <Mic size={14} />
              )}
              <span>
                {portableText && !remoteClient.enabled
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
          {!["home", "chat", "tasks", "routines", "memory", "integrations", "settings"].includes(page) && <div className="assistant-scope-bar">
            <label>{tr("Conversation scope")} <select value={scope} disabled={!privacyReady} onChange={(e) => preference(privateMode, e.target.value)}><option value="personal">{tr("Personal")}</option><option value="work">{tr("Work")}</option></select></label>
            <button className="btn" disabled={!privacyReady} aria-pressed={privateMode} onClick={() => preference(!privateMode, scope)}><LockKeyhole size={13} />{tr(privateMode ? "Private" : "Private session")}</button>
          </div>}
          {page === "home" && (
            <CommandCenter
              remoteCore={remoteClient.enabled}
              status={status}
              dashboard={dashboard}
              tasks={tasks}
              schedules={schedules}
              approvals={approvals}
              connection={connection}
              voiceState={voiceState}
              voiceLevel={voiceLevel}
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
          {page === "today" && <Today key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "organizer" && <Organizer key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "mail" && <Mail key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "automations" && <Automations key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "appleHealth" && showAppleHealth && <AppleHealth key={scope + ":" + privacyRevision.current + ":" + attachmentSession.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "development" && <Development key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
          {page === "homeAssistant" && <HomeAssistant key={scope + ":" + privacyRevision.current} scope={scope} privateMode={privateMode} privacyRevision={privacyRevision.current} notify={notify} onAsk={(prompt) => { void send(prompt); }} />}
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
            <Memory selectedScope={remoteClient.enabled ? scope : undefined} onScopeChange={remoteClient.enabled ? (value) => preference(privateMode, value) : undefined} notify={notify} openSettings={openSettings} />
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
      {remoteClient.enabled && <nav className="remote-mobile-nav" aria-label={tr("Main navigation")}>
        {([["home", "Overview", LayoutDashboard], ["today", "Today", CalendarClock], ["chat", "Chat", MessageSquare], ["tasks", "Tasks", Check]] as const).map(([id, label, Icon]) => <button key={id} className={page === id ? "active" : ""} onClick={() => setPage(id)}><Icon size={19} /><span>{tr(label)}</span></button>)}
        <button aria-expanded={mobileMenu} onClick={() => setMobileMenu(true)}><Workflow size={19} /><span>{tr("More")}</span></button>
      </nav>}
      {mobileMenu && <Modal title={tr("More sections")} onClose={() => setMobileMenu(false)}><div className="modal-body remote-mobile-sections">
        {([["appleHealth", "Apple Health"], ["organizer", "Activities"], ["mail", "Mail"], ["development", "Jira and GitHub"], ["homeAssistant", "Home Assistant"], ["routines", "Routines"], ["automations", "Automations"], ["memory", "Memory"], ["integrations", "Connections"], ["settings", "Settings"]] as const).filter(([id]) => id !== "appleHealth" || showAppleHealth).map(([id, label]) => <button className="btn" key={id} onClick={() => { setPage(id); setMobileMenu(false); }}>{tr(label)}</button>)}
      </div></Modal>}
      {page === "chat" && showAttachments && privacyReady && <ChatAttachments
        key={`${pickerDraft}:${pickerSession}:${pickerRevision}`}
        scope={scope}
        privateMode={privateMode}
        privacyRevision={pickerRevision}
        sessionId={attachmentSession.current}
        selected={attachments}
        healthAttached={!!healthAttachment}
        screenAttached={!!screenAttachment}
        screenCapture={serviceStatus.screen_capture ?? "unavailable"}
        isCurrent={pickerIsCurrent}
        onSelect={update => { if (pickerIsCurrent()) setAttachments(update); }}
        onAttachHealth={attachment => { if (pickerIsCurrent()) setHealthAttachment(attachment); }}
        onAttachScreen={attachment => {
          if (!pickerIsCurrent()) return false;
          if (screenAttachment) void deleteScreenCapture(screenAttachment.id, screenContext).catch(() => {});
          setScreenAttachment(attachment);
          setShowAttachments(false);
          setTimeout(() => input.current?.focus(), 0);
          return true;
        }}
        onClose={() => setShowAttachments(false)}
        notify={notify}
      />}
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
