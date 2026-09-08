# 分支整理与 Desktop 整合

更新时间：2026-09-08。此页记录本次源码整合；精确远端状态仍以 Git 查询为准。

| 分支 | 当前用途 |
|---|---|
| `main` / `origin/main` | PR #20 已合并；产品基线 `53544e3c96ba01906520637fae60cbc215b7808b`，后续纯文档提交不改变该产品代码基线 |
| `codex/desktop-latest` | 已合并的 Desktop 完整源码整合分支，保留来源记录；后续功能从当前 main 新建分支 |
| `codex/fix-desktop-search-filter` | 既有独立提交线；新版整合了其监控、搜索和启动修复，原提交继续保留 |
| `codex/simplify-windows-portable` | 早期 Windows 打包与验收提交；上游分支已删除，本地保留回溯 |
| `codex/windows-app-icon-integration`、`codex/about-links`、`codex/print-popup-permission` | 图标、关于链接和打印许可来源，保留独立历史，不作为最新版开发入口 |
| `codex/desktop-surface-lifecycle` | Desktop 生命周期修复来源，仍绑定本地源码工作树 |
| `codex/large-list-snapshot` | 最新已验 Desktop 的不可变构建输入，绑定 `runtime/desktop-integrated-source/` |

本地 `desktop-current-snapshot`、`desktop-current-snapshot-r2`、`desktop-integrated-snapshot`、`search-scope-snapshot` 及四个 `startup-diagnostics-snapshot*` 分支（均有 `codex/` 前缀）是中间构建快照，仅留本地回溯；其中已有工作树绑定的目录保持不动。它们不随本次推送到远端。

以下七个本地分支只指向稳定基线，没有独立提交；相关工作区内容由 `codex/desktop-latest` 完整收录，2026-09-08 推送成功并核对远端后，已删除这些冗余引用：

- `codex/default-ui-polish`
- `codex/desktop-current-package`
- `codex/fix-invoice-search-scope`
- `codex/fix-large-list-responsiveness`
- `codex/fix-source-bat-handshake`
- `codex/invoicehub-official-website`
- `codex/startup-conflict-diagnostics`

整合提交 `5331187` 及验证记录 `f35d314` 已于 2026-09-08 推送；删除七个引用前核对它们均指向当时稳定基线 `eb425bc` 且未绑定工作树，使用普通 `git branch -d` 删除。随后在同一整合分支修正两处测试版本断言、Windows 单据缓存发布重试及监控状态短锁，最终功能提交 `f9eebca` 的 push/PR 双平台 CI 和 DCO 全部通过，PR #20 已普通合并；保留独立历史和快照，不重写提交。

远端图标、桌面搜索、alpha.2 基线与 Dependabot 分支保留；本次 fetch 仅清除服务器已删除分支的本地 tracking 引用，不删除现存远端分支或 Tag。

## 提交范围

整合源码、前端、两款皮肤适配、图标、官网、启动/冲突诊断、监控进度、搜索范围、单据分页与断点缓存，以及对应测试、打包脚本和文档。已验 Desktop 快照 `8e723cf` 为整合来源；本次另有两项运行修复和测试/文档更新，不能将旧 ZIP 当作最终 main 的精确成品。

本机配置、运行缓存、日志、源发票、生成投影、用户的 `website.rar` 和 ZIP 不进入 Git 提交。ZIP 发布仍走独立 GitHub Releases 流程；本次只合并源码和文档，不创建 Release 或 Feed。

## 验证与边界

此前最新 Desktop 已通过独立验包、148 份包内源码/资源比对、聚焦 Python/Node 回归、7,003 条合成浏览器场景，以及真实目录 6,688 文件加载/停止/恢复验证。当前整合再次核对暂存树与该构建输入，并检查提交内容和文档契约。

整合时 15 项文档契约、31 项前端/官网 Node 测试、Python compileall 和 Git diff 检查通过。产品代码/资源与构建快照一致，差异只有六份文档及一份官网测试；内容扫描仅命中两项已人工确认的固定合成负向测试值。2026-09-08 只重试推送、清理分支引用并同步本文档，不重复产品测试或重打包。本机审计脚本与测试临时目录保留在 ignored 的 `runtime/desktop-push-check/` 供本次源码整合审计回溯，后续不再需要审计复现时可按该精确目录清理。

合并门禁已经覆盖完整 Windows/macOS Python 测试、编译、静态/发布契约及 macOS Swift 测试；不等于 macOS 成品、签名安装器、updater、原生选择器或实体打印验收，不改变既有 BAT 验证范围。源码回退使用 `git revert -m 1 53544e3c96ba01906520637fae60cbc215b7808b` 创建反向提交并走 PR；旧 Desktop 解包仍可本地回退。
