import Foundation

enum ArtifactDownloadPolicy {
    static func allows(url: URL, source: URL?, service: URL, mainFrame: Bool, download: Bool) -> Bool {
        guard mainFrame, download, url.scheme == "blob", let source,
              let contentOrigin = URL(string: String(url.absoluteString.dropFirst(5))) else { return false }
        func sameOrigin(_ value: URL) -> Bool {
            value.scheme == "http" && value.host == service.host && value.port == service.port
                && value.user == nil && value.password == nil
        }
        return sameOrigin(source) && sameOrigin(contentOrigin)
    }
}
