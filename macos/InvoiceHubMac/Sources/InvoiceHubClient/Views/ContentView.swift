import SwiftUI

public struct ContentView: View {
    @EnvironmentObject private var backend: LocalBackendController
    @SceneStorage("selectedRoute") private var selectedRouteRaw = AppRoute.home.rawValue

    public init() {}

    public var body: some View {
        NavigationSplitView {
            SidebarView(selection: selection)
        } detail: {
            WebContentView(route: selectedRoute)
                .environmentObject(backend)
        }
        .toolbar {
            ToolbarItemGroup {
                Button {
                    Task { await backend.rebuild() }
                } label: {
                    Label("重新汇总", systemImage: "arrow.triangle.2.circlepath")
                }
                Button {
                    Task { await backend.restart() }
                } label: {
                    Label("重启服务", systemImage: "arrow.clockwise")
                }
                .disabled(!backend.canStopOrRestart)
                .help(backend.serviceManagementHint)
                Button {
                    backend.openLogs()
                } label: {
                    Label("日志", systemImage: "doc.text")
                }
            }
        }
    }

    private var selectedRoute: AppRoute {
        get { AppRoute(rawValue: selectedRouteRaw) ?? .home }
        nonmutating set { selectedRouteRaw = newValue.rawValue }
    }

    private var selection: Binding<AppRoute> {
        Binding(
            get: { selectedRoute },
            set: { selectedRoute = $0 }
        )
    }
}
