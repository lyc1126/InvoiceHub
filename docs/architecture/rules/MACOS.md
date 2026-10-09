# macOS 平台与 SwiftUI 参考壳规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：macOS Application Support、NSOpenPanel、SwiftUI/WKWebView、Sparkle、签名与原生验收。
- 代码与验收定位：macos/InvoiceHubMac/；平台架构第 5—8 节、任务导航第 12.1 节；当前 Tauri 产品同时读 TAURI_HOST。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-macos) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

范围说明：SwiftUI/WKWebView 与 Sparkle 条款约束现存参考壳及其构建链；当前 Tauri 成品、宿主和更新资格仍须按 [Tauri 规则](TAURI_HOST.md) 与 [发行规则](RELEASE.md) 核对，不因保留这些约束宣称参考壳是当前发布目标。

## macOS 本地壳规则

- macOS 第一版为 SwiftUI/WKWebView 本地壳，业务核心继续复用 Python/FastAPI、`/api/v1`、CSV/XLSX/JSON 投影和独立监控 daemon；不得为 macOS 单独重写发票识别、成本分析或状态口径。
- `.app` bundle 只允许放只读核心资源和内置运行时；用户配置、SQLite、日志、pid、皮肤导入和运行态必须写入 `~/Library/Application Support/InvoiceHub` 或等价用户可写目录，不得写入 `.app/Contents`。
- macOS 用户运行不得依赖 Docker；Docker 只作为开发、测试和未来云端依赖验证工具。
- macOS 目录选择优先使用系统原生 `NSOpenPanel`；选择结果必须仍通过后端设置接口保存，并保留“待保存目录/保存后切换活动目录”的产品语义。
- macOS WKWebView 内的页面“选择文件夹”不得调用 Python/Tk picker；必须通过 Swift bridge 调用 `NSOpenPanel`，只把选择结果和后端校验结果返回给页面，避免弹出 Python Launcher 或选择器闪退。
- 重建未签名 macOS 开发 `.app` 可能改变 TCC 代码身份并重新触发“下载”等受保护目录授权；严格握手或 `health.ok=true` 不代表 `watch_dir` 可读。出现后台同步超时、`background_status=failed` 或页面 `Load failed` 时，必须先用系统日志区分目录权限与预览/API 故障；只有用户明确允许后才可通过真实 `NSOpenPanel` 重新授权，随后必须复验 `background_status=ready`、手动重建和源文件预览。
- macOS WKWebView 内的 HTML 文件输入必须由 `WKUIDelegate` 实现 `runOpenPanelWith`，使用系统 `NSOpenPanel` 并在选择或取消后始终完成 WebKit 回调；皮肤页只允许选择单个 ZIP，修改后必须在真实 `.app` 中点击验收原生面板。
- macOS 批量打印只允许受信主 WebView 以精确 `about:blank` 创建子窗口；登记后的子 WebView 只能导航到同端口、无查询和 fragment 的 `/invoices/print/{job_id}`。外部域名、错误端口、子框架和普通页面不得继承任何原生能力。
- 打印子窗口只能注入受限 `window.print()` bridge，并在已登记的打印路由、主框架和预期 origin 全部匹配时调用 `WKWebView.printOperation(with:)`；目录选择、后端控制和通用 `window.invoiceHubMac` bridge 只允许主 WebView，取消打印按正常完成处理并派发 `afterprint`。
- macOS 工具栏、菜单或 Swift bridge 触发的保存目录、重新汇总、监控启停等原生命令，必须复用 `/api/v1` 后端返回值，并在成功或失败后刷新/诊断 WKWebView 可见状态；不得只在 Swift 状态栏写“操作已发送”而让页面保持旧汇总。
- macOS 开发 `.app` 重跑脚本必须先收束旧 app 和旧 InvoiceHub 后端，再打开新版 app；不得让新壳连接到即将被旧壳退出钩子终止的 localhost。SwiftUI 壳运行中应禁用 AppKit 自动终止，避免系统在窗口/恢复状态短暂为空时结束 app 并带掉后端。
- macOS 开发 `.app` 脚本必须明确准备或绑定可用 Python 后端环境；写入 `dev-python-path.txt` 后，Swift 端必须校验该路径可执行，失效时直接诊断，不得静默回退到缺少依赖的系统 Python。
- macOS 壳不得只凭 `/api/v1/health` 的 `ok=true` 接入 localhost；必须同时核对打包 build ID、API 契约版本、必需能力、配置路径、运行目录和关键页面/API，任一不匹配都要拒绝连接并显示预期值、实际值、端口和日志路径。
- macOS 严格握手必须同时校验构建 manifest、health 和 Swift required 三方的 API 契约、`w9-ledger-review-v1` 与完整 capabilities；manifest 缺失/无效、`build_manifest_present=false` 或任一能力集合漂移都必须拒绝连接。
- macOS 严格握手只能实际读取 health 和无业务扫描的静态页面；必需 API 通过 `/openapi.json` 校验注册，不得为探测兼容性读取会扫描真实 `watch_dir` 的 documents/bookkeeping 等数据接口。Swift 与开发脚本的每次 HTTP 探测都必须设置连接和总时限。
- macOS 壳与开发脚本不得为规避端口冲突自动换端口；同一 Application Support 运行态只能有一套 localhost 写入者，固定端口被未知程序占用时必须明确失败。
- macOS 开发脚本只能终止命令行为 `invoice_hub.api.main` 且 `--config` 精确指向当前 Application Support 配置的旧服务；无法验证归属的 PID 或监听进程不得终止。
- `python -m invoice_hub.api.main` 启动只能构造一份 FastAPI/AppState 和一条后台 startup sync；包级 API 导出不得在 CLI 参数解析前抢先实例化默认应用。
- 关闭 macOS 主窗口不等于停止监控；停止 localhost 与停止监控必须保持分离，只有明确 stop-all/停止监控动作才允许停止监控 daemon。
- macOS 壳只能把当前壳启动且 Process/PID/health 精确匹配的服务标为 `owned`；一次 API 控制失败不得把 owned 服务降级为 external。发送终止信号后只有确认进程退出才允许清理 PID 和 ownership；超时必须保留真值和诊断。
- macOS 壳跨 `await` 的启动、停止、monitor 和重建结果必须绑定发起时的 lifecycle generation、phase、ownership、health PID 与 Process PID；完成时身份或代次已变化就丢弃旧结果，不得复活已停止服务或覆盖新的 starting/stopping 真值。
- WKWebView 的 `window.invoiceHubMac`、导航和原生 open panel 只对预期 `http://127.0.0.1:<固定端口>` 主框架开放；外部页面、子框架和不匹配 security origin 不得调用原生能力。
- SwiftPM GUI app 必须通过项目脚本生成 `.app` bundle 后运行，不把 SwiftUI GUI 当普通命令行可执行直接作为正式入口。
- macOS 正式包只能使用 `Contents/Resources/invoice-hub-core` 内嵌且清单匹配的核心与 Python，不得包含 `dev-python-path.txt`、`.backend-venv` 或系统 Python fallback；内嵌 core 缺失或结构无效时必须直接失败，绝不能回退当前目录或 checkout；monitor 使用项目内 polling observer，不为 macOS 强行引入缺少目标 wheel 的 watchdog。
- Sparkle 更新安装、升级标记写入、为更新停止/恢复 monitor 都必须由当前 App 已验证的 `owned` lifecycle（generation/phase/health PID/owned PID/Process PID）发起；`externalCompatible` 不得拥有 Web bridge、原生菜单或恢复路径来安装更新或改变其 monitor。安装前必须先写 Application Support 恢复标记，再停止 monitor 并确认真实 `running=false`；取消、下载/安装失败或停止失败时，仍由当前有效 owned lifecycle 恢复此前运行的 monitor。新版本只有在 build/package/health/OpenAPI 严格握手完成、启动已切换到经验证的 owned running 身份并释放 startup gate 后，才可尝试 marker 恢复；monitor 恢复 `ready=true` 后才删除标记。启动失败或 `externalCompatible` 路径仍必须保留既有收尾释放，不能以提前释放 gate 绕过身份验证。
- `externalCompatible` 的 Swift 菜单、侧栏和由壳注入的首页/设置页控件都必须禁用 monitor 的启动与停止；这是壳的所有权保护，不应把无认证 localhost HTTP API 误描述为跨客户端权限边界。
- macOS 正式脚本计算 SHA-256 时必须以 `LC_ALL=C LANG=C /usr/bin/shasum` 执行；构建机的 `C.UTF-8` locale 可能使系统 `shasum` 失败，不能把它当成产物哈希不匹配。
- macOS 内部候选的 staging App、Sparkle ZIP App、DMG App 与 DMG 容器必须全部为 ad-hoc 签名，并拒绝 Developer ID Authority 或 Team ID；验证器必须显式且互斥地使用 `--expect-internal-adhoc` 或 `--expect-notarized`，不得用自动猜测或无模式验证混淆内部候选与正式产物。
- Sparkle 发布私钥只允许使用 Keychain account `com.invoicehub.release`，`sign_update` 必须显式传递该 account。macOS 构建收据固定为 schema 4 并记录 `signature_mode`、`sparkle_keychain_account` 与 v4 验证器；公开 provenance/finalizer 只接受 `developer-id-notarized` 正式收据，仍须对实际制品独立执行 `--artifact-only --expect-notarized`，内部 ad-hoc 收据永远不能放行 Feed。
- macOS 发布验收必须额外覆盖：`.app/.dmg`、Developer ID、Hardened Runtime、公证/staple、quarantine、无 Docker/开发 `.venv`、包外发票目录、Application Support、原生面板、关闭窗口/monitor，以及一次真实 Sparkle 旧版到新版升级。
- macOS public-preview 的 DMG smoke 必须从挂载卷复制 App、复核 receipt 与 ad-hoc 签名、在复制件保留 quarantine，并仅用 `open -n -W -g` 经 LaunchServices 注入隔离 `HOME`；不得直接执行 `Contents/MacOS`、删除 quarantine 或传递 `INVOICE_HUB_DEV_STATE_ROOT`。其固定 shutdown 样本中，SSE 必须在结构化 shutdown 已被接受后结束，避免 WKWebView 的 EventSource 阻止 Uvicorn 正常退出。
- macOS 发布验证器对已签名 App 执行内嵌 Python、`pip check`、import smoke 或内容扫描时必须同时设置 `PYTHONDONTWRITEBYTECODE=1` 和解释器参数 `-B`；`-I` 会忽略 `PYTHON*` 环境变量，不能只靠前者。普通验证必须可重复执行且不得在 staging App 内新增 `.pyc` 或破坏 codesign seal，artifact-only 通过不能替代该幂等检查。

监控启停同时遵守 [监控规则](MONITORING.md)，成品输入和发布同时遵守 [发行规则](RELEASE.md)。

## 监控状态与原生停止补充

- macOS 优先使用 `PollingObserver`；观察器未激活而仅周期兜底时，必须明确显示 `observer_active=false`。
- SwiftUI 参考壳原生停止请求使用 `keep_monitor` 与 `remember=false`；应用退出可以收束属于当前壳的 child，但不能据此接管外部服务。

## 显式源文件回收

- macOS 显式删除只用 NSFileManager trashItemAtURL；失败保留源文件并诊断，不调用unlink或替代永久删除。原生废纸篓验收使用唯一合成文件，核对后恢复并清理；不以此冒充Tauri打包或真实业务配置验收。
