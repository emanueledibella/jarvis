import Foundation

@main
struct WakeRecoveryGuardTests {
  static var checks = 0

  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    guard condition() else { fatalError(message) }
  }

  static func ready() -> WakeRecoveryGuard {
    WakeRecoveryGuard(enabled: true, voiceEnabled: true, wakeEnabled: true,
      muted: false, locked: false, permissionsGranted: true,
      state: "armed", callbacks: 10, wakeMatches: 2)
  }

  static func main() {
    let baseline = ready()
    expect(baseline.allows(expectedCallbacks: 10, expectedWakeMatches: 2),
      "A stalled idle listener can rebuild capture without unmuting a new user preference")
    let blocked: [(String, (inout WakeRecoveryGuard) -> Void)] = [
      ("Disabled engine", { $0.enabled = false }),
      ("Disabled voice", { $0.voiceEnabled = false }),
      ("Disabled wake phrase", { $0.wakeEnabled = false }),
      ("New local mute", { $0.muted = true }),
      ("New screen lock", { $0.locked = true }),
      ("Revoked permissions", { $0.permissionsGranted = false }),
      ("New live conversation", { $0.live = true }),
      ("Playback or local wake cue", { $0.playing = true }),
      ("New listening turn", { $0.state = "listening" }),
      ("New spoken answer", { $0.state = "speaking" }),
      ("Active command", { $0.state = "processing" }),
      ("Active follow-up", { $0.state = "followup" }),
      ("Permanent model/authorization failure", { $0.state = "unavailable" }),
      ("Recognition resumed after the server's check", { $0.callbacks += 1 }),
      ("A wake matched after the server's check", { $0.wakeMatches += 1 }),
    ]
    for (message, mutate) in blocked {
      var value = baseline
      mutate(&value)
      expect(!value.allows(expectedCallbacks: 10, expectedWakeMatches: 2), message)
    }
    var locked = baseline
    locked.locked = true
    locked.allowWhenLocked = true
    expect(locked.allows(expectedCallbacks: 10, expectedWakeMatches: 2),
      "The owner's explicit lock-screen opt-in still applies")
    var transient = baseline
    transient.state = "unavailable"
    transient.transientFailure = true
    expect(transient.allows(expectedCallbacks: 10, expectedWakeMatches: 2),
      "Exhausted transient local service retries can escalate")
    transient.state = "recovering"
    expect(transient.allows(expectedCallbacks: 10, expectedWakeMatches: 2),
      "A soft retry can escalate without an active conversation")
    expect(!WakeRecoveryGuard().allows(expectedCallbacks: 0, expectedWakeMatches: 0),
      "An uninitialized guard must fail closed")
    expect(!baseline.allows(expectedCallbacks: -1, expectedWakeMatches: -1),
      "Missing progress expectations cannot authorize recovery")
    print("\(checks) native wake recovery guard scenarios passed")
  }
}
