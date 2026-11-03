import AppKit
import Foundation
import CoreGraphics

struct ServiceClient {
    enum ClientError: LocalizedError {
        case server(String)
        var errorDescription: String? { if case .server(let message) = self { return message }; return nil }
    }
}

@main struct RemoteNativeHelper {
    @MainActor static func main() async {
        let application = NSApplication.shared
        application.setActivationPolicy(.accessory)
        do {
            let data = FileHandle.standardInput.readDataToEndOfFile()
            guard data.count <= 1_000_000,
                  let request = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let operation = request["operation"] as? String else { throw ServiceClient.ClientError.server("Invalid native request.") }
            let arguments = request["arguments"] as? [String: Any] ?? [:]
            let deadline = request["expires"] as? Double ?? 0
            let unlocked = { () -> Bool in
                guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else { return false }
                return !(session["CGSSessionScreenIsLocked"] as? Bool ?? false)
            }
            let result: [String: Any]
            if operation == "native.status" {
                result = ["locked": !unlocked(), "platform": "macos"]
            } else if operation == "calendar.authorize" {
                application.activate(ignoringOtherApps: true)
                result = try await CalendarBridge().authorize()
            } else {
                guard deadline > Date().timeIntervalSince1970 else { throw ServiceClient.ClientError.server("Native authority expired.") }
                if operation == "screen.capture" {
                    application.activate(ignoringOtherApps: true)
                    result = try await ScreenContext().capture(allowed: { unlocked() && Date().timeIntervalSince1970 < deadline })
                } else if ["calendar.list", "calendar.create", "calendar.update", "calendar.delete"].contains(operation) {
                    result = try CalendarBridge().perform(operation, arguments)
                } else {
                    throw ServiceClient.ClientError.server("Unsupported native capability.")
                }
            }
            let output = try JSONSerialization.data(withJSONObject: result)
            FileHandle.standardOutput.write(output)
        } catch {
            let output = try? JSONSerialization.data(withJSONObject: ["error": error.localizedDescription])
            FileHandle.standardOutput.write(output ?? Data("{\"error\":\"Native operation failed.\"}".utf8))
        }
    }
}
