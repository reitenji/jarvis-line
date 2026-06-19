// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "JarvisLine",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "JarvisLine", targets: ["JarvisLine"]),
    ],
    targets: [
        .executableTarget(
            name: "JarvisLine",
            path: "Sources"
        ),
    ]
)
