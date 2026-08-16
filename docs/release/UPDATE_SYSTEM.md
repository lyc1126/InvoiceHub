# 更新体系开发说明

## 当前状态

公开仓库尚未发布二进制或更新 Feed。退休的预公开更新地址、包和 Tag 不兼容新的脱敏 Git 图，不能被迁移、重定向或作为升级来源。

`v0.3` 才引入公开更新体系：安装包只放 GitHub Releases，同仓库 GitHub Pages 提供 Feed。Tauri L6 现只保留代码级 host 检查/preflight 边界；在完整 recovery/relaunch coordinator 出现前，`update_install` 会清除候选并返回不可用，绝不下载、停止 monitor、安装或重启。L9 已构建并隔离烟测一个 schema-3 macOS arm64 development `.app`；该 profile 明确禁用 updater delegation，因而该 app 没有形成真实更新、DMG/NSIS、签名资产或平台更新烟测。不得把现有检查接口、development app、该源码边界或 Swift/Sparkle 参考代码描述为已完成的发行更新器。

## 固定边界

- `GET /api/v1/about` 只读本地身份，不联网。
- 只有用户触发的 `POST /api/v1/update/check` 或显式启用的延迟检查可以访问固定 HTTPS Feed。
- Feed URL 和允许主机不能由用户配置覆盖。检查必须限制 DNS、连接、重定向、头、正文和总时限，并保留最后一次有效缓存。
- Host RPC token 只由 host 传给其直接启动的 Python backend；backend 启动时捕获 token 并从 descendant 环境清除，token 绝不进入网页、Tauri command/event、API 响应或日志。
- `AppState` 在同一进程同时具备 Tauri host marker 和已配置 private Host RPC 时，把 API、设置页和后台 timer 对 `check_for_updates` 的调用都当作 delegated-install preflight：以非阻塞 `_host_update_lock` 串行化 allowlisted Feed metadata gate、host `update_check` 和安装。只有非 Tauri/非 host 进程的公开 `/api/v1/update/check` 保留 `UpdateService.check` 的 cache/ETag/busy 语义。host 检查锁竞争时必须立即返回不持久化 busy 结果，不访问 Feed/host candidate，也不得清除现有 approval；install 锁竞争则必须立即以脱敏 `HostRpcError` 失败，不消费 approval 或发送第二次 private RPC。取得锁后，Tauri host approval 必须在同一 session 取得并重新验证一个显式携带 `Cache-Control: no-cache`、不带 `If-None-Match` 的新 `200` Feed body；持久化缓存、ETag、`304`、离线或错误结果均不得授予 approval。只有该新 Feed 的 `latest_version` 与 host candidate version 完全一致，才授予进程内、一次性的 approval。Tauri updater builder 的 metadata 请求固定 5 秒总时限，不得使用插件/reqwest 默认的无时限请求占住 operation mutex 和 Host RPC 连接槽。
- 竞争的 hosted check 必须在构造 busy 响应后直接返回，不得再调用 `append_event` 或触发 SQLite 事件写入；成功与非竞争检查仍保留既有 `updates.checked` 事件语义。
- `POST /api/v1/update/install` 只接受 `{}`，不接收版本、URL、路径或签名；host 候选最多保留 300 秒，由有界 listener loop 主动清除。当前 Rust install 路径在获得请求后清除候选并返回不可用，直到完整 recovery/relaunch coordinator 能保证失败后恢复此前 monitor/进程状态。该 coordinator 的固定顺序才是：取得 host 验证的候选 -> 下载并 Minisign 验签 -> 停止 monitor -> 独立复核 monitor 已停 -> 安装/重启。
- Host RPC 失败对 Web API 统一为不含 token、候选、URL 或 secret 的 `503 Update installation unavailable`。

## 发布元数据门槛

`latest.json` 和平台元数据必须由同一工具从实际资产生成。每次发布都校验版本、URL、长度、SHA-256、签名、source tag、package ID、core build、源码归档、SBOM 和收据的一致性。

公开 Feed finalizer 必须从实际安装器、签名证据、收据和由固定 release Tag 导出的源码归档重新计算身份。任一平台资产、Tag、源码归档、收据、版本、source commit、core build、package ID、长度、SHA 或签名发生冲突时，阻断 Feed。

## 验证范围

2026-08-16 的 L6-R 最小证据包含受控 Rust 1.85 离线 lifecycle contract（13 个 library、5 个 integration test），以及使用项目精确 runtime pins、`pytest==9.1.1`、`httpx2==2.9.1` 的隔离 Python 选择（31 个 tests，`DeprecationWarning` 视为错误）。后者证明的是进程内 API runtime/contract，不是 product FastAPI service 或 updater 运行。2026-08-17 的 L9 额外证明 development host 能在隔离 state root 启动 owned backend、加载页面并正常退出；development updater 被禁用，故 L9 不能成为下载、验签、monitor stop、安装、重启或 Feed 证据。精确命令、通过数量和未覆盖边界见 [Tauri 2 执行计划](TAURI2_EXECUTION_PLAN.md)。

每个平台最终 RC 只执行一次真实更新烟测，覆盖合法更新、篡改签名、用户取消、monitor 停止失败和成功重启。此前先运行命中 API、前端、Rust 和元数据代码的聚焦测试；完整回归每个 RC 最多一次。
