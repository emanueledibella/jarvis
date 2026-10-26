import Foundation
import CryptoKit

final class LocalServiceFixture: URLProtocol {
    static var forged = true
    static var requests: [URLRequest] = []
    static let token = "local-service-test-fixture"
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requests.append(request)
        let url = request.url!
        var body: [String: Any] = ["state": "ready"]
        if url.path == "/health" {
            let challenge = URLComponents(url: url, resolvingAgainstBaseURL: true)!.queryItems!.first!.value!
            let code = HMAC<SHA256>.authenticationCode(for: Data("jarvis-health:8765:\(challenge)".utf8), using: SymmetricKey(data: Data(Self.token.utf8)))
            body = ["proof": Self.forged ? String(repeating: "0", count: 64) : code.map { String(format: "%02x", $0) }.joined()]
        }
        let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: body))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@main
struct ServiceTrustTests {
    static func main() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [LocalServiceFixture.self]
        let client = ServiceClient(base: URL(string: "http://127.0.0.1:8765")!, token: LocalServiceFixture.token, configuration: config)
        do {
            _ = try await client.request("/api/status")
            fatalError("An impostor must not receive the local bearer token")
        } catch ServiceClient.ClientError.unverifiedService {}
        precondition(LocalServiceFixture.requests.count == 1)
        precondition(LocalServiceFixture.requests[0].value(forHTTPHeaderField: "Authorization") == nil)
        LocalServiceFixture.forged = false
        LocalServiceFixture.requests = []
        let result = try await client.request("/api/status")
        precondition(result["state"] as? String == "ready")
        precondition(LocalServiceFixture.requests.count == 2)
        precondition(LocalServiceFixture.requests[0].value(forHTTPHeaderField: "Authorization") == nil)
        precondition(LocalServiceFixture.requests[1].value(forHTTPHeaderField: "Authorization") == "Bearer " + LocalServiceFixture.token)
        LocalServiceFixture.requests = []
        do {
            _ = try await client.request("//example.com/leak")
            fatalError("A service path must stay on the configured origin")
        } catch ServiceClient.ClientError.invalidURL {}
        precondition(LocalServiceFixture.requests.isEmpty)
        precondition(!ServiceTrust.sameOrigin(URL(string: "http://127.0.0.1:9000")!, client.base))
        print("3 native service authentication scenarios passed")
    }
}
