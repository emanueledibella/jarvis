import AppKit
import Foundation

@main struct DocumentOCRTests {
    static func main() async throws {
        do {
            _ = try await DocumentOCR.recognize("invalid")
            fatalError("Invalid OCR bytes were accepted")
        } catch {}
        let image = NSImage(size: NSSize(width: 800, height: 200))
        image.lockFocus()
        NSColor.white.setFill()
        NSRect(x: 0, y: 0, width: 800, height: 200).fill()
        ("HELLO JARVIS" as NSString).draw(at: NSPoint(x: 30, y: 70), withAttributes: [.font: NSFont.systemFont(ofSize: 64), .foregroundColor: NSColor.black])
        image.unlockFocus()
        let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
        let data = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.85])!
        let result = try await DocumentOCR.recognize(data.base64EncodedString())
        guard (result["text"] as? String ?? "").contains("JARVIS") else { fatalError("Synthetic OCR text not recognized") }
        print("2 document OCR scenarios passed")
    }
}
