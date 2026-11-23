# 分支整理、main 同步与双平台候选准备

## 2026-11-23 BUG-06 本地修复

按已确认规划接续 `codex/workspace-p3@95bad31412102c69c26a3c9fe1db71cdfb1b4753` 的成本 V2 开发线，无新 worktree。开工本地 `main/origin/main` 均为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`；本轮未联网更新远端引用。保留五份既有规划文档修改、无关 `pelican-bicycle.html` 和 ignored 配置/运行资料；不将它们当作本轮新增产物。

本地代码补齐草稿品目类型与来源状态交接、非库存科目确认/待补、历史与销项数量隔离；具体测试及未覆盖范围见 CHANGELOG。本轮修复与既有规划文档修改已按显式 DCO 清单本地提交（精确 HEAD 以实时 Git 为准），未推送、合并或打包；原起点 `95bad31` 不包含本轮修复，后续验收以最新本地提交为准。

## 2026-11-22 成本 V2 本地候选与 ENG-05 接续

本轮从 `codex/workspace-p3@5835f5e` 接续；开工核对本地/远端 main 均为 `ee0f2c2`。原未提交 V2 前端、迁移、服务分析、价格提示、回归与构建资源已用 48 个明确文件固定为 DCO 本地候选 `af987d8b9965234565b3132c0b443e90f0f6f7d3`。无关 `pelican-bicycle.html` 和 ignored 配置/运行资料保留，未加入候选。未推送、合并、打包或改变稳定 main。

候选通过全量 Python、Vue/Node、Ruff/编译及两组隔离浏览器。干净源码导出按冻结锁离线安装，三份重建 Vue 资源与提交逐字节一致，P3/成本浏览器在该导出上复验通过。JS SHA-256 保持 `5dd20d5c24cdb2ae53eac725a933ae15d1485f7404c5515f8f2cf5e0488788f8`。

11 月 22 日规划从同分支 `95bad31412102c69c26a3c9fe1db71cdfb1b4753` 开始，直接父提交为上述成本候选。该提交加入 ENG-05 的 Linux 浏览器 CI 和经典首页局部刷新修复。两次提交的 Python 产品源码与构建后的 Vue 资源相同，经典首页脚本有变更。后续业务与平台验收统一从这次提交取版本，修复后在结果中另记实际受测提交。本机三组浏览器各连续三次通过，整表重绘故障命中预期断言。按该提交查询 GitHub 的 `ci.yml` 尚无运行记录。规划开始时本地 `main` 为 `ee0f2c2`，与开发线相差 90 个提交。[近期交付顺序](PRODUCT_BACKLOG.md#next-delivery) · [浏览器回归](BROWSER_E2E.md)

## 工作区 P3 第 1—6 项（2026-11-17）

起点为已整理的 `codex/workspace-p2@36f8dfaf655622afff2457f49ac0de4aafc990b0`，稳定本地/远端 main 开工核验为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`。同目录分支 `codex/workspace-p3`，无新 worktree。保留起点无关 `pelican-bicycle.html` 与全部既有 ignored 配置/运行资料。只做 P3 第1—6项，WS-08/09另做；本地提交不推送、不合并、不打包，不将源码验收当作已发布能力。

按依赖顺序拆为六个本地 DCO 提交，固定账号先于逐文件识别。共享文件按代码块拆分，每项从暂存区导出独立源码快照检查，不使用最终工作区替代中间提交测试；前端变更各自生成对应 Vite 资源。

