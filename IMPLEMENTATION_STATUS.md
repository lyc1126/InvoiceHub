# IMPLEMENTATION_STATUS

更新时间：2026-08-14

## 公开基线

- 本仓库已将单一、脱敏的根提交发布为公开 `main`。旧的私有提交图、验证记录、二进制包和 Tag 只保留在 owner-only 私有归档中，不属于公开历史，也不会作为 Release 资产上传。
- 首个公开开发版本为 `0.3.0-alpha.1`；任何公开二进制都必须从脱敏图上的新版本、新 Tag 和新发布证据构建。
- 历史净化的范围、私有备份和已完成的公开门槛见 [执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。公开仓库已启用 DCO、Dependabot、Secret Scanning、Push Protection 和私密漏洞报告；仍未创建 Release、更新 Feed 或 Tauri 开发分支。

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
- 更新签名验证、下载、安装前 monitor 停止与重启由 host 管理；停止失败或用户取消必须保持现有运行状态。

## 发布与验证规则

- `src/invoice_hub/version.py` 是版本、协议、通道、公开链接和 package ID 的单一真值。Cargo、Tauri 与 npm 版本只能由同步/校验脚本派生。
- 每项实验必须先记录假设、会改变的决策、最小样本和停止条件。相同机制仅保留一个代表样本；每个 RC 最多一次完整回归。
- 公开前已运行一次候选内容审计和一次保留 refs 全量审计。后续文档或仓库设置变更不刷新该审计；真实命中才隔离或替换，并按受影响机制复核。
- 每个平台最终 RC 只做一次安装、启动、目录选择、托盘和更新烟测；修复后只重跑受影响类别。

## 尚未完成

- Tauri 2 源码、版本同步、doctor/bootstrap、Host RPC、原生更新安装及其五个决策场景尚未实现。
- 公开 Release、GitHub Pages Feed、正式 Windows 签名、macOS Developer ID/公证和最终用户安装烟测均尚未进行。
- 真实业务做账迁移、审批、导出和外部账套操作必须在用户当回合明确授权后另行执行。

## 验证范围说明

本文只描述当前源码能力与后续范围，不代表对任何历史二进制、真实目录、真实发票、正式 Windows BAT、系统原生面板或正式安装包作出新的验证声明。
