import Foundation

public struct BackendPaths: Equatable {
    public let coreRoot: URL
    public let resourceRoot: URL?
    public let appSupportRoot: URL
    public let configPath: URL
    public let runtimeDir: URL
    public let stdoutLog: URL
    public let stderrLog: URL
    public let serverPID: URL

    public init(
        coreRoot: URL,
        resourceRoot: URL?,
        appSupportRoot: URL,
        configPath: URL,
        runtimeDir: URL,
        stdoutLog: URL,
        stderrLog: URL,
        serverPID: URL
    ) {
        self.coreRoot = coreRoot
        self.resourceRoot = resourceRoot
        self.appSupportRoot = appSupportRoot
        self.configPath = configPath
        self.runtimeDir = runtimeDir
        self.stdoutLog = stdoutLog
        self.stderrLog = stderrLog
        self.serverPID = serverPID
    }

    public static func resolve(
        fileManager: FileManager = .default,
        startingAt start: URL? = nil,
        bundleResourceURL: URL? = Bundle.main.resourceURL,
        releaseMode: Bool = Bundle.main.object(forInfoDictionaryKey: "InvoiceHubReleaseMode") as? Bool == true
    ) throws -> BackendPaths {
        let resourceCore = bundleResourceURL?.appendingPathComponent("invoice-hub-core", isDirectory: true)
        let coreRoot: URL
        if releaseMode {
            guard let resourceCore, isCoreRoot(resourceCore, fileManager: fileManager) else {
                throw BackendPathError.releaseCoreUnavailable(
                    resourceCore?.path ?? "Contents/Resources/invoice-hub-core"
                )
            }
            coreRoot = resourceCore
        } else if let resourceCore, isCoreRoot(resourceCore, fileManager: fileManager) {
            coreRoot = resourceCore
        } else {
            let startURL = start ?? URL(fileURLWithPath: fileManager.currentDirectoryPath, isDirectory: true)
            coreRoot = try findCoreRoot(startingAt: startURL, fileManager: fileManager)
        }

        let appSupport = try appSupportDirectory(fileManager: fileManager)
        let configPath = appSupport
            .appendingPathComponent("config", isDirectory: true)
            .appendingPathComponent("app.local.json", isDirectory: false)
        let runtimeDir = appSupport.appendingPathComponent("runtime", isDirectory: true)
        return BackendPaths(
            coreRoot: coreRoot,
            resourceRoot: bundleResourceURL,
            appSupportRoot: appSupport,
            configPath: configPath,
            runtimeDir: runtimeDir,
            stdoutLog: runtimeDir.appendingPathComponent("server_stdout.log"),
            stderrLog: runtimeDir.appendingPathComponent("server_stderr.log"),
            serverPID: runtimeDir.appendingPathComponent("server.pid")
        )
    }

    public static func findCoreRoot(startingAt start: URL, fileManager: FileManager = .default) throws -> URL {
        var cursor = start.standardizedFileURL
        if !cursor.hasDirectoryPath {
            cursor.deleteLastPathComponent()
        }
        while true {
            if isCoreRoot(cursor, fileManager: fileManager) {
                return cursor
            }
            let parent = cursor.deletingLastPathComponent()
            if parent.path == cursor.path {
                break
            }
            cursor = parent
        }
        throw BackendPathError.coreRootNotFound(start.path)
    }

    public static func isCoreRoot(_ url: URL, fileManager: FileManager = .default) -> Bool {
        let apiMain = url
            .appendingPathComponent("src", isDirectory: true)
            .appendingPathComponent("invoice_hub", isDirectory: true)
            .appendingPathComponent("api", isDirectory: true)
            .appendingPathComponent("main.py", isDirectory: false)
        let webTemplates = url
            .appendingPathComponent("web", isDirectory: true)
            .appendingPathComponent("templates", isDirectory: true)
        return fileManager.fileExists(atPath: apiMain.path) && fileManager.fileExists(atPath: webTemplates.path)
    }

    public func ensureWritableLayout(fileManager: FileManager = .default) throws {
        try fileManager.createDirectory(at: appSupportRoot, withIntermediateDirectories: true)
        try fileManager.createDirectory(at: configPath.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fileManager.createDirectory(at: runtimeDir, withIntermediateDirectories: true)
    }

    private static func appSupportDirectory(fileManager: FileManager) throws -> URL {
        let base = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent("InvoiceHub", isDirectory: true)
    }
}

public enum BackendPathError: LocalizedError, Equatable {
    case coreRootNotFound(String)
    case releaseCoreUnavailable(String)

    public var errorDescription: String? {
        switch self {
        case .coreRootNotFound(let start):
            return "未找到 InvoiceHub Python 核心目录，起点: \(start)"
        case .releaseCoreUnavailable(let path):
            return "正式 App 缺少或损坏内嵌 InvoiceHub 核心，已拒绝回退开发目录: \(path)"
        }
    }
}
