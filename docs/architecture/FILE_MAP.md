# InvoiceHub 完整文件地图

> 公共候选基线：经过审计的单一脱敏根提交；旧私有提交、Tag、包和验证材料不在公开图中。
> 当前治理变化以 `docs/release/HISTORY_SANITIZATION_EXECUTION.md` 为真值。候选树、Git 对象和托管面验证通过后，`v0.3` Tauri 2 才从 `main` 开始。
> 本表覆盖当前受版本控制的全部工程文件，包括架构文档与文档契约测试；运行态、投影和本机未跟踪内容只登记生成规则，不使用会随增删文件失真的固定数量。
> 路径是导航键；职责和关系按符号而不是易漂移的行号描述。

## 1. 如何阅读文件关系

每一行包含三类信息：

- **职责/入口**：这个文件为什么存在，优先从哪个符号理解。
- **上游与下游**：它读取谁、被谁消费，或者产生什么文件。
- **修改影响**：至少要联动检查的测试、页面、文档或发布入口。

依赖总方向：

```text
用户入口/页面
  → api
  → services
  → monitoring / extraction / projections / targets / platform
  → domain / storage
  → 源发票、投影文件、运行状态和 SQLite
```

当前 `services/app_state.py` 是统一业务门面，实际跨越多层。它是导航中心，不代表可以把所有新逻辑继续堆入其中。

## 2. 仓库根、配置与治理

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `.editorconfig` | 编辑器基础格式约定。 | 影响所有文本文件；变更需检查 PowerShell 5.1 的 BOM 特例。 |
| `.gitattributes` | Git 文本和换行属性。 | 以 `text=auto` 固定自动识别的普通文本为 LF，保持二进制 `-text`，BAT/PS1 与 BOM CSV 保留 Windows 换行；与 clean checkout 及跨平台 Git archive/Core Build ID 一致性相关。 |
| `.gitignore` | 排除 runtime、dist、缓存、快捷方式和投影。 | 与发布构建排除规则、工作区状态分类共同保护本机数据。 |
| `.github/workflows/ci.yml` | Windows x64 与 macOS arm64 非发布 CI。 | 默认浅 checkout，运行源码/发行/文档/Swift/脚本门禁；发布 Git 夹具必须自行兼容浅边界；`contents: read`，不签名、不上传 Release。 |
| `.github/workflows/dco.yml` | 拉取请求的 DCO sign-off 检查。 | 遍历 PR 中的非 merge commits，缺少 `Signed-off-by` 即失败；合并前将其配置为 `main` 的 required check。 |
| `.github/dependabot.yml` | Dependabot 的 GitHub Actions 与 pip 周期更新配置。 | 仓库公开后由 GitHub 读取；不修改产品包或 release identity。 |
| `AGENTS.md` | 全仓库最高优先级工程规则。 | 所有任务先读；跨模块任务再按本架构地图选读专题。 |
| `CHANGELOG.md` | 当前重构和旧项目迁移历史。 | 为复杂保护逻辑提供历史原因；任何项目变更都更新 `Unreleased`。 |
| `CLAUDE.md` | 兼容其他编码 Agent 的快速入口。 | 不再复制易漂移规模数据，指向 `AGENTS.md` 和架构入口。 |
| `IMPLEMENTATION_STATUS.md` | 当前完成度、基线与未完成能力。 | 与 README、迁移清单和架构债务状态同步。 |
| `LICENSE` | AGPL-3.0-or-later 完整许可证文本。 | 进入源码快照和双平台成品；发布前仍需人工法律复核。 |
| `NOTICE` | 版权、AGPL、商标、贡献者版权和用户数据边界声明。 | 与 LICENSE、THIRD_PARTY_NOTICES 和公开仓库治理一致；不把用户发票或生成物自动纳入 AGPL。 |
| `CONTRIBUTING.md` | 贡献流程、最小验证和 DCO 说明。 | PR 必须带 sign-off；贡献者保留版权并按 AGPL-3.0-or-later 提交。 |
| `SECURITY.md` | 私密漏洞报告与安全范围说明。 | 仓库 public 后启用 private vulnerability reporting；不得在公开 issue 贴秘密、发票或配置。 |
| `CODE_OF_CONDUCT.md` | 社区行为与处理边界。 | 适用于 issue、PR、review 和项目沟通。 |
| `PRIVACY.md` | 本地数据处理、更新请求和 GitHub 交互的隐私说明。 | 不引入遥测；公开贡献不得附真实发票、公司资料或凭据。 |
| `README.md` | 用户与开发者的首要运行说明。 | 链接正式入口、产物位置、测试和本架构文档。 |
| `THIRD_PARTY_NOTICES.md` | Python、Swift、字体与其它第三方依赖声明入口。 | 与依赖锁、SBOM、Sparkle/Python runtime 发行审查联动。 |
| `pyproject.toml` | Python 版本、依赖、pytest 和包元数据。 | 被本地测试、Docker、Windows Python 入口和 core 包使用。 |
| `requirements/runtime.in` | 双平台共享运行依赖输入。 | Windows/macOS 平台输入 include；不能直接替代哈希锁。 |
| `requirements/runtime-windows-x64.in` | Windows x64 运行依赖输入，含 watchdog。 | 编译为 Windows Python 3.14 哈希锁。 |
| `requirements/runtime-macos-arm64.in` | macOS arm64 运行依赖输入，不含 watchdog。 | 编译为 Mac Python 3.14 哈希锁；使用内置 polling observer。 |
| `requirements/dev.in` | 开发/测试依赖输入。 | 编译为开发哈希锁。 |
| `requirements/release-tools.in` | pip-tools 与 CycloneDX 等发行工具输入。 | 只用于构建/审计，不进入用户 runtime。 |
| `requirements/test-tools.in` | CI 测试工具输入。 | 让 CI 工具自身也经哈希固定。 |
| `requirements/windows-x64-py314.lock` | Windows x64 Python 3.14 运行时哈希锁。 | runtime/package manifest、SBOM、wheelhouse 和验包共同核对。 |
| `requirements/macos-arm64-py314.lock` | macOS arm64 Python 3.14 运行时哈希锁。 | Mac embedded runtime、SBOM 与发布验证共同核对。 |
| `requirements/dev-py314.lock` | Python 3.14 开发依赖哈希锁。 | 开发环境与完整 pytest 使用。 |
| `requirements/release-tools-py314.lock` | 发行工具哈希锁。 | 生成/验证锁和 SBOM 的受控环境使用。 |
| `requirements/test-tools-py314.lock` | CI 测试工具哈希锁。 | CI bootstrap 使用，不进入成品。 |
| `docker-compose.yml` | 开发/Mac 验证用测试容器。 | 调用 `scripts/dev/run_docker_tests.sh` 对应的 pytest 环境；不是 Windows 正式依赖。 |
| `config/app.local.json`（ignored 本机文件） | localhost 本机配置结构；不存在时由 `targets.load_config` 或 Windows 首启生成。 | 可能含真实路径，不纳入 Git、对应源码或成品；core 构建另写脱敏 `config/app.default.json`。 |
| `启动一站式发票汇总系统.bat` | 根目录正式启动入口。 | 转发到 `scripts/windows/启动localhost汇总页.bat`；修改后必须做正式 BAT 验收。 |
| `停止一站式发票汇总系统.bat` | 只停止 localhost 的固定入口。 | 转发到 `scripts/windows/停止localhost服务.bat`；不得停止 monitor。 |
| `停止一站式发票汇总系统并停止监控.bat` | 先停 monitor 再停 localhost。 | 转发到 stop-all BAT；语义不能被设置页偏好改变。 |
| `导入旧版设置.bat` | Windows 新目录安装后的显式设置迁移入口。 | 转发到白名单迁移 PS1；不复制业务文件和运行态。 |
| `发票文件/.gitkeep` | 脱敏默认 `watch_dir` 的空目录占位。 | core 包会重建同名目录；实际发票和成本产物不纳入 Git。 |

