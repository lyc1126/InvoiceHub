# Git 分支、worktree 和 fork 速查

本文按本仓库当前历史解释常用 Git 概念，方便之后判断“改了代码、提交了、推送了”分别处在哪一步。

## 公开基线与工作区边界

- 当前公开权威引用是完成验证后的脱敏根提交；精确远端 HEAD 仍以实时 `git ls-remote` 为准。
- 所有预公开提交、Tag 和二进制均不复用。历史净化已完成；Tauri 2 已在 `main`，后续功能分支从实时核验的稳定主线创建。
- 本次公开基线不保留任何旧分支、合并基线或发布身份。后续功能只在新的公开 `main` 上按普通分支和 PR 流程开发。
- 私有工作区、stash、本机配置、未跟踪资产和 ignored 运行态均不属于公开图、Tag、Release 或 Feed 输入。
- 本节只帮助理解当前工作流，不作为永久 Git 真值；分支和 commit 快照始终以 `AGENTS.md` 的“Git 与授权”和实时 `git status/log` 为准。
- 当前本机配置：`config/app.local.json` 可能显示为 modified，这是本机运行配置，默认不提交。
- 当前推荐开发方式：所有代码、接口、前端、解析、启动、成本、发布类功能改动先从 `main` 新建 `codex/<task-name>` 分支，再通过 GitHub Draft PR 验收。
- 当前回溯原则：未合并功能直接删除分支；已合并功能用 `git revert` 生成反向提交，不默认重写 `main` 历史。

