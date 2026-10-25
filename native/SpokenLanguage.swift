import NaturalLanguage

enum SpokenLanguage {
  static func select(for text: String, response: String, fallback: String) -> String {
    let recognizer = NLLanguageRecognizer()
    recognizer.processString(text)
    if let candidate = recognizer.languageHypotheses(withMaximum: 1).first,
      candidate.value >= 0.6
    {
      return candidate.key.rawValue
    }
    return response == "auto" ? fallback : response
  }
}
