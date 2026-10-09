# Tauri 宿主、所有权与更新事务规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：src-tauri、desktop/browser、Host RPC、HMAC、startup gate、退出与 updater recovery。
- 代码与验收定位：src-tauri/src/、platform/host_rpc.py；平台架构、任务导航第 13—13.1 节。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-tauri) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

## 隔离开发运行态

- Tauri development profile 的 `INVOICE_HUB_DEV_STATE_ROOT` 必须显式提供、绝对、已存在并 canonicalize；它与 bundle/core 根及 macOS `.app` 容器必须双向不包含，`Contents` 下与 `Resources` 同级的目录同样拒绝，避免把可写 state 放入资源或让 bundle 落入 state。release profile、缺失、相对路径或 child 继承一律 fail closed。它只能让 host 定位其自身运行态，启动 Python backend 前必须清除，且开发烟测不得读取或写入真实 Application Support。

## 宿主生命周期与安装事务

- Tauri `src-tauri/` 只承担窗口、托盘、单实例、原生面板、打印、后端生命周期、随机令牌 Host RPC 与 updater。它只绑定 `127.0.0.1:8766`；未知占用必须明确失败，不能换端口或连接旧实例。Host RPC token 只允许由 host 传给其直接启动的 Python backend；backend 必须启动时捕获，并从 descendant 环境清除，绝不得返回网页、Tauri command/event、API 响应或日志，只接受固定 localhost origin 的枚举命令。携带该 token 的 Python loopback 请求必须显式禁用环境/系统代理并直连私有 listener。成功握手后必须先 arm 授权、再启动有界 child liveness watcher；watcher 只能撤销授权，不能在 child 已退出后重新授权。
- Tauri 后端 HTTP 响应必须按 Content-Length、无正文状态或合法 chunked 完成读取；不得因完整响应后的 TCP reset/未关闭而误判失败，也不得接受截断、歧义长度或重复身份头。错误只记录固定阶段与计数/系统错误，不含凭据或正文。浏览器兜底只允许成功握手后的窗口创建失败；用户确认后必须重新验证 child 与完整 ownership，不能绕过身份检查或自动覆盖保存偏好。
- Tauri updater metadata 请求必须设置 5 秒总时限，下载对象也必须继承有界时限。启用 updater 的 profile 只有在严格 owned 握手、tray/surface setup、startup gate 释放和 `BackendHost` 注册为 app state 全部完成后才可激活；development 或 updater-disabled internal-alpha 必须保持 inert。激活时只能从当前 `runtime_dir` 打开平台 marker store，并先执行一次 authenticated startup restore；恢复失败时保留 marker、保持 backend/WebUI 诊断可用、把 updater runtime 固定为失败态并拒绝后续检查/安装，不能为启动 updater 而提前释放 gate。
- `update_install` 只接受固定 enum 并原子消费一个 300 秒内的 host-owned 完整候选；版本、URL、签名或 artifact ID 均不得由 Web 传入或返回。安装必须采用两阶段提交：先启动一个被 execute/cancel latch 阻塞的私有 worker，再把精确 `{"ok":true}` 响应完整写入并 flush，最后才放行 download+内置签名验证 -> pause owned monitor -> install -> relaunch。响应写失败、worker spawn 失败或 latch 派发丢失必须进入不可重试的 `CommitLost`，且不得下载、写 marker、停止 monitor 或安装；commit reserved/executing 时拒绝并发 check/install 和普通 Quit。候选 identity 必须由 host 对 version/target/download URL/signature 的域分隔 SHA-256 transcript 生成，但不得公开或记录敏感 metadata。
- monitor recovery 的每个 Rust 请求和响应必须由 backend-private 32-byte ownership secret、fresh 64 位小写十六进制 challenge 和 HMAC-SHA256 transcript 双向绑定；secret 绝不得发送到固定端口、网页、API 或日志。Python 只为三条固定 bridge route 接受空 body 的完整认证头，拒绝篡改、不完整、非空 body 和进程内 replay；普通未认证页面 bridge 调用保持原语义。Rust 必须要求恰好一个响应 proof 并常量时间验证，同时保留 released owned lifecycle lease 在每次 marker/bridge 操作前后的 revalidation。
- monitor 暂停仍只接受 `running && ready` 的 owned monitor；已有/损坏/跨 scope marker、ownership loss 或任一失败都必须保留恢复义务并 fail closed。Unix marker 最终操作必须相对 opened-directory descriptor 使用 no-follow `openat`/atomic no-clobber `linkat`/`unlinkat`，整段 `load/publish/clear` 由目录 `flock` 串行化并在最终 link/unlink 后同步目录元数据；Windows 只能使用 handle-relative、no-reparse 操作。Windows updater `2.10.1` 的 `Update::install()` 会在 `on_before_exit` 后启动 installer 并直接退出，因此 callback 必须先调用受管 `BackendHost.shutdown_keep_monitor_or_terminate()`，无法确认终止时以非零状态退出且不得启动 installer。macOS 安装返回后必须先终止 backend、标记 relaunch prepared，再调用 `request_restart()`；对应 `ExitRequested` 只允许该已准备重启跳过重复 shutdown。普通托盘/Menu Quit 仍共用 `app.exit(0)` 和结构化 `keep_monitor` shutdown；API 错误或超时后必须显式 `kill + wait` 并确认 child 已退出，失败时阻止 host 退出。外部 AppleScript quit、Force Quit、SIGKILL、注销或断电不属于有序退出承诺。

## 桌面偏好与构建交接

- `v0.3` Tauri 新安装默认 `desktop`，已导入的显式偏好保持原值并在下次启动生效；browser 模式隐藏主窗口、只打开一次默认浏览器并常驻托盘。关闭浏览器或桌面窗口均不得停止独立 monitor。
- Tauri 页面结束 owned backend 后，watcher 必须原子撤销授权并请求 host 退出，释放托盘和单实例；主动 host shutdown 先撤销 ownership，避免重入。新启动方式需完整退出后生效，仅关窗隐藏或第二实例唤回不会切换模式。
- Desktop 打包必须同时核对当前前端工作区与已完成桌面功能分支，不得漏掉图标选择、打印弹窗偏好及已修复启动/监控行为。图标只接受内置枚举，默认白底 hi.；先确认 host 应用成功再保存，旧显式选择必须保留。

监控启停同时遵守 [监控规则](MONITORING.md)，成品输入和发布同时遵守 [发行规则](RELEASE.md)。

- 临时识别原生拖入按固定origin与首页路径校验，允许返回/皮肤查询参数；详情页和其它来源拒绝。启动OpenAPI门禁同步新增分页成本与删除计划/查询/确认方法。
