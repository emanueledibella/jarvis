import Foundation

// Classification must describe fresh speech captured after playback began.
// Delayed callbacks from the original question must never cut off its answer.
struct BargeInPolicy {
  private(set) var playbackStart: Int64?
  private(set) var inputReleasedAt: Int64?
  private(set) var triggered = false

  mutating func begin(atFrame frame: Int64) {
    if inputReleasedAt != nil { reset() }
    guard playbackStart == nil else { return }
    playbackStart = frame
    triggered = false
  }

  mutating func releaseInput(atFrame frame: Int64) {
    if playbackStart != nil && inputReleasedAt == nil { inputReleasedAt = frame }
  }

  mutating func take(startFrame: Int64, endFrame: Int64, confidence: Double,
                     currentFrame: Int64, echoProtected: Bool, playing: Bool) -> Bool {
    // A classifier result can arrive after the final played sample. Recover
    // speech that began while input was still gated, but do not reconnect for
    // a normal follow-up whose entire window was already sent to the provider.
    let repairingTail = inputReleasedAt.map {
      startFrame < $0 && currentFrame >= $0 && currentFrame - $0 <= 24000
    } ?? false
    guard echoProtected, playing || repairingTail, let start = playbackStart, !triggered,
      confidence.isFinite, confidence >= 0.80,
      startFrame >= start, endFrame > startFrame, endFrame <= currentFrame,
      currentFrame - endFrame <= 18000  // Ignore results more than 750 ms old.
    else { return false }
    triggered = true
    return true
  }

  mutating func reset() {
    playbackStart = nil
    inputReleasedAt = nil
    triggered = false
  }
}
