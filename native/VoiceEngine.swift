@preconcurrency import AVFoundation
import Accelerate
import AppKit
import OSLog
import Speech

@MainActor
final class VoiceEngine: NSObject {
  private let client: ServiceClient
  private var capture: AVAudioEngine?
  private var recognition: SFSpeechRecognitionTask?
  private var recognitionRestart: Task<Void, Never>?
  private var recovery = RecognitionRecovery()
  private let logger = Logger(subsystem: "it.jarvis.personal", category: "recognition")
  private var recognizer: SFSpeechRecognizer?
  private let requestLock = NSLock()
  private var speechRequest: SFSpeechAudioBufferRecognitionRequest?
  private let output = AVAudioEngine()
  private let player = AVAudioPlayerNode()
  private let synth = AVSpeechSynthesizer()
  private let playbackConverter = PlaybackPCMConverter()
  private var playbackFormat: AVAudioFormat { playbackConverter.format }
  private var playbackBuffer = PlaybackBufferState()
  private var playbackStart: Task<Void, Never>?
  private let liveAudio = LiveAudioBuffer()
  private var liveSocket: URLSessionWebSocketTask?
  private var liveReader: Task<Void, Never>?
  private var liveSender: Task<Void, Never>?
  private var liveReady = false
  private var liveGeneration = UUID()
  private var endingLive = false
  private var lastLiveSpeech = Date.distantPast
  private var lastPlaybackSound = Date.distantPast
  private var initialLiveSpeech: String?
  private let liveTransport = URLSession(configuration: .ephemeral)
  private var timer: Timer?
  private var state = "muted"
  private var enabled = false
  private var muted = true
  private var locked = false
  private var settings: [String: Any] = [:]
  private var command = ""
  private var lastTranscript = ""
  private var prefix = ""
  private var lastTextAt = Date.distantPast
  private var lastSoundAt = Date.distantPast
  private var turnStartedAt = Date.distantPast
  private var recognitionStartedAt = Date.distantPast
  private var followupUntil = Date.distantPast
  private var lastLevelAt = Date.distantPast
  private var spokenText = ""
  private var speechGeneration = UUID()
  private var pendingBuffers = 0
  private var finalBufferSeen = false
  private var conversationID: String?
  private var activeTaskID: String?
  private var privateSession = false
  private var turnPrivate = false
  private var turnScope = "personal"
  private var turnProfile = "local_connected"
  private var turnGeneration = UUID()
  private var turnConversationID: String?
  private var voiceScope = "personal"
  private var sessionGeneration = UUID()
  private var outputLevel: Float = 0
  private var lastError: String?
  private var inputLevel: Float = 0
  private var inputBuffers = 0
  private var lastInputBuffer = Date.distantPast
  private var recognitionCallbacks = 0
  private var wakeMatches = 0
  var onStateChange: ((String) -> Void)?

