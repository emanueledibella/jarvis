import Foundation

@main
struct BargeInPolicyTests {
  static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { fatalError(message) }
  }

  static func main() {
    var policy = BargeInPolicy()
    expect(!policy.take(startFrame: 0, endFrame: 12000, confidence: 1,
      currentFrame: 12000, echoProtected: true, playing: true), "No active playback means no interruption")
    policy.begin(atFrame: 24000)
    expect(!policy.take(startFrame: 18000, endFrame: 30000, confidence: 0.99,
      currentFrame: 31000, echoProtected: true, playing: true), "Delayed classification of the original question must not interrupt its answer")
    expect(!policy.take(startFrame: 24000, endFrame: 36000, confidence: 0.99,
      currentFrame: 37000, echoProtected: false, playing: true), "Unsupported echo cancellation must fail closed")
    expect(!policy.take(startFrame: 24000, endFrame: 36000, confidence: 0.4,
      currentFrame: 37000, echoProtected: true, playing: true), "Noise or uncertain classification is insufficient")
    expect(!policy.take(startFrame: 24000, endFrame: 36000, confidence: .nan,
      currentFrame: 37000, echoProtected: true, playing: true), "Malformed confidence must not trigger")
    expect(!policy.take(startFrame: 24000, endFrame: 36000, confidence: 0.99,
      currentFrame: 55000, echoProtected: true, playing: true), "Stale inference must be discarded")
    expect(!policy.take(startFrame: 24000, endFrame: 38000, confidence: 0.99,
      currentFrame: 37000, echoProtected: true, playing: true), "Future results are invalid")
    expect(!policy.take(startFrame: 36000, endFrame: 24000, confidence: 0.99,
      currentFrame: 37000, echoProtected: true, playing: true), "Reversed timestamps are invalid")
    expect(!policy.take(startFrame: 24000, endFrame: 36000, confidence: 0.99,
      currentFrame: 37000, echoProtected: true, playing: false), "Already finished playback must not restart listening")
    policy.begin(atFrame: 30000)
    expect(policy.playbackStart == 24000, "Network packets and rebuffering must not move the beginning of an active utterance")
    expect(policy.take(startFrame: 24000, endFrame: 36000, confidence: 0.99,
      currentFrame: 37000, echoProtected: true, playing: true), "Fresh, confident echo-cancelled speech interrupts once")
    expect(!policy.take(startFrame: 24500, endFrame: 36500, confidence: 0.99,
      currentFrame: 37000, echoProtected: true, playing: true), "Overlapping classifier windows cannot interrupt twice")
    policy.reset()
    expect(policy.playbackStart == nil && !policy.triggered, "Mute, lock and closure discard detection state")
    policy.begin(atFrame: 50000)
    expect(policy.take(startFrame: 50000, endFrame: 62000, confidence: 0.8,
      currentFrame: 63000, echoProtected: true, playing: true), "A later assistant answer can be interrupted independently")
    print("14 native spoken interruption scenarios passed")
  }
}
