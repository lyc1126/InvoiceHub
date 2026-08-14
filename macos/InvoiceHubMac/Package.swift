// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "InvoiceHubMac",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "InvoiceHubMac", targets: ["InvoiceHubMac"]),
        .library(name: "InvoiceHubClient", targets: ["InvoiceHubClient"])
    ],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", exact: "2.9.2")
    ],
    targets: [
        .target(
            name: "InvoiceHubClient",
            dependencies: [
                .product(name: "Sparkle", package: "Sparkle")
            ],
            path: "Sources/InvoiceHubClient"
        ),
        .executableTarget(
            name: "InvoiceHubMac",
            dependencies: ["InvoiceHubClient"],
            path: "Sources/InvoiceHubMac"
        ),
        .testTarget(
            name: "InvoiceHubClientTests",
            dependencies: ["InvoiceHubClient"],
            path: "Tests/InvoiceHubClientTests"
        )
    ]
)
