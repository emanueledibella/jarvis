import Foundation

@main
struct ListeningTurnTests {
  static func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    guard value() else { fatalError(message) }
  }

  static func main() {
    var turn = ListeningTurn()
    turn.begin("Organizza un viaggio")
    turn.update("Organizza un viaggio per Roma")
    expect(turn.text == "Organizza un viaggio per Roma", "Partial results replace the current task's hypothesis")
    turn.renewRecognition()
    turn.update("da venerdì")
    turn.update("da venerdì a domenica")
    expect(turn.text == "Organizza un viaggio per Roma da venerdì a domenica",
      "A final result or recoverable error must preserve the request across recognition tasks")
    turn.renewRecognition()
    turn.update("con due persone")
    expect(turn.text == "Organizza un viaggio per Roma da venerdì a domenica con due persone",
      "Multiple recognition renewals cannot erase or repeat the accepted prefix")
    expect(!turn.finished(at: 180, lastActivityAt: 179.8, endOfTurn: 0.9, waitForSpeech: 10),
      "An arbitrarily long active dictation must survive the old ten-second limit")
    expect(!turn.finished(at: 180, lastActivityAt: 179.2, endOfTurn: 0.9, waitForSpeech: 10),
      "A brief thinking pause does not submit the current prefix")
    expect(turn.finished(at: 181, lastActivityAt: 179.8, endOfTurn: 0.9, waitForSpeech: 10),
      "A completed request is submitted only after its configured quiet period")
    turn.begin()
    expect(turn.text.isEmpty, "A new turn, mute or privacy boundary clears the previous prefix")
    expect(!turn.finished(at: 100, lastActivityAt: 99, endOfTurn: 0.9, waitForSpeech: 10),
      "An empty wake-only turn has its full waiting window")
    expect(turn.finished(at: 111, lastActivityAt: 100, endOfTurn: 0.9, waitForSpeech: 10),
      "An abandoned wake-only turn returns to local wake listening")
    turn.update("Una nuova richiesta")
    expect(turn.text == "Una nuova richiesta", "Previous-session text cannot leak into the next request")
    print("10 native listening turn scenarios passed")
  }
}
