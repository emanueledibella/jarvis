import AVFoundation
import CoreAudio
import Foundation

struct AudioInputDevice: Equatable {
  let id: AudioDeviceID
  let uid: String
  let name: String
  var isDefault = false
  var bluetooth = false

  var catalogEntry: [String: Any] {
    ["uid": uid, "name": name, "is_default": isDefault, "bluetooth": bluetooth]
  }
}

enum AudioInputSelection {
  static func resolve(_ uid: String, devices: [AudioInputDevice]) -> AudioInputDevice? {
    // An explicit choice must never fall back to a different microphone.
    uid.isEmpty ? devices.first(where: { $0.isDefault }) : devices.first(where: { $0.uid == uid })
  }
}

struct AudioInputRouteWatch {
  private var key: String?

  mutating func observe(_ uid: String, device: AudioInputDevice?) -> Bool {
    let next = uid + "|" + (device.map { "\($0.id)|\($0.uid)" } ?? "missing")
    let changed = key != nil && key != next
    key = next
    return changed
  }
}

enum AudioInputDevices {
  private static let system = AudioObjectID(kAudioObjectSystemObject)

  private static func integer(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
    var address = AudioObjectPropertyAddress(mSelector: selector,
      mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var value: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    guard AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value) == noErr else { return nil }
    return value
  }

  private static func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var address = AudioObjectPropertyAddress(mSelector: selector,
      mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    // Core Audio returns these CFStrings retained. Transfer ownership to ARC
    // so periodic device checks do not leak names/UIDs.
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value) == noErr else { return nil }
    return value?.takeRetainedValue() as String?
  }

  private static func hasInput(_ device: AudioDeviceID) -> Bool {
    var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
      mScope: kAudioDevicePropertyScopeInput, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr,
      size >= MemoryLayout<AudioBufferList>.size, size < 1_048_576 else { return false }
    let storage = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { storage.deallocate() }
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, storage) == noErr else { return false }
    let buffers = UnsafeMutableAudioBufferListPointer(storage.assumingMemoryBound(to: AudioBufferList.self))
    return buffers.contains { $0.mNumberChannels > 0 }
  }

  static func list() -> [AudioInputDevice] {
    var address = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
      mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &address, 0, nil, &size) == noErr,
      size > 0, size <= 65536 else { return [] }
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(system, &address, 0, nil, &size, &ids) == noErr else { return [] }
    let defaultID = integer(system, kAudioHardwarePropertyDefaultInputDevice)
    return ids.prefix(Int(size) / MemoryLayout<AudioDeviceID>.size).compactMap { id in
      guard integer(id, kAudioDevicePropertyDeviceIsAlive) == 1,
        integer(id, kAudioDevicePropertyIsHidden) != 1, hasInput(id),
        let uid = string(id, kAudioDevicePropertyDeviceUID), !uid.isEmpty, uid.utf8.count <= 512,
        !uid.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
        let name = string(id, kAudioObjectPropertyName), !name.isEmpty else { return nil }
      let transport = integer(id, kAudioDevicePropertyTransportType)
      return AudioInputDevice(id: id, uid: uid, name: String(name.prefix(256)), isDefault: id == defaultID,
        bluetooth: transport == kAudioDeviceTransportTypeBluetooth || transport == kAudioDeviceTransportTypeBluetoothLE)
    }.sorted {
      if $0.isDefault != $1.isDefault { return $0.isDefault }
      return $0.name.localizedStandardCompare($1.name) == .orderedAscending
    }
  }

  static func select(_ device: AudioInputDevice, on input: AVAudioInputNode) throws {
    // Configure this engine's Audio Unit; never change the system default.
    let unit = input.auAudioUnit
    if unit.deviceID != device.id { try unit.setDeviceID(device.id) }
    guard unit.deviceID == device.id else {
      throw NSError(domain: "JarvisAudioInput", code: 1)
    }
  }
}