| 提交 | 内容 | 独立快照验证 |
|---|---|---|
| `d37a627` | B7.2 手填固定账号、预览绑定与私有档案 | 后端 46、Vitest 103、类型检查/构建 |
| `ed2515b` | B7.1 逐文件识别、页脚、有界读取与缓存 | 后端 58、Vitest 103、类型检查/构建 |
| `fcf33e6` | B7.3 CLI/凭证生成与公司自定义银行目录 | 后端 71；沿用上一提交前端 |
| `d341e48` | WS-10 凭证分录结构、库存/社保界面与懒加载 | 后端 52、Vitest 106、类型检查/构建 |
| `c1f468d` | B8.1 税费展示、候选来源与人工复核门禁 | 后端 49、Vitest 107、类型检查/构建 |
| 本节所在提交 | ENG-05 合成 FastAPI/Chromium 与最终文档 | 全量后端 1145、16 跳过、24 subtests；Node 37；真实浏览器切片通过 |

最终源码另通过定向 Ruff、compileall、文档契约/本地链接与 diff 检查；浏览器覆盖映射保存/断链、凭证增删保存重读、税费展开、浅深色/390px/无皮肤，零控制台错误。未覆盖真实默认配置、正式 Windows BAT、正式入口前台拉起、系统原生选择器、Tauri 宿主或打包成品。5 条 SWIG 弃用警告及 Vite 运行时解析字体提示仍存在；功能分支 pre-commit 钩子仅在 main/master 执行，本轮手工运行上述检查。

## 工作区 P1/P2 按风险拆分提交（2026-11-17）

用户要求把 `codex/workspace-p2@ab9d4b8` 上积累的前序工作区、P1、P2 未提交工作按风险拆分提交，并要求每个提交完整。按“风险分组 + 依赖顺序”本地提交，混合文件按代码块分入对应提交；每个代码提交都在临时 worktree 的独立检出上跑过后端全量测试。未推送、未开 PR、未合并 `main`。

| 提交 | 风险 | 内容 | 独立检出验证 |
|---|---|---|---|
| `8e6478e` | 低 | 前端设计标准、服务器链接设计与原型 | 纯文档 |
| `dcc66ac` | 低 | P1/P2 契约、架构地图、规则、待办与 P3 规划文档 | 后端全量通过 |
| `057efa0` | 最高 | B6：成本投影、monitor、后台同步改读公司自己的开具来源 | 后端 1022 通过 |
| `4d7af81` | 高 | 公司工作区后端 B1—B5、B7、B8（写公司资料夹）及 WS-02 目录保护回归 | 后端 1109、Node 30 通过 |
| `28e2a8c` | 中 | 经典页皮肤隔离与嵌入资源、首页项目列、成本页身份只读胶囊 | 后端 1124、Node 37 通过 |
| `4a0e6d3` | 中低 | Vue 工作区按原型重建并接入 P1/P2（含构建产物） | 后端 1124、Node 37、Vitest 102、类型检查通过；重新构建与提交产物一致 |
| `a07ceb2` | 高 | Tauri 原生拖入放行 Vue 临时识别页 | Rust lib 56 通过（含拖入判定）；4 项本机回环套接字测试见下 |

- 改写记录：首轮拆分漏看四个未跟踪文件（状态清单被截断），曾以两个补漏提交追加。用户 2026-11-17 要求提交完整后，在本地未推送范围内重放：嵌入资源并入 `28e2a8c`，目录保护测试并入 `4d7af81`；最终树与首轮补漏后的树逐字节相同。首轮提交保留在本地备份分支 `backup/workspace-p2-split-20261117`，确认无误后可删除。
- Rust：使用本机已有的固定工具链 1.85.0 与离线 crate 缓存运行 `cargo test --lib --offline`。`host_rpc` / `local_http` 的 4 项真实回环套接字测试在本机会话中连接 127.0.0.1 被系统拒绝（`Operation not permitted`，脱离沙箱同样被拒，Python 最小回环连接亦失败），属执行环境限制；这些文件本轮未改，需在普通终端复跑。
- 未提交：根目录 `pelican-bicycle.html`，与本项目无关，保留在工作区。

## 工作区 P2 开发（2026-11-17）

