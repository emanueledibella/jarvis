import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { createServer } from "vite";
import {
  afterWake,
  PCMResampler,
  voicePreferenceKey,
} from "../src/companionVoicePolicy.ts";

test("wake matching uses complete Unicode words, preserves commands, and ignores similar names", () => {
  assert.equal(
    afterWake("Ciao, JARVIS! Accendi la luce", "Jarvis"),
    "Accendi la luce",
  );
  assert.equal(afterWake("Jarvison accendi la luce", "Jarvis"), null);
  assert.equal(afterWake("myjarvis", "Jarvis"), null);
  assert.equal(afterWake("Ehi, Jarvis", "Ehi Jarvis"), "");
  assert.equal(
    afterWake("你好，Jarvis，che ore sono?", "Jarvis"),
    "che ore sono?",
  );
  assert.notEqual(
    voicePreferenceKey("https://one.example", "phone"),
    voicePreferenceKey("https://two.example", "phone"),
  );
});

test("microphone PCM stays continuous across uneven chunks at 44.1 and 48 kHz", () => {
  for (const rate of [44100, 48000]) {
    const input = Float32Array.from(
      { length: rate },
      (_, index) => Math.sin(index / 30) * 0.5,
    );
    const complete = new PCMResampler(rate).push(input);
    const resampler = new PCMResampler(rate),
      chunks: number[] = [];
    for (let offset = 0; offset < input.length; offset += 2048)
      chunks.push(...resampler.push(input.subarray(offset, offset + 2048)));
    assert.deepEqual(Int16Array.from(chunks), complete);
    assert.ok(Math.abs(complete.length - 24000) <= 1);
  }
});

let vite: any, Voice: any, remote: any, voice: any, listener: any;
let preference = { scope: "personal", private: false, revision: 0 };
let blocked = false,
  chatRequests: any[] = [],
  spoken: any[] = [],
  starts = 0;
let statusGate: Promise<void> | null = null;
let taskDetail: Record<string, unknown> = {
  task: { state: "succeeded", result: "Sono le dodici." },
};
let mobileCalls: { method: string; options: any }[] = [];
let mobileAudio = "";
let beginLive = true;
const storage = new Map<string, string>();
const originalFetch = globalThis.fetch;
const settings = {
  voice_enabled: true,
  wake_enabled: true,
  wake_phrase: "Jarvis",
  language: "it-IT",
  response_language: "auto",
  desktop_voice_provider: "apple",
  end_of_turn_ms: 300,
  listen_timeout_seconds: 10,
  followup_seconds: 0,
};

