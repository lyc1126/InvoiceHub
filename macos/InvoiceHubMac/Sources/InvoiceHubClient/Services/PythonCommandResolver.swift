import Foundation

public struct PythonCommand: Equatable {
    public let executableURL: URL
    public let argumentsPrefix: [String]

    public init(executableURL: URL, argumentsPrefix: [String] = []) {
        self.executableURL = executableURL
        self.argumentsPrefix = argumentsPrefix
    }
}

public enum PythonCommandResolver {
    public static func resolve(
        paths: BackendPaths,
        fileManager: FileManager = .default,
        releaseMode: Bool = Bundle.main.object(forInfoDictionaryKey: "InvoiceHubReleaseMode") as? Bool == true
    ) throws -> PythonCommand {
        if let resourceRoot = paths.resourceRoot {
            let devPath = resourceRoot.appendingPathComponent("dev-python-path.txt")
            if releaseMode && fileManager.fileExists(atPath: devPath.path) {
                throw PythonCommandError.developmentMarkerInRelease(devPath.path)
            }
            if !releaseMode, let text = try? String(contentsOf: devPath, encoding: .utf8) {
                let candidate = URL(fileURLWithPath: text.trimmingCharacters(in: .whitespacesAndNewlines))
                if fileManager.isExecutableFile(atPath: candidate.path) {
                    return PythonCommand(executableURL: candidate)
                }
                throw PythonCommandError.configuredPythonNotExecutable(candidate.path)
            }

            let bundled = resourceRoot
                .appendingPathComponent("python", isDirectory: true)
                .appendingPathComponent("bin", isDirectory: true)
                .appendingPathComponent("python3", isDirectory: false)
            if fileManager.isExecutableFile(atPath: bundled.path) {
                return PythonCommand(executableURL: bundled)
            }
            if releaseMode {
                throw PythonCommandError.bundledPythonMissing(bundled.path)
            }
        }

        if releaseMode {
            throw PythonCommandError.bundledPythonMissing(
                paths.resourceRoot?.appendingPathComponent("python/bin/python3").path ?? "Contents/Resources/python/bin/python3"
            )
        }

        let coreVenv = paths.coreRoot
            .appendingPathComponent(".venv", isDirectory: true)
            .appendingPathComponent("bin", isDirectory: true)
            .appendingPathComponent("python", isDirectory: false)
        if fileManager.isExecutableFile(atPath: coreVenv.path) {
            return PythonCommand(executableURL: coreVenv)
        }

        for raw in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"] {
            let candidate = URL(fileURLWithPath: raw)
            if fileManager.isExecutableFile(atPath: candidate.path) {
                return PythonCommand(executableURL: candidate)
            }
        }

        let env = URL(fileURLWithPath: "/usr/bin/env")
        if fileManager.isExecutableFile(atPath: env.path) {
            return PythonCommand(executableURL: env, argumentsPrefix: ["python3"])
        }

        throw PythonCommandError.notFound
    }
}

public enum PythonCommandError: LocalizedError, Equatable {
    case notFound
    case configuredPythonNotExecutable(String)
    case developmentMarkerInRelease(String)
    case bundledPythonMissing(String)

    public var errorDescription: String? {
        switch self {
        case .notFound:
            return "未找到可用 Python。请安装依赖或使用打包版内置 Python。"
        case .configuredPythonNotExecutable(let path):
            return "配置的 Python 不可执行，请重新运行 macOS 构建脚本: \(path)"
        case .developmentMarkerInRelease(let path):
            return "正式 App 中出现开发 Python 标记，已拒绝启动: \(path)"
        case .bundledPythonMissing(let path):
            return "正式 App 缺少内置 Python，且不会回退系统环境: \(path)"
        }
    }
}
