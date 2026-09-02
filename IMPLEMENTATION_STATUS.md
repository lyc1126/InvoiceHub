# IMPLEMENTATION_STATUS

更新时间：2026-09-02

## 公开基线

- 本仓库已将单一、脱敏的根提交发布为公开 `main`。旧的私有提交图、验证记录、二进制包和 Tag 只保留在 owner-only 私有归档中，不属于公开历史，也不会作为 Release 资产上传。
- 当前开发版本为 `0.3.0-alpha.2`；macOS public-preview 的独立 package identity、LaunchServices/quarantine smoke、SSE 关闭修复与 receipt finalization 门禁已合入公开 `main`，远端同名 Tag 仍是此前基线。组包器只可内部验证精确 pending receipt，随后必须写入并默认复验与实际 DMG SHA-256 绑定的 finalized record。该旧 Tag 不含此门禁，最终仍须在干净 `main` 上经新的明确授权重建 Tag。Windows SignPath 工作流已锁定安装器、SHA-256 与 receipt 三项 Actions artifact，但还未触发签名请求。没有 GitHub Release、公开资产或 Feed，任何公开二进制仍必须从脱敏图上的干净版本、Tag 和新发布证据构建。
- public-preview 另有专用成品烟测：它从 DMG 挂载复制的 App 复核默认 finalized receipt 与 ad-hoc 签名、写入 quarantine，再通过 LaunchServices 的 `open -n -W -g` 和临时 `HOME` 启动；不允许直接执行 `Contents/MacOS`，也不允许传递 `INVOICE_HUB_DEV_STATE_ROOT`。为使 WebView 的 EventSource 不再拖住 Uvicorn，SSE 生成器会在结构化 shutdown 已被接受后结束。receipt gate 的聚焦契约与既有 smoke 契约已经就绪，但最终干净 Tag 的 DMG、Finder/Gatekeeper 人工交互和成品验收尚未完成。
- 历史净化的范围、私有备份和已完成的公开门槛见 [执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。公开仓库已启用 DCO、Dependabot、Secret Scanning、Push Protection 和私密漏洞报告；仍未创建 Release 或更新 Feed。

## 保留的产品边界

- 产品仍是 `v1 localhost`：单一活动 `TargetProfile`、文件为业务真值，SQLite 只保存任务、事件、设置与缓存。
- 共享核心继续使用 Python、FastAPI、Web、CSV/XLSX/JSON 投影和独立 monitor；不为桌面壳重写发票、成本、单据或做账逻辑。
- Windows 与 macOS 源码同仓，但成品必须严格按平台隔离。用户配置、日志、运行态和业务文件均不进入源码或发布输入。

## 已实现的共享能力

- PDF/OFD/XML 票头与成本明细提取、金额合法性保护、两维分类、同票纠偏、普通汇总与成本投影。
- 独立 monitor、后台 startup sync、文件事件合并、周期兜底、手改三字段保护和可诊断日志。
- FastAPI 页面/API、目录草稿、监控控制、结构化关闭、源文件预览、批量打印、皮肤安全边界和真实表格/TSV 复制。
- 三套内置应用图标（暖橙、青碧、罗兰紫）的设置/皮肤页选择、浏览器 favicon 同步和 Tauri 私有 Host RPC；选择独立于皮肤，只保存到 `runtime/local_state/app_icon_state.json`。
- Windows portable 正式 BAT 保留 `Win32_Process` 命令行的严格身份校验；受限会话拒绝 CIM 元数据时，只接受解释器路径与 health 的 PID、配置、运行目录、build/package 全部一致的回退。新启动的 `Start-Process` 子进程只在本轮失败清理中使用其句柄，持久 PID 的 stop 仍经过身份复核；这不构成 Tauri 原生界面或安装包验收。
- 做账 W8/W9 的本地文件真值、状态迁移预览、服务端执行校验、批次 manifest 与只读 dry-run 边界。
- macOS SwiftUI/WKWebView 壳保留为现有平台参考；它不改变共享业务逻辑，也不构成未来 Tauri 发布证据。

## `v0.3` 目标

- 使用 Tauri 2 负责窗口、托盘、单实例、原生面板、打印、后端生命周期、受限 Host RPC 和 updater。
- 固定 localhost 为 `127.0.0.1:8766`；未知占用明确失败，不能换端口或接入未知旧进程。
- 首版目标是 Windows 10/11 x64 NSIS 与 macOS 13+ arm64 DMG/更新归档。Intel Mac、Windows ARM64、MSI、App Store、云端和增量更新不在首版范围。
- host recovery/relaunch coordinator 已完成源码与 contract 接线：启用 updater 的 profile 可在 owned startup gate 释放后执行 Tauri 内置下载/签名验证、monitor 暂停、安装与平台重启；普通 development 与 internal-alpha 制品仍显式禁用 updater。L10-E 只新增一个精确 development recovery-smoke 变体，用不可达 loopback endpoint 和无验签能力的 key sentinel 激活 startup restore；它不是产品更新 profile。macOS arm64 隔离样本已证明 owned startup restore、marker 删除和 monitor 显式停止，但未运行任何真实 Feed、候选、下载、验签、安装或重启，因此不构成产品 updater 或发行验收。

## Tauri 2 生命周期边界与开发 `.app`

- `src-tauri/` 已提供固定 `127.0.0.1:8766` 的后端生命周期代码：未知占用失败、host 启动的 child PID/manifest/identity/OpenAPI 方法严格握手、单实例恢复窗口，以及仅在成功后创建 WebView。初次握手后严格读取 `startup_surface`，再以新的 HMAC challenge 和 identity probe 复核归属才 arm 授权：`desktop` 创建 WebView，`browser` 只由 host-only opener 打开固定 origin；托盘和第二实例重新打开既定 surface，desktop 关闭只隐藏窗口且不停止 monitor。裸源码 checkout 仍因没有经编译绑定的 manifest 以状态 `78` fail-closed；`scripts/dev/tauri_dev_app.py` 的普通 `stage/build` 只生成 updater-disabled schema-3 development manifest、允许清单内 core 与显式 venv launcher，并将 manifest/launcher SHA-256 绑定进本地 arm64 host。显式 `stage-recovery/build-recovery` 只为 L10-E 写入 Rust host 接受的精确不可安装 tuple；两种 build 都可使用绝对 pnpm 或绝对 Tauri CLI，且都不产生 release manifest、DMG、NSIS 或正式发布输入。
- 应用图标选择新增三套随包 PNG 资产与 bundle `png/ico/icns` 默认图标；`GET/PUT /api/v1/app-icon` 只接收内置 `orange/teal/violet`，状态只保存到 `runtime/local_state/app_icon_state.json`。Tauri host 的私有 `set_app_icon` payload 必须恰好是该枚举；host 先更新窗口、任务栏和托盘，Python 只在成功响应后写入状态，避免下次启动与当前原生 surface 不一致。该实现只完成源码和契约覆盖，尚未运行 Windows 原生窗口、托盘、任务栏或安装包验收。
- Windows Tauri host 对这三份编译期 PNG 只接受并解码 8-bit RGBA 数据，再交给原生窗口和 tray；不依赖未启用的 Tauri 可选图片 API。Windows recovery marker 的底层 `HANDLE` 保持唯一 owner，不可 `Clone/Sync`，仅为 `Box<dyn RecoveryMarkerStore + Send>` 的跨线程转移声明受限 `Send`，并继续由一次 `Drop` 关闭。临时 marker 在同一 handle 上校验前保留 `FILE_READ_ATTRIBUTES`；no-replace rename 使用 `NtSetInformationFile` 和已打开目录句柄，避免 Win32 `SetFileInformationByHandle` 对 non-null `RootDirectory` 的 `ERROR_INVALID_PARAMETER`。实际 Windows contract 已通过相对根拒绝、publish/load/exact clear 与 no-clobber，锁定 desktop `cargo check` 也通过；该项仍只是 marker 存储与编译边界，不扩大为原生窗口、任务栏、托盘、打印、updater 或安装包运行验收。
- 打印弹窗许可保持默认开启的独立偏好 `allow_print_popups`：设置页可保存该严格布尔值，host 只在启动时读取；关闭时拒绝全部子窗口，开启时也只能从精确 `about:blank` 进入固定 localhost、无 query/fragment 且受限 job id 的打印页。当前 Windows host 同时显式创建 `%LOCALAPPDATA%\\InvoiceHub\\webview` 作为 WebView2 数据目录、以 GUI subsystem 运行，并以 `CREATE_NO_WINDOW` 和 runtime stdout/stderr 日志阻止后端控制台窗口；这些是源码/静态契约边界，不替代新的原生打印或 Windows 成品验收。
- internal-alpha 发行准备已落地并完成一次真实 arm64 构建：`scripts/dev/tauri_alpha_release.py` 从精确 Git snapshot 复制 allowlist core，校验并嵌入 Python 3.14.6 arm64 runtime，生成 schema-3 host manifest、launcher/build/package/runtime manifest 和 schema-4 receipt；`scripts/dev/verify_tauri_alpha.py` 对工作区副本的 App、DMG、哈希、布局、平台污染和 ad-hoc 模式做 fail-closed 校验并通过。完整 `source_commit` 与 `core_build_id` 留在 [L11-A 执行记录](docs/release/L11_A_INTERNAL_ALPHA_PLAN.md)和交付 receipt；该 artifact 明确为 `updater_enabled=false`、`public_release=false`。另以临时 HOME/state root 完成一次独立启动烟测：固定端口 health 到达 `ready`，身份匹配且未触碰真实 Application Support；该结果仍仅是内部评审证据，不是正式签名、公证、发布或最终用户安装证据。
- 归属证明使用后端独有的 256 位 secret、宿主每次新建 challenge 和 HMAC-SHA256 响应；secret 不发送给端口监听者。Host RPC token 只由 host 传给其直接启动的 Python backend，backend 启动时捕获并从 descendant 环境清除，绝不进入 WebView、Tauri command/event、API 响应或日志。私有随机 loopback listener 的 picker 面仅保留四种原生选择器枚举，更新命令面独立地仅为 `update_check/update_install`，WebView 没有 IPC 权限；host candidate 最多保留 300 秒，由 listener loop 主动清除并保存完整 cloneable `Update`，Web 只看到版本。同一进程同时具备 Tauri marker 与 configured private RPC 时，API、设置页和后台 timer 均通过 `check_for_updates` 进入 strict host preflight；只有非 Tauri/非 host 检查不获取 `_host_update_lock` 并保留 `UpdateService` 的 cache/ETag/nonblocking-busy 语义。host 检查锁竞争返回不持久化 busy 且不触发 metadata/candidate、不会清除既有 approval；install 锁竞争立即抛脱敏错误，不消费 approval 或发送第二次 RPC。host approval 必须来自同一 session 内显式携带 `Cache-Control: no-cache`、不带 ETag 的 fresh `200` body，缓存、ETag、`304`、离线或错误不授予 approval，随后才要求版本完全一致。安装接口只接受 `{}`，错误固定为脱敏 `503 Update installation unavailable`。Host updater metadata 与下载对象固定 5 秒时限。托盘 Quit 与 macOS 自定义应用菜单/Cmd-Q 共用 `app.exit(0)` 请求；应用菜单不使用会直达原生 `terminate:` 的 predefined Quit。Host 收到普通 `ExitRequested` 后才请求 `POST /api/v1/server/shutdown` 的 `keep_monitor` 结构化关闭并有界等待 owned child，API 错误或超时后显式 `kill + wait`，无法确认 child 已退出则阻止 host 退出；私有 update commit 期间普通 Quit 同样被阻止，只有 macOS 已准备 update relaunch 可跳过重复 shutdown。外部 AppleScript quit、Force Quit、SIGKILL 等可绕过该事件，不属于有序退出承诺。Rust picker 最多等待 120 秒，Python 保留 125 秒响应预算，四条 picker API 的私有错误固定为脱敏 `503 Native picker unavailable`。授权在 post-preference revalidation 后先 arm，随后由 100 ms 有界 child liveness watcher 撤销。Python 启动后捕获并清除 secret/token，monitor、后台同步和原生子进程不会继承它们。
- L10-R 只完成 source-level 的 Tauri monitor recovery primitive：`BackendHost` 在 tray/surface 成功、`app.manage` 前释放 startup gate，并把 generation、phase、health/owned/process PID 和 state scope 固定为 lifecycle lease。恢复事务会在每次 marker 或未来 bridge 操作前后复核该 lease；仅对已经 `running && ready` 的 owned monitor 写入标记，已有标记、corrupt/cross-scope 标记、未就绪 monitor、ownership 丢失和 bridge failure 都 fail closed。Unix marker store 以 opened-directory descriptor 加 `O_NOFOLLOW`/`openat`/atomic no-clobber `linkat`/`unlinkat` 固定最终操作；在该 L10-R 阶段其它非 Unix 平台返回 unavailable。下方 L10-C source-level slices 后续补充 Windows handle-relative/no-reparse marker store 与 Unix whole-operation protocol hardening。尚未接入 Host RPC、真实 monitor、下载、安装或重启，因此当前 `update_install` 的 candidate-consuming fail-closed 语义不变。
- L10-C 基础切片补齐四个可注入边界：固定 `127.0.0.1:8766` 的 `PythonMonitorRecoveryBridge`、只接收 `VerifiedUpdate` 的 pure `UpdateCoordinator`、共享既有 child/ownership/lifecycle `Arc` 的 cloneable `BackendLifecycleAuthority`，以及 Windows handle-relative/no-reparse marker store。该阶段的 source-level 结果和 Windows 编译限制保留为历史证据；它当时未接入 Host RPC/updater/startup restore，当前行为由下一条 L10-D 取代。
- L10-D 已完成 authenticated recovery/relaunch runtime coordinator 的源码接线。Backend 私有 secret 对三条 recovery 请求和精确响应做 fresh challenge/HMAC-SHA256 双向绑定，Python 以 128 个 challenge 的进程内有界集合拒绝重放并要求空 body，普通 bridge 调用不变。Updater 只在 startup gate 释放、`BackendHost` 注册后激活，从 `expected_identity.runtime_dir` 打开平台 marker store并先恢复；恢复失败保留 marker、WebUI/backend 和诊断，同时阻断 updater。`update_install` 原子消费 fresh 完整候选，worker 在 execute/cancel latch 后等待，精确 `{"ok":true}` 写入并 flush 后才执行 download+verify -> pause -> install -> relaunch；writer/spawn/latch loss 进入 `CommitLost` 且无副作用。Windows installer callback 先确认 managed backend 终止，macOS 安装后先停 backend、标记 relaunch prepared、再 `request_restart()`。这些是源码和 contract 证据，不是任何真实 Feed、monitor、installer、restart 或平台运行证据。
- L10-E 把运行验证限制为一个不可安装的 development recovery-smoke profile：Rust 只接受固定 `https://127.0.0.1:1/invoicehub-recovery-smoke/latest.json` 与明确写着 `NOT A SIGNING KEY` 的 base64 sentinel，且 enabled updater 对象只能有三个精确字段。`scripts/dev/tauri_recovery_smoke.py` 复核 App plist、manifest/launcher/build 身份，再创建临时 HOME/state/runtime/watch、关闭自动更新检查、预置同 scope marker；运行时只读取 health/status，并在恢复后调用 monitor stop，HTTP allowlist 不含 update 或 bridge start。预检修复了 Tauri 实际 `CFBundleExecutable=invoicehub-desktop` 的绑定；首次启动又在 backend 前暴露并修复 development overlay 缺少 updater 配置对象的问题，空 `pubkey` 占位不含 endpoint 或验证权限。离线重建后的 macOS arm64 样本以 build ID `8e40363fa673017e993727cf3f5dec347b24927c5ce1a0a4b945601737621873` 恢复 owned monitor 到 `running && ready`，删除 marker、显式停止 monitor并清理 backend/monitor PID、固定端口与临时目录，runner 报告 `update_requests=0`。
- `scripts/dev/tauri_version_sync.py` 从 `src/invoice_hub/version.py` 同步并校验 Cargo、Tauri 配置和 npm 的产品身份；`pnpm-lock.yaml` 与 `src-tauri/Cargo.lock` 已锁定对应 JavaScript/Rust 依赖。
- `rust-toolchain.toml` 固定 Rust/Cargo `1.85.0`，`.cargo/config.toml` 固定 MSRV-aware resolver。Windows/macOS 的 `doctor/bootstrap` 只诊断或按显式 `--install-js` 安装已锁定的 JavaScript 依赖，绝不安装 Rust、证书、Xcode 或 Visual Studio。
- 固定 endpoint/method/origin 本身仍不是 ownership proof；L10-D 的 host recovery 请求必须持续使用 backend-private secret 的 fresh challenge/HMAC 双向认证和 lifecycle 前后 revalidation，不得向候选固定端口发送 bearer secret，也不得把该认证 secret 扩大到普通页面 bridge 或 Web API。
- 在不修改用户级 Rust 的官方隔离环境中，已解析精确 Tauri crate、审查 lock，并通过 HMAC、固定端口、身份拒绝、OpenAPI 方法、post-preference revalidation、Host RPC 撤权/超时、tray/browser 与 L6 manifest/candidate/order 的聚焦验证。L6-R 另在同一 Rust 1.85 离线环境通过 13 个 library 与 5 个 lifecycle integration tests；干净隔离 Python 环境以项目精确 runtime pins、`pytest==9.1.1` 和 `httpx2==2.9.1` 运行了 31 个 L6-R API/Host RPC/metadata/documentation contracts，并将 `DeprecationWarning` 视为错误。L6-RR 在同一隔离 Python 环境以相同 warning-as-error 门禁运行更新服务、Host RPC 和文档契约，共 40 项通过；L6-RRR 的 42 项历史结果已由 L6-RRRR 的 44 项证据取代，覆盖 hosted strict public preflight、non-host bypass、检查锁 immediate-busy/approval 保留，以及 install 锁 immediate-error/approval 保留/无第二次 RPC；这些数字是对应历史切片，不冒充产品运行。当前 L10-E 收尾另通过 77 项聚焦 Python Tauri/Host RPC/文档契约、锁定 Rust 格式与离线 desktop/tests `cargo check`、版本同步、`compileall` 和 diff whitespace 门禁，并完成上条隔离 startup-recovery 样本。详细命令、通过数量和未覆盖边界见 [Tauri 2 执行计划](docs/release/TAURI2_EXECUTION_PLAN.md)。
- L6-RRRRR 以 45 项通过取代上述 44 项作为当前 host-lock 竞争证据：该历史样本未证明 contended busy 在返回前不会进入 `append_event` 的 SQLite 写入，也未覆盖 private `update_install` 异常后的 `finally` 锁释放。该结果仍不扩展为 Rust、产品进程或真实 updater 证据。
- L8-S/L9 已通过受控 macOS arm64 development `.app` 的组装、资源、固定端口、health/background、首页/静态资源、`desktop_available=true` 和默认 desktop 验证。开发 manifest 使用 schema 3，显式 venv launcher 与 manifest 原始字节均受 SHA-256 绑定；development profile 必须显式给出已存在的绝对 `INVOICE_HUB_DEV_STATE_ROOT`，host canonicalize 后要求它与 bundle/core 双向不包含，release、缺失或相对覆盖 fail-closed，且该变量不会传给 Python child。外部 AppleScript quit 曾绕过 shutdown POST 并留下 stale `ready`，该不受支持路径的有序退出结论仍撤回；P1-Q 随后从 clean source commit 重建并向前台 app 发送真实 Cmd-Q，确认 shutdown POST 200、`server_state=stopped`、monitor 保持停止、host/backend 退出、8766 释放且 server PID 清理。打开的 SSE 连接使 host 在 stopped state 后使用了显式 `kill + wait` 兜底。真实用户 Application Support 目录未被读取或写入，`.app` 及 staging/target 都未加入 Git。最初 tray 初始化因 16-bit RGBA `icon.png` 失败，已改为 8-bit RGBA，并用 PNG IHDR 回归锁定同类问题。该 development profile 明确禁用 updater，不证明原生 picker、browser/tray、单实例、打印、下载/验签/安装或任何发布流程。
- P1-R 接管复核已通过锁定 Rust 格式、16 项 library、6 项 lifecycle integration、desktop binary check、版本同步、聚焦 Python contracts、`compileall` 与 diff whitespace 门禁，Rust 编译无 warning。复核删除了 fail-closed 后不再可达的 monitor-stop/install-success 片段，没有用 dead-code allow 掩盖半实现。该结果只允许形成 DCO 开发提交并从 clean commit 重建一次 development `.app`，不扩大为真实 updater、安装器或平台发布证据。
- P1-RR 进一步修复了两个先前未被代表样本覆盖的私有边界：Python Host RPC 对 private loopback listener 的 bearer 请求显式禁用 `HTTP_PROXY/http_proxy` 等环境代理；development state root 以整个 macOS `.app` 容器为 containment boundary，`Contents/state` 这类不在 `Resources` 内的 sibling 也 fail closed。16 项 Rust library、6 项 lifecycle integration 与 16 项 Host RPC Python contracts 通过；这只允许继续受控开发，不构成真实 native panel、updater、安装器或平台发布证据。
- P1 setup cleanup：`BackendHost::launch` 后的 tray、desktop window 或 browser surface 初始化若失败，host 会在返回原始 setup error 前调用既有 `keep_monitor` shutdown，并在失败/超时时使用显式 `kill + wait`；无法确认 owned child 退出时 setup 保持阻塞并定期重试，child mutex 或 `try_wait` 错误也不得被当作 graceful exit，绝不把 cleanup error 交给 `Drop` 后退出。backend 与 `startup_surface` 只有在全部可失败初始化成功后才会 `app.manage`；L10-D updater 激活还必须发生在 manage 之后。该修复与当前 coordinator 源码接线都不构成真实 updater、安装器或平台发布证据。

## 发布与验证规则

- `src/invoice_hub/version.py` 是版本、协议、通道、公开链接和 package ID 的单一真值。Cargo、Tauri 与 npm 版本只能由同步/校验脚本派生。
- 每项实验必须先记录假设、会改变的决策、最小样本和停止条件。相同机制仅保留一个代表样本；每个 RC 最多一次完整回归。
- 公开前已运行一次候选内容审计和一次保留 refs 全量审计。后续文档或仓库设置变更不刷新该审计；真实命中才隔离或替换，并按受影响机制复核。
- 每个平台最终 RC 只做一次安装、启动、目录选择、托盘和更新烟测；修复后只重跑受影响类别。

## 尚未完成

- development `.app` 烟测覆盖 schema-3 development assembly、固定端口 owned backend、health/background、首页/静态资源、desktop 默认值，以及一个真实 Cmd-Q 的结构化退出样本；internal-alpha 另完成了 App/DMG/receipt 独立 verifier 和一次隔离启动烟测。tray 点击、外部终止和其它平台退出机制没有因此获得同等结论。原生打印、原生 picker、browser/tray、真实单实例与错误端口、合法/篡改更新、真实下载/验签/monitor 停止、安装/重启和其余决策场景仍未在桌面运行环境验证；development/internal-alpha artifact 均不构成平台安装验证。
- 公开 Release、GitHub Pages Feed、正式 Windows 签名、macOS Developer ID/公证和最终用户安装烟测均尚未进行。
- 真实业务做账迁移、审批、导出和外部账套操作必须在用户当回合明确授权后另行执行。

## 验证范围说明

本文只描述当前源码能力与后续范围，不代表对任何历史二进制、真实目录、真实发票、正式 Windows BAT、系统原生面板或正式安装包作出新的验证声明。
