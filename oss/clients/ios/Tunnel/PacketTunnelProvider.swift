import NetworkExtension
import os

/**
 * Packet tunnel provider. Mirrors the documented client behavior: the app
 * owns a utun interface and feeds packets to the sing-box core.
 *
 * The core comes from the GPL source bundle built via gomobile for iOS
 * (Libbox.xcframework, see clients/README.md). [startCore] is the single
 * integration seam: hand it the utun fd + client config path.
 *
 * Target setup (Xcode): new "Network Extension → Packet Tunnel Provider"
 * target, add this file, enable the NetworkExtension entitlement and the
 * App Group shared with the main app.
 */
class PacketTunnelProvider: NEPacketTunnelProvider {

    private let log = Logger(subsystem: "com.openbox.oss", category: "tunnel")
    // private var box: LibboxTunnel? // from Libbox.xcframework once added

    override func startTunnel(options: [String: NSObject]?,
                              completionHandler: @escaping (Error?) -> Void) {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "10.8.0.1")
        settings.mtu = 1500
        let v4 = NEIPv4Settings(addresses: ["10.8.0.2"], subnetMasks: ["255.255.255.0"])
        v4.includedRoutes = [NEIPv4Route.default()]
        v4.excludedRoutes = [
            // Keep the panel reachable directly so the tunnel can't strand us.
            // (Refine with the actual panel subnet at runtime.)
        ]
        settings.iPv4Settings = v4
        settings.dnsSettings = NEDNSSettings(servers: ["10.8.0.1"])

        setTunnelNetworkSettings(settings) { [weak self] error in
            guard let self else { completionHandler(error); return }
            if let error { completionHandler(error); return }
            do {
                let fd = try self.packetFlow.value(forKey: "socket") as? Int32
                let configPath = self.sharedConfigPath()
                try self.startCore(tunFd: fd ?? -1, configPath: configPath)
                completionHandler(nil)
            } catch {
                self.log.error("core start failed: \(error.localizedDescription)")
                completionHandler(error)
            }
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason,
                             completionHandler: @escaping () -> Void) {
        // box?.stop()
        completionHandler()
    }

    /// Config JSON written by the main app into the shared App Group.
    private func sharedConfigPath() -> String {
        let dir = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: "group.com.openbox.oss")!
        return dir.appendingPathComponent("client-config.json").path
    }

    /**
     * Integration seam for Libbox.xcframework (gomobile).
     * Adapt to the generated bindings, e.g. `LibboxStart(tunFd, configPath)`.
     */
    private func startCore(tunFd: Int32, configPath: String) throws {
        // TODO: wire Libbox.xcframework once built from the GPL source bundle.
        log.info("tunnel up (stub core), config: \(configPath)")
    }

    override func handleAppMessage(_ messageData: Data,
                                   completionHandler: ((Data?) -> Void)?) {
        // e.g. mode switches forwarded from the app: {"mode":"global"}
        completionHandler?(nil)
    }
}
