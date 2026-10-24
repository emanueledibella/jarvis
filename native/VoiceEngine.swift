import Accelerate
import AppKit
@preconcurrency import AVFoundation
import Speech

@MainActor
final class VoiceEngine: NSObject {
    private let client: ServiceClient
    private var capture: AVAudioEngine?
    private var recognition: SFSpeechRecognitionTask?
    private var recognizer: SFSpeechRecognizer?
    private let requestLock = NSLock()
    private var speechRequest: SFSpeechAudioBufferRecognitionRequest?
    private let output = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let synth = AVSpeechSynthesizer()
    private let playbackFormat = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1)!
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
    var onStateChange: ((String) -> Void)?

    init(client: ServiceClient) {
        self.client = client
        super.init()
        output.attach(player)
        output.connect(player, to: output.mainMixerNode, format: playbackFormat)
        output.mainMixerNode.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buffer, _ in
            let level = Self.rms(buffer)
            DispatchQueue.main.async { self?.outputLevel = level }
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
        settings = values
        if let privacy = values["private_session"] as? Bool, let scope = values["voice_scope"] as? String {
            setSession(privateMode: privacy, scope: scope)
        }
        if values["voice_enabled"] as? Bool == false {
            mute()
            return
        }
        if previousLanguage != nil && previousLanguage != values["language"] as? String && enabled && !muted {
            restartCapture()
        }
        // Existing grants can resume at login. First-time requests are made only by
        // the explicit Enable Voice action, never by a background web page.
        if !enabled && !UserDefaults.standard.bool(forKey: "microphoneMuted") && AVCaptureDevice.authorizationStatus(for: .audio) == .authorized && SFSpeechRecognizer.authorizationStatus() == .authorized {
            enabled = true
            muted = false
            restartCapture()
        }
    }

    func authorize() async -> [String: Any] {
        let mic = await AVCaptureDevice.requestAccess(for: .audio)
        let speech: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard mic && speech == .authorized else {
            muted = true
            setState("permission_required")
            return ["state": "permission_required", "error": "Concedi Microfono e Riconoscimento vocale in Impostazioni di Sistema → Privacy e sicurezza."]
        }
        enabled = true
        muted = false
        UserDefaults.standard.set(false, forKey: "microphoneMuted")
        restartCapture()
        if state == "unavailable" { return ["state": state, "error": lastError ?? "Riconoscimento locale non disponibile."] }
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
        guard settings["voice_enabled"] as? Bool != false else { throw ServiceClient.ClientError.server("La voce è disattivata nelle impostazioni o dall'arresto di emergenza.") }
        guard enabled || (AVCaptureDevice.authorizationStatus(for: .audio) == .authorized && SFSpeechRecognizer.authorizationStatus() == .authorized) else {
            throw ServiceClient.ClientError.server("Abilita prima la voce e concedi i permessi.")
        }
        enabled = true
        muted = false
        UserDefaults.standard.set(false, forKey: "microphoneMuted")
        restartCapture()
        if capture?.isRunning != true { throw ServiceClient.ClientError.server(lastError ?? "Microfono o riconoscimento locale non disponibile.") }
    }

    func listen() throws {
        if muted { try unmute() }
        guard capture?.isRunning == true else { throw ServiceClient.ClientError.server(lastError ?? "Abilita prima il microfono e il riconoscimento locale.") }
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
        stopCapture()
        guard !muted && !(locked && settings["voice_on_lock_screen"] as? Bool != true) else { return }
        let language = settings["language"] as? String ?? "it-IT"
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)), recognizer.supportsOnDeviceRecognition else {
            setState("unavailable", error: "Il riconoscimento on-device non è disponibile per questa lingua sul Mac. Nessun fallback cloud.")
            return
        }
        self.recognizer = recognizer
        let engine = AVAudioEngine()
        let input = engine.inputNode
        // Voice processing is best effort; a hardware test still determines echo quality.
        try? input.setVoiceProcessingEnabled(true)
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 && format.channelCount > 0 else {
            setState("unavailable", error: "Microfono non disponibile.")
            return
        }
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let self = self else { return }
            self.requestLock.lock()
            self.speechRequest?.append(buffer)
            self.requestLock.unlock()
            let level = Self.rms(buffer)
            DispatchQueue.main.async {
                self.inputLevel = level
                if level > 0.1 { self.lastSoundAt = Date() }
            }
        }
        do {
            engine.prepare()
            try engine.start()
            capture = engine
            resetRecognition()
            setState("armed")
        } catch {
            input.removeTap(onBus: 0)
            setState("unavailable", error: "Avvio audio fallito: controlla il dispositivo e i permessi.")
        }
    }

    private func stopCapture() {
        recognition?.cancel()
        recognition = nil
        requestLock.lock()
        speechRequest?.endAudio()
        speechRequest = nil
        requestLock.unlock()
        if let engine = capture {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        capture = nil
        inputLevel = 0
    }

    private func resetRecognition() {
        recognition?.cancel()
        recognition = nil
        guard capture?.isRunning == true, let recognizer = recognizer else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.taskHint = .dictation
        request.contextualStrings = [settings["wake_phrase"] as? String ?? "Jarvis", "Jarvis", "Second Brain", "GitHub", "calendario"]
        requestLock.lock()
        speechRequest?.endAudio()
        speechRequest = request
        requestLock.unlock()
        lastTranscript = ""
        prefix = ""
        recognitionStartedAt = Date()
        let requestID = UUID()
        recognitionID = requestID
        recognition = recognizer.recognitionTask(with: request) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self, self.recognitionID == requestID else { return }
                if let result = result {
                    self.receive(result.bestTranscription.formattedString)
                    if result.isFinal {
                        if self.state == "listening" && !self.command.isEmpty { self.finishTurn() }
                        self.resetRecognition()
                    }
                } else if error != nil && !self.muted {
                    self.setState("unavailable", error: "Riconoscimento locale interrotto. Controlla i modelli della lingua e riattiva la voce.")
                }
            }
        }
    }
    private var recognitionID = UUID()

    private func receive(_ text: String) {
        guard !muted && state != "locked" && text != lastTranscript else { return }
        lastTranscript = text
        let lower = text.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
        let phrase = settings["wake_phrase"] as? String ?? "Jarvis"
        let pattern = "(?i)(?<![\\p{L}\\p{N}])" + NSRegularExpression.escapedPattern(for: phrase) + "(?![\\p{L}\\p{N}])"
        let wake = text.range(of: pattern, options: .regularExpression)
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
            if wake != nil || (inputLevel > 0.2 && lower.count > 3) {
                stopSpeaking()
                beginTurn("")
            } else { return }
        }
        if state == "armed" || state == "processing" || state == "unavailable" {
            guard settings["wake_enabled"] as? Bool != false, let range = wake else { return }
            prefix = String(text[..<range.upperBound])
            beginTurn(String(text[range.upperBound...]).trimmingCharacters(in: .punctuationCharacters.union(.whitespacesAndNewlines)))
        } else if state == "followup" {
            beginTurn(text)
        } else if state == "listening" {
            if let range = wake, command.isEmpty {
                prefix = String(text[..<range.upperBound])
            }
            if !prefix.isEmpty && text.hasPrefix(prefix) {
                command = String(text.dropFirst(prefix.count)).trimmingCharacters(in: .punctuationCharacters.union(.whitespacesAndNewlines))
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
        command = text
        turnStartedAt = Date()
        lastTextAt = Date()
        lastSoundAt = Date()
        setState("listening")
    }

    private func finishTurn() {
        let text = command.trimmingCharacters(in: .whitespacesAndNewlines)
        command = ""
        prefix = ""
        guard !text.isEmpty else { setState("armed"); return }
        setState("processing")
        let conversation = turnConversationID
        let privacy = privateSession || turnPrivate, scope = turnScope, generation = turnGeneration, profile = turnProfile
        Task {
            do {
                var body: [String: Any] = ["text": text, "channel": "voice", "private": privacy, "scope": scope,"profile":profile,"request_id":UUID().uuidString]
                if let conversation = conversation { body["conversation_id"] = conversation }
                let response: [String: Any]
                do { response = try await client.request("/api/chat", method:"POST",body:body) }
                catch { response = try await client.request("/api/chat",method:"POST",body:body) }
                activeTaskID = response["id"] as? String
                if generation == sessionGeneration && privacy == privateSession { conversationID = response["conversation_id"] as? String ?? conversationID }
            } catch {
                setState("armed", error: "Consegna non confermata: controlla l'attività prima di ripetere la richiesta.")
            }
        }
        resetRecognition()
    }

    private func tick() {
        let current = Date()
        if state == "listening" {
            let silence = max(lastTextAt, lastSoundAt)
            let threshold = Double(settings["end_of_turn_ms"] as? Int ?? 900) / 1000
            if !command.isEmpty && current.timeIntervalSince(silence) > threshold {
                finishTurn()
            } else if current.timeIntervalSince(turnStartedAt) > Double(settings["listen_timeout_seconds"] as? Int ?? 30) {
                finishTurn()
            }
        } else if state == "followup" && current > followupUntil {
            setState("armed")
            resetRecognition()
        } else if state == "armed" && current.timeIntervalSince(recognitionStartedAt) > 45 {
            resetRecognition()
        }
        if current.timeIntervalSince(lastLevelAt) >= 0.12 && (state == "listening" || state == "speaking") {
            lastLevelAt = current
            let input = inputLevel, output = outputLevel
            Task { _ = try? await client.request("/api/native/level", method: "POST", body: ["input": input, "output": output]) }
        }
    }

    func speak(_ text: String) {
        guard settings["voice_enabled"] as? Bool != false else { return }
        guard !locked || settings["voice_on_lock_screen"] as? Bool == true else { return }
        stopSpeaking()
        spokenText = text
        pendingBuffers = 0
        finalBufferSeen = false
        let generation = UUID()
        speechGeneration = generation
        setState("speaking")
        let utterance = AVSpeechUtterance(string: text)
        let identifier = settings["tts_voice"] as? String ?? ""
        utterance.voice = identifier.isEmpty ? AVSpeechSynthesisVoice(language: settings["language"] as? String ?? "it-IT") : AVSpeechSynthesisVoice(identifier: identifier)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        synth.write(utterance) { [weak self] buffer in
            guard let pcm = buffer as? AVAudioPCMBuffer else { return }
            DispatchQueue.main.async {
                guard let self = self, self.speechGeneration == generation else { return }
                if pcm.frameLength == 0 {
                    self.finalBufferSeen = true
                    self.finishPlaybackIfNeeded()
                    return
                }
                guard let converted = self.convert(pcm) else { return }
                do {
                    if !self.output.isRunning { try self.output.start() }
                    self.pendingBuffers += 1
                    self.player.scheduleBuffer(converted, completionCallbackType: .dataPlayedBack) { _ in
                        DispatchQueue.main.async {
                            guard self.speechGeneration == generation else { return }
                            self.pendingBuffers -= 1
                            self.finishPlaybackIfNeeded()
                        }
                    }
                    if !self.player.isPlaying { self.player.play() }
                } catch {
                    self.stopSpeaking()
                    self.setState(self.muted ? "muted" : "armed", error: "Riproduzione audio non disponibile.")
                }
            }
        }
    }

    private func convert(_ input: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let converter = AVAudioConverter(from: input.format, to: playbackFormat),
              let result = AVAudioPCMBuffer(pcmFormat: playbackFormat, frameCapacity: AVAudioFrameCount(Double(input.frameLength) * 48000 / input.format.sampleRate) + 64) else { return nil }
        var supplied = false
        var error: NSError?
        converter.convert(to: result, error: &error) { _, status in
            if supplied { status.pointee = .noDataNow; return nil }
            supplied = true
            status.pointee = .haveData
            return input
        }
        return error == nil ? result : nil
    }

    private func finishPlaybackIfNeeded() {
        guard finalBufferSeen && pendingBuffers == 0 else { return }
        outputLevel = 0
        if muted { setState("muted") }
        else {
            followupUntil = Date().addingTimeInterval(Double(settings["followup_seconds"] as? Int ?? 8))
            setState("followup")
            resetRecognition()
        }
    }

    func stopSpeaking() {
        speechGeneration = UUID()
        synth.stopSpeaking(at: .immediate)
        player.stop()
        output.stop()
        pendingBuffers = 0
        finalBufferSeen = false
        outputLevel = 0
        if state == "speaking" { setState(muted ? "muted" : "armed") }
    }

    private func setState(_ value: String, error: String? = nil) {
        if let error = error { lastError = error }
        else if value != state || !["unavailable", "permission_required"].contains(value) { lastError = nil }
        state = value
        onStateChange?(value)
        var body: [String: Any] = ["voice_state": value, "microphone": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized ? "authorized" : "not_authorized", "speech": SFSpeechRecognizer.authorizationStatus() == .authorized ? "authorized" : "not_authorized", "on_device": recognizer?.supportsOnDeviceRecognition ?? false, "muted": muted, "locked": locked]
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
        if id == activeTaskID && ["failed", "cancelled", "waiting_user"].contains(state) {
            activeTaskID = nil
            if !muted { setState("armed") }
        }
    }
}