  init(client: ServiceClient) {
    self.client = client
    super.init()
    output.attach(player)
    output.connect(player, to: output.mainMixerNode, format: playbackFormat)
    output.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: nil) {
      [weak self] buffer, _ in
      let level = Self.rms(buffer)
      DispatchQueue.main.async {
        self?.outputLevel = level
        if level > 0.01 { self?.lastPlaybackSound = Date() }
      }
    }
    timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
      Task { @MainActor in self?.tick() }
    }
  }

  nonisolated private static func rms(_ buffer: AVAudioPCMBuffer) -> Float {
    guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return 0 }
    var value: Float = 0
    vDSP_rmsqv(samples, 1, &value, vDSP_Length(buffer.frameLength))
    return min(1, value * 8)
  }

  func configure(_ values: [String: Any]) {
    let previousLanguage = settings["language"] as? String
    let previousProvider = settings["desktop_voice_provider"] as? String
    let previousResponseLanguage = settings["response_language"] as? String
    settings = values
    if previousProvider != nil && previousProvider != values["desktop_voice_provider"] as? String {
      closeLive()
    }
    if previousResponseLanguage != nil
      && previousResponseLanguage != values["response_language"] as? String
    {
      closeLive()
    }
    if let privacy = values["private_session"] as? Bool,
      let scope = values["voice_scope"] as? String
    {
      setSession(privateMode: privacy, scope: scope)
    }
    if values["voice_enabled"] as? Bool == false {
      mute()
      return
    }
    if previousLanguage != nil && previousLanguage != values["language"] as? String && enabled
      && !muted
    {
      restartCapture()
    }
    // Existing grants can resume at login. First-time requests are made only by
    // the explicit Enable Voice action, never by a background web page.
    if !enabled && !UserDefaults.standard.bool(forKey: "microphoneMuted")
      && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
      && SFSpeechRecognizer.authorizationStatus() == .authorized
    {
      enabled = true
      muted = false
      restartCapture()
    }
  }

  func authorize() async -> [String: Any] {
    let mic = await AVCaptureDevice.requestAccess(for: .audio)
    let speech: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation {
      continuation in
      SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
    }
    guard mic && speech == .authorized else {
      muted = true
      setState("permission_required")
      return [
        "state": "permission_required",
        "error":
          "Grant Microphone and Speech Recognition access in System Settings → Privacy & Security.",
      ]
    }
    enabled = true
    muted = false
    UserDefaults.standard.set(false, forKey: "microphoneMuted")
    restartCapture()
    if state == "unavailable" {
      return ["state": state, "error": lastError ?? "Local speech recognition is unavailable."]
    }
    return ["state": state]
  }

  func mute() {
    muted = true
    UserDefaults.standard.set(true, forKey: "microphoneMuted")
    stopSpeaking()
    stopCapture()
    setState("muted")
  }

  func unmute() throws {
    guard settings["voice_enabled"] as? Bool != false else {
      throw ServiceClient.ClientError.server(
        "Voice is disabled in Settings or by emergency stop.")
    }
    guard
      enabled
        || (AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
          && SFSpeechRecognizer.authorizationStatus() == .authorized)
    else {
      throw ServiceClient.ClientError.server("Enable voice and grant permissions first.")
    }
    enabled = true
    muted = false
    UserDefaults.standard.set(false, forKey: "microphoneMuted")
    restartCapture()
    if capture?.isRunning != true {
      throw ServiceClient.ClientError.server(
        lastError ?? "Microphone or local recognition is unavailable.")
    }
  }

  func listen() throws {
    if liveSocket != nil {
      closeLive()
    }
    if muted || capture?.isRunning != true { try unmute() }
    guard capture?.isRunning == true else {
      throw ServiceClient.ClientError.server(
        lastError ?? "Enable the microphone and local recognition first.")
    }
    stopSpeaking()
    beginTurn("")
    resetRecognition()
  }

  func setSession(privateMode: Bool, scope: String) {
    if privateSession != privateMode || voiceScope != scope {
      privateSession = privateMode
      voiceScope = scope
      conversationID = nil
      sessionGeneration = UUID()
      closeLive()
    }
  }

  func setLocked(_ value: Bool) {
    locked = value
    if locked && settings["voice_on_lock_screen"] as? Bool != true {
      stopSpeaking()
      stopCapture()
      setState("locked")
    } else if !muted && enabled {
      restartCapture()
    }
  }

  func restartCapture() {
    closeLive()
    stopCapture()
    guard
      enabled && !muted && settings["voice_enabled"] as? Bool != false
        && !(locked && settings["voice_on_lock_screen"] as? Bool != true)
    else { return }
    recovery = RecognitionRecovery()
    guard
      AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        && SFSpeechRecognizer.authorizationStatus() == .authorized
    else {
      setState(
        "permission_required",
        error: "Grant Jarvis Microphone and Speech Recognition access in Privacy & Security.")
      return
    }
    let language = settings["language"] as? String ?? "it-IT"
    guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)),
      recognizer.supportsOnDeviceRecognition
    else {
      setState(
        "unavailable",
        error:
          "On-device recognition is unavailable for this language on this Mac. Cloud fallback is disabled."
      )
      return
    }
    self.recognizer = recognizer
    let engine = AVAudioEngine()
    let input = engine.inputNode
    let cloudAudio = liveAudio
    // Capture and playback use separate graphs. Enabling VoiceProcessingIO
    // here gives it no playback reference and can fail continuously in its
    // downlink renderer (!i/o). Use the hardware microphone stream directly.
    let format = input.outputFormat(forBus: 0)
    logger.info(
      "Capture format: rate=\(format.sampleRate, privacy: .public) channels=\(format.channelCount, privacy: .public)"
    )
    guard format.sampleRate > 0 && format.channelCount > 0 else {
      setState("unavailable", error: "Microphone is unavailable.")
      return
    }
    input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
      guard let self = self else { return }
      cloudAudio.append(buffer)
      self.requestLock.lock()
      self.speechRequest?.append(buffer)
      self.requestLock.unlock()
      let level = Self.rms(buffer)
      DispatchQueue.main.async {
        self.inputBuffers += 1
        self.lastInputBuffer = Date()
        self.inputLevel = level
        if level > 0.1 { self.lastSoundAt = Date() }
      }
    }
    do {
      engine.prepare()
      try engine.start()
      capture = engine
      lastInputBuffer = Date()
      resetRecognition()
      setState("armed")
    } catch {
      input.removeTap(onBus: 0)
      setState("unavailable", error: "Audio startup failed: check the device and permissions.")
    }
  }

  private func stopCapture() {
    cancelRecognition()
    if let engine = capture {
      engine.stop()
      engine.inputNode.removeTap(onBus: 0)
    }
    capture = nil
    inputLevel = 0
    liveAudio.clear()
  }

  private func cancelRecognition() {
    // Invalidate before cancel: its asynchronous error must never affect a
    // replacement session, a locked screen, or a muted microphone.
    recognitionID = UUID()
    recognitionRestart?.cancel()
    recognitionRestart = nil
    requestLock.lock()
    speechRequest?.endAudio()
    speechRequest = nil
    requestLock.unlock()
    recognition?.cancel()
    recognition = nil
  }

  private func resetRecognition() {
    scheduleRecognition(after: 0.2)
  }

  private func scheduleRecognition(after delay: TimeInterval) {
    cancelRecognition()
    guard
      liveSocket == nil && enabled && !muted && capture?.isRunning == true
        && !(locked && settings["voice_on_lock_screen"] as? Bool != true)
    else { return }
    let generation = recognitionID
    recognitionRestart = Task { [weak self] in
      do { try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000)) } catch { return }
      guard let self = self, self.recognitionID == generation, !self.muted,
        self.capture?.isRunning == true,
        !(self.locked && self.settings["voice_on_lock_screen"] as? Bool != true)
      else { return }
      self.recognitionRestart = nil
      self.startRecognition()
    }
  }

  private func startRecognition() {
    guard liveSocket == nil, let recognizer = recognizer, capture?.isRunning == true else { return }
    recognitionStartedAt = Date()
    guard recognizer.isAvailable else {
      handleRecognitionError(NSError(domain: "JarvisSpeechAvailability", code: 1))
      return
    }
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = true
    request.taskHint = .dictation
    request.contextualStrings = [
      settings["wake_phrase"] as? String ?? "Jarvis", "Jarvis", "Second Brain", "GitHub",
      "calendario",
    ]
    requestLock.lock()
    speechRequest?.endAudio()
    speechRequest = request
    requestLock.unlock()
    lastTranscript = ""
    prefix = ""
    let requestID = UUID()
    recognitionID = requestID
    if ["recovering", "unavailable"].contains(state) { setState("armed") }
    recognition = recognizer.recognitionTask(with: request) { [weak self] result, error in
      DispatchQueue.main.async {
        guard let self = self, self.recognitionID == requestID else { return }
        self.recognitionCallbacks += 1
        if let result = result {
          if !result.bestTranscription.formattedString.isEmpty { self.recovery.receivedSpeech() }
          self.receive(result.bestTranscription.formattedString)
          guard self.recognitionID == requestID else { return }
          if result.isFinal {
            if self.state == "listening" && !self.command.isEmpty {
              self.finishTurn(restartRecognition: false)
            }
            self.resetRecognition()
            return
          }
        }
        if let error = error, !self.muted { self.handleRecognitionError(error as NSError) }
      }
    }
  }
  private var recognitionID = UUID()

  private func handleRecognitionError(_ error: NSError) {
    logger.error(
      "Speech ended: domain=\(error.domain, privacy: .public) code=\(error.code, privacy: .public)")
    let decision = recovery.handle(
      error, sessionDuration: Date().timeIntervalSince(recognitionStartedAt))
    switch decision {
    case .retry(let delay):
      if !["processing", "speaking"].contains(state) {
        command = ""
        prefix = ""
        setState("recovering")
      }
      scheduleRecognition(after: delay)
    case .unavailable(let message):
      stopCapture()
      setState("unavailable", error: message)
    case .permissionRequired(let message):
      stopCapture()
      setState("permission_required", error: message)
    }
  }

  private func receive(_ text: String) {
    guard !muted && state != "locked" && text != lastTranscript else { return }
    lastTranscript = text
    let lower = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
    let phrase = settings["wake_phrase"] as? String ?? "Jarvis"
    let pattern =
      "(?i)(?<![\\p{L}\\p{N}])" + NSRegularExpression.escapedPattern(for: phrase)
      + "(?![\\p{L}\\p{N}])"
    let wake = text.range(of: pattern, options: .regularExpression)
    if wake != nil { wakeMatches += 1 }
    if state == "speaking" {
      if ["stop", "fermati", "silenzio"].contains(lower) {
        stopSpeaking()
        beginTurn("")
        resetRecognition()
        return
      }
      // Do not feed the assistant's own speech back as a new turn. Actual echo
      // cancellation and far-field performance must still be tested on hardware.
      if lower.count > 3 && spokenText.lowercased().contains(lower) { return }
      if wake != nil && !spokenText.lowercased().contains(phrase.lowercased()) {
        stopSpeaking()
        beginTurn("")
      } else {
        return
      }
    }
    if state == "armed" || state == "processing" || state == "unavailable" {
      guard settings["wake_enabled"] as? Bool != false, let range = wake else { return }
      prefix = String(text[..<range.upperBound])
      beginTurn(
        String(text[range.upperBound...]).trimmingCharacters(
          in: .punctuationCharacters.union(.whitespacesAndNewlines)))
    } else if state == "followup" {
      beginTurn(text)
    } else if state == "listening" {
      if let range = wake, command.isEmpty {
        prefix = String(text[..<range.upperBound])
      }
      if !prefix.isEmpty && text.hasPrefix(prefix) {
        command = String(text.dropFirst(prefix.count)).trimmingCharacters(
          in: .punctuationCharacters.union(.whitespacesAndNewlines))
      } else if prefix.isEmpty {
        command = text
      }
      lastTextAt = Date()
    }
  }

  private func beginTurn(_ text: String) {
    turnPrivate = privateSession
    turnScope = voiceScope
    turnProfile = settings["profile"] as? String ?? "local_connected"
    turnGeneration = sessionGeneration
    turnConversationID = conversationID
    if usesOpenAIVoice {
      startLive()
      return
    }
    command = text
    turnStartedAt = Date()
    lastTextAt = Date()
    lastSoundAt = Date()
    setState("listening")
  }

  private var usesOpenAIVoice: Bool {
    settings["desktop_voice_provider"] as? String == "openai_live"
      && settings["profile"] as? String != "local_strict"
  }

  private func startLive(speech: String? = nil) {
    guard liveSocket == nil, settings["voice_enabled"] as? Bool != false else { return }
    cancelRecognition()
    stopSpeaking()
    endingLive = false
    pendingBuffers = 0
    finalBufferSeen = false
    initialLiveSpeech = speech
    liveReady = false
    let generation = UUID()
    let session = sessionGeneration
    liveGeneration = generation
    if !muted { liveAudio.begin() }
    var address = URLComponents(url: client.base, resolvingAgainstBaseURL: true)!
    address.scheme = "ws"
    address.path = "/api/voice/live"
    var request = URLRequest(url: address.url!)
    request.setValue("Bearer \(client.token)", forHTTPHeaderField: "Authorization")
    let socket = liveTransport.webSocketTask(with: request)
    socket.maximumMessageSize = 1_048_576
    liveSocket = socket
    setState("connecting")
    var metadata: [String: Any] = [
      "type": "start", "private": privateSession, "scope": voiceScope,
      "profile": settings["profile"] as? String ?? "cloud",
      "privacy_revision": settings["privacy_revision"] as? Int ?? 0,
    ]
    if let id = conversationID { metadata["conversation_id"] = id }
    liveReader = Task { [weak self] in
      guard let self = self else { return }
      do {
        _ = try await self.client.authenticateService()
        guard self.liveGeneration == generation && !Task.isCancelled else {
          socket.cancel(with: .goingAway, reason: nil)
          return
        }
        socket.resume()
        try await socket.send(
          .string(
            String(data: try JSONSerialization.data(withJSONObject: metadata), encoding: .utf8)!))
        while !Task.isCancelled && self.liveGeneration == generation {
          let message = try await socket.receive()
          let data: Data
          switch message {
          case .string(let value): data = Data(value.utf8)
          case .data(let value): data = value
          @unknown default: continue
          }
          guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            self.liveGeneration == generation
          else { continue }
          switch event["type"] as? String {
          case "ready":
            self.liveReady = true
            self.setState("listening")
            if let text = self.initialLiveSpeech {
              self.initialLiveSpeech = nil
              try await self.sendLive(["type": "say", "text": text])
            }
          case "audio":
            if let encoded = event["audio"] as? String, let bytes = Data(base64Encoded: encoded) {
              try self.playLive(bytes)
            }
          case "input_text": self.recognitionCallbacks += 1
          case "task":
            if session == self.sessionGeneration {
              self.conversationID = event["conversation_id"] as? String ?? self.conversationID
              self.activeTaskID = event["id"] as? String
            }
          case "error":
            self.closeLive(error: event["message"] as? String ?? "OpenAI voice is unavailable.")
            return
          case "closed":
            self.closeLive(drain: true)
            return
          default: break
          }
        }
      } catch {
        if self.liveGeneration == generation && !Task.isCancelled {
          self.closeLive(
            error: "Voice connection interrupted. Press Talk to Jarvis to retry.")
        }
      }
    }
    liveSender = Task { [weak self] in
      guard let self = self else { return }
      do {
        while !Task.isCancelled && self.liveGeneration == generation {
          if self.liveReady && !self.muted {
            let bytes = try self.liveAudio.drain()
            if !bytes.isEmpty {
              try await self.sendLive(["type": "audio", "audio": bytes.base64EncodedString()])
            }
          }
          try await Task.sleep(nanoseconds: 20_000_000)
        }
      } catch {
        if self.liveGeneration == generation && !Task.isCancelled {
          self.closeLive(error: "The audio stream stopped. Reopen the voice conversation.")
        }
      }
    }
  }

  private func sendLive(_ object: [String: Any]) async throws {
    guard let socket = liveSocket else { return }
    let json = String(data: try JSONSerialization.data(withJSONObject: object), encoding: .utf8)!
    try await socket.send(.string(json))
  }

  private func playLive(_ bytes: Data) throws {
    guard bytes.count > 0, bytes.count % 2 == 0, pendingBuffers < 100,
      let format = AVAudioFormat(
        commonFormat: .pcmFormatInt16, sampleRate: 24000, channels: 1, interleaved: true),
      let pcm = AVAudioPCMBuffer(
        pcmFormat: format, frameCapacity: AVAudioFrameCount(bytes.count / 2)),
      let destination = pcm.int16ChannelData?[0]
    else {
      throw ServiceClient.ClientError.server("Invalid OpenAI audio or playback is too slow.")
    }
    pcm.frameLength = AVAudioFrameCount(bytes.count / 2)
    _ = bytes.withUnsafeBytes { raw in memcpy(destination, raw.baseAddress!, bytes.count) }
    let converted = try playbackConverter.convert(pcm)
    if Self.rms(converted) > 0.01 {
      lastLiveSpeech = Date()
      if settings["desktop_voice_duplex"] as? String != "full" { liveAudio.setGated(true) }
      if state != "speaking" { setState("speaking") }
    }
    try enqueuePlayback(converted, realtime: true)
  }

  private func closeLive(error: String? = nil, drain: Bool = false) {
    guard let socket = liveSocket else { return }
    if drain {
      do {
        for tail in try playbackConverter.finish() { try enqueuePlayback(tail, realtime: true) }
      } catch {
        closeLive(error: "Could not finish voice playback.")
        return
      }
    }
    liveSocket = nil
    liveGeneration = UUID()
    liveReady = false
    initialLiveSpeech = nil
    liveReader?.cancel()
    liveSender?.cancel()
    liveReader = nil
    liveSender = nil
    liveAudio.clear()
    Task {
      try? await socket.send(.string("{\"type\":\"close\"}"))
      socket.cancel(with: .normalClosure, reason: nil)
    }
    if drain && pendingBuffers > 0 {
      endingLive = true
      finalBufferSeen = true
      startPlayback(force: true)
      return
    }
    speechGeneration = UUID()
    player.stop()
    output.stop()
    pendingBuffers = 0
    resetPlayback()
    outputLevel = 0
    if let error = error {
      setState("unavailable", error: error)
    } else {
      setState(muted ? "muted" : "armed")
    }
    if !muted && !locked { resetRecognition() }
  }

  private func finishTurn(restartRecognition: Bool = true) {
    let text = command.trimmingCharacters(in: .whitespacesAndNewlines)
    command = ""
    prefix = ""
    guard !text.isEmpty else {
      setState("armed")
      return
    }
    setState("processing")
    let conversation = turnConversationID
    let privacy = privateSession || turnPrivate
    let scope = turnScope
    let generation = turnGeneration
    let profile = turnProfile
    Task {
      do {
        var body: [String: Any] = [
          "text": text, "channel": "voice", "private": privacy, "scope": scope, "profile": profile,
          "request_id": UUID().uuidString,
        ]
        if let conversation = conversation { body["conversation_id"] = conversation }
        let response: [String: Any]
        do { response = try await client.request("/api/chat", method: "POST", body: body) } catch {
          response = try await client.request("/api/chat", method: "POST", body: body)
        }
        activeTaskID = response["id"] as? String
        if generation == sessionGeneration && privacy == privateSession {
          conversationID = response["conversation_id"] as? String ?? conversationID
        }
      } catch {
        setState(
          "armed",
          error: "Delivery is unconfirmed: check the task before repeating the request.")
      }
    }
    if restartRecognition { resetRecognition() }
  }

  private func tick() {
    let current = Date()
    if !muted && capture?.isRunning == true && current.timeIntervalSince(lastInputBuffer) > 5 {
      closeLive()
      stopCapture()
      setState(
        "unavailable",
        error:
          "The microphone is not providing audio. Open the MacBook lid or select an external microphone, then press Talk to Jarvis."
      )
      return
    }
    if liveSocket != nil {
      if state == "speaking" && current.timeIntervalSince(lastLiveSpeech) > 0.6 {
        setState("listening")
      }
      if settings["desktop_voice_duplex"] as? String != "full"
        && current.timeIntervalSince(lastLiveSpeech) > 0.6
        && current.timeIntervalSince(lastPlaybackSound) > 0.4
      {
        liveAudio.setGated(false)
      }
    } else if state == "listening" {
      let silence = max(lastTextAt, lastSoundAt)
      let threshold = Double(settings["end_of_turn_ms"] as? Int ?? 900) / 1000
      if !command.isEmpty && current.timeIntervalSince(silence) > threshold {
        finishTurn()
      } else if current.timeIntervalSince(turnStartedAt)
        > Double(settings["listen_timeout_seconds"] as? Int ?? 30)
      {
        finishTurn()
      }
    } else if state == "followup" && current > followupUntil {
      setState("armed")
      resetRecognition()
    } else if state == "armed" && recognitionRestart == nil
      && current.timeIntervalSince(recognitionStartedAt) > 45
    {
      resetRecognition()
    }
    if current.timeIntervalSince(lastLevelAt) >= 0.12
      && ["armed", "listening", "speaking"].contains(state)
    {
      lastLevelAt = current
      let input = inputLevel
      let output = outputLevel
      Task {
        _ = try? await client.request(
          "/api/native/level", method: "POST", body: ["input": input, "output": output])
      }
    }
  }

  func speak(_ text: String) {
    guard settings["voice_enabled"] as? Bool != false else { return }
    guard !locked || settings["voice_on_lock_screen"] as? Bool == true else { return }
    if usesOpenAIVoice {
      if liveSocket != nil {
        Task { try? await sendLive(["type": "say", "text": text]) }
      } else {
        startLive(speech: text)
      }
      return
    }
    stopSpeaking()
    spokenText = text
    pendingBuffers = 0
    finalBufferSeen = false
    let generation = UUID()
    speechGeneration = generation
    setState("speaking")
    let utterance = AVSpeechUtterance(string: text)
    let identifier = settings["tts_voice"] as? String ?? ""
    utterance.voice =
      identifier.isEmpty
      ? AVSpeechSynthesisVoice(
        language: SpokenLanguage.select(
          for: text, response: settings["response_language"] as? String ?? "auto",
          fallback: settings["language"] as? String ?? "it-IT"))
      : AVSpeechSynthesisVoice(identifier: identifier)
    utterance.rate = AVSpeechUtteranceDefaultSpeechRate
    synth.write(utterance) { [weak self] buffer in
      guard let pcm = buffer as? AVAudioPCMBuffer else { return }
      DispatchQueue.main.async {
        guard let self = self, self.speechGeneration == generation else { return }
        do {
          if pcm.frameLength == 0 {
            for tail in try self.playbackConverter.finish() {
              try self.enqueuePlayback(tail, realtime: false)
            }
            self.finalBufferSeen = true
            self.startPlayback(force: true)
            self.finishPlaybackIfNeeded()
            return
          }
          try self.enqueuePlayback(self.playbackConverter.convert(pcm), realtime: false)
        } catch {
          self.stopSpeaking()
          self.setState(
            self.muted ? "muted" : "armed", error: "Audio playback is unavailable.")
        }
      }
    }
  }

  private func enqueuePlayback(_ buffer: AVAudioPCMBuffer, realtime: Bool) throws {
    let frames = Int(buffer.frameLength)
    guard frames > 0 else { return }
    if realtime && playbackBuffer.queuedFrames + frames > Int(playbackFormat.sampleRate * 8) {
      throw ServiceClient.ClientError.server("Voice playback exceeded its bounded buffer.")
    }
    if !output.isRunning { try output.start() }
    playbackBuffer.enqueue(frames)
    pendingBuffers += 1
    let generation = speechGeneration
    player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
      DispatchQueue.main.async {
        guard let self = self, self.speechGeneration == generation else { return }
        self.pendingBuffers -= 1
        self.playbackBuffer.completed(frames)
        if self.playbackBuffer.queuedFrames == 0 { self.player.pause() }
        self.finishPlaybackIfNeeded()
      }
    }
    if playbackBuffer.ready || !playbackBuffer.buffering {
      startPlayback()
    } else if playbackStart == nil {
      playbackStart = Task { [weak self] in
        do { try await Task.sleep(nanoseconds: 120_000_000) } catch { return }
        guard let self = self, self.speechGeneration == generation else { return }
        self.playbackStart = nil
        self.startPlayback(force: true)
      }
    }
  }

  private func startPlayback(force: Bool = false) {
    guard playbackBuffer.queuedFrames > 0,
      force || playbackBuffer.ready || !playbackBuffer.buffering
    else { return }
    playbackStart?.cancel()
    playbackStart = nil
    playbackBuffer.started()
    if !player.isPlaying { player.play() }
  }

  private func resetPlayback() {
    playbackStart?.cancel()
    playbackStart = nil
    playbackBuffer.reset()
    playbackConverter.reset()
  }

  private func finishPlaybackIfNeeded() {
    guard finalBufferSeen && pendingBuffers == 0 else { return }
    outputLevel = 0
    if endingLive {
      endingLive = false
      liveAudio.clear()
      setState(muted ? "muted" : "armed")
      if !muted { scheduleRecognition(after: 0.4) }
      return
    }
    if muted {
      setState("muted")
    } else {
      followupUntil = Date().addingTimeInterval(Double(settings["followup_seconds"] as? Int ?? 8))
      setState("followup")
      resetRecognition()
    }
  }

  func stopSpeaking() {
    closeLive()
    speechGeneration = UUID()
    synth.stopSpeaking(at: .immediate)
    player.stop()
    output.stop()
    pendingBuffers = 0
    resetPlayback()
    finalBufferSeen = false
    outputLevel = 0
    if state == "speaking" { setState(muted ? "muted" : "armed") }
  }

  private func setState(_ value: String, error: String? = nil) {
    if let error = error {
      lastError = error
    } else if value != state || !["unavailable", "permission_required"].contains(value) {
      lastError = nil
    }
    state = value
    onStateChange?(value)
    var body: [String: Any] = [
      "voice_state": value,
      "microphone": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        ? "authorized" : "not_authorized",
      "speech": SFSpeechRecognizer.authorizationStatus() == .authorized
        ? "authorized" : "not_authorized",
      "on_device": recognizer?.supportsOnDeviceRecognition ?? false, "muted": muted,
      "locked": locked, "input_buffers": inputBuffers,
      "recognition_callbacks": recognitionCallbacks, "wake_matches": wakeMatches,
    ]
    if let error = lastError { body["error"] = error }
    Task { _ = try? await client.request("/api/native/status", method: "POST", body: body) }
  }

  func statusHeartbeat() {
    setState(state)
  }

  func shutdown() {
    stopSpeaking()
    stopCapture()
  }

  func taskChanged(_ id: String, state: String) {
    guard liveSocket == nil else { return }
    if id == activeTaskID && ["failed", "cancelled", "waiting_user"].contains(state) {
      activeTaskID = nil
      if !muted { setState("armed") }
    }
  }
}