## 3. 文档

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `docs/DEVELOPMENT_ARCHITECTURE.md` | 当前架构权威入口、基线和学习顺序。 | README、AGENTS、状态文档和所有专题附录指向这里。 |
| `docs/architecture/PLATFORM_ARCHITECTURE.md` | 共享核心、Windows/macOS 责任矩阵、所有权和启动时序。 | 平台入口、选择器、进程控制、构建握手或发布边界变化时更新。 |
| `docs/architecture/FILE_MAP.md` | 本文件；逐文件工程地图。 | 新增、删除、移动文件时同步，并由文档契约测试检查。 |
| `docs/architecture/INTERFACES_AND_FLOWS.md` | 页面/API/SSE/进程/产物关系。 | 接口、前端消费、状态语义或运行时序变化时更新。 |
| `docs/architecture/DATA_AND_ALGORITHMS.md` | 模型、数据库、投影和算法教学。 | 字段、公式、解析证据、状态 JSON 或数据库变化时更新。 |
| `docs/architecture/AGENT_TASK_MAP.md` | 按任务定位代码、联动点和验收。 | AGENTS 的按任务强制阅读规则依赖此表。 |
| `docs/architecture/COMMENT_RATIONALE_MAP.md` | 注释债和设计原因清单。 | 后续复杂模块真实改动时据此逐点补注释，不批量注释。 |
| `docs/BASELINE_FROM_OLD_PROJECT.md` | 旧项目能力迁移基线。 | 只用于行为对照，不规定重构版目录；与迁移清单互补。 |
| `docs/GIT_BRANCH_WORKTREE_FORK_GUIDE.md` | 分支、worktree、PR 和回退操作指南。 | 受 AGENTS Git 规则约束；稳定基线变化时同步。 |
| `docs/MAC_WINDOWS_WORKFLOW.md` | Mac 开发与 Windows 正式验收分工。 | 与 Docker、PowerShell、正式 BAT 和发布验收相关。 |
| `docs/MIGRATION_GAP_CHECKLIST.md` | 旧能力迁移缺口和验收状态。 | 功能迁移、验收口径和开发交接能力变化时更新。 |
| `docs/MONITORING_AND_LOGGING.md` | monitor 状态、日志和诊断说明。 | 与 `monitoring/*`、MonitorBridge 和设置页运行状态联动。 |
| `docs/release/HISTORY_SANITIZATION_EXECUTION.md` | 公开历史净化、私有备份、候选内容审计、全 ref 验证和托管面复核的执行记录。 | 公开 Git 图、发布资产、仓库可见性或 Tauri 开发线变化前必须更新。 |
| `docs/release/UPDATE_SYSTEM.md` | About、Feed、cache、Sparkle、Windows 旁路升级的完整开发说明。 | 更新协议或 UI/安装流程变化时同步。 |
| `docs/release/WINDOWS_REPACKAGE_CONFIG.json` | Windows 构建链的机器可读参数。 | 每个新 RC 都必须从 `version.py`、锁和 clean source commit 重新校验，不能复用退休发布身份。 |
| `docs/jierui/view-voucher-page.selectors.md` | 公开树的外部页面自动化边界说明。 | 不保存真实选择器、地址、坐标或账套事实；W10 操作员必须在获授权的私有环境重新采集。 |
| `docs/jierui/voucher-import-template.facts.json` | 捷锐导入模板六项 readiness 事实。 | build ID 输入；未实测能力必须保持阻断状态。 |

