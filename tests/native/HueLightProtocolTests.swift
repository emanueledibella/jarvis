import Foundation

@main
struct HueLightProtocolTests {
  static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { fatalError(message) }
  }

  static func rejected(_ changes: [String: Any]) -> Bool {
    do { _ = try HueLightProtocol.commands(changes); return false }
    catch { return true }
  }

  static func main() throws {
    let on = try HueLightProtocol.commands(["on": true])
    expect(on[0].uuid == HueLightProtocol.power && on[0].data == Data([1]), "Power uses the fixed Hue power characteristic")
    let off = try HueLightProtocol.commands(["on": false])
    expect(off[0].data == Data([0]), "Off has an explicit, absolute wire value")
    let dim = try HueLightProtocol.commands(["brightness": 50])
    expect(dim[0].data == Data([127]), "Percent brightness maps to the Hue 1–254 range")
    let white = try HueLightProtocol.commands(["temperature_kelvin": 4000])
    expect(white[0].data == Data([250, 0]), "Kelvin becomes little-endian mireds")
    let combined = HueLightProtocol.packet(on + dim + white)
    expect(combined == Data([1,1,1,2,1,127,3,2,250,0]), "Combined changes use typed TLV fields without exposing raw GATT access")
    let red = try HueLightProtocol.xy("#FF0000")
    expect(abs(red.0 - 0.700606) < 0.00001 && abs(red.1 - 0.299301) < 0.00001, "RGB conversion uses linear-light XY coordinates")
    expect(HueLightProtocol.unsigned(Data([0x34, 0x12])) == 0x1234, "Readback preserves little-endian state")
    expect(HueLightProtocol.unsigned(Data([0x34])) == nil, "Short state packets are rejected")
    expect(rejected(["brightness": true]), "Boolean input is not a brightness number")
    expect(rejected(["on": 1]), "Numeric input is not a power boolean")
    expect(rejected(["brightness": 0]), "Zero is normalized to power-off by the host, never written as an unsupported dim level")
    expect(rejected(["brightness": 101]), "Brightness cannot exceed the light's range")
    expect(rejected(["brightness": 0.5]), "Fractional command values are rejected")
    expect(rejected(["temperature_kelvin": 100]), "Invalid white temperatures cannot reach the radio")
    expect(rejected(["color": "red"]), "Colors must use a validated wire-independent format")
    expect(rejected(["color": "#000000"]), "Black cannot produce undefined XY coordinates")
    expect(rejected(["reset": true]), "Factory reset is not an allowed lighting operation")
    expect(rejected(["color": "#FFFFFF", "temperature_kelvin": 2700]), "Color modes cannot conflict")
    print("18 native Hue protocol scenarios passed")
  }
}
