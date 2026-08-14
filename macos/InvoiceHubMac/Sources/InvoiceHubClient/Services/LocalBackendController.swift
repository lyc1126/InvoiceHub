import AppKit
import Combine
import Foundation
import OSLog

struct BackendStartupGate {
    private(set) var isActive = false

    mutating func tryAcquire(phase: BackendPhase, ownership: BackendOwnership) -> Bool {
        guard !isActive else { return false }
        switch phase {
        case .starting, .running, .stopping:
            return false
        case .idle, .stopped, .failed:
            break
        }
        guard ownership != .externalCompatible else { return false }
        isActive = true
        return true
    }

    mutating func release() {
        isActive = false
    }

    mutating func releaseAfterVerifiedOwnedStartup(lifecycle: BackendLifecycleSnapshot) -> Bool {
        guard BackendUpdateMonitorRecoveryPolicy.canFinalizeStartupForRecovery(
            startupGateIsActive: isActive,
            lifecycle: lifecycle
        ) else {
            return false
        }
        release()
        return true
    }
}

struct BackendLifecycleSnapshot: Equatable {
    let generation: UInt64
    let phase: BackendPhase
    let ownership: BackendOwnership
    let healthPID: Int?
    let ownedPID: Int32?
    let processPID: Int32?
    let processIsRunning: Bool
}

struct BackendLifecycleToken: Equatable {
    let generation: UInt64
    let phase: BackendPhase
    let ownership: BackendOwnership
    let healthPID: Int?
    let ownedPID: Int32?
    let processPID: Int32?

    init(capturing snapshot: BackendLifecycleSnapshot) {
        generation = snapshot.generation
        phase = snapshot.phase
        ownership = snapshot.ownership
        healthPID = snapshot.healthPID
        ownedPID = snapshot.ownedPID
        processPID = snapshot.processPID
    }
}

struct BackendStartupFailureToken: Equatable {
    let generation: UInt64
    let attemptedPID: Int32?
}

enum BackendStartupCleanupResult: Equatable {
    case notRequired
    case retainedAttempt
    case finalizedAttempt(Int32)
}

struct BackendLifecyclePolicy {
    static func matchesCapturedIdentity(
        token: BackendLifecycleToken,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        token.generation == current.generation
            && token.phase == current.phase
            && token.ownership == current.ownership
            && token.healthPID == current.healthPID
            && token.ownedPID == current.ownedPID
            && token.processPID == current.processPID
    }

    static func hasVerifiedIdentity(_ snapshot: BackendLifecycleSnapshot) -> Bool {
        guard snapshot.healthPID != nil else { return false }
        switch snapshot.ownership {
        case .owned:
            return hasVerifiedOwnedIdentity(snapshot)
        case .externalCompatible:
            return snapshot.ownedPID == nil
                && snapshot.processPID == nil
                && !snapshot.processIsRunning
        case .none:
            return false
        }
    }

    static func hasVerifiedOwnedIdentity(_ snapshot: BackendLifecycleSnapshot) -> Bool {
        snapshot.ownership == .owned
            && BackendProcessTruth.healthMatchesTrackedOwnedProcess(
                healthPID: snapshot.healthPID,
                expectedPID: snapshot.ownedPID,
                trackedOwnedPID: snapshot.ownedPID,
                processPID: snapshot.processPID,
                processIsRunning: snapshot.processIsRunning
            )
    }

    static func canApplyAsyncCompletion(
        token: BackendLifecycleToken,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        matchesCapturedIdentity(token: token, current: current)
            && hasVerifiedIdentity(current)
    }

    static func canApplyOwnedAsyncCompletion(
        token: BackendLifecycleToken,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        token.ownership == .owned
            && matchesCapturedIdentity(token: token, current: current)
            && hasVerifiedOwnedIdentity(current)
    }

    static func isDirectlyConfirmedOwnedExit(
        token: BackendLifecycleToken,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        token.ownership == .owned
            && current.generation == token.generation &+ 1
            && current.phase == .stopped
            && current.ownership == .none
            && current.healthPID == nil
            && current.ownedPID == nil
            && current.processPID == nil
            && !current.processIsRunning
    }

    static func canApplyStartupCompletion(
        generation: UInt64,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        generation == current.generation && current.phase == .starting
    }

    static func canApplyStartupFailure(
        generation: UInt64,
        attemptedPID: Int32?,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        guard canApplyStartupCompletion(generation: generation, current: current) else {
            return false
        }
        guard let attemptedPID else { return true }
        return current.ownership == .owned
            && current.ownedPID == attemptedPID
            && current.processPID == attemptedPID
            && current.processIsRunning
    }

    static func isExpectedFinalizedStartupAttempt(
        token: BackendStartupFailureToken,
        current: BackendLifecycleSnapshot
    ) -> Bool {
        token.attemptedPID != nil
            && current.generation == token.generation &+ 1
            && current.phase == .stopped
            && current.ownership == .none
            && current.healthPID == nil
            && current.ownedPID == nil
            && current.processPID == nil
            && !current.processIsRunning
    }

    static func startupFailurePhase(
        token: BackendStartupFailureToken,
        cleanupResult: BackendStartupCleanupResult,
        current: BackendLifecycleSnapshot,
        message: String
    ) -> BackendPhase? {
        let canApply: Bool
        switch cleanupResult {
        case .notRequired:
            canApply = token.attemptedPID == nil
                && canApplyStartupFailure(
                    generation: token.generation,
                    attemptedPID: nil,
                    current: current
                )
        case .retainedAttempt:
            canApply = canApplyStartupFailure(
                generation: token.generation,
                attemptedPID: token.attemptedPID,
                current: current
            )
        case .finalizedAttempt(let finalizedPID):
            canApply = token.attemptedPID == finalizedPID
                && isExpectedFinalizedStartupAttempt(token: token, current: current)
        }
        return canApply ? .failed(message) : nil
    }
}