before(async () => {
  const events: any = new EventTarget();
  events.jarvisCompanion = {
    platform: "macos",
    load: async () => null,
    save: async () => {},
    clear: async () => {},
    voiceStart: async () => {
      starts++;
    },
    voiceStop: async () => {},
    voiceSpeak: async (options: any) => {
      spoken.push(options);
    },
    onVoice: (receive: any) => {
      listener = receive;
      return () => {
        listener = null;
      };
    },
  };
  Object.assign(globalThis, {
    location: new URL("https://jarvis.example"),
    window: events,
    document: { baseURI: "https://jarvis.example/" },
    history: { replaceState() {} },
    sessionStorage: { removeItem() {} },
    localStorage: {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
    },
    AudioContext: class {
      async resume() {}
    },
    Capacitor: {
      PluginHeaders: [
        {
          name: "JarvisNative",
          methods: [
            ...[
              "voiceStart",
              "voiceStop",
              "voiceSpeak",
              "voiceFinalizeRecognition",
              "voiceBeginLive",
              "voiceReadLive",
              "voiceStartLivePlayback",
              "voicePlayLive",
            ].map((name) => ({ name, rtype: "promise" })),
            { name: "addListener", rtype: "callback" },
            { name: "removeListener", rtype: "callback" },
          ],
        },
      ],
      nativePromise: async (_plugin: string, method: string, options: any) => {
        mobileCalls.push({ method, options });
        if (method === "voiceBeginLive") return { started: beginLive };
        if (method === "voiceReadLive") {
          const audio = mobileAudio;
          mobileAudio = "";
          return { audio };
        }
        if (method === "voicePlayLive") return { output: 0.5 };
        if (method === "voiceSpeak") spoken.push(options);
        return {};
      },
      nativeCallback: (
        _plugin: string,
        method: string,
        _options: any,
        receive: any,
      ) => {
        listener = method === "addListener" ? receive : null;
        return "voice-listener";
      },
    },
  });
  vite = await createServer({
    root: fileURLToPath(new URL("..", import.meta.url)),
    configFile: false,
    server: { middlewareMode: true, watch: null, ws: false },
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  Voice = (await vite.ssrLoadModule("/src/companionVoice.ts")).CompanionVoice;
  remote = (await vite.ssrLoadModule("/src/remoteClient.ts")).remoteClient;
  remote.enabled = true;
  remote.access = "synthetic-access";
  remote.expires = Date.now() + 300000;
  remote.credentials = {
    server_url: "https://jarvis.example",
    device_id: "synthetic-device",
    session_id: "synthetic-session",
  };
  globalThis.fetch = async (input: any, options: any) => {
    const pathname = new URL(String(input)).pathname;
    if (pathname === "/api/settings")
      return Response.json({ values: settings });
    if (pathname === "/api/status") {
      if (statusGate) await statusGate;
      return Response.json({ emergency_stop: blocked });
    }
    if (pathname === "/api/voice/session") return Response.json(preference);
    if (pathname === "/api/chat") {
      chatRequests.push(JSON.parse(options.body));
      return Response.json({
        id: "voice-task",
        conversation_id: "voice-conversation",
      });
    }
    if (pathname === "/api/tasks/voice-task/detail")
      return Response.json(taskDetail);
    throw new Error("Unexpected route: " + pathname);
  };
});

after(async () => {
  await voice?.control("mute");
  globalThis.fetch = originalFetch;
  await vite?.close();
});

test("calling Jarvis sends one command, speaks the result, and returns to wake listening", async () => {
  voice = new Voice();
  await voice.attach();
  assert.equal(voice.getSnapshot().enabled, false);
  assert.equal(starts, 0, "Microphone requires local opt-in");
  await voice.control("enable");
  listener({
    type: "transcript",
    segment: "one",
    text: "Parla con Jarvison",
    final: true,
  });
  assert.equal(voice.getSnapshot().state, "armed");
  listener({
    type: "transcript",
    segment: "two",
    text: "Jarvis, che ore sono?",
    final: false,
  });
  listener({
    type: "transcript",
    segment: "two",
    text: "Jarvis, che ore sono?",
    final: true,
  });
  await delay(400);
  assert.equal(chatRequests.length, 1);
  assert.equal(chatRequests[0].text, "che ore sono?");
  assert.equal(chatRequests[0].channel, "voice");
  assert.equal(chatRequests[0].privacy_revision, 0);
  assert.equal(spoken.length, 1);
  assert.equal(spoken[0].text, "Sono le dodici.");
  assert.equal(voice.getSnapshot().state, "armed");
});

test("mute cancels a pending command and cannot be undone by an in-flight enable", async () => {
  listener({
    type: "transcript",
    segment: "three",
    text: "Jarvis, accendi la luce",
    final: true,
  });
  await voice.control("mute");
  await delay(350);
  assert.equal(chatRequests.length, 1);
  let release: any;
  statusGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const enabling = voice.control("enable");
  await delay(1);
  await voice.control("mute");
  release();
  statusGate = null;
  await enabling;
  assert.equal(voice.getSnapshot().enabled, false);
  assert.equal(voice.getSnapshot().state, "muted");
});

test("backgrounding cancels activation, returning resumes opt-in, and emergency prevents capture", async () => {
  await voice.control("enable");
  listener({
    type: "transcript",
    segment: "four",
    text: "Jarvis, leggi la posta",
    final: true,
  });
  listener({ type: "suspended" });
  await delay(350);
  assert.equal(chatRequests.length, 1);
  listener({ type: "resumed" });
  await delay(20);
  assert.equal(voice.getSnapshot().state, "armed");
  blocked = true;
  await assert.rejects(voice.control("listen"), /Emergency stop/);
  assert.equal(voice.getSnapshot().state, "muted");
  await voice.control("mute");
  blocked = false;
  voice.detach();
});

test("Live sends PCM after activation, interrupts with a single-use handoff, and releases the microphone on mute", async () => {
  const sockets: any[] = [],
    tracks: any[] = [],
    captures: any[] = [];
  class Socket {
    static OPEN = 1;
    readyState = 1;
    sent: any[] = [];
    onmessage: any;
    onclose: any;
    onerror: any;
    send(value: string) {
      this.sent.push(JSON.parse(value));
    }
    close() {
      this.readyState = 3;
    }
  }
  class Context {
    currentTime = 0;
    sampleRate = 48000;
    destination = {};
    audioWorklet = { addModule: async () => {} };
    async resume() {}
    async close() {}
    createMediaStreamSource() {
      return { connect() {}, disconnect() {} };
    }
    createBuffer(_channels: number, length: number, rate: number) {
      const data = new Float32Array(length);
      return { getChannelData: () => data, duration: length / rate };
    }
    createBufferSource() {
      return {
        buffer: null,
        connect() {},
        start() {},
        stop() {},
        onended: null,
      };
    }
  }
  Object.assign(globalThis, {
    WebSocket: Socket,
    AudioContext: Context,
    AudioWorkletNode: class {
      port: any = {};
      constructor() {
        captures.push(this);
      }
      connect() {}
      disconnect() {}
    },
  });
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: async () => {
          const track = {
            stopped: false,
            stop() {
              this.stopped = true;
            },
            getSettings: () => ({ echoCancellation: true }),
          };
          tracks.push(track);
          return { getTracks: () => [track], getAudioTracks: () => [track] };
        },
      },
    },
  });
  const socketMethod = remote.voiceSocket;
  remote.voiceSocket = async () => {
    const socket = new Socket();
    sockets.push(socket);
    return socket;
  };
  Object.assign(settings, {
    profile: "cloud",
    desktop_voice_provider: "openai_live",
    desktop_voice_duplex: "echo_cancelled",
  });
  voice = new Voice();
  try {
    await voice.attach();
    await voice.control("listen");
    assert.equal(sockets.length, 1);
    assert.equal(sockets[0].sent[0].type, "start");
    // Audio spoken during provider startup is bounded in RAM and sent once ready.
    captures[0].port.onmessage({ data: new Float32Array(2048).fill(0.1) });
    assert.equal(sockets[0].sent.length, 1);
    sockets[0].onmessage({
      data: JSON.stringify({ type: "ready", resume_id: "live-handoff" }),
    });
    assert.equal(sockets[0].sent[1].type, "audio");
    assert.ok(atob(sockets[0].sent[1].audio).length > 0);
    sockets[0].onmessage({
      data: JSON.stringify({ type: "audio", audio: btoa("\0".repeat(24000)) }),
    });
    assert.equal(voice.getSnapshot().state, "speaking");
    for (let index = 0; index < 6; index++)
      captures[0].port.onmessage?.({ data: new Float32Array(2048).fill(0.1) });
    await delay(20);
    assert.equal(sockets.length, 2);
    assert.deepEqual(sockets[0].sent.at(-1), { type: "close", handoff: true });
    assert.equal(sockets[1].sent[0].resume_id, "live-handoff");
    assert.equal(tracks[0].stopped, true);
    await voice.control("mute");
    assert.ok(tracks.every((track) => track.stopped));
    assert.equal(sockets[1].readyState, 3);
  } finally {
    await voice.control("mute");
    voice.detach();
    remote.voiceSocket = socketMethod;
  }
});

