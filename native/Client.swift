import Foundation

final class ServiceClient {
    let base: URL
    let token: String
    private let session: URLSession

    init(base: URL, token: String) {
        self.base = base
        self.token = token
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 130
        self.session = URLSession(configuration: configuration)
    }

    func request(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> [String: Any] {
        guard let url = URL(string: path, relativeTo: base) else { throw ClientError.invalidURL }
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
            throw ClientError.server(object?["detail"] as? String ?? "Il servizio non risponde correttamente.")
        }
        return ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any]) ?? [:]
    }

    enum ClientError: LocalizedError {
        case invalidURL
        case server(String)
        var errorDescription: String? {
            switch self {
            case .invalidURL: return "Indirizzo del servizio non valido."
            case .server(let text): return text
            }
        }
    }
}
