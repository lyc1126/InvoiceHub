# 变更日志

## 未发布

- 2026-08-26 macOS public-preview 启动与结构化关闭修复：新增独立的 DMG 成品烟测入口，先独立复核 App/DMG/receipt，再挂载、复制、ad-hoc 验签并为临时 App 写入 quarantine；Tauri App 只允许由 LaunchServices 的 `open -n -W -g` 启动，并仅注入隔离 `HOME`，不传 development state override。烟测只访问固定 health/monitor/shutdown allowlist，覆盖 monitor start/ready/stop 与 `stop_monitor` 结构化退出。`GET /api/v1/events/stream` 现会在已接受结构化关闭后结束生成器，避免 WKWebView 的 EventSource 阻止 Uvicorn 正常退出。聚焦 public-preview/release/recovery 测试共 22 项通过；此前候选仅用于定位该关闭缺陷，最终干净 Tag 的 DMG、真实 Finder/Gatekeeper 交互和 Release 资产仍待执行。

- 2026-08-25 macOS public-preview 组装门禁修复：共享 staging 器对 internal-alpha 保留 `dmg` 包型缺省值，public-preview 显式覆盖为 `preview-dmg`，使其独立 package ID 能通过 fail-closed package manifest 校验。新增回归契约，此修复尚未获新 Tag 或平台成品证据。

- 2026-08-25 `v0.3.0-alpha.2` 双平台公开预览组装基础：同步产品版本和现有构建身份；新增 macOS arm64 public-preview DMG 的独立 staging、release profile、ad-hoc receipt/verifier，以及 Windows x64 current-user NSIS/SignPath workflow、WebView2 SHA-256 锁和双层签名顺序。`v0.3.0-alpha.2` Tag 已创建但尚无 GitHub Release 或资产；其 macOS public-preview 包型缺陷由上条修复，等待修复合并后重新确定 Tag。updater、Feed 与平台成品烟测仍未执行；Windows 卸载器在本 alpha 中明确未签名。

- 2026-08-24 Tauri L10-E 非安装恢复烟测边界与运行证据：普通 development `stage/build`
  与 internal-alpha 继续生成 `updater.enabled=false`；新增显式
  `stage-recovery/build-recovery`，development manifest 只有在 endpoint 等于固定、
  不可达的 HTTPS loopback 地址且 public key 等于无验签能力的 sentinel 时才允许
  激活 L10-D startup restore，任一额外字段、任意 endpoint 或 key 都拒绝。新增隔离
  runner，使用临时 HOME/state/runtime/watch、`auto_check_updates=false` 和预置 marker，
  其 localhost 请求面只允许 health、monitor status 与 monitor stop，不调用
  `update_check/update_install`。运行预检先修复 runner 将 Tauri display name 误当作
  `CFBundleExecutable` 的问题，并把 App plist、host manifest 与 product version
  绑定；第一次启动随后在 backend/monitor 之前因缺省 `plugins.updater` 被 Tauri
  反序列化为 `null` 而 fail closed，development overlay 现只提供空 `pubkey` 配置
  对象，不携带 endpoint 或验签权限。锁定 Rust 1.85/Tauri CLI 2.11.4 离线重建后，
  macOS arm64 隔离样本以 build ID
  `8e40363fa673017e993727cf3f5dec347b24927c5ce1a0a4b945601737621873`
  通过：owned backend/monitor 身份与路径匹配，monitor 达到 `running && ready`，marker
  被删除，显式 stop 成功，runner 报告 `update_requests=0`；样本 PID、固定端口和临时
  目录均已清理。该结果只证明 authenticated startup restore，不授权或覆盖 Feed、
  候选、下载、验签、安装、重启、DMG/NSIS、签名、公证或发布。
- 2026-08-24 旧工作区功能与故障回溯治理：新增脱敏查询索引，按功能类别、
  常见症状、不变量和当前源码/测试入口提供回溯路线；原始非公开 Changelog 及其
  附件、路径、局部摘录和验证记录继续只留在私有归档外部，不复制、链接、暂存或
  提交到公开工作树、测试夹具或发布输入。
