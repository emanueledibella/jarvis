import AVFoundation
import Speech
import Foundation

// Shared by the macOS companion helper and the iOS Capacitor plugin. Ambient
// recognition must remain on device; there is deliberately no network fallback.
final class CompanionSpeech: NSObject, AVSpeechSynthesizerDelegate {
    var emit: ([String: Any]) -> Void = { _ in }
    private var engine: AVAudioEngine?
    private var recognizer: SFSpeechRecognizer?
    private let captureLock = NSLock()
    private var captureID: UUID?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var renewal: Timer?
    private var generation = 0
    private var failures = 0
    private var options: [String: String] = [:]
    private var enabled = false
    private var lastLevel = 0.0
    private let synthesizer = AVSpeechSynthesizer()
    private var spoken: ((String?) -> Void)?
    #if os(macOS)
    private var selected: SelectedAudioInput?
    #endif
    private var separatePlayback: AVAudioEngine?
    private var playbackOnly = false
    private var audio = LiveAudioBuffer(preRollBytes: 24000)
    private var resumeFrame: Int64?
    private var streaming = false
    private var player: AVAudioPlayerNode?
    private var playbackGeneration = 0
    private var playbackFrames = 0
    private var lastPlaybackID = 0
    private static let words = try! NSRegularExpression(pattern: "[\\p{L}\\p{N}]+")

    override init() { super.init(); synthesizer.delegate = self }

    func start(_ options: [String: String], completion: @escaping (String?) -> Void) {
        stop()
        self.options = options
        enabled = true
        let expected = generation
        SFSpeechRecognizer.requestAuthorization { status in
            AVCaptureDevice.requestAccess(for: .audio) { microphone in
                DispatchQueue.main.async {
                    guard self.enabled, self.generation == expected else { completion("Listening was cancelled."); return }
                    guard status == .authorized, microphone else {
                        self.enabled = false
                        completion("Allow microphone and speech recognition in system settings."); return
                    }
                    do { try self.startCapture(); try self.recognize(); completion(nil) }
                    catch { self.stop(); completion(error.localizedDescription) }
                }
            }
        }
    }

