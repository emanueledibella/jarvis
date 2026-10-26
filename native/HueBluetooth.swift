@preconcurrency import CoreBluetooth
import Foundation

@MainActor
final class HueBluetooth: NSObject, @preconcurrency CBCentralManagerDelegate, @preconcurrency CBPeripheralDelegate {
  private typealias Failure = HueLightProtocol.Failure
  private var central: CBCentralManager?
  private var discovered: [UUID: CBPeripheral] = [:]
  private var current: CBPeripheral?
  private var characteristics: [String: CBCharacteristic] = [:]
  private var busy = false
  private var enabled = false
  private var phase = ""
  private var expected = ""
  private var stepID = UUID()
  private var timer: Task<Void, Never>?
  private var waiter: CheckedContinuation<Data, Error>?

  func perform(_ operation: String, _ arguments: [String: Any]) async throws -> [String: Any] {
    guard enabled else { throw Failure.unavailable }
    guard !busy else { throw Failure.busy }
    guard ["hue.scan", "hue.inspect", "hue.read", "hue.write"].contains(operation) else { throw Failure.invalid }
    busy = true
    defer { busy = false }
    if central == nil {
      central = CBCentralManager(delegate: self, queue: .main,
        options: [CBCentralManagerOptionShowPowerAlertKey: false])
    }
    try await poweredOn()
    if operation == "hue.scan" {
      discovered.removeAll()
      central!.scanForPeripherals(withServices: [CBUUID(string: HueLightProtocol.advertised), CBUUID(string: HueLightProtocol.service)],
        options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
      defer { central?.stopScan() }
      try await Task.sleep(nanoseconds: 8_000_000_000)
      guard enabled, central?.state == .poweredOn else { throw Failure.unavailable }
      return ["lights": discovered.values.map { ["id": $0.identifier.uuidString, "name": $0.name ?? "Hue light"] }]
    }
    guard let value = arguments["device_id"] as? String, let id = UUID(uuidString: value),
      let peripheral = discovered[id] ?? central!.retrievePeripherals(withIdentifiers: [id]).first else { throw Failure.unreachable }
    current = peripheral
    peripheral.delegate = self
    characteristics.removeAll()
    do {
      if peripheral.state != .connected {
        _ = try await step("connect", seconds: 10) { self.central!.connect(peripheral) }
      }
      _ = try await step("services", seconds: 5) {
        peripheral.discoverServices([CBUUID(string: HueLightProtocol.service)])
      }
      guard let service = peripheral.services?.first(where: { $0.uuid == CBUUID(string: HueLightProtocol.service) }) else { throw Failure.unsupported }
      _ = try await step("characteristics", expected: service.uuid.uuidString, seconds: 5) {
        peripheral.discoverCharacteristics(nil, for: service)
      }
      guard let power = characteristics[HueLightProtocol.power], power.properties.contains(.read), power.properties.contains(.write) else { throw Failure.unsupported }
      // The encrypted power read lets CoreBluetooth request legitimate bonding.
      // Never reset the lamp or alter the phone's bond to make this succeed.
      let until = Date().addingTimeInterval(operation == "hue.inspect" ? 35 : 2)
      while true {
        do { _ = try await read(HueLightProtocol.power); break }
        catch Failure.pairing {
          guard operation == "hue.inspect", Date() < until else { throw Failure.pairing }
          try await Task.sleep(nanoseconds: 1_000_000_000)
        }
      }
      if operation == "hue.write" {
        guard let changes = arguments["changes"] as? [String: Any] else { throw Failure.invalid }
        let fields = try HueLightProtocol.commands(changes)
        for field in fields {
          guard characteristics[field.uuid]?.properties.contains(.write) == true else { throw Failure.unsupported }
        }
        if characteristics[HueLightProtocol.combined]?.properties.contains(.write) == true {
          try await write(HueLightProtocol.combined, HueLightProtocol.packet(fields))
        } else {
          // Configure before powering on; power-off goes first. No flash effects.
          let ordered = fields.sorted { left, right in
            func priority(_ field: (uuid: String, tag: UInt8, data: Data)) -> Int {
              field.uuid == HueLightProtocol.power ? (field.data.first == 0 ? 0 : 2) : 1
            }
            return priority(left) < priority(right)
          }
          for field in ordered { try await write(field.uuid, field.data) }
        }
      }
      let light = try await state()
      let result: [String: Any] = ["light": light, "capabilities": capabilities()]
      await disconnect()
      return result
    } catch {
      await disconnect()
      throw error
    }
  }

  private func poweredOn() async throws {
    if central?.state == .poweredOn { return }
    if central?.state == .unauthorized { throw Failure.permission }
    if central?.state == .poweredOff || central?.state == .unsupported { throw Failure.unavailable }
    _ = try await step("power", seconds: 35) {}
    guard central?.state == .poweredOn else { throw Failure.unavailable }
  }

  private func step(_ phase: String, expected: String = "", seconds: Double,
                    start: () -> Void) async throws -> Data {
    let id = UUID()
    return try await withTaskCancellationHandler {
      try await withCheckedThrowingContinuation { continuation in
        self.phase = phase
        self.expected = expected
        self.stepID = id
        self.waiter = continuation
        self.timer = Task { [weak self] in
          do { try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) } catch { return }
          guard let self = self, self.stepID == id else { return }
          self.finish(.failure(Failure.timeout))
        }
        start()
      }
    } onCancel: { [weak self] in
      Task { @MainActor in
        guard let self = self, self.stepID == id else { return }
        self.finish(.failure(CancellationError()))
      }
    }
  }

