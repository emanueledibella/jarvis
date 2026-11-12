import { Capacitor } from "@capacitor/core";
import { useSyncExternalStore } from "react";
import { api, post } from "./api";
import {
  nativePlugin,
  remoteClient,
  type NativeLiveBridge,
  type NativeLivePlayback,
} from "./remoteClient";
import { randomId } from "./randomId";
import {
  afterWake,
  canContinueVoice,
  PCMResampler,
  voicePreferenceKey,
} from "./companionVoicePolicy";

type Values = Record<string, any>;
type VoiceGuard = { session: string; revision: number };
// Keep the provider timeline moving for an output-only Live session. Each
// frame is 100 ms of PCM16 mono at 24 kHz, with no microphone attached.
const liveSilence = JSON.stringify({ type: "audio", audio: "A".repeat(6400) });
type LocalTurn = {
  lastActivity: number;
  waitMs: number;
  segments: Map<string, string>;
  sessionId: string;
  wakeSegment?: string;
  wakeFrame?: number;
  wakeFinal?: boolean;
  finalWaitUntil?: number;
};
type Snapshot = {
  state: string;
  enabled: boolean;
  muted: boolean;
  supported: boolean;
  error: string;
  transcript: string;
  microphone: string;
  input: number;
  output: number;
};
const initial: Snapshot = {
  state: "muted",
  enabled: false,
  muted: true,
  supported: false,
  error: "",
  transcript: "",
  microphone: "",
  input: 0,
  output: 0,
};

