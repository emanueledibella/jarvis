import Foundation

// Classification must describe fresh speech captured after playback began.
// Delayed callbacks from the original question must never cut off its answer.
struct BargeInPolicy {
  private(set) var playbackStart: Int64?
  private(set) var triggered = false

  mutating func begin(atFrame frame: Int64) {
    guard playbackStart == nil else { return }
    playbackStart = frame
    triggered = false
  }

  mutating func take(startFrame: Int64, endFrame: Int64, confidence: Double,
                     currentFrame: Int64, echoProtected: Bool, playing: Bool) -> Bool {
    guard echoProtected, playing, let start = playbackStart, !triggered,
      confidence.isFinite, confidence >= 0.80,
      startFrame >= start, endFrame > startFrame, endFrame <= currentFrame,
      currentFrame - endFrame <= 18000  // Ignore results more than 750 ms old.
    else { return false }
    triggered = true
    return true
  }

  mutating func reset() {
    playbackStart = nil
    triggered = false
  }
}