struct BackendControlPolicy {
    static func blocksControlAction(startupIsActive: Bool, phase: BackendPhase) -> Bool {
        guard !startupIsActive else { return true }
        switch phase {
        case .starting, .stopping:
            return true
        case .idle, .running, .stopped, .failed:
            return false
        }
    }

    static func canManageBackend(
        startupIsActive: Bool,
        lifecycle: BackendLifecycleSnapshot
    ) -> Bool {
        !blocksControlAction(startupIsActive: startupIsActive, phase: lifecycle.phase)
            && lifecycle.phase.isRunning
            && lifecycle.ownership == .owned
            && BackendLifecyclePolicy.hasVerifiedIdentity(lifecycle)
    }

    static func canManageUpdateLifecycle(
        startupIsActive: Bool,
        lifecycle: BackendLifecycleSnapshot
    ) -> Bool {
        canManageBackend(startupIsActive: startupIsActive, lifecycle: lifecycle)
    }

    static func canRunControlAction(
        startupIsActive: Bool,
        lifecycle: BackendLifecycleSnapshot
    ) -> Bool {
        !blocksControlAction(startupIsActive: startupIsActive, phase: lifecycle.phase)
            && lifecycle.phase.isRunning
            && BackendLifecyclePolicy.hasVerifiedIdentity(lifecycle)
    }

    static func phaseAfterFailure(
        startupIsActive: Bool,
        currentPhase: BackendPhase,
        ownership: BackendOwnership,
        hasVerifiedHealth: Bool,
        message: String
    ) -> BackendPhase {
        if startupIsActive {
            return currentPhase == .stopping ? .stopping : .starting
        }
        switch currentPhase {
        case .starting:
            return .starting
        case .stopping:
            return .stopping
        case .running where ownership != .none && hasVerifiedHealth:
            return .running
        case .idle, .running, .stopped, .failed:
            return .failed(message)
        }
    }
}

struct BackendUpdateMonitorRecoveryPolicy {
    static func hasVerifiedOwnedRunningIdentity(_ lifecycle: BackendLifecycleSnapshot) -> Bool {
        lifecycle.phase.isRunning && BackendLifecyclePolicy.hasVerifiedOwnedIdentity(lifecycle)
    }

    static func canFinalizeStartupForRecovery(
        startupGateIsActive: Bool,
        lifecycle: BackendLifecycleSnapshot
    ) -> Bool {
        startupGateIsActive && hasVerifiedOwnedRunningIdentity(lifecycle)
    }

    static func canRecoverMarkedMonitor(
        markerIsPresent: Bool,
        startupGateIsActive: Bool,
        lifecycle: BackendLifecycleSnapshot
    ) -> Bool {
        markerIsPresent
            && !startupGateIsActive
            && hasVerifiedOwnedRunningIdentity(lifecycle)
    }
}

struct BackendProcessTruth {
    static func healthMatchesTrackedOwnedProcess(
        healthPID: Int?,
        expectedPID: Int32?,
        trackedOwnedPID: Int32?,
        processPID: Int32?,
        processIsRunning: Bool
    ) -> Bool {
        guard
            processIsRunning,
            let healthPID,
            let expectedPID,
            let trackedOwnedPID,
            let processPID
        else {
            return false
        }
        return Int64(healthPID) == Int64(expectedPID)
            && trackedOwnedPID == expectedPID
            && processPID == expectedPID
    }

    static func ownershipForCompatibleHealth(
        healthPID: Int?,
        trackedOwnedPID: Int32?,
        processPID: Int32?,
        processIsRunning: Bool
    ) -> BackendOwnership? {
        guard processIsRunning else {
            return trackedOwnedPID == nil && processPID == nil ? .externalCompatible : nil
        }
        return healthMatchesTrackedOwnedProcess(
            healthPID: healthPID,
            expectedPID: trackedOwnedPID,
            trackedOwnedPID: trackedOwnedPID,
            processPID: processPID,
            processIsRunning: processIsRunning
        ) ? .owned : nil
    }

    static func shouldCleanupFailedLaunch(
        attemptPID: Int32?,
        trackedOwnedPID: Int32?,
        processPID: Int32?
    ) -> Bool {
        guard let attemptPID else { return false }
        return trackedOwnedPID == attemptPID && processPID == attemptPID
    }

    static func canFinalizeOwnedExit(
        expectedPID: Int32,
        trackedOwnedPID: Int32?,
        processPID: Int32,
        processIsRunning: Bool
    ) -> Bool {
        !processIsRunning && trackedOwnedPID == expectedPID && processPID == expectedPID
    }
}

@MainActor
public final class LocalBackendController: ObservableObject {
    private static let logger = Logger(subsystem: "com.invoicehub.mac", category: "backend")

    @Published public private(set) var status = BackendStatus()
    @Published public private(set) var baseURL: URL?
    @Published public private(set) var paths: BackendPaths?
    @Published public private(set) var webRefreshToken = 0
    @Published public private(set) var ownership = BackendOwnership.none
    @Published public private(set) var buildManifest: InvoiceHubBuildManifest?
    @Published public private(set) var packageManifest: InvoiceHubPackageManifest?
    @Published public private(set) var healthSnapshot: BackendHealth?
    @Published public private(set) var startupSurface = StartupSurface.desktop