## 4. 开发与 Windows 脚本

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `scripts/dev/build_core.ps1` | 开发侧 core 构建包装。 | 选择 `.venv` 或 `py -3`，调用 `invoice_hub.release.build_core`。 |
| `scripts/dev/windows_release_config.ps1` | 读取并校验 Windows 机器打包配置。 | 在下载、Python 选择和 staging 清理前核对 `version.py`、派生路径、锁与安全相对路径；输出配置 SHA。 |
| `scripts/dev/initialize_windows_repackage.ps1` | Windows 真机打包会话初始化门禁。 | 强制 remote release tip、HEAD、独立交付 RC_SHA 三者相等，核对工具/磁盘/clean 状态并写会话证据。 |
| `scripts/dev/prepare_windows_test_environment.ps1` | 准备隔离的 CPython 3.14.6 x64 源码测试环境。 | 同时安装 Windows runtime 锁与 test-tools 锁，使用独立 wheelhouse，并以环境内受边界校验的 `.pth` 绑定当前 RC `src`；成品 runtime 不携带该绑定。 |
| `scripts/dev/prepare_windows_runtime.ps1` | 准备精确 Python 3.14.6 x64、wheelhouse 和 runtime manifest。 | 每次从只读 `base-python` 复制产品 runtime，保留基线 `Doc`、裁剪产品 `Doc`，固定锁定安装时间并恢复环境，再规范产品 `Scripts/RECORD`；不能回退未知 Python。 |
| `scripts/dev/build_windows_portable.ps1` | Windows portable 总编排与双构建 SHA 比较。 | 接受精确 source commit；以禁用 `core.autocrlf` 的 Git archive 取源码，再调用 runtime 准备、core 组装与验包。 |
| `scripts/dev/generate_synthetic_release_fixture.py` | 生成不含真实业务信息的 PDF/XML/OFD 发布验收目录和 SHA manifest。 | Windows 真机 monitor/投影/预览验收使用；未知文件目录拒绝写入。 |
| `scripts/dev/verify_windows_portable.ps1` | 解压并验证 Windows 候选 ZIP。 | 调用 Python 静态验证并检查包内解释器/import/Tk/pip。 |
| `scripts/dev/verify_release_source.ps1` | Windows 源码、身份、测试和文档预门禁。 | CI 与真机手册共用；要求 clean source commit，并在选择解释器前拒绝非精确 Python 3.14.6 patch。 |
| `scripts/dev/run_docker_tests.sh` | Docker pytest 快捷入口。 | 调用 `docker compose run --rm test`；只用于开发/Mac 验证。 |
| `scripts/dev/run_tests.ps1` | Windows 开发测试门禁。 | 可显式绑定隔离测试 Python，执行 pytest、`compileall src tests` 和全部前端 JS 语法检查。 |
| `scripts/tools/jierui_probe_template.py` | 捷锐模板探测辅助入口。 | 只生成或核对结构性事实，不写真实凭证状态。 |
| `scripts/tools/jierui_voucher_import.py` | 随包 runner 包装。 | 转发到 `invoice_hub.runners.jierui_voucher_import`，要求显式 batch manifest。 |
| `scripts/windows/run_monitor_status.ps1` | monitor 状态 CLI 包装。 | 解析 Python，调用 `invoice_hub.monitoring.control status`。 |
| `scripts/windows/run_start_localhost.ps1` | localhost 正式启动器。 | 读配置、准备 runtime、启动 uvicorn、探测首页、写 PID/state/log 与 PowerShell version/edition/home 诊断并拉起浏览器。 |
| `scripts/windows/run_start_monitor.ps1` | monitor 启动包装。 | 调用 `monitoring.control start`，成功由 ready 握手决定。 |
| `scripts/windows/run_stop_localhost.ps1` | localhost 停止实现。 | 处理 PID、仓库进程和 `server_state.json`；不调用 monitor stop。 |
| `scripts/windows/run_stop_monitor.ps1` | monitor 停止包装。 | 调用 `monitoring.control stop`，支持超时参数。 |
| `scripts/windows/InvoiceHub.Windows.psm1` | 正式 Windows 公共启动/停止真值与浏览器派发。 | 严格识别包、Python、PID、模块、root/config/port；health 从原始响应流按 UTF-8 解码后再比较中文路径身份；负责槽位冲突隔离。 |
| `scripts/windows/import_previous_settings.ps1` | 旧包到新包的白名单迁移包装。 | 调用 `release.settings_migration`；拒绝同根目录。 |
| `scripts/windows/创建根目录快捷方式.ps1` | 生成本机 `.lnk`。 | 目标是根启动 BAT；生成物 ignored。 |
| `scripts/windows/启动localhost汇总页.bat` | PowerShell 7 优先、5.1 后备的启动 BAT。 | 先验证 Program Files PS7，再解析 PATH/App Execution Alias；保留强制 5.1，调用 `run_start_localhost.ps1`。 |
| `scripts/windows/停止localhost服务.bat` | localhost 停止 BAT。 | 使用同一 Program Files/PATH PS7 选择规则调用 `run_stop_localhost.ps1`；保持“只停 WebUI”语义。 |
| `scripts/windows/停止localhost服务并停止监控.bat` | stop-all BAT。 | 使用同一 PowerShell 选择规则先调 monitor stop，再调用 localhost stop BAT。 |
| `scripts/windows/导入旧版设置.bat` | 包内设置迁移 BAT。 | 使用同一 Program Files/PATH PS7 与强制 5.1 规则；参数原样传给迁移 PS1。 |

## 5. Python 包入口与 API

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/__init__.py` | 包说明和 `__version__`。 | 被包导入和发布元数据使用；版本策略变化时同步发布文档。 |
| `src/invoice_hub/version.py` | 产品/包版本、API 契约、通道、链接、白名单和 package ID 单一真值。 | Python、Swift 脚本、manifest、About、Feed 与测试必须一致。 |
| `src/invoice_hub/api/__init__.py` | 惰性导出 `create_app`。 | 保持外部工厂入口，同时避免执行 `api.main` 前抢先实例化默认 AppState。 |
| `src/invoice_hub/api/app.py` | FastAPI 应用、页面路由、API、错误码、静态资源和 SSE。 | 上游是浏览器；下游是 `AppState`、皮肤文件和模板；主要由 API/前端契约测试覆盖。 |
| `src/invoice_hub/api/main.py` | 参数化 uvicorn CLI 入口。 | 读取 root/config/host/port 后通过模块应用只构造一个 AppState；正式 BAT 当前直接启动 uvicorn app。 |

## 6. 领域模型

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/domain/__init__.py` | 汇总导出领域模型。 | extraction、projections、targets、monitor bridge 从此导入契约。 |
| `src/invoice_hub/domain/models.py` | `TargetProfile`、`InvoiceRecord`、成本快照、任务和事件模型。 | API 返回、投影服务和 SQLite 事件使用；字段变化需同步前端、产物和契约测试。 |

