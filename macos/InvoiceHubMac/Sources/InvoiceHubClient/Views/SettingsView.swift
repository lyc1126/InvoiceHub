import SwiftUI

public struct SettingsView: View {
    @EnvironmentObject private var backend: LocalBackendController

    public init() {}

    public var body: some View {
        Form {
            Section("本地后端") {
                LabeledContent("地址") {
                    Text(backend.baseURL?.absoluteString ?? "尚未启动")
                        .textSelection(.enabled)
                }
                LabeledContent("构建 ID") {
                    Text(backend.buildManifest?.buildID ?? "尚未读取")
                        .textSelection(.enabled)
                }
                LabeledContent("API 契约") {
                    Text(backend.buildManifest?.apiContractVersion ?? "尚未读取")
                        .textSelection(.enabled)
                }
                LabeledContent("服务所有权") {
                    Text(backend.ownership.title)
                }
                Text(backend.serviceManagementHint)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                LabeledContent("配置") {
                    Text(backend.paths?.configPath.path ?? "尚未生成")
                        .textSelection(.enabled)
                }
                LabeledContent("运行状态") {
                    Text(backend.paths?.runtimeDir.path ?? "尚未生成")
                        .textSelection(.enabled)
                }
                LabeledContent("核心资源") {
                    Text(backend.paths?.coreRoot.path ?? "尚未解析")
                        .textSelection(.enabled)
                }
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 620)
    }
}