export class CompanionVoice {
  private snapshot = initial;
  private subscribers = new Set<() => void>();
  private settings: Values = {};
  private generation = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private poll?: ReturnType<typeof setTimeout>;
  private audioPoll?: ReturnType<typeof setTimeout>;
  private stopEvents?: () => void;
  private socket?: WebSocket;
  private stream?: MediaStream;
  private context?: AudioContext;
  private capture?: AudioWorkletNode;
  private source?: MediaStreamAudioSourceNode;
  private cue?: OscillatorNode;
  private handoffs = new WeakSet<WebSocket>();
  private nodes = new Set<AudioBufferSourceNode>();
  private outputAt = 0;
  private playbackID = 0;
  private nativePlaybackFinished?: (id: number) => void;
  private turn?: LocalTurn;
  private recognizerSpeaking = false;
  private inputFloor = 0;
  private suspended = false;
  private key = "";
  private operation: Promise<void> = Promise.resolve();
  subscribe = (listener: () => void) => {
    this.subscribers.add(listener);
    return () => {
      this.subscribers.delete(listener);
    };
  };
  getSnapshot = () => this.snapshot;
  private update(changes: Partial<Snapshot>) {
    this.snapshot = { ...this.snapshot, ...changes };
    for (const listener of this.subscribers) listener();
  }
  private get native() {
    return Capacitor.isNativePlatform() ? nativePlugin : window.jarvisCompanion;
  }
  private get mobile() {
    return Capacitor.isNativePlatform();
  }
  private get liveBridge(): NativeLiveBridge | undefined {
    if (this.settings.desktop_voice_provider !== "openai_live") return;
    if (Capacitor.getPlatform() === "ios") return nativePlugin;
    const bridge = window.jarvisCompanion;
    if (
      bridge?.voiceFinalizeRecognition &&
      bridge.voiceBeginLive &&
      bridge.voiceReadLive &&
      bridge.voicePlayLive
    ) {
      return {
        voiceFinalizeRecognition: bridge.voiceFinalizeRecognition,
        voiceBeginLive: bridge.voiceBeginLive,
        voiceReadLive: bridge.voiceReadLive,
        voicePlayLive: bridge.voicePlayLive,
      };
    }
  }
  private get livePlayback(): NativeLivePlayback | undefined {
    if (Capacitor.getPlatform() === "ios") return nativePlugin;
    const bridge = window.jarvisCompanion;
    if (bridge?.voiceStartLivePlayback && bridge.voicePlayLive) {
      return {
        voiceStartLivePlayback: bridge.voiceStartLivePlayback,
        voicePlayLive: bridge.voicePlayLive,
      };
    }
  }
  private async startRecognition() {
    await this.native?.voiceStart?.({
      language: this.settings.language || "it-IT",
      phrase: this.settings.wake_phrase || "Jarvis",
      microphone: this.snapshot.microphone,
      ...(this.liveBridge ? { bufferLive: true } : {}),
    });
  }
  private clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
  }
  private serialize(action: () => Promise<void>) {
    this.operation = this.operation.then(action, action);
    return this.operation;
  }

  async attach() {
    const current = ++this.generation;
    this.suspended = false;
    this.key = voicePreferenceKey(
      remoteClient.credentials?.server_url || location.origin,
      remoteClient.credentials?.device_id || "browser",
    );
    let saved: Values = {};
    try {
      saved = JSON.parse(localStorage.getItem(this.key) || "{}");
    } catch {
      /* An unavailable preference never enables a microphone. */
    }
    this.update({
      ...initial,
      supported:
        this.mobile ||
        (!!window.jarvisCompanion?.voiceStart &&
          remoteClient.platform === "macos"),
      enabled: saved.enabled === true,
      muted: saved.enabled !== true,
      microphone: typeof saved.microphone === "string" ? saved.microphone : "",
    });
    if (this.mobile) {
      const listener = await nativePlugin.addListener("voice", (value) =>
        this.receive(value),
      );
      if (current !== this.generation) {
        await listener.remove();
        return;
      }
      this.stopEvents = () => {
        void listener.remove();
      };
    } else
      this.stopEvents = window.jarvisCompanion?.onVoice?.((value) =>
        this.receive(value),
      );
    await this.reload(false);
    if (current !== this.generation) return;
    if (this.snapshot.enabled && this.snapshot.supported)
      await this.arm().catch((error) => this.fail(error));
  }

  detach() {
    this.stopEvents?.();
    this.stopEvents = undefined;
    this.suspended = true;
    void this.stop(false);
    const context = this.context;
    this.context = undefined;
    if (context?.close) void context.close().catch(() => {});
  }

  async reload(rearm = true) {
    const current = this.generation;
    const result = await api("/settings");
    if (current !== this.generation) return;
    const previous = JSON.stringify(this.settings);
    this.settings = result.values;
    if (this.settings.voice_enabled === false) {
      await this.stop(false);
      return;
    }
    if (
      rearm &&
      previous !== JSON.stringify(this.settings) &&
      this.snapshot.enabled &&
      this.snapshot.supported
    )
      await this.arm();
  }

  private persist() {
    try {
      localStorage.setItem(
        this.key,
        JSON.stringify({
          enabled: this.snapshot.enabled,
          microphone: this.snapshot.microphone,
        }),
      );
    } catch {
      /* Voice still works for this launch. */
    }
  }

  async control(action: string) {
    if (action === "autostart_enable" || action === "autostart_disable") {
      if (!window.jarvisCompanion?.setLaunchAtLogin)
        throw new Error(
          "Launch at login is available on the desktop companion.",
        );
      return window.jarvisCompanion.setLaunchAtLogin(
        action === "autostart_enable",
      );
    }
    if (action === "mute") {
      this.update({ enabled: false });
      this.persist();
      await this.stop();
      await window.jarvisCompanion?.setVoiceEnabled?.({
        enabled: false,
        allowLocked: false,
      });
      return {};
    }
    if (action === "stop") {
      await this.stop(false);
      if (this.snapshot.enabled) await this.arm();
      return {};
    }
    if (!["enable", "unmute", "listen"].includes(action))
      throw new Error("This action requires an authorized desktop executor.");
    if (!this.snapshot.supported) {
      window.dispatchEvent(new Event("jarvis-companion-record"));
      return {};
    }
    const current = ++this.generation;
    this.suspended = false;
    // Only the Web Audio path needs to unlock playback from the user's click.
    if (!this.mobile || action === "listen") {
      this.context ??= new AudioContext();
      void this.context.resume().catch(() => {});
    }
    const status = await api("/status");
    if (current !== this.generation) return {};
    if (status.emergency_stop) {
      await this.stop();
      throw new Error("Emergency stop is active.");
    }
    this.settings = (await api("/settings")).values;
    if (current !== this.generation) return {};
    if (this.settings.voice_enabled === false) {
      await this.stop();
      throw new Error("Voice is disabled. Enable it in Voice settings.");
    }
    this.update({ enabled: true, muted: false, error: "" });
    this.persist();
    await window.jarvisCompanion?.setVoiceEnabled?.({
      enabled: true,
      allowLocked: this.settings.voice_on_lock_screen === true,
    });
    try {
      if (action === "listen") await this.activate("");
      else await this.arm();
    } catch (error) {
      this.update({ enabled: false });
      this.persist();
      await this.stop();
      throw error;
    }
    return {};
  }

  async selectMicrophone(uid: string) {
    this.update({ microphone: uid });
    this.persist();
    if (this.snapshot.enabled) await this.arm();
  }
  async inputs() {
    return (
      this.native?.voiceInputs?.() || { state: "unsupported", devices: [] }
    );
  }

  private stopCapture() {
    if (this.audioPoll) clearTimeout(this.audioPoll);
    this.audioPoll = undefined;
    this.nativePlaybackFinished = undefined;
    this.cue?.stop();
    this.cue?.disconnect();
    this.cue = undefined;
    if (this.capture) {
      this.capture.port.onmessage = null;
      this.capture.disconnect();
      this.capture = undefined;
    }
    this.source?.disconnect();
    this.source = undefined;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = undefined;
    if (this.socket) {
      const socket = this.socket;
      this.socket = undefined;
      socket.onclose = null;
      socket.onerror = null;
      if (socket.readyState === WebSocket.OPEN && !this.handoffs.has(socket))
        socket.send(JSON.stringify({ type: "close" }));
      socket.close();
    }
    for (const node of this.nodes) node.stop();
    this.nodes.clear();
    this.outputAt = 0;
  }

  async stop(muted = true, state = "muted", transcript = "") {
    const current = ++this.generation;
    this.clearTimer();
    if (this.poll) clearTimeout(this.poll);
    this.poll = undefined;
    this.stopCapture();
    this.turn = undefined;
    this.recognizerSpeaking = false;
    this.inputFloor = 0;
    this.update({ state, muted, transcript, input: 0, output: 0 });
    await this.serialize(async () => {
      await this.native?.voiceStop?.();
    });
    return current;
  }

  private async arm(followup = false) {
    const current = await this.stop(false);
    if (
      current !== this.generation ||
      !this.snapshot.enabled ||
      this.suspended ||
      this.settings.voice_enabled === false
    )
      return;
    const status = await api("/status");
    if (current !== this.generation || this.suspended) return;
    if (status.emergency_stop) {
      this.update({ state: "muted", muted: true });
      return;
    }
    await window.jarvisCompanion?.setVoiceEnabled?.({
      enabled: true,
      allowLocked: this.settings.voice_on_lock_screen === true,
    });
    if (current !== this.generation || this.suspended) return;
    this.update({
      state: followup
        ? "followup"
        : this.settings.wake_enabled
          ? "armed"
          : "muted",
      muted: false,
      error: "",
    });
    if (!followup && !this.settings.wake_enabled) return;
    if (followup) this.beginLocalTurn(this.settings.followup_seconds * 1000);
    await this.serialize(async () => {
      if (current !== this.generation) return;
      await this.startRecognition();
    });
  }

  private beginLocalTurn(waitMs: number, wakeSegment?: string) {
    const turn: LocalTurn = {
      lastActivity: performance.now(),
      waitMs,
      wakeSegment,
      segments: new Map(),
      sessionId: remoteClient.sessionId,
    };
    this.turn = turn;
    this.scheduleTurnEnd(turn);
    return turn;
  }

  private scheduleTurnEnd(turn: LocalTurn) {
    this.clearTimer();
    // Android reports speech onset and completion independently of text.
    if (this.recognizerSpeaking) return;
    const quiet = this.snapshot.transcript
      ? Math.max(300, this.settings.end_of_turn_ms || 900)
      : turn.waitMs;
    const waitUntil = () =>
      Math.max(
        turn.lastActivity + quiet,
        turn.wakeFinal || turn.wakeFrame !== undefined
          ? 0
          : (turn.finalWaitUntil ?? 0),
      );
    const remaining = waitUntil() - performance.now();
    this.timer = setTimeout(
      () => {
        if (this.turn !== turn) return;
        if (performance.now() < waitUntil()) {
          this.scheduleTurnEnd(turn);
          return;
        }
        const bridge = this.liveBridge;
        if (
          bridge &&
          this.snapshot.transcript &&
          turn.wakeSegment &&
          turn.wakeFrame === undefined &&
          !turn.wakeFinal &&
          turn.finalWaitUntil === undefined
        ) {
          // Apple may provide the wake timestamp only with its final hypothesis.
          // Ask for it after silence, leaving capture active throughout.
          turn.finalWaitUntil = performance.now() + 1000;
          void bridge.voiceFinalizeRecognition().catch(() => {});
          this.scheduleTurnEnd(turn);
          return;
        }
        this.turn = undefined;
        const current = this.generation;
        void this.completeTurn(turn).catch((error) => {
          if (current === this.generation) this.fail(error);
        });
      },
      Math.max(1, remaining),
    );
  }

  private async completeTurn(turn: LocalTurn) {
    if (turn.sessionId !== remoteClient.sessionId) return;
    const text = this.snapshot.transcript;
    if (!text) return this.arm();
    // Apple can retain the entire request on its original microphone. If the
    // recognizer didn't provide a usable wake timestamp, the local transcript
    // is already complete. Android uses that same text path for hands-free turns.
    const bridge = this.liveBridge;
    if (bridge && turn.wakeFrame !== undefined) {
      const current = this.generation;
      const { started } = await bridge.voiceBeginLive({
        frame: turn.wakeFrame,
      });
      if (
        current !== this.generation ||
        this.suspended ||
        turn.sessionId !== remoteClient.sessionId
      )
        return;
      if (started) {
        this.update({ state: "processing" });
        await this.live("", undefined, undefined, { text, bridge });
        return;
      }
    }
    await this.submit(text);
  }

  private receive(value: Values) {
    if (value.type === "suspended") {
      this.suspended = true;
      void this.stop(false);
      return;
    }
    if (value.type === "resumed") {
      if (!this.suspended) return;
      this.suspended = false;
      if (this.snapshot.enabled)
        void this.arm().catch((error) => this.fail(error));
      return;
    }
    if (!this.snapshot.enabled || this.suspended) return;
    if (value.type === "live_playback_finished") {
      this.nativePlaybackFinished?.(value.id);
      return;
    }
    if (value.type === "level" && typeof value.input === "number") {
      this.update({ input: value.input });
      const audible = value.input >= Math.max(0.045, this.inputFloor * 2.5);
      if (this.turn && audible) this.turn.lastActivity = performance.now();
      else
        this.inputFloor =
          this.inputFloor * 0.96 + Math.min(0.4, value.input) * 0.04;
      return;
    }
    if (value.type === "speech") {
      this.recognizerSpeaking = value.active === true;
      if (this.turn) {
        this.turn.lastActivity = performance.now();
        this.scheduleTurnEnd(this.turn);
      }
      return;
    }
    if (value.type === "error") {
      this.fail(new Error(value.message));
      return;
    }
    if (
      value.type === "recovering" &&
      ["armed", "recovering"].includes(this.snapshot.state)
    ) {
      this.update({ state: "recovering" });
      return;
    }
    if (value.type === "ready" && this.snapshot.state === "recovering") {
      this.update({ state: "armed" });
      return;
    }
    if (
      value.type !== "transcript" ||
      typeof value.text !== "string" ||
      typeof value.segment !== "string"
    )
      return;
    const state = this.snapshot.state;
    let turn = this.turn;
    const phrase = this.settings.wake_phrase || "Jarvis";
    if (state === "armed" || state === "recovering") {
      const wake = afterWake(value.text, phrase);
      if (wake === null) return;
      this.update({ state: "listening", transcript: "" });
      // A cue played into the same microphone can become part of the request.
      if (!this.mobile && !wake) this.readyCue();
      turn = this.beginLocalTurn(
        (this.settings.listen_timeout_seconds || 10) * 1000,
        value.segment,
      );
    }
    if (!turn) return;
    const isWake = value.segment === turn.wakeSegment;
    const text = isWake ? afterWake(value.text, phrase) : value.text.trim();
    if (text === null) return;
    if (
      isWake &&
      Number.isSafeInteger(value.wake_frame) &&
      value.wake_frame > 0
    )
      turn.wakeFrame = value.wake_frame;
    if (isWake && value.final) turn.wakeFinal = true;
    if (text) turn.segments.set(value.segment, text);
    else if (value.final) turn.segments.delete(value.segment);
    const transcript = [...turn.segments.values()].join(" ").slice(0, 20000);
    if (transcript === this.snapshot.transcript) {
      if (turn.finalWaitUntil !== undefined && isWake && value.final)
        this.scheduleTurnEnd(turn);
      return;
    }
    this.update({ state: "listening", transcript });
    turn.lastActivity = performance.now();
    this.scheduleTurnEnd(turn);
  }

  private async activate(prefix: string) {
    const current = await this.stop(false, "listening", prefix);
    if (current !== this.generation || this.suspended) return;
    if (this.settings.desktop_voice_provider === "openai_live") {
      await this.live(prefix);
      return;
    }
    this.beginLocalTurn((this.settings.listen_timeout_seconds || 10) * 1000);
    await this.serialize(async () => {
      if (current !== this.generation) return;
      await this.startRecognition();
    });
  }

  private async submit(text: string) {
    const stopped = this.stop(false, "processing", text);
    const current = this.generation;
    try {
      await stopped;
      if (current !== this.generation || this.suspended) return;
      await this.dispatchTurn(text, current);
    } catch (error) {
      if (current === this.generation) this.fail(error);
    }
  }

  private async dispatchTurn(text: string, current: number) {
    const session = await api("/voice/session");
    if (current !== this.generation) return;
    const guard = {
      session: remoteClient.sessionId,
      revision: session.revision,
    };
    const task = await post("/chat", {
      text,
      conversation_id: remoteClient.conversationId,
      scope: session.scope,
      private: session.private,
      privacy_revision: session.revision,
      channel: "voice",
      request_id: randomId(),
    });
    if (current !== this.generation) return;
    remoteClient.bindConversation(task.conversation_id);
    window.dispatchEvent(
      new CustomEvent("jarvis-companion-task", { detail: task }),
    );
    let announced = false;
    let finishReadback: ((answer?: string) => boolean) | undefined;
    const read = async () => {
      if (current !== this.generation) return;
      try {
        const preference = await api("/voice/session");
        if (current !== this.generation) return;
        if (
          !canContinueVoice(guard, remoteClient.sessionId, preference.revision)
        ) {
          await this.stop(false);
          return;
        }
        const { task: result, events } = await api(
          "/tasks/" + task.id + "/detail",
        );
        if (
          current !== this.generation ||
          guard.session !== remoteClient.sessionId
        )
          return;
        if (["queued", "running"].includes(result.state)) {
          const update = announced
            ? undefined
            : events?.find((event: Values) => event.type === "task.progress")
                ?.data?.text;
          if (typeof update === "string" && update) {
            announced = true;
            try {
              if (this.settings.desktop_voice_provider === "openai_live")
                finishReadback = await this.speakWithLive(
                  update,
                  current,
                  guard,
                  true,
                );
              else await this.speakNative(update);
            } catch {
              // Progress audio is optional; still retrieve the actual result.
            }
            if (current !== this.generation) return;
            if (!finishReadback) this.update({ state: "processing" });
            return void read();
          }
          this.poll = setTimeout(() => void read(), 600);
          return;
        }
        const answer =
          result.state === "succeeded" && result.result
            ? String(result.result)
            : undefined;
        if (finishReadback?.(answer)) return;
        if (answer) await this.speak(answer, current, guard);
        else await this.arm();
      } catch (error) {
        if (current === this.generation) this.fail(error);
      }
    };
    await read();
  }

  private async speak(text: string, current: number, guard: VoiceGuard) {
    if (this.settings.desktop_voice_provider === "openai_live") {
      await this.speakWithLive(text, current, guard);
      return;
    }
    await this.speakNative(text);
    if (current === this.generation)
      await this.arm(Number(this.settings.followup_seconds) > 0);
  }

  private async speakNative(text: string) {
    this.update({ state: "speaking" });
    const language =
      this.settings.response_language === "auto"
        ? this.settings.language
        : this.settings.response_language;
    await this.native?.voiceSpeak?.({
      text: text.slice(0, 4000),
      language: language || "it-IT",
      voice: this.settings.tts_voice || "",
    });
  }

  private async speakWithLive(
    text: string,
    current: number,
    guard: VoiceGuard,
    progress = false,
  ) {
    const preference = await api("/voice/session");
    const authorized = () =>
      current === this.generation &&
      canContinueVoice(guard, remoteClient.sessionId, preference.revision);
    if (!authorized()) return;

    const player = this.livePlayback;
    if (player) await player.voiceStartLivePlayback();
    else {
      this.context ??= new AudioContext();
      await this.context.resume();
    }
    if (!authorized()) return;

    const socket = await remoteClient.voiceSocket();
    if (!authorized()) {
      socket.close();
      return;
    }
    this.socket = socket;
    const active = () => authorized() && this.socket === socket;
    const missingAudio = new Error(
      "The configured OpenAI voice did not return audio.",
    );
    let requested = false;
    let heard = false;
    let lastAudible = -Infinity;
    let closed = false;
    let speakingProgress = progress;
    let waitingForAnswer = false;
    let answer: string | undefined;
    let pendingPlayback: number | undefined;
    const rearm = () =>
      void this.arm(Number(this.settings.followup_seconds) > 0).catch((error) =>
        this.fail(error),
      );
    const restartWithAnswer = () => {
      this.clearTimer();
      this.stopCapture();
      if (answer)
        void this.speakWithLive(answer, current, guard).catch((error) => {
          if (authorized()) this.fail(error);
        });
      else this.update({ state: "processing", output: 0 });
    };
    const fail = (error: unknown) => {
      if (!active()) return;
      if (speakingProgress) restartWithAnswer();
      else this.fail(error);
    };
    const say = (phrase: string) => {
      heard = false;
      lastAudible = -Infinity;
      this.clearTimer();
      this.timer = setTimeout(
        () => fail(missingAudio),
        speakingProgress ? 5000 : 20000,
      );
      socket.send(JSON.stringify({ type: "say", text: phrase.slice(0, 4000) }));
    };
    const speakAnswer = () => {
      if (!answer) return;
      if (closed || socket.readyState !== WebSocket.OPEN) {
        restartWithAnswer();
        return;
      }
      speakingProgress = waitingForAnswer = false;
      say(answer);
      answer = undefined;
    };
    const finish = () => {
      if (!active()) return;
      if (speakingProgress) {
        waitingForAnswer = true;
        this.update({ state: "processing", output: 0 });
        speakAnswer();
      } else rearm();
    };
    const drained = () => {
      if (!active()) return;
      this.clearTimer();
      // Playback can briefly run out of packets between parts of the answer.
      this.timer = setTimeout(
        finish,
        closed ? 0 : speakingProgress ? 600 : 1200,
      );
    };
    const keepClockRunning = () => {
      if (!active() || closed || socket.readyState !== WebSocket.OPEN) return;
      if (socket.bufferedAmount > 512000) {
        fail(new Error("Voice connection is too slow. Try again."));
        return;
      }
      socket.send(liveSilence);
      this.audioPoll = setTimeout(keepClockRunning, 100);
    };
    if (player) {
      this.nativePlaybackFinished = (id) => {
        if (id !== pendingPlayback) return;
        pendingPlayback = undefined;
        drained();
      };
    }
    socket.onmessage = (event) => {
      if (!active()) return;
      const value = JSON.parse(event.data);
      if (value.type === "ready" && !requested) {
        requested = true;
        keepClockRunning();
        if (answer) speakAnswer();
        else say(text);
      } else if (
        value.type === "audio" &&
        !waitingForAnswer &&
        typeof value.audio === "string"
      ) {
        // Keep short pauses in the reply but do not let continuous silence
        // trigger playback before speech or delay rearming after it.
        const now = performance.now();
        if (this.hasAudiblePCM(value.audio)) lastAudible = now;
        else if (now - lastAudible > 400) return;
        heard = true;
        this.clearTimer();
        this.timer = setTimeout(
          () => fail(new Error("Audio playback is unavailable.")),
          20000,
        );
        if (player) {
          const id = ++this.playbackID;
          pendingPlayback = id;
          this.update({ state: "speaking" });
          void player
            .voicePlayLive({ audio: value.audio, id })
            .then(({ output }) => {
              if (active() && pendingPlayback === id) this.update({ output });
            })
            .catch(fail);
        } else this.playPCM(value.audio, drained);
      } else if (value.type === "error") fail(new Error(value.message));
    };
    socket.onerror = () => fail(new Error("Voice connection interrupted."));
    socket.onclose = () => {
      if (!active()) return;
      closed = true;
      if (waitingForAnswer) return;
      if (!heard) fail(missingAudio);
      else if (pendingPlayback === undefined && !this.nodes.size) drained();
    };
    this.timer = setTimeout(() => fail(missingAudio), progress ? 5000 : 20000);
    socket.send(
      JSON.stringify({
        type: "start",
        profile: this.settings.profile,
        scope: preference.scope,
        private: preference.private,
        privacy_revision: preference.revision,
        conversation_id: remoteClient.conversationId,
      }),
    );
    // Keep one playback-only session and use the selected voice for both
    // phrases. Never open the microphone or submit the backend task again.
    if (progress)
      return (next?: string) => {
        if (!active()) return false;
        if (!next) rearm();
        else {
          answer = next;
          if (waitingForAnswer) speakAnswer();
        }
        return true;
      };
  }

  private hasAudiblePCM(encoded: string) {
    let pcm: string;
    try {
      pcm = atob(encoded);
    } catch {
      return false;
    }
    if (!pcm.length || pcm.length % 2) return false;
    // A level near silence should not count as delivery of the response.
    let squares = 0;
    for (let i = 1; i < pcm.length; i += 2) {
      const sample = (pcm.charCodeAt(i) << 8) | pcm.charCodeAt(i - 1);
      squares += ((sample << 16) >> 16) ** 2;
    }
    return squares > (pcm.length / 2) * (32768 * 0.00125) ** 2;
  }

  private async live(
    prefix: string,
    resumeId?: string,
    seed?: Uint8Array,
    nativeOpening?: { text: string; bridge: NativeLiveBridge },
  ) {
    const current = this.generation,
      sessionId = remoteClient.sessionId;
    const session = await api("/voice/session");
    if (current !== this.generation) return;
    let context: AudioContext | undefined, stream: MediaStream | undefined;
    if (!nativeOpening) {
      context = this.context ??= new AudioContext();
      await context.resume();
      let deviceId: string | undefined;
      if (this.snapshot.microphone) {
        const catalog = await this.inputs();
        const chosen = catalog.devices?.find(
          (device: Values) => device.uid === this.snapshot.microphone,
        );
        const matches = (
          await navigator.mediaDevices.enumerateDevices()
        ).filter(
          (device) =>
            device.kind === "audioinput" && device.label === chosen?.name,
        );
        if (!chosen || matches.length !== 1)
          throw new Error(
            "The selected microphone is unavailable for live audio. Choose the system default or another microphone.",
          );
        deviceId = matches[0].deviceId;
      }
      if (current !== this.generation) return;
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
          echoCancellation:
            this.settings.desktop_voice_duplex === "echo_cancelled",
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      });
      if (current !== this.generation) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
    }
    let socket: WebSocket;
    try {
      socket = await remoteClient.voiceSocket();
    } catch (error) {
      if (current !== this.generation) return;
      if (!nativeOpening) throw error;
      if (sessionId === remoteClient.sessionId)
        await this.submit(nativeOpening.text);
      return;
    }
    if (current !== this.generation || sessionId !== remoteClient.sessionId) {
      socket.close();
      stream?.getTracks().forEach((track) => track.stop());
      return;
    }
    this.socket = socket;
    let ready = false,
      sentAudio = false,
      closed = false;
    let playingNative: number | undefined;
    let nativeTailUntil = 0;
    let resume = "",
      speechSeconds = 0,
      noise = 0.003;
    const echoCancelled =
      stream?.getAudioTracks()[0]?.getSettings().echoCancellation === true;
    const automatic =
      this.settings.desktop_voice_duplex === "full" ||
      (this.settings.desktop_voice_duplex === "echo_cancelled" &&
        echoCancelled);
    let history: Uint8Array[] = [],
      historyBytes = 0;
    const failed = (error: unknown, transport = false) => {
      if (current !== this.generation) return;
      // Retrying as text after audio reached the core could duplicate actions.
      if (nativeOpening && !sentAudio && transport) {
        void this.submit(nativeOpening.text).catch((err) => this.fail(err));
      } else this.fail(error);
    };
    const transmitEncoded = (audio: string) => {
      if (!audio || socket.readyState !== WebSocket.OPEN) return;
      if (socket.bufferedAmount > 512000) {
        failed(new Error("Voice connection is too slow. Try again."));
        return;
      }
      socket.send(JSON.stringify({ type: "audio", audio }));
      sentAudio = true;
    };
    const transmit = (bytes: Uint8Array) => {
      let binary = "";
      for (const byte of bytes) binary += String.fromCharCode(byte);
      transmitEncoded(btoa(binary));
    };
    const rearm = (delayMs: number) => {
      this.clearTimer();
      this.timer = setTimeout(() => {
        if (current === this.generation)
          void this.arm().catch((error) => this.fail(error));
      }, delayMs);
    };
    const readNative = async () => {
      if (
        !nativeOpening ||
        current !== this.generation ||
        closed ||
        socket.readyState !== WebSocket.OPEN
      )
        return;
      try {
        const { audio } = await nativeOpening.bridge.voiceReadLive();
        if (current !== this.generation || closed) return;
        if (playingNative === undefined && performance.now() >= nativeTailUntil)
          transmitEncoded(audio);
        this.audioPoll = setTimeout(() => void readNative(), 80);
      } catch (error) {
        if (!closed) failed(error, true);
      }
    };
    if (nativeOpening) {
      this.nativePlaybackFinished = (id) => {
        if (id !== playingNative || current !== this.generation) return;
        playingNative = undefined;
        nativeTailUntil = performance.now() + 120;
        if (closed) rearm(100);
        else this.update({ state: "listening", transcript: "", output: 0 });
      };
    }
    socket.onmessage = (event) => {
      if (current !== this.generation) return;
      const value = JSON.parse(event.data);
      if (value.type === "ready") {
        if (ready) return;
        ready = true;
        this.clearTimer();
        resume = value.resume_id;
        if (seed) transmit(seed);
        for (const bytes of history) transmit(bytes);
        history = [];
        historyBytes = 0;
        if (nativeOpening) {
          void readNative();
        } else {
          this.update({ state: "listening" });
          if (!prefix) this.readyCue();
        }
      } else if (value.type === "audio") {
        if (nativeOpening) {
          const id = ++this.playbackID;
          playingNative = id;
          this.update({ state: "speaking" });
          void nativeOpening.bridge
            .voicePlayLive({ audio: value.audio, id })
            .then(({ output }) => {
              if (current === this.generation && playingNative === id)
                this.update({ output });
            })
            .catch((error) => failed(error));
        } else this.playPCM(value.audio);
      } else if (value.type === "input_text") {
        // The opening already has a complete local transcript. Avoid
        // showing it twice while the provider transcribes the same audio.
        if (!nativeOpening || this.snapshot.state === "listening")
          this.update({
            state: "listening",
            transcript: this.snapshot.transcript + value.text,
          });
      } else if (value.type === "output_text")
        this.update({ state: "speaking" });
      else if (value.type === "task") {
        remoteClient.bindConversation(value.conversation_id);
        window.dispatchEvent(
          new CustomEvent("jarvis-companion-task", { detail: value }),
        );
      } else if (value.type === "error") failed(new Error(value.message));
    };
    socket.onerror = () => {
      failed(new Error("Voice connection interrupted."), true);
    };
    socket.onclose = () => {
      if (current !== this.generation) return;
      closed = true;
      if (nativeOpening && !sentAudio) {
        failed(new Error("Voice connection interrupted."), true);
        return;
      }
      // Let the queued audio finish before rearming wake listening.
      if (context)
        rearm(Math.max(0, this.outputAt - context.currentTime) * 1000 + 100);
      else rearm(playingNative === undefined ? 100 : 16000);
    };
    this.timer = setTimeout(() => {
      if (!ready) failed(new Error("Voice connection timed out."), true);
    }, 20000);
    socket.send(
      JSON.stringify({
        type: "start",
        profile: this.settings.profile,
        scope: session.scope,
        private: session.private,
        privacy_revision: session.revision,
        conversation_id: remoteClient.conversationId,
        initial_text: prefix,
        ...(resumeId ? { resume_id: resumeId } : {}),
      }),
    );
    if (!context || !stream) return;
    await context.audioWorklet.addModule(
      new URL("companion-capture.js", document.baseURI).href,
    );
    if (current !== this.generation) return;
    const resampler = new PCMResampler(context.sampleRate);
    const source = context.createMediaStreamSource(stream);
    this.source = source;
    const capture = new AudioWorkletNode(context, "jarvis-companion-capture");
    this.capture = capture;
    capture.port.onmessage = (event) => {
      if (current !== this.generation || socket.readyState !== WebSocket.OPEN)
        return;
      const pcm = resampler.push(event.data);
      const bytes = new Uint8Array(pcm.buffer);
      history.push(bytes);
      historyBytes += bytes.length;
      while (historyBytes > (ready ? 72000 : 480000) && history.length > 1)
        historyBytes -= history.shift()!.length;
      let squares = 0;
      for (const sample of event.data as Float32Array)
        squares += sample * sample;
      const rms = Math.sqrt(squares / Math.max(1, event.data.length));
      this.update({ input: Math.min(1, rms * 8) });
      if (!ready) return;
      if (context.currentTime < this.outputAt) {
        // With echo cancellation, sustained near-field speech interrupts the
        // current answer. Gate the old uplink until its handoff is accepted so
        // the same request cannot be delegated twice by two provider sessions.
        speechSeconds =
          automatic && rms > Math.max(0.035, noise * 3.5)
            ? speechSeconds + pcm.length / 24000
            : 0;
        if (speechSeconds >= 0.22 && resume) {
          const saved = new Uint8Array(historyBytes);
          let offset = 0;
          for (const part of history) {
            saved.set(part, offset);
            offset += part.length;
          }
          this.handoffs.add(socket);
          socket.send(JSON.stringify({ type: "close", handoff: true }));
          void this.stop(false, "listening")
            .then((expected) => {
              if (
                expected === this.generation &&
                this.snapshot.enabled &&
                !this.suspended &&
                remoteClient.sessionId === sessionId
              )
                return this.live("", resume, saved);
            })
            .catch((error) => this.fail(error));
        }
        return;
      }
      speechSeconds = 0;
      noise = Math.min(0.02, noise * 0.98 + rms * 0.02);
      transmit(bytes);
    };
    source.connect(capture);
    capture.connect(context.destination);
  }

  private playPCM(encoded: string, drained?: () => void) {
    const context = this.context!;
    const bytes = Uint8Array.from(atob(encoded), (value) =>
      value.charCodeAt(0),
    );
    if (!bytes.length || bytes.length % 2) return;
    const pcm = new DataView(bytes.buffer),
      audio = context.createBuffer(1, bytes.length / 2, 24000),
      samples = audio.getChannelData(0);
    for (let index = 0; index < samples.length; index++)
      samples[index] = pcm.getInt16(index * 2, true) / 32768;
    const source = context.createBufferSource();
    source.buffer = audio;
    source.connect(context.destination);
    this.outputAt = Math.max(context.currentTime + 0.03, this.outputAt);
    this.nodes.add(source);
    source.onended = () => {
      this.nodes.delete(source);
      if (!this.nodes.size && this.socket) {
        if (drained) drained();
        else this.update({ state: "listening", transcript: "" });
      }
    };
    source.start(this.outputAt);
    this.outputAt += audio.duration;
    let squares = 0;
    for (const sample of samples) squares += sample * sample;
    this.update({
      state: "speaking",
      output: Math.min(1, Math.sqrt(squares / samples.length) * 8),
    });
  }

  sessionChanged() {
    if (this.snapshot.enabled)
      void this.arm().catch((error) => this.fail(error));
  }
  private readyCue() {
    this.context ??= new AudioContext();
    const context = this.context,
      current = this.generation;
    if (!context.createOscillator) return;
    void context
      .resume()
      .then(() => {
        if (current !== this.generation) return;
        const oscillator = context.createOscillator(),
          volume = context.createGain();
        oscillator.frequency.value = 660;
        volume.gain.setValueAtTime(0.035, context.currentTime);
        volume.gain.exponentialRampToValueAtTime(
          0.001,
          context.currentTime + 0.1,
        );
        oscillator.connect(volume);
        volume.connect(context.destination);
        oscillator.onended = () => {
          oscillator.disconnect();
          volume.disconnect();
          if (this.cue === oscillator) this.cue = undefined;
        };
        this.cue = oscillator;
        oscillator.start();
        oscillator.stop(context.currentTime + 0.1);
      })
      .catch(() => {});
  }
  private fail(error: any) {
    const message = error?.message || "Voice is unavailable.";
    const stopping = this.stop(),
      current = this.generation;
    void stopping.finally(() => {
      if (current === this.generation)
        this.update({ state: "unavailable", error: message });
    });
  }
}

export const companionVoice = new CompanionVoice();
export function useCompanionVoice() {
  return useSyncExternalStore(
    companionVoice.subscribe,
    companionVoice.getSnapshot,
    () => initial,
  );
}
