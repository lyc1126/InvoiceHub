# 分支整理、main 同步与双平台候选准备

更新时间：2026-09-08。此页记录本轮本地/远端引用整理、`main` 同步和 macOS 候选构建；精确远端状态仍以 Git 查询为准。

## 当前主线与保留引用

本轮双端发布源码固定为 `55a59870630198b7b8b055b85decfaa5bb360db6`，即包含 Desktop 整合及文档收尾的公开 main 基线。后续 README、截图和发布记录提交不改变已发布制品身份；当前 main 与文档分支的精确 tip 通过实时 Git 查询核对，不将本次构建 SHA 误当未来始终不变的主线值。

| 引用 | 当前用途 |
|---|---|
| `main` / `origin/main` | 当前公开开发基线，实时 tip 通过 Git 查询；alpha.2 Tag 的固定来源见下方 |
| `codex/macos-desktop-main-sync` | 本轮文档同步和 macOS 候选准备分支，从 alpha.2 公开主线基线开始；README 与发布记录按用户要求推送，主线更新遵循受保护分支流程 |
| `codex/desktop-latest` / `origin/codex/desktop-latest` | 已合并 Desktop 完整源码来源，当前保留来源提交 `f9eebca` |
| `codex/desktop-main-docs` / `origin/codex/desktop-main-docs` | 上一轮文档同步来源，当前保留提交 `bd31f58` |
| `origin/codex/app-icon-skins-windows`、`origin/codex/fix-desktop-search-filter` | 图标/皮肤和搜索/启动等独立来源线，继续保留回溯 |
| `codex/app-icon-windows`、`codex/tax-calculator-mvp`、`codex/tauri2-update-recovery` | 本地独立功能线，继续保留，不因本轮主线同步删除 |
| `origin/dependabot/*` | 自动依赖更新引用，继续保留 |
| `codex/alpha2-dual-platform-release-prep` | 旧的双平台 release-prep 工作树和分支仍保留；本轮不执行 `git worktree prune` |

本轮开工前的源码分支为 `codex/tauri2-alpha2-main-baseline@8d1c904`。其中税费计算器和 Mac 工作区的脏改动完整保存在 stash `df6451e0018c0de4db9734efecdae09da89a0eb0`；该 stash 只用于本机恢复，不属于公开源码、候选构建或 Release 输入。本地 `main` 已同步到 `origin/main@55a59870630198b7b8b055b85decfaa5bb360db6`，文档分支从该点继续维护 README、截图与发布记录。

## 本轮已清理的引用

以下六个本地分支已确认只指向已合并历史后使用普通 `git branch -d` 删除：

- `codex/tauri2-alpha2-main-baseline`
- `codex/tauri2-alpha2-packaging`
- `codex/tauri2-alpha2-postmerge-baseline`
- `codex/tauri2-alpha2-public-preview-fix`
- `codex/tauri2-alpha2-receipt-gate`
- `codex/tauri2-unified-desktop`

唯一旧 Mac alpha baseline 的远端引用也已删除，并用 `git ls-remote --heads origin` 复核不再可达。清理没有重写提交历史，没有删除仍有独立用途的功能线，也没有清理旧的 dirty release-prep worktree。

## 当前平台候选

本轮从精确 `main@55a59870630198b7b8b055b85decfaa5bb360db6` 构建了 macOS arm64 alpha.2 preview 候选：

- 候选目录：`dist/candidates/20260908-macos-main-55a5987/`
- 产物：`InvoiceHub-v0.3.0-alpha.2-macos-arm64-preview.app`、`.dmg` 和 `build-receipt.json`
- `source_commit`：`55a59870630198b7b8b055b85decfaa5bb360db6`
- `core_build_id`：`c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`
- DMG：`109535179` bytes，SHA-256 `21715661a3bffa48e8afd0034a81eb975758280f3a6ed6d2356d982ec5607298`
- 模式：public-preview ad-hoc、未公证、host updater disabled；finalized receipt verifier 已通过

包内源码/web/website 与精确 Git 源码逐字节一致，build/package/runtime identity、锁、Python 3.14.6 导入探针和 App/DMG 签名通过。隔离 HOME smoke 尚未通过；所有者已明确接受这一缺口并授权发布预览。实际默认配置验收与离线检查分别记录，不冒称隔离烟测、Developer ID 或公证已通过。

