import Foundation

@main
struct RecognitionRecoveryTests {
  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
  }

  static func main() {
    let silence = NSError(domain: "kAFAssistantErrorDomain", code: 1110)
    let interruption = NSError(domain: "kAFAssistantErrorDomain", code: 1101)
    var policy = RecognitionRecovery()
    for _ in 0..<150 {
      expect(
        policy.handle(silence, sessionDuration: 20) == .retry(after: 0.3),
        "Idle listening must survive repeated silent sessions")
    }
    expect(policy.consecutiveFailures == 0, "Silence is not a service failure")

    let delays: [TimeInterval] = [0.5, 1, 2, 4, 8]
    for delay in delays {
      expect(
        policy.handle(interruption, sessionDuration: 0.1) == .retry(after: delay),
        "Repeated fast failures must back off")
    }
    guard case .unavailable = policy.handle(interruption, sessionDuration: 0.1) else {
      fatalError("Repeated service failures must eventually stop")
    }

    policy.receivedSpeech()
    expect(
      policy.handle(interruption, sessionDuration: 0.1) == .retry(after: 0.5),
      "Recognized speech restores the recovery budget")

    policy = RecognitionRecovery()
    for _ in 0..<5 { _ = policy.handle(silence, sessionDuration: 0.01) }
    guard case .unavailable = policy.handle(silence, sessionDuration: 0.01) else {
      fatalError("An instantly failing silence loop must not spin forever")
    }

    let missing = NSError(domain: "kLSRErrorDomain", code: 102)
    policy = RecognitionRecovery()
    guard case .unavailable(let assetsMessage) = policy.handle(missing, sessionDuration: 0) else {
      fatalError("Missing assets require setup, not automatic retries")
    }
    expect(assetsMessage.contains("modello vocale"), "Missing assets need actionable advice")

    guard
      case .unavailable(let disabledMessage) = policy.handle(
        NSError(domain: "kLSRErrorDomain", code: 201), sessionDuration: 0)
    else {
      fatalError("Disabled Dictation requires system setup")
    }
    expect(
      disabledMessage.contains("disattivati"),
      "Disabled Dictation must not be reported as missing assets")

    guard
      case .permissionRequired = policy.handle(
        NSError(domain: "kAFAssistantErrorDomain", code: 1700), sessionDuration: 0)
    else {
      fatalError("Denied authorization must not trigger a retry loop")
    }

    let wrapped = NSError(
      domain: "kAFAssistantErrorDomain", code: 203, userInfo: [NSUnderlyingErrorKey: missing])
    guard case .unavailable(let nestedMessage) = policy.handle(wrapped, sessionDuration: 0) else {
      fatalError("The underlying asset failure must remain visible")
    }
    expect(nestedMessage.contains("kLSRErrorDomain:102"), "Keep the diagnostic domain and code")

    policy = RecognitionRecovery()
    expect(
      policy.handle(NSError(domain: "UnrelatedDomain", code: 102), sessionDuration: 0)
        == .retry(after: 0.5), "An unrelated error code must not claim assets are missing")

    _ = policy.handle(interruption, sessionDuration: 0.1)
    expect(
      policy.handle(interruption, sessionDuration: 30) == .retry(after: 0.5),
      "A stable session breaks a consecutive-failure sequence")

    policy = RecognitionRecovery()
    let privateError = NSError(
      domain: "kAFAssistantErrorDomain", code: 203,
      userInfo: [NSLocalizedDescriptionKey: "private-transcription-must-not-appear"])
    for _ in 0..<5 { _ = policy.handle(privateError, sessionDuration: 0) }
    guard case .unavailable(let privateMessage) = policy.handle(privateError, sessionDuration: 0)
    else { fatalError("Expected final diagnostic") }
    expect(
      !privateMessage.contains("private-transcription"),
      "Error messages must not expose arbitrary userInfo or transcripts")
    print("11 native recognition recovery scenarios passed")
  }
}