    private func startCapture() throws {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: options["language"] ?? "it-IT")),
              recognizer.supportsOnDeviceRecognition else {
            throw failure("On-device speech recognition is unavailable for this language. Install its speech resources or choose another language.")
        }
        self.recognizer = recognizer
        let id = UUID()
        captureLock.lock()
        captureID = id
        lastLevel = 0
        audio = LiveAudioBuffer(preRollBytes: options["live"] == "true" ? 384000 : 24000)
        resumeFrame = 0
        captureLock.unlock()
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try session.setActive(true)
        if let uid = options["microphone"], !uid.isEmpty {
            guard let port = session.availableInputs?.first(where: { $0.uid == uid }) else {
                throw failure("The selected microphone is disconnected.")
            }
            try session.setPreferredInput(port)
        } else { try session.setPreferredInput(nil) }
        #endif
        #if os(macOS)
        let uid = options["microphone"] ?? ""
        if !uid.isEmpty {
            guard AudioInputSelection.resolve(uid, devices: AudioInputDevices.list()) != nil else {
                throw failure("The selected microphone is disconnected.")
            }
            let capture = try SelectedAudioInput(uid: uid) { [weak self] buffer in self?.consume(buffer, id: id) }
            selected = capture
            if options["live"] == "true" {
                let playback = AVAudioEngine()
                installPlayer(on: playback)
                separatePlayback = playback
            }
            try capture.start()
            return
        }
        #endif
        let capture = AVAudioEngine()
        let node = capture.inputNode
        let format = node.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw failure("Microphone is unavailable.") }
        node.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in self?.consume(buffer, id: id) }
        if options["live"] == "true" { installPlayer(on: capture) }
        engine = capture
        capture.prepare()
        try capture.start()
    }

    private var captureRunning: Bool {
        #if os(macOS)
        if let selected = selected { return selected.isRunning }
        #endif
        return engine?.isRunning == true
    }

    private func recognize() throws {
        guard let recognizer = recognizer, captureRunning else { throw failure("Microphone is unavailable.") }
        generation += 1
        let current = generation
        let input = SFSpeechAudioBufferRecognitionRequest()
        input.requiresOnDeviceRecognition = true
        input.shouldReportPartialResults = true
        input.taskHint = .dictation
        input.contextualStrings = [options["phrase"] ?? "Jarvis"]
        captureLock.lock()
        let now = audio.position()
        let seed = audio.snapshot(afterFrame: max(resumeFrame ?? now, now - 12000))
        let origin = seed.frame
        if let pcm = LiveAudioBuffer.buffer(seed.data), let speech = LiveAudioBuffer.recognitionBuffer(pcm) {
            input.append(speech)
        }
        resumeFrame = nil
        request = input
        captureLock.unlock()
        let segment = UUID().uuidString
        task = recognizer.recognitionTask(with: input) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self, self.enabled, self.generation == current else { return }
                if let result = result {
                    self.failures = 0
                    let transcription = result.bestTranscription
                    var event: [String: Any] = ["type": "transcript", "text": transcription.formattedString,
                                                "final": result.isFinal, "segment": segment]
                    if self.options["live"] == "true", let frame = self.wakeFrame(in: transcription, origin: origin) {
                        event["wake_frame"] = frame
                    }
                    self.emit(event)
                }
                if error != nil || result?.isFinal == true { self.recover(current, failed: result?.isFinal != true) }
            }
        }
        renewal = Timer.scheduledTimer(withTimeInterval: 50, repeats: false) { [weak self] _ in
            self?.recover(current, failed: false)
        }
        emit(["type": "ready"])
    }

    private func consume(_ buffer: AVAudioPCMBuffer, id: UUID) {
        captureLock.lock()
        defer { captureLock.unlock() }
        guard captureID == id else { return }
        if let pcm = audio.append(buffer), let request = request, let speech = LiveAudioBuffer.recognitionBuffer(pcm) {
            request.append(speech)
        }
        let now = ProcessInfo.processInfo.systemUptime
        guard now - lastLevel >= 0.1, buffer.frameLength > 0,
              let samples = buffer.floatChannelData?[0] else { return }
        lastLevel = now
        var squares: Float = 0
        for index in 0..<Int(buffer.frameLength) { squares += samples[index] * samples[index] }
        let level = min(1, sqrt(squares / Float(buffer.frameLength)) * 8)
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.captureID == id else { return }
            self.emit(["type": "level", "input": level])
        }
    }

    private func recover(_ expected: Int, failed: Bool) {
        guard enabled, generation == expected else { return }
        clearRecognition()
        // A recognition task can end mid-phrase. Keep the microphone running
        // and rotate only the Speech request, without a cooldown on success.
        if !failed {
            do { try recognize(); return }
            catch { stop(); emit(["type": "error", "message": error.localizedDescription]); return }
        }
        let next = generation
        failures += 1
        emit(["type": "recovering"])
        renewal = Timer.scheduledTimer(withTimeInterval: min(30, 0.5 * pow(2, Double(min(failures - 1, 6)))), repeats: false) { [weak self] _ in
            guard let self = self, self.enabled, self.generation == next else { return }
            do { try self.recognize() }
            catch { self.stop(); self.emit(["type": "error", "message": error.localizedDescription]) }
        }
    }

    private func clearRecognition() {
        generation += 1
        renewal?.invalidate(); renewal = nil
        captureLock.lock()
        let ending = request
        request = nil
        if resumeFrame == nil { resumeFrame = audio.position() }
        captureLock.unlock()
        task?.cancel(); task = nil
        ending?.endAudio()
    }

    func finalizeRecognition() {
        captureLock.lock()
        let ending = request
        if ending != nil {
            request = nil
            resumeFrame = audio.position()
        }
        captureLock.unlock()
        // Finish the hypothesis without stopping microphone capture.
        ending?.endAudio()
    }

    private func wakeFrame(in transcription: SFTranscription, origin: Int64) -> Int64? {
        func words(in text: String) -> [(String, NSRange)] {
            let string = text as NSString
            return Self.words.matches(in: text, range: NSRange(location: 0, length: string.length)).map {
                (string.substring(with: $0.range).lowercased(), $0.range)
            }
        }
        let phrase = words(in: options["phrase"] ?? "Jarvis").map { $0.0 }
        let found = words(in: transcription.formattedString)
        guard !phrase.isEmpty, found.count >= phrase.count,
              let index = (0...(found.count - phrase.count)).first(where: {
                  found[$0..<($0 + phrase.count)].map { $0.0 } == phrase
              }) else { return nil }
        let last = found[index + phrase.count - 1].1
        guard let segment = transcription.segments.last(where: { NSIntersectionRange($0.substringRange, last).length > 0 }),
              NSMaxRange(segment.substringRange) == NSMaxRange(last),
              segment.timestamp >= 0, segment.duration > 0 else { return nil }
        let end = segment.timestamp + segment.duration
        let available = audio.position()
        guard end.isFinite, end * 24000 <= Double(available - origin) else { return nil }
        return origin + Int64((end * 24000).rounded(.up))
    }

    func beginLive(afterFrame frame: Int) -> Bool {
        guard enabled, options["live"] == "true", captureRunning,
              audio.begin(afterFrame: Int64(frame), requireWholeRange: true) else { return false }
        #if os(macOS)
        if let playback = separatePlayback {
            do { try playback.start() }
            catch { return false }
        }
        #endif
        clearRecognition()
        streaming = true
        return true
    }

    func readLive() throws -> Data {
        guard streaming, captureRunning else { throw failure("Microphone is unavailable.") }
        return try audio.drain(maxBytes: 24000)
    }

    func startLivePlayback() throws {
        stop()
        do {
            #if os(iOS)
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .spokenAudio)
            try session.setActive(true)
            #endif
            let playback = AVAudioEngine()
            separatePlayback = playback
            installPlayer(on: playback)
            try playback.start()
            playbackOnly = true
        } catch {
            stop()
            throw failure("Audio playback is unavailable.")
        }
    }

    private func installPlayer(on engine: AVAudioEngine) {
        let player = AVAudioPlayerNode()
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1))
        self.player = player
    }

    func playLive(_ data: Data, id: Int) throws -> Float {
        guard (streaming && captureRunning) || (playbackOnly && separatePlayback?.isRunning == true),
              let player = player,
              let pcm = LiveAudioBuffer.buffer(data), let output = LiveAudioBuffer.recognitionBuffer(pcm),
              playbackFrames + Int(output.frameLength) <= 360000 else {
            throw failure("Invalid voice audio or playback is too slow.")
        }
        let frames = Int(output.frameLength)
        let current = playbackGeneration
        lastPlaybackID = id
        playbackFrames += frames
        player.scheduleBuffer(output, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, self.playbackGeneration == current else { return }
                self.playbackFrames -= frames
                if self.playbackFrames == 0 {
                    self.emit(["type": "live_playback_finished", "id": self.lastPlaybackID])
                }
            }
        }
        if !player.isPlaying { player.play() }
        return LiveAudioBuffer.level(pcm)
    }

    private func clearCapture() {
        clearRecognition()
        captureLock.lock()
        captureID = nil
        audio.clear()
        streaming = false
        captureLock.unlock()
        playbackGeneration += 1
        playbackFrames = 0
        playbackOnly = false
        player?.stop()
        player = nil
        if let engine = engine { engine.stop(); engine.inputNode.removeTap(onBus: 0) }
        engine = nil
        #if os(macOS)
        selected?.stop(); selected = nil
        #endif
        separatePlayback?.stop(); separatePlayback = nil
        recognizer = nil
    }

    func stop() {
        enabled = false
        clearCapture()
        failures = 0
        synthesizer.stopSpeaking(at: .immediate)
        spoken?("Speech stopped."); spoken = nil
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    func speak(_ text: String, language: String, voice: String, completion: @escaping (String?) -> Void) {
        stop()
        #if os(iOS)
        do {
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
            try AVAudioSession.sharedInstance().setActive(true)
        } catch { completion("Audio playback is unavailable."); return }
        #endif
        spoken = completion
        let utterance = AVSpeechUtterance(string: String(text.prefix(4000)))
        utterance.voice = AVSpeechSynthesisVoice(identifier: voice) ?? AVSpeechSynthesisVoice(language: language)
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        let completion = spoken; spoken = nil
        completion?(nil)
    }

    private func failure(_ message: String) -> NSError {
        NSError(domain: "JarvisCompanionSpeech", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
