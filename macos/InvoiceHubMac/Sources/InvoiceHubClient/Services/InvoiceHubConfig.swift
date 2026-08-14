import Foundation

public enum InvoiceHubConfig {
    public static func ensureDefaultConfig(paths: BackendPaths, preferredPort: Int = 8766, fileManager: FileManager = .default) throws -> Int {
        try paths.ensureWritableLayout(fileManager: fileManager)
        if fileManager.fileExists(atPath: paths.configPath.path) {
            return try existingPort(at: paths.configPath) ?? preferredPort
        }

        let watchDir = paths.appSupportRoot.appendingPathComponent("发票文件", isDirectory: true)
        try fileManager.createDirectory(at: watchDir, withIntermediateDirectories: true)
        let payload = defaultPayload(watchDir: watchDir, runtimeDir: paths.runtimeDir, port: preferredPort)
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try data.write(to: paths.configPath, options: .atomic)
        return preferredPort
    }

    public static func defaultPayload(watchDir: URL, runtimeDir: URL, port: Int) -> [String: Any] {
        [
            "host": "127.0.0.1",
            "port": port,
            "watch_dir": watchDir.path,
            "runtime_dir": runtimeDir.path,
            "reference_markup_rate": "0.08",
            "recent_watch_dirs": [],
            "release_capabilities": ["local_ocr": false]
        ]
    }

    private static func existingPort(at url: URL) throws -> Int? {
        let data = try Data(contentsOf: url)
        guard
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
            let port = object["port"] as? Int
        else {
            return nil
        }
        return port
    }
}
