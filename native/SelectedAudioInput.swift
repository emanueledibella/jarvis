@preconcurrency import AVFoundation
import CoreMedia

protocol AudioCaptureSource: AnyObject {
  var isRunning: Bool { get }
  func stop()
}

extension AVAudioEngine: AudioCaptureSource {}

// Use a device-bound capture session when the chosen microphone differs from
// the system route. Changing an AVAudioEngine I/O unit's device cannot safely
// route arbitrary independent input/output hardware on every Mac.
final class SelectedAudioInput: NSObject, AudioCaptureSource, AVCaptureAudioDataOutputSampleBufferDelegate {
  private let session = AVCaptureSession()
  private let output = AVCaptureAudioDataOutput()
  private let queue = DispatchQueue(label: "it.jarvis.audio.selected-input")
  private let lock = NSLock()
  private var active = false
  private let receive: (AVAudioPCMBuffer) -> Void

  init(uid: String, receive: @escaping (AVAudioPCMBuffer) -> Void) throws {
    self.receive = receive
    super.init()
    guard let device = AVCaptureDevice(uniqueID: uid), device.hasMediaType(.audio) else {
      throw NSError(domain: "JarvisAudioInput", code: 1)
    }
    let input = try AVCaptureDeviceInput(device: device)
    session.beginConfiguration()
    guard session.canAddInput(input) else {
      session.commitConfiguration()
      throw NSError(domain: "JarvisAudioInput", code: 2)
    }
    session.addInput(input)
    guard session.canAddOutput(output) else {
      session.commitConfiguration()
      throw NSError(domain: "JarvisAudioInput", code: 2)
    }
    output.audioSettings = [AVFormatIDKey: kAudioFormatLinearPCM,
      AVLinearPCMBitDepthKey: 32, AVLinearPCMIsFloatKey: true,
      AVLinearPCMIsNonInterleaved: false]
    session.addOutput(output)
    output.setSampleBufferDelegate(self, queue: queue)
    session.commitConfiguration()
  }

  var isRunning: Bool {
    lock.lock()
    defer { lock.unlock() }
    return active && session.isRunning
  }

  func start() throws {
    lock.lock()
    active = true
    lock.unlock()
    session.startRunning()
    guard session.isRunning else {
      stop()
      throw NSError(domain: "JarvisAudioInput", code: 3)
    }
  }

  func stop() {
    lock.lock()
    active = false
    lock.unlock()
    output.setSampleBufferDelegate(nil, queue: nil)
    session.stopRunning()
  }

  static func pcmBuffer(_ sample: CMSampleBuffer) -> AVAudioPCMBuffer? {
    let frames = CMSampleBufferGetNumSamples(sample)
    guard CMSampleBufferDataIsReady(sample), frames > 0, frames <= 192000,
      let description = CMSampleBufferGetFormatDescription(sample),
      let stream = CMAudioFormatDescriptionGetStreamBasicDescription(description),
      stream.pointee.mFormatID == kAudioFormatLinearPCM,
      stream.pointee.mChannelsPerFrame > 0, stream.pointee.mChannelsPerFrame <= 32,
      stream.pointee.mSampleRate.isFinite, stream.pointee.mSampleRate >= 8000,
      stream.pointee.mSampleRate <= 384000,
      let format = AVAudioFormat(streamDescription: stream),
      let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames))
    else { return nil }
    buffer.frameLength = AVAudioFrameCount(frames)
    guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0,
      frameCount: Int32(frames), into: buffer.mutableAudioBufferList) == noErr else { return nil }
    return buffer
  }

  func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
    from connection: AVCaptureConnection) {
    lock.lock()
    defer { lock.unlock() }
    guard active, let buffer = Self.pcmBuffer(sampleBuffer) else { return }
    receive(buffer)
  }
}
