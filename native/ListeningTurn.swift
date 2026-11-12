import Foundation

// A Speech.framework task can end before a person's request does. Keep the
// accepted prefix across task renewals and replace only the new task's partial.
struct ListeningTurn {
  private(set) var text = ""
  private var retained = ""

  mutating func begin(_ value: String = "") {
    retained = ""
    text = value
  }

  mutating func renewRecognition() { retained = text }

  mutating func update(_ partial: String) {
    text = [retained, partial].filter { !$0.isEmpty }.joined(separator: " ")
  }

  func finished(at now: TimeInterval, lastActivityAt: TimeInterval,
                endOfTurn: TimeInterval, waitForSpeech: TimeInterval) -> Bool {
    // The waiting timeout is inactivity, not a maximum dictation length.
    now - lastActivityAt > (text.isEmpty ? waitForSpeech : endOfTurn)
  }
}
