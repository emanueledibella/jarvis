import AVFoundation
import CoreMedia

@main
struct SelectedAudioInputTests {
  static var checks = 0
  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    if !condition() { fatalError(message) }
  }

  static func sample(_ pcm: AVAudioPCMBuffer, ready: Bool = true) -> CMSampleBuffer {
    var value: CMSampleBuffer?
    let result = CMAudioSampleBufferCreateWithPacketDescriptions(allocator: kCFAllocatorDefault,
      dataBuffer: nil, dataReady: false, makeDataReadyCallback: nil, refcon: nil,
      formatDescription: pcm.format.formatDescription, sampleCount: Int(pcm.frameLength),
      presentationTimeStamp: .zero, packetDescriptions: nil, sampleBufferOut: &value)
    precondition(result == noErr)
    if ready {
      precondition(CMSampleBufferSetDataBufferFromAudioBufferList(value!, blockBufferAllocator: kCFAllocatorDefault,
        blockBufferMemoryAllocator: kCFAllocatorDefault, flags: 0, bufferList: pcm.audioBufferList) == noErr)
      precondition(CMSampleBufferSetDataReady(value!) == noErr)
    }
    return value!
  }

  static func main() {
    for channels in [AVAudioChannelCount(1), AVAudioChannelCount(2)] {
      let format = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: channels)!
      let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 64)!
      pcm.frameLength = 64
      for channel in 0..<Int(channels) {
        for frame in 0..<64 { pcm.floatChannelData![channel][frame] = Float(channel + 1) * 0.125 }
      }
      let copied = SelectedAudioInput.pcmBuffer(sample(pcm))!
      expect(copied.frameLength == 64, "Capture preserves the exact frame count")
      expect(copied.format.sampleRate == 48000 && copied.format.channelCount == channels,
        "Device input keeps its original sample rate and channel layout before shared conversion")
      expect(copied.floatChannelData![0][32] == 0.125, "PCM is copied without distortion")
      if channels == 2 {
        expect(copied.floatChannelData![1][32] == 0.25, "Reference channels cannot overwrite the microphone channel")
      }
      pcm.floatChannelData![0][32] = 0
      expect(copied.floatChannelData![0][32] == 0.125, "Capture owns its PCM memory independently of the sample buffer")
      expect(SelectedAudioInput.pcmBuffer(sample(pcm, ready: false)) == nil, "Unready samples cannot enter recognition")
    }
    print("\(checks) native selected microphone PCM scenarios passed")
  }
}
