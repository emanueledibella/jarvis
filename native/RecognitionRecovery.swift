import Foundation

enum RecognitionRecoveryDecision: Equatable {
  case retry(after: TimeInterval)
  case unavailable(String)
  case permissionRequired(String)
}

struct RecognitionRecovery {
  private(set) var consecutiveFailures = 0

  mutating func receivedSpeech() { consecutiveFailures = 0 }

  mutating func handle(_ error: NSError, sessionDuration: TimeInterval)
    -> RecognitionRecoveryDecision
  {
    var chain = [error]
    while chain.count < 6, let underlying = chain.last?.userInfo[NSUnderlyingErrorKey] as? NSError {
      chain.append(underlying)
    }
    // Apple's error table distinguishes missing assets, disabled Dictation,
    // a normal silent session and service interruptions. Do not log transcripts
    // or arbitrary error userInfo when diagnosing a private audio stream.
    let reference = chain.map { "\($0.domain):\($0.code)" }.joined(separator: " → ")
    func contains(_ domain: String, _ code: Int) -> Bool {
      chain.contains { $0.domain == domain && $0.code == code }
    }
    if contains("kLSRErrorDomain", 102) {
      return .unavailable(
        "The selected language's local speech model is missing. Check System Settings → Keyboard → Dictation, then enable voice again. (\(reference))"
      )
    }
    if contains("kLSRErrorDomain", 201) {
      return .unavailable(
        "macOS reports that Siri or Dictation is disabled. Check System Settings → Keyboard → Dictation, then enable voice again. (\(reference))"
      )
    }
    if contains("kAFAssistantErrorDomain", 1700) {
      return .permissionRequired(
        "Speech recognition is not authorized. Check Jarvis permissions in Privacy & Security. (\(reference))"
      )
    }
    let normalEnd = contains("kAFAssistantErrorDomain", 1110) || contains("kLSRErrorDomain", 301)
    if normalEnd && sessionDuration >= 1 {
      consecutiveFailures = 0
      return .retry(after: 0.3)
    }
    if sessionDuration >= 15 { consecutiveFailures = 0 }
    consecutiveFailures += 1
    guard consecutiveFailures <= 5 else {
      return .unavailable(
        "The local speech service keeps stopping. Check the selected microphone and macOS Dictation, then press Talk to Jarvis to retry. (\(reference))"
      )
    }
    return .retry(after: min(8, 0.5 * pow(2, Double(consecutiveFailures - 1))))
  }
}
