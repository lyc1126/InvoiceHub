import SwiftUI

public struct InvoiceHubCommands: Commands {
    @ObservedObject private var backend: LocalBackendController

    public init(backend: LocalBackendController) {
        self.backend = backend
    }

    public var body: some Commands {
        CommandMenu("本地服务") {
            Button("启动或连接服务") {
                Task { await backend.start() }
            }
            .keyboardShortcut("r", modifiers: [.command, .shift])

            Button("重启页面服务") {
                Task { await backend.restart() }
            }
            .disabled(!backend.canStopOrRestart)

            Button("停止页面服务") {
                Task { await backend.stopLocalhost() }
            }
            .disabled(!backend.canStopOrRestart)

            Divider()

            Button("重新汇总") {
                Task { await backend.rebuild() }
            }

            Divider()

            Button("启动监控") {
                Task { await backend.startMonitor() }
            }
            .disabled(!backend.canStopOrRestart)

            Button("停止监控") {
                Task { await backend.stopMonitor() }
            }
            .disabled(!backend.canStopOrRestart)

            Divider()

            Button("在浏览器打开") {
                backend.openInBrowser()
            }

            Button("显示桌面窗口") {
                backend.showDesktopWindow()
            }

            Button("打开运行日志") {
                backend.openLogs()
            }

            Button("打开诊断页") {
                backend.openDiagnostics()
            }
        }
    }
}