async function until(check: () => boolean) {
  for (let index = 0; index < 100; index++) {
    if (check()) return;
    await delay(20);
  }
  assert.ok(check(), "Timed out waiting for the voice state");
}

async function withMobile(
  platform: "ios" | "android",
  run: () => Promise<void>,
) {
  const bridge = globalThis as any;
  if (platform === "ios") bridge.webkit = { messageHandlers: { bridge: {} } };
  else bridge.androidBridge = {};
  Object.assign(settings, {
    desktop_voice_provider: "openai_live",
    profile: "cloud",
  });
  mobileCalls = [];
  mobileAudio = "";
  beginLive = true;
  voice = new Voice();
  try {
    await voice.attach();
    await voice.control("enable");
    await run();
  } finally {
    await voice.control("mute");
    voice.detach();
    await delay(0);
    delete bridge.webkit;
    delete bridge.androidBridge;
  }
}

test("iPhone keeps one capture through a wake, delayed transcription, and Live playback", async () => {
  const originalSocket = remote.voiceSocket;
  const sent: any[] = [];
  const socket: any = {
    readyState: WebSocket.OPEN,
    send: (value: string) => sent.push(JSON.parse(value)),
    close() {
      this.readyState = 3;
    },
  };
  remote.voiceSocket = async () => socket;
  const count = chatRequests.length;
  try {
    await withMobile("ios", async () => {
      assert.equal(
        mobileCalls.find((call) => call.method === "voiceStart")?.options
          .bufferLive,
        true,
      );
      const stops = mobileCalls.filter(
        (call) => call.method === "voiceStop",
      ).length;
      listener({
        type: "transcript",
        segment: "opening",
        text: "Jarvis",
        final: false,
      });
      await delay(350);
      assert.equal(
        sent.length,
        0,
        "Saying only the name sends nothing to Live",
      );

      listener({
        type: "transcript",
        segment: "opening",
        text: "Jarvis dimmi che",
        final: false,
      });
      for (let index = 0; index < 5; index++) {
        listener({ type: "level", input: 0.12 });
        await delay(90);
      }
      assert.equal(voice.getSnapshot().state, "listening");
      assert.equal(
        sent.length,
        0,
        "Speech with no new words from the recognizer keeps the turn open",
      );
      assert.equal(chatRequests.length, count);
      listener({ type: "resumed" }); // iOS can become active without having gone to background.
      listener({
        type: "transcript",
        segment: "opening",
        text: "Jarvis dimmi che tempo",
        final: false,
      });
      await until(() =>
        mobileCalls.some((call) => call.method === "voiceFinalizeRecognition"),
      );
      assert.equal(sent.length, 0);
      listener({
        type: "transcript",
        segment: "opening",
        text: "Jarvis dimmi che tempo",
        final: true,
        wake_frame: 12000,
      });
      listener({
        type: "transcript",
        segment: "continued",
        text: "farà domani",
        final: true,
      });
      await until(() => sent.length === 1);
      assert.equal(
        voice.getSnapshot().transcript,
        "dimmi che tempo farà domani",
      );
      assert.equal(
        sent[0].initial_text,
        "",
        "The retained audio supplies the full request",
      );
      assert.equal(
        mobileCalls.filter((call) => call.method === "voiceStop").length,
        stops,
      );
      assert.deepEqual(
        mobileCalls.find((call) => call.method === "voiceBeginLive")?.options,
        { frame: 12000 },
      );
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceReadLive"),
        false,
      );

      const openingAudio = btoa(String.fromCharCode(0, 1, 0, 2));
      mobileAudio = openingAudio;
      socket.onmessage({
        data: JSON.stringify({ type: "ready", resume_id: "native-resume" }),
      });
      await until(() => sent.length === 2);
      assert.deepEqual(sent[1], { type: "audio", audio: openingAudio });
      socket.onmessage({
        data: JSON.stringify({
          type: "audio",
          audio: btoa(String.fromCharCode(0, 1)),
        }),
      });
      await until(() =>
        mobileCalls.some((call) => call.method === "voicePlayLive"),
      );
      socket.close();
      socket.onclose();
      assert.equal(voice.getSnapshot().state, "speaking");
      listener({
        type: "live_playback_finished",
        id: mobileCalls.find((call) => call.method === "voicePlayLive")?.options
          .id,
      });
      await until(() => voice.getSnapshot().state === "armed");
      assert.equal(
        chatRequests.length,
        count,
        "A transmitted Live turn cannot be sent again as chat",
      );
    });
  } finally {
    remote.voiceSocket = originalSocket;
  }
});

