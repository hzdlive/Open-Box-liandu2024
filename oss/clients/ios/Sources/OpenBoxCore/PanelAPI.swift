import Foundation

/// HTTP client for the panel API (docs/client-api.md).
/// Auth: Bearer <client_token> from the pairing flow. Tokens live in the
/// Keychain via ``TokenStore`` and are never logged.
public final class PanelAPI: Sendable {
    private let baseURL: String
    private let tokenStore: TokenStore
    private let session: URLSession
    private let decoder: JSONDecoder

    public init(baseURL: String, tokenStore: TokenStore) {
        self.baseURL = baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL
        self.tokenStore = tokenStore
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 30
        cfg.timeoutIntervalForResource = 60
        self.session = URLSession(configuration: cfg)
        self.decoder = JSONDecoder()
    }

    private func request(_ path: String, method: String = "GET",
                        body: Data? = nil, authed: Bool = true) throws -> URLRequest {
        guard let url = URL(string: baseURL + path) else { throw APIError.badURL }
        var r = URLRequest(url: url)
        r.httpMethod = method
        if authed {
            guard let tok = tokenStore.clientToken() else { throw APIError.notPaired }
            r.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            r.httpBody = body
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return r
    }

    private func call<T: Decodable>(_ path: String, method: String = "GET",
                                    body: Data? = nil, authed: Bool = true) async throws -> T {
        let (data, resp) = try await session.data(for: request(path, method: method, body: body, authed: authed))
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? -1)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func callRaw(_ path: String, method: String = "GET",
                         body: Data? = nil, authed: Bool = true) async throws -> Data {
        let (data, resp) = try await session.data(for: request(path, method: method, body: body, authed: authed))
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw APIError.http((resp as? HTTPURLResponse)?.statusCode ?? -1)
        }
        return data
    }

    private func jsonBody(_ dict: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: dict)
    }

    // MARK: - Pairing (no auth; the one-time code is the credential)

    public func pairCode() async throws -> PairCode {
        try await call("/api/pair/code", method: "POST",
                       body: jsonBody([:]), authed: false)
    }

    /// Parses an `openbox://pair?host=…&port=…&token=…` URL.
    public static func parsePairURL(_ s: String) throws -> (baseURL: String, token: String) {
        guard let comps = URLComponents(string: s),
              let host = comps.queryItems?.first(where: { $0.name == "host" })?.value,
              let token = comps.queryItems?.first(where: { $0.name == "token" })?.value else {
            throw APIError.badPairURL
        }
        let port = comps.queryItems?.first(where: { $0.name == "port" })?.value ?? "8080"
        return ("http://\(host):\(port)", token)
    }

    @discardableResult
    public func pairConfirm(oneTimeToken: String, deviceName: String) async throws -> PairResult {
        let res: PairResult = try await call(
            "/api/pair/confirm", method: "POST",
            body: jsonBody(["token": oneTimeToken, "device": deviceName]), authed: false)
        tokenStore.save(res.clientToken)
        return res
    }

    // MARK: - Client API

    public func status() async throws -> ClientStatus {
        try await call("/api/client/status")
    }

    public func nodes() async throws -> [NodeInfo] {
        try await call("/api/client/nodes")
    }

    public func groups() async throws -> [GroupInfo] {
        try await call("/api/client/groups")
    }

    public func selectOutbound(group: String, tag: String) async throws {
        _ = try await callRaw("/api/client/groups/\(group)/select",
                              method: "POST", body: jsonBody(["tag": tag]))
    }

    /// Raw client sing-box config JSON (feeds the tunnel provider).
    public func clientConfig(mode: ProxyMode, ruleset: String = "follow") async throws -> Data {
        try await callRaw("/api/client/config?mode=\(mode.rawValue)&ruleset=\(ruleset)")
    }

    public func mode() async throws -> ProxyMode {
        struct M: Decodable { let mode: String }
        let m: M = try await call("/api/client/mode")
        return ProxyMode(rawValue: m.mode) ?? .rule
    }

    public func setMode(_ mode: ProxyMode) async throws {
        _ = try await callRaw("/api/client/mode", method: "POST",
                              body: jsonBody(["mode": mode.rawValue]))
    }

    public func syncPull(clientRev: Int) async throws -> SyncPullResult {
        try await call("/api/client/subscriptions/sync", method: "POST",
                       body: jsonBody(["direction": "pull", "client_rev": clientRev]))
    }

    public func syncPush(name: String, content: String) async throws -> SyncPushResult {
        try await call("/api/client/subscriptions/sync", method: "POST",
                       body: jsonBody(["direction": "push", "name": name,
                                       "content": content, "format": "auto"]))
    }

    public func wifiPolicy() async throws -> WifiPolicy {
        try await call("/api/client/wifi-policy")
    }
}

public enum APIError: Error, Sendable {
    case badURL
    case badPairURL
    case notPaired
    case http(Int)
}
