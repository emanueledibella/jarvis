import Foundation

// Decisions depend on microphone/recognizer timestamps, never network readiness.
// A missed opportunity expires rather than becoming a delayed spoken greeting.
struct WakeAcknowledgement {
  let delay: TimeInterval = 0.30
  let deadline: TimeInterval = 0.80
  let quietPeriod: TimeInterval = 0.20
  private(set) var activatedAt: TimeInterval?
  private(set) var consumed = true
  private(set) var requestStarted = false

  mutating func begin(at time: TimeInterval, hasRequest: Bool) {
    activatedAt = time
    consumed = hasRequest
    requestStarted = hasRequest
  }

  mutating func heardRequest() {
    requestStarted = true
    consumed = true
  }

  mutating func heardSound(at time: TimeInterval) {
    guard let start = activatedAt, time >= start + 0.10, !consumed else { return }
    heardRequest()
  }

  mutating func take(at time: TimeInterval, lastSoundAt: TimeInterval) -> Bool {
    guard let start = activatedAt, !consumed else { return false }
    guard time <= start + deadline else { consumed = true; return false }
    guard !requestStarted, time >= start + delay, time - lastSoundAt >= quietPeriod else { return false }
    consumed = true
    return true
  }

  mutating func cancel() {
    activatedAt = nil
    consumed = true
    requestStarted = false
  }

  static func language(response: String, fallback: String) -> String? {
    let selected = (response == "auto" ? fallback : response).lowercased()
    if selected.hasPrefix("it") { return "it" }
    if selected.hasPrefix("en") { return "en" }
    return nil
  }

  static func isCueOnlyOrPrefix(_ text: String) -> Bool {
    let value = text.lowercased().trimmingCharacters(in: .punctuationCharacters.union(.whitespacesAndNewlines))
    guard !value.isEmpty else { return false }
    return ["dimmi", "yes", "sì", "si", "ies"].contains { $0.hasPrefix(value) }
  }
}