test("Android waits for the final hypothesis and submits the combined request once", async () => {
  const count = chatRequests.length;
  const socket = replySocket();
  const originalSocket = remote.voiceSocket;
  remote.voiceSocket = async () => socket;
  try {
    await withMobile("android", async () => {
      listener({ type: "speech", active: true });
      listener({
        type: "transcript",
        segment: "wake",
        text: "Jarvis dimmi",
        final: false,
      });
      await delay(380);
      assert.equal(voice.getSnapshot().state, "listening");
      assert.equal(chatRequests.length, count);
      listener({
        type: "transcript",
        segment: "wake",
        text: "Jarvis dimmi che",
        final: true,
      });
      listener({ type: "speech", active: false });
      listener({ type: "speech", active: true });
      listener({
        type: "transcript",
        segment: "second",
        text: "ore",
        final: false,
      });
      await delay(380);
      assert.equal(chatRequests.length, count);
      listener({
        type: "transcript",
        segment: "second",
        text: "ore sono",
        final: true,
      });
      listener({ type: "speech", active: false });
      await until(() => socket.sent.length > 0);
      assert.equal(chatRequests.length, count + 1);
      assert.equal(chatRequests.at(-1).text, "dimmi che ore sono");
      socket.receive({ type: "ready" });
      assert.equal(socket.sent.at(-1).type, "say");
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceSpeak"),
        false,
      );
    });
  } finally {
    remote.voiceSocket = originalSocket;
  }
});

