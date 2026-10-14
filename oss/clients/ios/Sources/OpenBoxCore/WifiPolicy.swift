import Foundation
import OpenBoxCore
import SystemConfiguration.CaptiveNetwork

/// Wi-Fi auto-pause policy evaluation (documented client behavior).
///
/// iOS constraints (honest): continuous background SSID monitoring like
/// Android is not available. SSID reads need the `wifi-info` entitlement
/// (com.apple.developer.networking.wifi-info) + Location permission, and
/// evaluation happens when the app is foregrounded or woken by the tunnel.
/// NEHotspotHelper would allow more but needs a special Apple entitlement.
public enum WifiPolicyEvaluator {
    public static func currentSSID() -> String? {
        guard let ifs = CNCopySupportedInterfaces() as? [String] else { return nil }
        for name in ifs {
            guard let info = CNCopyCurrentNetworkInfo(name as CFString) as? [String: Any],
                  let ssid = info[kCNNetworkInfoKeySSID as String] as? String else { continue }
            return ssid
        }
        return nil
    }

    /// Returns true when the VPN should pause right now.
    public static func shouldPause(policy: WifiPolicy) -> Bool {
        guard policy.enabled else { return false }
        guard let ssid = currentSSID() else { return false }
        return policy.pauseSsids.contains(ssid)
    }
}
