import Foundation

// Evaluated on the voice engine's main actor immediately before rebuilding
// capture. A recovery queued before a mute, lock, wake, or conversation must
// never override the newer user action or interrupt live audio.
struct WakeRecoveryGuard {
  var enabled = false
  var voiceEnabled = false
  var wakeEnabled = false
  var muted = true
  var locked = true
  var allowWhenLocked = false
  var permissionsGranted = false
  var live = false
  var playing = false
  var state = "unavailable"
  var transientFailure = false
  var callbacks = 0
  var wakeMatches = 0

  func allows(expectedCallbacks: Int, expectedWakeMatches: Int) -> Bool {
    enabled && voiceEnabled && wakeEnabled && !muted && (!locked || allowWhenLocked)
      && permissionsGranted && !live && !playing
      && (["armed", "recovering"].contains(state) || (state == "unavailable" && transientFailure))
      && callbacks == expectedCallbacks && wakeMatches == expectedWakeMatches
  }
}

// A quiet microphone is normal, including a lazily starting recognizer. Recover
// ended tasks or sustained audible input that produces no recognition progress.
struct RecognitionLiveness {
  enum TaskState: String {
    case idle, starting, running, finishing, canceling, completed, unknown
  }

  private var startedAt: TimeInterval?
  private var callbackAt: TimeInterval?
  private var audioAt: TimeInterval?
  private var firstAudibleAt: TimeInterval?
  private var lastAudibleAt: TimeInterval?
  private var audibleSeconds: TimeInterval = 0

  mutating func begin(at now: TimeInterval) {
    self = RecognitionLiveness()
    startedAt = now
  }

  mutating func stop() { self = RecognitionLiveness() }

  mutating func receivedCallback(at now: TimeInterval) {
    guard startedAt != nil else { return }
    callbackAt = now
    firstAudibleAt = nil
    lastAudibleAt = nil
    audibleSeconds = 0
  }

  mutating func receivedAudio(at now: TimeInterval, seconds: TimeInterval, level: Double) {
    guard startedAt != nil, now.isFinite, seconds.isFinite, seconds > 0,
      seconds <= 1, level.isFinite else { return }
    audioAt = now
    if level >= 0.1 {
      if let previous = lastAudibleAt, now - previous > 2 {
        firstAudibleAt = nil
        audibleSeconds = 0
      }
      if firstAudibleAt == nil { firstAudibleAt = now }
      lastAudibleAt = now
      audibleSeconds = min(2, audibleSeconds + seconds)
    }
  }

  func stalled(at now: TimeInterval, task: TaskState) -> Bool {
    guard now.isFinite, let start = startedAt, now >= start,
      let audio = audioAt, now >= audio, now - audio <= 2 else { return false }
    switch task {
    case .starting:
      guard audibleSeconds >= 0.25, let first = firstAudibleAt,
        let last = lastAudibleAt, now - last <= 10 else { return false }
      return callbackAt == nil && now - start >= 10 && now - first >= 4
    case .idle, .finishing, .canceling, .completed, .unknown:
      return now - max(start, callbackAt ?? start) >= 2
    case .running:
      guard audibleSeconds >= 0.25, let first = firstAudibleAt,
        let last = lastAudibleAt, now - last <= 5 else { return false }
      return now - max(start, callbackAt ?? start) >= 6 && now - first >= 4
    }
  }
}

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