操作前先读下方[强制 Git 操作规则](#git-rules)；本文示例不是推送、删除分支或合并的授权。

## 一句话区分

- 工作区：文件已经改了，但还没保存成 Git 历史点。
- 暂存区：准备进入下一次提交的文件清单。
- commit：本机历史里的一个保存点。
- push：把本机提交上传到 GitHub。
- branch：同一个仓库里的一条开发线。
- worktree：同一个仓库同时签出多个工作目录，适合并行做不同任务。
- fork：把别人 GitHub 上的仓库复制到自己账号下，适合参与外部项目。

## 什么时候用 branch

适合“同一个项目里做一条可合并的开发线”。

本项目常用命令：

```powershell
git switch main
git pull --ff-only origin main
git status --short --branch --ignored
git rev-parse --short HEAD
git switch -c codex/invoice-format-badge
git add AGENTS.md CHANGELOG.md docs/GIT_BRANCH_WORKTREE_FORK_GUIDE.md
git diff --cached --name-status
git diff --cached --check
git commit -m "Document branch rollback workflow"
```

不要使用 `git add .` 或 `git add -A`。本项目有本机配置、运行态、快捷方式和真实发票产物，提交范围必须用显式文件清单。

`main` 只保留已验收版本。用户可见功能、大功能和跨模块改动必须在 `codex/` 分支完成并推送到 GitHub Draft PR；满意后再合并。

`git push` 不是默认动作。只有用户明确说“推送”“上传到 GitHub”“更新 PR”或“创建 PR”时，才执行推送。

## 本项目推荐流程

1. 在 `main` 上确认基线：

```powershell
git switch main
git pull --ff-only origin main
git status --short --branch --ignored
git rev-parse --short HEAD
```

2. 从当前基线创建功能分支：

```powershell
git switch -c codex/<task-name>
```

3. 修改代码或文档后，只暂存本轮明确文件：

```powershell
git add <file1> <file2> <file3>
git diff --cached --name-status
git diff --cached --check
```

4. 按风险运行测试。常规代码合并前至少跑：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src tests
```

纯文档流程变更可以不跑业务测试，但最终说明未运行原因。

5. 提交并推送功能分支：

```powershell
git commit -m "Add branch rollback rules"
```

6. 用户明确要求上传或创建 PR 后，再推送功能分支：

```powershell
git push -u origin codex/<task-name>
```

7. 在 GitHub 创建 Draft PR。PR 里写清变更范围、测试结果、未覆盖项、敏感路径检查和回退方式。

## main 分支保护怎么做

在 GitHub 网页配置，避免本机工具或误操作直接把未验收内容推到 `main`。

路径：

```text
Repository -> Settings -> Branches -> Add branch protection rule
```

建议设置：

- `Branch name pattern` 填 `main`。
- 勾选 `Require a pull request before merging`，强制所有主线变更先经过 PR。
- 如果是单人仓库，可以先不强制 approval；如果希望更严格，开启 `Require approvals` 并设为 `1`。
- 勾选 `Dismiss stale pull request approvals when new commits are pushed`，避免旧审批覆盖新提交。
- 有 GitHub Actions CI 后，再勾选 `Require status checks to pass before merging`，并选择对应测试；当前没有 CI 时先不要启用必需检查，避免把自己锁住。
- 可选勾选 `Require conversation resolution before merging`，确保 PR 讨论都处理完再合并。
- 如果页面提供 `Do not allow bypassing the above settings`，建议勾选，避免管理员绕过规则直接改主线。
- 确认 `Allow force pushes` 不勾选。
- 确认 `Allow deletions` 不勾选。

保存后，正常工作流变为：功能分支本地提交 -> 用户明确要求后推送 -> Draft PR -> 验收满意 -> 合并进 `main`。不满意时关闭 PR 并删除分支即可。

## 什么时候用 worktree

适合“同一个仓库同时开两个文件夹干活”，比如一个文件夹修 bug，另一个文件夹继续做新功能，互不打断。

常用命令：

```powershell
git worktree add ..\InvoiceHub-format feature/invoice-format-badge
git worktree list
git worktree remove ..\InvoiceHub-format
```

注意：每个 worktree 只能签出一个分支；同一个分支不能同时被两个 worktree 签出。

本项目默认不强制 worktree。只有并行维护两条开发线、长期对照旧实现或用户明确要求时才使用；使用时要记录新目录路径、绑定分支和后续清理命令。

## 什么时候用 fork

适合“你不是原仓库主人，想先复制一份到自己 GitHub 账号下再改”。仓库公开后，外部贡献者通常应 fork，再向上游 `main` 发起带 DCO sign-off 的 PR；维护者日常功能开发仍优先使用同仓库 `codex/<task-name>` 分支。

典型流程：

```powershell
git clone https://github.com/your-name/some-project.git
git remote add upstream https://github.com/original-owner/some-project.git
git fetch upstream
```

## 常用状态怎么看

```powershell
git status --short --branch
```

- `## main...origin/main`：本地 `main` 正在跟踪 GitHub 的 `origin/main`。
- `ahead 1`：本地多 1 个提交，还没 push。
- `behind 1`：GitHub 多 1 个提交，本地还没拉取。
- `M file`：文件被修改。
- `?? file`：新文件还没被 Git 跟踪。
- `!! file`：文件被 `.gitignore` 忽略。

## 本项目提交前检查

本项目不能把本机业务绝对路径、运行态、真实发票产物推到 GitHub。提交前至少看：

```powershell
git status --short --branch --ignored
git diff --cached --name-status
git diff --cached --check
```

如果看到 `.venv/`、`运行状态/`、`.lnk`、成本发票明细/汇总产物或本机业务路径进入暂存区，应先移出暂存或改回默认配置。

## 不满意时怎么回退

未合并到 `main`：

```powershell
git switch main
git branch -D codex/<task-name>
git push origin --delete codex/<task-name>
```

这种情况 `main` 从未被功能影响，回到当前稳定版本最快。

已合并到 `main`：

```powershell
git switch main
git pull --ff-only origin main
git revert <merge-commit>
git push origin main
```

如果不是 merge commit，而是普通提交，就用：

```powershell
git revert <commit>
```

默认不要用 `git reset --hard`、force push 或改写 GitHub 上的 `main` 历史。只有明确知道风险并得到用户确认时，才考虑历史重写。

<a id="git-rules"></a>

## Git 分支开发与回溯规则

- `main` 只保留已验收、可回退的稳定版本；代码、接口、前端、解析、启动、成本、发布类功能改动不得直接在 `main` 上施工。
- 大功能、用户可见功能、跨模块改动和高风险修复必须从当前稳定 `main` 新建 `codex/<task-name>` 分支开发；分支名用英文短横线描述任务，例如 `codex/voucher-draft`。
- 创建分支前必须执行 `git status --short --branch --ignored`，并确认当前分支、未提交修改、ignored 运行态和当前 `main` 基线 commit；最终回复或任务记录中必须写清本轮从哪个 commit/分支开工。
- 创建分支前若存在非本轮代码修改，必须先分类说明并决定是否暂存、提交、保留或停止；`config/app.local.json` 这类本机运行配置允许留在工作区，但不得纳入功能提交。
- 默认使用同一个工作目录切换分支；只有并行维护两条开发线、需要长期对照旧实现或用户明确要求时，才使用 `git worktree`。使用 worktree 时必须说明新目录路径、绑定分支和清理方式。
- `push` 不是默认收尾动作；只有用户明确要求“推送 / 上传到 GitHub / 更新 PR / 创建 PR”时，才允许执行 `git push`。不得因为本地提交完成就自动推送。
- 用户明确要求推送功能分支时，使用 `git push -u origin codex/<task-name>`；不得把未验收功能直接推到 `origin/main`。
- 用户明确要求创建或更新 PR 时，才允许推送分支并创建/更新 GitHub Draft PR。PR 描述必须列出变更范围、测试结果、未覆盖项、敏感路径/本机配置检查结论和回退方式。用户明确满意后，才允许合并进 `main`。
- PR 合并前必须复核 PR diff、测试结果、未覆盖项、`config/app.local.json`、真实发票路径、运行态、发布产物和本机业务路径；发现风险时先修复或停止，不得带风险合并。
- 未合并的功能如果不满意：切回 `main`，删除本地分支和远端分支即可；不得为丢弃未合并功能去重写 `main` 历史。
- 已合并的功能如果不满意：优先使用 `git revert <merge-commit>` 或 `git revert <commit>` 生成反向提交；禁止默认使用 `git reset --hard`、强推或重写共享历史，除非用户明确要求并确认风险。
- 本地未提交试验只能在功能分支内丢弃；不得在 `main` 上做“试试看”的高风险改动。
- 未经用户明确要求，不做 force push，不改写已推送历史，不做 rebase/squash 来隐藏或重排既有提交。

## Git 提交与推送速查

- 开始提交前必须先执行 `git status --short --branch --ignored`，确认当前分支、领先/落后关系、未提交修改和 ignored 运行态；不得沿用旧状态判断。
- 提交范围必须用显式文件清单暂存，优先 `git add <file...>`，不得用 `git add .`、`git add -A` 这类会把本机运行态、配置或产物一并扫进去的命令。
- `config/app.local.json` 默认不提交本机运行配置；只有确认内容已脱敏、`watch_dir` 等路径符合“项目内相对路径、包外用户目录不写入默认示例”的规则时才允许暂存。含业务绝对路径、最近目录、真实发票路径的本机配置必须留在本地。
- 暂存后必须检查：
  - `git diff --cached --name-status`
  - `git diff --cached --check`
  - 对 staged diff 搜索本机业务路径、`.lnk`、`.venv`、`runtime`、`dist`、`运行状态`、`__pycache__`、真实发票和成本产物关键词。
- 代码、接口、前端、解析、启动、成本或发布相关提交，必须先跑与风险匹配的测试；常规提交优先执行 `.venv\Scripts\python.exe -m pytest` 和 `.venv\Scripts\python.exe -m compileall src tests`。纯文档提交可不跑完整测试，但最终回复必须说明未运行原因。
- 提交信息使用清晰英文祈使句，例如 `Add recent watch directory removal controls`；不要改写用户已有历史，不做 rebase/squash，除非用户明确要求。
- 推送必须由用户明确指定；没有明确“推送/上传/更新 PR/创建 PR”要求时，不得执行 `git push`。用户要求推送时，推送目标必须匹配当前任务分支：功能分支使用 `git push -u origin codex/<task-name>`；只有已在 `main` 上完成验收合并或用户明确要求直推稳定主线时，才使用 `git push origin main`。
- 如果 GitHub HTTPS 短暂超时，先重试并用 `git status --short --branch`、`git branch -vv` 判断本地是否仍领先；如果远端有冲突或不可访问，不擅自改分支名、不强推，停止并报告。
- 推送后必须复核：
  - `git branch -vv`
  - `git log --oneline --decorate --graph --all -8`
  - `git ls-remote --heads origin <当前分支名>`；涉及主线合并或推送时同时检查 `git ls-remote --heads origin main`
  - `git status --short --ignored`
- 最终回复必须按 `modified/deleted/untracked/ignored/warning` 分类说明工作区状态；如果 `config/app.local.json` 仍修改，必须说明它是本机运行配置并未上传。

## 当前 Git 快照

- 更新时间：`2026-08-14`。公开图以脱敏根提交开始，后续公开提交只能是其后代；不继承旧提交、Tag 或 Release 身份。精确 SHA 只通过实时 Git 命令核对，不写入当前事实文档。
- 原工作区、stash、本机配置、未跟踪资产、ignored 运行态和真实业务文件都不属于公开根提交或发行输入，不得清理或混入。
- 私有历史备份的存在不构成公开发布资格；若需恢复旧图，只能由所有者在独立 private 仓库中进行，绝不得推回公开仓库。
- 每次任务开工、提交、推送和收尾前仍必须重新执行 `git status --short --branch --ignored`，不得沿用本节快照数字。
