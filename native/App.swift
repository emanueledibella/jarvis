import AppKit
import Carbon
import ServiceManagement
import UserNotifications
import WebKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    var window: NSWindow?
    var webView: WKWebView?
    var statusItem: NSStatusItem!
    var client: ServiceClient!
    var voice: VoiceEngine!
    let calendar = CalendarBridge()
    let hue = HueBluetooth()
    var service: Process?
    var projectRoot = ""
    var dataDirectory = ""
    var terminating = false
    var pollTask: Task<Void, Never>?
    var hotKey: EventHotKeyRef?
    var nativeSettings: [String: Any] = [:]
    var serviceRestarts = 0
    var interfaceLanguage = InterfaceLanguage.configured(UserDefaults.standard.string(forKey: "interfaceLanguage"))
    let interfaceMessages = InterfaceLanguage.messages()
    var webReady = false

    func ui(_ source: String) -> String { interfaceLanguage.text(source, messages: interfaceMessages) }

    func configureInterface(_ value: String?) {
        let next = InterfaceLanguage.configured(value)
        guard next != interfaceLanguage else { return }
        interfaceLanguage = next
        UserDefaults.standard.set(next.rawValue, forKey: "interfaceLanguage")
        buildMenu()
        statusItem.button?.toolTip = ui("Jarvis — personal assistant")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if let icon = Bundle.main.url(forResource: "Jarvis", withExtension: "icns") {
            NSApp.applicationIconImage = NSImage(contentsOf: icon)
        }
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem.button?.image = NSImage(systemSymbolName: "waveform.circle", accessibilityDescription: "Jarvis")
        statusItem.button?.toolTip = ui("Jarvis — personal assistant")
        buildMenu()
        do {
            let resource = Bundle.main.url(forResource: "project-root", withExtension: "txt")!
            projectRoot = try String(contentsOf: resource, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            let helper = Process()
            helper.executableURL = URL(fileURLWithPath: projectRoot + "/.venv/bin/jarvis")
            helper.arguments = ["desktop-info"]
            helper.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
            let pipe = Pipe()
            helper.standardOutput = pipe
            helper.standardError = FileHandle.nullDevice
            try helper.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            helper.waitUntilExit()
            guard let info = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let address = info["url"] as? String, let url = URL(string: address),
                  url.host == "127.0.0.1", let token = info["token"] as? String else {
                throw ServiceClient.ClientError.server("Run scripts/setup.sh to prepare the service.")
            }
            configureInterface(info["ui_language"] as? String)
            dataDirectory = info["data_dir"] as? String ?? ""
            client = ServiceClient(base: url, token: token)
            voice = VoiceEngine(client: client)
            voice.onStateChange = { [weak self] state in
                let name = state == "muted" ? "mic.slash.circle" : state == "speaking" ? "waveform.circle.fill" : "waveform.circle"
                let states = ["armed": "Ready for Jarvis", "muted": "Microphone muted", "speaking": "Speaking", "listening": "Listening", "processing": "Working on it.", "followup": "Ready to continue", "recovering": "Restoring listening."]
                self?.statusItem.button?.image = NSImage(systemSymbolName: name, accessibilityDescription: (self?.ui("Jarvis: ") ?? "Jarvis: ") + (self?.ui(states[state] ?? state) ?? state))
            }
            Task {
                do {
                    _ = try await client.request("/health")
                } catch {
                    startService()
                }
                await poll()
            }
            registerHotkey()
            observeSession()
            if !UserDefaults.standard.bool(forKey: "hasLaunched") || CommandLine.arguments.contains("--show") {
                UserDefaults.standard.set(true, forKey: "hasLaunched")
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.showDashboard() }
            }
        } catch {
            let alert = NSAlert()
            alert.messageText = ui("Jarvis is not ready yet")
            alert.informativeText = ui(error.localizedDescription)
            alert.runModal()
        }
    }

    func buildMenu() {
        let menu = NSMenu()
        let items: [(String, Selector, String)] = [(ui("Open Jarvis"), #selector(showDashboard), "j"), (ui("Talk now"), #selector(listen), ""), (ui("Mute microphone"), #selector(mute), ""), (ui("Unmute microphone"), #selector(unmute), "")]
        for (title, action, key) in items {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.target = self
            menu.addItem(item)
        }
        menu.addItem(.separator())
        let settings = NSMenuItem(title: ui("Launch at login"), action: #selector(toggleAutostart), keyEquivalent: "")
        settings.target = self
        settings.state = SMAppService.mainApp.status == .enabled ? .on : .off
        menu.addItem(settings)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: ui("Quit Jarvis"), action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
    }

    func startService() {
        guard !terminating && service?.isRunning != true else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: projectRoot + "/.venv/bin/jarvis")
        process.arguments = ["serve"]
        process.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
        let logPath = dataDirectory + "/service.log"
        if !FileManager.default.fileExists(atPath: logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil, attributes: [.posixPermissions: 0o600])
        }
        let handle = FileHandle(forWritingAtPath: logPath)
        handle?.seekToEndOfFile()
        process.standardOutput = handle
        process.standardError = handle
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self, !self.terminating else { return }
                self.serviceRestarts += 1
                self.service = nil
                let delay = min(30.0, pow(2.0, Double(min(self.serviceRestarts, 5))))
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { self.startService() }
            }
        }
        do {
            try process.run()
            service = process
        } catch {
            statusItem.button?.toolTip = ui("Jarvis: service startup failed")
        }
    }

    @objc func showDashboard() {
        guard client != nil else { return }
        if window == nil {
            let configuration = WKWebViewConfiguration()
            let encoded = String(data: try! JSONSerialization.data(withJSONObject: [client.token]), encoding: .utf8)!
            let origin = client.base.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            let originJSON = String(data: try! JSONSerialization.data(withJSONObject: [origin]), encoding: .utf8)!
            let source = "if (location.origin === \(originJSON)[0]) { window.__JARVIS_TOKEN__ = \(encoded)[0]; window.__JARVIS_NATIVE__ = true; }"
            configuration.userContentController.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
            let view = WKWebView(frame: .zero, configuration: configuration)
            view.navigationDelegate = self
            view.setValue(false, forKey: "drawsBackground")
            let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1400, height: 900)
            let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: min(1320, screen.width * 0.92), height: min(840, screen.height * 0.92)), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            win.title = "Jarvis"
            win.minSize = NSSize(width: 800, height: 600)
            win.isReleasedWhenClosed = false
            win.delegate = self
            win.contentView = view
            win.appearance = NSAppearance(named: .darkAqua)
            win.center()
            webView = view
            window = win
            Task {
                do {
                    _ = try await client.authenticateService()
                    view.load(URLRequest(url: client.base))
                } catch {
                    statusItem.button?.toolTip = ui("Jarvis: local service verification failed")
                }
            }
        }
        NSApp.setActivationPolicy(.regular)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil)
        NSApp.setActivationPolicy(.accessory)
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showDashboard()
        return true
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { webReady = true }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { webReady = false }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.host == client.base.host && url.port == client.base.port && url.scheme == "http" {
            decisionHandler(.allow)
        } else {
            if navigationAction.navigationType == .linkActivated && ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func poll() async {
        var sequence = -1
        var failures = 0
        while !terminating {
            do {
                let result = try await client.request("/api/native/poll?after=\(sequence)")
                sequence = max(sequence, result["cursor"] as? Int ?? 0)
                if let settings = result["settings"] as? [String: Any] {
                    nativeSettings = settings
                    configureInterface(settings["ui_language"] as? String)
                    voice.configure(settings)
                    hue.configure(enabled: settings["lighting_enabled"] as? Bool ?? false)
                }
                for event in result["events"] as? [[String: Any]] ?? [] {
                    sequence = max(sequence, event["sequence"] as? Int ?? 0)
                    let data = event["data"] as? [String: Any] ?? [:]
                    switch event["type"] as? String {
                    case "native.operation":
                        Task { await performNative(data) }
                    case "speech.requested":
                        if data["channel"] as? String != "phone", let text = data["text"] as? String { voice.speak(text) }
                    case "speech.stop": voice.stopSpeaking()
                    case "task.updated":
                        if let id = event["task_id"] as? String, let state = data["state"] as? String { voice.taskChanged(id, state: state) }
                    case "notification.created":
                        await notify(title: data["title"] as? String ?? "Jarvis")
                    case "settings.updated": break
                    default: break
                    }
                }
                voice.statusHeartbeat()
                if !webReady && window?.isVisible == true { webView?.load(URLRequest(url: client.base)) }
                serviceRestarts = 0
                failures = 0
            } catch {
                failures += 1
                if failures > 2 { statusItem.button?.toolTip = ui("Jarvis: reconnecting to the service") }
                if failures == 3 { startService() }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }
    }

    func performNative(_ data: [String: Any]) async {
        guard let key = data["id"] as? String else { return }
        // Claim once and retrieve authoritative arguments immediately before an OS action.
        guard let authority = try? await client.request("/api/native/claim/" + key, method: "POST"),
              let operation = authority["operation"] as? String else { return }
        let arguments = authority["arguments"] as? [String: Any] ?? [:]
        var result: [String: Any]
        do {
            switch operation {
            case "control.enable":
                result = await voice.authorize()
                if result["state"] as? String != "permission_required" {
                    _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
                }
            case "control.mute": voice.mute(); result = ["state": "muted"]
            case "control.unmute": try voice.unmute(); result = ["state": "armed"]
            case "control.recover_wake":
                result = voice.recoverWake(expectedCallbacks: arguments["recognition_callbacks"] as? Int ?? -1,
                                           expectedWakeMatches: arguments["wake_matches"] as? Int ?? -1)
            case "control.listen":
                if let privacy = arguments["private"] as? Bool, let scope = arguments["scope"] as? String { voice.setSession(privateMode: privacy, scope: scope) }
                try voice.listen(); result = ["state": "listening"]
            case "control.session":
                voice.setSession(privateMode: arguments["private"] as? Bool ?? false, scope: arguments["scope"] as? String ?? "personal")
                result = ["state":"updated"]
            case "control.stop": voice.stopSpeaking(); hue.shutdown(); result = ["state": "stopped"]
            case "hue.scan", "hue.inspect", "hue.read", "hue.write": result = try await hue.perform(operation, arguments)
            case "control.calendar_authorize": result = try await calendar.authorize()
            case "control.autostart_enable": result = try enableAutostart()
            case "control.autostart_disable": try await SMAppService.mainApp.unregister(); buildMenu(); result = ["state": "disabled"]
            default:
                if operation.hasPrefix("calendar.") { result = try calendar.perform(operation, arguments) }
                else { throw ServiceClient.ClientError.server("Native action is not allowed.") }
            }
        } catch { result = ["error": error.localizedDescription] }
        _ = try? await client.request("/api/native/result/" + key, method: "POST", body: result)
    }

    func notify(title: String) async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard settings.authorizationStatus == .authorized else { return }
        let content = UNMutableNotificationContent()
        content.title = ui("Jarvis — result ready")
        content.body = ui("Open Jarvis to see the result.")
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        try? await UNUserNotificationCenter.current().add(request)
    }

    func observeSession() {
        let center = NSWorkspace.shared.notificationCenter
        center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.voice.restartCapture() }
        }
        DistributedNotificationCenter.default().addObserver(forName: NSNotification.Name("com.apple.screenIsLocked"), object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.voice.setLocked(true) }
        }
        DistributedNotificationCenter.default().addObserver(forName: NSNotification.Name("com.apple.screenIsUnlocked"), object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.voice.setLocked(false) }
        }
    }

    func registerHotkey() {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            guard let userData = userData else { return noErr }
            let delegate = Unmanaged<AppDelegate>.fromOpaque(userData).takeUnretainedValue()
            Task { @MainActor in try? delegate.voice?.listen() }
            return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), nil)
        RegisterEventHotKey(UInt32(kVK_ANSI_J), UInt32(cmdKey | shiftKey), EventHotKeyID(signature: 0x4A525653, id: 1), GetApplicationEventTarget(), 0, &hotKey)
    }

    @objc func listen() { try? voice?.listen() }
    @objc func mute() { voice?.mute() }
    @objc func unmute() { try? voice?.unmute() }
    @objc func toggleAutostart() {
        Task {
            do {
                if SMAppService.mainApp.status == .enabled { try await SMAppService.mainApp.unregister() }
                else { _ = try enableAutostart() }
                buildMenu()
            } catch {
                let alert = NSAlert()
                alert.messageText = ui("Launch at login requires approval")
                alert.informativeText = ui("Check System Settings → General → Login Items.")
                alert.runModal()
            }
        }
    }
    func enableAutostart() throws -> [String: Any] {
        if SMAppService.mainApp.status != .enabled && SMAppService.mainApp.status != .requiresApproval {
            do { try SMAppService.mainApp.register() }
            catch { if SMAppService.mainApp.status != .requiresApproval { throw error } }
        }
        buildMenu()
        if SMAppService.mainApp.status == .requiresApproval {
            SMAppService.openSystemSettingsLoginItems()
            return ["state":"requires_approval"]
        }
        return ["state":SMAppService.mainApp.status == .enabled ? "enabled" : "not_registered"]
    }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) {
        terminating = true
        voice?.shutdown()
        hue.shutdown()
        if let process = service, process.isRunning { process.terminate() }
    }
}

@main
struct JarvisApplication {
    @MainActor static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