## 7. 发票提取与分类

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/extraction/__init__.py` | 提取层公共 API。 | 向 summary、cost、documents 暴露提取、分类、金额校验和文件枚举。 |
| `src/invoice_hub/extraction/classification.py` | 两维分类证据、标准化和冲突状态。 | 被 parsers 和 cost analysis 使用；修改需覆盖分类、汇总、API、详情和一致性。 |
| `src/invoice_hub/extraction/parsers.py` | PDF/OFD/XML 票头提取、金额防污染、同票纠偏。 | 输入源发票，输出 `InvoiceRecord`；summary、cost、documents 消费；核心回归在分类和汇总成本测试。 |

## 8. TargetProfile 与运行路径

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/targets/__init__.py` | 导出配置、布局和档案函数。 | AppState、monitor daemon/control 和测试使用。 |
| `src/invoice_hub/targets/paths.py` | `AppConfig`、`Layout`、相对路径序列化、SHA1 `target_id`、冲突隔离。 | 决定所有入口的路径解释；变更需覆盖路径、启动、monitor、打包和配置测试。 |

## 9. 文件与 SQLite 存储

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/storage/__init__.py` | 导出文件助手和 `SQLiteRepository`。 | services、monitoring、projections 使用。 |
| `src/invoice_hub/storage/files.py` | JSON/CSV 读取与临时文件原子替换。 | manual overrides、成本状态、summary 和皮肤状态依赖；编码必须兼容 Excel/WPS。 |
| `src/invoice_hub/storage/repository.py` | SQLite `settings/tasks/events/cache` schema 与任务/事件接口。 | AppState、monitor、SSE 消费；明确不保存发票主数据。 |

## 10. 普通汇总、成本与单据投影

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/projections/__init__.py` | 导出普通汇总与成本服务。 | monitoring 和外部调用的稳定入口。 |
| `src/invoice_hub/projections/summary.py` | `build_summary`、重复标记、CSV/XLSX schema 和写表。 | 消费 extraction；写入 profile workspace；monitor/AppState 调用。 |
| `src/invoice_hub/projections/cost_analysis.py` | PDF 坐标表格、XML/OFD 明细、校验、均价、参考价和工作簿生成。 | 成本算法核心；`costs.py`、documents 和选择/详情成本拆分使用。 |
| `src/invoice_hub/projections/costs.py` | `CostProjectionService`，状态兼容、快照、参考状态保存与同步统计。 | AppState、monitoring 调用；输出 `/api/v1/cost-analysis` 契约。 |
| `src/invoice_hub/projections/documents.py` | 入库/出库预览、人民币大写、模板扩行和原子导出。 | AppState documents 用例调用；复用票头和成本明细解析。 |
| `src/invoice_hub/projections/document_templates/电子入库单模板.xlsx` | 入库单版式真值。 | `write_inbound_workbook` 读取；版式变化需跑单据渲染/单元格测试。 |
| `src/invoice_hub/projections/document_templates/电子出库单模板.xlsx` | 出库单版式真值。 | `write_outbound_workbook` 读取；版式变化需跑单据测试。 |

## 10.1 做账安全协议

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/bookkeeping/__init__.py` | 导出做账领域与服务入口。 | AppState 做账用例和测试从此访问稳定符号。 |
| `src/invoice_hub/bookkeeping/paths.py` | 公司资料夹 `凭证/` 真值路径。 | 真实业务状态不得写入仓库或通用 runtime。 |
| `src/invoice_hub/bookkeeping/repository.py` | 严格 schema、写锁、revision/CAS 和诊断。 | 所有状态写入必须经此边界，异常文件 fail closed。 |
| `src/invoice_hub/bookkeeping/status.py` | 状态 v1/v2、preview/apply 迁移和业务身份。 | 禁止启动时自动迁移；审批和导出绑定 revision。 |
| `src/invoice_hub/bookkeeping/vouchers.py` | 稳定 posting key、提案 revision 和凭证生成。 | 规则变化只能生成同业务事件的新 revision。 |
| `src/invoice_hub/bookkeeping/validator.py` | `VoucherExecutabilityValidator`。 | 审批和导出必须共用，服务端结构化返回 blockers。 |
| `src/invoice_hub/bookkeeping/decisions.py` | W9 会计决定和证据。 | 与 profile、科目、辅助档案和提案指纹联动。 |
| `src/invoice_hub/bookkeeping/catalogs.py` | 账套 profile、科目和辅助核算档案。 | 绑定 company/environment/identity 及目录 SHA。 |
| `src/invoice_hub/bookkeeping/mapping.py` | 映射规则、resolver、影响预览和定向重算。 | 不得静默覆盖 manual/ai_confirmed。 |
| `src/invoice_hub/bookkeeping/mapping_migration.py` | 映射 v1 到 v2 两阶段迁移。 | apply 重验 source/preview/revision/binding/backup SHA。 |
| `src/invoice_hub/bookkeeping/import_file.py` | 凭证导入 XLSX 和 manifest 绑定。 | 输出不可变批次，文件 SHA 变化使授权失效。 |
| `src/invoice_hub/bookkeeping/batches.py` | exported 到 imported/failed/unknown 状态机。 | finalize 幂等，unknown/partial 只能 reconcile-only。 |
| `src/invoice_hub/runners/__init__.py` | 随包 runner 包边界。 | 不直接写做账状态。 |
| `src/invoice_hub/runners/jierui_voucher_import.py` | batch-bound dry-run runner。 | W8 不开放真实 apply；只接受显式 `--batch-manifest`。 |

## 11. Monitor

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/monitoring/__init__.py` | 导出 `MonitorState` 和 `MonitorSynchronizer`。 | 供服务层和测试使用。 |
| `src/invoice_hub/monitoring/control.py` | status/start/stop/notify CLI。 | Windows monitor PS1 调用；构造 MonitorBridge。 |
| `src/invoice_hub/monitoring/daemon.py` | 独立进程、Watchdog、1 秒事件合并、周期同步和 ready 生命周期。 | 由 MonitorBridge 启动；写 lock/status/events/log。 |
| `src/invoice_hub/monitoring/polling_observer.py` | 无第三方 watchdog 的有界轮询 observer。 | macOS 正式锁使用；保持 daemon observer 接口和事件合并语义。 |
| `src/invoice_hub/monitoring/state.py` | PID 真值、lock、文件签名、processed、Excel 手改和通知。 | daemon/synchronizer/bridge 共用；状态文件位于 target profile。 |
| `src/invoice_hub/monitoring/sync.py` | 重建决策矩阵、schema-only 刷新和普通/成本同步编排。 | daemon 和 AppState 后台启动同步调用。 |