- 2026-08-24 文档治理：将本文件既有记录统一译为中文，并把后续
  `CHANGELOG.md` 使用中文的规则写入工程治理。新增或修改跨功能流程时，
  代码必须在交接点说明上游输入、下游消费者、执行顺序或不变量，以及失败
  边界；本次不改变产品行为。
- 2026-08-24 Tauri L10-D 认证恢复/重启运行时协调器：在既有的后端私有桌面
  所有权 secret 下，以 HMAC-SHA256 将每一条 Rust monitor 恢复请求及精确的
  Python 响应绑定到一个全新的 challenge；拒绝不完整、被篡改、非空 body 或
  重放的认证请求，且不改变普通 bridge 调用。以域分隔的 artifact identity
  保留完整的 host-owned updater candidate；只有 owned startup gate 已释放且
  `BackendHost` 已被管理后才激活 updater runtime，并在接受 updater 操作前
  恢复任何平台恢复 marker。`update_install` 现在先保留一个全新的 candidate，
  在 execute/cancel latch 后启动私有 worker，写入并 flush 精确的成功响应，
  然后才执行受锁保护的 Tauri 下载/签名校验 -> 暂停 monitor -> 安装 -> 重启
  协调器。writer/spawn/latch 丢失会显式进入 `CommitLost`，不产生 update 或
  monitor 副作用；startup restore 或 transaction 失败会保留后端供诊断，并
  阻断后续 updater 工作。Windows 在启动安装器前通过 `on_before_exit` 确认受管
  backend 已终止；macOS 先停止 backend、标记已准备重启，再请求 restart，私有
  commit 进行期间阻断普通 Quit。本项只有源码与契约集成：未运行或获授权运行
  产品进程、真实 Feed/update、monitor、安装器、重启、产物构建、签名、发布或
  平台运行烟测。
- 2026-08-23 Tauri L10-C 基础切片：新增固定 loopback 的
  `PythonMonitorRecoveryBridge`、纯 verified-artifact update coordinator，
  以及共享既有 child、ownership 和 lifecycle handle 的可 clone
  `BackendLifecycleAuthority`。新增 Windows marker-store 源码契约：使用相对
  于已打开目录的 handle 并拒绝 reparse point，同时保留 Unix 的
  descriptor-pinned marker primitive。这些仅为源码层接缝：遵循目录锁协议的
  Unix store 会串行化整个 load/publish/clear 操作，在持有锁时重读过期 clear，
  并在最终 publish/clear link 操作后持久同步目录元数据（绕过该协议的直接编辑
  不在保证范围内）。最小 `x86_64-pc-windows-msvc` 临时 crate 交叉编译通过；
  没有 Windows runtime 证据，完整 Tauri Windows target check 仍被需要
  `assert.h` 的 `ring` 阻断。所有切片都未接入 Host RPC、updater、startup
  restore 或真实 monitor；updater 仍会消费 candidate 并 fail closed。聚焦验证
  通过 56 项 Rust 检查（backend authority 14、bridge 9、coordinator unit 2 加
  contract 12、recovery 17、Windows host static 1、strict OpenAPI 1）和 42 项
  Python contract（lifecycle 13、development documentation 12、foundation 17）。
  strict OpenAPI handshake 要求 `GET /api/v1/bridge/status`、
  `POST /api/v1/bridge/stop` 和 `POST /api/v1/bridge/start`；缺失或方法错误的
  `/bridge/start` 会被拒绝。未来 updater 接线必须先公开保留 candidate，再进行
  私有 fixed-enum commit，因为锁定的 updater `2.10.1` 会在 Windows
  `Update::install()` 时退出进程，而 macOS 仍需 `request_restart`；commit loss
  与恢复失败必须保持为显式失败状态。
- 2026-08-23 L10-C bridge 边界：固定 loopback monitor adapter 没有请求级
  ownership authentication，不能作为 ownership proof。实际接线前，每个
  request/response 都必须绑定后端私有的 fresh challenge/HMAC 或等价认证 header，
  在请求前后保留 lifecycle revalidation，且绝不能把 bearer secret 发送给候选
  固定端口。
