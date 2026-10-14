import SwiftUI
import OpenBoxCore

@main
struct OpenBoxApp: App {
    @StateObject private var session = Session()

    var body: some Scene {
        WindowGroup {
            if session.isPaired {
                ContentView(session: session)
            } else {
                PairingView(session: session)
            }
        }
    }
}

/// Holds the paired API client for the UI.
@MainActor
final class Session: ObservableObject {
    let store = TokenStore()
    @Published var isPaired: Bool
    @Published var api: PanelAPI?

    init() {
        let paired = store.isPaired()
        self.isPaired = paired
        if paired, let base = store.baseURL() {
            self.api = PanelAPI(baseURL: base, tokenStore: store)
        }
    }

    func completePairing(baseURL: String) {
        store.saveBaseURL(baseURL)
        api = PanelAPI(baseURL: baseURL, tokenStore: store)
        isPaired = true
    }

    func unpair() {
        store.clear()
        api = nil
        isPaired = false
    }
}
