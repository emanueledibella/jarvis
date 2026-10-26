import Foundation

@main
struct AudioInputTests {
  static var checks = 0
  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    if !condition() { fatalError(message) }
  }
  static func main() {
    var builtIn = AudioInputDevice(id: 1, uid: "fixture-built-in", name: "Fixture microphone")
    var headset = AudioInputDevice(id: 2, uid: "fixture-headset", name: "Fixture headset", isDefault: true, bluetooth: true)
    expect(AudioInputSelection.resolve("", devices: [builtIn, headset]) == headset, "Follow the default input")
    expect(AudioInputSelection.resolve(builtIn.uid, devices: [headset, builtIn]) == builtIn, "An explicit choice overrides the system default locally")
    expect(AudioInputSelection.resolve(headset.uid, devices: [headset, builtIn]) == headset, "Bluetooth inputs remain selectable")
    expect(AudioInputSelection.resolve(builtIn.uid, devices: [headset]) == nil, "A missing pinned microphone must not fall back to another device")
    expect(AudioInputSelection.resolve("", devices: []) == nil, "No input is a valid unavailable state")
    expect(AudioInputSelection.resolve("", devices: [builtIn]) == nil, "An unmarked device cannot silently become the default")
    expect(AudioInputSelection.resolve("FIXTURE-BUILT-IN", devices: [builtIn]) == nil, "UID matching is exact")
    let duplicate = AudioInputDevice(id: 3, uid: "fixture-other", name: builtIn.name)
    expect(AudioInputSelection.resolve(builtIn.uid, devices: [duplicate, builtIn]) == builtIn, "Names do not identify a microphone")

    var watch = AudioInputRouteWatch()
    expect(!watch.observe("", device: headset), "Initial enumeration is not a route change")
    expect(!watch.observe("", device: headset), "Stable default does not restart capture")
    headset.isDefault = false
    builtIn.isDefault = true
    expect(watch.observe("", device: builtIn), "Following default responds to a route change")
    expect(watch.observe(builtIn.uid, device: builtIn), "An explicit choice replaces follow-default mode")
    builtIn.isDefault = false
    expect(!watch.observe(builtIn.uid, device: builtIn), "Other apps changing the default cannot move a pinned input")
    expect(watch.observe(builtIn.uid, device: nil), "Disconnecting pauses the pinned input")
    expect(!watch.observe(builtIn.uid, device: nil), "A disconnected input does not cause a restart loop")
    expect(watch.observe(builtIn.uid, device: builtIn), "Reconnecting restores the same microphone")
    let reconnected = AudioInputDevice(id: 20, uid: builtIn.uid, name: builtIn.name)
    expect(watch.observe(builtIn.uid, device: reconnected), "A new hardware ID for the same UID needs a fresh graph")
    let renamed = AudioInputDevice(id: 20, uid: builtIn.uid, name: "Renamed fixture")
    expect(!watch.observe(builtIn.uid, device: renamed), "Display-name changes cannot interrupt capture")
    expect(!builtIn.catalogEntry.keys.contains("id"), "Transient hardware IDs are not exposed in settings")
    expect(Set(builtIn.catalogEntry.keys) == Set(["uid", "name", "is_default", "bluetooth"]), "Only the local picker metadata is returned")
    print("\(checks) native audio input scenarios passed")
  }
}