- 2026-08-20 Tauri L10-R monitor 恢复基础：为未来 host-owned monitor 恢复
  协调器新增纯源码、fail-closed 的 transaction。它捕获已释放的 owned
  lifecycle lease（generation、phase、health、owned 和 process PID 及 state
  scope），拒绝既有恢复义务或未 ready 的 monitor，且只在随后观察到 owned
  `running && ready` 后清除 marker。Unix marker 持久化使用固定目录 descriptor
  的 no-follow `openat`/atomic no-clobber `linkat`/`unlinkat`；非 Unix 构建明确
  返回 unavailable。该 transaction 不包含 Host RPC、真实 monitor、下载器、
  安装器、重启、bundle、签名或 release 集成，`update_install` 仍消费 candidate
  并 fail closed。
- 2026-08-19 Tauri internal-alpha 组装：新增有边界的 macOS arm64
  `internal-alpha` profile、clean-snapshot staging、内嵌 Python 3.14.6 runtime
  输入、manifest/launcher hash binding、receipt 生成与独立 fail-closed verifier。
  已安装 pnpm wrapper 不可用时，builder 可使用直接锁定的 Tauri CLI path。本项
  仅用于本地验证：未启用 Release、Feed、updater installation、Developer ID、
  notarization 或 GitHub mutation。
- 2026-08-19 Tauri internal-alpha 证据：从 clean commit
  `1892a52bf5eba4ae3b24720fbc32899a4e6003a0` 构建一个 arm64 `.app` 和同源码
  ad-hoc `.dmg`；独立 App/DMG/receipt verifier 通过，另一次临时 HOME launch
  smoke 在固定端口达到 `ready`，package/build/source identity 相符。产物仍仅
  用于内部，不形成 Release、Feed、updater installation、签名、notarization 或
  最终用户安装的声明。
- 2026-08-19 Tauri internal-alpha runtime gate：只允许解析后 target 仍位于
  embedded runtime 内的相对 runtime symlink；staging copy 仍会解引用它们，最终
  artifact verifier 拒绝 symlink。这允许使用固定的 python-build-standalone
  launcher link，同时不放宽 bundle containment。
- 2026-08-19 Tauri internal-alpha receipt 修复：将已签名 `.app` 表示为确定性的
  directory-tree digest 与文件总字节数，而非把 bundle 目录当作普通文件；DMG
  记录仍为普通文件 hash。
- 2026-08-19 Tauri internal-alpha bundle 映射：将已验证的 embedded Python
  runtime 纳入 `Contents/Resources/python`；verifier 现在检查与 App 相同的
  launcher-visible path。
- 2026-08-19 Tauri internal-alpha receipt 隐私：receipt 保存 artifact name 而非
  本机绝对 build path；hash、source identity 和 verification field 不变。
- 2026-08-18 Tauri setup cleanup 确认：在 `BackendHost::launch` 后，tray 或选定
  desktop/browser surface 的初始化可能在正常 `ExitRequested` handler 建立前失败。
  setup 会让 child 保持本地状态直到所有可失败初始化成功；失败时重试既有结构化
  `keep_monitor` shutdown，并以显式 kill-and-wait fallback 持续到确认 owned child
  已终止；child lock 或 `try_wait` error 视为未确认并进入 forced termination，
  而不是 graceful exit。仅在此后才返回原始 surface error。聚焦 lifecycle
  contract 禁止把 cleanup error 返回给 `Drop`；这不会启用 update installation 或
  形成 release 证据。
- 2026-08-17 Tauri Windows CI fixture 修复：development-app contract 不再假定
  POSIX execute-mode bit 在 Windows 上控制 `os.access(..., X_OK)`。其不可执行
  virtual-environment sample 现在只拒绝精确的 executable-access probe，从而在
  每个 hosted platform 确定性触发现有 fail-closed production branch。production
  staging、validation、packaging 与 runtime behavior 不变；聚焦及 hosted
  verification 已记录在 Tauri execution plan。
