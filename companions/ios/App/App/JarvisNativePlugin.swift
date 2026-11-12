import Foundation
import Capacitor
import Security
import AVFoundation

@objc(JarvisNativePlugin)
public class JarvisNativePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "JarvisNativePlugin"
    public let jsName = "JarvisNative"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "load", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "save", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "clear", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "shared", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "removeShared", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "startRecording", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stopRecording", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceStart", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceStop", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceFinalizeRecognition", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceBeginLive", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceReadLive", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceStartLivePlayback", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voicePlayLive", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceSpeak", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "voiceInputs", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthRead", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "healthCancel", returnType: CAPPluginReturnPromise)
    ]
    private let speech = CompanionSpeech()
    private var health: CompanionHealth?
    private var voiceObservers: [NSObjectProtocol] = []
    private var vaultActions: [(JarvisNativePlugin) -> Void] = []
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private let service = "it.jarvis.companion.session"
    private var inbox: URL? { FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.it.jarvis.companion")?.appendingPathComponent("SharedInbox", isDirectory: true) }

    public override func load() {
        speech.emit = { [weak self] value in self?.notifyListeners("voice", data: value) }
        voiceObservers.append(NotificationCenter.default.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.speech.stop(); self?.cleanupRecording()
            Task { @MainActor in self?.health?.cancel() }
            self?.notifyListeners("voice", data: ["type": "suspended"])
        })
        voiceObservers.append(NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            self?.resumeVault()
            self?.notifyListeners("voice", data: ["type": "resumed"])
        })
        voiceObservers.append(NotificationCenter.default.addObserver(forName: UIApplication.protectedDataDidBecomeAvailableNotification, object: nil, queue: .main) { [weak self] _ in
            self?.resumeVault()
        })
        voiceObservers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] notification in
            let kind = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            if kind == AVAudioSession.InterruptionType.began.rawValue {
                self?.speech.stop(); self?.notifyListeners("voice", data: ["type": "suspended"])
            } else if UIApplication.shared.applicationState == .active {
                self?.notifyListeners("voice", data: ["type": "resumed"])
            }
        })
    }

    @objc func healthStatus(_ call: CAPPluginCall) {
        Task { @MainActor in call.resolve(["available": CompanionHealth.available]) }
    }

    @objc func healthRead(_ call: CAPPluginCall) {
        Task { @MainActor in
            do {
                guard let metrics = call.getArray("metrics", String.self), let days = call.getInt("days") else {
                    call.reject("Choose health categories and a reading period."); return
                }
                if self.health == nil { self.health = CompanionHealth() }
                call.resolve(try await self.health!.read(metrics: metrics, days: days))
            } catch { call.reject(error.localizedDescription) }
        }
    }

    @objc func healthCancel(_ call: CAPPluginCall) {
        Task { @MainActor in self.health?.cancel(); call.resolve() }
    }

    @objc func voiceStart(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard UIApplication.shared.applicationState != .background else { call.reject("Open Jarvis to enable listening."); return }
            self.cleanupRecording()
            self.speech.start(["language": call.getString("language") ?? "it-IT",
                               "phrase": call.getString("phrase") ?? "Jarvis",
                               "microphone": call.getString("microphone") ?? "",
                               "live": call.getBool("bufferLive") == true ? "true" : "false"]) { error in
                if let error = error { call.reject(error) } else { call.resolve() }
            }
        }
    }
    @objc func voiceStop(_ call: CAPPluginCall) {
        DispatchQueue.main.async { self.speech.stop(); call.resolve() }
    }
    @objc func voiceFinalizeRecognition(_ call: CAPPluginCall) {
        DispatchQueue.main.async { self.speech.finalizeRecognition(); call.resolve() }
    }
    @objc func voiceBeginLive(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard UIApplication.shared.applicationState != .background, let frame = call.getInt("frame") else {
                call.resolve(["started": false]); return
            }
            call.resolve(["started": self.speech.beginLive(afterFrame: frame)])
        }
    }
    @objc func voiceReadLive(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            do { call.resolve(["audio": try self.speech.readLive().base64EncodedString()]) }
            catch { call.reject(error.localizedDescription) }
        }
    }
    @objc func voicePlayLive(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let encoded = call.getString("audio"), encoded.utf8.count <= 96000,
                  let data = Data(base64Encoded: encoded), let id = call.getInt("id") else {
                call.reject("Invalid voice audio."); return
            }
            do { call.resolve(["output": try self.speech.playLive(data, id: id)]) }
            catch { call.reject(error.localizedDescription) }
        }
    }
    @objc func voiceStartLivePlayback(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard UIApplication.shared.applicationState != .background else {
                call.reject("Open Jarvis to use voice playback."); return
            }
            do { try self.speech.startLivePlayback(); call.resolve() }
            catch { call.reject(error.localizedDescription) }
        }
    }
    @objc func voiceSpeak(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.speech.speak(call.getString("text") ?? "", language: call.getString("language") ?? "it-IT", voice: call.getString("voice") ?? "") { error in
                if let error = error { call.reject(error) } else { call.resolve() }
            }
        }
    }
    @objc func voiceInputs(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            let session = AVAudioSession.sharedInstance()
            let devices = (session.availableInputs ?? []).map { port in
                ["uid": port.uid, "name": port.portName, "is_default": session.currentRoute.inputs.contains(where: { $0.uid == port.uid }),
                 "bluetooth": port.portType == .bluetoothHFP] as [String: Any]
            }
            call.resolve(["state": "ready", "devices": devices])
        }
    }

    deinit { for observer in voiceObservers { NotificationCenter.default.removeObserver(observer) } }

    @objc func shared(_ call: CAPPluginCall) {
        var values: [[String: Any]] = []
        if let directory = inbox, let files = try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.contentModificationDateKey, .fileSizeKey]) {
            for url in files {
                let metadata = try? url.resourceValues(forKeys: [.contentModificationDateKey, .fileSizeKey])
                if Date().timeIntervalSince(metadata?.contentModificationDate ?? .distantPast) > 900 || (metadata?.fileSize ?? 4_100_001) > 4_100_000 || values.count >= 5 {
                    try? FileManager.default.removeItem(at: url); continue
                }
                if let data = try? Data(contentsOf: url), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { values.append(value) }
            }
        }
        call.resolve(["items": values])
    }
    @objc func removeShared(_ call: CAPPluginCall) {
        guard let raw = call.getString("id"), let id = UUID(uuidString: raw), let directory = inbox else { call.reject("Identificativo condivisione non valido."); return }
        try? FileManager.default.removeItem(at: directory.appendingPathComponent(id.uuidString.lowercased() + ".json"))
        call.resolve()
    }
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "remote-session", kSecAttrSynchronizable as String: false]
    }

    private func withUnlockedVault(_ call: CAPPluginCall, _ action: @escaping (JarvisNativePlugin) -> Void) {
        DispatchQueue.main.async {
            if UIApplication.shared.isProtectedDataAvailable {
                action(self)
            } else if self.vaultActions.count < 8 {
                self.vaultActions.append(action)
            } else {
                call.reject("Unlock your iPhone to reconnect Jarvis.")
            }
        }
    }

    private func resumeVault() {
        guard UIApplication.shared.isProtectedDataAvailable else { return }
        let pending = vaultActions
        vaultActions.removeAll()
        for action in pending { action(self) }
    }

    @objc func load(_ call: CAPPluginCall) {
        withUnlockedVault(call) { $0.loadSavedSession(call) }
    }

    private func loadSavedSession(_ call: CAPPluginCall) {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
        if status != errSecSuccess, !UIApplication.shared.isProtectedDataAvailable {
            load(call); return
        }
        if status == errSecItemNotFound { call.resolve([:]); return }
        guard status == errSecSuccess, let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else {
            call.reject("Sblocca il dispositivo per accedere alle credenziali."); return
        }
        call.resolve(["value": value])
    }

    @objc func save(_ call: CAPPluginCall) {
        guard let value = call.getString("value"), value.utf8.count <= 8192,
              let data = value.data(using: .utf8) else { call.reject("Credenziali non valide."); return }
        withUnlockedVault(call) { $0.saveSession(call, data: data) }
    }

    private func saveSession(_ call: CAPPluginCall, data: Data) {
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        if status != errSecSuccess, !UIApplication.shared.isProtectedDataAvailable {
            // The core may have already rotated the token. Finish persisting
            // this same token on unlock instead of trying the previous one.
            withUnlockedVault(call) { $0.saveSession(call, data: data) }
            return
        }
        guard status == errSecSuccess else { call.reject("Salvataggio nel Keychain non riuscito."); return }
        call.resolve()
    }

    @objc func clear(_ call: CAPPluginCall) {
        withUnlockedVault(call) { plugin in
            plugin.speech.stop()
            let status = SecItemDelete(plugin.query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { call.reject("Rimozione credenziali non riuscita."); return }
            call.resolve()
        }
    }

    @objc func startRecording(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard self.recorder == nil else { call.reject("Una registrazione è già attiva."); return }
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async {
                    guard granted else { call.reject("Permesso microfono non concesso."); return }
                    do {
                        let session = AVAudioSession.sharedInstance()
                        try session.setCategory(.record, mode: .default)
                        try session.setActive(true)
                        let directory = FileManager.default.temporaryDirectory
                        for file in (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? [] where file.lastPathComponent.hasPrefix("jarvis-recording-") {
                            try? FileManager.default.removeItem(at: file)
                        }
                        let url = directory.appendingPathComponent("jarvis-recording-\(UUID().uuidString).m4a")
                        let recorder = try AVAudioRecorder(url: url, settings: [
                            AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: 16000,
                            AVNumberOfChannelsKey: 1, AVEncoderBitRateKey: 48000])
                        self.recordingURL = url
                        self.recorder = recorder
                        guard recorder.record(forDuration: 60) else { throw NSError(domain: "JarvisAudio", code: 1) }
                        call.resolve()
                    } catch { self.cleanupRecording(); call.reject("Impossibile avviare la registrazione.") }
                }
            }
        }
    }

    @objc func stopRecording(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let recorder = self.recorder, let url = self.recordingURL else { call.reject("Nessuna registrazione attiva."); return }
            let seconds = recorder.currentTime
            recorder.stop()
            defer { self.cleanupRecording() }
            guard let data = try? Data(contentsOf: url), data.count <= 3_000_000 else {
                call.reject("Registrazione assente o troppo grande."); return
            }
            call.resolve(["content": data.base64EncodedString(), "mime": "audio/mp4", "seconds": min(60, seconds)])
        }
    }

    private func cleanupRecording() {
        recorder?.stop(); recorder = nil
        if let url = recordingURL { try? FileManager.default.removeItem(at: url) }
        recordingURL = nil
        try? AVAudioSession.sharedInstance().setActive(false)
    }
}

