import AppKit
import ScreenCaptureKit

@MainActor final class ScreenContext: NSObject, SCContentSharingPickerObserver {
    private var continuation: CheckedContinuation<SCContentFilter, Error>?
    private var expiry: Task<Void, Never>?

    func cancel() {
        finish(.failure(ServiceClient.ClientError.server("Screen selection was cancelled.")))
    }

    private func finish(_ result: Result<SCContentFilter, Error>) {
        guard let pending = continuation else { return }
        continuation = nil
        expiry?.cancel()
        expiry = nil
        SCContentSharingPicker.shared.remove(self)
        SCContentSharingPicker.shared.isActive = false
        pending.resume(with: result)
    }

    private func choose() async throws -> SCContentFilter {
        guard continuation == nil else { throw ServiceClient.ClientError.server("A screen selection is already open.") }
        return try await withCheckedThrowingContinuation { pending in
            continuation = pending
            let picker = SCContentSharingPicker.shared
            var configuration = SCContentSharingPickerConfiguration()
            configuration.allowedPickerModes = [.singleWindow]
            configuration.excludedBundleIDs = [Bundle.main.bundleIdentifier ?? "it.jarvis.personal"]
            configuration.allowsChangingSelectedContent = false
            picker.defaultConfiguration = configuration
            picker.maximumStreamCount = 1
            picker.add(self)
            picker.isActive = true
            picker.present(using: .window)
            expiry = Task { [weak self] in
                try? await Task.sleep(nanoseconds: 40_000_000_000)
                if !Task.isCancelled { self?.cancel() }
            }
        }
    }

    func capture(allowed: @escaping @MainActor () -> Bool) async throws -> [String: Any] {
        guard allowed() else { throw ServiceClient.ClientError.server("Screen capture is unavailable while locked or after privacy changes.") }
        let filter = try await choose()
        guard allowed(), filter.style == .window else { throw ServiceClient.ClientError.server("Screen selection authority expired.") }
        let configuration = SCStreamConfiguration()
        let rect = filter.contentRect
        let scale = min(1.0, 1400.0 / max(1.0, max(rect.width, rect.height)))
        configuration.width = max(1, Int(rect.width * scale))
        configuration.height = max(1, Int(rect.height * scale))
        configuration.showsCursor = false
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
        guard allowed() else { throw ServiceClient.ClientError.server("Screen capture discarded after lock or privacy change.") }
        let bitmap = NSBitmapImageRep(cgImage: image)
        var encoded: String?
        for quality in [0.7, 0.45, 0.25] {
            if let data = bitmap.representation(using: .jpeg, properties: [.compressionFactor: quality]), data.count <= 280_000 {
                encoded = data.base64EncodedString()
                break
            }
        }
        guard let encoded else { throw ServiceClient.ClientError.server("Selected window exceeds the capture size limit.") }
        let ocr = try await DocumentOCR.recognize(encoded)
        guard allowed() else { throw ServiceClient.ClientError.server("Screen capture discarded after lock or privacy change.") }
        return ["image": encoded, "text": ocr["text"] ?? "", "confidence": ocr["confidence"] ?? 0,
                "width": image.width, "height": image.height, "source": "owner_selected_window"]
    }

    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        Task { @MainActor [weak self] in self?.cancel() }
    }
    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        Task { @MainActor [weak self] in self?.finish(.success(filter)) }
    }
    nonisolated func contentSharingPickerStartDidFailWithError(_ error: Error) {
        Task { @MainActor [weak self] in self?.finish(.failure(ServiceClient.ClientError.server("The system window picker could not start."))) }
    }
}
