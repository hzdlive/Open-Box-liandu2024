import Foundation

/// Pull-based subscription sync (docs/client-api.md §5).
/// Pushes originate from the share-link import UI directly.
public final class SyncManager: Sendable {
    private let api: PanelAPI
    private let revKey = "openbox.client_rev"

    public init(api: PanelAPI) {
        self.api = api
    }

    /// Returns the pulled nodes (empty when nothing changed).
    @discardableResult
    public func sync() async throws -> [NodeInfo] {
        let lastRev = UserDefaults.standard.integer(forKey: revKey)
        let res = try await api.syncPull(clientRev: lastRev)
        if res.rev != lastRev {
            UserDefaults.standard.set(res.rev, forKey: revKey)
        }
        // TODO: upsert res.nodes into the local cache (SwiftData) for offline UI.
        return res.nodes
    }
}
