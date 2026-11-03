import Foundation
import Vision
import ImageIO

enum DocumentOCR {
    static func recognize(_ encoded: String) async throws -> [String: Any] {
        guard encoded.utf8.count <= 400_000, let data = Data(base64Encoded: encoded),
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              image.width * image.height <= 4_000_000 else {
            throw ServiceClient.ClientError.server("Invalid or oversized OCR image.")
        }
        return try await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.recognitionLanguages = ["it-IT", "en-US"]
            request.usesLanguageCorrection = true
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
            let candidates = Array((request.results ?? []).prefix(1000)).compactMap { $0.topCandidates(1).first }
            let text = String(candidates.map(\.string).joined(separator: "\n").prefix(50_000))
            let confidence = candidates.isEmpty ? 0 : candidates.reduce(0.0) { $0 + Double($1.confidence) } / Double(candidates.count)
            return ["text": text, "confidence": confidence, "method": "apple_vision_ocr"]
        }.value
    }
}
