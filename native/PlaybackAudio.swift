import AVFoundation
import Foundation

// A converter belongs to an audio stream, not to a WebSocket packet. Recreating
// it for every packet discards its filter history and priming/trailing samples.
final class PlaybackPCMConverter {
  let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1)!
  private var converter: AVAudioConverter?
  private var sourceFormat: AVAudioFormat?

  func convert(_ input: AVAudioPCMBuffer) throws -> AVAudioPCMBuffer {
    guard input.format.sampleRate > 0 else {
      throw ServiceClient.ClientError.server("Invalid playback sample rate.")
    }
    if sourceFormat != input.format {
      converter = AVAudioConverter(from: input.format, to: format)
      sourceFormat = input.format
    }
    let capacity = Double(input.frameLength) * format.sampleRate / input.format.sampleRate + 512
    guard capacity <= format.sampleRate * 30, let converter = converter,
      let result = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(capacity))
    else { throw ServiceClient.ClientError.server("Playback conversion is unavailable.") }
    var supplied = false
    var error: NSError?
    let status = converter.convert(to: result, error: &error) { _, state in
      guard !supplied else {
        state.pointee = .noDataNow
        return nil
      }
      supplied = true
      state.pointee = .haveData
      return input
    }
    guard status != .error && error == nil else {
      throw ServiceClient.ClientError.server("Playback audio conversion failed.")
    }
    return result
  }

  func finish() throws -> [AVAudioPCMBuffer] {
    guard let converter = converter else { return [] }
    defer { reset() }
    var buffers: [AVAudioPCMBuffer] = []
    for _ in 0..<8 {
      let result = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096)!
      var error: NSError?
      let status = converter.convert(to: result, error: &error) { _, state in
        state.pointee = .endOfStream
        return nil
      }
      guard status != .error && error == nil else {
        throw ServiceClient.ClientError.server("Could not finish playback conversion.")
      }
      if result.frameLength > 0 { buffers.append(result) }
      if status == .endOfStream || result.frameLength == 0 { return buffers }
    }
    throw ServiceClient.ClientError.server("Playback converter did not finish within its limit.")
  }

  func reset() {
    converter = nil
    sourceFormat = nil
  }
}

// Buffer a small amount before playback/rebuffering. Short final utterances also
// start through a bounded timer or explicit end-of-stream, rather than waiting
// indefinitely for another packet. This policy never opens an audio device.
struct PlaybackBufferState {
  let sampleRate: Double
  let prebufferFrames: Int
  private(set) var queuedFrames = 0
  private(set) var buffering = true

  init(sampleRate: Double = 48000, milliseconds: Double = 120) {
    self.sampleRate = sampleRate
    prebufferFrames = Int(sampleRate * milliseconds / 1000)
  }

  var ready: Bool { queuedFrames >= prebufferFrames }

  mutating func enqueue(_ frames: Int) { queuedFrames += frames }
  mutating func started() { buffering = false }
  mutating func completed(_ frames: Int) {
    queuedFrames = max(0, queuedFrames - frames)
    if queuedFrames == 0 { buffering = true }
  }
  mutating func reset() {
    queuedFrames = 0
    buffering = true
  }
}