- 2026-08-17 Tauri exit/update timeout 修复：macOS application menu 现在使用
  带 Cmd-Q 的自定义 Quit item，它与 tray Quit 都请求同一 `app.exit(0)` path。
  每个收到的 `ExitRequested` 都先执行结构化 `keep_monitor` backend shutdown；
  menu 不使用可能绕过该 event 的 native predefined Quit selector。external
  termination path 不被宣称为有序 shutdown mechanism。API failure 或 timeout
  会显式 kill 并等待 owned child；无法确认终止时阻止 host exit，而非依赖 process
  `Drop`。host updater metadata check 现在使用五秒总 timeout，避免 stalled Feed
  永久占用 updater mutex 或 Host RPC connection capacity。聚焦验证已记录在
  Tauri execution plan。一个 clean-commit macOS development sample 向前台 app
  发送真实 Cmd-Q，观察到 shutdown POST、stopped state、host/backend exit、固定
  端口释放和 PID cleanup。打开的 SSE connection 使 backend 写入 `stopped` 后仍
  需要显式 kill-and-wait fallback；这只证明受支持的 custom-menu/Cmd-Q path，
  不启用 update installation，也不把结论扩大到 external termination。
- 2026-08-17 Tauri P1 transport/container 修复：私有 Python Host RPC request
  现在使用显式 no-proxy loopback transport，因此配置的 `HTTP_PROXY` 无法接收
  bearer token。development state-root containment 现在将完整 macOS `.app`
  bundle，而非仅 `Contents/Resources`，视为 protected；`Contents` sibling 的
  state path 也会被拒绝。聚焦 Host RPC 与 Rust lifecycle contract 通过；这仍是
  源码层安全修复，不是 product-process、updater、installer 或 platform-release
  结果。
- 2026-08-17 Tauri P1 lifecycle/provenance 修复：`update_install` 当时会刻意
  消费所有 candidate 并返回 unavailable，直到具备完整 recovery/relaunch
  coordinator，以避免更新进行到一半就下载、停止 monitor、安装或重启。tray Quit
  现在请求既有结构化 `keep_monitor` shutdown 并等待 owned backend；其 direct
  child kill 原本是有界 timeout/error fallback，现已由上述后续修复用于每次
  application exit。移除了 dormant monitor-stop/install response fragment，
  以免 Rust host 暗示可执行 coordinator。development assembly 将 dirty
  allowlisted input 记录为 `<HEAD>+dirty`，development state 现在要求显式、
  已存在且与 bundle 双向不相交的 canonical root。锁定的 Rust formatting、16 项
  library test、6 项 lifecycle integration test、desktop binary check、version
  sync、聚焦 Python contract、`compileall` 与 diff whitespace check 均通过，且
  Rust 无 warning。脱敏 candidate scan 仅发现 ignored dependency build metadata
  和已记录的 deterministic ledger-fixture false-positive 类别；tracked/non-ignored
  source 不含本机 identity、credential、business output、runtime 或 release
  artifact。这不是 product-process、installer、signed-update、native-panel 或
  platform release-smoke 结果。
- 对齐 public-history execution record 与已准备的 sanitized-root Tauri
  development line，同时保留 no-Tag/no-Release/no-Pages 边界。
- 2026-08-17 Tauri development application L8-S/L9：新增确定性的
  development-only assembler，用其 staging allowlisted core、schema-3 host
  manifest 和显式 virtual-environment launcher，并将 raw manifest 和 launcher 的
  SHA-256 值绑定进 host build。macOS arm64 development `InvoiceHub.app` 曾构建
  一次，并以 isolated development state root 进行一次 smoke test：owned backend
  精确绑定 `127.0.0.1:8766`，health 与 background startup 达到 ready，homepage
  和 static asset 已加载，`desktop_available=true` 且为默认 desktop surface。随后
  一次 external AppleScript quit 释放 process、port 和 PID，却绕过 structured
  shutdown 并留下 stale server state，因此撤回该不受支持 exit 子结论。P1-Q 随后
  以 clean commit `399b20c` 重建并使用真实 Cmd-Q，只建立受支持的 structured-exit
  path。该 app 是本地 ignored development artifact，未触碰真实用户的
  Application Support state。development profile 禁用 updater delegation，拒绝
  release/relative state-root override。最初的 macOS tray initialization failure
  可追溯到 16-bit RGBA icon；图标现为 8-bit RGBA，且 IHDR-focused regression
  保护该机制。这不是 DMG、NSIS、Developer ID、notarization、Feed、Release、
  真实 updater、native-panel、browser/tray 或 Windows smoke 证据。
