import SwiftUI
import OpenBoxCore
import NetworkExtension

struct ContentView: View {
    @ObservedObject var session: Session
    @State private var status: String = "…"
    @State private var mode: ProxyMode = .rule
    @State private var vpnOn = false

    var body: some View {
        NavigationStack {
            List {
                Section("状态") { Text(status).font(.footnote).monospaced() }
                Section("代理") {
                    Button(vpnOn ? "停止" : "启动") { toggleVPN() }
                    Picker("模式", selection: $mode) {
                        Text("规则").tag(ProxyMode.rule)
                        Text("全局").tag(ProxyMode.global)
                        Text("直连").tag(ProxyMode.direct)
                    }
                    .onChange(of: mode) { _, m in setMode(m) }
                }
                Section("同步") {
                    Button("立即同步订阅") { Task { await syncNow() } }
                }
                Section("配对") {
                    Button("解除配对", role: .destructive) { session.unpair() }
                }
            }
            .navigationTitle("OpenBox OSS")
            .task { await refresh() }
            // share-link deep links: openbox:// ss:// vless:// …
            .onOpenURL { url in Task { await importLink(url.absoluteString) } }
        }
    }

    private func refresh() async {
        guard let api = session.api else { return }
        do {
            let s = try await api.status()
            let m = try await api.mode()
            status = "running=\(s.running) rev=\(s.rev)"
            mode = m
        } catch {
            status = "panel unreachable"
        }
    }

    private func setMode(_ m: ProxyMode) {
        Task {
            try? await session.api?.setMode(m)
            // Push the fresh client config to the tunnel for next start.
            await writeClientConfig()
        }
    }

    private func syncNow() async {
        guard let api = session.api else { return }
        do {
            let mgr = SyncManager(api: api)
            let nodes = try await mgr.sync()
            status = "synced \(nodes.count) new nodes"
        } catch {
            status = "sync failed"
        }
    }

    private func importLink(_ link: String) async {
        guard let api = session.api else { return }
        do {
            let r = try await api.syncPush(name: "import", content: link)
            status = "imported \(r.added) node(s)"
        } catch {
            status = "import failed"
        }
    }

    /// Writes the panel-generated client config into the App Group so the
    /// PacketTunnelProvider can read it on next start.
    private func writeClientConfig() async {
        guard let api = session.api,
              let dir = FileManager.default.containerURL(
                forSecurityApplicationGroupIdentifier: "group.com.openbox.oss") else { return }
        do {
            let data = try await api.clientConfig(mode: mode)
            try data.write(to: dir.appendingPathComponent("client-config.json"))
        } catch { /* surface in UI in production */ }
    }

    private func toggleVPN() {
        // Production: load NETunnelProviderManager with the tunnel bundle id
        // and flip isEnabled / startVPNTunnel. Kept minimal here.
        vpnOn.toggle()
    }
}
