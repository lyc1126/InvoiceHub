import AppKit
import Foundation
import Sparkle

@MainActor
public final class InvoiceHubSparkleUpdater: NSObject, ObservableObject, SPUUpdaterDelegate {
    private weak var backend: LocalBackendController?
    private var installIdentity: BackendLifecycleToken?
    private lazy var controller = SPUStandardUpdaterController(
        startingUpdater: true,
        updaterDelegate: self,
        userDriverDelegate: nil
    )

    public func beginUserInitiatedUpdate(using backend: LocalBackendController) throws -> [String: Any] {
        guard backend.updateInstallLifecycleToken() != nil else {
            throw SparkleUpdateError.ownedBackendRequired
        }
        guard let feed = Bundle.main.object(forInfoDictionaryKey: "SUFeedURL") as? String,
              let feedURL = URL(string: feed),
              feedURL.scheme == "https",
              feedURL.host == "lyc1126.github.io",
              let publicKey = Bundle.main.object(forInfoDictionaryKey: "SUPublicEDKey") as? String,
              !publicKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else {
            throw SparkleUpdateError.notConfigured
        }

        let alert = NSAlert()
        alert.messageText = "准备安装 InvoiceHub 更新？"
        alert.informativeText = "如果持续监控正在运行，安装前会先确认它已停止；新版本完成健康握手后会自动恢复。取消更新不会改变当前监控状态。"
        alert.alertStyle = .informational
        alert.addButton(withTitle: "继续")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else {
            return ["ok": true, "started": false, "cancelled": true]
        }

        guard let identity = backend.updateInstallLifecycleToken() else {
            throw SparkleUpdateError.ownedBackendRequired
        }
        guard controller.updater.canCheckForUpdates else {
            throw SparkleUpdateError.busy
        }
        self.backend = backend
        installIdentity = identity
        controller.checkForUpdates(nil)
        return ["ok": true, "started": true, "cancelled": false]
    }

    public func allowedChannels(for updater: SPUUpdater) -> Set<String> {
        ["beta"]
    }

    public func updater(
        _ updater: SPUUpdater,
        shouldPostponeRelaunchForUpdate item: SUAppcastItem,
        untilInvokingBlock installHandler: @escaping () -> Void
    ) -> Bool {
        guard let backend, let identity = installIdentity,
              backend.isCurrentUpdateInstallIdentity(identity)
        else {
            let staleBackend = self.backend
            clearPendingInstallCycle()
            Task { @MainActor in
                await staleBackend?.restoreMonitorAfterUpdateIfNeeded()
                self.showPausedInstallAlert(for: BackendUpdateError.ownedLifecycleRequired)
            }
            // Returning false would allow Sparkle to relaunch without the monitor safety gate.
            return true
        }
        Task { @MainActor in
            do {
                try await backend.prepareMonitorForUpdateInstall(expectedIdentity: identity)
                guard backend.isCurrentUpdateInstallIdentity(identity) else {
                    throw BackendUpdateError.ownedLifecycleRequired
                }
                installHandler()
            } catch {
                await backend.restoreMonitorAfterUpdateIfNeeded()
                clearPendingInstallCycle()
                showPausedInstallAlert(for: error)
            }
        }
        return true
    }

    public func userDidCancelDownload(_ updater: SPUUpdater) {
        restoreMonitorAfterCancelledCycle()
    }

    public func updater(_ updater: SPUUpdater, didAbortWithError error: Error) {
        restoreMonitorAfterCancelledCycle()
    }

    public func updater(
        _ updater: SPUUpdater,
        didFinishUpdateCycleFor updateCheck: SPUUpdateCheck,
        error: Error?
    ) {
        if error != nil {
            restoreMonitorAfterCancelledCycle()
        }
    }

    private func restoreMonitorAfterCancelledCycle() {
        let backend = backend
        clearPendingInstallCycle()
        Task { @MainActor in
            await backend?.restoreMonitorAfterUpdateIfNeeded()
        }
    }

    private func clearPendingInstallCycle() {
        installIdentity = nil
        backend = nil
    }

    private func showPausedInstallAlert(for error: Error) {
        let alert = NSAlert(error: error)
        alert.messageText = "更新安装已暂停"
        alert.informativeText = "持续监控只能由当前 App 已验证拥有的后端安全停止。InvoiceHub 没有退出旧版本；请处理诊断后重新检查更新。\n\n\(error.localizedDescription)"
        alert.runModal()
    }
}

public enum SparkleUpdateError: LocalizedError {
    case notConfigured
    case busy
    case ownedBackendRequired

    public var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "当前 App 未配置经过验证的 Sparkle 更新源或 EdDSA 公钥。"
        case .busy:
            return "Sparkle 正在处理另一项更新操作，请稍后重试。"
        case .ownedBackendRequired:
            return "当前连接不是本 App 已验证拥有的后端，不能安装更新或变更持续监控。"
        }
    }
}
