import Foundation
@preconcurrency import JavaScriptCore
import XCTest
@preconcurrency import WebKit
@testable import InvoiceHubClient

final class StartupSurfaceTests: XCTestCase {
    func testStartupSurfaceDefaultsToDesktopAndAcceptsBrowser() {
        XCTAssertEqual(StartupSurface.normalized(nil), .desktop)
        XCTAssertEqual(StartupSurface.normalized("unknown"), .desktop)
        XCTAssertEqual(StartupSurface.normalized("browser"), .browser)
        XCTAssertEqual(StartupSurface.normalized("desktop"), .desktop)
    }
}

private final class InvoiceHubURLProtocolStub: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: InvoiceHubAPIError.invalidResponse)
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private final class PopupPrintMessageHandlerStub: NSObject, WKScriptMessageHandler {
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {}
}

private final class PrintPopupLifetimeProbe: NSObject {}

private func lifecycleSnapshot(
    generation: UInt64 = 1,
    phase: BackendPhase = .running,
    ownership: BackendOwnership = .owned,
    healthPID: Int? = 123,
    ownedPID: Int32? = 123,
    processPID: Int32? = 123,
    processIsRunning: Bool = true
) -> BackendLifecycleSnapshot {
    BackendLifecycleSnapshot(
        generation: generation,
        phase: phase,
        ownership: ownership,
        healthPID: healthPID,
        ownedPID: ownedPID,
        processPID: processPID,
        processIsRunning: processIsRunning
    )
}

final class BackendPathResolverTests: XCTestCase {
    func testStartupGateRejectsConcurrentAttemptUntilRelease() {
        var gate = BackendStartupGate()

        XCTAssertTrue(gate.tryAcquire(phase: .idle, ownership: .none))
        XCTAssertTrue(gate.isActive)
        XCTAssertFalse(gate.tryAcquire(phase: .idle, ownership: .none))

        gate.release()

        XCTAssertFalse(gate.isActive)
        XCTAssertTrue(gate.tryAcquire(phase: .failed("retry"), ownership: .owned))
    }

    func testStartupGateRejectsTransitionalAndRunningStates() {
        for phase in [BackendPhase.starting, .stopping, .running] {
            var gate = BackendStartupGate()
            XCTAssertFalse(gate.tryAcquire(phase: phase, ownership: .none))
            XCTAssertFalse(gate.isActive)
        }

        var ownedRunning = BackendStartupGate()
        XCTAssertFalse(ownedRunning.tryAcquire(phase: .running, ownership: .owned))
        var externalRunning = BackendStartupGate()
        XCTAssertFalse(externalRunning.tryAcquire(phase: .running, ownership: .externalCompatible))
        var staleExternal = BackendStartupGate()
        XCTAssertFalse(staleExternal.tryAcquire(phase: .failed("stale"), ownership: .externalCompatible))
    }

    func testBackendControlPolicyBlocksActionsDuringTransitions() {
        XCTAssertTrue(BackendControlPolicy.blocksControlAction(startupIsActive: true, phase: .idle))
        XCTAssertTrue(BackendControlPolicy.blocksControlAction(startupIsActive: false, phase: .starting))
        XCTAssertTrue(BackendControlPolicy.blocksControlAction(startupIsActive: false, phase: .stopping))
        XCTAssertFalse(BackendControlPolicy.blocksControlAction(startupIsActive: false, phase: .running))
        XCTAssertFalse(BackendControlPolicy.blocksControlAction(startupIsActive: false, phase: .failed("retry")))
    }

    func testBackendControlPolicyRequiresVerifiedOwnedRunningStateForLifecycleManagement() {
        XCTAssertTrue(BackendControlPolicy.canManageBackend(
            startupIsActive: false,
            lifecycle: lifecycleSnapshot()
        ))
        XCTAssertFalse(BackendControlPolicy.canManageBackend(
            startupIsActive: true,
            lifecycle: lifecycleSnapshot()
        ))
        XCTAssertFalse(BackendControlPolicy.canManageBackend(
            startupIsActive: false,
            lifecycle: lifecycleSnapshot(phase: .starting)
        ))
        XCTAssertFalse(BackendControlPolicy.canManageBackend(
            startupIsActive: false,
            lifecycle: lifecycleSnapshot(healthPID: nil)
        ))
        XCTAssertFalse(BackendControlPolicy.canManageBackend(
            startupIsActive: false,
            lifecycle: lifecycleSnapshot(
                ownership: .externalCompatible,
                healthPID: 456,
                ownedPID: nil,
                processPID: nil,
                processIsRunning: false
            )
        ))
    }

    func testUpdateLifecycleRequiresCurrentVerifiedOwnedIdentity() {
        let owned = lifecycleSnapshot(generation: 7)
        let ownedToken = BackendLifecycleToken(capturing: owned)
        let external = lifecycleSnapshot(
            generation: 7,
            ownership: .externalCompatible,
            healthPID: 456,
            ownedPID: nil,
            processPID: nil,
            processIsRunning: false
        )
        let externalToken = BackendLifecycleToken(capturing: external)

        XCTAssertTrue(BackendControlPolicy.canManageUpdateLifecycle(
            startupIsActive: false,
            lifecycle: owned
        ))
        XCTAssertTrue(BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: ownedToken,
            current: owned
        ))
        XCTAssertFalse(BackendControlPolicy.canManageUpdateLifecycle(
            startupIsActive: true,
            lifecycle: owned
        ))
        XCTAssertFalse(BackendControlPolicy.canManageUpdateLifecycle(
            startupIsActive: false,
            lifecycle: external
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: externalToken,
            current: external
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyOwnedAsyncCompletion(
            token: ownedToken,
            current: lifecycleSnapshot(generation: 8)
        ))
    }

    func testMarkerPresentStartupRecoveryBecomesEligibleOnlyAfterVerifiedOwnedStartupReleasesGate() {
        var gate = BackendStartupGate()
        let owned = lifecycleSnapshot(generation: 7)

        XCTAssertTrue(gate.tryAcquire(phase: .idle, ownership: .none))
        XCTAssertTrue(BackendUpdateMonitorRecoveryPolicy.canFinalizeStartupForRecovery(
            startupGateIsActive: gate.isActive,
            lifecycle: owned
        ))
        XCTAssertFalse(BackendUpdateMonitorRecoveryPolicy.canRecoverMarkedMonitor(
            markerIsPresent: true,
            startupGateIsActive: gate.isActive,
            lifecycle: owned
        ))

        XCTAssertTrue(gate.releaseAfterVerifiedOwnedStartup(lifecycle: owned))
        XCTAssertFalse(gate.isActive)
        XCTAssertTrue(BackendUpdateMonitorRecoveryPolicy.canRecoverMarkedMonitor(
            markerIsPresent: true,
            startupGateIsActive: gate.isActive,
            lifecycle: owned
        ))
        XCTAssertFalse(BackendUpdateMonitorRecoveryPolicy.canRecoverMarkedMonitor(
            markerIsPresent: false,
            startupGateIsActive: gate.isActive,
            lifecycle: owned
        ))

        var externalGate = BackendStartupGate()
        let external = lifecycleSnapshot(
            generation: 7,
            ownership: .externalCompatible,
            healthPID: 456,
            ownedPID: nil,
            processPID: nil,
            processIsRunning: false
        )
        XCTAssertTrue(externalGate.tryAcquire(phase: .idle, ownership: .none))
        XCTAssertFalse(externalGate.releaseAfterVerifiedOwnedStartup(lifecycle: external))
        XCTAssertTrue(externalGate.isActive)
        XCTAssertFalse(BackendUpdateMonitorRecoveryPolicy.canRecoverMarkedMonitor(
            markerIsPresent: true,
            startupGateIsActive: false,
            lifecycle: external
        ))
    }

    func testAsyncCompletionAcceptsSameVerifiedOwnedRunningIdentity() {
        let current = lifecycleSnapshot(generation: 7)
        let token = BackendLifecycleToken(capturing: current)

        XCTAssertTrue(BackendLifecyclePolicy.canApplyAsyncCompletion(token: token, current: current))
        XCTAssertTrue(BackendControlPolicy.canRunControlAction(
            startupIsActive: false,
            lifecycle: current
        ))
    }

    func testAsyncCompletionAcceptsVerifiedExternalRunningIdentity() {
        let current = lifecycleSnapshot(
            generation: 7,
            ownership: .externalCompatible,
            healthPID: 456,
            ownedPID: nil,
            processPID: nil,
            processIsRunning: false
        )
        let token = BackendLifecycleToken(capturing: current)

        XCTAssertTrue(BackendLifecyclePolicy.canApplyAsyncCompletion(token: token, current: current))
        XCTAssertTrue(BackendControlPolicy.canRunControlAction(
            startupIsActive: false,
            lifecycle: current
        ))
    }

    func testAsyncCompletionRejectsNewGenerationEvenAfterReturningToRunning() {
        let original = lifecycleSnapshot(generation: 7)
        let token = BackendLifecycleToken(capturing: original)
        let restarted = lifecycleSnapshot(generation: 10)

        XCTAssertFalse(BackendLifecyclePolicy.canApplyAsyncCompletion(token: token, current: restarted))
    }