function replySocket() {
  return {
    readyState: WebSocket.OPEN,
    sent: [] as any[],
    onmessage: null as any,
    onclose: null as any,
    send(value: string) {
      this.sent.push(JSON.parse(value));
    },
    receive(value: object) {
      this.onmessage?.({ data: JSON.stringify(value) });
    },
    close() {
      this.readyState = 3;
      this.onclose?.();
    },
  };
}

test("a spoken weather request plays progress and the result on one readback socket", async () => {
  const count = chatRequests.length;
  const previous = taskDetail;
  const socket = replySocket();
  const originalSocket = remote.voiceSocket;
  let connections = 0;
  remote.voiceSocket = async () => {
    connections++;
    return socket;
  };
  try {
    await withMobile("ios", async () => {
      beginLive = false;
      const update = "Un attimo, controllo il meteo.";
      taskDetail = {
        task: { state: "running" },
        events: [{ type: "task.progress", data: { text: update } }],
      };
      listener({
        type: "transcript",
        segment: "weather",
        text: "Jarvis, che tempo fa?",
        final: true,
        wake_frame: 12000,
      });
      await until(() => socket.sent.some((value) => value.type === "start"));
      socket.receive({ type: "ready" });
      assert.deepEqual(
        socket.sent.filter((value) => value.type === "say"),
        [{ type: "say", text: update }],
      );
      const audible = { type: "audio", audio: btoa(String.fromCharCode(0, 1)) };
      socket.receive(audible);
      await until(() =>
        mobileCalls.some((call) => call.method === "voicePlayLive"),
      );
      taskDetail = { task: { state: "succeeded", result: "A Torino piove." } };
      listener({
        type: "live_playback_finished",
        id: mobileCalls.find((call) => call.method === "voicePlayLive")?.options
          .id,
      });
      await until(
        () => socket.sent.filter((value) => value.type === "say").length === 2,
      );
      assert.deepEqual(
        socket.sent.filter((value) => value.type === "say").at(-1),
        { type: "say", text: "A Torino piove." },
      );
      assert.equal(connections, 1);
      assert.equal(chatRequests.length, count + 1);
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceSpeak"),
        false,
      );
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceReadLive"),
        false,
      );
    });
  } finally {
    remote.voiceSocket = originalSocket;
    taskDetail = previous;
  }
});

