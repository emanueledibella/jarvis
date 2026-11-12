import Foundation
import AppKit

@main
struct CompanionVoiceHelper {
    static func main() {
        let speech = CompanionSpeech()
        let lock = NSLock()
        nonisolated func output(_ value: [String: Any]) {
            guard let data = try? JSONSerialization.data(withJSONObject: value) else { return }
            lock.lock(); defer { lock.unlock() }
            FileHandle.standardOutput.write(data + Data([10]))
        }
        speech.emit = output
        // The helper captures only while the authenticated renderer asks for it.
        DispatchQueue.global().async {
            while let line = readLine(), line.utf8.count <= 100000 {
                guard let data = line.data(using: .utf8), let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let id = value["id"] as? Int, let command = value["command"] as? String else { continue }
                DispatchQueue.main.async {
                    func reply(_ error: String? = nil, result: [String: Any] = [:]) {
                        output(["type": "reply", "id": id, "result": result, "error": error as Any? ?? NSNull()])
                    }
                    let options = value["options"] as? [String: Any] ?? [:]
                    switch command {
                    case "start":
                        var speechOptions = options.compactMapValues { $0 as? String }
                        speechOptions["live"] = options["bufferLive"] as? Bool == true ? "true" : "false"
                        speech.start(speechOptions) { reply($0) }
                    case "stop": speech.stop(); reply()
                    case "finalize-recognition": speech.finalizeRecognition(); reply()
                    case "inputs": reply(result: ["state": "ready", "devices": AudioInputDevices.list().map { $0.catalogEntry }])
                    case "speak":
                        speech.speak(options["text"] as? String ?? "", language: options["language"] as? String ?? "it-IT",
                                     voice: options["voice"] as? String ?? "") { reply($0) }
                    case "begin-live":
                        let started = (options["frame"] as? Int).map(speech.beginLive(afterFrame:)) ?? false
                        reply(result: ["started": started])
                    case "read-live":
                        do { reply(result: ["audio": try speech.readLive().base64EncodedString()]) }
                        catch { reply(error.localizedDescription) }
                    case "start-live-playback":
                        do { try speech.startLivePlayback(); reply() }
                        catch { reply(error.localizedDescription) }
                    case "play-live":
                        guard let encoded = options["audio"] as? String, encoded.utf8.count <= 96000,
                              let data = Data(base64Encoded: encoded), let id = options["id"] as? Int else {
                            reply("Invalid voice audio."); return
                        }
                        do { reply(result: ["output": try speech.playLive(data, id: id)]) }
                        catch { reply(error.localizedDescription) }
                    default: reply("Unsupported speech command.")
                    }
                }
            }
            DispatchQueue.main.async { speech.stop(); exit(0) }
        }
        RunLoop.main.run()
    }
}
