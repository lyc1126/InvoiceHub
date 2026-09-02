# Mac / Windows 开发与验收分工

## 当前公开基线

脱敏根提交已发布到独立的公开仓库。候选树、保留 Git 对象、聚焦回归和托管面验证已通过；退休的预公开包、验证记录和本机验证目录只留在私有归档中，不能复用。`0.3.0-alpha.2` 已加入 Windows Tauri ZIP 源码链，但尚未创建公开 Tag、Release 或 Feed；macOS development/internal-alpha 产物仍只作历史边界证据。

## 共享与平台边界

- 共享：Python、FastAPI、Web、`/api/v1`、TargetProfile、发票提取、投影、独立 monitor、做账协议和版本真值。
- Windows：当前源码入口是根 BAT 与 PowerShell；alpha.2 交付目标为 Windows 10/11 x64 无签名 Tauri portable ZIP，不生成 MSI/NSIS。
- macOS：现有 SwiftUI/WKWebView 壳仅作开发与边界参考；`v0.3` 首版目标为 macOS 13+ arm64 DMG 与更新归档。
- 任一平台的源码、依赖锁、runtime、启动器和成品必须互斥。共享源码不意味着可混入另一平台成品。

Windows 源码开发入口：

```powershell
.\启动一站式发票汇总系统.bat -Development
```

该命令只验证当前 checkout 的源码开发入口，不代表正式安装包或便携包已验收。

Tauri macOS development `.app` 已有一次隔离启动与 Cmd-Q 退出证据：它使用 explicit venv launcher、schema-3 manifest 和仅 development profile 的外置 state root，固定绑定 `127.0.0.1:8766` 后完成 health/background、首页/静态资源和 desktop 默认值检查；clean-commit 样本的真实 Cmd-Q 触发 shutdown POST 并形成 stopped state，host/backend/PID/端口清理完成，SSE 未及时退出时由显式 `kill + wait` 兜底。外部 AppleScript quit 仍不属于这一可拦截路径。该样本不覆盖 native picker、browser/tray 点击、单实例、打印、updater 或任何 DMG/签名/公证项，也不改写真实 Application Support。

## Windows 便携包

alpha.2 Windows x64 便携 ZIP 是 Tauri host 的非安装交付，不生成 MSI/NSIS，也不原地替换目录。它只需要一台 Windows x64 主机执行：

1. 先运行 `tauri-doctor.ps1 --require-ready`；它必须看到 Rust `1.85.0` MSVC、Visual Studio C++ Build Tools/Windows SDK、Node/pnpm 与 Evergreen WebView2 Runtime。doctor 不安装 WebView2，缺失时由用户安装。
2. 从目标公开 tag 的 clean checkout 运行 `tauri-windows-portable.ps1 build`，并传入绝对锁定 Python 3.14.6 runtime 和 pnpm；它将 release manifest SHA-256 编译绑定到 raw x64 `InvoiceHub.exe`，生成 ZIP、SHA、receipt 与 SBOM。
3. 在相同 tag 的 clean checkout 运行 `tauri-windows-portable.ps1 handoff`，输出 `dist/handoff/v0.3.0-alpha.2/` 的产品 ZIP、SHA、receipt、SBOM、源码归档及 SHA、strict `latest.json` 和 Mac 上传说明。
4. 将 ZIP 解压到临时中文空格路径，隔离 `LOCALAPPDATA`，直接启动 `InvoiceHub.exe`；host 必须把 backend/config/runtime 与 WebView2 profile 一并收束在 `%LOCALAPPDATA%\\InvoiceHub`，其中 profile 为预创建的 `webview`。验证窗口、health/identity、固定端口冲突、单实例、目录选择、monitor（含 `running=true`、`ready=true`、`observer_active=true`）、tray Quit、进程清理和只读 Feed 检查。

release host 的 PE 必须是 GUI subsystem，且 runtime 下的 `server_stdout.log`、`server_stderr.log` 必须出现；不得以用户可见控制台承载 HTTP 诊断。

不要求双组装、断网重装或 PS7/PS5.1 双烟测；双组装 SHA 比对、离线重建和源码预门禁仍可显式执行。alpha.2 的 Feed 只能含一个真实 Windows ZIP、receipt 与源码身份；“检查更新/前往下载”只打开 GitHub prerelease，安装接口保持 fail-closed，不能停止 monitor、替换现有目录或伪造 macOS 资产。任何未执行的 Windows 真机行为必须如实标为未覆盖。

### 2026-09-01 source gate

运行时 shell-helper 裁剪、锁定 Rust 1.85 格式/测试、版本同步、聚焦发布契约、完整 Python 回归、`compileall`、PowerShell 解析和 diff whitespace 检查均已通过。独立 test Python 已离线重建其当前源码 `.pth` 绑定；未绑定且路径过长的 pytest 临时目录不构成验证证据。该主机的 Rust 1.85、MSVC/Windows SDK、Node/pnpm、锁文件和系统级 Evergreen WebView2 Runtime 均可用。doctor 曾因错误 Edge Update client ID 和三段版本限制把四段 `131.0.2903.86` runtime 误报缺失；修复并以 18 项 foundation 回归验证后，真实 `tauri-doctor --require-ready` 已放行。随后的 valid candidate 已通过静态验包和 owned backend handshake，但 desktop WebView 在 Tauri 隐式 profile 位置返回 Windows access denied；browser surface 可工作，因此问题被限定为 desktop profile。host 现显式创建并传入 `%LOCALAPPDATA%\\InvoiceHub\\webview`。后续 fresh candidate 已创建隔离桌面窗口，却在首次 monitor 启动时因 bridge/status 读取与 daemon 状态原子替换产生 `WinError 5` 而 fail closed；`MonitorState.read_status()` 现加入已有 TargetProfile 锁，12 项 monitor 回归通过。该源码修复仍须从 clean commit 重建 ZIP 后验证桌面窗口、picker、monitor、tray、Feed、Tag、Release 与 Pages。

## macOS 新 RC

1. 从同一 clean `RC_SHA` 构建内嵌 core 与 arm64 runtime，生成 manifest、SBOM 和源码归档。
2. 正式产物需要 Developer ID、Hardened Runtime、公证、staple、quarantine 与签名更新归档。
3. 严格握手只读取 health、静态页面和 OpenAPI；不得为兼容探测扫描真实业务目录。
4. 最终 RC 在 macOS 13+ arm64 执行一次安装、启动、原生目录选择、托盘、合法/篡改更新和 monitor 停止烟测。

## 共同规则

- 每项实验先记录假设、决策、最小样本和停止条件。
- 先跑命中变更面的测试；每个 RC 最多一次完整回归。
- 安装、升级和卸载不得复制真实发票、成本产物、日志、PID、SQLite、缓存或皮肤。
- 未执行的平台验收必须明确写为未覆盖，不能由另一平台的测试结果推断。