test("an expired iPhone wake buffer submits once and plays the answer with the configured Live voice", async () => {
  const count = chatRequests.length;
  const socket = replySocket();
  const originalSocket = remote.voiceSocket;
  remote.voiceSocket = async () => socket;
  try {
    await withMobile("ios", async () => {
      beginLive = false;
      listener({
        type: "transcript",
        segment: "expired",
        text: "Jarvis che ore sono",
        final: true,
        wake_frame: 12000,
      });
      await until(() => socket.sent.length > 0);
      assert.equal(chatRequests.length, count + 1);
      assert.equal(chatRequests.at(-1).text, "che ore sono");
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceBeginLive"),
        true,
      );
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceStartLivePlayback"),
        true,
      );
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceReadLive"),
        false,
      );
      assert.equal(
        socket.sent[0].initial_text,
        undefined,
        "Do not run the user's command again",
      );

      socket.receive({ type: "ready" });
      socket.receive({ type: "ready" });
      assert.deepEqual(
        socket.sent.filter((value) => value.type === "say"),
        [{ type: "say", text: "Sono le dodici." }],
      );
      for (const value of socket.sent.filter((value) => value.type === "audio"))
        assert.equal(atob(value.audio), "\0".repeat(4800));
      socket.receive({ type: "audio", audio: btoa("\0".repeat(4800)) });
      assert.equal(voice.getSnapshot().state, "processing");
      socket.receive({ type: "audio", audio: btoa(String.fromCharCode(0, 1)) });
      await until(() =>
        mobileCalls.some((call) => call.method === "voicePlayLive"),
      );
      socket.close();
      assert.equal(voice.getSnapshot().state, "speaking");
      listener({
        type: "live_playback_finished",
        id: mobileCalls.find((call) => call.method === "voicePlayLive")?.options
          .id,
      });
      await until(() => voice.getSnapshot().state === "armed");
      assert.equal(
        mobileCalls.some((call) => call.method === "voiceSpeak"),
        false,
      );
      assert.equal(chatRequests.length, count + 1);
    });
  } finally {
    remote.voiceSocket = originalSocket;
  }
});

test("a Mac companion wake reaches Live on the original native capture", async () => {
  const bridge = window.jarvisCompanion!;
  const originalSocket = remote.voiceSocket;
  const options: any[] = [];
  const sent: any[] = [];
  let stopped = 0;
  const originalStart = bridge.voiceStart;
  const originalStop = bridge.voiceStop;
  bridge.voiceStart = async (value) => {
    options.push(value);
  };
  bridge.voiceStop = async () => {
    stopped++;
  };
  bridge.voiceFinalizeRecognition = async () => {};
  bridge.voiceBeginLive = async ({ frame }) => ({ started: frame === 18000 });
  bridge.voiceReadLive = async () => ({
    audio: btoa(String.fromCharCode(0, 1)),
  });
  bridge.voicePlayLive = async () => ({ output: 0 });
  const socket: any = {
    readyState: WebSocket.OPEN,
    send: (value: string) => sent.push(JSON.parse(value)),
    close() {
      this.readyState = 3;
    },
  };
  remote.voiceSocket = async () => socket;
  voice = new Voice();
  try {
    await voice.attach();
    await voice.control("enable");
    const idleStops = stopped;
    assert.equal(options.at(-1).bufferLive, true);
    listener({
      type: "transcript",
      segment: "mac",
      text: "Jarvis dimmi",
      final: false,
    });
    listener({ type: "level", input: 0.15 });
    await delay(200);
    assert.equal(sent.length, 0);
    listener({
      type: "transcript",
      segment: "mac",
      text: "Jarvis dimmi che ore sono",
      final: true,
      wake_frame: 18000,
    });
    await until(() => sent.length === 1);
    socket.onmessage({ data: JSON.stringify({ type: "ready" }) });
    await until(() => sent.length > 1);
    assert.equal(sent[1].type, "audio");
    assert.equal(
      stopped,
      idleStops,
      "The original Mac microphone remains open through Live startup",
    );
  } finally {
    await voice.control("mute");
    voice.detach();
    bridge.voiceStart = originalStart;
    bridge.voiceStop = originalStop;
    delete bridge.voiceFinalizeRecognition;
    delete bridge.voiceBeginLive;
    delete bridge.voiceReadLive;
    delete bridge.voicePlayLive;
    remote.voiceSocket = originalSocket;
  }
});