    func testAsyncCompletionRejectsLifecyclePhaseTransitions() {
        let original = lifecycleSnapshot(generation: 7)
        let token = BackendLifecycleToken(capturing: original)

        for phase in [BackendPhase.starting, .stopping, .stopped] {
            XCTAssertFalse(BackendLifecyclePolicy.canApplyAsyncCompletion(
                token: token,
                current: lifecycleSnapshot(generation: 7, phase: phase)
            ))
        }
    }

    func testAsyncCompletionRejectsChangedProcessIdentityOrDeadProcess() {
        let original = lifecycleSnapshot(generation: 7)
        let token = BackendLifecycleToken(capturing: original)
        let changedSnapshots = [
            lifecycleSnapshot(generation: 7, healthPID: 456),
            lifecycleSnapshot(generation: 7, ownedPID: 456),
            lifecycleSnapshot(generation: 7, processPID: 456),
            lifecycleSnapshot(generation: 7, processIsRunning: false)
        ]

        for current in changedSnapshots {
            XCTAssertFalse(BackendLifecyclePolicy.canApplyAsyncCompletion(token: token, current: current))
        }
    }

    func testStopFailureCanRestoreOnlyOriginalStoppingIdentity() {
        let stopping = lifecycleSnapshot(generation: 8, phase: .stopping)
        let token = BackendLifecycleToken(capturing: stopping)

        XCTAssertTrue(BackendLifecyclePolicy.canApplyAsyncCompletion(token: token, current: stopping))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyAsyncCompletion(
            token: token,
            current: lifecycleSnapshot(generation: 8, phase: .running)
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyAsyncCompletion(
            token: token,
            current: lifecycleSnapshot(generation: 9, phase: .stopping)
        ))
    }

    func testDirectOwnedExitRequiresExactlyNextStoppedGeneration() {
        let stopping = lifecycleSnapshot(generation: 8, phase: .stopping)
        let token = BackendLifecycleToken(capturing: stopping)
        let confirmedExit = lifecycleSnapshot(
            generation: 9,
            phase: .stopped,
            ownership: .none,
            healthPID: nil,
            ownedPID: nil,
            processPID: nil,
            processIsRunning: false
        )

        XCTAssertTrue(BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(
            token: token,
            current: confirmedExit
        ))
        XCTAssertFalse(BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(
            token: token,
            current: lifecycleSnapshot(
                generation: 8,
                phase: .stopped,
                ownership: .none,
                healthPID: nil,
                ownedPID: nil,
                processPID: nil,
                processIsRunning: false
            )
        ))
        XCTAssertFalse(BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(
            token: token,
            current: lifecycleSnapshot(
                generation: 10,
                phase: .stopped,
                ownership: .none,
                healthPID: nil,
                ownedPID: nil,
                processPID: nil,
                processIsRunning: false
            )
        ))
    }

    func testDirectOwnedExitDoesNotAcceptNewerLifecycleTransitions() {
        let stopping = lifecycleSnapshot(generation: 8, phase: .stopping)
        let token = BackendLifecycleToken(capturing: stopping)

        for phase in [BackendPhase.starting, .stopping, .stopped] {
            XCTAssertFalse(BackendLifecyclePolicy.isDirectlyConfirmedOwnedExit(
                token: token,
                current: lifecycleSnapshot(
                    generation: 10,
                    phase: phase,
                    ownership: phase == .stopped ? .none : .owned,
                    healthPID: phase == .stopped ? nil : 123,
                    ownedPID: phase == .stopped ? nil : 123,
                    processPID: phase == .stopped ? nil : 123,
                    processIsRunning: phase != .stopped
                )
            ))
        }
    }

    func testStartupCompletionRequiresOriginalStartingGeneration() {
        XCTAssertTrue(BackendLifecyclePolicy.canApplyStartupCompletion(
            generation: 7,
            current: lifecycleSnapshot(generation: 7, phase: .starting)
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyStartupCompletion(
            generation: 7,
            current: lifecycleSnapshot(generation: 8, phase: .starting)
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyStartupCompletion(
            generation: 7,
            current: lifecycleSnapshot(generation: 7, phase: .running)
        ))
    }

    func testStartupFailureRequiresOriginalLiveAttemptedProcess() {
        let original = lifecycleSnapshot(
            generation: 7,
            phase: .starting,
            healthPID: nil
        )

        XCTAssertTrue(BackendLifecyclePolicy.canApplyStartupFailure(
            generation: 7,
            attemptedPID: 123,
            current: original
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyStartupFailure(
            generation: 8,
            attemptedPID: 123,
            current: original
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyStartupFailure(
            generation: 7,
            attemptedPID: 456,
            current: original
        ))
        XCTAssertFalse(BackendLifecyclePolicy.canApplyStartupFailure(
            generation: 7,
            attemptedPID: 123,
            current: lifecycleSnapshot(
                generation: 7,
                phase: .starting,
                healthPID: nil,
                processIsRunning: false
            )
        ))
    }

    func testStartupFailurePreservesOriginalErrorAfterExpectedCleanupFinalizes() {
        let token = BackendStartupFailureToken(generation: 7, attemptedPID: 123)
        let finalizedAttempt = lifecycleSnapshot(
            generation: 8,
            phase: .stopped,
            ownership: .none,
            healthPID: nil,
            ownedPID: nil,
            processPID: nil,
            processIsRunning: false
        )
        let logPath = "/tmp/Invoice Hub/backend stderr.log"
        let originalError = BackendLaunchError.healthTimeout(logPath).localizedDescription

        let phase = BackendLifecyclePolicy.startupFailurePhase(
            token: token,
            cleanupResult: .finalizedAttempt(123),
            current: finalizedAttempt,
            message: originalError
        )

        XCTAssertEqual(phase, .failed(originalError))
        XCTAssertTrue(originalError.contains(logPath))
    }

    func testStartupFailureCleanupCannotOverwriteNewLifecycle() {
        let token = BackendStartupFailureToken(generation: 7, attemptedPID: 123)
        let cleanupResult = BackendStartupCleanupResult.finalizedAttempt(123)
        let staleSnapshots = [
            lifecycleSnapshot(
                generation: 9,
                phase: .stopped,
                ownership: .none,
                healthPID: nil,
                ownedPID: nil,
                processPID: nil,
                processIsRunning: false
            ),
            lifecycleSnapshot(
                generation: 8,
                phase: .starting,
                ownership: .owned,
                healthPID: nil,
                ownedPID: 456,
                processPID: 456,
                processIsRunning: true
            )
        ]

        for current in staleSnapshots {
            XCTAssertNil(BackendLifecyclePolicy.startupFailurePhase(
                token: token,
                cleanupResult: cleanupResult,
                current: current,
                message: "original failure"
            ))
        }
        XCTAssertNil(BackendLifecyclePolicy.startupFailurePhase(
            token: token,
            cleanupResult: .finalizedAttempt(456),
            current: lifecycleSnapshot(
                generation: 8,
                phase: .stopped,
                ownership: .none,
                healthPID: nil,
                ownedPID: nil,
                processPID: nil,
                processIsRunning: false
            ),
            message: "original failure"
        ))
    }

    func testBackendControlFailureCannotPromoteUnverifiedOwnedProcessToRunning() {
        XCTAssertEqual(
            BackendControlPolicy.phaseAfterFailure(
                startupIsActive: true,
                currentPhase: .starting,
                ownership: .owned,
                hasVerifiedHealth: false,
                message: "failed"
            ),
            .starting
        )
        XCTAssertEqual(
            BackendControlPolicy.phaseAfterFailure(
                startupIsActive: false,
                currentPhase: .running,
                ownership: .owned,
                hasVerifiedHealth: false,
                message: "failed"
            ),
            .failed("failed")
        )
        XCTAssertEqual(
            BackendControlPolicy.phaseAfterFailure(
                startupIsActive: false,
                currentPhase: .stopping,
                ownership: .owned,
                hasVerifiedHealth: true,
                message: "failed"
            ),
            .stopping
        )
    }

    func testBackendControlFailurePreservesOnlyVerifiedRunningBackends() {
        for ownership in [BackendOwnership.owned, .externalCompatible] {
            XCTAssertEqual(
                BackendControlPolicy.phaseAfterFailure(
                    startupIsActive: false,
                    currentPhase: .running,
                    ownership: ownership,
                    hasVerifiedHealth: true,
                    message: "failed"
                ),
                .running
            )
        }
        XCTAssertEqual(
            BackendControlPolicy.phaseAfterFailure(
                startupIsActive: false,
                currentPhase: .failed("already failed"),
                ownership: .owned,
                hasVerifiedHealth: true,
                message: "failed"
            ),
            .failed("failed")
        )
    }

    @MainActor
    func testReloadWebContentAdvancesToken() {
        let controller = LocalBackendController()
        let initial = controller.webRefreshToken

        controller.reloadWebContent()

        XCTAssertEqual(controller.webRefreshToken, initial + 1)
    }

    func testFindCoreRootWalksParentDirectories() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let api = root
            .appendingPathComponent("src/invoice_hub/api", isDirectory: true)
        let templates = root
            .appendingPathComponent("web/templates", isDirectory: true)
        try FileManager.default.createDirectory(at: api, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: templates, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: api.appendingPathComponent("main.py").path, contents: Data())

        let nested = root.appendingPathComponent("macos/InvoiceHubMac/Sources", isDirectory: true)
        try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)

        XCTAssertEqual(try BackendPaths.findCoreRoot(startingAt: nested).standardizedFileURL, root.standardizedFileURL)
        try FileManager.default.removeItem(at: root)
    }

    func testReleasePathResolverRejectsMissingOrInvalidEmbeddedCoreWithoutDevelopmentFallback() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let fallbackCore = root.appendingPathComponent("checkout", isDirectory: true)
        let fallbackAPI = fallbackCore.appendingPathComponent("src/invoice_hub/api", isDirectory: true)
        let fallbackTemplates = fallbackCore.appendingPathComponent("web/templates", isDirectory: true)
        let resources = root.appendingPathComponent("Resources", isDirectory: true)
        let embeddedCore = resources.appendingPathComponent("invoice-hub-core", isDirectory: true)
        try FileManager.default.createDirectory(at: fallbackAPI, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: fallbackTemplates, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: fallbackAPI.appendingPathComponent("main.py").path, contents: Data())

        XCTAssertThrowsError(try BackendPaths.resolve(
            startingAt: fallbackCore,
            bundleResourceURL: resources,
            releaseMode: true
        )) { error in
            XCTAssertEqual(error as? BackendPathError, .releaseCoreUnavailable(embeddedCore.path))
        }

        try FileManager.default.createDirectory(at: embeddedCore, withIntermediateDirectories: true)
        XCTAssertThrowsError(try BackendPaths.resolve(
            startingAt: fallbackCore,
            bundleResourceURL: resources,
            releaseMode: true
        )) { error in
            XCTAssertEqual(error as? BackendPathError, .releaseCoreUnavailable(embeddedCore.path))
        }

        let developmentPaths = try BackendPaths.resolve(
            startingAt: fallbackCore,
            bundleResourceURL: resources,
            releaseMode: false
        )
        XCTAssertEqual(developmentPaths.coreRoot.standardizedFileURL, fallbackCore.standardizedFileURL)

        let embeddedAPI = embeddedCore.appendingPathComponent("src/invoice_hub/api", isDirectory: true)
        let embeddedTemplates = embeddedCore.appendingPathComponent("web/templates", isDirectory: true)
        try FileManager.default.createDirectory(at: embeddedAPI, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: embeddedTemplates, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: embeddedAPI.appendingPathComponent("main.py").path, contents: Data())
        let releasePaths = try BackendPaths.resolve(
            startingAt: fallbackCore,
            bundleResourceURL: resources,
            releaseMode: true
        )
        XCTAssertEqual(releasePaths.coreRoot.standardizedFileURL, embeddedCore.standardizedFileURL)
    }

    func testDefaultConfigUsesProvidedWritableLocations() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let watch = root.appendingPathComponent("发票文件", isDirectory: true)
        let runtime = root.appendingPathComponent("runtime", isDirectory: true)
        let payload = InvoiceHubConfig.defaultPayload(watchDir: watch, runtimeDir: runtime, port: 8766)

        XCTAssertEqual(payload["host"] as? String, "127.0.0.1")
        XCTAssertEqual(payload["port"] as? Int, 8766)
        XCTAssertEqual(payload["watch_dir"] as? String, watch.path)
        XCTAssertEqual(payload["runtime_dir"] as? String, runtime.path)
        XCTAssertEqual(payload["reference_markup_rate"] as? String, "0.08")
    }

