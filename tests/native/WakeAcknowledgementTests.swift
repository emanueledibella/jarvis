import Foundation

@main
struct WakeAcknowledgementTests {
  static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { fatalError(message) }
  }

  static func main() throws {
    var reply = WakeAcknowledgement()
    reply.begin(at: 10, hasRequest: false)
    expect(!reply.take(at: 10.2, lastSoundAt: 10), "Do not interrupt the natural pause immediately after the wake word")
    expect(reply.take(at: 10.35, lastSoundAt: 10), "A lone wake word gets one prompt local acknowledgment")
    expect(!reply.take(at: 10.5, lastSoundAt: 10), "Do not acknowledge the same wake twice")

    reply.begin(at: 20, hasRequest: true)
    expect(!reply.take(at: 20.35, lastSoundAt: 20), "An inline request must never get a listening invitation")
    reply.begin(at: 30, hasRequest: false)
    reply.heardRequest()
    expect(!reply.take(at: 30.4, lastSoundAt: 30), "A partial command cancels the pending acknowledgment")
    reply.begin(at: 40, hasRequest: false)
    reply.heardSound(at: 40.15)
    expect(!reply.take(at: 40.7, lastSoundAt: 40.15), "New microphone activity cancels the cue even before transcription arrives")

    reply.begin(at: 50, hasRequest: false)
    expect(!reply.take(at: 51.1, lastSoundAt: 50), "Late wake recognition must skip its opportunity rather than speak later")
    expect(!reply.take(at: 51.2, lastSoundAt: 50), "An expired opportunity cannot be revived by silence")
    reply.begin(at: 60, hasRequest: false)
    expect(!reply.take(at: 60.31, lastSoundAt: 60.2), "A recently active microphone is not a quiet invitation window")
    reply.cancel()
    expect(!reply.take(at: 60.6, lastSoundAt: 60.2), "Mute, lock, profile and privacy changes cancel a pending cue")

    expect(WakeAcknowledgement.language(response: "auto", fallback: "it-IT") == "it", "Automatic acknowledgments use the voice locale, not the interface language")
    expect(WakeAcknowledgement.language(response: "en-GB", fallback: "it-IT") == "en", "A fixed English response preference selects the English cue")
    expect(WakeAcknowledgement.language(response: "fr-FR", fallback: "it-IT") == nil, "Do not play an acknowledgment in the wrong unsupported language")
    expect(WakeAcknowledgement.isCueOnlyOrPrefix("Dim"), "A partial echo cannot open an unwanted cloud session")
    expect(WakeAcknowledgement.isCueOnlyOrPrefix("Dimmi."), "Delayed local cue transcripts remain non-requests")
    expect(!WakeAcknowledgement.isCueOnlyOrPrefix("Dimmi che ore sono"), "A real request following the cue must remain intact")
    print("16 native wake acknowledgment scenarios passed")
  }
}
