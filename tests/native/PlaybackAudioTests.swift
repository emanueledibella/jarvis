import AVFoundation
import Foundation

@main
struct PlaybackAudioTests {
  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
  }

  static func samples(_ buffer: AVAudioPCMBuffer) -> [Float] {
    Array(UnsafeBufferPointer(start: buffer.floatChannelData![0], count: Int(buffer.frameLength)))
  }

  static func signal(start: Int, count: Int, rate: Double = 24000) -> AVAudioPCMBuffer {
    let format = AVAudioFormat(
      commonFormat: .pcmFormatInt16, sampleRate: rate, channels: 1, interleaved: true)!
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count))!
    buffer.frameLength = AVAudioFrameCount(count)
    for i in 0..<count {
      buffer.int16ChannelData![0][i] = Int16(sin(Double(start + i) * 2 * .pi * 440 / rate) * 14000)
    }
    return buffer
  }

  static func render(total: Int, sizes: [Int], rate: Double = 24000) throws -> [Float] {
    let converter = PlaybackPCMConverter()
    var output: [Float] = []
    var offset = 0
    var packet = 0
    while offset < total {
      let count = min(sizes[packet % sizes.count], total - offset)
      output += samples(try converter.convert(signal(start: offset, count: count, rate: rate)))
      offset += count
      packet += 1
    }
    for tail in try converter.finish() { output += samples(tail) }
    let repeatedFinish = try converter.finish()
    expect(repeatedFinish.isEmpty, "Finishing twice must not repeat the tail")
    return output
  }

  static func main() throws {
    let reference = try render(total: 24000, sizes: [24000])
    let fragmented = try render(total: 24000, sizes: [257, 960, 1024, 480, 1536])
    expect(reference.count == 48000, "End-of-stream must preserve the complete duration")
    expect(fragmented.count == reference.count, "Packets must not repeatedly lose priming samples")
    let error = zip(reference, fragmented).map { abs($0 - $1) }.max() ?? 0
    expect(error < 0.00001, "Fragmented conversion must match a continuous stream")
    let jump = zip(fragmented.dropFirst(), fragmented).map { abs($0 - $1) }.max() ?? 0
    expect(jump < 0.04, "Packet boundaries must not introduce audible waveform jumps")

    let tiny = try render(total: 2400, sizes: [1, 2, 3, 17, 31])
    let tinyReference = try render(total: 2400, sizes: [2400])
    expect(tiny.count == tinyReference.count, "Tiny packets must retain all samples")
    expect(
      zip(tiny, tinyReference).allSatisfy { abs($0 - $1) < 0.00001 },
      "Resampling state must also survive very small packets")

    let appleRate = try render(total: 22050, sizes: [257, 1024, 480], rate: 22050)
    let appleReference = try render(total: 22050, sizes: [22050], rate: 22050)
    expect(appleRate.count == appleReference.count, "Apple-rate audio must preserve duration")
    expect(
      zip(appleRate, appleReference).allSatisfy { abs($0 - $1) < 0.00001 },
      "Noninteger conversion ratios must preserve continuity")

    let converter = PlaybackPCMConverter()
    _ = try converter.convert(signal(start: 0, count: 500))
    converter.reset()
    let silent = signal(start: 0, count: 500)
    for i in 0..<500 { silent.int16ChannelData![0][i] = 0 }
    var cleared = samples(try converter.convert(silent))
    for tail in try converter.finish() { cleared += samples(tail) }
    expect(cleared.allSatisfy { $0 == 0 }, "Stop must discard previous filter history")

    var buffer = PlaybackBufferState()
    buffer.enqueue(480)
    expect(!buffer.ready && buffer.buffering, "Do not start on the first small network packet")
    buffer.enqueue(5280)
    expect(buffer.ready, "120 ms must be enough to begin playback")
    buffer.started()
    buffer.completed(480)
    expect(!buffer.buffering, "Keep playing while queued audio remains")
    buffer.completed(5280)
    expect(buffer.buffering && buffer.queuedFrames == 0, "Rebuffer after a drained queue")
    buffer.enqueue(480)
    expect(!buffer.ready, "Network recovery needs a fresh prebuffer")
    buffer.reset()
    expect(buffer.queuedFrames == 0 && buffer.buffering, "Stop clears playback accounting")
    print("9 native playback continuity and buffering scenarios passed")
    print("Packeted PCM: \(fragmented.count) frames; max sample error \(error); max step \(jump)")
  }
}
