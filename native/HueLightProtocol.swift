import Foundation
import CoreFoundation

// Fixed Hue lighting characteristics only. Device reset, radio configuration,
// firmware, alarms, and arbitrary GATT operations are deliberately absent.
enum HueLightProtocol {
  static let service = "932C32BD-0000-47A2-835A-A8D455B859DD"
  static let advertised = "FE0F"
  static let power = "932C32BD-0002-47A2-835A-A8D455B859DD"
  static let brightness = "932C32BD-0003-47A2-835A-A8D455B859DD"
  static let temperature = "932C32BD-0004-47A2-835A-A8D455B859DD"
  static let color = "932C32BD-0005-47A2-835A-A8D455B859DD"
  static let combined = "932C32BD-0007-47A2-835A-A8D455B859DD"
  static let readable = [power, brightness, temperature, color]

  static func word(_ value: Int) -> Data {
    Data([UInt8(value & 255), UInt8((value >> 8) & 255)])
  }

  static func unsigned(_ data: Data, offset: Int = 0) -> Int? {
    let bytes = [UInt8](data)
    guard offset >= 0, bytes.count >= offset + 2 else { return nil }
    return Int(bytes[offset]) | (Int(bytes[offset + 1]) << 8)
  }

  static func xy(_ hex: String) throws -> (Double, Double) {
    guard hex.count == 7, hex.first == "#", let value = UInt32(hex.dropFirst(), radix: 16) else {
      throw Failure.invalid
    }
    let components = [Int((value >> 16) & 255), Int((value >> 8) & 255), Int(value & 255)].map { channel -> Double in
      let c = Double(channel) / 255
      return c > 0.04045 ? pow((c + 0.055) / 1.055, 2.4) : c / 12.92
    }
    let r = components[0], g = components[1], b = components[2]
    let x = r * 0.664511 + g * 0.154324 + b * 0.162028
    let y = r * 0.283881 + g * 0.668433 + b * 0.047685
    let z = r * 0.000088 + g * 0.072310 + b * 0.986039
    guard x + y + z > 0 else { throw Failure.invalid }
    return (x / (x + y + z), y / (x + y + z))
  }

  static func commands(_ changes: [String: Any]) throws -> [(uuid: String, tag: UInt8, data: Data)] {
    guard !changes.isEmpty, Set(changes.keys).isSubset(of: ["on", "brightness", "temperature_kelvin", "color"]),
      !(changes["color"] != nil && changes["temperature_kelvin"] != nil) else { throw Failure.invalid }
    var fields: [(String, UInt8, Data)] = []
    if let value = changes["on"] {
      guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { throw Failure.invalid }
      fields.append((power, 1, Data([number.boolValue ? 1 : 0])))
    }
    if let value = changes["brightness"] {
      let percent = try integer(value, lower: 1, upper: 100)
      fields.append((brightness, 2, Data([UInt8(max(1, Int((Double(percent) * 254 / 100).rounded())))])))
    }
    if let value = changes["temperature_kelvin"] {
      let kelvin = try integer(value, lower: 2000, upper: 6500)
      fields.append((temperature, 3, word(Int((1_000_000 / Double(kelvin)).rounded()))))
    }
    if let value = changes["color"] {
      guard let hex = value as? String else { throw Failure.invalid }
      let point = try xy(hex)
      fields.append((color, 4, word(Int((point.0 * 65535).rounded())) + word(Int((point.1 * 65535).rounded()))))
    }
    return fields
  }

  static func integer(_ value: Any, lower: Int, upper: Int) throws -> Int {
    guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
      n.doubleValue.isFinite, n.doubleValue == Double(n.intValue),
      (lower...upper).contains(n.intValue) else { throw Failure.invalid }
    return n.intValue
  }

  static func packet(_ fields: [(uuid: String, tag: UInt8, data: Data)]) -> Data {
    fields.reduce(into: Data()) { packet, field in
      packet.append(field.tag)
      packet.append(UInt8(field.data.count))
      packet.append(field.data)
    }
  }

  enum Failure: LocalizedError {
    case invalid, unavailable, permission, busy, unreachable, pairing, unsupported, timeout
    var errorDescription: String? {
      switch self {
      case .invalid: return "Invalid lighting command."
      case .unavailable: return "Turn on Bluetooth on the Mac to connect a light."
      case .permission: return "Allow Jarvis Bluetooth access in System Settings → Privacy & Security → Bluetooth."
      case .busy: return "Bluetooth lighting is busy. Wait for the current operation to finish."
      case .unreachable: return "The light is unreachable. Keep it powered and near the Mac; close the Hue app on the phone and try again."
      case .pairing: return "Bluetooth pairing was not confirmed. Allow the macOS pairing request and make the lamp discoverable."
      case .unsupported: return "The selected device does not expose supported Hue lighting controls."
      case .timeout: return "The light did not respond in time. Read its state before repeating a change."
      }
    }
  }
}
