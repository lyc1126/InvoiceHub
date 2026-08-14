# 迁移与公开缺口清单

更新时间：2026-08-14

## 公开历史净化

- [x] 仓库所有者已授权替换公开历史、删除旧远端分支和 Tag，并保留 owner-only 私有备份。
- [x] 选择单一脱敏根提交，而非逐提交文本替换，避免保留可关联的验证叙述和身份元数据。
- [x] 规定移除真实本机路径、私有主体/项目/人员标识、真实业务验证材料、容器元数据、历史 Git 身份与真实凭据。
- [x] 将所有测试夹具确认或替换为明确的合成数据。
- [x] 对候选源树完成一次文本、二进制容器和工作簿属性审计。
- [x] 创建中性身份的根提交，并对所有保留对象完成一次 gitleaks 与业务数据分类审计。
- [ ] 用托管 API 核对 heads、tags、PR refs、Release/asset、LFS 与可见 fork/cache 状态；通过后才重写远端并转 public。

执行约束见 [历史净化执行记录](release/HISTORY_SANITIZATION_EXECUTION.md)。旧私有包和旧 Tag 绝不进入新的公开图或 Release。

## 已保留的共享核心

- [x] `v1 localhost`、单活动 `TargetProfile`、文件真值与 SQLite 运行态边界。
- [x] PDF/OFD/XML 提取、金额防污染、两维分类、同票纠偏、普通汇总与成本投影。
- [x] 独立 monitor、后台 startup sync、事件合并、周期兜底、手改保护与诊断日志。
- [x] 目录草稿、SSE 断线恢复、真实表格/TSV、预览、批量打印、皮肤安全边界和结构化关闭。
- [x] 做账 W8/W9 的严格本地状态、预览/apply、服务端执行校验、批次 manifest 和 dry-run 边界。
- [x] 现有 macOS SwiftUI/WKWebView 壳仅作为共享后端与原生桥接的参考实现。

## `v0.3.0-alpha.1` Tauri 2 缺口

- [ ] 建立 `src-tauri/`，只承载窗口、托盘、单实例、原生面板、打印、后端生命周期、Host RPC 与 updater。
- [ ] 实现 `127.0.0.1:8766` 的严格启动/握手；未知端口占用必须失败。
- [ ] 保持 `startup_surface=desktop|browser` 语义；新安装默认 desktop，既有显式偏好保持原值。
- [ ] 以不返回网页的随机 token 限制 Host RPC，只开放枚举命令与预期 localhost origin。
- [ ] 保持 `POST /api/v1/update/check` 兼容，新增 host 委托的安装接口；安装前可靠停止 monitor。
- [ ] 从 `version.py` 派生 Cargo、Tauri 和 npm 版本，锁定 Rust/Cargo/pnpm/Tauri，并提供不自动装证书或 IDE 的 doctor/bootstrap。

## 发布缺口

- [ ] Windows 10/11 x64 NSIS 安装器与新的公开构建/签名证据。
- [ ] macOS 13+ arm64 DMG、更新归档、Developer ID、Hardened Runtime、公证、staple、quarantine 与升级证据。
- [ ] 同仓库 GitHub Pages 更新 Feed、真实资产签名、源码归档、SBOM、收据与最终 provenance 闭环。
- [ ] 每个平台最终 RC 一次安装、启动、目录选择、托盘、合法/篡改更新与 monitor 停止烟测。

## 不在当前范围

- [ ] Windows ARM64、MSI、Intel/Universal macOS、App Store、云端、多用户、增量更新与正式本地 OCR 包。
- [ ] 真实业务做账迁移、审批、导出、账套或外部系统写入。它们需要独立事实、真实环境和当回合用户授权。