class JarvisViewController: CAPBridgeViewController {
    override func capacitorDidLoad() {
        bridge?.registerPluginInstance(JarvisNativePlugin())
        #if DEBUG
        if ProcessInfo.processInfo.environment["JARVIS_VERIFY_NATIVE"] == "1" {
            verifyNativeVault()
        }
        #endif
    }

    #if DEBUG
    // Developer-only integration probe: a separate temporary item, never session credentials.
    private func verifyNativeVault() {
        let registered = bridge?.plugin(withName: "JarvisNative") is JarvisNativePlugin
        NSLog("[JarvisVerify] native-plugin=%@", registered ? "ready" : "missing")
        let sample = Data("Jarvis native vault probe".utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "it.jarvis.companion.diagnostics",
            kSecAttrAccount as String: UUID().uuidString,
            kSecAttrSynchronizable as String: false
        ]
        var attributes = query
        attributes[kSecValueData as String] = sample
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let added = SecItemAdd(attributes as CFDictionary, nil)
        guard added == errSecSuccess else {
            NSLog("[JarvisVerify] keychain-add=%d", added)
            return
        }
        var read = query
        read[kSecReturnData as String] = true
        read[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        let loaded = SecItemCopyMatching(read as CFDictionary, &value)
        let matches = (value as? Data) == sample
        let removed = SecItemDelete(query as CFDictionary)
        NSLog("[JarvisVerify] keychain-add=%d read=%d match=%@ delete=%d",
              added, loaded, matches ? "yes" : "no", removed)
    }
    #endif
}
