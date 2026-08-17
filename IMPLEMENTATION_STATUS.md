# IMPLEMENTATION_STATUS

更新时间：2026-08-17

## 公开基线

- 本仓库已将单一、脱敏的根提交发布为公开 `main`。旧的私有提交图、验证记录、二进制包和 Tag 只保留在 owner-only 私有归档中，不属于公开历史，也不会作为 Release 资产上传。
- 首个公开开发版本为 `0.3.0-alpha.1`；`codex/tauri2-unified-desktop` 已从公开 `main` 建立。任何公开二进制都必须从脱敏图上的新版本、新 Tag 和新发布证据构建。
- 历史净化的范围、私有备份和已完成的公开门槛见 [执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。公开仓库已启用 DCO、Dependabot、Secret Scanning、Push Protection 和私密漏洞报告；仍未创建 Release 或更新 Feed。

## 保留的产品边界

- 产品仍是 `v1 localhost`：单一活动 `TargetProfile`、文件为业务真值，SQLite 只保存任务、事件、设置与缓存。
- 共享核心继续使用 Python、FastAPI、Web、CSV/XLSX/JSON 投影和独立 monitor；不为桌面壳重写发票、成本、单据或做账逻辑。
- Windows 与 macOS 源码同仓，但成品必须严格按平台隔离。用户配置、日志、运行态和业务文件均不进入源码或发布输入。

## 已实现的共享能力

- PDF/OFD/XML 票头与成本明细提取、金额合法性保护、两维分类、同票纠偏、普通汇总与成本投影。
- 独立 monitor、后台 startup sync、文件事件合并、周期兜底、手改三字段保护和可诊断日志。
- FastAPI 页面/API、目录草稿、监控控制、结构化关闭、源文件预览、批量打印、皮肤安全边界和真实表格/TSV 复制。
- 做账 W8/W9 的本地文件真值、状态迁移预览、服务端执行校验、批次 manifest 与只读 dry-run 边界。
- macOS SwiftUI/WKWebView 壳保留为现有平台参考；它不改变共享业务逻辑，也不构成未来 Tauri 发布证据。

## `v0.3` 目标

- 使用 Tauri 2 负责窗口、托盘、单实例、原生面板、打印、后端生命周期、受限 Host RPC 和 updater。
- 固定 localhost 为 `127.0.0.1:8766`；未知占用明确失败，不能换端口或接入未知旧进程。
- 首版目标是 Windows 10/11 x64 NSIS 与 macOS 13+ arm64 DMG/更新归档。Intel Mac、Windows ARM64、MSI、App Store、云端和增量更新不在首版范围。
- 更新签名验证、下载、安装前 monitor 停止与重启仍是未来 host recovery/relaunch coordinator 的责任；当前 `update_install` 故意清除候选并返回不可用，不会下载、停止 monitor、安装或重启。

## Tauri 2 生命周期边界与开发 `.app`

- `src-tauri/` 已提供固定 `127.0.0.1:8766` 的后端生命周期代码：未知占用失败、host 启动的 child PID/manifest/identity/OpenAPI 方法严格握手、单实例恢复窗口，以及仅在成功后创建 WebView。初次握手后严格读取 `startup_surface`，再以新的 HMAC challenge 和 identity probe 复核归属才 arm 授权：`desktop` 创建 WebView，`browser` 只由 host-only opener 打开固定 origin；托盘和第二实例重新打开既定 surface，desktop 关闭只隐藏窗口且不停止 monitor。裸源码 checkout 仍因没有经编译绑定的 manifest 以状态 `78` fail-closed；`scripts/dev/tauri_dev_app.py` 只为开发 profile 生成 schema-3 staged manifest、允许清单内 core 与显式 venv launcher，并将 manifest/launcher SHA-256 绑定进本地 arm64 host。它不产生 release manifest、DMG、NSIS 或正式发布输入。
- 归属证明使用后端独有的 256 位 secret、宿主每次新建 challenge 和 HMAC-SHA256 响应；secret 不发送给端口监听者。Host RPC token 只由 host 传给其直接启动的 Python backend，backend 启动时捕获并从 descendant 环境清除，绝不进入 WebView、Tauri command/event、API 响应或日志。私有随机 loopback listener 的 picker 面仅保留四种原生选择器枚举，更新命令面独立地仅为 `update_check/update_install`，WebView 没有 IPC 权限；host candidate 最多保留 300 秒，由 listener loop 主动清除，当前 install 请求会立即清除候选并返回脱敏不可用，直到完整 recovery/relaunch coordinator 出现。同一进程同时具备 Tauri marker 与 configured private RPC 时，API、设置页和后台 timer 均通过 `check_for_updates` 进入 strict host preflight；只有非 Tauri/非 host 检查不获取 `_host_update_lock` 并保留 `UpdateService` 的 cache/ETag/nonblocking-busy 语义。host 检查锁竞争返回不持久化 busy 且不触发 metadata/candidate、不会清除既有 approval；install 锁竞争立即抛脱敏错误，不消费 approval 或发送第二次 RPC。host approval 必须来自同一 session 内显式携带 `Cache-Control: no-cache`、不带 ETag 的 fresh `200` body，缓存、ETag、`304`、离线或错误不授予 approval，随后才要求版本完全一致。安装接口只接受 `{}`，错误固定为脱敏 `503 Update installation unavailable`。Host updater metadata 请求固定 5 秒总时限。托盘 Quit 与 macOS 自定义应用菜单/Cmd-Q 共用 `app.exit(0)` 请求；应用菜单不使用会直达原生 `terminate:` 的 predefined Quit。Host 收到 `ExitRequested` 后才请求 `POST /api/v1/server/shutdown` 的 `keep_monitor` 结构化关闭并有界等待 owned child，API 错误或超时后显式 `kill + wait`，无法确认 child 已退出则阻止 host 退出，不依赖进程 `Drop`。外部 AppleScript quit、Force Quit、SIGKILL 等可绕过该事件，不属于有序退出承诺。Rust picker 最多等待 120 秒，Python 保留 125 秒响应预算，四条 picker API 的私有错误固定为脱敏 `503 Native picker unavailable`。授权在 post-preference revalidation 后先 arm，随后由 100 ms 有界 child liveness watcher 撤销。Python 启动后捕获并清除 secret/token，monitor、后台同步和原生子进程不会继承它们。
- `scripts/dev/tauri_version_sync.py` 从 `src/invoice_hub/version.py` 同步并校验 Cargo、Tauri 配置和 npm 的产品身份；`pnpm-lock.yaml` 与 `src-tauri/Cargo.lock` 已锁定对应 JavaScript/Rust 依赖。
- `rust-toolchain.toml` 固定 Rust/Cargo `1.85.0`，`.cargo/config.toml` 固定 MSRV-aware resolver。Windows/macOS 的 `doctor/bootstrap` 只诊断或按显式 `--install-js` 安装已锁定的 JavaScript 依赖，绝不安装 Rust、证书、Xcode 或 Visual Studio。
- 在不修改用户级 Rust 的官方隔离环境中，已解析精确 Tauri crate、审查 lock，并通过 HMAC、固定端口、身份拒绝、OpenAPI 方法、post-preference revalidation、Host RPC 撤权/超时、tray/browser 与 L6 manifest/candidate/order 的聚焦验证。L6-R 另在同一 Rust 1.85 离线环境通过 13 个 library 与 5 个 lifecycle integration tests；干净隔离 Python 环境以项目精确 runtime pins、`pytest==9.1.1` 和 `httpx2==2.9.1` 运行了 31 个 L6-R API/Host RPC/metadata/documentation contracts，并将 `DeprecationWarning` 视为错误。L6-RR 在同一隔离 Python 环境以相同 warning-as-error 门禁运行更新服务、Host RPC 和文档契约，共 40 项通过；L6-RRR 的 42 项历史结果已由 L6-RRRR 的 44 项当前证据取代，覆盖 hosted strict public preflight、non-host bypass、检查锁 immediate-busy/approval 保留，以及 install 锁 immediate-error/approval 保留/无第二次 RPC。Rust 未改动也未重跑。这些是进程内或 source-level evidence，不是已启动 product FastAPI 服务或真实 updater；本轮未重跑未修改 binary entry 的 `cargo check`。详细命令、通过数量和未覆盖边界见 [Tauri 2 执行计划](docs/release/TAURI2_EXECUTION_PLAN.md)。
- L6-RRRRR 以 45 项通过取代上述 44 项作为当前 host-lock 竞争证据：该历史样本未证明 contended busy 在返回前不会进入 `append_event` 的 SQLite 写入，也未覆盖 private `update_install` 异常后的 `finally` 锁释放。该结果仍不扩展为 Rust、产品进程或真实 updater 证据。
- L8-S/L9 已通过受控 macOS arm64 development `.app` 的组装、资源、固定端口、health/background、首页/静态资源、`desktop_available=true` 和默认 desktop 验证。开发 manifest 使用 schema 3，显式 venv launcher 与 manifest 原始字节均受 SHA-256 绑定；development profile 必须显式给出已存在的绝对 `INVOICE_HUB_DEV_STATE_ROOT`，host canonicalize 后要求它与 bundle/core 双向不包含，release、缺失或相对覆盖 fail-closed，且该变量不会传给 Python child。后续 clean-commit 退出复核发现外部 AppleScript quit 绕过 shutdown POST，虽然 host/child、端口和 PID 已收束，`server_state.json` 仍停在 `ready`；因此有序退出证据已撤回，必须由 P1-Q 的自定义应用菜单/Cmd-Q 样本重新建立。真实用户 Application Support 目录未被读取或写入，`.app` 及 staging/target 都未加入 Git。最初 tray 初始化因 16-bit RGBA `icon.png` 失败，已改为 8-bit RGBA，并用 PNG IHDR 回归锁定同类问题。该 development profile 明确禁用 updater，不证明原生 picker、browser/tray、单实例、打印、下载/验签/安装或任何发布流程。
- P1-R 接管复核已通过锁定 Rust 格式、16 项 library、6 项 lifecycle integration、desktop binary check、版本同步、聚焦 Python contracts、`compileall` 与 diff whitespace 门禁，Rust 编译无 warning。复核删除了 fail-closed 后不再可达的 monitor-stop/install-success 片段，没有用 dead-code allow 掩盖半实现。该结果只允许形成 DCO 开发提交并从 clean commit 重建一次 development `.app`，不扩大为真实 updater、安装器或平台发布证据。
- P1-RR 进一步修复了两个先前未被代表样本覆盖的私有边界：Python Host RPC 对 private loopback listener 的 bearer 请求显式禁用 `HTTP_PROXY/http_proxy` 等环境代理；development state root 以整个 macOS `.app` 容器为 containment boundary，`Contents/state` 这类不在 `Resources` 内的 sibling 也 fail closed。16 项 Rust library、6 项 lifecycle integration 与 16 项 Host RPC Python contracts 通过；这只允许继续受控开发，不构成真实 native panel、updater、安装器或平台发布证据。

## 发布与验证规则

- `src/invoice_hub/version.py` 是版本、协议、通道、公开链接和 package ID 的单一真值。Cargo、Tauri 与 npm 版本只能由同步/校验脚本派生。
- 每项实验必须先记录假设、会改变的决策、最小样本和停止条件。相同机制仅保留一个代表样本；每个 RC 最多一次完整回归。
- 公开前已运行一次候选内容审计和一次保留 refs 全量审计。后续文档或仓库设置变更不刷新该审计；真实命中才隔离或替换，并按受影响机制复核。
- 每个平台最终 RC 只做一次安装、启动、目录选择、托盘和更新烟测；修复后只重跑受影响类别。

## 尚未完成

- 一次开发 `.app` 烟测仅覆盖 schema-3 development assembly、固定端口 owned backend、health/background、首页/静态资源和 desktop 默认值；其旧有退出子结论已撤回，P1-Q 仍需用自定义应用菜单/Cmd-Q 重建结构化退出证据。原生打印、原生 picker、browser/tray、真实单实例与错误端口、合法/篡改更新、真实下载/验签/monitor 停止、安装/重启和其余决策场景仍未在桌面运行环境验证；development artifact 不构成平台安装验证。
- 公开 Release、GitHub Pages Feed、正式 Windows 签名、macOS Developer ID/公证和最终用户安装烟测均尚未进行。
- 真实业务做账迁移、审批、导出和外部账套操作必须在用户当回合明确授权后另行执行。

## 验证范围说明

本文只描述当前源码能力与后续范围，不代表对任何历史二进制、真实目录、真实发票、正式 Windows BAT、系统原生面板或正式安装包作出新的验证声明。
