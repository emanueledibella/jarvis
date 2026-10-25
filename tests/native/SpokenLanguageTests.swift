import Foundation

@main
struct SpokenLanguageTests {
  static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
  }

  static func main() {
    expect(
      SpokenLanguage.select(
        for: "Buongiorno, vorrei sapere quali impegni ho nel calendario domani mattina.",
        response: "auto", fallback: "en-GB") == "it",
      "Italian responses must select an Italian system voice")
    expect(
      SpokenLanguage.select(
        for: "Good morning, please check my calendar and tell me what meetings I have tomorrow.",
        response: "auto", fallback: "it-IT") == "en",
      "English responses must select an English system voice")
    expect(
      SpokenLanguage.select(for: "", response: "it-IT", fallback: "en-GB") == "it-IT",
      "The preferred response language is the first fallback for uncertain text")
    expect(
      SpokenLanguage.select(
        for: "Please check my calendar and tell me what meetings I have tomorrow morning.",
        response: "it-IT", fallback: "it-IT") == "en",
      "A user-requested language switch must use the language of the actual response")
    expect(
      SpokenLanguage.select(for: "", response: "auto", fallback: "it-IT") == "it-IT",
      "Uncertain text uses the configured recognition-language fallback")
    print("5 native spoken language scenarios passed")
  }
}
