import Foundation

/// Mirrors docs/client-api.md and the tested /api/client/* surface.
public struct ClientStatus: Codable, Sendable {
    public let running: Bool
    public let version: String?
    public let uptimeS: Double?
    public let mode: String
    public let rev: Int

    enum CodingKeys: String, CodingKey {
        case running, version, mode, rev
        case uptimeS = "uptime_s"
    }
}

public struct NodeInfo: Codable, Sendable, Identifiable {
    public var id: String { tag }
    public let tag: String
    public let `protocol`: String
    public let server: String
    public let port: Int
    public let latencyMs: Double?
    public let ok: Bool?

    enum CodingKeys: String, CodingKey {
        case tag, `protocol`, server, port, ok
        case latencyMs = "latency_ms"
    }
}

public struct GroupInfo: Codable, Sendable {
    public let name: String
    public let type: String
    public let members: [String]
}

public struct PairCode: Codable, Sendable {
    public let token: String
    public let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case token
        case expiresIn = "expires_in"
    }
}

public struct PairResult: Codable, Sendable {
    public let clientToken: String
    public let deviceId: Int64

    enum CodingKeys: String, CodingKey {
        case clientToken = "client_token"
        case deviceId = "device_id"
    }
}

public struct SyncPullResult: Codable, Sendable {
    public let rev: Int
    public let nodes: [NodeInfo]
}

public struct SyncPushResult: Codable, Sendable {
    public let added: Int
    public let rev: Int
}

public struct WifiPolicy: Codable, Sendable {
    public var enabled: Bool = false
    public var pauseSsids: [String] = []
    public var action: String = "pause" // pause | direct

    enum CodingKeys: String, CodingKey {
        case enabled, action
        case pauseSsids = "pause_ssids"
    }
}

public enum ProxyMode: String, Sendable, CaseIterable {
    case global, rule, direct
}
