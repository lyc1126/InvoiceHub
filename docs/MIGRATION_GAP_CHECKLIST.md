# 迁移与公开缺口清单

更新时间：2026-08-18

## 公开历史净化

- [x] 仓库所有者已授权替换公开历史、删除旧远端分支和 Tag，并保留 owner-only 私有备份。
- [x] 选择单一脱敏根提交，而非逐提交文本替换，避免保留可关联的验证叙述和身份元数据。
- [x] 规定移除真实本机路径、私有主体/项目/人员标识、真实业务验证材料、容器元数据、历史 Git 身份与真实凭据。
- [x] 将所有测试夹具确认或替换为明确的合成数据。
- [x] 对候选源树完成一次文本、二进制容器和工作簿属性审计。
- [x] 创建中性身份的根提交，并对所有保留对象完成一次 gitleaks 与业务数据分类审计。
- [x] 用托管 API 核对 heads、tags、PR refs、Release/asset、LFS 与可见 fork/cache 状态；新公开仓库只包含脱敏根及其后代，原始图保留在 private archive。

执行约束见 [历史净化执行记录](release/HISTORY_SANITIZATION_EXECUTION.md)。旧私有包和旧 Tag 绝不进入新的公开图或 Release。

## 已保留的共享核心

- [x] `v1 localhost`、单活动 `TargetProfile`、文件真值与 SQLite 运行态边界。
- [x] PDF/OFD/XML 提取、金额防污染、两维分类、同票纠偏、普通汇总与成本投影。
- [x] 独立 monitor、后台 startup sync、事件合并、周期兜底、手改保护与诊断日志。
- [x] 目录草稿、SSE 断线恢复、真实表格/TSV、预览、批量打印、皮肤安全边界和结构化关闭。
- [x] 做账 W8/W9 的严格本地状态、预览/apply、服务端执行校验、批次 manifest 和 dry-run 边界。
- [x] 现有 macOS SwiftUI/WKWebView 壳仅作为共享后端与原生桥接的参考实现。

## `v0.3.0-alpha.1` Tauri 2 缺口