- 2026-08-16 Tauri release-input L7：完成只读 readiness audit。source 刻意
  禁用 Tauri bundling，且没有用于 schema-2 desktop host manifest 及其 compile-time
  SHA-256 的确定性 generator 或 stager；既有 Windows portable 和 legacy
  Swift/macOS packager 不能提供 Tauri NSIS 或 DMG/update-archive input。audit 还
  发现当前 static manifest schema 无法安全保存 per-user config/runtime path。
  release assembly 保持阻断；L8 在实现前被记录，以便在任何 generator 出现前定义
  dynamic state-layout 与 manifest-path contract。没有创建 product process、bundle、
  signing、notarization、upload、publication 或 Feed。
- 2026-08-16 Tauri updater L6-RRRRR：让存在竞争的 hosted update check 在
  `append_event` 前返回其只读 busy result，因此不会阻塞在 SQLite event write。
  增加该 blocked-event path 和 private RPC exception 后释放 install lock 的代表性
  contract。目标 isolated Python contract 在将 deprecation 视为 error 时通过 45 项，
  就 event-write 和 exception-release 范围取代 L6-RRRR 的 44 项结果。未运行 Rust、
  product process、update、package、signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRRR：修正 hosted-Tauri update check 的范围。当
  Tauri marker 和 private Host RPC 都配置时，API、settings 和 background check
  使用严格 fresh-Feed/candidate preflight；只有 non-Tauri/non-host check 保留普通
  cache/ETag path。install lock contention 现在立即失败，不消费 approval 也不发送
  第二次 Host RPC。目标 isolated Python contract 在将 deprecation 视为 error 时
  通过 44 项，取代 L6-RRR 的 42 项结果，但其 event-write 和 exception-release
  范围又已被 L6-RRRRR 取代。未运行 Rust、product process、update、package、
  signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRR（已取代）：将普通 update check 保持在 host
  lifecycle lock 之外；存在竞争的 Tauri host approval 立即返回非持久 busy result，
  不进行 metadata/candidate 工作，也不清除既有 approval。已获得锁的 host path
  仍通过显式 `try/finally` release 串行化 strict metadata、candidate 与 one-shot
  install。该项被 L6-RRRR 取代，因为其 42 项结果未建立更严格的 hosted-Tauri
  public-check 范围；未运行 Rust、product process、update、package、signing 或
  platform smoke test。
- 2026-08-16 Tauri updater L6-RR：让 strict host-approval Feed request 显式发送
  `Cache-Control: no-cache`，同时继续省略 ETag 并拒绝 `304`；non-host public
  update check 保留原有 cache/ETag header。明确并锁定独立的四项 picker 与两项
  updater Host RPC command surface。目标 isolated Python contract 在将 deprecation
  视为 error 时通过 40 项；未运行 Rust、product process、update、package、signing
  或 platform smoke test。
- 2026-08-16 Tauri updater L6-R：要求 host-install approval path 重新验证新鲜的
  allowlisted Feed `200` body，不使用 cache、ETag 或 `304` reuse，同时保持 non-host
  public check caching。在五分钟后由 bounded listener loop 主动清扫 one-shot host
  candidate，并以 generation-check 删除，使旧 expiry sweep 不能清除新 slot。修正
  当前文档，只描述 token 从 host 交给其直接启动的 Python backend，随后在 startup
  capture 并清理 descendant-environment。isolated Python selection 通过 31 项，
  Rust 1.85 offline contract 通过 13 项 library 加 5 项 lifecycle test；未运行
  product process、`8766` bind、update/download、package、signing 或 platform
  smoke test。