    private var process: Process?
    private var ownedPID: Int32?
    private var stdoutHandle: FileHandle?
    private var stderrHandle: FileHandle?
    private var apiClient: InvoiceHubAPIClient?
    private var startupGate = BackendStartupGate()
    private var lifecycleGeneration: UInt64 = 0
    private lazy var sparkleUpdater = InvoiceHubSparkleUpdater()

    private var lifecycleSnapshot: BackendLifecycleSnapshot {
        BackendLifecycleSnapshot(
            generation: lifecycleGeneration,
            phase: status.phase,
            ownership: ownership,
            healthPID: healthSnapshot?.pid,
            ownedPID: ownedPID,
            processPID: process?.processIdentifier,
            processIsRunning: process?.isRunning ?? false
        )
    }

    public init() {}

    public var canStopOrRestart: Bool {
        BackendControlPolicy.canManageBackend(
            startupIsActive: startupGate.isActive,
            lifecycle: lifecycleSnapshot
        )
    }

    public var canInstallUpdate: Bool {
        BackendControlPolicy.canManageUpdateLifecycle(
            startupIsActive: startupGate.isActive,
            lifecycle: lifecycleSnapshot
        )
    }

    func updateInstallLifecycleToken() -> BackendLifecycleToken? {
        guard canInstallUpdate else { return nil }
        return BackendLifecycleToken(capturing: lifecycleSnapshot)
    }

