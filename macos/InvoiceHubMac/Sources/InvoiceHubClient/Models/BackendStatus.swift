import Foundation

public enum BackendOwnership: String, Equatable {
    case owned
    case externalCompatible
    case none

    public var canStopOrRestart: Bool { self == .owned }

    public var title: String {
        switch self {
        case .owned:
            return "当前 App 管理"
        case .externalCompatible:
            return "外部兼容服务"
        case .none:
            return "无"
        }
    }
}

public enum BackendPIDFile {
    public static func read(_ url: URL) -> Int32? {
        guard let text = try? String(contentsOf: url, encoding: .utf8),
              let value = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
        else {
            return nil
        }
        return value
    }

    @discardableResult
    public static func removeIfMatches(_ url: URL, expectedPID: Int32) -> Bool {
        guard read(url) == expectedPID else { return false }
        do {
            try FileManager.default.removeItem(at: url)
            return true
        } catch {
            return false
        }
    }
}

public enum BackendPhase: Equatable {
    case idle
    case starting
    case running
    case stopping
    case stopped
    case failed(String)

    public var isRunning: Bool {
        if case .running = self {
            return true
        }
        return false
    }
}

public struct BackendStatus: Equatable {
    public var phase: BackendPhase
    public var message: String
    public var updatedAt: Date

    public init(phase: BackendPhase = .idle, message: String = "尚未启动", updatedAt: Date = Date()) {
        self.phase = phase
        self.message = message
        self.updatedAt = updatedAt
    }
}
