# Mac / Windows 开发与验收分工

## 当前公开基线

脱敏根提交已发布到独立的公开仓库。候选树、保留 Git 对象、聚焦回归和托管面验证已通过；退休的预公开包、验证记录和本机验证目录只留在私有归档中，不能复用。`codex/tauri2-unified-desktop` 已建立并只包含不可运行的 foundation；当前仍未创建公开 Tag、Release 或 Feed。

## 共享与平台边界

- 共享：Python、FastAPI、Web、`/api/v1`、TargetProfile、发票提取、投影、独立 monitor、做账协议和版本真值。
- Windows：当前源码入口是根 BAT 与 PowerShell；`v0.3` 首版目标为 Windows 10/11 x64 NSIS 安装器。
- macOS：现有 SwiftUI/WKWebView 壳仅作开发与边界参考；`v0.3` 首版目标为 macOS 13+ arm64 DMG 与更新归档。
- 任一平台的源码、依赖锁、runtime、启动器和成品必须互斥。共享源码不意味着可混入另一平台成品。

Windows 源码开发入口：

```powershell
.\启动一站式发票汇总系统.bat -Development
```

该命令只验证当前 checkout 的源码开发入口，不代表正式安装包或便携包已验收。

## Windows 新 RC

1. 从精确 clean `RC_SHA` 建立隔离环境，核对版本、依赖锁、源码快照和 SBOM。
2. 按平台锁准备 runtime，组装两次并核对 SHA；断网重装后重复该验证。
3. 静态验包必须拒绝本机配置、业务数据、运行态、日志、缓存、秘密和 macOS 内容。
4. 最终 RC 在 Windows 10/11 x64 执行一次安装、启动、目录选择、托盘、更新和停止 monitor 烟测。

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