起点 `codex/workspace-p1@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73`；开工核验本地/远端 main 均为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`。依赖前序 P1/工作区未提交实现，在同目录建立 `codex/workspace-p2`，未用 worktree。开工已有 modified 99、untracked 42 与 ignored 运行态；全部保留。B3/B5/B7 与 B8 手工基础已接入，自动税务规则未解锁；未暂存、提交、推送、合并或打包。与前序修改共用文件，按项独立提交须先整理前序基线；本轮保存相对开工文件副本的增量供审阅，不混入前序提交。

## 工作区 P1 开发（2026-11-17）

起点 `codex/cost-select-all-transitions@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73`，开工实时核验本地/远端 main 为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`。规格依赖已有开发线及未提交的工作区前端，保留全部现场后在同目录建立 `codex/workspace-p1`；未创建 worktree。实现 B1/B2/B4/B6，未提交、推送、合并或打包。规格每项独立提交尚未执行：新增改动与前序未提交内容共用文件，需要先独立整理前序基线，禁止直接把它们混入 P1 提交。源码工作不代表稳定 main/发行成品已包含。


## WS-03 / WS-04 开发补齐（2026-11-16）

任务 `ws-03-04-20261116` 在既有 `codex/cost-select-all-transitions@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73` 接续，保留已有未提交代码、文档、原型与 ignored 本机状态；本地 main 仍为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`。新增项目列、比较明细和受限回单预览，未切换分支、提交、推送、合并或打包；本轮未重新查询远端。源码开发完成不代表稳定 main 或成品已包含。

## WS-02 后端与工作区皮肤隔离接续（2026-11-14）

任务 `ws-02-backend-20261114` 接续现有 `codex/cost-select-all-transitions@ab9d4b8`，保留起点 WS-01 未提交代码 / 文档与原有 HTML。实时 `git ls-remote` 核对 main 为 `ee0f2c2`，当前开发分支尚无同名远端引用。沿既有 WS 开发线补齐目录身份 / 状态校验，并按用户确认隔离工作区两款装饰皮肤；不切换分支、不提交、不推送、不合并、不打包，稳定主线与已发布成品保持原身份。

## WS-01 临时识别与模块缓存接续（2026-11-14）

任务 `ws-01-completion-20261114` 从同一 `codex/cost-select-all-transitions@ab9d4b8` 恢复；原聊天已暂停且无后台写入，接手复核通过。保留起点 32 份 modified、13 份 untracked 与 ignored 本机状态，在既有未完成源码上补保护、专用回归、构建与文档。当前分支 / HEAD / main 未改，不提交、不推送、不合并、不打包；本地实现仍不属于稳定 main 或已发布成品。

## WS-01 外观衔接接续（2026-11-14）

本轮 `ws-01-appearance-20261114` 从 `codex/cost-select-all-transitions@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73` 继续已整合的 WS 开发范围；本地 main 仍为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`。开工保留前轮九份文档修改、原有未跟踪 HTML 与 ignored 本机状态。新增 Vue 皮肤衔接、对应回归和文档，尚未提交；不切换分支、不推送、不合并、不打包，不将源码能力记入已发布成品。当前开发余项与 37 项待真实验收继续由下列统一入口维护。

## WS 任务线现场核对（2026-11-13）

本轮任务为 `ws-status-acceptance-audit-20261113`：核对 WS-01—07 与待真实验收清单，修正文档口径；起点为 `codex/cost-select-all-transitions@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73`。