- 2026-08-16 Tauri updater L6：将 raw desktop bundle manifest 绑定到未来
  staged-manifest packager 注入的 compile-time SHA-256，使 source checkout 以
  exit-78 fail-closed。新增 host-delegated `update_check` 和 one-shot
  `update_install` command，带有五分钟 candidate bound、allowlisted
  Feed/version-match approval gate、empty-body HTTP install API 与脱敏的 503
  failure。installation 现具有固定顺序：download 加 Minisign verification、
  monitor stop 与 independent recheck，然后 install/restart。controlled Rust
  contract 与 isolated FastAPI TestClient contract 通过；未运行 product process、
  real update、bundle、signing 或 platform smoke。
- 2026-08-16 Tauri 2 lifecycle 与 startup-surface 边界：新增 fixed-port backend
  ownership、child identity/manifest/OpenAPI-method check、HMAC-SHA256
  challenge-response proof 和四枚举 private native-picker RPC。完成 owned-backend
  handshake 后，host 严格读取持久化的 `desktop|browser` preference：desktop 创建
  zero-permission WebView，browser 以 host-only pinned opener 打开 fixed origin，
  single-instance/tray open 重新打开该 selected surface，而 desktop close 只隐藏
  window、不停止 monitor。缺失 manifest 的 checkout 会在 Tauri startup 前以
  status 78 退出；host credential 从 child environment 移除，bounded liveness
  watcher 撤销 RPC authorization。host 在读取 preference 后重复 ownership proof；
  picker bridge 保留 Rust 的 120-second dialog 与 Python 的 125-second budget，
  并将 private failure 映射为脱敏 HTTP 503。isolated `cargo check`/`cargo test` 和
  聚焦 Python static contract 通过。上方另行记录后续 L6 isolated TestClient
  endpoint contract；两项记录都不代表 Tauri/FastAPI product service、installer、
  signing、native panel、Windows BAT 或 platform smoke test。
- 2026-08-16 Tauri 2 foundation：新增 public execution plan、single-source
  version synchronizer、pinned pnpm Tauri dependency、fixed-localhost host
  scaffold 以及不安装依赖的 Windows/macOS doctor/bootstrap entry point。diagnostic
  从请求的 project root 运行，阻止 Rustup/Corepack auto-download，并在 Windows
  interpreter、MSVC 或 SDK prerequisite 缺失时 fail closed。一个经过 checksum
  verification 的 isolated Rust 1.85.0 environment 现在锁定精确 Tauri crate，
  生成经审查、MSRV-compatible 的 `Cargo.lock`，并通过聚焦 `cargo check`/fixed-origin
  Rust test；普通 user environment 不变。lifecycle、Host RPC、updater、packaging 和
  platform smoke test 仍明确未实现。
- 修正 interface-flow release boundary，使其记录已完成的 public transition，同时
  保留禁止复用 retired private asset 的约束。
- 将 Windows CI 的 release-version argument 从 retired `0.2.0-beta.1` literal
  改为读取 `version.py`，使 source-identity gate 与 public release configuration
  对齐。
- 2026-08-14 public repository transition：在新的 public repository 发布已审计的
  sanitized root；只在 owner-controlled private archive 保留已退休 original graph，
  并启用 public-repository security 与 contribution governance。未复用任何 retired
  package、tag、receipt、Release asset 或 update Feed。
- 准备 sanitized public root：将历史 business fixture 替换为明确的 synthetic data，
  retire pre-publication release evidence，并新增 all-ref 和 hosting verification
  gate。
- 修正 alpha-channel update-feed prerelease validation，并同步 local-candidate
  publication gate 和 Windows source-development guidance。

## 公开基线 - 2026-08-14

- public repository 从经过净化的 source snapshot 开始。较早的 private development
  history、validation narrative 与 release artifact 有意不属于 public Git graph。
- 下一条 development line 是 `0.3.0-alpha.1`，它引入 Tauri 2 desktop host，同时
  保留 Python、FastAPI、Web 与 monitor core。
- 本仓库不发布任何 pre-publication binary 或 tag。未来 public binary 将使用新
  version 和全新、经过审计的 release evidence。

## 兼容范围

- invoice extraction、projection、independent monitor、localhost API 与既有 Web UI
  仍是共享 product core。
- 第一版 Tauri release 面向 Windows 10/11 x64 NSIS 与 macOS 13+ arm64
  DMG/update archive；其他 desktop variant 不在范围内。
