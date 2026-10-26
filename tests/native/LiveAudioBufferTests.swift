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

    buffer.clear()
    buffer.begin()
    buffer.setGated(true)
    let onset = buffer.position()
    for _ in 0..<30 { buffer.append(audio) }
    let seed = buffer.snapshot(afterFrame: onset)
    expect(!seed.data.isEmpty && seed.data.contains { $0 != 0 },
      "The local processed-input pre-roll retains user speech while provider uploads are gated")
    let wire = try buffer.drain()
    expect(wire.allSatisfy { $0 == 0 }, "The same gated samples must remain silent on the old provider connection")
    buffer.clear()
    buffer.begin(deferred: true, seed: seed.data)
    let seeded = try buffer.drain()
    expect(seeded == Data(seed.data.prefix(4800)), "A fresh connection starts with the user's preserved onset")
    expect(LiveAudioBuffer.buffer(seed.data)?.frameLength == AVAudioFrameCount(seed.data.count / 2),
      "The local recognizer receives the same PCM16 onset before live input resumes")
    expect(LiveAudioBuffer.buffer(Data([0])) == nil && LiveAudioBuffer.buffer(Data(count: 72002)) == nil,
      "Recognition seed decoding rejects incomplete or oversized samples")
    for _ in 0..<400 { buffer.append(audio) }
    expect(buffer.snapshot(afterFrame: 0).data.count <= 72000,
      "The interruption history remains bounded even throughout active streaming")
    buffer.clear()
    expect(buffer.snapshot(afterFrame: 0).data.isEmpty, "Mute and privacy changes clear interruption history as well")
    let seedPCM = LiveAudioBuffer.buffer(Data([0, 128, 0, 0, 255, 127]))!
    let speech = LiveAudioBuffer.recognitionBuffer(seedPCM)!
    expect(speech.format.commonFormat == .pcmFormatFloat32
      && speech.format.sampleRate == 24000 && speech.format.channelCount == 1,
      "Speech.framework receives a consistent mono floating-point format")
    expect(speech.frameLength == seedPCM.frameLength,
      "Local recognition retains the provider's frame clock and wake timestamps")
    let samples = speech.floatChannelData![0]
    expect(samples[0] == -1 && samples[1] == 0 && abs(samples[2] - 0.9999695) < 0.000001,
      "PCM16 conversion preserves signed amplitude without clipping or silence")
    expect(LiveAudioBuffer.recognitionBuffer(audio) == nil,
      "Unexpected input formats cannot be misread as PCM16")
    print("21 native audio buffering scenarios passed")
  }
}
