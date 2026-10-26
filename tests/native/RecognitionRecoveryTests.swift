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
    expect(assetsMessage.contains("speech model"), "Missing assets need actionable advice")

    guard
      case .unavailable(let disabledMessage) = policy.handle(
        NSError(domain: "kLSRErrorDomain", code: 201), sessionDuration: 0)
    else {
      fatalError("Disabled Dictation requires system setup")
    }
    expect(
      disabledMessage.contains("disabled"),
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
    var liveness = RecognitionLiveness()
    liveness.begin(at: 100)
    liveness.receivedAudio(at: 145, seconds: 0.1, level: 0.01)
    expect(!liveness.stalled(at: 145, task: .running),
      "Long quiet sessions are not stalled recognition")

    liveness.receivedAudio(at: 145.1, seconds: 0.01, level: 0.5)
    liveness.receivedAudio(at: 149.2, seconds: 0.1, level: 0.01)
    expect(!liveness.stalled(at: 149.2, task: .running),
      "An isolated sound must not restart the recognizer")

    liveness.begin(at: 200)
    liveness.receivedAudio(at: 202, seconds: 0.3, level: 0.2)
    liveness.receivedAudio(at: 206, seconds: 0.1, level: 0.01)
    expect(liveness.stalled(at: 206, task: .running),
      "Sustained audible input with no callback must recover a wedged recognizer")
    liveness.receivedCallback(at: 206)
    expect(!liveness.stalled(at: 206.1, task: .running),
      "A result or error callback proves progress and clears old audio evidence")

    liveness.begin(at: 300)
    liveness.receivedAudio(at: 330, seconds: 0.1, level: 0)
    expect(!liveness.stalled(at: 330, task: .starting),
      "A lazily starting recognizer must survive silence without consuming its retry budget")
    liveness.receivedAudio(at: 331, seconds: 0.3, level: 0.2)
    liveness.receivedAudio(at: 334, seconds: 0.1, level: 0)
    expect(!liveness.stalled(at: 334, task: .starting), "Allow time to process the first audible input")
    liveness.receivedAudio(at: 335, seconds: 0.1, level: 0)
    expect(liveness.stalled(at: 335, task: .starting),
      "A task that never starts after sustained input cannot advertise ready indefinitely")

    liveness.begin(at: 400)
    liveness.receivedAudio(at: 402, seconds: 0.1, level: 0)
    expect(liveness.stalled(at: 402, task: .completed),
      "A task that ends without delivering its completion callback must be renewed")
    expect(!liveness.stalled(at: 405, task: .completed),
      "Missing microphone input belongs to capture diagnostics, not speech retries")

    liveness.stop()
    liveness.receivedAudio(at: 500, seconds: 0.3, level: 1)
    expect(!liveness.stalled(at: 505, task: .completed),
      "Mute and cancellation disable recognition liveness recovery")

    liveness.begin(at: 600)
    liveness.receivedAudio(at: 601, seconds: .nan, level: 1)
    liveness.receivedAudio(at: 601, seconds: 0.3, level: .infinity)
    expect(!liveness.stalled(at: .nan, task: .starting)
      && !liveness.stalled(at: 610, task: .running),
      "Malformed clocks or signal metrics cannot trigger a retry")

    policy = RecognitionRecovery()
    let stalled = NSError(domain: "JarvisSpeechLiveness", code: 1)
    for delay in delays {
      expect(policy.handle(stalled, sessionDuration: 6) == .retry(after: delay),
        "Silent recognition stalls share the bounded service-recovery backoff")
    }
    guard case .unavailable = policy.handle(stalled, sessionDuration: 6) else {
      fatalError("A persistently unresponsive recognizer must stop retrying and offer manual activation")
    }
    print("20 native recognition recovery/liveness scenarios passed")
  }
}
