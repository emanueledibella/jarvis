@preconcurrency import AVFoundation
import SoundAnalysis

// The built-in classifier runs locally, off the audio tap. Its input is already
// echo-cancelled by VoiceProcessingIO; raw loudness alone is not an interruption.
final class SpeechActivityDetector: NSObject, SNResultsObserving, @unchecked Sendable {
  private let queue = DispatchQueue(label: "it.jarvis.personal.speech-activity", qos: .userInitiated)
  private let lock = NSLock()
  private let analyzer: SNAudioStreamAnalyzer
  private var active = true
  private var queuedFrames = 0
  private let onSpeech: @Sendable (Int64, Int64, Double) -> Void
  private let onFailure: @Sendable () -> Void

  init(onSpeech: @escaping @Sendable (Int64, Int64, Double) -> Void,
       onFailure: @escaping @Sendable () -> Void) throws {
    self.onSpeech = onSpeech
    self.onFailure = onFailure
    analyzer = SNAudioStreamAnalyzer(format: LiveAudioBuffer.format)
    super.init()
    let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
    guard request.knownClassifications.contains("speech") else {
      throw ServiceClient.ClientError.server("Local speech activity detection is unavailable.")
    }
    request.windowDuration = CMTime(seconds: 0.5, preferredTimescale: 24000)
    request.overlapFactor = 0.75
    try analyzer.add(request, withObserver: self)
  }

  func append(_ buffer: AVAudioPCMBuffer, atFrame frame: Int64) {
    let count = Int(buffer.frameLength)
    lock.lock()
    guard active else { lock.unlock(); return }
    guard queuedFrames + count <= 24000 else {
      active = false
      lock.unlock()
      onFailure()
      return
    }
    queuedFrames += count
    lock.unlock()
    queue.async { [self] in
      lock.lock()
      let run = active
      lock.unlock()
      if run { analyzer.analyze(buffer, atAudioFramePosition: frame) }
      lock.lock()
      queuedFrames -= count
      lock.unlock()
    }
  }

  func cancel() {
    lock.lock()
    active = false
    lock.unlock()
    queue.async { [self] in analyzer.removeAllRequests() }
  }

  func request(_ request: SNRequest, didProduce result: SNResult) {
    guard let result = result as? SNClassificationResult,
      let speech = result.classification(forIdentifier: "speech") else { return }
    lock.lock()
    let run = active
    lock.unlock()
    if run {
      let start = CMTimeGetSeconds(result.timeRange.start)
      let end = CMTimeGetSeconds(CMTimeRangeGetEnd(result.timeRange))
      guard start.isFinite, end.isFinite, start >= 0, end >= start else { return }
      onSpeech(Int64(start * 24000), Int64(end * 24000), speech.confidence)
    }
  }

  func request(_ request: SNRequest, didFailWithError error: Error) {
    cancel()
    onFailure()
  }
}