    func isCurrentUpdateInstallIdentity(_ token: BackendLifecycleToken) -> Bool {
        BackendControlPolicy.canManageUpdateLifecycle(
            startupIsActive: startupGate.isActive,
            lifecycle: lifecycleSnapshot
        ) && BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: token,
            current: lifecycleSnapshot
        )
    }

    public var serviceManagementHint: String {
        switch ownership {
        case .owned:
            return "当前 App 启动并管理此 localhost 服务。"
        case .externalCompatible:
            return "当前连接由其他进程管理；本 App 不会停止、重启或删除其 PID。"
        case .none:
            return "当前没有可由本 App 管理的 localhost 服务。"
        }
    }

    public func start() async {
        guard startupGate.tryAcquire(phase: status.phase, ownership: ownership) else { return }
        defer { startupGate.release() }
        if let trackedProcess = process, let trackedPID = ownedPID, !trackedProcess.isRunning {
            _ = finalizeOwnedBackendExit(
                trackedProcess,
                expectedPID: trackedPID,
                message: "先前 owned 本地服务已退出"
            )
        }
        let startGeneration = advanceLifecycleGeneration()
        var launchedOwnedPID: Int32?
        status = BackendStatus(phase: .starting, message: "正在核对构建并启动本地服务...")
        do {
            let resolvedPaths = try BackendPaths.resolve()
            let manifest = try InvoiceHubBuildManifest.load(from: resolvedPaths.coreRoot)
            let package = try InvoiceHubPackageManifest.load(from: resolvedPaths.coreRoot)
            let port = try InvoiceHubConfig.ensureDefaultConfig(paths: resolvedPaths)
            let url = URL(string: "http://127.0.0.1:\(port)/")!
            let client = InvoiceHubAPIClient(baseURL: url)
            paths = resolvedPaths
            buildManifest = manifest
            packageManifest = package
            baseURL = url
            apiClient = client
            Self.logger.info("Starting backend flow build=\(manifest.buildID, privacy: .public) config=\(resolvedPaths.configPath.path, privacy: .public) port=\(port, privacy: .public)")

            if let existingHealth = await client.health() {
                try await verifyBackend(
                    health: existingHealth,
                    manifest: manifest,
                    packageManifest: package,
                    paths: resolvedPaths,
                    port: port,
                    client: client
                )
                guard let resolvedOwnership = BackendProcessTruth.ownershipForCompatibleHealth(
                    healthPID: existingHealth.pid,
                    trackedOwnedPID: ownedPID,
                    processPID: process?.processIdentifier,
                    processIsRunning: process?.isRunning ?? false
                ) else {
                    throw BackendLaunchError.ownershipConflict(existingHealth.pid, ownedPID)
                }
                guard BackendLifecyclePolicy.canApplyStartupCompletion(
                    generation: startGeneration,
                    current: lifecycleSnapshot
                ) else {
                    return
                }
                healthSnapshot = existingHealth
                ownership = resolvedOwnership
                status = BackendStatus(
                    phase: .running,
                    message: resolvedOwnership == .owned
                        ? "已重新连接本 App 管理的本地服务"
                        : "已连接构建一致的外部服务；停止与重启由原进程管理"
                )
                await restoreMonitorAfterVerifiedStartupIfNeeded()
                await applyStartupSurfacePreference(using: client)
                return
            }

            guard ownership == .none, process == nil, ownedPID == nil else {
                throw BackendLaunchError.ownedProcessUnavailable(ownedPID)
            }
            let launchedProcess = try launchBackend(paths: resolvedPaths, port: port)
            launchedOwnedPID = launchedProcess.processIdentifier
            try writeOwnedPIDFile(paths: resolvedPaths, launchedProcess: launchedProcess)
            let health = try await waitForCompatibleHealth(
                client: client,
                manifest: manifest,
                packageManifest: package,
                paths: resolvedPaths,
                port: port,
                timeoutSeconds: 15
            )
            guard BackendProcessTruth.healthMatchesTrackedOwnedProcess(
                healthPID: health.pid,
                expectedPID: launchedOwnedPID,
                trackedOwnedPID: ownedPID,
                processPID: process?.processIdentifier,
                processIsRunning: process?.isRunning ?? false
            ) else {
                throw BackendLaunchError.ownershipConflict(health.pid, ownedPID)
            }
            guard BackendLifecyclePolicy.canApplyStartupCompletion(
                generation: startGeneration,
                current: lifecycleSnapshot
            ) else {
                return
            }
            healthSnapshot = health
            status = BackendStatus(phase: .running, message: "本地服务已启动，构建握手通过")
            await restoreMonitorAfterVerifiedStartupIfNeeded()
            await applyStartupSurfacePreference(using: client)
        } catch {
            let failureMessage = error.localizedDescription
            let failureToken = BackendStartupFailureToken(
                generation: startGeneration,
                attemptedPID: launchedOwnedPID
            )
            var cleanupResult: BackendStartupCleanupResult = launchedOwnedPID == nil
                ? .notRequired
                : .retainedAttempt
            if BackendProcessTruth.shouldCleanupFailedLaunch(
                attemptPID: launchedOwnedPID,
                trackedOwnedPID: ownedPID,
                processPID: process?.processIdentifier
            ) && ownership == .owned {
                let cleanupFinalized = await terminateOwnedBackend(waitForExit: true)
                if cleanupFinalized, let launchedOwnedPID {
                    cleanupResult = .finalizedAttempt(launchedOwnedPID)
                }
            }
            if let launchedOwnedPID,
               BackendLifecyclePolicy.isExpectedFinalizedStartupAttempt(
                   token: failureToken,
                   current: lifecycleSnapshot
               ) {
                cleanupResult = .finalizedAttempt(launchedOwnedPID)
            }
            guard let failurePhase = BackendLifecyclePolicy.startupFailurePhase(
                token: failureToken,
                cleanupResult: cleanupResult,
                current: lifecycleSnapshot,
                message: failureMessage
            ) else {
                return
            }
            status = BackendStatus(phase: failurePhase, message: failureMessage)
            Self.logger.error("Backend start failed: \(failureMessage, privacy: .public)")
        }
    }

    @discardableResult
    public func stopLocalhost() async -> Bool {
        guard canStopOrRestart else {
            if BackendControlPolicy.blocksControlAction(
                startupIsActive: startupGate.isActive,
                phase: status.phase
            ) {
                return false
            }
            let message = ownership == .externalCompatible
                ? "当前为外部兼容服务，本 App 无权停止；监控状态未改变。"
                : ownership == .owned
                    ? "owned 页面服务尚未完成 health 验证，未执行停止。"
                    : "当前没有由本 App 启动的页面服务。"
            let failurePhase = ownership == .none
                ? BackendPhase.stopped
                : BackendControlPolicy.phaseAfterFailure(
                    startupIsActive: startupGate.isActive,
                    currentPhase: status.phase,
                    ownership: ownership,
                    hasVerifiedHealth: healthSnapshot != nil,
                    message: message
                )
            status = BackendStatus(phase: failurePhase, message: message)
            return false
        }
        guard let client = apiClient, let expectedPID = ownedPID else {
            status = BackendStatus(phase: .running, message: "无法确认 owned 后端连接；未停止进程或删除 PID。")
            return false
        }
        advanceLifecycleGeneration()
        status = BackendStatus(phase: .stopping, message: "正在停止本 App 管理的页面服务...")
        let stopToken = BackendLifecycleToken(capturing: lifecycleSnapshot)
        do {
            let response = try await client.shutdownKeepingMonitor()
            guard response.accepted else {
                throw BackendLaunchError.shutdownRejected(
                    response.message.isEmpty ? "后端未接受保留监控的关闭请求。" : response.message
                )
            }
            guard await waitForOwnedBackendExit(
                expectedPID: expectedPID,
                token: stopToken,
                timeoutSeconds: 10
            ) else {
                guard BackendLifecyclePolicy.canApplyAsyncCompletion(
                    token: stopToken,
                    current: lifecycleSnapshot
                ) else {
                    return false
                }
                throw BackendLaunchError.shutdownTimeout(paths?.stderrLog.path ?? "")
            }
            return true
        } catch {
            guard BackendLifecyclePolicy.canApplyAsyncCompletion(
                token: stopToken,
                current: lifecycleSnapshot
            ) else {
                return false
            }
            status = BackendStatus(
                phase: .running,
                message: "停止页面服务失败：\(error.localizedDescription) owned 进程未被强制终止，PID 未删除。"
            )
            Self.logger.error("Backend shutdown failed without force termination: \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    public func terminateOwnedBackendForAppQuit() {
        guard ownership == .owned, let pid = ownedPID else { return }
        guard let trackedProcess = process, trackedProcess.processIdentifier == pid else { return }
        if trackedProcess.isRunning {
            trackedProcess.terminate()
        }
        for _ in 0..<20 where trackedProcess.isRunning {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if !trackedProcess.isRunning {
            _ = finalizeOwnedBackendExit(trackedProcess, expectedPID: pid, message: "App 退出时本地服务已停止")
        }
    }

    public func restart() async {
        guard canStopOrRestart else {
            if BackendControlPolicy.blocksControlAction(
                startupIsActive: startupGate.isActive,
                phase: status.phase
            ) {
                return
            }
            let message = "只有完成 health 验证且由当前 App 管理的 owned 服务允许重启。\(serviceManagementHint)"
            status = BackendStatus(
                phase: ownership == .none
                    ? .stopped
                    : BackendControlPolicy.phaseAfterFailure(
                        startupIsActive: startupGate.isActive,
                        currentPhase: status.phase,
                        ownership: ownership,
                        hasVerifiedHealth: healthSnapshot != nil,
                        message: message
                    ),
                message: message
            )
            return
        }
        guard await stopLocalhost() else { return }
        await start()
    }

    public func pickWatchDirectoryDraft() async throws -> [String: Any] {
        guard let client = apiClient else { throw InvoiceHubAPIError.invalidResponse }
        guard let selected = MacDirectoryPicker.pickDirectory(title: "选择发票监控文件夹") else {
            let settings = try? await client.settings()
            return [
                "ok": true,
                "selected": false,
                "watch_dir": settings?["watch_dir"] as? String ?? "",
                "validation": settings?["path_validation"] as? [String: Any] ?? [:]
            ]
        }
        let validation = try await client.validateWatchDirectory(selected)
        return [
            "ok": true,
            "selected": true,
            "requires_save": true,
            "watch_dir": selected.path,
            "validation": validation
        ]
    }

    public func pickOutboundDirectoryDraft() async throws -> [String: Any] {
        guard let client = apiClient else { throw InvoiceHubAPIError.invalidResponse }
        guard let selected = MacDirectoryPicker.pickDirectory(title: "选择开具发票文件夹") else {
            let state = try? await client.documentsState()
            return [
                "ok": true,
                "selected": false,
                "outbound_invoice_dir": state?["outbound_invoice_dir"] as? String ?? "",
                "validation": state?["outbound_dir_validation"] as? [String: Any] ?? [:]
            ]
        }
        let validation = try await client.validateOutboundDirectory(selected)
        return [
            "ok": true,
            "selected": true,
            "requires_save": true,
            "outbound_invoice_dir": selected.path,
            "validation": validation
        ]
    }

    public func pickOCRCandidateDirectoryDraft() -> [String: Any] {
        guard let selected = MacDirectoryPicker.pickDirectory(title: "选择 OCR 候选文件夹") else {
            return ["ok": true, "selected": false, "path": ""]
        }
        return ["ok": true, "selected": true, "path": selected.path]
    }

    public func startMonitor() async {
        await runOwnedControlAction("正在启动持续监听...") { try await $0.startMonitor() }
    }

    public func stopMonitor() async {
        await runOwnedControlAction("正在停止持续监听...") { try await $0.stopMonitor() }
    }

    public func rebuild() async {
        await runControlAction("正在重新汇总...") { try await $0.rebuild() }
    }

    public func openInBrowser() {
        guard let baseURL else { return }
        NSWorkspace.shared.open(baseURL)
    }

    public func showDesktopWindow() {
        NotificationCenter.default.post(name: .invoiceHubShowDesktopWindow, object: self)
    }

    public func installUpdate() throws -> [String: Any] {
        guard canInstallUpdate else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        return try sparkleUpdater.beginUserInitiatedUpdate(using: self)
    }

    public func prepareMonitorForUpdateInstall() async throws {
        guard let identity = updateInstallLifecycleToken() else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        try await prepareMonitorForUpdateInstall(expectedIdentity: identity)
    }

    func prepareMonitorForUpdateInstall(expectedIdentity: BackendLifecycleToken) async throws {
        guard isCurrentUpdateInstallIdentity(expectedIdentity) else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        guard let apiClient, let paths else {
            throw BackendUpdateError.backendUnavailable
        }
        let before = try await apiClient.bridgeStatus()
        guard isCurrentUpdateInstallIdentity(expectedIdentity) else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        guard Self.monitorIsRunning(before) else { return }
        let marker = Self.updateMonitorRestoreMarker(paths: paths)
        try FileManager.default.createDirectory(at: marker.deletingLastPathComponent(), withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "schema_version": 1,
            "restore_monitor": true,
            "created_at": ISO8601DateFormatter().string(from: Date()),
        ]
        try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            .write(to: marker, options: .atomic)
        guard isCurrentUpdateInstallIdentity(expectedIdentity) else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        _ = try await apiClient.stopMonitor()
        guard isCurrentUpdateInstallIdentity(expectedIdentity) else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        let after = try await apiClient.bridgeStatus()
        guard isCurrentUpdateInstallIdentity(expectedIdentity) else {
            throw BackendUpdateError.ownedLifecycleRequired
        }
        guard !Self.monitorIsRunning(after) else {
            throw BackendUpdateError.monitorDidNotStop
        }
    }

    public func restoreMonitorAfterUpdateIfNeeded() async {
        guard let apiClient, let paths else { return }
        let marker = Self.updateMonitorRestoreMarker(paths: paths)
        guard BackendUpdateMonitorRecoveryPolicy.canRecoverMarkedMonitor(
            markerIsPresent: FileManager.default.fileExists(atPath: marker.path),
            startupGateIsActive: startupGate.isActive,
            lifecycle: lifecycleSnapshot
        ) else {
            return
        }
        guard let identity = updateInstallLifecycleToken() else { return }
        do {
            _ = try await apiClient.startMonitor()
            guard isCurrentUpdateInstallIdentity(identity) else { return }
            let statusPayload = try await apiClient.bridgeStatus()
            guard isCurrentUpdateInstallIdentity(identity) else { return }
            guard Self.monitorIsRunning(statusPayload), Self.monitorIsReady(statusPayload) else {
                throw BackendUpdateError.monitorDidNotRestore
            }
            guard isCurrentUpdateInstallIdentity(identity) else { return }
            try FileManager.default.removeItem(at: marker)
            status = BackendStatus(phase: .running, message: "更新后持续监控已恢复")
        } catch {
            guard isCurrentUpdateInstallIdentity(identity) else { return }
            status = BackendStatus(
                phase: .running,
                message: "更新后持续监控尚未恢复：\(error.localizedDescription)"
            )
        }
    }

    private func restoreMonitorAfterVerifiedStartupIfNeeded() async {
        guard startupGate.releaseAfterVerifiedOwnedStartup(lifecycle: lifecycleSnapshot) else {
            return
        }
        await restoreMonitorAfterUpdateIfNeeded()
    }

    public func openDiagnostics() {
        guard let url = url(for: .backend) else { return }
        NSWorkspace.shared.open(url)
    }

    public func openLogs() {
        guard let runtimeDir = paths?.runtimeDir else { return }
        NSWorkspace.shared.open(runtimeDir)
    }

    public func reloadWebContent() {
        webRefreshToken += 1
    }

    public func url(for route: AppRoute) -> URL? {
        guard let baseURL else { return nil }
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)
        components?.path = route.webPath
        return components?.url
    }

    private func applyStartupSurfacePreference(using client: InvoiceHubAPIClient) async {
        do {
            let payload = try await client.preferences()
            let preferences = payload["preferences"] as? [String: Any]
            let surface = StartupSurface.normalized(preferences?["startup_surface"])
            startupSurface = surface
            if surface == .browser {
                openInBrowser()
            }
            NotificationCenter.default.post(
                name: .invoiceHubStartupSurfaceChanged,
                object: self,
                userInfo: ["surface": surface.rawValue]
            )
        } catch {
            startupSurface = .desktop
            status = BackendStatus(
                phase: .running,
                message: "本地服务已就绪，但启动方式偏好读取失败：\(error.localizedDescription)"
            )
        }
    }

    private static func updateMonitorRestoreMarker(paths: BackendPaths) -> URL {
        paths.runtimeDir
            .appendingPathComponent("local_state", isDirectory: true)
            .appendingPathComponent("restore-monitor-after-update.json", isDirectory: false)
    }

    private static func monitorStatusObject(_ payload: [String: Any]) -> [String: Any] {
        payload["status"] as? [String: Any] ?? payload
    }

    private static func monitorIsRunning(_ payload: [String: Any]) -> Bool {
        monitorStatusObject(payload)["running"] as? Bool == true
    }

    private static func monitorIsReady(_ payload: [String: Any]) -> Bool {
        monitorStatusObject(payload)["ready"] as? Bool == true
    }

    private func runControlAction(
        _ progressMessage: String,
        operation: (InvoiceHubAPIClient) async throws -> [String: Any]
    ) async {
        guard !BackendControlPolicy.blocksControlAction(
            startupIsActive: startupGate.isActive,
            phase: status.phase
        ) else {
            return
        }
        var client = apiClient
        if client == nil || !BackendControlPolicy.canRunControlAction(
            startupIsActive: startupGate.isActive,
            lifecycle: lifecycleSnapshot
        ) {
            await start()
            client = apiClient
        }
        guard let client,
              BackendControlPolicy.canRunControlAction(
                  startupIsActive: startupGate.isActive,
                  lifecycle: lifecycleSnapshot
              )
        else {
            return
        }
        let controlToken = BackendLifecycleToken(capturing: lifecycleSnapshot)
        status = BackendStatus(phase: .running, message: progressMessage)
        do {
            finishControlAction(with: try await operation(client), token: controlToken)
        } catch {
            failControlAction(with: error, token: controlToken)
        }
    }

    private func runOwnedControlAction(
        _ progressMessage: String,
        operation: (InvoiceHubAPIClient) async throws -> [String: Any]
    ) async {
        guard canStopOrRestart, let client = apiClient else {
            reportOwnedMonitorStopUnavailable()
            return
        }
        let controlToken = BackendLifecycleToken(capturing: lifecycleSnapshot)
        guard BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: controlToken,
            current: lifecycleSnapshot
        ) else {
            reportOwnedMonitorStopUnavailable()
            return
        }
        status = BackendStatus(phase: .running, message: progressMessage)
        do {
            finishOwnedControlAction(with: try await operation(client), token: controlToken)
        } catch {
            failOwnedControlAction(with: error, token: controlToken)
        }
    }

    private func reportOwnedMonitorStopUnavailable() {
        guard !BackendControlPolicy.blocksControlAction(
            startupIsActive: startupGate.isActive,
            phase: status.phase
        ) else {
            return
        }
        let message = ownership == .externalCompatible
            ? "当前为外部兼容服务，本 App 不会停止其持续监控。"
            : "只有当前 App 启动且完成 health/PID/Process 验证的服务可以停止持续监控。"
        status = BackendStatus(
            phase: ownership == .none
                ? .stopped
                : BackendControlPolicy.phaseAfterFailure(
                    startupIsActive: startupGate.isActive,
                    currentPhase: status.phase,
                    ownership: ownership,
                    hasVerifiedHealth: healthSnapshot != nil,
                    message: message
                ),
            message: message
        )
    }

    private func finishControlAction(with payload: [String: Any], token: BackendLifecycleToken) {
        guard BackendLifecyclePolicy.canApplyAsyncCompletion(
            token: token,
            current: lifecycleSnapshot
        ) else {
            return
        }
        let ok = payload["ok"] as? Bool
        let message = payload["message"] as? String
        status = BackendStatus(phase: .running, message: message ?? (ok == false ? "操作返回异常，请查看诊断页" : "操作已完成"))
        reloadWebContent()
    }

    private func failControlAction(with error: Error, token: BackendLifecycleToken) {
        guard BackendLifecyclePolicy.canApplyAsyncCompletion(
            token: token,
            current: lifecycleSnapshot
        ) else {
            return
        }
        status = BackendStatus(phase: .running, message: error.localizedDescription)
    }

    private func finishOwnedControlAction(with payload: [String: Any], token: BackendLifecycleToken) {
        guard BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: token,
            current: lifecycleSnapshot
        ) else {
            return
        }
        let ok = payload["ok"] as? Bool
        let message = payload["message"] as? String
        status = BackendStatus(phase: .running, message: message ?? (ok == false ? "操作返回异常，请查看诊断页" : "操作已完成"))
        reloadWebContent()
    }

    private func failOwnedControlAction(with error: Error, token: BackendLifecycleToken) {
        guard BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: token,
            current: lifecycleSnapshot
        ) else {
            return
        }
        status = BackendStatus(phase: .running, message: error.localizedDescription)
    }

    private func verifyBackend(
        health: BackendHealth,
        manifest: InvoiceHubBuildManifest,
        packageManifest: InvoiceHubPackageManifest,
        paths: BackendPaths,
        port: Int,
        client: InvoiceHubAPIClient
    ) async throws {
        let report = BackendCompatibilityReport.evaluate(
            health: health,
            manifest: manifest,
            packageManifest: packageManifest,
            paths: paths
        )
        guard report.isCompatible else {
            throw BackendLaunchError.incompatible(
                port: port,
                expectedBuildID: manifest.buildID,
                actualBuildID: health.buildID,
                issues: report.issues,
                logPath: paths.stderrLog.path
            )
        }
        do {
            try await client.verifyRequiredRoutes()
        } catch {
            throw BackendLaunchError.requiredRoutes(error.localizedDescription, port, paths.stderrLog.path)
        }
    }

    private func launchBackend(paths: BackendPaths, port: Int) throws -> Process {
        let python = try PythonCommandResolver.resolve(paths: paths)
        let launched = Process()
        launched.executableURL = python.executableURL
        launched.arguments = python.argumentsPrefix + [
            "-m", "invoice_hub.api.main",
            "--root", paths.coreRoot.path,
            "--config", paths.configPath.path,
            "--host", "127.0.0.1",
            "--port", "\(port)"
        ]
        launched.currentDirectoryURL = paths.coreRoot
        launched.environment = backendEnvironment(paths: paths)

        let stdout = try openLogHandle(paths.stdoutLog)
        let stderr = try openLogHandle(paths.stderrLog)
        launched.standardOutput = stdout
        launched.standardError = stderr
        stdoutHandle = stdout
        stderrHandle = stderr
        launched.terminationHandler = { [weak self, weak launched] terminated in
            Task { @MainActor in
                guard let self, let launched else { return }
                let pid = terminated.processIdentifier
                _ = self.finalizeOwnedBackendExit(
                    launched,
                    expectedPID: pid,
                    message: "本地服务已退出，退出码 \(terminated.terminationStatus)"
                )
            }
        }
        do {
            try launched.run()
        } catch {
            closeLogHandles()
            throw error
        }
        process = launched
        ownedPID = launched.processIdentifier
        ownership = .owned
        return launched
    }

    private func writeOwnedPIDFile(paths: BackendPaths, launchedProcess: Process) throws {
        guard self.process === launchedProcess,
              ownedPID == launchedProcess.processIdentifier,
              ownership == .owned
        else {
            throw BackendLaunchError.ownershipConflict(nil, ownedPID)
        }
        try "\(launchedProcess.processIdentifier)\n".write(to: paths.serverPID, atomically: true, encoding: .utf8)
    }

    private func waitForCompatibleHealth(
        client: InvoiceHubAPIClient,
        manifest: InvoiceHubBuildManifest,
        packageManifest: InvoiceHubPackageManifest,
        paths: BackendPaths,
        port: Int,
        timeoutSeconds: Int
    ) async throws -> BackendHealth {
        for _ in 0..<(timeoutSeconds * 10) {
            if let health = await client.health() {
                try await verifyBackend(
                    health: health,
                    manifest: manifest,
                    packageManifest: packageManifest,
                    paths: paths,
                    port: port,
                    client: client
                )
                return health
            }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        throw BackendLaunchError.healthTimeout(paths.stderrLog.path)
    }

    private func waitForOwnedBackendExit(
        expectedPID: Int32,
        token: BackendLifecycleToken,
        timeoutSeconds: Int
    ) async -> Bool {
        for _ in 0..<(timeoutSeconds * 10) {
            let current = lifecycleSnapshot
            if BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(token: token, current: current) {
                return true
            }
            guard BackendLifecyclePolicy.matchesCapturedIdentity(
                token: token,
                current: current
            ) else {
                return false
            }
            if let trackedProcess = process,
               trackedProcess.processIdentifier == expectedPID,
               !trackedProcess.isRunning {
                return finalizeOwnedBackendExit(
                    trackedProcess,
                    expectedPID: expectedPID,
                    message: "本地服务已退出"
                )
            }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        let current = lifecycleSnapshot
        if BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(token: token, current: current) {
            return true
        }
        guard BackendLifecyclePolicy.matchesCapturedIdentity(
            token: token,
            current: current
        ) else {
            return false
        }
        if let trackedProcess = process,
           trackedProcess.processIdentifier == expectedPID,
           !trackedProcess.isRunning {
            return finalizeOwnedBackendExit(
                trackedProcess,
                expectedPID: expectedPID,
                message: "本地服务已退出"
            )
        }
        return false
    }

    @discardableResult
    private func terminateOwnedBackend(waitForExit: Bool) async -> Bool {
        guard ownership == .owned, let pid = ownedPID else { return false }
        guard let trackedProcess = process, trackedProcess.processIdentifier == pid else { return false }
        if trackedProcess.isRunning {
            trackedProcess.terminate()
            if waitForExit {
                for _ in 0..<40 where trackedProcess.isRunning {
                    try? await Task.sleep(nanoseconds: 100_000_000)
                }
            }
        }
        guard !trackedProcess.isRunning else { return false }
        return finalizeOwnedBackendExit(trackedProcess, expectedPID: pid, message: "本地服务已停止")
    }

    @discardableResult
    private func finalizeOwnedBackendExit(_ exitedProcess: Process, expectedPID: Int32, message: String) -> Bool {
        guard self.process === exitedProcess else { return false }
        guard BackendProcessTruth.canFinalizeOwnedExit(
            expectedPID: expectedPID,
            trackedOwnedPID: ownedPID,
            processPID: exitedProcess.processIdentifier,
            processIsRunning: exitedProcess.isRunning
        ) else {
            return false
        }
        advanceLifecycleGeneration()
        process = nil
        closeLogHandles()
        if let pidFile = paths?.serverPID {
            BackendPIDFile.removeIfMatches(pidFile, expectedPID: expectedPID)
        }
        ownedPID = nil
        ownership = .none
        healthSnapshot = nil
        status = BackendStatus(phase: .stopped, message: message)
        return true
    }

    @discardableResult
    private func advanceLifecycleGeneration() -> UInt64 {
        lifecycleGeneration &+= 1
        return lifecycleGeneration
    }

    private func backendEnvironment(paths: BackendPaths) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["INVOICE_HUB_ROOT"] = paths.coreRoot.path
        env["INVOICE_HUB_CONFIG"] = paths.configPath.path
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if Bundle.main.object(forInfoDictionaryKey: "InvoiceHubReleaseMode") as? Bool == true {
            env["INVOICE_HUB_RELEASE_MODE"] = "1"
        } else {
            env.removeValue(forKey: "INVOICE_HUB_RELEASE_MODE")
        }
        let sourcePath = paths.coreRoot.appendingPathComponent("src", isDirectory: true).path
        env["PYTHONPATH"] = env["PYTHONPATH"].map { sourcePath + ":" + $0 } ?? sourcePath
        return env
    }

    private func openLogHandle(_ url: URL) throws -> FileHandle {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: url)
        try handle.truncate(atOffset: 0)
        return handle
    }

    private func closeLogHandles() {
        try? stdoutHandle?.close()
        try? stderrHandle?.close()
        stdoutHandle = nil
        stderrHandle = nil
    }
}