本轮已收到与 Mac 同源的 Windows x64 portable 候选及其 SHA sidecar、build receipt。receipt 记录 `source_commit=55a59870630198b7b8b055b85decfaa5bb360db6`、`core_build_id=c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`、ZIP 大小 `58040173` bytes、SHA-256 `f7c03a502d06d19faa61ee5f9ed859c4da3f57c6789f52014dec3fd4005a6ff3`，类型为 unsigned portable，`updater_enabled=false`。Windows 完整包由用户说明已验证后交付；本机独立静态验包和收据/实际 ZIP SHA-256 核对通过，不把本机检查描述为 Windows 真机运行验收。后续双平台候选使用同一 source/core 身份闭合。

`v0.3.0-alpha.2` Tag 已按所有者确认，从旧提交调整到本轮双端共同源码；注释 Tag 对象为 `ffdfa9361115a4948f7592ec9a1b2c2cb88c2c52`。[公开 Pre-release](https://github.com/lyc1126/InvoiceHub/releases/tag/v0.3.0-alpha.2) 已发布 8 项资源；服务器大小和 SHA-256 均匹配本地清单，8 项公开资源重下载复验也全部一致。本次 Tag 发布操作未改动 main、其它 Tag 或更新 Feed；README 文档随后通过独立提交更新主线。

## 提交与验收边界

本轮只回填公开文档和分支状态，不修改发票、税费、Mac 壳、Windows 包装或其它独立功能代码；本轮已按授权发布 Release 和更新该 Tag；文档与截图随后按用户要求更新 GitHub README，不创建更新 Feed，也不把 stash、用户配置、运行态、源发票、投影或 ignored 候选目录纳入公开输入。

源码快照导出曾被 `tests/test_tauri_windows_portable.py` 中既有的合成负向 secret 值命中扫描而失败；本轮没有绕过或放宽该扫描规则。Mac 包内源码与 runtime 离线核验已通过，隔离 HOME smoke 尚未通过，Mac smoke 未得到属于隔离 HOME 的 health；其后观察到构建身份正确且后台 ready 的实例，却使用真实 Application Support，不能计入隔离烟测通过；Windows 仅保留用户交付的真机证据和本机静态验包边界。

## 本轮交付目录和剩余动作

双端已发布资源已集中到 ignored 的 `dist/candidates/20260908-dual-platform-55a5987/`，包含 Windows ZIP、两端 receipt/校验和、Windows 包内原始 SBOM 与 Mac 旁置 Python SBOM；`release-plan.json` 记录所有者授权及实际发布状态，附有发布说明。Mac 原始 App、DMG、运行时文件哈希表和离线核验报告保留在上面的 Mac 候选目录，供复验与回退，不作为源码提交。

用户已确认完成系统首次打开；`spctl` 对 ad-hoc 签名的拒绝不能单独证明当前 App 不能运行。正式自动化烟测未得到隔离 HOME 的 health。清理旧实例后的另一样本曾观察到正确新构建的 ready 后端，但运行于真实 Application Support，不能计入隔离烟测通过，也不能声称全部检查未触碰真实运行态。最小无业务 App 的同参数 LaunchServices 实验正确输出隔离 HOME，因此不据此修改业务代码或删除 quarantine。

用户首次打开已完成。当前默认配置的启动、页面和 monitor 启停已复核；隔离 HOME 自动化烟测仍需另行修复/复验，不与当前配置验收混为一谈。旧 Tag 指向和预览验收范围已经所有者明确确认，发布说明持续披露未覆盖项。Windows 成品已同源，不需要因本轮纯文档或验收记录变化重打。源码导出器的固定合成负向夹具误报已逐文件复核，但生产导出器仍报告失败，不能将人工审计冒称该自动门禁通过。未覆盖本轮原生目录选择、打印、浏览器/托盘交互、正式 Windows BAT、公证和 updater。

当前运行验收补充：保留的新候选 App 使用实际默认空目录，health/background ready、原生首页渲染、两种首页资源路径及 monitor start-ready-stop 均已复核，monitor 恢复原 false，新 App 保持运行。`current-macos-acceptance.json` 只记录脱敏验收摘要；它不替代未通过的隔离 HOME 自动化 smoke。