- [x] 建立 `src-tauri/` foundation、固定 `127.0.0.1:8766` 合同和由 `version.py` 派生的 Cargo/Tauri/npm 产品身份；host 已具备托盘、browser 启动路径、单实例恢复、close-to-hide 和 L6 host 委托 updater 边界。裸源码 checkout 继续在缺少编译绑定 manifest 时以状态 `78` 退出；development assembler 已生成并构建一个本地 arm64 `.app`，但不构成原生面板、打印、发布或平台验收声明。
- [x] 锁定 pnpm 与 Tauri JavaScript 依赖，并提供不会自动安装 Rust、证书、Xcode 或 Visual Studio 的 Windows/macOS `doctor/bootstrap`。
- [x] 在受控 Rust/Cargo `1.85.0` 环境中解析精确直接 Tauri crate、生成并审查 MSRV-compatible `src-tauri/Cargo.lock`，并通过最小 Rust compile/test；这只允许开始后续 host 生命周期实现，不等于已实现或发布。
- [x] 实现 `127.0.0.1:8766` 严格启动/握手：未知占用失败、child PID/build/package identity/OpenAPI 方法复核、HMAC challenge-response 归属证明，以及 manifest 原始字节 SHA-256 必须匹配编译期注入值的状态 `78` fail-closed。schema-3 development manifest 与显式 venv launcher 已被组装并编译绑定；一次隔离启动验证了 owned backend、health/background ready 与首页，退出机制由下方独立 P1-Q 样本限定，不扩大为 release bundle 或平台发布证据。
- [x] 保持 `startup_surface=desktop|browser` 语义：Tauri child 的缺省偏好为 desktop，既有有效显式偏好保持原值；严格 handshake 后 Rust 才选择 WebView 或固定 origin 的 host-only browser opener，托盘/第二实例重开同一 surface。L9 已验证 development `.app` 的 `desktop_available=true` 与默认 desktop；Windows 便携版仍拒绝新增 desktop 选择，真实 browser、tray、单实例和原生面板仍未验收。
- [x] 以不返回网页的随机 token 限制 Host RPC，picker 面只开放四种 picker 枚举与精确 localhost origin，更新面独立地只开放 `update_check/update_install`；host 只把 token/secret 传给其直接启动的 backend，backend 启动时捕获并从 descendant 环境清除，Python bearer 请求显式禁用环境代理，WebView capability 为空，token 不进入 Tauri command/event、API 响应或日志；授权先 arm 再由有界 liveness watcher 在 child exit 后撤销；尚未实测原生面板。
- [x] 保持 `POST /api/v1/update/check` 兼容：同一进程具备 Tauri host marker 和 private RPC 时，API、设置页和后台检查都进入 strict host preflight；只有非 Tauri/非 host 检查不获取 host lifecycle 锁并保留 cache/ETag/busy 语义。host approval 只以非阻塞方式获取该锁，竞争时返回不持久化 busy 结果且不触发 metadata/candidate 或清除既有 approval；install 锁竞争立即失败且不消费 approval 或发起第二次 private RPC。获得锁后，AppState 只在同一 session 内取得显式携带 `Cache-Control: no-cache`、不带 ETag 的 fresh allowlisted Feed `200` body、并与 host candidate version 完全一致时授予一次性内存 approval，缓存、ETag、`304`、离线或错误不可授权。host candidate 最多 300 秒，由 listener 主动清除；在 recovery/relaunch coordinator 完整实现前，`update_install` 清除候选后直接 fail closed，不下载、不停 monitor、不安装或重启。隔离 Rust/FastAPI TestClient 合同覆盖此源码边界；真实下载、更新、bundle、签名、重启和平台烟测仍未执行。
- [x] hosted host-lock 竞争的 busy 返回不写 `updates.checked`：该路径不调用 `append_event`，因此不会把“立即/非持久化”响应重新变成 SQLite 写入等待；成功和非竞争检查的事件语义不变。
- [x] L8-S/L9：development profile 仅接受显式、已存在、绝对且 canonicalize 后与 bundle/core 及完整 macOS `.app` 容器双向不包含的 `INVOICE_HUB_DEV_STATE_ROOT`，`Contents` sibling 同样 fail-closed，release、缺失或相对覆盖 fail-closed，变量不传给 Python child；在隔离 state root 构建并启动一次 unsigned/ad-hoc macOS arm64 development `.app`。固定端口、health/background、首页/静态资源和 desktop 默认值通过；真实 Application Support 未被触碰。16-bit RGBA 图标导致的 tray 初始化失败已改为 8-bit RGBA，并有 IHDR 回归。
- [x] P1-Q：clean-commit 外部 AppleScript quit 绕过 shutdown POST 并留下 `server_state=ready`，因此该外部路径仍不作有序退出承诺。修复后的自定义 macOS 应用菜单 Quit/Cmd-Q 与 tray 共用 `app.exit(0)` 且禁止 predefined Quit；隔离的 clean-commit 真实 Cmd-Q 样本已确认 shutdown POST 200、stopped state、monitor 未启动、host/backend/PID/端口清理，SSE 未及时退出时由显式 `kill + wait` 兜底。该结果允许推送开发分支并创建 Draft PR，但不覆盖 tray 点击、Force Quit、SIGKILL 或平台发布。
- [x] P1 setup cleanup：BackendHost 启动后若 tray、desktop window 或 browser surface 初始化失败，host 在返回原始 setup error 前调用既有 keep-monitor shutdown，并在失败/超时时 kill+wait owned child；如果终止尚不可确认则 setup 保持阻塞并重试，child mutex 或 `try_wait` 错误也不算退出，绝不返回后依赖 Drop。只有成功初始化后才把 backend/surface 注册到 app state。该路径不依赖 `ExitRequested`，且不改变 updater fail-closed 语义。

## 发布缺口

- [ ] Windows 10/11 x64 NSIS 安装器与新的公开构建/签名证据。
- [ ] macOS 13+ arm64 DMG、更新归档、Developer ID、Hardened Runtime、公证、staple、quarantine 与升级证据。
- [ ] 同仓库 GitHub Pages 更新 Feed、真实资产签名、源码归档、SBOM、收据与最终 provenance 闭环。
- [ ] 每个平台最终 RC 一次安装、启动、目录选择、托盘、合法/篡改更新与 monitor 停止烟测。

## 不在当前范围

- [ ] Windows ARM64、MSI、Intel/Universal macOS、App Store、云端、多用户、增量更新与正式本地 OCR 包。
- [ ] 真实业务做账迁移、审批、导出、账套或外部系统写入。它们需要独立事实、真实环境和当回合用户授权。
