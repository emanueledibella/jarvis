import AppKit
import Foundation

// Rasterize the shared vector mark with macOS, without image-generation APIs.
let arguments = CommandLine.arguments
guard arguments.count == 3,
  let image = NSImage(contentsOfFile: arguments[1]),
  let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: 1024, pixelsHigh: 1024,
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
    isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
  let context = NSGraphicsContext(bitmapImageRep: bitmap)
else { fatalError("Usage: swift scripts/render-icon.swift input.svg output.png") }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
context.imageInterpolation = .high
image.draw(in: NSRect(x: 0, y: 0, width: 1024, height: 1024))
NSGraphicsContext.restoreGraphicsState()
guard let data = bitmap.representation(using: .png, properties: [:]) else {
  fatalError("Could not encode the app icon.")
}
try data.write(to: URL(fileURLWithPath: arguments[2]), options: .atomic)
