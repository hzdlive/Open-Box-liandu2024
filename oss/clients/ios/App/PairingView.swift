import SwiftUI
import OpenBoxCore
import AVFoundation

/// Pairing screen. QR scanning via AVFoundation (no third-party dependency);
/// manual paste supported as fallback.
struct PairingView: View {
    @ObservedObject var session: Session
    @State private var manualURL = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                Text("扫描面板「设置 → 客户端配对」的二维码")
                    .font(.headline)
                // TODO: wire AVCaptureSession + AVCaptureMetadataOutput
                // (metadataObjectTypes = [.qr]) and feed results into pair(_:).
                TextField("或粘贴 openbox://pair?… 链接", text: $manualURL)
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                Button("配对") { pair(manualURL) }
                    .buttonStyle(.borderedProminent)
                if let error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
                Spacer()
            }
            .padding()
            .navigationTitle("配对")
        }
    }

    private func pair(_ urlString: String) {
        Task {
            do {
                let (baseURL, token) = try PanelAPI.parsePairURL(urlString)
                let store = session.store
                let api = PanelAPI(baseURL: baseURL, tokenStore: store)
                _ = try await api.pairConfirm(oneTimeToken: token,
                                              deviceName: UIDevice.current.name)
                await MainActor.run { session.completePairing(baseURL: baseURL) }
            } catch {
                await MainActor.run { self.error = "配对失败：\(error)" }
            }
        }
    }
}
