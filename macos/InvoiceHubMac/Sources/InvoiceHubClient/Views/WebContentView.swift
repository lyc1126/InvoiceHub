import SwiftUI

public struct WebContentView: View {
    @EnvironmentObject private var backend: LocalBackendController
    let route: AppRoute

    public init(route: AppRoute) {
        self.route = route
    }

    public var body: some View {
        Group {
            if let url = backend.url(for: route), backend.status.phase.isRunning {
                WebView(url: url, backend: backend)
                    .id("\(url.absoluteString)#\(backend.webRefreshToken)")
            } else {
                VStack(spacing: 14) {
                    ProgressView()
                        .controlSize(.large)
                    Text(backend.status.message)
                        .font(.headline)
                    if case .failed(let reason) = backend.status.phase {
                        Text(reason)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .textSelection(.enabled)
                    }
                    HStack {
                        Button("重试启动") {
                            Task { await backend.start() }
                        }
                        Button("打开日志") {
                            backend.openLogs()
                        }
                    }
                }
                .padding(32)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(route.title)
    }
}
