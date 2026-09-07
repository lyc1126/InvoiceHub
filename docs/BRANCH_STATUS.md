# 分支整理与 Desktop 整合

更新时间：2026-09-07。此页记录本次源码整合；精确远端状态仍以 Git 查询为准。

| 分支 | 当前用途 |
|---|---|
| `main` / `origin/main` | 稳定基线 `eb425bc`；本次不合并或改写 |
| `codex/desktop-latest` | 最新 Desktop 完整源码整合及后续维护入口，从上述稳定基线建立；本地提交已完成，网络阻断下尚未推送 |
| `codex/fix-desktop-search-filter` | 既有独立提交线；新版整合了其监控、搜索和启动修复，原提交继续保留 |
| `codex/simplify-windows-portable` | 早期 Windows 打包与验收提交；上游分支已删除，本地保留回溯 |
| `codex/windows-app-icon-integration`、`codex/about-links`、`codex/print-popup-permission` | 图标、关于链接和打印许可来源，保留独立历史，不作为最新版开发入口 |
| `codex/desktop-surface-lifecycle` | Desktop 生命周期修复来源，仍绑定本地源码工作树 |
| `codex/large-list-snapshot` | 最新已验 Desktop 的不可变构建输入，绑定 `runtime/desktop-integrated-source/` |

本地 `desktop-current-snapshot`、`desktop-current-snapshot-r2`、`desktop-integrated-snapshot`、`search-scope-snapshot` 及四个 `startup-diagnostics-snapshot*` 分支（均有 `codex/` 前缀）是中间构建快照，仅留本地回溯；其中已有工作树绑定的目录保持不动。它们不随本次推送到远端。

以下七个本地分支只指向稳定基线，没有独立提交；相关工作区内容由 `codex/desktop-latest` 完整收录，推送成功后删除这些冗余引用：

- `codex/default-ui-polish`
- `codex/desktop-current-package`
- `codex/fix-invoice-search-scope`
- `codex/fix-large-list-responsiveness`
- `codex/fix-source-bat-handshake`
- `codex/invoicehub-official-website`
- `codex/startup-conflict-diagnostics`

当前以上七个引用仍保留。整合提交 `5331187` 完成后，三次 HTTPS 推送遭遇 GitHub 443 连接超时或连接重置；尚无远端接收成功证据。恢复网络后执行 `git push -u origin codex/desktop-latest` 并核对远端 SHA，再删除上述无独立提交的本地引用。

远端图标、桌面搜索、alpha.2 基线与 Dependabot 分支保留；本次 fetch 仅清除服务器已删除分支的本地 tracking 引用，不删除现存远端分支或 Tag。

## 提交范围

整合源码、前端、两款皮肤适配、图标、官网、启动/冲突诊断、监控进度、搜索范围、单据分页与断点缓存，以及对应测试、打包脚本和文档。产品代码/资源对应已验 Desktop 构建快照 `8e723cf`，本次补充文档和分支记录，并修正官网测试的控制器提取边界。

本机配置、运行缓存、日志、源发票、生成投影、用户的 `website.rar` 和 ZIP 不进入 Git 提交。ZIP 的发布仍走 GitHub Releases 流程；本次只提交并推送源码，不创建 Release、Feed 或 PR。

## 验证与边界

此前最新 Desktop 已通过独立验包、148 份包内源码/资源比对、聚焦 Python/Node 回归、7,003 条合成浏览器场景，以及真实目录 6,688 文件加载/停止/恢复验证。当前整合再次核对暂存树与该构建输入，并检查提交内容和文档契约。

本轮 15 项文档契约、31 项前端/官网 Node 测试、Python compileall 和 Git diff 检查通过。产品代码/资源与构建快照一致，差异只有六份文档及一份官网测试；内容扫描仅命中两项已人工确认的固定合成负向测试值。本机审计脚本与测试临时目录保留在 ignored 的 `runtime/desktop-push-check/`，待推送核对和分支清理完成后可删除。

该记录不等于新的全仓测试、macOS 成品、签名安装器、updater、原生选择器或实体打印验收，也不改变既有 BAT 验证范围。回退可以切回稳定 `main`；旧 Desktop 解包仍可本地回退。