## 12. 服务层

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/services/__init__.py` | 导出 `AppState`、过期选择、预览和打印异常及 `create_state`。 | API 应用工厂依赖。 |
| `src/invoice_hub/services/app_state.py` | 当前统一用例门面：设置、诊断、发票、预览/打印、成本、单据、monitor、皮肤、OCR 占位和关闭。 | 上接 API，下接几乎全部子系统；改动必须按用例做相邻回归。 |
| `src/invoice_hub/services/app_state.py` 的 business dossier 用例 | 解析当前公司资料夹、一次有界扫描快捷入口/统计并限制打开路径。 | `/api/v1/business-dossier*` 和首页消费；不得改变 `watch_dir` 扫描语义；截断统计必须明确为下界。 |
| `src/invoice_hub/services/document_rendering.py` | MuPDF 文档打开和安全分页 PNG 渲染的共享适配。 | preview/print 共用；缺依赖、加密、空文档、页尺寸和渲染失败保持结构化错误。 |
| `src/invoice_hub/services/file_preview.py` | 短期源文件预览 job、闲置续租、页面/文本缓存、SVG/XML/图片安全边界。 | 保留已选源文件顺序；15 分钟闲置 TTL、页数、像素、作业数和缓存上限防止内存滥用。 |
| `src/invoice_hub/services/invoice_printing.py` | 短期同票 PDF 打印 job 和分页 PNG 缓存。 | 不持久化票面；只接收受控 PDF，过期/容量/加密失败明确返回。 |
| `src/invoice_hub/services/monitor_bridge.py` | monitor 子进程命令、状态真值、ready 等待和启停。 | AppState 与 control 调用；与 daemon/state 构成生命周期闭环。 |
| `src/invoice_hub/services/skins.py` | 皮肤 ZIP 安全验证、运行态存储、启用和文件服务。 | API、AppState、common.js 使用；安全回归在 API 测试。 |
| `src/invoice_hub/services/update_service.py` | HTTPS 白名单更新检查、ETag/cache、版本/契约/平台产物选择和错误状态。 | About/API/启动后台检查消费；绝不执行安装。 |

## 13. 平台与发布

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/platform/__init__.py` | 导出 Windows 平台 API。 | AppState 只通过此边界调用选择器和打开路径。 |
| `src/invoice_hub/platform/native_dialogs.py` | Tk 原生目录/文件选择子进程。 | `platform/windows.py` 从项目根启动；取消选择也返回结构化结果。 |
| `src/invoice_hub/platform/windows.py` | 打开文件/目录、运行原生选择器、OCR 扩展名。 | AppState 调用；Windows GUI 行为需真实系统验收。 |
| `src/invoice_hub/release/__init__.py` | core 发布边界说明。 | 标记 release 包职责。 |
| `src/invoice_hub/release/build_core.py` | 从精确 Git commit 组装确定性 Windows ZIP，写脱敏配置、清单、SBOM 和文件 SHA。 | Windows 构建脚本调用；不读取本机未跟踪/业务数据。 |
| `src/invoice_hub/release/build_manifest.py` | 确定性 build ID、API 契约、做账协议和能力清单。 | health、macOS Swift 握手和 `build_and_run.sh --verify` 三方核对。 |
| `src/invoice_hub/release/dependency_lock.py` | 解析并验证平台哈希锁及 package/version。 | runtime 准备、SBOM、发行身份测试使用。 |
| `src/invoice_hub/release/runtime_manifest.py` | 绑定 runtime 树、Python、平台/架构、锁和 import probe；规范 Windows 产品 runtime。 | Windows 安装后删除顶层 `Scripts` 并以 CSV 规则同步 RECORD，Windows/Mac 构建及成品验证共同使用其余清单能力。 |
| `src/invoice_hub/release/package_manifest.py` | 绑定成品版本、平台、架构、包型、锁、Feed、source/core identity。 | health、启动器、About、更新服务与验包使用。 |
| `src/invoice_hub/release/content_scan.py` | 分作用域扫描成品/源码中的秘密和本机绝对路径。 | 自有源码/core 使用严格规则；仅哈希锁定的依赖目录允许上游构建 provenance 路径，私钥和高置信 token 始终阻断。 |
| `src/invoice_hub/release/sbom.py` | 从哈希锁生成确定性 CycloneDX 1.6 SBOM。 | 双平台成品和验证器核对 lock identity。 |
| `src/invoice_hub/release/settings_migration.py` | 新旧 Windows 包之间的配置/偏好白名单迁移与备份。 | 不复制日志、PID、SQLite、cache、皮肤或业务文件。 |
| `src/invoice_hub/release/source_snapshot.py` | 从精确 clean commit 生成确定性对应源码 tar.gz，并从 tag commit 重建受控树身份。 | `git archive` 忽略 checkout 工作树；过滤本机配置/秘密/特殊文件，重算 tree SHA、文件数与 core build。 |
| `src/invoice_hub/release/provenance.py` | 新平台公开 Feed 的最终身份门禁。 | 从实际产物/收据/源码归档重算身份，并把归档与固定 release Tag commit 的受控树逐项核对。 |
| `src/invoice_hub/release/update_metadata.py` | latest.json、Sparkle appcast 的同源生成、严格验证与 parity 门禁。 | 只允许 `generate_release_metadata` 先消费已验证 provenance 再写入；绑定三平台产物、对应源码、EdDSA、source commit 与 core build。 |
| `src/invoice_hub/release/verify_portable.py` | Windows portable 精确路径白名单、反向 macOS/Python 非产品内容拒绝、身份、秘密、锁与 SBOM 验证。 | 大小写不敏感地拒绝 `python/Doc` 与 `python/Scripts`；PowerShell 验包脚本调用，不替代真实 Windows GUI/BAT。 |

