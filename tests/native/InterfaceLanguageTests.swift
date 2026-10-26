import Foundation

@main
struct InterfaceLanguageTests {
    static func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }

    static func main() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let messages = try JSONSerialization.jsonObject(with: data) as! [String: String]
        expect(InterfaceLanguage.configured(nil) == .english, "Existing installs default to English")
        expect(InterfaceLanguage.configured("it") == .italian, "Italian is supported")
        expect(InterfaceLanguage.configured("../it") == .english, "Arbitrary locale paths are rejected")
        expect(InterfaceLanguage.italian.text("Open Jarvis", messages: messages) == "Apri Jarvis", "Native menus use the shared Italian catalog")
        expect(InterfaceLanguage.english.text("Open Jarvis", messages: messages) == "Open Jarvis", "Switching back restores English")
        expect(InterfaceLanguage.italian.text("provider diagnostic", messages: messages) == "provider diagnostic", "Unknown diagnostics remain unchanged")
        print("6 native interface language scenarios passed")
    }
}