    func testDocumentsRouteIsAvailableInMacShell() {
        XCTAssertTrue(AppRoute.allCases.contains(.documents))
        XCTAssertEqual(AppRoute.documents.title, "单据")
        XCTAssertEqual(AppRoute.documents.webPath, "/documents")
    }

    func testUserNavigationOrderExcludesDiagnostics() {
        XCTAssertEqual(
            AppRoute.userNavigationRoutes,
            [.home, .costs, .documents, .bookkeeping, .ocr, .consistency, .settings]
        )
        XCTAssertFalse(AppRoute.userNavigationRoutes.contains(.backend))
        XCTAssertFalse(AppRoute.userNavigationRoutes.contains(.skins))
    }

    func testBookkeepingRouteIsAvailableInMacShell() {
        XCTAssertTrue(AppRoute.allCases.contains(.bookkeeping))
        XCTAssertEqual(AppRoute.bookkeeping.title, "做账")
        XCTAssertEqual(AppRoute.bookkeeping.webPath, "/bookkeeping")
    }

    func testSettingsRouteIsAvailableInMacShell() {
        XCTAssertTrue(AppRoute.allCases.contains(.settings))
        XCTAssertEqual(AppRoute.settings.title, "设置")
        XCTAssertEqual(AppRoute.settings.webPath, "/settings")
    }

