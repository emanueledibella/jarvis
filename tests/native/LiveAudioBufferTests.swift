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
    buffer.clear()
    for _ in 0..<100 { buffer.append(audio) }
    let wakeEnd = buffer.position()
    for _ in 0..<20 { buffer.append(audio) }
    let commandFrames = buffer.position() - wakeEnd
    buffer.begin(afterFrame: wakeEnd, deferred: true)
    buffer.begin(afterFrame: wakeEnd, deferred: true)
    var commandAudio = Data()
    while true {
      let part = try buffer.drain()
      if part.isEmpty { break }
      commandAudio.append(part)
    }
    expect(commandAudio.count == Int(commandFrames) * 2,
      "Trim the wake word at its audio timestamp while preserving the complete command onset; activation is idempotent")

    buffer.clear()
    buffer.begin(deferred: true)
    for _ in 0..<1500 { buffer.append(audio) }
    var waitingAudio = Data()
    while true {
      let part = try buffer.drain()
      if part.isEmpty { break }
      waitingAudio.append(part)
    }
    expect(waitingAudio.count <= 480000 && !waitingAudio.isEmpty,
      "A long local wake-only pause rolls a bounded RAM buffer without starting or overflowing a cloud stream")

    buffer.startStreaming()
    for _ in 0..<1500 { buffer.append(audio) }
    do {
      _ = try buffer.drain()
      fatalError("Once delivery starts, a stalled provider must still fail closed")
    } catch ServiceClient.ClientError.server {}

    buffer.clear()
    let future = buffer.position() + 24000
    buffer.begin(afterFrame: future)
    for _ in 0..<10 { buffer.append(audio) }
    let afterFuture = try buffer.drain()
    expect(!afterFuture.isEmpty, "A future timestamp cannot discard subsequent microphone samples")
    print("10 native audio buffering scenarios passed")
  }
}
