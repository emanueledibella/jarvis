import Foundation

enum InterfaceLanguage: String {
    case english = "en"
    case italian = "it"

    static func configured(_ value: String?) -> InterfaceLanguage {
        InterfaceLanguage(rawValue: value ?? "") ?? .english
    }

    func text(_ source: String, messages: [String: String]) -> String {
        self == .italian ? messages[source] ?? source : source
    }

    static func messages(bundle: Bundle = .main) -> [String: String] {
        guard let url = bundle.url(forResource: "Interface.it", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let messages = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            return [:]
        }
        return messages
    }
}
