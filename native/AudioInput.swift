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
  static func isSelectable(uid: String, aggregate: Bool) -> Bool {
    !aggregate && !uid.hasPrefix("CADefaultDeviceAggregate-")
      && !uid.hasPrefix("VPAUAggregateAudioDevice")
  }
  static func resolve(_ uid: String, devices: [AudioInputDevice]) -> AudioInputDevice? {
    // An explicit choice must never fall back to a different microphone.
    uid.isEmpty ? devices.first(where: { $0.isDefault }) : devices.first(where: { $0.uid == uid })
  }

  static func needsIndependentCapture(_ uid: String, device: AudioInputDevice) -> Bool {
    !uid.isEmpty && !device.isDefault
  }
}

struct AudioInputRouteWatch {
  private var key: String?

  mutating func observe(_ uid: String, device: AudioInputDevice?) -> Bool {
    let next = uid + "|" + (device.map { "\($0.id)|\($0.uid)|\($0.isDefault)" } ?? "missing")
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
    var streams = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreams,
      mScope: kAudioDevicePropertyScopeInput, mElement: kAudioObjectPropertyElementMain)
    var streamSize: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &streams, 0, nil, &streamSize) == noErr,
      streamSize > 0 else { return false }
    var address = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
      mScope: kAudioDevicePropertyScopeInput, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr,
      size >= MemoryLayout<AudioBufferList>.size, size < 1_048_576 else { return false }
    let storage = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
    defer { storage.deallocate() }
    let capacity = Int(size)
    storage.initializeMemory(as: UInt8.self, repeating: 0, count: capacity)
    guard AudioObjectGetPropertyData(device, &address, 0, nil, &size, storage) == noErr else { return false }
    let list = storage.assumingMemoryBound(to: AudioBufferList.self)
    let header = MemoryLayout<AudioBufferList>.size - MemoryLayout<AudioBuffer>.size
    guard Int(size) <= capacity, Int(size) >= header,
      Int(list.pointee.mNumberBuffers) <= (Int(size) - header) / MemoryLayout<AudioBuffer>.stride else { return false }
    let buffers = UnsafeMutableAudioBufferListPointer(list)
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
    // AVCapture exposes real selectable inputs, excluding private I/O
    // aggregates that an audio engine creates and destroys for processing.
    let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.microphone, .external],
      mediaType: .audio, position: .unspecified)
    let captureUIDs = Set(discovery.devices.map { $0.uniqueID })
    return ids.prefix(Int(size) / MemoryLayout<AudioDeviceID>.size).compactMap { id in
      let transport = integer(id, kAudioDevicePropertyTransportType)
      guard integer(id, kAudioDevicePropertyDeviceIsAlive) == 1,
        integer(id, kAudioDevicePropertyIsHidden) != 1, hasInput(id),
        let uid = string(id, kAudioDevicePropertyDeviceUID), captureUIDs.contains(uid),
        AudioInputSelection.isSelectable(uid: uid, aggregate: transport == kAudioDeviceTransportTypeAggregate),
        !uid.isEmpty, uid.utf8.count <= 512,
        !uid.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
        let name = string(id, kAudioObjectPropertyName), !name.isEmpty else { return nil }
      return AudioInputDevice(id: id, uid: uid, name: String(name.prefix(256)), isDefault: id == defaultID,
        bluetooth: transport == kAudioDeviceTransportTypeBluetooth || transport == kAudioDeviceTransportTypeBluetoothLE)
    }.sorted {
      if $0.isDefault != $1.isDefault { return $0.isDefault }
      return $0.name.localizedStandardCompare($1.name) == .orderedAscending
    }
  }

}
