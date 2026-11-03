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
        CAPPluginMethod(name: "stopRecording", returnType: CAPPluginReturnPromise)
    ]
    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private let service = "it.jarvis.companion.session"
    private var inbox: URL? { FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.it.jarvis.companion")?.appendingPathComponent("SharedInbox", isDirectory: true) }

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

    @objc func load(_ call: CAPPluginCall) {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &item)
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
        let attributes: [String: Any] = [kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { call.reject("Salvataggio nel Keychain non riuscito."); return }
        call.resolve()
    }

    @objc func clear(_ call: CAPPluginCall) {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { call.reject("Rimozione credenziali non riuscita."); return }
        call.resolve()
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
    }
}
