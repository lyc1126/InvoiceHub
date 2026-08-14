import Foundation

struct RequiredAPIOperation: Equatable {
    let method: String
    let path: String

    var displayName: String {
        "\(method.uppercased()) \(path)"
    }
}

public final class InvoiceHubAPIClient {
    static let requiredPagePaths = ["/", "/costs", "/documents", "/bookkeeping", "/settings"]
    static let requiredAPIOperations = [
        RequiredAPIOperation(method: "get", path: "/api/v1/documents/state"),
        RequiredAPIOperation(method: "get", path: "/api/v1/bookkeeping/state"),
        RequiredAPIOperation(method: "get", path: "/api/v1/settings"),
        RequiredAPIOperation(method: "get", path: "/api/v1/preferences"),
        RequiredAPIOperation(method: "get", path: "/api/v1/about"),
        RequiredAPIOperation(method: "post", path: "/api/v1/update/check"),
        RequiredAPIOperation(method: "get", path: "/api/v1/diagnostics/config-health"),
        RequiredAPIOperation(method: "get", path: "/api/v1/skins"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/selection-summary"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/preview-jobs"),
        RequiredAPIOperation(method: "get", path: "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}"),
        RequiredAPIOperation(method: "get", path: "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/preview-jobs/{job_id}/keep-alive"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location"),
        RequiredAPIOperation(method: "post", path: "/api/v1/invoices/print-jobs"),
        RequiredAPIOperation(method: "get", path: "/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}"),
        RequiredAPIOperation(method: "get", path: "/invoices/print/{job_id}"),
        RequiredAPIOperation(method: "post", path: "/api/v1/server/shutdown")
    ]
    static let requiredAPIPaths = requiredAPIOperations.map(\.path)

    public let baseURL: URL
    private let session: URLSession
    private let healthSession: URLSession
    private let routeVerificationSession: URLSession

    public convenience init(baseURL: URL, session: URLSession = .shared) {
        self.init(
            baseURL: baseURL,
            session: session,
            sessionFactory: { URLSession(configuration: $0) }
        )
    }

    init(
        baseURL: URL,
        session: URLSession,
        sessionFactory: (URLSessionConfiguration) -> URLSession
    ) {
        self.baseURL = baseURL
        self.session = session
        let baseConfiguration = session.configuration
        let healthConfiguration = Self.boundedConfiguration(copying: baseConfiguration, timeout: 1)
        let routeConfiguration = Self.boundedConfiguration(copying: baseConfiguration, timeout: 5)
        healthSession = sessionFactory(healthConfiguration)
        routeVerificationSession = sessionFactory(routeConfiguration)
    }

    public func health() async -> BackendHealth? {
        do {
            let payload = try await getJSON("/api/v1/health", timeout: 1, using: healthSession)
            return BackendHealth(payload: payload)
        } catch {
            return nil
        }
    }

    public func verifyRequiredRoutes() async throws {
        for path in Self.requiredPagePaths {
            try await requireSuccess(path, using: routeVerificationSession)
        }
        let schema = try await getJSON("/openapi.json", timeout: 5, using: routeVerificationSession)
        guard let registeredPaths = schema["paths"] as? [String: Any] else {
            throw InvoiceHubAPIError.invalidJSON
        }
        let missing = Self.requiredAPIOperations.compactMap { operation -> String? in
            guard let pathItem = registeredPaths[operation.path] as? [String: Any],
                  pathItem[operation.method] != nil
            else {
                return operation.displayName
            }
            return nil
        }
        if !missing.isEmpty {
            throw InvoiceHubAPIError.missingRequiredRoutes(missing)
        }
    }

    public func settings() async throws -> [String: Any] {
        try await getJSON("/api/v1/settings")
    }

    public func preferences() async throws -> [String: Any] {
        try await getJSON("/api/v1/preferences")
    }

    public func bridgeStatus() async throws -> [String: Any] {
        try await getJSON("/api/v1/bridge/status")
    }

    public func documentsState() async throws -> [String: Any] {
        try await getJSON("/api/v1/documents/state")
    }

    public func validateOutboundDirectory(_ url: URL) async throws -> [String: Any] {
        try await sendJSON("POST", path: "/api/v1/documents/validate-outbound-dir", payload: ["outbound_invoice_dir": url.path])
    }

    public func updateWatchDirectory(_ url: URL) async throws -> [String: Any] {
        try await sendJSON("PUT", path: "/api/v1/settings", payload: ["watch_dir": url.path])
    }

    public func validateWatchDirectory(_ url: URL) async throws -> [String: Any] {
        try await sendJSON("POST", path: "/api/v1/settings/validate-watch-dir", payload: ["watch_dir": url.path])
    }

    public func startMonitor() async throws -> [String: Any] {
        try await sendJSON("POST", path: "/api/v1/bridge/start", payload: nil)
    }

    public func stopMonitor() async throws -> [String: Any] {
        try await sendJSON("POST", path: "/api/v1/bridge/stop", payload: nil)
    }

    public func rebuild() async throws -> [String: Any] {
        try await sendJSON("POST", path: "/api/v1/bridge/rebuild", payload: nil)
    }

    public func shutdownKeepingMonitor() async throws -> BackendShutdownResponse {
        let payload = try await sendJSON(
            "POST",
            path: "/api/v1/server/shutdown",
            payload: ["shutdown_behavior": "keep_monitor", "remember": false],
            timeout: 5
        )
        return try BackendShutdownResponse(payload: payload)
    }

    private func getJSON(
        _ path: String,
        timeout: TimeInterval = 10,
        using requestSession: URLSession? = nil
    ) async throws -> [String: Any] {
        var request = URLRequest(url: url(for: path))
        request.timeoutInterval = timeout
        let (data, response) = try await (requestSession ?? session).data(for: request)
        try validate(response: response, data: data)
        return try decodeObject(data)
    }

    private func requireSuccess(_ path: String, using requestSession: URLSession) async throws {
        var request = URLRequest(url: url(for: path))
        request.timeoutInterval = 5
        let (data, response) = try await requestSession.data(for: request)
        try validate(response: response, data: data)
    }

    private static func boundedConfiguration(
        copying configuration: URLSessionConfiguration,
        timeout: TimeInterval
    ) -> URLSessionConfiguration {
        let bounded = configuration.copy() as? URLSessionConfiguration ?? configuration
        bounded.timeoutIntervalForRequest = timeout
        bounded.timeoutIntervalForResource = timeout
        return bounded
    }

    private func sendJSON(
        _ method: String,
        path: String,
        payload: [String: Any]?,
        timeout: TimeInterval = 30
    ) async throws -> [String: Any] {
        var request = URLRequest(url: url(for: path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let payload {
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decodeObject(data)
    }

    private func url(for path: String) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        let trimmed = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + trimmed
        return components.url!
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw InvoiceHubAPIError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? ""
            throw InvoiceHubAPIError.httpStatus(http.statusCode, message)
        }
    }

    private func decodeObject(_ data: Data) throws -> [String: Any] {
        guard !data.isEmpty else {
            return [:]
        }
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw InvoiceHubAPIError.invalidJSON
        }
        return object
    }
}

public struct BackendShutdownResponse: Equatable {
    public let ok: Bool
    public let scheduled: Bool
    public let idempotent: Bool
    public let shutdownBehavior: String
    public let message: String

    public init(payload: [String: Any]) throws {
        guard let ok = payload["ok"] as? Bool else {
            throw InvoiceHubAPIError.invalidJSON
        }
        self.ok = ok
        scheduled = payload["scheduled"] as? Bool ?? false
        idempotent = payload["idempotent"] as? Bool ?? false
        shutdownBehavior = payload["shutdown_behavior"] as? String ?? ""
        message = payload["message"] as? String ?? ""
    }

    public var accepted: Bool {
        ok && (scheduled || idempotent) && shutdownBehavior == "keep_monitor"
    }
}

public enum InvoiceHubAPIError: LocalizedError, Equatable {
    case invalidResponse
    case invalidJSON
    case missingRequiredRoutes([String])
    case httpStatus(Int, String)

    public var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "本地服务返回了无效响应。"
        case .invalidJSON:
            return "本地服务返回的 JSON 无法解析。"
        case .missingRequiredRoutes(let paths):
            return "本地服务缺少必需接口: \(paths.joined(separator: ", "))"
        case .httpStatus(let code, let message):
            return "本地服务请求失败: HTTP \(code) \(message)"
        }
    }
}