public enum BackendLaunchError: LocalizedError, Equatable {
    case healthTimeout(String)
    case incompatible(port: Int, expectedBuildID: String, actualBuildID: String?, issues: [String], logPath: String)
    case requiredRoutes(String, Int, String)
    case shutdownRejected(String)
    case shutdownTimeout(String)
    case ownershipConflict(Int?, Int32?)
    case ownedProcessUnavailable(Int32?)

    public var errorDescription: String? {
        switch self {
        case .healthTimeout(let logPath):
            return "本地服务启动超时。未自动换端口，请检查占用进程与日志: \(logPath)"
        case .incompatible(let port, let expected, let actual, let issues, let logPath):
            return "拒绝连接版本或运行目录不一致的后端。端口: \(port)\n预期 build_id: \(expected)\n实际 build_id: \(actual ?? "缺失")\n\(issues.joined(separator: "\n"))\n日志: \(logPath)\n请关闭旧版 InvoiceHub 后重新运行构建脚本；未知占用进程不会被终止。"
        case .requiredRoutes(let detail, let port, let logPath):
            return "后端缺少首页、单据页或单据状态接口，拒绝接入。端口: \(port)\n实际错误: \(detail)\n日志: \(logPath)"
        case .shutdownRejected(let detail):
            return "后端拒绝关闭请求：\(detail)"
        case .shutdownTimeout(let logPath):
            let suffix = logPath.isEmpty ? "" : " 日志: \(logPath)"
            return "等待 owned 后端自行退出超时；未强制终止进程或删除 PID。\(suffix)"
        case .ownershipConflict(let healthPID, let ownedPID):
            return "兼容后端 PID \(healthPID.map(String.init) ?? "缺失") 与仍在运行的 owned PID \(ownedPID.map(String.init) ?? "缺失") 不一致；保留 owned 进程真值并拒绝降级为外部服务。"
        case .ownedProcessUnavailable(let ownedPID):
            return "owned 后端 PID \(ownedPID.map(String.init) ?? "缺失") 尚未提供兼容 health；保留现有进程真值，拒绝启动第二个后端。"
        }
    }
}

public enum BackendUpdateError: LocalizedError, Equatable {
    case backendUnavailable
    case ownedLifecycleRequired
    case monitorDidNotStop
    case monitorDidNotRestore

    public var errorDescription: String? {
        switch self {
        case .backendUnavailable:
            return "本地后端尚未完成健康握手，不能安装更新。"
        case .ownedLifecycleRequired:
            return "当前连接不是本 App 已验证拥有的后端，不能安装更新或变更持续监控。"
        case .monitorDidNotStop:
            return "持续监控未确认停止，已阻止旧版本退出。"
        case .monitorDidNotRestore:
            return "新版本未确认持续监控恢复就绪。"
        }
    }
}
