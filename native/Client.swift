import Foundation
import CryptoKit

enum ServiceTrust {
    static func sameOrigin(_ url: URL, _ base: URL) -> Bool {
        url.scheme == base.scheme && url.host == base.host && (url.port ?? 80) == (base.port ?? 80) && url.user == nil && url.password == nil
    }

    static func validProof(_ proof: String, token: String, port: Int, challenge: String) -> Bool {
        guard proof.count == 64 else { return false }
        var bytes = Data()
        var offset = proof.startIndex
        while offset < proof.endIndex {
            let end = proof.index(offset, offsetBy: 2)
            guard let byte = UInt8(proof[offset..<end], radix: 16) else { return false }
            bytes.append(byte)
            offset = end
        }
        return HMAC<SHA256>.isValidAuthenticationCode(bytes, authenticating: Data("jarvis-health:\(port):\(challenge)".utf8), using: SymmetricKey(data: Data(token.utf8)))
    }
}

private final class NoServiceRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

final class ServiceClient {
    let base: URL
    let token: String
    private let session: URLSession

    init(base: URL, token: String, configuration: URLSessionConfiguration? = nil) {
        self.base = base
        self.token = token
        let configuration = configuration ?? URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 130
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.connectionProxyDictionary = [:]
        self.session = URLSession(configuration: configuration, delegate: NoServiceRedirects(), delegateQueue: nil)
    }

    func authenticateService() async throws -> [String: Any] {
        let challenge = UUID().uuidString.replacingOccurrences(of: "-", with: "")
        guard let url = URL(string: "/health?challenge=" + challenge, relativeTo: base) else { throw ClientError.invalidURL }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 6)
        request.httpMethod = "GET"
        let (stream, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.statusCode == 200,
              let final = response.url, ServiceTrust.sameOrigin(final, base) else { throw ClientError.unverifiedService }
        var data = Data()
        for try await byte in stream {
            guard data.count < 4096 else { throw ClientError.unverifiedService }
            data.append(byte)
        }
        guard let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let proof = result["proof"] as? String,
              ServiceTrust.validProof(proof, token: token, port: base.port ?? 80, challenge: challenge) else {
            throw ClientError.unverifiedService
        }
        return result
    }

    func request(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> [String: Any] {
        guard path.hasPrefix("/"), !path.hasPrefix("//"), let url = URL(string: path, relativeTo: base), ServiceTrust.sameOrigin(url, base) else { throw ClientError.invalidURL }
        let health = try await authenticateService()
        if path == "/health" { return health }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body = body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else {
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw ClientError.server(object?["detail"] as? String ?? "The service is not responding correctly.")
        }
        return ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
    }

    enum ClientError: LocalizedError {
        case invalidURL
        case unverifiedService
        case server(String)
        var errorDescription: String? {
            switch self {
            case .invalidURL: return "Invalid service address."
            case .unverifiedService: return "The local service could not be verified. No token was sent."
            case .server(let text): return text
            }
        }
    }
}
