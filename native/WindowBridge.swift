import AppKit
import CoreGraphics
import Foundation

@MainActor final class WindowBridge {
    func list() -> [String: Any] {
        let runningApps = NSWorkspace.shared.runningApplications
        let frontmost = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""

        var regularApps: [[String: Any]] = []
        for app in runningApps {
            guard app.activationPolicy == .regular else { continue }
            let name = app.localizedName ?? ""
            guard !name.isEmpty else { continue }
            regularApps.append([
                "name": name,
                "bundle_id": app.bundleIdentifier ?? "",
                "pid": app.processIdentifier,
                "active": app.isActive,
                "hidden": app.isHidden,
            ])
        }

        var windows: [[String: Any]] = []
        if let windowList = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] {
            for win in windowList {
                let layer = win[kCGWindowLayer as String] as? Int ?? -1
                guard layer == 0 else { continue }
                let owner = win[kCGWindowOwnerName as String] as? String ?? ""
                guard !owner.isEmpty, owner != "Window Server", owner != "JarvisNativeHelper" else { continue }
                let id = win[kCGWindowNumber as String] as? Int ?? 0
                let title = win[kCGWindowName as String] as? String ?? ""
                let boundsDict = win[kCGWindowBounds as String] as? [String: Any] ?? [:]
                let bounds: [String: Any] = [
                    "x": boundsDict["X"] as? Double ?? 0,
                    "y": boundsDict["Y"] as? Double ?? 0,
                    "width": boundsDict["Width"] as? Double ?? 0,
                    "height": boundsDict["Height"] as? Double ?? 0,
                ]
                windows.append([
                    "id": id,
                    "app": owner,
                    "title": title,
                    "bounds": bounds,
                    "active": owner == frontmost,
                ])
            }
        }

        return [
            "frontmost": frontmost,
            "apps": regularApps,
            "windows": windows,
            "count": windows.count,
        ]
    }

    private func findAppURL(name: String, bundleId: String) -> URL? {
        if !bundleId.isEmpty, let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) {
            return url
        }
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: name) {
            return url
        }
        for folder in ["/Applications", "/System/Applications", "/System/Applications/Utilities", ("~/Applications" as NSString).expandingTildeInPath] {
            let appPath = (folder as NSString).appendingPathComponent(name.hasSuffix(".app") ? name : "\(name).app")
            if FileManager.default.fileExists(atPath: appPath) {
                return URL(fileURLWithPath: appPath)
            }
        }
        return nil
    }

    func perform(arguments: [String: Any]) throws -> [String: Any] {
        let action = (arguments["action"] as? String ?? "focus").lowercased()
        let appName = arguments["app"] as? String ?? arguments["app_name"] as? String ?? ""
        let bundleId = arguments["bundle_id"] as? String ?? ""
        let urlString = arguments["url"] as? String ?? ""

        switch action {
        case "open_url":
            guard !urlString.isEmpty, let url = URL(string: urlString) else {
                throw ServiceClient.ClientError.server("Invalid or missing URL.")
            }
            let opened = NSWorkspace.shared.open(url)
            return ["action": "open_url", "url": urlString, "success": opened]

        case "launch":
            guard !appName.isEmpty || !bundleId.isEmpty else {
                throw ServiceClient.ClientError.server("Specify an app name or bundle ID to launch.")
            }
            guard let appUrl = findAppURL(name: appName, bundleId: bundleId) else {
                throw ServiceClient.ClientError.server("Could not locate application '\(appName.isEmpty ? bundleId : appName)'.")
            }
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.openApplication(at: appUrl, configuration: config, completionHandler: nil)
            return ["action": "launch", "target": appName.isEmpty ? bundleId : appName, "url": appUrl.path, "success": true]

        case "focus", "activate":
            guard !appName.isEmpty else {
                throw ServiceClient.ClientError.server("Specify the application name to focus.")
            }
            let matching = NSWorkspace.shared.runningApplications.filter {
                $0.localizedName?.localizedCaseInsensitiveCompare(appName) == .orderedSame ||
                $0.bundleIdentifier?.localizedCaseInsensitiveCompare(appName) == .orderedSame
            }
            guard let targetApp = matching.first else {
                if let appUrl = findAppURL(name: appName, bundleId: bundleId) {
                    let config = NSWorkspace.OpenConfiguration()
                    config.activates = true
                    NSWorkspace.shared.openApplication(at: appUrl, configuration: config, completionHandler: nil)
                    return ["action": "focus", "app": appName, "launched": true, "success": true]
                }
                throw ServiceClient.ClientError.server("Application '\(appName)' is not running.")
            }
            targetApp.unhide()
            let activated = targetApp.activate()
            return ["action": "focus", "app": appName, "pid": targetApp.processIdentifier, "success": activated]

        case "hide":
            guard !appName.isEmpty else {
                throw ServiceClient.ClientError.server("Specify the application name to hide.")
            }
            let matching = NSWorkspace.shared.runningApplications.filter {
                $0.localizedName?.localizedCaseInsensitiveCompare(appName) == .orderedSame
            }
            guard let targetApp = matching.first else {
                throw ServiceClient.ClientError.server("Application '\(appName)' is not running.")
            }
            let hidden = targetApp.hide()
            return ["action": "hide", "app": appName, "success": hidden]

        case "unhide":
            guard !appName.isEmpty else {
                throw ServiceClient.ClientError.server("Specify the application name to unhide.")
            }
            let matching = NSWorkspace.shared.runningApplications.filter {
                $0.localizedName?.localizedCaseInsensitiveCompare(appName) == .orderedSame
            }
            guard let targetApp = matching.first else {
                throw ServiceClient.ClientError.server("Application '\(appName)' is not running.")
            }
            let unhidden = targetApp.unhide()
            return ["action": "unhide", "app": appName, "success": unhidden]

        case "close", "terminate":
            guard !appName.isEmpty else {
                throw ServiceClient.ClientError.server("Specify the application name to close.")
            }
            let matching = NSWorkspace.shared.runningApplications.filter {
                $0.localizedName?.localizedCaseInsensitiveCompare(appName) == .orderedSame
            }
            guard let targetApp = matching.first else {
                throw ServiceClient.ClientError.server("Application '\(appName)' is not running.")
            }
            let terminated = targetApp.terminate()
            return ["action": "close", "app": appName, "success": terminated]

        default:
            throw ServiceClient.ClientError.server("Unsupported window action: '\(action)'. Supported: focus, hide, unhide, launch, close, open_url.")
        }
    }
}
