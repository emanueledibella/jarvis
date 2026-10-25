import AVFoundation
import Foundation

@main
struct LiveAudioBufferTests {
  static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { fatalError(message) }
  }

  static func main() throws {
    let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1)!
    let audio = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480)!
    audio.frameLength = 480
    for index in 0..<480 {
      audio.floatChannelData![0][index] = Float(sin(Double(index) / 10) * 0.1)
    }
    let buffer = LiveAudioBuffer()
    for _ in 0..<400 { buffer.append(audio) }
    let beforeActivation = try buffer.drain()
    expect(beforeActivation.isEmpty, "Audio before activation must remain in the local pre-roll")
    buffer.begin()
    var preRoll = Data()
    while true {
      let chunk = try buffer.drain()
      if chunk.isEmpty { break }
      expect(chunk.count % 2 == 0, "Only complete PCM16 samples may be transmitted")
      preRoll.append(chunk)
    }
    expect(
      !preRoll.isEmpty && preRoll.count <= 72000, "The pre-roll must be bounded to 1.5 seconds")
    for _ in 0..<1500 { buffer.append(audio) }
    do {
      _ = try buffer.drain()
      fatalError("A stalled connection must not create an unbounded recording")
    } catch ServiceClient.ClientError.server {}
    buffer.clear()
    let afterClear = try buffer.drain()
    expect(afterClear.isEmpty, "Mute and session changes discard pending audio")
    for index in 0..<480 { audio.floatChannelData![0][index] = 0 }
    buffer.begin()
    for _ in 0..<10 { buffer.append(audio) }
    let fresh = try buffer.drain()
    expect(
      !fresh.isEmpty && fresh.allSatisfy { $0 == 0 },
      "Resampler history must not leak audio from a previous session")
    buffer.clear()
    buffer.begin()
    buffer.setGated(true)
    for index in 0..<480 { audio.floatChannelData![0][index] = 0.5 }
    for _ in 0..<10 { buffer.append(audio) }
    let suppressed = try buffer.drain()
    expect(
      !suppressed.isEmpty && suppressed.allSatisfy { $0 == 0 },
      "Playback gating must prevent the assistant voice from being uploaded as a user command")
    buffer.clear()
    buffer.begin()
    for _ in 0..<10 { buffer.append(audio) }
    buffer.setGated(true)
    let capturedBeforePlayback = try buffer.drain()
    expect(
      capturedBeforePlayback.contains { $0 != 0 },
      "Starting playback must not discard the user's already captured question")
    print("6 native audio buffering scenarios passed")
  }
}