- 主目录的 `codex/cost-select-all-transitions` 与独立 worktree 的 `codex/ws-07-company-registry` 同指 `ab9d4b8`，WS-02 最新实现已包含在本地成本开发线。
- 本地 `main`、`origin/main` 与 `git ls-remote origin refs/heads/main` 均为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`；与任务起点双向差异为 `0 / 69`，开发线领先 69 个提交。远端未返回上述两条开发分支的同名引用。
- 本轮只改核对文档，不切换分支、不提交、不推送、不合并、不打包；这些本地能力不属于已发布成品。起点已有未跟踪 HTML 与 ignored 本机配置 / 运行态 / 产物保留。

开发范围见 [WS 当前汇总](../IMPLEMENTATION_STATUS.md)；待真实验收见[三轮清单](MIGRATION_GAP_CHECKLIST.md#ws-real-acceptance)。本节是核对时的引用快照，后续以实时 Git 为准；下方是各次整合与发布的历史记录。

## 工程门禁并入本地成本开发线（2026-11-09）

`codex/engineering-guardrails`（CI 门禁、API 路由拆分、Vue 工作区前端基础，4 个 DCO 提交）由用户授权在本地合并：以快进方式并入 `codex/cost-select-all-transitions`，该开发线仍领先 `main` 且未推送、未开 PR；用户决定功能稳定后再开 PR，`main` 不变。合并前主工作区的未提交修改（成本页、银行模块、交接工具及相关文档）先备份到仓库外并 stash，快进后原样恢复为未提交状态，逐文件核对无丢失；合并后在该工作区运行全量 pytest、ruff、Node 交互测试与前端类型检查/组件测试/构建可复现检查。精确提交以实时 Git 为准。

## 优化版 1 来源与发布（2026-09-10）

Windows 来源分支 `codex/windows-alpha2-release-source` 已取得，精确提交 `0d5239f113ac5017174fbbf09dd30817ebeed432`，与两端制品收据一致；此前缺少对象的阻塞已经解除。发布源码固定在 `v0.3.0-alpha.2-opt.1`，内嵌产品版本仍为 alpha.2，核心身份 `0f41b453964c635dc6d0623c98d7abffef8614f6d65709853da877d7733b53b0`。

主线集成使用 `codex/opt1-release-integration`；原文档分支 `codex/alpha2-opt1-release-docs` 与准备分支 `codex/alpha2-optimized-release` 保留。两份原始 Windows 提交缺少 DCO，集成分支使用带来源记录和签署的新提交，文件树与已核验版本一致，原始提交及已发布 Tag 不改写。构建时的源码是干净 detached commit，后续文档变更不进入该制品。既有未跟踪文件与本机运行态已恢复保留；Windows 交接文档中的 stash 仅表示交付方历史，不与 Mac 本机状态混同。

Mac DMG 为 `169041824` bytes，SHA-256 `c9076f464e8544391314eda0bd277aee047ba27623f572c265d1d91e8e7cd6da`；Windows ZIP 为 `114288563` bytes，SHA-256 `85284a9d0024da1c50c81fa011b21c802429db3b1ad7c5de0a666de290eec461`。10 项发布输入位于 ignored 的 `dist/candidates/20260910-alpha2-opt1-release/`，Mac 原始 App、离线/原生 OFD/正常启动报告位于 `dist/candidates/20260910-alpha2-opt1-macos-0d5239f/`。这些文件保留供发布复验和回退，不作为源码提交。

[优化批次发布页](https://github.com/lyc1126/InvoiceHub/releases/tag/v0.3.0-alpha.2-opt.1)已公开，10 项资源的服务器哈希核对一致；旧 alpha.2 不覆盖。Mac 已通过离线、包内 OFD 两页及正常配置的 ready/资源/monitor 验收，隔离 HOME 自动验收未通过的限制继续披露。

## 优化版跨平台接收（2026-09-09）

当前同步工作位于 `codex/alpha2-optimized-release`，从公开 main 的 PR #24 基线开始，已接收 Windows 启动加固 patch。Windows receipt 来源为 `0d5239f113ac5017174fbbf09dd30817ebeed432`，远端全分支及精确 SHA 请求均尚未取得该对象；补丁应用后的核心指纹一致，但这不等于 Git 来源身份已闭合。必须取得原始提交后再执行最终同源 Mac 组包和新优化版 Tag 发布，不修改既有已公开 alpha.2 Tag/资产。首页仅新增用户要求的维护约定；未跟踪文件及本机运行态保留。

下方 Windows 分支/stash 是随附 patch 记录的 Windows 主机历史，不表示本 Mac 工作区创建或持有这些 stash。

## Windows 启动加固（2026-09-09）

本轮 main 从 `f71323b` 快进到 `b3d69f6`（PR #24），开发分支为 `codex/windows-alpha2-startup-hardening`。原七份 OFD 打包文档保存在 stash `474bdd8aab5379ed2653fad01b9c9e4a48c3842c`；未跟踪压缩包、旧包及本机配置保留。本轮只产出本地 Windows alpha.2 修复优化候选，不修改 GitHub Tag/Release/Feed。精确构建身份和验收范围见 CHANGELOG 与候选 receipt。

更新时间：2026-09-08。此页记录本轮本地/远端引用整理、`main` 同步和 macOS 候选构建；精确远端状态仍以 Git 查询为准。

## 启动探测主线集成（2026-09-09）

用户在源码修复和验证范围说明后明确授权提交、推送并合并 main。功能来源为 `codex/fix-backend-startup-probe`，从 `f71323b1e560a2e75653d847b069552cee84c18f` 开工；采用 DCO sign-off、功能分支 PR 和普通 merge，不重排历史。开发实现与稳定源码统一跟随 main，精确提交/合并身份以对应 PR 与实时 Git 为准；Windows/macOS CI、DCO 和本机 Rust 回归分别记录，不能把 Python CI 称为 Windows Rust 或原生桌面验收。

本次只提交后端 HTTP framing、脱敏启动诊断、浏览器兜底及其合成测试/文档。外部日志、压缩附件、本机配置、运行态、编译缓存和无关 HTML 不纳入提交。已发布 alpha.2 ZIP/DMG、Tag 与 Feed 保持既有身份；新成品和 Windows 原生验收仍须单独执行。

## OFD 主线集成（2026-09-08）

用户在真实 OFD 的独立预览和 InvoiceHub 浏览器弹窗展示后，明确授权提交、推送并合并 main。本次集成来源为 `codex/ofd-preview-renderer`；采用签署 DCO 的普通提交、功能分支推送和受保护主线 PR merge，不重排原历史。开发实现与稳定源码统一跟随 main；精确 feature/merge/main 身份以该 PR 和实时 Git 为准。已发布 alpha.2 未重新打包，不将新源码与旧制品混称同一份二进制能力。

提交只包含组件适配/构建源码、锁、许可证、合成测试和脱敏文档。真实 OFD 及临时演示状态留在公开工作树外，组件二进制与合成 QA 包留在 ignored runtime；本机配置、旧工作树和其它独立开发资料不作为提交输入。双平台 CI/DCO 与本机真实组件检查分别记录，不将 hosted CI 的原生组件 skip 记为 Windows 引擎验证。

## OFD 开工前分支清理（2026-09-08）

当前开发为 `codex/ofd-preview-renderer`，从 `main@fda171dbb7deb4e01731c5a72ec8102f11d3c03d` 新建。开工时主工作区无 modified/deleted/untracked，本机配置、运行态、构建产物和投影均为既有 ignored。远端 main 同 SHA。

按用户明确要求，先以 main 祖先关系确认，再普通删除本地 `codex/app-icon-windows`、`codex/macos-desktop-main-sync`、`codex/tauri2-update-recovery`、`codex/tax-calculator-mvp` 四个旧分支。远端 `codex/desktop-latest`、`codex/desktop-main-docs`、`codex/macos-desktop-main-sync` 三个已合并分支也已删除，并重新查询确认；仅删除分支引用，没有改写提交或 Tag。

仍有独立提交的图标/搜索分支、Dependabot、含未提交改动的旧 release-prep 工作树及原 stash 保留；失效 worktree 登记不在本轮执行全局 prune。新 OFD 功能没有推送、PR 或主线合并。下方为 alpha.2 发布阶段的历史记录，不作为当前分支存活清单。

## alpha.2 发布阶段引用快照（历史）

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
