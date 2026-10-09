# AGENTS.md

本文件作用于整个仓库，所有 Agent 每个任务必须完整读取。不要创建 `AGENT.md`、`agent.md` 或其他旧命名变体。

## 开工规则

- 每个线程任务开始时，在分析、改代码、跑测试或给结论前，必须显式读取本文件，并按本文档和相关真值文档的约束执行；不得只凭对话记忆、上轮状态或单条测试结果继续施工。
- 涉及发票识别、汇总稳定性、localhost、OCR、成本分析、启动脚本、发布验收或旧项目行为对照时，除本文件外还必须读取相关真值文档：
  - `CHANGELOG.md`
  - `IMPLEMENTATION_STATUS.md`
  - `README.md`
  - `docs/MIGRATION_GAP_CHECKLIST.md`
  - `docs/BASELINE_FROM_OLD_PROJECT.md`
- 如需引用旧项目行为，只读旧项目文档和代码；没有用户明确授权，不得修改、恢复、格式化或清理旧项目。
- 如果目录结构、入口、运行状态或 `git` 状态已经先于文档发生变化，必须在同一任务内回填文档，再允许收尾。

功能细则已移入架构地图的 `docs/architecture/rules/`。**先在 [任务快速索引](docs/architecture/AGENT_TASK_MAP.md#quick-lookup) 按问题定位，再完整读取命中的规则页和对应任务行；涉及多个功能时读取全部命中项。** 搜索摘要不能替代规则正文；无需通读不相关功能。

## 项目边界

- 当前产品边界：`v1 localhost`
- 当前运行模型：`单活动监控目录 + TargetProfile 独立档案`
- 公开基线：本仓库以一个脱敏根提交建立新的 `main`。旧私有提交图、Tag、构建包、receipt 和验证叙述不属于公开图或 Release 输入；详情见 `docs/release/HISTORY_SANITIZATION_EXECUTION.md`。
- 当前不做：多用户、权限、授权、云部署、MSI、Windows ARM64、macOS Intel/Universal、App Store、本地 OCR 正式打包版、SQLite 发票主存储。
- 本文件已整合旧项目仓库根 `AGENTS.md` 与 `发票处理脚本/AGENTS.md` 中仍适配重构版的约束。旧项目特有的目录名、版本号、旧 `web_localhost` 布局和旧包名只作为历史基线，不作为新项目结构要求。
- 共享业务核心为 Python/FastAPI/Web 与独立 monitor，当前桌面宿主为 `src-tauri/`；SwiftUI/WKWebView 保留为开发与迁移参考。版本与契约以 `src/invoice_hub/version.py`、`src/invoice_hub/release/build_manifest.py` 为准。

## 第一性原则

- 源发票是事实；CSV/XLSX/JSON 是可重建投影。
- 字段策略保持：宁可空，不要脏值。
- 用户可见路径必须明确区分：
  - `watch_dir`：当前发票业务来源目录
  - `workspace`：普通汇总与运行状态工作区
  - `watch_dir/成本发票明细.csv`
  - `watch_dir/成本发票汇总.xlsx`
  - `watch_dir/成本开票状态.json`
- SQLite 只允许存任务、事件、缓存和设置，不作为发票主存储。
- Docker 只作为开发与 Mac 验证工具，不作为 Windows 正式离线运行依赖。
- 源码、默认配置和文档示例不得写死本机绝对路径；项目根目录内路径写回配置时必须保存为相对路径，包外用户目录才允许保存绝对路径。
- 所有用户可见状态必须可诊断：状态文件、日志、事件、API 返回和页面提示不能互相矛盾。
- 自动删除同步只允许改变投影与状态，不得删除源发票；用户手改字段必须受保护。用户明确勾选并二次确认的“删除所选文件”是独立原生回收站操作，遵守[页面规则](docs/architecture/rules/WEB_UI.md)，不得永久删除降级。
- 监控必须是独立 daemon，关闭窗口、停止 localhost 与停止 monitor 的语义保持分离；启停与后台同步任务必须读 [监控规则](docs/architecture/rules/MONITORING.md)。
- 真实业务资料、凭据、原始私有日志不得进入公开工作树或测试夹具；做账真值仍在公司资料夹 `凭证/` 下。代码验收不授权真实迁移、审批、导出或账套操作；真实 apply 仍需用户当回合明确授权，详见 [做账规则](docs/architecture/rules/BOOKKEEPING.md)。

## 开发架构阅读与同步规则

- `docs/DEVELOPMENT_ARCHITECTURE.md` 是当前开发实现的权威架构入口；`docs/architecture/AGENT_TASK_MAP.md` 是按任务定位修改入口、联动范围和最低验收的导航表。
- 跨模块、架构、数据链、启动、监控和发布任务，必须先读架构总入口，再按任务导航阅读对应专题：接口与时序读 `docs/architecture/INTERFACES_AND_FLOWS.md`，数据、数据库与算法读 `docs/architecture/DATA_AND_ALGORITHMS.md`，文件关系读 `docs/architecture/FILE_MAP.md`，设计原因与注释债读 `docs/architecture/COMMENT_RATIONALE_MAP.md`。
- 窄范围修改也必须先在任务导航中定位该任务；只需阅读与修改面直接相关的专题，不要求无差别重读全部附录。
- 新增、删除、移动或重命名工程文件时，必须在同一任务内同步 `docs/architecture/FILE_MAP.md`；不得只改目录树而留下失真的 Agent 导航。
- 修改 API、页面消费、SSE、错误码、状态语义、生成产物或运行流程时，必须同步 `docs/architecture/INTERFACES_AND_FLOWS.md`；修改模型、SQLite schema、投影字段、公式或算法时，必须同步 `docs/architecture/DATA_AND_ALGORITHMS.md`。
- 修改跨模块影响范围、最低测试或验收入口时，同步 `docs/architecture/AGENT_TASK_MAP.md`；产生新的非直觉约束、兼容原因或失败保护时，同步 `docs/architecture/COMMENT_RATIONALE_MAP.md`，必要时再把长期不变量写回本文件。
- 整合开发分支完成验收并合并 `main` 后，必须在同一任务内把架构文档的开发实现基线和稳定发布基线切换到新的 `main` commit，不保留两套相互漂移的架构说明。
- [文件地图的目录规则](docs/architecture/FILE_MAP.md#directory-rules) 约束工程文件归属；目录、入口和新文件任务必须核对。
- 新增长期约束时，全局必读内容写入本文件；功能细则只维护在 `docs/architecture/rules/` 的所属专题，并同步任务导航及对应架构地图。不得将功能规则再次整段堆回 AGENTS.md 或 CLAUDE.md。

## 文档语言与代码注释规则

- GitHub 首页 `README.md` 仅在大型产品内容更新后，对与该更新直接相关的部分定点修改；日常修复、性能优化和构建验收流水写入 `CHANGELOG.md`、Release 说明及对应真值文档，不重写首页布局、文案和截图。明确的用户要求优先。

- `CHANGELOG.md` 的标题、分节和新增/修订记录一律使用中文；代码标识符、API 路径、命令、配置键、协议名、产品名和不可翻译的专有名词可保留原文。翻译历史记录时不得改变版本、哈希、接口、验证范围或未覆盖项的事实含义。
- 每次编辑代码时，必须判断本轮改动是否包含局部代码不能自明的业务规则、跨层/跨功能衔接、时序、安全边界、兼容约束或失败恢复语义；存在时必须在最靠近该判断、交接或保护分支的位置补充简洁注释。纯语法、直观数据转换、已由命名和类型完整表达的逻辑不得为了凑数逐行注释。
- 新增或修改跨功能流程时，衔接注释必须让开发者一眼看出：上游输入或状态来自哪里、下游哪个功能/消费者会使用它、为何必须保持当前顺序或不变量，以及放宽或失败时会造成什么后果。典型交接包括页面 -> API -> 服务 -> 投影、monitor -> 状态文件 -> SSE/页面、host -> backend -> 原生能力，以及读取 -> 校验 -> 写入/通知。
- 注释只陈述当前代码和测试能证明的事实；优先一至三行，并与 `docs/architecture/COMMENT_RATIONALE_MAP.md` 的原因、不变量和守护测试同步。复杂编排可使用稳定的阶段标题帮助导航，但不得用大段流水账、猜测性历史或重复代码本身代替设计说明。

## 非公开历史功能与故障回溯

- [旧工作区功能与故障回溯索引](docs/legacy/OLD_WORKSPACE_CHANGELOG_INDEX.md) 是公开工作树中唯一允许的旧工作区 Changelog 备查入口；它只提供脱敏的功能类别、故障症状、不变量和当前查询路线，不是原始记录的副本。
- 回溯顺序固定为：当前源码/测试和真值文档 -> 当前 `CHANGELOG.md` -> 旧项目能力基线 -> 脱敏索引。若仍不足，只有所有者可在公开工作树外的私有归档人工核对，并只能将新的脱敏结论写回本仓库。
- 原始非公开 Changelog 及其附件、绝对路径、软链接、局部摘录、验证数据和构建/运行记录不得复制、链接、暂存、提交或写入本工作树的 ignored 目录；不得把它们作为公开图、测试夹具、发布输入或行为真值。

## Git 与授权

- 开工、提交、推送和收尾前重新执行 `git status --short --branch --ignored`；用实时 Git 核对分支、HEAD、main、未提交修改与 ignored 运行态，不沿用聊天或旧文档快照。任务记录须注明起点分支和 commit。
- `main` 只保留已验收、可回退版本。功能、大改动、跨模块和高风险修复从核验后的稳定 main 新建 `codex/<task-name>`；用户对本次工作分支的明确要求优先。纯文档任务可按用户指定分支执行。
- 已有非本轮修改必须先分类并保留或明确处理，不得顺手清理。默认使用同一目录切换分支；只有并行开发、长期对照或用户要求时使用 worktree，并说明目录、分支和清理方式。
- 不默认 push。只有用户明确要求推送、上传、创建或更新 PR 才允许推送对应功能分支并按请求创建/更新 Draft PR；用户明确满意后才允许合并 main。PR 必须列明范围、测试、未覆盖项、敏感信息检查和回退方式。
- 暂存使用显式文件清单，禁止 `git add .` / `git add -A`。本机 `config/app.local.json`、业务路径、运行态、产物、stash 和无关文件不得混入提交。提交前检查 staged 文件、diff、秘密与本机路径，提交信息用清晰英文祈使句并遵守贡献指南的 DCO。
- 已合并功能回退优先 `git revert`；不得默认 reset hard、force push、rebase/squash 或改写已推送历史。未合并功能的分支删除也必须在用户要求的处置范围内。
- 创建/切换/删除分支、暂存、提交、推送、PR、合并与回退前，读取 [Git 操作细则](docs/GIT_BRANCH_WORKTREE_FORK_GUIDE.md#git-rules)，执行其前后核对项；远端冲突/不可访问不能通过强推或擅自改分支名解决。
- 私有历史备份不能作为公开发布资格；旧图只能由所有者在独立 private 仓库中恢复，绝不得推回公开仓库。公开源码及发行仅使用脱敏根提交的后代。

## 验收规则

- 自动化回归不是最终用户验收。
- 对外宣称“已验证”“已修复”“已全通”时必须明确说明：
  - 测了什么
  - 没测什么
  - 是否覆盖真实默认配置
  - 是否覆盖正式 Windows BAT
  - 是否覆盖浏览器前台拉起
  - 是否覆盖系统原生选择器弹窗
  - 是否覆盖打包产物
- 修复用户可见问题时必须做相邻路径回归，不能只验证直接命中的链路。
- 涉及路径解析、启动脚本、配置加载、打包目录、运行状态目录时，必须检查同一配置在所有入口下的解析结果是否一致。
- 按任务导航执行最低自动化和必要真实验收；测试结论绑定本次代码与环境，文档验证不能冒充运行验证。纯文档调整运行文档契约、本地链接与 `git diff --check`，不运行无关产品全回归；代码变更按风险运行业务测试和编译检查。
- Windows 用户入口、当前前端资源/皮肤和发布成品的额外验收，分别见 [Windows](docs/architecture/rules/WINDOWS.md)、[页面](docs/architecture/rules/WEB_UI.md)、[发行](docs/architecture/rules/RELEASE.md) 规则。不可用或未执行的真实验收必须明确披露。

## 收尾规则

- 任何项目变更都必须更新 `CHANGELOG.md` 的 `Unreleased`。
- 后续变更记录必须按时间写入，优先使用 `YYYY-MM-DD 任务标题` 小节；记录内容必须实事求是写清任务需求、执行过程、采用方案、任务结果、验证范围和未覆盖项，不得只写“优化/修复/已完成”这类无法复盘的空泛描述。
- 行为、结构、入口、验收口径变化时必须同步更新 `IMPLEMENTATION_STATUS.md` 与相关真值文档；`README.md` 按首页维护约定，只在大型产品内容更新后定点修改，或执行用户明确要求的修改。
- 涉及旧功能迁移、缺口修复或验收口径变化时必须同步更新 `docs/MIGRATION_GAP_CHECKLIST.md`。
- 如果本轮修复触发新模式或新风险，必须写回所属功能规则；跨功能的长期不变量再回写本文件。
- 开发、调试、测试、烟测、解压验收、打包验收产生的临时文件和临时目录，收尾前必须清理；确需保留时必须在回复中写明保留路径、原因和后续清理动作。
- 收尾前必须运行 `git status --short --ignored` 并分类说明：
  - `modified`
  - `deleted`
  - `untracked`
  - `ignored`
  - `warning`
