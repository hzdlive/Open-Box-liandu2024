import Foundation
import Security

/// Keychain-backed token + base-URL storage. Nothing sensitive touches
/// UserDefaults.
public final class TokenStore: Sendable {
    private let service = "com.openbox.oss"
    private let accountToken = "client_token"
    private let accountBase = "panel_base_url"

    public init() {}

    public func clientToken() -> String? { read(accountToken) }
    public func save(_ token: String) { write(token, accountToken) }
    public func clear() { delete(accountToken) }

    public func baseURL() -> String? { read(accountBase) }
    public func saveBaseURL(_ url: String) { write(url, accountBase) }

    public func isPaired() -> Bool { clientToken() != nil && baseURL() != nil }

    // MARK: - Keychain plumbing

    private func query(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    private func read(_ account: String) -> String? {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func write(_ value: String, _ account: String) {
        let data = Data(value.utf8)
        var q = query(account)
        if SecItemCopyMatching(q as CFDictionary, nil) == errSecSuccess {
            SecItemUpdate(q as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        } else {
            q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
            SecItemAdd(q as CFDictionary, nil)
        }
    }

    private func delete(_ account: String) {
        SecItemDelete(query(account) as CFDictionary)
    }
}