    func testCurrentBackendCapabilitiesCoverSyncedWebModules() {
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.review"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.executability.v2"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.import-batch.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.import-finalize.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.jierui.facts.v2"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.jierui.runner.dry-run.v2"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.state-cas.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.w9-ledger-review.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.mapping-resolution.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.targeted-recompute.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("bookkeeping.migration-cas.v2"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("costs.internal-scroll"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("settings.center.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("settings.preferences.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("diagnostics.support-package.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("invoices.classification.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("invoices.rename-safe.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("invoices.selection-summary.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("monitor.ready-handshake.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("server.shutdown-choice.v1"))
        XCTAssertTrue(BackendCompatibilityReport.requiredCapabilities.contains("skins.zip-portable"))
    }

    func testSkinFilePickerAcceptsOnlyOneZipFile() {
        let policy = WebFilePickerPolicy.resolve(
            pagePath: AppRoute.skins.webPath,
            allowsDirectories: false,
            allowsMultipleSelection: false
        )

        XCTAssertTrue(policy.canChooseFiles)
        XCTAssertFalse(policy.canChooseDirectories)
        XCTAssertFalse(policy.allowsMultipleSelection)
        XCTAssertEqual(policy.allowedContentTypes, [.zip])
    }

    func testGenericWebFilePickerKeepsRequestedMultiplicityWithoutTypeRestriction() {
        let policy = WebFilePickerPolicy.resolve(
            pagePath: AppRoute.documents.webPath,
            allowsDirectories: false,
            allowsMultipleSelection: true
        )

        XCTAssertTrue(policy.canChooseFiles)
        XCTAssertFalse(policy.canChooseDirectories)
        XCTAssertTrue(policy.allowsMultipleSelection)
        XCTAssertTrue(policy.allowedContentTypes.isEmpty)
    }

    func testWebDirectoryPickerDoesNotAlsoSelectFiles() {
        let policy = WebFilePickerPolicy.resolve(
            pagePath: AppRoute.home.webPath,
            allowsDirectories: true,
            allowsMultipleSelection: false
        )

        XCTAssertFalse(policy.canChooseFiles)
        XCTAssertTrue(policy.canChooseDirectories)
        XCTAssertTrue(policy.allowedContentTypes.isEmpty)
    }

    func testWebOriginPolicyAllowsOnlyHandshakeLoopbackMainFrame() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))

        XCTAssertTrue(WebOriginPolicy.allowsMainFrameURL(
            URL(string: "http://127.0.0.1:8766/settings?no_skin=1"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsMainFrameURL(
            URL(string: "http://localhost:8766/settings"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsMainFrameURL(
            URL(string: "https://127.0.0.1:8766/settings"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsMainFrameURL(
            URL(string: "http://127.0.0.1:8767/settings"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsMainFrameURL(
            URL(string: "http://127.0.0.1:8766/settings"),
            expectedBaseURL: expected,
            isMainFrame: false
        ))
    }

    func testWebOriginPolicyRequiresMatchingMainFrameSecurityOrigin() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))

        XCTAssertTrue(WebOriginPolicy.allowsScriptMessage(
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsScriptMessage(
            scheme: "http",
            host: "127.0.0.1",
            port: 8767,
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebOriginPolicy.allowsScriptMessage(
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: false
        ))
    }

    func testPrintPopupPolicyOnlyCreatesTrustedMainAboutBlankWindow() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))
        let trustedSource = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))

        XCTAssertTrue(WebPopupPolicy.allowsCreation(
            sourceURL: trustedSource,
            requestedURL: URL(string: "about:blank"),
            sourceScheme: "http",
            sourceHost: "127.0.0.1",
            sourcePort: 8766,
            expectedBaseURL: expected,
            sourceIsMainFrame: true
        ))
        XCTAssertFalse(WebPopupPolicy.allowsCreation(
            sourceURL: trustedSource,
            requestedURL: URL(string: "http://127.0.0.1:8766/invoices/print/job123"),
            sourceScheme: "http",
            sourceHost: "127.0.0.1",
            sourcePort: 8766,
            expectedBaseURL: expected,
            sourceIsMainFrame: true
        ))
        XCTAssertFalse(WebPopupPolicy.allowsCreation(
            sourceURL: trustedSource,
            requestedURL: URL(string: "about:blank#unexpected"),
            sourceScheme: "http",
            sourceHost: "127.0.0.1",
            sourcePort: 8766,
            expectedBaseURL: expected,
            sourceIsMainFrame: true
        ))
        XCTAssertFalse(WebPopupPolicy.allowsCreation(
            sourceURL: trustedSource,
            requestedURL: URL(string: "about:blank"),
            sourceScheme: "http",
            sourceHost: "127.0.0.1",
            sourcePort: 8767,
            expectedBaseURL: expected,
            sourceIsMainFrame: true
        ))
        XCTAssertFalse(WebPopupPolicy.allowsCreation(
            sourceURL: trustedSource,
            requestedURL: URL(string: "about:blank"),
            sourceScheme: "http",
            sourceHost: "127.0.0.1",
            sourcePort: 8766,
            expectedBaseURL: expected,
            sourceIsMainFrame: false
        ))
    }

    func testPrintPopupPolicyAllowsOnlyOneSameOriginPrintRoute() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))
        let allowed = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/invoices/print/job_123-abc"))

        XCTAssertEqual(
            WebPopupPolicy.printPath(for: allowed, expectedBaseURL: expected, isMainFrame: true),
            allowed.path
        )
        for nonCanonicalRoute in [
            "http://127.0.0.1:8766/invoices/print/job_123-abc/",
            "http://127.0.0.1:8766/invoices//print/job_123-abc",
            "http://127.0.0.1:8766/invoices/print/job_123-abc/another-component",
        ] {
            XCTAssertNil(WebPopupPolicy.printPath(
                for: URL(string: nonCanonicalRoute),
                expectedBaseURL: expected,
                isMainFrame: true
            ))
        }
        XCTAssertNil(WebPopupPolicy.printPath(
            for: URL(string: "http://127.0.0.1:8766/settings"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertNil(WebPopupPolicy.printPath(
            for: URL(string: "http://127.0.0.1:8766/invoices/print/job123?retry=1"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertNil(WebPopupPolicy.printPath(
            for: URL(string: "https://127.0.0.1:8766/invoices/print/job123"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertNil(WebPopupPolicy.printPath(
            for: URL(string: "http://127.0.0.1:8767/invoices/print/job123"),
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertNil(WebPopupPolicy.printPath(
            for: allowed,
            expectedBaseURL: expected,
            isMainFrame: false
        ))
    }

    func testPrintPopupNavigationAllowsOnlyMainFramePrintRoute() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))
        let route = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/invoices/print/job123"))

        XCTAssertEqual(
            WebPopupPolicy.printPathForPopupNavigation(
                route,
                expectedBaseURL: expected,
                sourceIsMainFrame: true,
                targetIsMainFrame: true
            ),
            "/invoices/print/job123"
        )
        XCTAssertNil(WebPopupPolicy.printPathForPopupNavigation(
            route,
            expectedBaseURL: expected,
            sourceIsMainFrame: true,
            targetIsMainFrame: false
        ))
        XCTAssertNil(WebPopupPolicy.printPathForPopupNavigation(
            route,
            expectedBaseURL: expected,
            sourceIsMainFrame: true,
            targetIsMainFrame: nil
        ))
    }

    func testInitialPopupBlankNavigationAllowsOnlyCreationHandoffTargetRoles() {
        let blank = URL(string: "about:blank")

        XCTAssertTrue(WebPopupPolicy.allowsInitialPopupBlankNavigation(
            blank,
            sourceIsMainFrame: true,
            targetIsMainFrame: true
        ))
        XCTAssertTrue(WebPopupPolicy.allowsInitialPopupBlankNavigation(
            blank,
            sourceIsMainFrame: true,
            targetIsMainFrame: nil
        ))
        XCTAssertFalse(WebPopupPolicy.allowsInitialPopupBlankNavigation(
            blank,
            sourceIsMainFrame: true,
            targetIsMainFrame: false
        ))
        XCTAssertFalse(WebPopupPolicy.allowsInitialPopupBlankNavigation(
            URL(string: "about:blank#unexpected"),
            sourceIsMainFrame: true,
            targetIsMainFrame: nil
        ))
        XCTAssertFalse(WebPopupPolicy.allowsInitialPopupBlankNavigation(
            blank,
            sourceIsMainFrame: false,
            targetIsMainFrame: nil
        ))
    }

    func testPrintBridgePolicyRequiresRegisteredPopupIdentityAndPrintRoute() throws {
        let expected = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/"))
        let printURL = try XCTUnwrap(URL(string: "http://127.0.0.1:8766/invoices/print/job123"))

        XCTAssertTrue(WebPrintPolicy.allowsPrintBridgeMessage(
            action: "print",
            pageURL: printURL,
            registeredPrintPath: "/invoices/print/job123",
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebPrintPolicy.allowsPrintBridgeMessage(
            action: "pickWatchDir",
            pageURL: printURL,
            registeredPrintPath: "/invoices/print/job123",
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebPrintPolicy.allowsPrintBridgeMessage(
            action: "print",
            pageURL: printURL,
            registeredPrintPath: "/invoices/print/another-job",
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: true
        ))
        XCTAssertFalse(WebPrintPolicy.allowsPrintBridgeMessage(
            action: "print",
            pageURL: printURL,
            registeredPrintPath: "/invoices/print/job123",
            scheme: "http",
            host: "127.0.0.1",
            port: 8766,
            expectedBaseURL: expected,
            isMainFrame: false
        ))
    }

    func testPrintBridgeScriptDoesNotExposeTheMainNativeBridge() {
        let script = WebView.printBridgeScript()

        XCTAssertTrue(script.contains("window.opener = null;"))
        XCTAssertTrue(script.contains("Object.defineProperty(window, \"opener\", {"))
        XCTAssertTrue(script.contains("value: null,"))
        XCTAssertTrue(script.contains("writable: false,"))
        XCTAssertTrue(script.contains("configurable: false"))
        XCTAssertTrue(script.contains("window.print = () =>"))
        XCTAssertTrue(script.contains("invoiceHubMacPrint"))
        XCTAssertTrue(script.contains("beforeprint"))
        XCTAssertTrue(script.contains("afterprint"))
        XCTAssertTrue(script.contains("var printInFlight = false;"))
        XCTAssertTrue(script.contains("if (printInFlight) return;"))
        XCTAssertTrue(script.contains("__invoiceHubMacFinishPrint"))
        XCTAssertTrue(script.contains("printInFlight = false;"))
        XCTAssertFalse(script.contains("pickWatchDir"))
        XCTAssertFalse(script.contains("window.invoiceHubMac ="))
    }

    func testPrintBridgeScriptSeversOpenerWithoutBreakingCreatorPopupProxy() throws {
        let context = try XCTUnwrap(JSContext())
        context.evaluateScript(
            """
            const printEvents = [];
            const printMessages = [];
            const popup = {
              opener: { invoiceHubMac: { pickWatchDir: () => "forbidden" } },
              webkit: {
                messageHandlers: {
                  invoiceHubMacPrint: {
                    postMessage: payload => printMessages.push(payload)
                  }
                }
              },
              dispatchEvent: event => printEvents.push(event.type),
              location: {
                replace: url => { popup.navigation = url; }
              }
            };
            globalThis.window = popup;
            globalThis.creatorPopupProxy = popup;
            globalThis.Event = function(type) { this.type = type; };
            """
        )
        XCTAssertNil(context.exception)

        context.evaluateScript(WebView.printBridgeScript())
        XCTAssertNil(context.exception)

        context.evaluateScript(
            "window.opener = { invoiceHubMac: { pickWatchDir: () => \"reintroduced\" } };"
        )
        XCTAssertNil(context.exception)
        XCTAssertTrue(context.evaluateScript("window.opener === null")?.toBool() ?? false)
        XCTAssertTrue(context.evaluateScript("typeof window.opener?.invoiceHubMac === 'undefined'")?.toBool() ?? false)
        XCTAssertTrue(context.evaluateScript("typeof window.invoiceHubMac === 'undefined'")?.toBool() ?? false)

        context.evaluateScript("creatorPopupProxy.location.replace('/invoices/print/job123');")
        XCTAssertEqual(
            context.evaluateScript("creatorPopupProxy.navigation")?.toString(),
            "/invoices/print/job123"
        )

        context.evaluateScript("window.print(); window.__invoiceHubMacFinishPrint();")
        XCTAssertEqual(
            context.evaluateScript("printEvents.join(',')")?.toString(),
            "beforeprint,afterprint"
        )
        XCTAssertEqual(
            context.evaluateScript("printMessages.length")?.toInt32(),
            1
        )
        XCTAssertEqual(
            context.evaluateScript("printMessages[0].action")?.toString(),
            "print"
        )
    }

    func testPrintPopupLifecycleKeepsPrintingStateAfterCloseBegins() {
        var lifecycle = PrintPopupLifecycle()

        XCTAssertTrue(lifecycle.beginPrintOperation())
        XCTAssertFalse(lifecycle.beginPrintOperation())
        lifecycle.beginClosing()
        XCTAssertTrue(lifecycle.isClosing)
        XCTAssertTrue(lifecycle.printOperationActive)
        XCTAssertFalse(lifecycle.beginPrintOperation())
        lifecycle.finishPrintOperation()
        XCTAssertFalse(lifecycle.printOperationActive)
    }

    func testPrintPopupLifecycleRejectsPrintAfterCloseBegins() {
        var lifecycle = PrintPopupLifecycle()

        lifecycle.beginClosing()
        XCTAssertFalse(lifecycle.beginPrintOperation())
        XCTAssertTrue(lifecycle.isClosing)
        XCTAssertFalse(lifecycle.printOperationActive)
    }

    func testPrintPopupRegistryRetiresClosedPopupIntoStrongQuarantine() throws {
        let quarantine = PrintPopupQuarantine<PrintPopupLifetimeProbe>()
        let owner = NSObject()
        var popup: PrintPopupLifetimeProbe? = PrintPopupLifetimeProbe()
        weak var weakPopup = popup

        do {
            let registry = PrintPopupRegistry<PrintPopupLifetimeProbe> { popup in
                quarantine.retain(popup)
            }
            let activePopup = try XCTUnwrap(popup)
            registry.register(activePopup, for: owner)
            XCTAssertEqual(registry.activeCount, 1)
            XCTAssertTrue(registry.retireActivePopup(
                matching: { $0 === activePopup },
                beforeRetire: { _ in }
            ))
            XCTAssertNil(registry.activePopup(for: owner))
            XCTAssertEqual(registry.activeCount, 0)
            XCTAssertEqual(quarantine.retainedCount, 1)
            XCTAssertFalse(registry.retireActivePopup(
                matching: { $0 === activePopup },
                beforeRetire: { _ in }
            ))
        }

        popup = nil
        let retainedPopup = try XCTUnwrap(weakPopup)
        XCTAssertTrue(quarantine.contains(retainedPopup))
    }

    func testPrintPopupRegistryRetiresCloseDuringPrintWithoutReleasingPopup() {
        let quarantine = PrintPopupQuarantine<PrintPopupLifetimeProbe>()
        let owner = NSObject()
        let popup = PrintPopupLifetimeProbe()
        var lifecycle = PrintPopupLifecycle()

        do {
            let registry = PrintPopupRegistry<PrintPopupLifetimeProbe> { popup in
                quarantine.retain(popup)
            }
            registry.register(popup, for: owner)
            XCTAssertTrue(lifecycle.beginPrintOperation())
            XCTAssertTrue(registry.retireActivePopup(
                matching: { $0 === popup },
                beforeRetire: { _ in lifecycle.beginClosing() }
            ))
            XCTAssertNil(registry.activePopup(for: owner))
            XCTAssertTrue(lifecycle.printOperationActive)
            XCTAssertEqual(quarantine.retainedCount, 1)
        }

        lifecycle.finishPrintOperation()
        XCTAssertFalse(lifecycle.printOperationActive)
        XCTAssertTrue(quarantine.contains(popup))
    }

    func testPrintPopupRegistryWindowCloseRetirementIsIdempotentAcrossDismantle() {
        let quarantine = PrintPopupQuarantine<PrintPopupLifetimeProbe>()
        let registry = PrintPopupRegistry<PrintPopupLifetimeProbe> { popup in
            quarantine.retain(popup)
        }
        let owner = NSObject()
        let popup = PrintPopupLifetimeProbe()
        var closePreparationCount = 0

        registry.register(popup, for: owner)
        XCTAssertTrue(registry.retireActivePopup(
            matching: { $0 === popup },
            beforeRetire: { _ in closePreparationCount += 1 }
        ))
        XCTAssertFalse(registry.retireActivePopup(
            matching: { $0 === popup },
            beforeRetire: { _ in closePreparationCount += 1 }
        ))
        XCTAssertNil(registry.activePopup(for: owner))
        XCTAssertEqual(closePreparationCount, 1)
        XCTAssertEqual(quarantine.retainedCount, 1)
        XCTAssertTrue(quarantine.contains(popup))
    }

    func testPrintPopupConfigurationUsesDelegateConfigurationWithRestrictedBridge() {
        let configuration = WKWebViewConfiguration()
        let inheritedController = configuration.userContentController
        let handler = PopupPrintMessageHandlerStub()

        let printController = WebPopupConfigurationPolicy.installRestrictedPrintBridge(
            on: configuration,
            messageHandler: handler
        )

        XCTAssertTrue(configuration.userContentController === printController)
        XCTAssertFalse(configuration.userContentController === inheritedController)
        XCTAssertEqual(printController.userScripts.count, 1)
        XCTAssertEqual(printController.userScripts[0].source, WebView.printBridgeScript())
        XCTAssertEqual(printController.userScripts[0].injectionTime, .atDocumentStart)
        XCTAssertTrue(printController.userScripts[0].isForMainFrameOnly)
    }

    func testBackendOwnershipOnlyAllowsOwnedLifecycleManagement() {
        XCTAssertTrue(BackendOwnership.owned.canStopOrRestart)
        XCTAssertFalse(BackendOwnership.externalCompatible.canStopOrRestart)
        XCTAssertFalse(BackendOwnership.none.canStopOrRestart)
    }

    func testBackendProcessTruthKeepsMatchingLiveOwnedHealth() {
        XCTAssertEqual(
            BackendProcessTruth.ownershipForCompatibleHealth(
                healthPID: 123,
                trackedOwnedPID: 123,
                processPID: 123,
                processIsRunning: true
            ),
            .owned
        )
        XCTAssertEqual(
            BackendProcessTruth.ownershipForCompatibleHealth(
                healthPID: 456,
                trackedOwnedPID: nil,
                processPID: nil,
                processIsRunning: false
            ),
            .externalCompatible
        )
        XCTAssertNil(
            BackendProcessTruth.ownershipForCompatibleHealth(
                healthPID: 456,
                trackedOwnedPID: 123,
                processPID: 123,
                processIsRunning: true
            )
        )
    }

    func testFreshLaunchHealthRequiresExactRunningChildIdentity() {
        XCTAssertTrue(BackendProcessTruth.healthMatchesTrackedOwnedProcess(
            healthPID: 123,
            expectedPID: 123,
            trackedOwnedPID: 123,
            processPID: 123,
            processIsRunning: true
        ))
        XCTAssertFalse(BackendProcessTruth.healthMatchesTrackedOwnedProcess(
            healthPID: 456,
            expectedPID: 123,
            trackedOwnedPID: 123,
            processPID: 123,
            processIsRunning: true
        ))
        XCTAssertFalse(BackendProcessTruth.healthMatchesTrackedOwnedProcess(
            healthPID: 123,
            expectedPID: 123,
            trackedOwnedPID: 123,
            processPID: 123,
            processIsRunning: false
        ))
        XCTAssertFalse(BackendProcessTruth.healthMatchesTrackedOwnedProcess(
            healthPID: 123,
            expectedPID: 123,
            trackedOwnedPID: 456,
            processPID: 123,
            processIsRunning: true
        ))
    }

    func testFailedLaunchCleanupTargetsOnlyTheProcessStartedByThatAttempt() {
        XCTAssertTrue(BackendProcessTruth.shouldCleanupFailedLaunch(
            attemptPID: 123,
            trackedOwnedPID: 123,
            processPID: 123
        ))
        XCTAssertFalse(BackendProcessTruth.shouldCleanupFailedLaunch(
            attemptPID: nil,
            trackedOwnedPID: 123,
            processPID: 123
        ))
        XCTAssertFalse(BackendProcessTruth.shouldCleanupFailedLaunch(
            attemptPID: 123,
            trackedOwnedPID: 456,
            processPID: 456
        ))
    }

    func testBackendProcessTruthRequiresConfirmedExit() {
        XCTAssertFalse(BackendProcessTruth.canFinalizeOwnedExit(
            expectedPID: 123,
            trackedOwnedPID: 123,
            processPID: 123,
            processIsRunning: true
        ))
        XCTAssertTrue(BackendProcessTruth.canFinalizeOwnedExit(
            expectedPID: 123,
            trackedOwnedPID: 123,
            processPID: 123,
            processIsRunning: false
        ))
        XCTAssertFalse(BackendProcessTruth.canFinalizeOwnedExit(
            expectedPID: 123,
            trackedOwnedPID: 456,
            processPID: 123,
            processIsRunning: false
        ))
    }

    func testWebBridgePublishesOwnedAndExternalManagementSnapshots() throws {
        let owned = WebView.bridgeScript(for: .owned, canInstallUpdate: true)
        let ownedWithoutCurrentIdentity = WebView.bridgeScript(for: .owned, canInstallUpdate: false)
        let external = WebView.bridgeScript(for: .externalCompatible)
        let none = WebView.bridgeScript(for: .none)

        XCTAssertTrue(owned.contains("backendOwnership: \"owned\""))
        XCTAssertTrue(owned.contains("canManageBackend: true"))
        XCTAssertTrue(owned.contains("canInstallUpdate: true"))
        XCTAssertTrue(external.contains("backendOwnership: \"externalCompatible\""))
        XCTAssertTrue(external.contains("canManageBackend: false"))
        XCTAssertTrue(external.contains("canInstallUpdate: false"))
        XCTAssertTrue(none.contains("backendOwnership: \"none\""))
        XCTAssertTrue(none.contains("canManageBackend: false"))
        XCTAssertTrue(none.contains("canInstallUpdate: false"))
        XCTAssertTrue(owned.contains("installUpdate()"))
        XCTAssertFalse(ownedWithoutCurrentIdentity.contains("installUpdate()"))
        XCTAssertFalse(external.contains("installUpdate()"))
        XCTAssertFalse(none.contains("installUpdate()"))
        for action in ["pickWatchDir", "pickOutboundDir", "pickOcrCandidateDir", "__resolve", "__reject"] {
            XCTAssertTrue(owned.contains(action))
            XCTAssertTrue(external.contains(action))
        }

        for (script, expectedInstallUpdateType) in [
            (owned, "function"),
            (ownedWithoutCurrentIdentity, "undefined"),
            (external, "undefined"),
            (none, "undefined"),
        ] {
            let context = try XCTUnwrap(JSContext())
            context.evaluateScript("var window = { webkit: { messageHandlers: { invoiceHubMac: { postMessage: function() {} } } } };")
            XCTAssertNil(context.exception)
            context.evaluateScript(script)
            XCTAssertNil(context.exception)
            XCTAssertEqual(
                context.evaluateScript("typeof window.invoiceHubMac.installUpdate")?.toString(),
                expectedInstallUpdateType
            )
        }
    }

    func testPIDFileRemovalRequiresOwnedPIDMatch() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let pidFile = root.appendingPathComponent("server.pid")
        try "123\n".write(to: pidFile, atomically: true, encoding: .utf8)

        XCTAssertFalse(BackendPIDFile.removeIfMatches(pidFile, expectedPID: 456))
        XCTAssertTrue(FileManager.default.fileExists(atPath: pidFile.path))
        XCTAssertTrue(BackendPIDFile.removeIfMatches(pidFile, expectedPID: 123))
        XCTAssertFalse(FileManager.default.fileExists(atPath: pidFile.path))
        try FileManager.default.removeItem(at: root)
    }

    func testBuildManifestAndBackendCompatibility() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let manifestURL = root.appendingPathComponent("invoice-hub-build.json")
        let manifestPayload: [String: Any] = [
            "build_id": "build-123",
            "api_contract_version": "2026-08-02-release-update-v1",
            "bookkeeping_protocol_version": "w9-ledger-review-v1",
            "capabilities": BackendCompatibilityReport.requiredCapabilities,
            "source_commit": "abc",
            "built_at": "2026-07-29T00:00:00Z"
        ]
        try JSONSerialization.data(withJSONObject: manifestPayload).write(to: manifestURL)
        let manifest = try InvoiceHubBuildManifest.load(from: root)
        let paths = BackendPaths(
            coreRoot: root,
            resourceRoot: nil,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config.json"),
            runtimeDir: root.appendingPathComponent("runtime"),
            stdoutLog: root.appendingPathComponent("stdout.log"),
            stderrLog: root.appendingPathComponent("stderr.log"),
            serverPID: root.appendingPathComponent("server.pid")
        )
        let matchingPayload: [String: Any] = [
            "ok": true,
            "pid": 10,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": "build-123",
            "api_contract_version": "2026-08-02-release-update-v1",
            "bookkeeping_protocol_version": "w9-ledger-review-v1",
            "capabilities": BackendCompatibilityReport.requiredCapabilities,
            "build_manifest_present": true
        ]
        let matching = BackendHealth(payload: matchingPayload)
        let oldBackend = BackendHealth(payload: ["ok": true])

        XCTAssertTrue(BackendCompatibilityReport.evaluate(health: matching, manifest: manifest, paths: paths).isCompatible)
        for invalidPID in [0, -1] {
            var invalidPIDPayload = matchingPayload
            invalidPIDPayload["pid"] = invalidPID
            let invalidPIDReport = BackendCompatibilityReport.evaluate(
                health: BackendHealth(payload: invalidPIDPayload),
                manifest: manifest,
                paths: paths
            )
            XCTAssertFalse(invalidPIDReport.isCompatible)
            XCTAssertTrue(invalidPIDReport.issues.contains { $0.contains("后端 PID 缺失或无效") })
        }
        let mismatch = BackendCompatibilityReport.evaluate(health: oldBackend, manifest: manifest, paths: paths)
        XCTAssertFalse(mismatch.isCompatible)
        XCTAssertTrue(mismatch.issues.contains { $0.contains("build_id") })
        XCTAssertTrue(mismatch.issues.contains { $0.contains("做账协议") })
        XCTAssertTrue(mismatch.issues.contains { $0.contains("缺少能力") })

        let legacyManifest = InvoiceHubBuildManifest(
            buildID: manifest.buildID,
            apiContractVersion: manifest.apiContractVersion,
            bookkeepingProtocolVersion: "w8-legacy",
            capabilities: manifest.capabilities,
            sourceCommit: manifest.sourceCommit,
            builtAt: manifest.builtAt
        )
        let legacyHealth = BackendHealth(payload: [
            "ok": true,
            "pid": 10,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": "build-123",
            "api_contract_version": "2026-08-02-release-update-v1",
            "bookkeeping_protocol_version": "w8-legacy",
            "capabilities": BackendCompatibilityReport.requiredCapabilities,
            "build_manifest_present": true
        ])
        let legacyReport = BackendCompatibilityReport.evaluate(health: legacyHealth, manifest: legacyManifest, paths: paths)
        XCTAssertFalse(legacyReport.isCompatible)
        XCTAssertTrue(legacyReport.issues.contains { $0.contains("构建清单做账协议不受支持") })
        XCTAssertTrue(legacyReport.issues.contains { $0.contains("后端做账协议不受支持") })

        let capabilityDrift = BackendHealth(payload: [
            "ok": true,
            "pid": 10,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": "build-123",
            "api_contract_version": "2026-08-02-release-update-v1",
            "bookkeeping_protocol_version": "w9-ledger-review-v1",
            "capabilities": BackendCompatibilityReport.requiredCapabilities + ["unexpected.extra"],
            "build_manifest_present": true
        ])
        let driftReport = BackendCompatibilityReport.evaluate(health: capabilityDrift, manifest: manifest, paths: paths)
        XCTAssertFalse(driftReport.isCompatible)
        XCTAssertTrue(driftReport.issues.contains("构建清单与后端能力集合不匹配"))

        var missingManifestFlagPayload = manifestPayload
        missingManifestFlagPayload["ok"] = true
        missingManifestFlagPayload["pid"] = 10
        missingManifestFlagPayload["config_path"] = paths.configPath.path
        missingManifestFlagPayload["runtime_dir"] = paths.runtimeDir.path
        let missingManifestFlag = BackendHealth(payload: missingManifestFlagPayload)
        let missingManifestReport = BackendCompatibilityReport.evaluate(health: missingManifestFlag, manifest: manifest, paths: paths)
        XCTAssertFalse(missingManifestReport.isCompatible)
        XCTAssertTrue(missingManifestReport.issues.contains { $0.contains("build_manifest_present") })
        try FileManager.default.removeItem(at: root)
    }

    func testStrictPackageManifestAndHealthIdentity() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let buildID = String(repeating: "a", count: 64)
        let sourceCommit = String(repeating: "b", count: 40)
        let packagePayload: [String: Any] = [
            "schema_version": 1,
            "package_id": "com.invoicehub.macos.arm64.dmg",
            "product_version": "0.3.0-alpha.1",
            "platform": "macos",
            "architecture": "arm64",
            "package_type": "dmg",
            "python_version": "3.14.6",
            "dependency_lock_sha256": String(repeating: "c", count: 64),
            "update_channel": "beta",
            "update_feed_url": "https://lyc1126.github.io/InvoiceHub/updates/alpha/latest.json",
            "allowed_update_hosts": [
                "github.com",
                "lyc1126.github.io",
                "objects.githubusercontent.com",
                "release-assets.githubusercontent.com"
            ],
            "core_build_id": buildID,
            "source_commit": sourceCommit
        ]
        try JSONSerialization.data(withJSONObject: packagePayload).write(
            to: root.appendingPathComponent("invoice-hub-package.json")
        )
        let package = try InvoiceHubPackageManifest.load(from: root, releaseMode: true)
        let manifest = InvoiceHubBuildManifest(
            buildID: buildID,
            apiContractVersion: BackendCompatibilityReport.requiredAPIContractVersion,
            bookkeepingProtocolVersion: BackendCompatibilityReport.requiredBookkeepingProtocolVersion,
            capabilities: BackendCompatibilityReport.requiredCapabilities,
            sourceCommit: sourceCommit,
            builtAt: "2026-08-02T00:00:00Z"
        )
        let paths = BackendPaths(
            coreRoot: root,
            resourceRoot: nil,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config/app.local.json"),
            runtimeDir: root.appendingPathComponent("runtime"),
            stdoutLog: root.appendingPathComponent("runtime/stdout.log"),
            stderrLog: root.appendingPathComponent("runtime/stderr.log"),
            serverPID: root.appendingPathComponent("runtime/server.pid")
        )
        var healthPayload: [String: Any] = [
            "ok": true,
            "pid": 123,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": buildID,
            "api_contract_version": manifest.apiContractVersion,
            "bookkeeping_protocol_version": manifest.bookkeepingProtocolVersion,
            "capabilities": manifest.capabilities,
            "build_manifest_present": true,
            "build_manifest_valid": true,
            "product_version": package.productVersion,
            "package_id": package.packageID,
            "platform": package.platform,
            "architecture": package.architecture,
            "package_type": package.packageType,
            "package_manifest_present": true,
            "package_manifest_valid": true
        ]
        XCTAssertTrue(
            BackendCompatibilityReport.evaluate(
                health: BackendHealth(payload: healthPayload),
                manifest: manifest,
                packageManifest: package,
                paths: paths
            ).isCompatible
        )
        var sourceDriftPayload = packagePayload
        sourceDriftPayload["source_commit"] = String(repeating: "c", count: 40)
        try JSONSerialization.data(withJSONObject: sourceDriftPayload).write(
            to: root.appendingPathComponent("invoice-hub-package.json")
        )
        let sourceDriftPackage = try InvoiceHubPackageManifest.load(from: root, releaseMode: true)
        let sourceDrift = BackendCompatibilityReport.evaluate(
            health: BackendHealth(payload: healthPayload),
            manifest: manifest,
            packageManifest: sourceDriftPackage,
            paths: paths
        )
        XCTAssertFalse(sourceDrift.isCompatible)
        XCTAssertTrue(sourceDrift.issues.contains { $0.contains("source_commit") })
        healthPayload["package_id"] = "unexpected.package"
        let mismatch = BackendCompatibilityReport.evaluate(
            health: BackendHealth(payload: healthPayload),
            manifest: manifest,
            packageManifest: package,
            paths: paths
        )
        XCTAssertFalse(mismatch.isCompatible)
        XCTAssertTrue(mismatch.issues.contains { $0.contains("package_id") })
        try FileManager.default.removeItem(at: root)
    }

    func testMatchingManifestAndHealthExtrasStillFailClientCapabilityContract() {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let paths = BackendPaths(
            coreRoot: root,
            resourceRoot: nil,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config.json"),
            runtimeDir: root.appendingPathComponent("runtime"),
            stdoutLog: root.appendingPathComponent("stdout.log"),
            stderrLog: root.appendingPathComponent("stderr.log"),
            serverPID: root.appendingPathComponent("server.pid")
        )
        let capabilities = BackendCompatibilityReport.requiredCapabilities + ["unexpected.extra"]
        let manifest = InvoiceHubBuildManifest(
            buildID: "build-123",
            apiContractVersion: "2026-08-02-release-update-v1",
            bookkeepingProtocolVersion: "w9-ledger-review-v1",
            capabilities: capabilities,
            sourceCommit: "abc",
            builtAt: "2026-07-29T00:00:00Z"
        )
        let health = BackendHealth(payload: [
            "ok": true,
            "pid": 10,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": manifest.buildID,
            "api_contract_version": manifest.apiContractVersion,
            "bookkeeping_protocol_version": manifest.bookkeepingProtocolVersion,
            "capabilities": capabilities,
            "build_manifest_present": true
        ])

        let report = BackendCompatibilityReport.evaluate(health: health, manifest: manifest, paths: paths)

        XCTAssertFalse(report.isCompatible)
        XCTAssertTrue(report.issues.contains("构建清单能力集合与客户端要求不匹配"))
        XCTAssertTrue(report.issues.contains("后端能力集合与客户端要求不匹配"))
        XCTAssertFalse(report.issues.contains("构建清单与后端能力集合不匹配"))
    }

    func testMatchingLegacyAPIContractsStillFailClientContract() {
        XCTAssertEqual(
            BackendCompatibilityReport.requiredAPIContractVersion,
            "2026-08-02-release-update-v1"
        )
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let paths = BackendPaths(
            coreRoot: root,
            resourceRoot: nil,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config.json"),
            runtimeDir: root.appendingPathComponent("runtime"),
            stdoutLog: root.appendingPathComponent("stdout.log"),
            stderrLog: root.appendingPathComponent("stderr.log"),
            serverPID: root.appendingPathComponent("server.pid")
        )
        let manifest = InvoiceHubBuildManifest(
            buildID: "build-123",
            apiContractVersion: "legacy-but-matching",
            bookkeepingProtocolVersion: BackendCompatibilityReport.requiredBookkeepingProtocolVersion,
            capabilities: BackendCompatibilityReport.requiredCapabilities,
            sourceCommit: "abc",
            builtAt: "2026-07-29T00:00:00Z"
        )
        let health = BackendHealth(payload: [
            "ok": true,
            "pid": 10,
            "config_path": paths.configPath.path,
            "runtime_dir": paths.runtimeDir.path,
            "build_id": manifest.buildID,
            "api_contract_version": manifest.apiContractVersion,
            "bookkeeping_protocol_version": manifest.bookkeepingProtocolVersion,
            "capabilities": manifest.capabilities,
            "build_manifest_present": true
        ])

        let report = BackendCompatibilityReport.evaluate(health: health, manifest: manifest, paths: paths)

        XCTAssertFalse(report.isCompatible)
        XCTAssertTrue(report.issues.contains { $0.contains("构建清单 API 契约不受支持") })
        XCTAssertTrue(report.issues.contains { $0.contains("后端 API 契约不受支持") })
        XCTAssertFalse(report.issues.contains { $0.contains("API 契约不匹配") })
    }

    func testBuildManifestWithoutBookkeepingProtocolFailsClosed() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "build_id": "legacy",
            "api_contract_version": "legacy",
            "capabilities": BackendCompatibilityReport.requiredCapabilities,
            "source_commit": "abc",
            "built_at": "2026-07-17T00:00:00Z"
        ]
        try JSONSerialization.data(withJSONObject: payload).write(
            to: root.appendingPathComponent("invoice-hub-build.json"),
            options: .atomic
        )

        XCTAssertThrowsError(try InvoiceHubBuildManifest.load(from: root)) { error in
            XCTAssertEqual(error as? BuildManifestError, .invalid(root.appendingPathComponent("invoice-hub-build.json").path))
        }
        try FileManager.default.removeItem(at: root)
    }

    func testBuildManifestWithoutCapabilitiesFailsClosed() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try """
        {"build_id":"legacy","api_contract_version":"legacy","bookkeeping_protocol_version":"w9-ledger-review-v1","source_commit":"abc","built_at":"2026-07-17T00:00:00Z"}
        """.write(
            to: root.appendingPathComponent("invoice-hub-build.json"),
            atomically: true,
            encoding: .utf8
        )

        XCTAssertThrowsError(try InvoiceHubBuildManifest.load(from: root)) { error in
            XCTAssertEqual(error as? BuildManifestError, .invalid(root.appendingPathComponent("invoice-hub-build.json").path))
        }
        try FileManager.default.removeItem(at: root)
    }

    func testShutdownClientPostsFixedKeepMonitorChoice() async throws {
        func bodyData(from request: URLRequest) -> Data? {
            if let body = request.httpBody {
                return body
            }
            guard let stream = request.httpBodyStream else { return nil }
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while true {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                data.append(buffer, count: count)
            }
            return data
        }

        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [InvoiceHubURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        var capturedRequest: URLRequest?
        var capturedPayload: [String: Any]?
        InvoiceHubURLProtocolStub.handler = { request in
            capturedRequest = request
            if let body = bodyData(from: request) {
                capturedPayload = try JSONSerialization.jsonObject(with: body) as? [String: Any]
            }
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            let data = try JSONSerialization.data(withJSONObject: [
                "ok": true,
                "scheduled": true,
                "idempotent": false,
                "shutdown_behavior": "keep_monitor",
                "message": "scheduled"
            ])
            return (response, data)
        }
        defer { InvoiceHubURLProtocolStub.handler = nil }

        let client = InvoiceHubAPIClient(baseURL: URL(string: "http://127.0.0.1:8766/")!, session: session)
        let result = try await client.shutdownKeepingMonitor()

        XCTAssertTrue(result.accepted)
        XCTAssertEqual(capturedRequest?.httpMethod, "POST")
        XCTAssertEqual(capturedRequest?.url?.path, "/api/v1/server/shutdown")
        let payload = try XCTUnwrap(capturedPayload)
        XCTAssertEqual(payload.count, 2)
        XCTAssertEqual(payload["shutdown_behavior"] as? String, "keep_monitor")
        XCTAssertEqual(payload["remember"] as? Bool, false)
    }

    func testHandshakeSessionsAndRequestsUseHardDeadlines() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [InvoiceHubURLProtocolStub.self]
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 120
        let session = URLSession(configuration: configuration)
        var handshakeConfigurations: [URLSessionConfiguration] = []
        var requestedTimeouts: [(String, TimeInterval)] = []
        InvoiceHubURLProtocolStub.handler = { request in
            let url = try XCTUnwrap(request.url)
            requestedTimeouts.append((url.path, request.timeoutInterval))
            let response = HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": url.path == "/openapi.json" ? "application/json" : "text/html"]
            )!
            if url.path == "/api/v1/health" {
                return (response, try JSONSerialization.data(withJSONObject: ["ok": true]))
            }
            if url.path == "/openapi.json" {
                let paths = Dictionary(uniqueKeysWithValues: InvoiceHubAPIClient.requiredAPIOperations.map {
                    ($0.path, [$0.method: [:] as [String: Any]])
                })
                return (response, try JSONSerialization.data(withJSONObject: ["paths": paths]))
            }
            return (response, Data("ok".utf8))
        }
        defer { InvoiceHubURLProtocolStub.handler = nil }

        let client = InvoiceHubAPIClient(
            baseURL: URL(string: "http://127.0.0.1:8766/")!,
            session: session,
            sessionFactory: { boundedConfiguration in
                handshakeConfigurations.append(boundedConfiguration)
                return URLSession(configuration: boundedConfiguration)
            }
        )

        let health = await client.health()
        XCTAssertTrue(health?.ok == true)
        try await client.verifyRequiredRoutes()

        XCTAssertEqual(handshakeConfigurations.count, 2)
        XCTAssertEqual(handshakeConfigurations[0].timeoutIntervalForRequest, 1, accuracy: 0.001)
        XCTAssertEqual(handshakeConfigurations[0].timeoutIntervalForResource, 1, accuracy: 0.001)
        XCTAssertEqual(handshakeConfigurations[1].timeoutIntervalForRequest, 5, accuracy: 0.001)
        XCTAssertEqual(handshakeConfigurations[1].timeoutIntervalForResource, 5, accuracy: 0.001)
        XCTAssertEqual(
            requestedTimeouts.map { $0.0 },
            ["/api/v1/health"] + InvoiceHubAPIClient.requiredPagePaths + ["/openapi.json"]
        )
        for (path, timeout) in requestedTimeouts {
            XCTAssertEqual(timeout, path == "/api/v1/health" ? 1 : 5, accuracy: 0.001, path)
        }
    }

    func testStrictRouteVerificationUsesOpenAPIWithoutLoadingBusinessData() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [InvoiceHubURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        var requestedPaths: [String] = []
        InvoiceHubURLProtocolStub.handler = { request in
            let url = try XCTUnwrap(request.url)
            requestedPaths.append(url.path)
            let response = HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": url.path == "/openapi.json" ? "application/json" : "text/html"]
            )!
            if url.path == "/openapi.json" {
                let paths = Dictionary(uniqueKeysWithValues: InvoiceHubAPIClient.requiredAPIOperations.map {
                    ($0.path, [$0.method: [:] as [String: Any]])
                })
                return (response, try JSONSerialization.data(withJSONObject: ["paths": paths]))
            }
            return (response, Data("ok".utf8))
        }
        defer { InvoiceHubURLProtocolStub.handler = nil }

        let client = InvoiceHubAPIClient(baseURL: URL(string: "http://127.0.0.1:8766/")!, session: session)
        try await client.verifyRequiredRoutes()

        XCTAssertEqual(requestedPaths, InvoiceHubAPIClient.requiredPagePaths + ["/openapi.json"])
        XCTAssertFalse(requestedPaths.contains("/api/v1/documents/state"))
        XCTAssertFalse(requestedPaths.contains("/api/v1/bookkeeping/state"))
    }

    func testStrictRouteVerificationFailsWhenOpenAPIRouteIsMissing() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [InvoiceHubURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        InvoiceHubURLProtocolStub.handler = { request in
            let url = try XCTUnwrap(request.url)
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
            if url.path == "/openapi.json" {
                return (response, try JSONSerialization.data(withJSONObject: ["paths": [:]]))
            }
            return (response, Data("ok".utf8))
        }
        defer { InvoiceHubURLProtocolStub.handler = nil }

        let client = InvoiceHubAPIClient(baseURL: URL(string: "http://127.0.0.1:8766/")!, session: session)
        do {
            try await client.verifyRequiredRoutes()
            XCTFail("expected missing route verification to fail")
        } catch let error as InvoiceHubAPIError {
            guard case .missingRequiredRoutes(let paths) = error else {
                return XCTFail("unexpected API error: \(error)")
            }
            XCTAssertEqual(paths, InvoiceHubAPIClient.requiredAPIOperations.map(\.displayName))
        }
    }

    func testStrictRouteVerificationFailsWhenOpenAPIMethodIsMissing() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [InvoiceHubURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let required = try XCTUnwrap(InvoiceHubAPIClient.requiredAPIOperations.first { $0.path == "/api/v1/invoices/print-jobs" })
        InvoiceHubURLProtocolStub.handler = { request in
            let url = try XCTUnwrap(request.url)
            let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!
            if url.path == "/openapi.json" {
                var paths = Dictionary(uniqueKeysWithValues: InvoiceHubAPIClient.requiredAPIOperations.map {
                    ($0.path, [$0.method: [:] as [String: Any]])
                })
                paths[required.path] = ["get": [:] as [String: Any]]
                return (response, try JSONSerialization.data(withJSONObject: ["paths": paths]))
            }
            return (response, Data("ok".utf8))
        }
        defer { InvoiceHubURLProtocolStub.handler = nil }

        let client = InvoiceHubAPIClient(baseURL: URL(string: "http://127.0.0.1:8766/")!, session: session)
        do {
            try await client.verifyRequiredRoutes()
            XCTFail("expected missing OpenAPI operation verification to fail")
        } catch let error as InvoiceHubAPIError {
            guard case .missingRequiredRoutes(let operations) = error else {
                return XCTFail("unexpected API error: \(error)")
            }
            XCTAssertEqual(operations, [required.displayName])
        }
    }

    func testMissingBuildManifestFailsClosed() {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        XCTAssertThrowsError(try InvoiceHubBuildManifest.load(from: root)) { error in
            XCTAssertEqual(error as? BuildManifestError, .missing(root.appendingPathComponent("invoice-hub-build.json").path))
        }
    }

    func testConfiguredPythonPathMustBeExecutable() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let resources = root.appendingPathComponent("Resources", isDirectory: true)
        let core = root.appendingPathComponent("core", isDirectory: true)
        let invalidPython = root.appendingPathComponent("missing-python")
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: core, withIntermediateDirectories: true)
        try invalidPython.path.write(
            to: resources.appendingPathComponent("dev-python-path.txt"),
            atomically: true,
            encoding: .utf8
        )

        let paths = BackendPaths(
            coreRoot: core,
            resourceRoot: resources,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config/app.local.json"),
            runtimeDir: root.appendingPathComponent("runtime", isDirectory: true),
            stdoutLog: root.appendingPathComponent("runtime/server_stdout.log"),
            stderrLog: root.appendingPathComponent("runtime/server_stderr.log"),
            serverPID: root.appendingPathComponent("runtime/server.pid")
        )

        XCTAssertThrowsError(try PythonCommandResolver.resolve(paths: paths)) { error in
            XCTAssertEqual(error as? PythonCommandError, .configuredPythonNotExecutable(invalidPython.path))
        }
        try FileManager.default.removeItem(at: root)
    }

    func testReleasePythonResolverRejectsDevelopmentMarkerAndSystemFallback() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let resources = root.appendingPathComponent("Resources", isDirectory: true)
        let core = root.appendingPathComponent("core", isDirectory: true)
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: core, withIntermediateDirectories: true)
        let marker = resources.appendingPathComponent("dev-python-path.txt")
        try "/usr/bin/python3\n".write(to: marker, atomically: true, encoding: .utf8)
        let paths = BackendPaths(
            coreRoot: core,
            resourceRoot: resources,
            appSupportRoot: root,
            configPath: root.appendingPathComponent("config/app.local.json"),
            runtimeDir: root.appendingPathComponent("runtime"),
            stdoutLog: root.appendingPathComponent("runtime/stdout.log"),
            stderrLog: root.appendingPathComponent("runtime/stderr.log"),
            serverPID: root.appendingPathComponent("runtime/server.pid")
        )
        XCTAssertThrowsError(try PythonCommandResolver.resolve(paths: paths, releaseMode: true)) { error in
            XCTAssertEqual(error as? PythonCommandError, .developmentMarkerInRelease(marker.path))
        }
        try FileManager.default.removeItem(at: marker)
        let expected = resources.appendingPathComponent("python/bin/python3")
        XCTAssertThrowsError(try PythonCommandResolver.resolve(paths: paths, releaseMode: true)) { error in
            XCTAssertEqual(error as? PythonCommandError, .bundledPythonMissing(expected.path))
        }
        try FileManager.default.removeItem(at: root)
    }
}
