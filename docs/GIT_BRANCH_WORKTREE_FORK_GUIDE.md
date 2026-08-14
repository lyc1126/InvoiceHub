# Git 分支、worktree 和 fork 速查

本文按本仓库当前历史解释常用 Git 概念，方便之后判断“改了代码、提交了、推送了”分别处在哪一步。

## 本仓库这次发生了什么

- 当前公开权威引用是完成验证后的脱敏根提交；精确远端 HEAD 仍以实时 `git ls-remote` 为准。
- 所有预公开提交、Tag 和二进制均不复用。远端历史净化、候选 Git 对象扫描和托管面验证通过后，下一功能分支才从 `main` 创建为 `codex/tauri2-unified-desktop`。
- 本次公开基线不保留任何旧分支、合并基线或发布身份。后续功能只在新的公开 `main` 上按普通分支和 PR 流程开发。
- 私有工作区、stash、本机配置、未跟踪资产和 ignored 运行态均不属于公开图、Tag、Release 或 Feed 输入。
- 本节只帮助理解当前工作流，不作为永久 Git 真值；分支和 commit 快照始终以 `AGENTS.md` 的“当前 Git 快照”和实时 `git status/log` 为准。
- 当前本机配置：`config/app.local.json` 可能显示为 modified，这是本机运行配置，默认不提交。
- 当前推荐开发方式：所有代码、接口、前端、解析、启动、成本、发布类功能改动先从 `main` 新建 `codex/<task-name>` 分支，再通过 GitHub Draft PR 验收。
- 当前回溯原则：未合并功能直接删除分支；已合并功能用 `git revert` 生成反向提交，不默认重写 `main` 历史。

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
