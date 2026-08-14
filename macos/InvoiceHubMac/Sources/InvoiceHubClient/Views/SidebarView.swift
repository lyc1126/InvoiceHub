import SwiftUI

public struct SidebarView: View {
    @EnvironmentObject private var backend: LocalBackendController
    @Binding private var selection: AppRoute

    public init(selection: Binding<AppRoute>) {
        _selection = selection
    }

    public var body: some View {
        List(selection: $selection) {
            Section("InvoiceHub") {
                ForEach(AppRoute.userNavigationRoutes) { route in
                    Label(route.title, systemImage: route.systemImage)
                        .tag(route)
                }
            }

            Section("本地服务") {
                StatusRow(status: backend.status)
                Button("启动监控") {
                    Task { await backend.startMonitor() }
                }
                .disabled(!backend.canStopOrRestart)
                .help(backend.serviceManagementHint)
                Button("停止监控") {
                    Task { await backend.stopMonitor() }
                }
                .disabled(!backend.canStopOrRestart)
                .help(backend.serviceManagementHint)
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("InvoiceHub")
    }
}

private struct StatusRow: View {
    let status: BackendStatus

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundStyle(color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body)
                Text(status.message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 4)
    }

    private var title: String {
        switch status.phase {
        case .idle:
            return "待启动"
        case .starting:
            return "启动中"
        case .running:
            return "已连接"
        case .stopping:
            return "停止中"
        case .stopped:
            return "已停止"
        case .failed:
            return "需要处理"
        }
    }

    private var icon: String {
        switch status.phase {
        case .running:
            return "checkmark.circle.fill"
        case .failed:
            return "exclamationmark.triangle.fill"
        case .starting, .stopping:
            return "clock.fill"
        default:
            return "circle"
        }
    }

    private var color: Color {
        switch status.phase {
        case .running:
            return .green
        case .failed:
            return .orange
        case .starting, .stopping:
            return .blue
        default:
            return .secondary
        }
    }
}
