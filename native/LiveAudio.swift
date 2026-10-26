import AVFoundation
import Foundation

// Short audio buffers stay in RAM. A local wake word activates the uplink; this
// queue never writes a recording to disk and is cleared on mute/session changes.
final class LiveAudioBuffer: @unchecked Sendable {
  private let lock = NSLock()
  static let format = AVAudioFormat(
    commonFormat: .pcmFormatInt16, sampleRate: 24000, channels: 1, interleaved: true)!
  private let pcm = LiveAudioBuffer.format
  private var converter: AVAudioConverter?
  private var sourceFormat: AVAudioFormat?
  private var preRoll = Data()
  private var pending = Data()
  private var active = false
  private var preparing = false
  private var overflow = false
  private var gated = false
  private var capturedFrames: Int64 = 0
  private let preRollBytes = 72000  // 1.5 seconds, including wake-detection latency.
  private let maximumBytes = 480000  // Bounded startup/network buffer: 10 seconds.

  @discardableResult
  func append(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
    lock.lock()
    defer { lock.unlock() }
    if sourceFormat != buffer.format {
      converter = AVAudioConverter(from: buffer.format, to: pcm)
      sourceFormat = buffer.format
    }
    guard let converter = converter,
      let converted = AVAudioPCMBuffer(
        pcmFormat: pcm,
        frameCapacity: AVAudioFrameCount(
          Double(buffer.frameLength) * 24000 / buffer.format.sampleRate) + 64)
    else { return nil }
    var supplied = false
    var error: NSError?
    converter.convert(to: converted, error: &error) { _, status in
      if supplied {
        status.pointee = .noDataNow
        return nil
      }
      supplied = true
      status.pointee = .haveData
      return buffer
    }
    guard error == nil, converted.frameLength > 0, let samples = converted.int16ChannelData?[0]
    else { return nil }
    let count = Int(converted.frameLength) * 2
    capturedFrames += Int64(converted.frameLength)
    let original = Data(bytes: samples, count: count)
    // Keep a short processed-input history even while the provider uplink is
    // gated, so interruption detection can recover the user's first syllables.
    preRoll.append(original)
    if preRoll.count > preRollBytes { preRoll.removeFirst(preRoll.count - preRollBytes) }
    let bytes = active && gated ? Data(repeating: 0, count: count) : original
    if active {
      if pending.count + bytes.count <= maximumBytes {
        pending.append(bytes)
      } else if preparing {
        pending.append(bytes)
        pending.removeFirst(pending.count - maximumBytes)
      } else {
        overflow = true
      }
    }
    return converted
  }

  func position() -> Int64 {
    lock.lock()
    defer { lock.unlock() }
    return capturedFrames
  }

  func snapshot(afterFrame: Int64) -> (frame: Int64, data: Data) {
    lock.lock()
    defer { lock.unlock() }
    let start = capturedFrames - Int64(preRoll.count / 2)
    let frame = min(capturedFrames, max(start, afterFrame))
    return (frame, Data(preRoll.dropFirst(Int(frame - start) * 2)))
  }

  static func buffer(_ data: Data) -> AVAudioPCMBuffer? {
    guard !data.isEmpty, data.count <= 72000, data.count % 2 == 0,
      let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(data.count / 2)),
      let samples = buffer.int16ChannelData?[0] else { return nil }
    buffer.frameLength = AVAudioFrameCount(data.count / 2)
    _ = data.withUnsafeBytes { memcpy(samples, $0.baseAddress!, data.count) }
    return buffer
  }

  func begin(afterFrame: Int64? = nil, deferred: Bool = false, seed: Data? = nil) {
    lock.lock()
    defer { lock.unlock() }
    guard !active else { return }
    let start = capturedFrames - Int64(preRoll.count / 2)
    let discard = afterFrame.map { Int(min(Int64(preRoll.count), max(0, $0 - start) * 2)) } ?? 0
    pending = seed ?? Data(preRoll.dropFirst(discard))
    overflow = pending.count > maximumBytes || pending.count % 2 != 0
    if overflow { pending.removeAll() }
    active = true
    preparing = deferred
  }

  func startStreaming() {
    lock.lock()
    defer { lock.unlock() }
    preparing = false
  }

  func drain() throws -> Data {
    lock.lock()
    defer { lock.unlock() }
    if overflow {
      throw ServiceClient.ClientError.server(
        "The audio connection is too slow. Reopen the conversation.")
    }
    let size = min(4800, pending.count)
    let result = Data(pending.prefix(size))
    pending.removeFirst(size)
    return result
  }

  func clear() {
    lock.lock()
    defer { lock.unlock() }
    pending.removeAll()
    preRoll.removeAll()
    active = false
    preparing = false
    overflow = false
    gated = false
    converter?.reset()
  }

  func setGated(_ value: Bool) {
    lock.lock()
    defer { lock.unlock() }
    gated = value
  }
}
