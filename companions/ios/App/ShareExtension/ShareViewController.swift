import UIKit
import Social
import UniformTypeIdentifiers

final class ShareViewController: SLComposeServiceViewController {
    override func viewDidLoad() {
        super.viewDidLoad()
        title = "Salva in Jarvis"
        navigationItem.rightBarButtonItem?.title = "Salva"
        placeholder = "Apri Jarvis per scegliere conversazione e privacy prima dell’invio."
    }
    override func isContentValid() -> Bool { (contentText ?? "").utf8.count <= 100_000 }
    override func didSelectPost() {
        Task { @MainActor in
            do {
                guard let group = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.it.jarvis.companion") else { throw CocoaError(.fileNoSuchFile) }
                var directory = group.appendingPathComponent("SharedInbox", isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                    attributes: [.protectionKey: FileProtectionType.complete])
                var resource = URLResourceValues(); resource.isExcludedFromBackup = true
                try directory.setResourceValues(resource)
                for url in (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [] {
                    let date = try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
                    if Date().timeIntervalSince(date ?? .distantPast) > 900 { try? FileManager.default.removeItem(at: url) }
                }
                var values: [[String: Any]] = []
                let text = contentText ?? ""
                if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { values.append(["text": text]) }
                let items = extensionContext?.inputItems as? [NSExtensionItem] ?? []
                let providers = items.flatMap { $0.attachments ?? [] }.prefix(5)
                for provider in providers where values.count < 5 {
                    if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                        let url: URL? = await withCheckedContinuation { continuation in
                            provider.loadItem(forTypeIdentifier: UTType.url.identifier) { value, _ in continuation.resume(returning: value as? URL) }
                        }
                        if let url, ["http", "https"].contains(url.scheme ?? ""), url.absoluteString.count <= 8192 { values.append(["text": url.absoluteString]) }
                        continue
                    }
                    let types: [(UTType, String)] = [(.pdf, "pdf"), (.png, "png"), (.jpeg, "jpg"), (UTType("org.openxmlformats.wordprocessingml.document") ?? .data, "docx"), (.plainText, "txt")]
                    guard let (type, suffix) = types.first(where: { provider.hasItemConformingToTypeIdentifier($0.0.identifier) }) else { continue }
                    let value: [String: Any]? = await withCheckedContinuation { continuation in
                        provider.loadFileRepresentation(forTypeIdentifier: type.identifier) { url, _ in
                            guard let url, let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
                                  size > 0, size <= 3_000_000, let data = try? Data(contentsOf: url), data.count <= 3_000_000 else { continuation.resume(returning: nil); return }
                            let proposed = provider.suggestedName ?? "document"
                            let basename = String(proposed.filter { $0 != "/" && $0 != "\\" && !$0.isNewline }.prefix(100))
                            let name = basename.lowercased().hasSuffix("." + suffix) ? basename : basename + "." + suffix
                            continuation.resume(returning: ["name": name, "content": data.base64EncodedString()])
                        }
                    }
                    if let value { values.append(value) }
                }
                let existing = (try? FileManager.default.contentsOfDirectory(atPath: directory.path).count) ?? 0
                guard !values.isEmpty, existing + values.count <= 5 else { throw CocoaError(.fileWriteOutOfSpace) }
                for var value in values {
                    let id = UUID().uuidString.lowercased()
                    value["id"] = id; value["created"] = Date().timeIntervalSince1970 * 1000
                    try JSONSerialization.data(withJSONObject: value).write(to: directory.appendingPathComponent(id + ".json"), options: [.atomic, .completeFileProtection])
                }
                extensionContext?.completeRequest(returningItems: nil)
            } catch { extensionContext?.cancelRequest(withError: NSError(domain: "JarvisShare", code: 1, userInfo: [NSLocalizedDescriptionKey: "Condivisione non salvata. Apri Jarvis e libera le fonti in attesa; sono consentiti cinque elementi di massimo 3 MB."])) }
        }
    }
}