  private func finish(_ result: Result<Data, Error>) {
    timer?.cancel()
    timer = nil
    let continuation = waiter
    waiter = nil
    phase = ""
    expected = ""
    continuation?.resume(with: result)
  }

  private func read(_ uuid: String) async throws -> Data {
    guard let peripheral = current, let characteristic = characteristics[uuid],
      characteristic.properties.contains(.read) else { throw Failure.unsupported }
    return try await step("read", expected: uuid, seconds: 8) { peripheral.readValue(for: characteristic) }
  }

  private func write(_ uuid: String, _ data: Data) async throws {
    guard enabled, let peripheral = current, let characteristic = characteristics[uuid],
      characteristic.properties.contains(.write) else { throw Failure.unsupported }
    _ = try await step("write", expected: uuid, seconds: 8) {
      peripheral.writeValue(data, for: characteristic, type: .withResponse)
    }
  }

  private func capabilities() -> [String: Bool] {
    let mapping = ["on": HueLightProtocol.power, "brightness": HueLightProtocol.brightness,
                   "temperature_kelvin": HueLightProtocol.temperature, "color": HueLightProtocol.color]
    return mapping.mapValues { characteristics[$0]?.properties.contains(.write) == true && characteristics[$0]?.properties.contains(.read) == true }
  }

  private func state() async throws -> [String: Any] {
    let power = try await read(HueLightProtocol.power)
    guard power.count == 1, power.first == 0 || power.first == 1 else { throw Failure.unsupported }
    var result: [String: Any] = ["on": power.first == 1]
    if characteristics[HueLightProtocol.brightness]?.properties.contains(.read) == true {
      let data = try await read(HueLightProtocol.brightness)
      if data.count == 1, let value = data.first, value > 0, value <= 254 {
        result["brightness"] = Int((Double(value) * 100 / 254).rounded())
      }
    }
    if characteristics[HueLightProtocol.temperature]?.properties.contains(.read) == true {
      if let mireds = HueLightProtocol.unsigned(try await read(HueLightProtocol.temperature)), (153...500).contains(mireds) {
        result["temperature_kelvin"] = Int((1_000_000 / Double(mireds)).rounded())
      }
    }
    if characteristics[HueLightProtocol.color]?.properties.contains(.read) == true {
      let data = try await read(HueLightProtocol.color)
      if let x = HueLightProtocol.unsigned(data), let y = HueLightProtocol.unsigned(data, offset: 2), x != 65535 || y != 65535 {
        result["xy"] = [Double(x) / 65535, Double(y) / 65535]
      }
    }
    return result
  }

  private func disconnect() async {
    guard let peripheral = current else { return }
    if peripheral.state != .disconnected {
      _ = try? await step("disconnect", seconds: 3) { self.central?.cancelPeripheralConnection(peripheral) }
    }
    peripheral.delegate = nil
    current = nil
    characteristics.removeAll()
  }

  func shutdown() {
    central?.stopScan()
    finish(.failure(CancellationError()))
    if let current = current { central?.cancelPeripheralConnection(current) }
  }

  func configure(enabled: Bool) {
    self.enabled = enabled
    if !enabled { shutdown() }
  }

  func centralManagerDidUpdateState(_ central: CBCentralManager) {
    if phase == "power", central.state == .poweredOn { finish(.success(Data())) }
    else if central.state == .unauthorized { finish(.failure(Failure.permission)) }
    else if central.state == .poweredOff || central.state == .unsupported { finish(.failure(Failure.unavailable)) }
  }

  func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                      advertisementData: [String: Any], rssi RSSI: NSNumber) {
    let advertised = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []
    let serviceData = advertisementData[CBAdvertisementDataServiceDataKey] as? [CBUUID: Data] ?? [:]
    let overflow = advertisementData[CBAdvertisementDataOverflowServiceUUIDsKey] as? [CBUUID] ?? []
    let signatures = Set(advertised + overflow + Array(serviceData.keys))
    if central.isScanning, discovered.count < 30,
      signatures.contains(CBUUID(string: HueLightProtocol.advertised)) || signatures.contains(CBUUID(string: HueLightProtocol.service)) {
      discovered[peripheral.identifier] = peripheral
    }
  }

  func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
    if current === peripheral && phase == "connect" { finish(.success(Data())) }
  }

  func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
    if current === peripheral { finish(.failure(Failure.unreachable)) }
  }

  func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
    if current === peripheral { finish(phase == "disconnect" ? .success(Data()) : .failure(Failure.unreachable)) }
  }

  func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
    if current === peripheral && phase == "services" {
      finish(error == nil ? .success(Data()) : .failure(Failure.unsupported))
    }
  }

  func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
    guard current === peripheral, phase == "characteristics", expected == service.uuid.uuidString else { return }
    for value in service.characteristics ?? [] { characteristics[value.uuid.uuidString] = value }
    finish(error == nil ? .success(Data()) : .failure(Failure.unsupported))
  }

  func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
    guard current === peripheral, phase == "read", expected == characteristic.uuid.uuidString else { return }
    if let error = error as NSError? {
      let auth = error.domain == CBATTErrorDomain && [5, 15].contains(error.code)
      finish(.failure(auth ? Failure.pairing : Failure.unreachable))
    } else if let value = characteristic.value { finish(.success(value)) }
    else { finish(.failure(Failure.unsupported)) }
  }

  func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
    guard current === peripheral, phase == "write", expected == characteristic.uuid.uuidString else { return }
    finish(error == nil ? .success(Data()) : .failure(Failure.unreachable))
  }
}
