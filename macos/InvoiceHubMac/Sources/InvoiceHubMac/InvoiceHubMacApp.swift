import AppKit
import SwiftUI
import InvoiceHubClient

@main
@MainActor
struct InvoiceHubMacApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var backend = LocalBackendController()

    var body: some Scene {
        WindowGroup("InvoiceHub", id: "main") {
            ContentView()
                .environmentObject(backend)
                .frame(minWidth: 1080, minHeight: 720)
                .task {
                    appDelegate.bindBackend(backend)
                    await backend.start()
                }
        }
        .commands {
            InvoiceHubCommands(backend: backend)
        }

        Settings {
            SettingsView()
                .environmentObject(backend)
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    var backend: LocalBackendController?
    private var startupSurfaceObserver: NSObjectProtocol?
    private var showDesktopObserver: NSObjectProtocol?

    func bindBackend(_ backend: LocalBackendController) {
        self.backend = backend
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        ProcessInfo.processInfo.disableAutomaticTermination("InvoiceHubMac keeps the local backend available while the app is running.")
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        startupSurfaceObserver = NotificationCenter.default.addObserver(
            forName: .invoiceHubStartupSurfaceChanged,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            Task { @MainActor [weak self] in
                let surface = StartupSurface.normalized(notification.userInfo?["surface"])
                if surface == .browser {
                    self?.hideMainWindow()
                } else {
                    self?.showMainWindow()
                }
            }
        }
        showDesktopObserver = NotificationCenter.default.addObserver(
            forName: .invoiceHubShowDesktopWindow,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.showMainWindow()
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let startupSurfaceObserver { NotificationCenter.default.removeObserver(startupSurfaceObserver) }
        if let showDesktopObserver { NotificationCenter.default.removeObserver(showDesktopObserver) }
        backend?.terminateOwnedBackendForAppQuit()
    }

    private func hideMainWindow() {
        NSApp.windows.first(where: { $0.title == "InvoiceHub" })?.orderOut(nil)
    }

    private func showMainWindow() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        NSApp.windows.first(where: { $0.title == "InvoiceHub" })?.makeKeyAndOrderFront(nil)
    }
}
