import Foundation

@main struct ArtifactDownloadPolicyTests {
    static func main() {
        let service = URL(string: "http://127.0.0.1:8765")!
        let blob = URL(string: "blob:http://127.0.0.1:8765/fixture")!
        func permitted(_ value: String, source: URL? = nil, frame: Bool = true, download: Bool = true) -> Bool {
            ArtifactDownloadPolicy.allows(url: URL(string: value)!, source: source ?? service,
                                          service: service, mainFrame: frame, download: download)
        }
        precondition(permitted(blob.absoluteString))
        precondition(!permitted(blob.absoluteString, frame: false))
        precondition(!permitted(blob.absoluteString, download: false))
        precondition(!permitted(blob.absoluteString, source: URL(string: "https://example.com")!))
        precondition(!permitted("blob:http://127.0.0.1:9999/fixture"))
        precondition(!permitted("blob:http://127.0.0.1:8765@evil.example/fixture"))
        precondition(!permitted("blob:http://user@127.0.0.1:8765/fixture"))
        precondition(!permitted("https://example.com/file.csv"))
        precondition(!permitted("file:///tmp/fixture"))
        precondition(!ArtifactDownloadPolicy.allows(url: blob, source: nil, service: service, mainFrame: true, download: true))
        print("Artifact download policy: 10 scenarios passed")
    }
}