## 13.1 macOS SwiftUI 壳

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `macos/InvoiceHubMac/Package.swift` | SwiftPM 产品、最低 macOS、Sparkle 依赖和测试目标。 | 开发与正式 Release/arm64 构建共用；签名/Info.plist/DMG 由 release 脚本完成。 |
| `macos/InvoiceHubMac/Package.resolved` | 精确 Sparkle 2.9.2 revision 锁。 | SwiftPM 构建与正式发行复现使用。 |
| `macos/InvoiceHubMac/README.md` | macOS 开发、握手、运行态和发布方向。 | 与平台架构及脚本参数同步。 |
| `macos/InvoiceHubMac/script/build_and_run.sh` | 构建 `.app`、准备 Python、生成 manifest、收束已知旧服务和有界 verify。 | 固定端口；OpenAPI 校验 API 方法（含预览 keep-alive POST）；TERM 超时后二次验明归属才可 KILL；PID 删除使用内容 CAS。 |
| `macos/InvoiceHubMac/script/prepare_release_runtime.sh` | 下载/校验固定 PBS arm64 Python、离线安装 Mac 锁并裁剪固定上游平台辅助文件。 | manifest 前只删除已知三个 Windows shell helper 与 pip/distlib 六个 Windows launcher，再扫描拒绝任何其它 BAT/CMD/PS1/PSM1 或 EXE/DLL/PYD/MSI/MSIX；拒绝 watchdog 与开发回退。 |
| `macos/InvoiceHubMac/script/build_release.sh` | 从 clean commit 生成 Release arm64 app、Sparkle ZIP 和 DMG。 | internal 对 App/DMG 做 ad-hoc；正式模式要求 Developer ID identity/Team ID/notary；Sparkle 使用专用 account，写 schema 4 审计收据。 |
| `macos/InvoiceHubMac/script/verify_macos_release.sh` | `.app/DMG` 的身份、runtime、架构、签名模式、公证、路径/秘密、SBOM 与反向 Windows 内容拒绝。 | 互斥支持 `--expect-internal-adhoc` 与 `--expect-notarized`，同时验 staging/Sparkle/DMG App 和 DMG；所有已签名 App 的 Python 检查禁写字节码，普通验证必须幂等；Tag-bound finalizer 只用 `--artifact-only --expect-notarized`。 |
| `macos/InvoiceHubMac/script/verify_sparkle_update.swift` | 从已签名 update App 的 `SUPublicEDKey` 验证 Sparkle ZIP 的 Ed25519 签名。 | 公钥必须匹配发行负责人显式信任根；对 ZIP 原始字节验签，不能信任收据或 sidecar 自称。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubMac/InvoiceHubMacApp.swift` | App/Scene/AppDelegate 生命周期。 | App 真正退出时才允许收束 owned 后端。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/AppRoute.swift` | 共享 Web 页面导航定义。 | 必需页面参与 verify。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/BackendStatus.swift` | 后端阶段、所有权和可见状态。 | owned 与 externalCompatible 不得混淆。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/BuildHandshake.swift` | manifest/health/required 三方兼容报告。 | build、API、W9 协议、能力、路径和 PID 任一不符都拒绝。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/StartupSurface.swift` | desktop/browser 启动方式解析与默认值。 | Mac 默认 desktop；偏好在下次启动应用。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/BackendPaths.swift` | Application Support 配置/runtime/PID/log 布局。 | `.app/Contents` 保持只读。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubAPIClient.swift` | health、OpenAPI 路由/方法握手、控制和结构化 shutdown 客户端。 | 兼容探测不读取业务数据接口；必需集合包含预览 keep-alive POST；原生命令必须复用后端响应语义。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubConfig.swift` | 固定端口和脱敏初始配置。 | 不自动换端口。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/LocalBackendController.swift` | 启动/连接/owned 真值/显式关闭/退出收束状态机。 | 异步完成绑定 generation/phase/health/Process PID；仅确认进程退出后清 PID 和 ownership；Sparkle marker 仅在 verified owned startup 已释放 gate 后恢复。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/PythonCommandResolver.swift` | 校验内置或开发 Python 路径。 | `dev-python-path.txt` 失效时明确失败。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubSparkleUpdater.swift` | Sparkle 检查、安装前 monitor 协调、升级标记和失败恢复。 | 不绕过 Sparkle 验签；不在 Swift 迁移业务数据。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Commands/InvoiceHubCommands.swift` | 工具栏/菜单原生命令。 | 调用 `/api/v1` 后刷新可见页面。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Support/MacDirectoryPicker.swift` | `NSOpenPanel` 目录选择。 | 只返回草稿，不直接写配置。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/ContentView.swift` | 主布局与当前路由。 | 不承载业务算法。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/SettingsView.swift` | 原生壳设置和状态。 | 与 Web 设置页职责分离。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/SidebarView.swift` | 共享页面导航入口。 | 普通导航不暴露 backend。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/WebContentView.swift` | WebView 与加载状态容器。 | 使用严格握手后的固定 localhost。 |
| `macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/WebView.swift` | WKWebView、origin/main-frame 限制、bridge、上传面板和打印子窗口策略。 | 通用 bridge 只向预期主框架开放；打印仅 exact `about:blank` 到同端口受控 job 路由；皮肤仅单 ZIP。 |
| `macos/InvoiceHubMac/Tests/InvoiceHubClientTests/BackendPathResolverTests.swift` | 路径、握手、所有权、关闭、Web origin 和打印子窗口策略契约。 | macOS 壳改动的最低 Swift 回归。 |

## 14. 自动化测试与样本

| 文件 | 主要覆盖 | 关联生产模块 |
|---|---|---|
| `tests/fixtures/sample_invoice.xml` | 最小结构化发票样本。 | extraction、summary、cost XML 链路。 |
| `tests/test_api_contract.py` | API 字段、设置、关闭、诊断、SSE、皮肤、成本、选择合计和重命名。 | `api/app.py`、`AppState`、skins、costs、summary。 |
| `tests/test_file_preview.py` | 预览 job、来源复核、分页、文本、容量与安全边界。 | file_preview、document_rendering、AppState、API。 |
| `tests/test_file_preview_frontend_contract.py` | 首页预览 DOM、交互和静态资源契约。 | index.html、page-index.js、app.css。 |
| `tests/test_documents.py` | 单据状态、预览、人民币大写、模板扩行、导出和路径限制。 | documents、AppState documents API。 |
| `tests/test_frontend_contract.py` | 模板、JS、CSS、资源版本、表格、SSE、设置和皮肤静态契约。 | `web/**` 与 API 字段名称。 |
| `tests/test_invoice_printing.py` | 同票 PDF 选择、打印 job、分页、过期和容量边界。 | invoice_printing、document_rendering、AppState、API。 |
| `tests/test_invoice_print_frontend_contract.py` | 首页批量打印和受控打印页的前端契约。 | index.html、invoice_print.html、page-index.js。 |
| `tests/test_invoice_classification.py` | 两维分类、上下文证据、PDF/OFD、表头和候选校验。 | classification、parsers、cost analysis、summary。 |
| `tests/test_monitoring.py` | PID、坏状态恢复、同步、lock、bridge 和文件事件。 | monitoring、targets、storage。 |
| `tests/test_paths.py` | TargetProfile、成本路径和冲突隔离。 | targets、skins。 |
| `tests/test_release.py` | core ZIP 排除规则和脱敏配置。 | release/build_core。 |
| `tests/test_build_manifest.py` | build ID、清单字段、能力、脚本 PID CAS 和 macOS 静态契约。 | release/build_manifest、macOS 脚本和生命周期。 |
| `tests/test_dependency_lock.py` | 平台锁、Python 3.14、哈希与版本单一真值。 | dependency_lock、requirements。 |
| `tests/test_release_identity.py` | 版本、package ID、manifest 和源码许可身份。 | version、package/runtime manifest、pyproject。 |
| `tests/test_sbom.py` | CycloneDX 输出的确定性和 lock identity。 | release/sbom。 |
| `tests/test_source_snapshot.py` | clean commit 源码快照、排除/秘密与确定性。 | release/source_snapshot。 |
| `tests/test_release_provenance.py` | 真实包/收据/源码/Tag 的 finalizer、Sparkle ZIP 路径和重复条目边界。 | release/provenance。 |
| `tests/test_update_metadata.py` | latest/appcast schema、三产物/core/source/EdDSA parity。 | release/update_metadata。 |
| `tests/test_update_service.py` | 白名单、重定向、超时/大小、ETag/cache、版本与契约状态。 | services/update_service。 |
| `tests/test_settings_migration.py` | 配置/偏好白名单、备份、Windows browser 归一和业务排除。 | release/settings_migration。 |
| `tests/test_polling_observer.py` | macOS polling observer 的事件/停止契约。 | monitoring/polling_observer、daemon。 |
| `tests/test_windows_release_contract.py` | Windows BAT/PS1/module/manifest/browser/stale 静态契约，以及 fresh PowerShell 初始化器、浅源归档和确定性磁盘阈值动态契约。 | scripts/windows、scripts/dev Windows 发行链；初始化器成功路径不得依赖宿主临时卷余量，低于配置阈值必须失败且不写 receipt。 |
| `tests/test_macos_release_contract.py` | Mac runtime/build/verify/Sparkle/签名脚本静态契约。 | macOS 正式发行文件。 |
| `tests/test_api_bookkeeping.py` | 做账 API、错误模型和废弃接口 410。 | AppState、api、bookkeeping。 |
| `tests/test_bookkeeping_decisions.py` | W9 会计决定与提案 revision。 | decisions、vouchers。 |
| `tests/test_bookkeeping_export.py` | 批次 manifest、XLSX、签名和 finalize。 | import_file、batches、validator。 |
| `tests/test_bookkeeping_mapping.py` | 映射影响预览、CAS、胜者和定向重算。 | mapping、repository。 |
| `tests/test_bookkeeping_mapping_migration.py` | 映射 v1/v2 preview/apply。 | mapping_migration。 |
| `tests/test_bookkeeping_profile.py` | 账套、科目和辅助档案绑定。 | catalogs、validator。 |
| `tests/test_bookkeeping_projection.py` | 凭证生成、posting key 和 revision。 | vouchers、status。 |
| `tests/test_bookkeeping_status.py` | 严格状态仓储与迁移。 | repository、status。 |
| `tests/test_bookkeeping_validator_w9.py` | W9 可执行性 blockers。 | validator、decisions、catalogs。 |
| `tests/test_runner_dryrun.py` | batch-bound dry-run 与禁止猜测最新文件。 | runners、scripts/tools。 |
| `tests/test_summary_and_costs.py` | 金额防污染、同票纠偏、结构化成本、均价、参考状态和 schema 刷新。 | extraction、summary、cost_analysis、costs。 |
| `tests/test_development_documentation.py` | 文件地图、链接、接口路由、基线、旧事实和敏感路径门禁。 | 本架构文档、README、AGENTS、CLAUDE 和 Git 指南。 |

## 15. 前端公共资源

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `web/static/css/app.css` | 全站布局、表格、状态、响应式和无皮肤默认样式。 | 所有普通模板引用；修改需更新模板 `?v=` 和前端契约。 |
| `web/static/css/settings-actions.css` | 首页/设置页操作、确认对话框和通知样式。 | `index.html`、`settings.html` 引用；版本参数需同步。 |
| `web/static/js/common.js` | API 包装、转义、表格 TSV、皮肤、SSE 和导航过渡。 | 所有页面 JS 依赖；SSE 页面通过 `connectEvents` 复用重连语义。 |
| `web/static/js/page-index.js` | 首页目录草稿、发票列表、筛选、预览续租/自动恢复、批量打印、勾选合计和 monitor 操作。 | 消费 settings/invoices/preview/keep-alive/print/selection/bridge API；弹窗关闭必须停止续租。 |
| `web/static/js/page-costs.js` | 成本标签、表格、行级加价和状态保存。 | 消费 preferences/cost-analysis/bridge API；对应成本工作簿 sheet。 |
| `web/static/js/page-detail.js` | 发票详情、成本拆分、手改和打开文件。 | 消费 invoice detail/manual/open API。 |
| `web/static/js/page-documents.js` | 入出库标签、目录草稿、预览、导出策略和打开操作。 | 消费 documents/preferences API，并监听汇总事件。 |
| `web/static/js/page-ocr.js` | OCR 候选目录和禁用服务状态。 | 消费 preferences/ocr API；当前不执行正式 OCR。 |
| `web/static/js/page-consistency.js` | 同票多格式一致性表。 | 消费 consistency-report API。 |
| `web/static/js/page-settings.js` | 设置中心、运行控制、重命名、偏好、诊断和关闭系统。 | 消费多数设置/bridge/documents/skins/ocr/diagnostics/shutdown API。 |
| `web/static/js/page-skins.js` | 皮肤 ZIP 导入、替换、启用和重置。 | 消费 skins API；不执行包内 JS。 |
| `web/static/js/page-bookkeeping.js` | 凭证人审、映射规则、账套设置和批次状态。 | 消费 `/api/v1/bookkeeping/*`，持续展示服务端 blockers。 |

## 16. 内置皮肤资产

| 文件 | 职责与关系 |
|---|---|
| `web/static/skins/animal-island/skin.json` | 内置皮肤 manifest，声明 id/name/version/entry；由 SkinService 读取。 |
| `web/static/skins/animal-island/skin.css` | 仅覆盖既有变量和选择器；引用同包字体、纹理。 |
| `web/static/skins/animal-island/asset-sources.json` | 字体和原创纹理的来源/许可记录。 |
| `web/static/skins/animal-island/fonts/noto-sans-sc-ui.woff2` | 本地 UI 字体子集；仅由 skin.css 相对引用。 |
| `web/static/skins/animal-island/fonts/nunito-ui.woff2` | 本地拉丁 UI 字体子集；仅由 skin.css 相对引用。 |
| `web/static/skins/animal-island/fonts/zen-maru-ui-400.woff2` | 本地常规字重子集。 |
| `web/static/skins/animal-island/fonts/zen-maru-ui-700.woff2` | 本地粗体字重子集。 |
| `web/static/skins/animal-island/textures/leaf-confetti.png` | 原创叶片纹理；不能替换为未授权游戏素材。 |
| `web/static/skins/animal-island/textures/paper-grain.png` | 原创纸张纹理；由 skin.css 相对引用。 |
| `web/static/skins/ink-pulse/skin.json` | 内置 Ink Pulse `1.3.0` manifest。 | 与 SkinService 内置版本和静态契约同步。 |
| `web/static/skins/ink-pulse/skin.css` | 分类、勾选详情、成本明细和关闭弹窗的深色印刷皮肤覆盖。 | 不改变业务 DOM；必须保留 `?no_skin=1`。 |
| `web/static/skins/ink-pulse/asset-sources.json` | Ink Pulse 字体和原创纹理来源/许可。 | 发布与皮肤安全审查使用。 |
| `web/static/skins/ink-pulse/fonts/OFL-DelaGothicOne.txt` | Dela Gothic One OFL 许可。 | 与对应本地字体文件一起分发。 |
| `web/static/skins/ink-pulse/fonts/OFL-ZCOOLKuaiLe.txt` | ZCOOL KuaiLe OFL 许可。 | 与对应本地字体文件一起分发。 |
| `web/static/skins/ink-pulse/fonts/dela-gothic-one-latin.woff` | 本地拉丁显示字体。 | 只由 skin.css 包内相对引用。 |
| `web/static/skins/ink-pulse/fonts/zcool-kuaile-ui.woff` | 本地 UI 字体子集。 | 只由 skin.css 包内相对引用。 |
| `web/static/skins/ink-pulse/textures/ink-field-v1.webp` | 原创墨场背景纹理。 | 包内静态资源，无远程依赖。 |
| `web/static/skins/ink-pulse/textures/ink-splatter-atlas-v1.png` | 原创喷墨纹理图集。 | 包内静态资源，无官方游戏素材。 |
| `web/static/skins/ink-pulse/textures/panel-print-v1.webp` | 原创面板印刷纹理。 | 包内静态资源，无远程依赖。 |

## 17. HTML 页面

| 文件 | 页面/消费者 | 主要关系 |
|---|---|---|
| `web/templates/base_head.html` | 当前未作为所有页面的运行时 include。 | 保存公共 CSS 片段，但真实模板仍独立维护版本参数。 |
| `web/templates/index.html` | `/` 首页。 | 引用 common、page-index、两份 CSS；真实表格和勾选合计 DOM。 |
| `web/templates/invoice_print.html` | `/invoices/print/{job_id}`。 | no-store 的受控打印页，只消费已创建 print job 的分页 URL。 |
| `web/templates/costs.html` | `/costs`。 | 引用 page-costs；标签与成本工作簿 sheet 对应。 |
| `web/templates/detail.html` | `/invoices/{invoice_key}`。 | bootstrap 注入 invoiceKey，page-detail 拉取数据。 |
| `web/templates/documents.html` | `/documents`。 | page-documents 管理入库/出库预览和目录草稿。 |
| `web/templates/ocr.html` | `/ocr`。 | 展示当前 OCR 未内置状态和候选文件入口。 |
| `web/templates/consistency.html` | `/consistency`。 | page-consistency 展示多格式冲突。 |
| `web/templates/settings.html` | `/settings`。 | page-settings 和 settings-actions；提供 `?no_skin=1` 恢复入口。 |
| `web/templates/skins.html` | `/skins`。 | page-skins 提供 ZIP 导入/替换/启用。 |
| `web/templates/bookkeeping.html` | `/bookkeeping`。 | W8/W9 人审、映射、账套和批次视图。 |
| `web/templates/backend.html` | `/backend` 高级诊断。 | 不注入皮肤；内联请求 health/settings/bridge，不出现在普通首要导航。 |

## 18. 生成物与非源码边界

以下路径不逐文件登记，因为它们是可变运行态或本机资产：

- `runtime/`、`运行状态/`：SQLite、PID、state、日志、偏好、皮肤和 TargetProfile 档案。
- `dist/`：core 构建产物。
- `发票文件/*.pdf|*.ofd|*.xml`：源业务发票。
- `发票文件/成本发票明细.csv`、`成本发票汇总.xlsx`、`成本开票状态.json`：成本投影。
- `.venv/`、`__pycache__/`、`.pytest_cache*`：开发缓存。
- 根目录 `.lnk`、`.playwright-cli/`、`ink-pulse/`、`ink-pulse.zip`、`output/`：当前本机验收或皮肤资产，不属于本架构基线。

这些内容不得被 `git add .`、发布构建或文档示例意外带入。


## 19. 相关入口

- [开发架构总入口](../DEVELOPMENT_ARCHITECTURE.md)
- [平台架构](PLATFORM_ARCHITECTURE.md)
- [接口与运行流程](INTERFACES_AND_FLOWS.md)
- [数据结构与算法](DATA_AND_ALGORITHMS.md)
- [Agent 任务导航](AGENT_TASK_MAP.md)
- [注释与设计原因地图](COMMENT_RATIONALE_MAP.md)
