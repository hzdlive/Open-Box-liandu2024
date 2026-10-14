// swift-tools-version: 5.9
// OpenBoxCore: shared panel-API client, pairing, sync, Wi-Fi policy.
// Pure Foundation — no UI, no NetworkExtension dependency.
import PackageDescription

let package = Package(
    name: "OpenBoxCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "OpenBoxCore", targets: ["OpenBoxCore"]),
    ],
    targets: [
        .target(name: "OpenBoxCore", path: "Sources/OpenBoxCore"),
    ]
)
