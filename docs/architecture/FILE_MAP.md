# InvoiceHub 完整文件地图

## 2026-10-09 勾选工作流文件

| 文件 | 职责与联动 |
|---|---|
| `src/invoice_hub/platform/trash.py` | macOS Foundation / Windows IFileOperation 原生回收站适配；永久删除保护，无新增依赖 |
| `src/invoice_hub/services/invoice_trash.py` | 确认计划、源签名、逐文件持久意图与结果、幂等查询；由 AppState 活动目录锁及同步锁编排 |
| `web/static/css/selection-workflow.css` | 首页筛选、来源 disclosure、删除确认与详情返回；index/detail 模板共同加载 |
| `tests/test_selection_workflow.py` | 删除确认/部分失败/重启/失效/锁/COM契约、来源税率归属及详情身份测试 |
| `tests/selection_workflow.test.cjs` | 7003项预览、100项名称窗口、迟到响应、筛选口径及不重复删除测试 |

现有 API/app_state/cost_analysis 联动 page-index.js/page-detail.js 与 index/detail 模板。确认日志仅在包外运行态，不能进入源目录或打包输入。首页和详情的新资源版本为 `20261009-selection-6`，成本与单据继续 `20261009-progressive-3`。


## 2026-10-09 临时识别文件关系

- `src/invoice_hub/services/temporary_recognition.py`：独立子进程识别、源签名/内容校验、可重建会话缓存与设置。
- `src/invoice_hub/api/temporary_recognition.py`：选择、拖入登记、会话、重命名、删除和设置路由，由 `api/app.py` 注册并关闭 worker。
- `web/templates/temporary_recognition.html`、`web/static/css/temporary-recognition.css`、`web/static/js/temporary-recognition.js`：首页弹窗、排序、历史、表格及设置页控制器。
- `tests/test_temporary_recognition.py`、`tests/temporary_recognition.test.cjs`：独立来源、顺序、失效、重启、渐进进度、选择器和迟到响应回归。
- 原生链联动 `platform/native_dialogs.py`、`platform/windows.py`、`platform/host_rpc.py` 与 `src-tauri/src/host_rpc.rs`、`src-tauri/src/main.rs`；不新增外部依赖。


## 2026-10-09 渐进读取文件关系

| 文件 | 职责与关系 |
|---|---|
| `src/invoice_hub/storage/read_views.py` | `ReadViews` 保存成本四标签完整代际；`ProgressiveRows` 追加首次解析的临时批次；供 summary/costs/AppState 使用 |
| `tests/test_progressive_loading.py` | 暂停第二张解析证明首批可见；分页/全量统计/缓存复用/写锁并发/失败临时数据/过期保存/单据按需预览回归 |

`TargetProfile.workspace_dir/read-views.sqlite3` 及 WAL/SHM 仅为可重建读取缓存，不作为发票主存储或发行输入。现有 `document_index.py` 增加成本 CSV 分组内存缓存与阶段性候选发布；三个 page 脚本继续由各自模板加载；成本与单据版本为 `20261009-progressive-3`，首页后续升级为 `20261009-selection-6`。未改变成本三件套所在目录。

## 税务工作台设计文件（2026-09-11）

| 文件 | 职责 | 实现状态与关联 |
|---|---|---|
| `docs/TAX_WORKBENCH_DESIGN.md` | 首页交互、独立公司资料绑定、证据/任务/API 草案与 D0—D5 计划 | 设计提案，不表示拟议工程文件已创建；关联算法规格及合成原型 |
| `docs/TAX_ALGORITHMS_AND_POLICY.md` | Decimal、价税、月度 VAT、附加、印花、季度所得税公式，官方依据和独立预期 | 记录已核对与待补证边界，不是现行生产规则包 |
| `docs/TAX_POLICY_SOURCES_AND_REVIEW.md` | 政策来源分级（A 官方原文 / B 解释与征管口径 / C 线索 / D 视频号自媒体）、四层政策中心、变更流水线、订阅与待办、覆盖声明与漏报保障、版本差异、运营成本与核验签署 | 设计与治理规格；本轮未执行抓取、轮询或外部请求，不新增未核验文号；D5 的前置约束 |
| `docs/TAX_WORKBENCH_VALUE_AND_READINESS.md` | 决策文档：会计痛点、计算器就绪度与草稿定位核查、政策中心价值与护城河、最小可用形态、开发者重新评估清单与停止条件 | 记录当前事实与判断，不是设计规格；结论可被实现推翻，推翻时同步更新本页 |
| `docs/design/tax-calculator-prototype.html` | 小图标/入口位置、紧凑 20 键、预设/自定义税率输入、税种切换/勾选、独立滚动的翻面/结果、资料选择模拟 | 自定义只校验输入并标记待重算；位置偏好仅会话内；选择器不打开真实系统窗口；不进入 `web/` 或包资源清单，无税务运算、业务 IO 或生产 API；图标 ISC 来源参照 `website/assets/LICENSE-lucide` |

## 多公司工作区设计原型（2026-11-01）

| 文件 | 职责 | 实现状态与关联 |
|---|---|---|
| `docs/design/workspace-sidebar-prototype.html` | 左侧模块列（含临时识别、↑ 更新入口）、可拖动调宽的公司 › 项目 / 目录侧栏与右键置顶、悬停全名卡片；目录页保留现有首页发票列表与勾选合计详情、右键标签；`⇄` 比较标签按关系勾稽（进销存、往来、抵扣），类目可点开明细、下方原始文件并排联动；首页标签可全部关闭（空白起始页），其他模块不显示标签并各自缓存对象与滚动位置；公司/项目票面汇总、原始凭证缩略图、缺失子目录创建与新建工作区向导；做账（可编辑凭证、年月小日历选所属期、记账日期、跨期单据、通用凭证导出、库存加权、工资社保、税费）；双击 `hi.` 刷新本页缓存；银行版式识别与余额链 | 单文件合成数据交互原型：进项、销项、流水、勾选清单由同一份合成账簿派生；不读写真实目录、不进入 `web/` 或包资源清单、无生产 API；仍是单活动监控目录。分阶段落地见 [产品待办 WS-01—06](../PRODUCT_BACKLOG.md#ws-01) 与 [BANK-01](../PRODUCT_BACKLOG.md#bank-01) |

2026-09-08 OFD 预览新增工程文件：

| 文件 | 职责与关系 |
|---|---|
| `src/invoice_hub/services/ofd_rendering.py` | 真实 OFD 页树、ZIP/XML 预检、组件身份/哈希、独立 worker 与 PNG 管道；由 file_preview 调用 |
| `scripts/dev/build_ofd_preview.py` | SHA 锁定输入下载、Java 编译、jlink、组件文件清单和独立 SBOM；无 Maven 构建入口 |
| `tools/ofd-preview/pom.xml` | OFDRW 依赖裁剪来源，供维护者重新解析依赖时对照 |
| `tools/ofd-preview/dependencies.lock.json` | 实际运行 JAR 的坐标、URL、长度、SHA-256 |
| `tools/ofd-preview/toolchains.lock.json` | Windows x64/macOS arm64 JDK 21 原包身份与解包入口 |
| `tools/ofd-preview/NOTICE.md` | 组件与保留依赖许可说明、源码来源；随组件携带 |
| `tools/ofd-preview/LICENSE-OFDRW` | OFDRW 的 Apache-2.0 许可证原文，随组件保留 |
| `tools/ofd-preview/src/main/java/com/invoicehub/ofd/Preview.java` | 只开放单页 PNG、字形/尺寸预检及私有二进制输出 |
| `tools/ofd-preview/src/main/java/org/slf4j/impl/StaticLoggerBinder.java` | 本项目实现的 SLF4J binding，把渲染告警转为失败而不记录发票文字 |
| `tests/ofd_preview_fixture.py` | 原创合成 OFD 页树、中文、金额、线框和测试图像，供单测生成临时文件 |
| `tests/test_ofd_rendering.py` | 结构安全、组件完整性、超时/并发、真实引擎与混选 API 回归 |
| `docs/OFD_PREVIEW.md` | 方案、实验决策、构建命令、容量与未覆盖项 |

生成物 `runtime/components/ofd-preview/`、`runtime/ofd-preview-qa/`、`runtime/ofd-build-cache/` 与 Maven `tools/ofd-preview/target/` 均 ignored。分发时组件位于内嵌 Python 的 `components/ofd-preview/` 并纳入外层 runtime tree/制品哈希；不得将任一平台 runtime 作为源码提交。

2026-09-08：[`v0.3.0-alpha.2` 双平台预览](https://github.com/lyc1126/InvoiceHub/releases/tag/v0.3.0-alpha.2) 已按所有者确认的验收范围发布。Windows x64 portable ZIP 与 macOS arm64 preview DMG 同源，包含校验和、收据和平台 Python SBOM；Mac 离线核验与实际默认配置验收通过，隔离 HOME 自动烟测仍未通过，未启用安装 updater 或更新 Feed。精确发布身份和限制见[分支与发布记录](../BRANCH_STATUS.md)。


- `docs/BRANCH_STATUS.md`：当前 `main`/文档分支身份、已清理与保留引用、同源双平台候选的 source/core/哈希边界，以及提交/推送/验收范围。

`state_dir/.invoice_monitor_status.lock` 是 `monitoring/state.py` 生成的短状态读写锁，与完整汇总锁分离；仅运行态使用，不作为 daemon 存活真值或发行输入。

| 新增路径 | 职责 |
|---|---|
| `src/invoice_hub/services/document_index.py` | 单据 spawn worker、逐文件缓存与进度；AppState 创建实例，`DocumentService` 调度 |
| `tests/test_document_index.py` | 真实进程停止/恢复、健康并发、变更/删除/隔离、过期身份 |
| `web/static/css/large-lists.css` | 首页/单据分页与加载控件尺寸，兼容皮肤和窄屏 |

运行产物 `runtime/local_state/documents/index/<scope>/files.sqlite3`（含 WAL/SHM）、`inbound.json`、`outbound.json`、`status.json` 只作派生缓存，不进入 Git/Release 或源目录。实际 runtime 随配置解析，Desktop 使用用户运行目录。

> 公共基线：经过审计的单一脱敏根提交及其公开后代；旧私有提交、Tag、包和验证材料不在公开图中。
> 当前治理变化以 `docs/release/HISTORY_SANITIZATION_EXECUTION.md` 为真值。公开门槛已完成；`v0.3` Tauri 2 开发分支已从 `main` 建立，已有经审查的 Cargo lock 和代码级生命周期边界。裸 checkout 缺 manifest 而 fail-closed；development assembler 已构建并隔离烟测一个本地 macOS arm64 `.app`，internal-alpha 也已完成 arm64 App/DMG/receipt verifier 与隔离启动烟测，尚无 Release。
> 本表覆盖当前受版本控制的全部工程文件，包括架构文档与文档契约测试；运行态、投影和本机未跟踪内容只登记生成规则，不使用会随增删文件失真的固定数量。
> 路径是导航键；职责和关系按符号而不是易漂移的行号描述。

新增排障入口：`docs/STARTUP_TROUBLESHOOTING.md`，面向公测的分阶段日志解读、单次 browser/desktop 参数与尚未发布/验收边界。

## 1. 如何阅读文件关系

2026-09-07 既有 Desktop 功能整合新增文件导航：

| 文件 | 职责与关系 |
| --- | --- |
| `src/invoice_hub/services/app_icons.py` | 四款内置图标、默认值和运行态保存，由 app_state/API 使用。 |
| `src-tauri/src/app_icon.rs` | 固定图标枚举、包内 PNG 解码及窗口/托盘更新，由 main 和 Host RPC 使用。 |
| `web/static/app-icon/website/icon_32.png`、`web/static/app-icon/website/icon_256.png` | 官网图标 favicon/选择预览，由当前图标生成器生成。 |
| `web/static/app-icon/orange/icon_32.png`、`web/static/app-icon/orange/icon_256.png` | 橙色图标 favicon/选择预览，来自已有公开分支。 |
| `web/static/app-icon/teal/icon_32.png`、`web/static/app-icon/teal/icon_256.png` | 青色图标 favicon/选择预览，来自已有公开分支。 |
| `web/static/app-icon/violet/icon_32.png`、`web/static/app-icon/violet/icon_256.png` | 紫色图标 favicon/选择预览，来自已有公开分支。 |
| `tests/test_app_icon.py` | 图标列表、状态、拒绝非法输入、host 失败与 favicon 契约。 |
| `src/invoice_hub/release/windows_alpha_metadata.py` | 现有 update_service 所需的 Windows alpha 元数据校验；不会自动发布或切换 Feed。 |
| `tests/test_windows_alpha_metadata.py` | alpha 元数据格式、身份和发布资产约束。 |
| `scripts/dev/smoke_windows_portable.ps1` | 已有 Windows BAT 验包脚本，检查进程归属和包内产物；不代表 Tauri EXE 验收。 |

现有文件同时恢复 WebView 目录/打印偏好、picker 调度、监控状态/同步进度和 Windows 启动恢复；工程路径不变。构建器仍仅 stage/build/verify，不提供发布动作。

2026-09-07 接入已有 Windows Tauri ZIP 工具：`scripts/dev/tauri_windows_portable.py` 负责干净快照 stage/build/verify；`src-tauri/tauri.windows.conf.json` 复用默认图标与固定端口构建 raw host；`src/invoice_hub/release/verify_tauri_windows_portable.py` 校验白名单、逐文件 SHA、manifest、GUI subsystem、runtime 与 receipt；`tests/test_tauri_windows_portable.py` 覆盖合法、篡改、缓存、官网越界和产品身份。官网只按 `website.py` 列表复制，不引入候选分支 Feed/handoff 工具。内置皮肤修改仍位于原有 CSS/manifest，不新增业务 DOM。

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

`services/app_state.py` 是组装根（ENG-03/ENG-08）：用例实现在 `services/` 下的领域服务里，路由以 `state.<服务>` 直接调用，按下表找对应文件；新逻辑写进领域服务，不加入 AppState。

<a id="directory-rules"></a>

## 目录规则

- `src/invoice_hub/domain`：领域模型与契约
- `src/invoice_hub/extraction`：PDF/OFD/XML/OCR 轻量提取
- `src/invoice_hub/projections`：CSV/XLSX/JSON 投影
- `src/invoice_hub/targets`：路径解析与运行态自愈
- `src/invoice_hub/api`：FastAPI 应用工厂、页面与共享请求辅助；领域 API 路由放 `api/routes/<领域>.py`，不再写回 `app.py`
- `src/invoice_hub/services`：业务服务
- `src/invoice_hub/platform`：Windows 启停、进程、通知、原生选择器、打开文件
- `src/invoice_hub/storage`：文件真值读写与 SQLite 任务/事件
- `src/invoice_hub/bank`：银行对账单/回单适配器、勾稽、回单匹配、建议分录、脱敏底稿，以及参考凭证草稿与捷锐导入文件（只读源文件与 `凭证/`，命令行入口）
- `src/invoice_hub/release`：发布构建与验收辅助
- `web`：模板与静态资源；`web/static/app/` 只放 `frontend/` 的提交构建产物，不手改
- `frontend`：Vue 3 工作区前端源码（Vite/TypeScript/Pinia/Vue Router/Vitest），新界面功能在这里实现，构建到 `web/static/app/`
- `scripts/windows`：正式 Windows 用户入口
- `macos/InvoiceHubMac`：macOS SwiftUI/WKWebView 本地壳与 SwiftPM 工程，负责 macOS 窗口、菜单、目录选择和本地后端进程控制；不得承载发票解析主逻辑
- `scripts/dev`：开发、Docker、门禁脚本
- `tests`：自动化测试与黄金样本
- `runtime`、`运行状态`、`dist`：本地运行态和发布产物，必须 ignored
- 根目录允许保留 `启动一站式发票汇总系统.bat`、`停止一站式发票汇总系统.bat`、`停止一站式发票汇总系统并停止监控.bat` 和本机生成的 `启动一站式发票汇总系统.lnk`，作为用户第一视图入口；`.lnk` 不纳入 Git。
- 根目录 `检查启动环境.bat` 为只读诊断入口，开发与测试可传 `-ConfigPath`；启动冲突必须给出可见提示、监听 PID 和可读取的程序路径，权限不足必须显式说明。诊断不能授予所有权或自动结束其他环境进程。Windows Desktop 单实例按安装路径与运行目录隔离，不同环境仍共用固定端口并明确拒绝冲突；正式 EXE 必须保留 InvoiceHub 的产品名和文件描述，托盘提供运行诊断。

## 2. 仓库根、配置与治理

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `.editorconfig` | 编辑器基础格式约定。 | 影响所有文本文件；变更需检查 PowerShell 5.1 的 BOM 特例。 |
| `.gitattributes` | Git 文本和换行属性。 | 以 `text=auto` 固定自动识别的普通文本为 LF，保持二进制 `-text`，BAT/PS1 与 BOM CSV 保留 Windows 换行；与 clean checkout 及跨平台 Git archive/Core Build ID 一致性相关。 |
| `.gitignore` | 排除 runtime、dist、缓存、快捷方式和投影。 | 与发布构建排除规则、工作区状态分类共同保护本机数据。 |
| `.github/workflows/ci.yml` | Windows x64 与 macOS arm64 非发布 CI，另含 ruff、Rust（macOS/Windows）与 Vue 前端作业。 | 默认浅 checkout，运行源码/发行/文档/脚本、Node 交互测试、`cargo fmt/clippy/test` 和前端类型检查/组件测试/提交构建可复现门禁；Windows clippy 暂只报告（ENG-01）；发布 Git 夹具必须自行兼容浅边界；`contents: read`，不签名、不上传 Release。 |
| `.github/workflows/macos-reference-shell.yml` | SwiftUI 参考壳的 `swift test`。 | 仅在 `macos/**`、`version.py`、`build_manifest.py` 或本文件变化时触发；参考壳已冻结，Tauri 是发行宿主。 |
| `.github/workflows/dco.yml` | 拉取请求的 DCO sign-off 检查。 | 遍历 PR 中的非 merge commits，缺少 `Signed-off-by` 即失败；合并前将其配置为 `main` 的 required check。 |
| `.github/dependabot.yml` | Dependabot 的 GitHub Actions 与 pip 周期更新配置。 | 仓库公开后由 GitHub 读取；不修改产品包或 release identity。 |
| `AGENTS.md` | 全仓库必读规则与按需阅读入口。 | 所有任务先读；跨模块任务再按本架构地图选读专题。 |
| `CHANGELOG.md` | 当前重构和旧项目迁移历史。 | 为复杂保护逻辑提供历史原因；任何项目变更都更新 `Unreleased`。 |
| `CLAUDE.md` | 兼容其他编码 Agent 的快速入口。 | 简短兼容入口，指向 `AGENTS.md`、功能规则索引和架构专题，不复制业务细则。 |
| `IMPLEMENTATION_STATUS.md` | 当前完成度、基线与未完成能力。 | 与 README、迁移清单和架构债务状态同步。 |
| `LICENSE` | AGPL-3.0-or-later 完整许可证文本。 | 进入源码快照和双平台成品；发布前仍需人工法律复核。 |
| `NOTICE` | 版权、AGPL、商标、贡献者版权和用户数据边界声明。 | 与 LICENSE、THIRD_PARTY_NOTICES 和公开仓库治理一致；不把用户发票或生成物自动纳入 AGPL。 |
| `CONTRIBUTING.md` | 贡献流程、最小验证和 DCO 说明。 | PR 必须带 sign-off；贡献者保留版权并按 AGPL-3.0-or-later 提交。 |
| `SECURITY.md` | 私密漏洞报告与安全范围说明。 | 公开仓库已启用 private vulnerability reporting；不得在公开 issue 贴秘密、发票或配置。 |
| `CODE_OF_CONDUCT.md` | 社区行为与处理边界。 | 适用于 issue、PR、review 和项目沟通。 |
| `PRIVACY.md` | 本地数据处理、更新请求和 GitHub 交互的隐私说明。 | 不引入遥测；公开贡献不得附真实发票、公司资料或凭据。 |
| `README.md` | 用户与开发者的首要运行说明。 | 链接正式入口、产物位置、测试和本架构文档。 |
| `THIRD_PARTY_NOTICES.md` | Python、Swift、字体与其它第三方依赖声明入口。 | 与依赖锁、SBOM、Sparkle/Python runtime 发行审查联动。 |
| `pyproject.toml` | Python 版本、依赖、pytest 和包元数据。 | 被本地测试、Docker、Windows Python 入口和 core 包使用。 |
| `package.json` | Tauri host 的 npm 产品身份、pnpm 版本和 JavaScript 直接依赖声明。 | 产品版本由 `tauri_version_sync.py` 从 `version.py` 派生；不承载业务前端。 |
| `pnpm-lock.yaml` | Tauri CLI/API 的完整 JavaScript integrity lock。 | 仅在显式 `--install-js` 或开发者手动 pnpm 安装时消费；不得用它替代 Cargo lock。 |
| `rust-toolchain.toml` | Rust/Cargo 1.85.0 与两首发 target 的固定工具链声明。 | `tauri_doctor.py` 诊断；无 Rust/Cargo 或 `src-tauri/Cargo.lock` 时 host 必须保持未就绪。 |
| `.cargo/config.toml` | Cargo 的 MSRV-aware 解析策略。 | 必须保留 `fallback`，避免直接 Tauri 版本不变时被较新的传递依赖悄然抬高到 Rust 1.85 以上。 |
| `requirements/runtime.in` | 双平台共享运行依赖输入。 | Windows/macOS 平台输入 include；不能直接替代哈希锁。 |
| `requirements/runtime-windows-x64.in` | Windows x64 运行依赖输入，含 watchdog。 | 编译为 Windows Python 3.14 哈希锁。 |
| `requirements/runtime-macos-arm64.in` | macOS arm64 运行依赖输入，不含 watchdog。 | 编译为 Mac Python 3.14 哈希锁；使用内置 polling observer。 |
| `requirements/dev.in` | 开发/测试依赖输入。 | 编译为开发哈希锁。 |
| `requirements/release-tools.in` | pip-tools 与 CycloneDX 等发行工具输入。 | 只用于构建/审计，不进入用户 runtime。 |
| `requirements/test-tools.in` | CI 测试工具输入。 | 让 CI 工具自身也经哈希固定。 |
| `requirements/lint-tools.in` | 静态检查工具（ruff）输入。 | 与 test-tools 分开，避免改动 Windows 重打包配置绑定的测试锁。 |
| `requirements/windows-x64-py314.lock` | Windows x64 Python 3.14 运行时哈希锁。 | runtime/package manifest、SBOM、wheelhouse 和验包共同核对。 |
| `requirements/macos-arm64-py314.lock` | macOS arm64 Python 3.14 运行时哈希锁。 | Mac embedded runtime、SBOM 与发布验证共同核对。 |
| `requirements/dev-py314.lock` | Python 3.14 开发依赖哈希锁。 | 开发环境与完整 pytest 使用。 |
| `requirements/release-tools-py314.lock` | 发行工具哈希锁。 | 生成/验证锁和 SBOM 的受控环境使用。 |
| `requirements/test-tools-py314.lock` | CI 测试工具哈希锁。 | CI bootstrap 使用，不进入成品。 |
| `requirements/lint-tools-py314.lock` | ruff 的 macOS arm64 / Windows x64 / Linux x86_64 wheel 哈希锁。 | 仅 CI lint 作业与本地开发安装；规则集在 `pyproject.toml` 的 `[tool.ruff]`，不进入成品或发布源码必需清单。 |
| `docker-compose.yml` | 开发/Mac 验证用测试容器。 | 调用 `scripts/dev/run_docker_tests.sh` 对应的 pytest 环境；不是 Windows 正式依赖。 |
| `config/app.local.json`（ignored 本机文件） | localhost 本机配置结构；不存在时由 `targets.load_config` 或 Windows 首启生成。 | 可能含真实路径，不纳入 Git、对应源码或成品；core 构建另写脱敏 `config/app.default.json`。 |
| `启动一站式发票汇总系统.bat` | 根目录正式启动入口。 | 转发到 `scripts/windows/启动localhost汇总页.bat`；修改后必须做正式 BAT 验收。 |
| `停止一站式发票汇总系统.bat` | 只停止 localhost 的固定入口。 | 转发到 `scripts/windows/停止localhost服务.bat`；不得停止 monitor。 |
| `停止一站式发票汇总系统并停止监控.bat` | 先停 monitor 再停 localhost。 | 转发到 stop-all BAT；语义不能被设置页偏好改变。 |
| `导入旧版设置.bat` | Windows 新目录安装后的显式设置迁移入口。 | 转发到白名单迁移 PS1；不复制业务文件和运行态。 |
| `发票文件/.gitkeep` | 脱敏默认 `watch_dir` 的空目录占位。 | core 包会重建同名目录；实际发票和成本产物不纳入 Git。 |

## 按需读取的功能规则

规则正文从 AGENTS.md 迁入以下专题；查找先读 [任务索引](AGENT_TASK_MAP.md#quick-lookup)。

| 文件 | 职责 | 关系与维护 |
|---|---|---|
| `docs/architecture/rules/INVOICE_EXTRACTION.md` | 发票提取、金额与同票分类的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/COST_ANALYSIS.md` | 成本明细与开票参考的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/MONITORING.md` | 后台同步、监控与关闭的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/WEB_UI.md` | 页面、单据、预览、打印与皮肤的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/BOOKKEEPING.md` | 业务资料夹与做账的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/TAX_WORKBENCH.md` | 税务工作台与税务计算器的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/WINDOWS.md` | Windows 正式入口与启动的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/MACOS.md` | macOS 平台与 SwiftUI 参考壳的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/TAURI_HOST.md` | Tauri 宿主、所有权与更新事务的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |
| `docs/architecture/rules/RELEASE.md` | 公开基线、构建与发行的强制约束。 | 从 AGENT_TASK_MAP 按问题进入；维护功能规则并回查对应源码与验收。 |

## 通用交接开发工具

| 文件 | 职责 | 联动与验收 |
|---|---|---|
| `scripts/dev/agent_handoff.py` | Agent 无关的线程引用映射、短摘要、按需详情、现场指纹、CAS、增量事件和中断恢复。 | 私有 JSON/Markdown 只写仓库外；交接协议、入口、合成回归。 |
| `scripts/dev/build_agent_handoff.py` | 从明确公开源码与固定运行时或可信旧包的 runtime 生成便携包及逐文件清单。 | 拒绝归档越界、私有成员与篡改；双平台运行限制分别记录。 |
| `docs/AGENT_HANDOFF.md` | 通用协议、命令、字段、恢复步骤及跨 Agent 接手入口；也是便携包说明。 | AGENTS/CLAUDE 共用，独立于厂商会话。 |
| `tests/test_agent_handoff.py` | 普通文件接力、并发 CAS、坏状态/断尾恢复、未知操作与私有目录边界。 | 不使用真实业务资料或模型 API。 |
| `tests/test_agent_handoff_packaging.py` | 合成 runtime 的白名单、复现、路径/哈希和包篡改拒绝。 | 合成平台载荷不冒充真实内嵌运行时或平台验收。 |

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
| `docs/legacy/OLD_WORKSPACE_CHANGELOG_INDEX.md` | 旧工作区功能与故障的脱敏回溯索引。 | 只提供类别、不变量和当前查询入口；原始非公开 Changelog 不得复制、链接或写入公开工作树。 |
| `docs/GIT_BRANCH_WORKTREE_FORK_GUIDE.md` | 分支、worktree、PR 和回退操作指南。 | 受 AGENTS Git 规则约束；稳定基线变化时同步。 |
| `docs/MAC_WINDOWS_WORKFLOW.md` | Mac 开发与 Windows 正式验收分工。 | 与 Docker、PowerShell、正式 BAT 和发布验收相关。 |
| `docs/MIGRATION_GAP_CHECKLIST.md` | 旧能力迁移缺口和验收状态。 | 功能迁移、验收口径和开发交接能力变化时更新。 |
| `docs/PRODUCT_BACKLOG.md` | 未来工作总览：设计稿与原型索引、已确认但未排期的优化与新功能、待修复缺陷，含编号、优先级、状态、证据、方案、验收标准与影响范围。 | 发现值得做但本轮不做的改进时登记；排期、完成或放弃时更新状态并链接 CHANGELOG；证据不得含真实业务数据。 |
| `docs/COST_ANALYSIS_V2_DESIGN.md` | 成本分析 v2 设计提案：已确认决策、公司级品目表（别名、库存科目、类型、税率）、成本基数（进项税是否计入、结存加权单价）、销项税率与计税方式、灵活定价规则（加价率 / 目标毛利 / 固定加价 / 合同价 / 阶梯 / 市场价底线）与 4 层优先级、页面结构、兼容迁移与落地顺序。 | 未实现；现行规则以 COST_ANALYSIS 规则页为准；落地拆分见 PRODUCT_BACKLOG 的 COST-06、COST-01—05 与 BUG-01。 |
| `docs/AGENT_ACCESS_DESIGN.md` | Agent 接入设计提案：参照 Vibe Island 接入形态，MCP 主通道与命令行兜底、本机 socket / 命名管道与配对令牌、L0—L2 能力分级与禁止项、灵活控制模型（预设 / 询问卡片 / 规则表）、辅助导入（Agent 起草版式档案或逐格更正、软件校验、暂存确认）、应用内审批与活动面板、一键安装适配器、分阶段与验收要点。 | 未实现；2026-11-09 确认先只读、WorkBuddy 优先；现行接口以 INTERFACES_AND_FLOWS 为准；落地拆分见 PRODUCT_BACKLOG 的 AGENT-01—04。 |
| `docs/MONITORING_AND_LOGGING.md` | monitor 状态、日志和诊断说明。 | 与 `monitoring/*`、MonitorBridge 和设置页运行状态联动。 |
| `docs/release/HISTORY_SANITIZATION_EXECUTION.md` | 公开历史净化、私有备份、候选内容审计、全 ref 验证和托管面复核的执行记录。 | 公开 Git 图、发布资产、仓库可见性或 Tauri 开发线变化前必须更新。 |
| `docs/release/TAURI2_EXECUTION_PLAN.md` | 公开 Tauri 2 分阶段计划、实验决策记录、重打边界和当前阻断项。 | 改动 Tauri host、依赖锁、生命周期、更新或平台验收时先更新实验记录。 |
| `docs/release/L11_A_INTERNAL_ALPHA_PLAN.md` | internal-alpha macOS arm64 App/DMG 的受限实验、构建身份与隔离启动烟测记录。 | 只记录内部评审证据；artifact、verifier、启动边界或保留/清理决策变化时同步，不能作为公开 Release、Feed、签名或公证依据。 |
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
| `scripts/dev/tauri_version_sync.py` | 从 `version.py` 同步或校验 npm、Cargo 与 Tauri 配置的产品身份。 | `--check` fail closed；`--write` 是唯一允许写派生版本的入口。 |
| `scripts/dev/tauri_doctor.py` | 不安装任何系统工具的 Tauri 环境、锁、固定 origin 与平台 SDK 诊断。 | `--require-ready` 在 Rust/Cargo/Cargo.lock 缺失时非零退出；不生成 lock。 |
| `scripts/dev/tauri_bootstrap.py` | 先校验版本再运行 doctor 的显式 bootstrap。 | 默认只诊断；仅 `--install-js` 可安装已锁定 JavaScript 依赖，绝不安装 Rust/证书/Xcode/Visual Studio。 |
| `scripts/dev/tauri-doctor.sh` | macOS/POSIX doctor 包装。 | 只转发到 Python doctor。 |
| `scripts/dev/tauri-bootstrap.sh` | macOS/POSIX bootstrap 包装。 | 只转发到 Python bootstrap。 |
| `scripts/dev/tauri-doctor.ps1` | Windows doctor 包装。 | 使用 `py -3` 或已解析的 `python` 转发；两者均缺失时明确 `exit 2`，不安装系统工具。 |
| `scripts/dev/tauri-bootstrap.ps1` | Windows bootstrap 包装。 | 使用 `py -3` 或已解析的 `python` 转发；两者均缺失时明确 `exit 2`，不安装系统工具。 |
| `scripts/dev/tauri_dev_app.py` | macOS arm64 Tauri development `.app` 的 allowlisted staging 与 app-only build 入口。 | 普通 `stage/build` 生成 updater-disabled schema-3 manifest；显式 `stage-recovery/build-recovery` 只写 L10-E 固定不可安装 tuple。build 接受绝对 pnpm 或绝对 Tauri CLI，只构建 ignored `.app`，不生成 DMG/更新归档、不签名/公证、不启动应用。 |
| `scripts/dev/tauri_recovery_smoke.py` | L10-E macOS arm64 authenticated startup-recovery 隔离 runner。 | 只接受 plist executable/identifier/version、host manifest、launcher hash 与 core build identity 一致的精确 recovery-smoke App；创建临时 HOME/state/runtime/watch、关闭自动更新检查并预置 scope marker。localhost allowlist 只有 health、bridge status 和 bridge stop；确认身份后停止临时 monitor，并只终止自己创建的进程组，绝不调用 update check/install。 |
| `scripts/dev/tauri_public_preview.py` | macOS public-preview DMG 组装入口。 | release profile 只允许精确 disabled updater；产物是 ad-hoc、未公证且与 internal-alpha receipt 隔离。pending receipt 仅用于一次内部 verifier pass，120 秒超时或任一 verifier 失败都会带 stdout/stderr 失败。 |
| `scripts/dev/verify_tauri_public_preview.py` | macOS public-preview DMG 与独立 receipt 验证器。 | 复核 public-release 身份、ad-hoc 签名、未公证状态与 staging 布局；默认拒绝 pending 或篡改 finalizer，只接受与实际 DMG SHA-256 精确绑定的 verifier output，不把 receipt 作为正式签名或公证证据。 |
| `scripts/dev/tauri_public_preview_smoke.py` | macOS public-preview 成品 smoke 入口。 | 从 mounted DMG 复制 App、复核 receipt/ad-hoc 签名并保留 quarantine；只经 LaunchServices 与隔离 `HOME` 启动，核验 health、monitor 和结构化退出，不允许 development state override 或任意 localhost 请求。 |
| `scripts/dev/tauri_windows_public_preview.ps1` | Windows NSIS public-preview 组装与验包入口。 | 先验证下载哈希，再按应用签名、NSIS、安装器签名顺序执行并比较包内 EXE。 |
| `scripts/dev/tauri_windows_preview_stage.py` | Windows public-preview 的 clean-source staging 入口。 | 复用 Windows portable 的源码白名单与敏感内容扫描，验证 3.14.6 runtime，写 NSIS package/build/SBOM/host manifest，并将其 SHA-256 编译绑定到 Tauri host。 |
| `docs/release/WINDOWS_PUBLIC_PREVIEW_CONFIG.json` | Windows public-preview 的受控 WebView2 下载、NSIS marker、包身份及安装器/SHA-256/receipt 名称锁。 | workflow 与 PowerShell 组包器必须先验证此处 SHA-256，不能以 URL 或版本号替代字节锁。 |
| `docs/release/WINDOWS_PUBLIC_PREVIEW_RUNBOOK.md` | Windows 10/11 x64 public-preview 的人工执行、取证和烟测手册。 | 只从最终精确 Tag 的 GitHub-hosted workflow 获取三项 artifact；强制两层 Authenticode、receipt/哈希、current-user 安装和未签名卸载器披露，不自动上传 Release。 |
| `.github/workflows/windows-public-preview.yml` | 仅 GitHub-hosted Windows runner、精确 Tag 手动触发的 SignPath NSIS public-preview 工作流。 | 使用两个 SignPath artifact configuration，复核内外层 Authenticode 与包内 EXE 字节一致性后，只上传安装器、SHA-256 和 receipt 三项 Actions artifact，不创建或修改 GitHub Release。 |
| `scripts/dev/tauri_alpha_release.py` | internal-alpha macOS arm64 clean-snapshot staging、Tauri App 构建、ad-hoc DMG 组装和 schema-4 receipt 入口。 | 只接受 allowlisted core、锁定 Python 3.14.6 runtime 和固定 manifest；默认拒绝 dirty source、用户状态、Windows 文件、updater/Feed/Release 输入；可用 `--tauri-cli` 绕过失效的 pnpm 包装层。 |
| `scripts/dev/verify_tauri_alpha.py` | internal-alpha App/DMG/receipt 的独立 fail-closed 验证器。 | 校验 manifest、launcher/runtime/package/build SHA、布局、架构、ad-hoc 签名和平台污染；不把 receipt 单独当作正式签名、公证或发布证据。 |
| `scripts/tools/jierui_probe_template.py` | 捷锐模板探测辅助入口。 | 只生成或核对结构性事实，不写真实凭证状态。 |
| `scripts/tools/jierui_voucher_import.py` | 随包 runner 包装。 | 转发到 `invoice_hub.runners.jierui_voucher_import`，要求显式 batch manifest。 |
| `scripts/windows/run_monitor_status.ps1` | monitor 状态 CLI 包装。 | 解析 Python，调用 `invoice_hub.monitoring.control status`。 |
| `scripts/windows/run_start_localhost.ps1` | localhost 正式启动器。 | 读配置、准备 runtime、启动 uvicorn、探测首页、写 PID/state/log 与 PowerShell version/edition/home 诊断并拉起浏览器。 |
| `检查启动环境.bat` | 源码/测试环境只读启动诊断入口。 | 转发正式启动器的 `-Diagnose`，支持 `-ConfigPath/-NoDialog`，不依赖 Python 可用或获取启动锁。 |
| `scripts/windows/run_start_monitor.ps1` | monitor 启动包装。 | 调用 `monitoring.control start`，成功由 ready 握手决定。 |
| `scripts/windows/run_stop_localhost.ps1` | localhost 停止实现。 | 处理 PID、仓库进程和 `server_state.json`；不调用 monitor stop。 |
| `scripts/windows/run_stop_monitor.ps1` | monitor 停止包装。 | 调用 `monitoring.control stop`，支持超时参数。 |
| `scripts/windows/InvoiceHub.Windows.psm1` | 正式 Windows 公共启动/停止真值与浏览器派发。 | 严格识别包、Python、PID、模块、root/config/port；venv 转发后的 executable 与命令行首项分别匹配可信解释器集合；health 从原始响应流按 UTF-8 解码后再比较中文路径身份；负责槽位冲突隔离。 |
| `scripts/windows/import_previous_settings.ps1` | 旧包到新包的白名单迁移包装。 | 调用 `release.settings_migration`；拒绝同根目录。 |
| `scripts/windows/创建根目录快捷方式.ps1` | 生成本机 `.lnk`。 | 目标是根启动 BAT；生成物 ignored。 |
| `scripts/windows/启动localhost汇总页.bat` | PowerShell 7 优先、5.1 后备的启动 BAT。 | 先验证 Program Files PS7，再解析 PATH/App Execution Alias；保留强制 5.1，调用 `run_start_localhost.ps1`。 |
| `scripts/windows/停止localhost服务.bat` | localhost 停止 BAT。 | 使用同一 Program Files/PATH PS7 选择规则调用 `run_stop_localhost.ps1`；保持“只停 WebUI”语义。 |
| `scripts/windows/停止localhost服务并停止监控.bat` | stop-all BAT。 | 使用同一 PowerShell 选择规则先调 monitor stop，再调用 localhost stop BAT。 |
| `scripts/windows/导入旧版设置.bat` | 包内设置迁移 BAT。 | 使用同一 Program Files/PATH PS7 与强制 5.1 规则；参数原样传给迁移 PS1。 |

## 4.1 Tauri host lifecycle boundary

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src-tauri/Cargo.toml` | Tauri host package metadata, including the explicit `tray-icon` feature, exact direct Tauri/plugin/HMAC dependencies, Unix-only `libc` for descriptor-pinned marker storage, and pinned Windows-only `windows-sys` for handle-relative/no-reparse marker storage. | Version is derived by `tauri_version_sync.py`; direct crates are pinned to published releases and must match `Cargo.lock`. The Windows dependency documents a source-level boundary only and does not imply Windows runtime acceptance. |
| `src-tauri/Cargo.lock` | Reviewed Rust 1.85-compatible Cargo dependency graph. | Generated only in the controlled toolchain with `.cargo/config.toml`; it locks dependency integrity. Runnable development behavior additionally requires the staged manifest/launcher binding, and remains distinct from release evidence. |
| `src-tauri/build.rs` | Tauri build-script entry point. | It runs only with the exact direct crate versions and reviewed `Cargo.lock` in a controlled Rust environment. |
| `src-tauri/src/startup_diagnostics.rs` | 原生启动/运行诊断与 Windows 单实例标识派生。 | OS 监听 PID、进程路径/父进程、受限公开 health 字段；原生提示与本地日志；不授权、不停止进程。 |
| `src-tauri/tauri.conf.json` | Derived product identity, fixed localhost development origin, no config-created WebView, and disabled bundling configuration. | Must retain `http://127.0.0.1:8766`; `main.rs` creates a WebView only after the owned-backend handshake. |
| `src-tauri/tauri.dev.conf.json` | Development-only bundle configuration. | Enables only the macOS arm64 app bundle used by `tauri_dev_app.py`; it cannot be reused for DMG/NSIS, release signing, or updater inputs. |
| `src-tauri/tauri.alpha.conf.json` | Internal-alpha bundle configuration for version `0.3.0-alpha.1`. | Enables only the isolated allowlisted App resources staged by `tauri_alpha_release.py`; updater remains disabled and this config is not a public Release or notarization input. |
| `src-tauri/tauri.public-preview.conf.json` | macOS arm64 public-preview bundle configuration. | 只为 `tauri_public_preview.py` 的独立 staging 组装 release-profile DMG；host manifest 必须精确禁用 updater，不能携带 Feed 或公钥。 |
| `src-tauri/tauri.windows-preview.conf.json` | Windows x64 current-user NSIS public-preview bundle configuration. | 只接收 Windows staging、offline WebView2 installer 和无 Tauri 签名的 NSIS 打包；应用与外层安装器由 SignPath 分两步签名。 |
| `src-tauri/capabilities/no-webview-ipc.json` | Explicit zero-permission capability for the future main WebView. | Native picker access cannot become Tauri command/event IPC. |
| `src-tauri/src/lib.rs` | Fixed backend host/port constants and module exports. | Do not add business-core logic; lifecycle and Host RPC retain this origin invariant. |
| `src-tauri/src/local_http.rs` | 固定 loopback 消费者共用的有界 HTTP framing、总时限读取与脱敏错误，含传输边界回归。 | backend 启动/关闭及只读诊断使用；不提供连接、代理、任意 URL 或 ownership 授权。 |
| `src-tauri/src/backend.rs` | Bundle-manifest parsing with raw-byte SHA-256 compile binding, development/internal-alpha/release profile separation, fixed arguments, backend child ownership, HMAC challenge response, identity/OpenAPI handshake, post-preference fresh ownership revalidation, structured keep-monitor shutdown, strict child-exit confirmation, explicit confirmed kill/wait fallback, 100 ms bounded child-exit revocation, cloneable `BackendLifecycleAuthority`, private ownership-secret retention, and updater-runtime activation delegation. | The ordinary development and internal-alpha assemblers inject the compile hash while keeping updater disabled; development can enable only the exact L10-E unreachable endpoint/non-signing-key tuple with no extra updater fields. A bare checkout or mismatch exits `78`. Activation passes strict `runtime_dir`, secret, and shared authority to Host RPC only after gate release and app-state registration. |
| `src-tauri/src/monitor_recovery.rs` | Source-only lifecycle lease, fail-closed monitor pause/restore transaction, strict scope-bound marker schema, Unix descriptor-pinned/no-follow marker primitives, and platform store selection. | Every marker or bridge action requires the same released owned lease; ready-only pause and later ready restore preserve recovery obligations. For stores following the marker-store protocol, Unix whole-operation `load/publish/clear` serialization is closed by directory `flock`; stale-clear re-reads under the lock, and publish/clear sync directory metadata after the final link/unlink. Same-user direct edits bypassing the protocol remain outside the guarantee. Windows implementation lives in `monitor_recovery/windows_marker_store.rs`; other non-Unix storage returns unavailable. The module remains transport/updater agnostic and is adapted by Host RPC rather than acquiring public authority itself. |
| `src-tauri/src/monitor_recovery/windows_marker_store.rs` | Windows handle-relative marker store: opens and validates a directory handle, uses NT `RootDirectory` leaf opens and no-replace rename, rejects reparse/non-regular targets, and flushes marker data before the final operation. | Marker operations remain relative to the already-open directory handle and never resolve a caller-supplied path by name; a minimal `x86_64-pc-windows-msvc` temporary crate cross-compile passed, but there is no Windows runtime evidence and the full Tauri Windows target check remains blocked by `ring` requiring `assert.h`. |
| `src-tauri/src/monitor_bridge.rs` | Fixed-loopback `PythonMonitorRecoveryBridge` adapter with bounded direct TCP requests and authenticated status/stop/start request/response transcripts. | Endpoint, method and empty body are fixed; no caller URL/path/body or proxy is accepted. Each request uses a fresh challenge and HMAC-SHA256 under the backend-private secret without sending that secret; the exact status/body response requires one constant-time-verified proof. The recovery transaction still revalidates the released lifecycle before and after every bridge action, and ordinary browser bridge calls are not promoted into this authenticated updater authority. |
| `src-tauri/src/update_coordinator.rs` | Pure trait-injected update transaction, `VerifiedUpdate` boundary, strict verify -> pause -> install -> relaunch ordering, and restore-attempt preservation. | Installer never receives raw unverified bytes; candidate mismatch fails before pause/install/relaunch. It does not download, call Tauri updater, persist state, stop a real monitor, or request a platform restart. |
| `src-tauri/src/host_rpc.rs` | Private random-loopback listener, exact-origin/token/enum authorization, native picker dispatch, host-owned full updater candidates, authenticated startup restore, deferred private commit, Tauri updater adapters, and platform relaunch state. | The token and retained `Update` metadata never enter Web/Tauri IPC/Python API/logs/descendants. The listener expires a generation-checked 300-second candidate; metadata and download use 5-second timeouts. Enabled runtime activates only after gate release/manage and restores the marker first. Install atomically consumes one fresh candidate, reserves/spawns a latch worker, flushes exact success, then executes built-in verified download -> pause -> install -> relaunch. Writer/spawn/latch loss is `CommitLost` with no side effects; failed restore/transaction blocks further updater work. Windows confirms backend exit in `on_before_exit`; macOS prepares and requests restart. |
| `src-tauri/src/main.rs` | Loads a compiled-bound bundle manifest, installs single-instance/dialog/host-only-opener plugins, creates a custom macOS application Quit item with Cmd-Q, launches and registers `BackendHost`, activates the updater runtime after the released gate, initializes the selected surface, and routes `ExitRequested` through update-aware confirmed shutdown. | A checkout without the manifest exits `78`. Setup keeps the child local until tray/surface success and confirms cleanup before returning errors. Updater activation failure leaves backend/WebUI diagnostics available; successful activation emits only a non-sensitive recovery-runtime diagnostic used by L10-E. Tray Quit and custom Cmd-Q share `app.exit(0)`; reserved/executing commits block ordinary Quit, macOS `relaunch_prepared` skips duplicate shutdown, and other received exits require structured shutdown plus confirmed kill/wait fallback. |
| `src-tauri/boot/index.html` | Inert local boot asset required by the minimal Tauri configuration. | It is not a replacement frontend; the real application remains the existing localhost Web UI. |
| `src-tauri/icons/icon.png` | 512px desktop 图标 04，Tauri 窗口与托盘输入。 | 固定 8-bit RGBA；由纸白母版生成，IHDR 契约防止 tray 初始化失败。 |
| `src-tauri/icons/desktop-04.png` | 官网纸白底、墨黑 `hi.`、荧光折角的 1024px RGBA 母版。 | `generate_desktop_icon.py` 确定性生成；与平台容器保持一致。 |
| `src-tauri/icons/icon.ico` | Windows 多尺寸默认图标。 | 16/20/24/32/40/48/64/128/256px；tauri.conf.json 显式接入。 |
| `src-tauri/icons/icon.icns` | macOS 多尺寸默认图标。 | 最大 1024px；与 PNG/ICO 同母版，不代表新包已构建。 |
| `src-tauri/icons/README.md` | 第四款设计、生成命令、平台接线和字体许可。 | 图标更新同步。 |
| `scripts/dev/generate_desktop_icon.py` | Pillow + 包内 Dela Gothic One 字体的确定性图标生成器。 | 生成四个图标资源；不依赖本机字体或联网。 |
| `src-tauri/README.md` | Lifecycle scope, development assembly, and release boundary. | Update together with the execution plan whenever Cargo, lifecycle, Host RPC, updater, staging, or packaging status changes. |
| `src-tauri/tests/monitor_recovery_contract.rs` | Focused transaction and Unix marker-store contracts. | Covers ready/stopped monitor paths, marker corruption/scope/pending state, gate/lease loss, bridge failures, Unix serialization/republication and symlink rejection; it does not invoke a real monitor or updater. |
| `src-tauri/tests/update_coordinator_contract.rs` | Pure update coordinator contract tests. | Covers verified-artifact promotion, candidate mismatch, ordering, pause/install/relaunch failures and restore-attempt preservation; it does not download, install or restart. |
| `src-tauri/tests/windows_marker_store_contract.rs` | Windows marker-store source/static contract. | Locks handle-relative `RootDirectory`, no-reparse/no-replace behavior and platform gating; the minimal Windows cross-compile passed, but Windows runtime is unverified and the full Tauri target check remains blocked by `ring`/`assert.h`. |

## 5. Python 包入口与 API

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/__init__.py` | 包说明和 `__version__`。 | 被包导入和发布元数据使用；版本策略变化时同步发布文档。 |
| `src/invoice_hub/version.py` | 产品/包版本、API 契约、通道、链接、白名单和 package ID 单一真值。 | Python、Swift 脚本、manifest、About、Feed 与测试必须一致。 |
| `src/invoice_hub/website.py` | 随包官网资源白名单、路径校验与精确复制。 | `/website/`、Core Build ID、源码快照、Windows/Tauri/Swift 组装共用；许可证随资源分发，维护脚本不公开。 |
| `src/invoice_hub/api/__init__.py` | 惰性导出 `create_app`。 | 保持外部工厂入口，同时避免执行 `api.main` 前抢先实例化默认 AppState。 |
| `src/invoice_hub/api/app.py` | FastAPI 应用工厂：生命周期、静态资源与缓存中间件、页面/官网/打印页/`/workspace` 路由、health 与桌面握手，并按固定顺序组合 `api/routes/` 路由组。 | 上游是浏览器与桌面宿主；下游是 `AppState`、模板和路由组。路由组按原位置 `include_router`，改动顺序前须核对重叠路径（如 `/api/v1/invoices/{invoice_key}`、`/api/v1/skins/{skin_id}/…`）。 |
| `src/invoice_hub/api/common.py` | 请求辅助：`_state`、同源/原生选择器/更新来源校验、桌面 host challenge、三条 monitor recovery route 的认证 transcript、做账错误映射、SSE 游标。 | 被 `app.py` 与全部路由组共用。普通 bridge 调用保持原语义；只有带完整 recovery 认证头、空 body 且 challenge 未重放的 host 请求才执行 HMAC 校验并签名精确响应；四条 picker route 与 update install 继续把 private failure 映射为固定脱敏 503。 |
| `src/invoice_hub/api/routes/__init__.py` | 路由组包说明。 | 新领域 API 在此目录新增模块并由 `create_app` 显式组合。 |
| `src/invoice_hub/api/routes/settings.py` | About、更新检查/安装、设置、偏好、诊断与 watch_dir 选择/校验/改名路由。 | `AppState` 设置与更新服务；picker 与 update install 走 `common` 的脱敏 503。 |
| `src/invoice_hub/api/routes/invoices.py` | 发票列表、删除所选、勾选合计、原票预览、批量打印与详情/手改/打开路由。 | `state.invoices/selection/preview_print` 与 AppState 的删除所选编排、`invoice_trash`、`file_preview`、`invoice_printing`；预览内容使用 `PREVIEW_CONTENT_HEADERS`。 |
| `src/invoice_hub/api/routes/costs.py` | 成本分析快照、分页视图、开票参考状态与打开汇总路由。 | `CostAnalysisService` 经 `AppState`。 |
| `src/invoice_hub/api/routes/documents.py` | 入库/出库单据状态、索引、目录与预览/导出/打开路由。 | `document_index` 与单据投影。 |
| `src/invoice_hub/api/routes/companies.py` | 公司清单路由（WS-07 第 1 步）：增删改查、子目录补建预览与确认；第 2 步的按公司只读目录与目录发票列表；`CompanyRegistryError` 映射为 `{ok:false, error:{code}}`，文件系统工作经线程池。 | 调用 `state.companies`；不得改变 `watch_dir` 或 monitor。 |
| `src/invoice_hub/api/routes/dossier.py` | 业务资料夹读取与打开路由。 | 做账与成本共用的公司资料夹。 |
| `src/invoice_hub/api/routes/appearance.py` | 皮肤列表/导入/替换/启用/重置/文件与应用图标路由。 | `skins`、`app_icons`；图标更新经 Host RPC。 |
| `src/invoice_hub/api/routes/monitor.py` | monitor bridge 状态、进度、健康检查、重建、启停与打开日志/运行目录路由。 | status/start/stop 经 `_monitor_recovery_response` 承载认证 transcript。 |
| `src/invoice_hub/api/routes/bookkeeping.py` | 做账生成、科目、凭证审阅/决定、映射规则与迁移、导出与导入批次路由。 | `bookkeeping/` 安全协议；错误经 `_bookkeeping_error_response`。 |
| `src/invoice_hub/api/routes/ocr.py` | OCR 设置、服务状态、选择与文本提取路由。 | 本地 OCR 正式包不内置。 |
| `src/invoice_hub/api/routes/system.py` | 一致性报告、任务、SSE 事件流与关闭服务路由。 | SSE 在关闭已受理后结束；关闭经 `shutdown_scheduler`。 |
| `src/invoice_hub/api/main.py` | 参数化 uvicorn CLI 入口。 | 读取 root/config/host/port 并设置环境后调用 `create_app()`，只构造一个 AppState（`api/app.py` 没有模块级实例，导入不会触发启动同步）；正式 BAT 当前直接启动 uvicorn app。 |

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
| `src/invoice_hub/targets/companies.py` | 公司清单的只读查找（WS-07），供 API 进程、monitor daemon 与后台同步子进程共用：清单路径、路径键/包含判断、根目录解析、`taxpayer_type_for`、`company_taxpayer_for(config, 目录, 月份)`；坏清单读作“无公司”。 | 唯一写入者是 `services/company_registry.py`；成本开票参考经它取纳税人类型（`projections/costs.py`、`monitoring/sync.py`、`services/costs.py`、`monitor_control.py`、`background_sync.py`）。 |
| `src/invoice_hub/targets/paths.py` | `AppConfig`、`Layout`、相对路径序列化、SHA1 `target_id`、冲突隔离，以及 `path_is_under_root` 受控根判断和 `profile_identity` 过期结果判断。 | 决定所有入口的路径解释；变更需覆盖路径、启动、monitor、打包和配置测试。 |

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
| `src/invoice_hub/projections/costs.py` | `CostProjectionService`，状态兼容、快照、参考状态保存与同步统计。另有 `read_only_inputs`：只读返回明细行、发票校验行、品目表与税务设置，供非监控目录的公司比较使用（不刷新、不写）。 | `services/costs.py`、monitoring 调用；输出 `/api/v1/cost-analysis` 契约。 |
| `src/invoice_hub/projections/cost_outbound.py` | 手动重新汇总时读取开具发票目录：按发票号去重多格式、只采用销售方为本目录进项购买方的票、按开票参考分组键汇总销项数量与金额；文件签名缓存与汇总写入 profile 工作区 `cost_outbound_files.json` / `cost_outbound_summary.json`。 | `costs.py::refresh_outbound` 调用，复用 `cost_analysis` 的解析与分组键；不写 `watch_dir` 或开具目录。 |
| `src/invoice_hub/projections/documents.py` | 入库/出库预览、无前缀大写金额、模板列宽/扩行/打印范围和原子导出。 | AppState documents 用例调用；只读入库明细按完整来源副本去重、冲突阻断。 |
| `src/invoice_hub/projections/document_templates/电子入库单模板.xlsx` | 入库单版式真值。 | `write_inbound_workbook` 读取；版式变化需跑单据渲染/单元格测试。 |
| `src/invoice_hub/projections/document_templates/电子出库单模板.xlsx` | 出库单版式真值。 | `write_outbound_workbook` 读取；版式变化需跑单据测试。 |

## 10.1 做账安全协议

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/bookkeeping/__init__.py` | 导出做账领域与服务入口。 | `services/bookkeeping.py` 做账用例和测试从此访问稳定符号。 |
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

## 10.2 银行流水底稿

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/bank/__init__.py` | 包说明与 `WORKPAPER_SCHEMA`。 | 底稿 JSON schema 变化需递增版本并同步数据算法第 4.6 节。 |
| `src/invoice_hub/bank/__main__.py` | `python -m invoice_hub.bank` 命令行入口，参数校验与默认输出目录。 | 只调用 `workpaper.run`；不写 `凭证/`，不连接账套或电子税务局。 |
| `src/invoice_hub/bank/models.py` | 标准记录：对账单、行、回单、税费明细、校验问题；Decimal 金额解析。 | 所有银行适配器的唯一输出契约；方向按企业视角。 |
| `src/invoice_hub/bank/boc.py` | 中国银行对账单（竖线表格）与电子回单（按坐标配对标签与值）适配器。 | 新增银行另写适配器并在 `workpaper.discover` 注册；未知版式必须报错不猜。 |
| `src/invoice_hub/bank/checks.py` | 逐行余额、页脚合计、月度衔接/断档、账面期初差额、重复行。 | 底稿“校验结果”来源；错误项须先于做账处理。 |
| `src/invoice_hub/bank/matching.py` | 流水行与回单匹配：流水号+金额优先，退到日期+金额+方向唯一。 | 多候选不猜，进入人工确认。 |
| `src/invoice_hub/bank/classify.py` | 往来角色推断与建议分录（手续费/利息/缴税拆分/自然人/客户/供应商/油卡）。 | 依据文本不得含户名；户名只在 `aux`，供脱敏统一替换。 |
| `src/invoice_hub/bank/redaction.py` | 私有/脱敏视图、HMAC 稳定化名、用途词白名单、泄漏扫描。 | 扫描命中即拒绝写出；密钥与对照表只在私有目录。 |
| `src/invoice_hub/bank/ledger.py` | 读取 `凭证/科目表.json`、辅助核算档案和映射规则；按名称路径定位末级科目。 | 找不到或不唯一时返回空编码，由草稿列入待补科目，不猜相近科目。 |
| `src/invoice_hub/bank/vouchers.py` | 凭证草稿生成：销项/进项发票、银行流水、待认证进项转出、月末增值税与附加、季度印花税；默认短摘要；账套读回（序时账）对账与补记；银行对账与月度核对；原件速查；`申报数据.json` 模板。 | 读 `workpaper.analyze` 结果与发票明细投影；只产出建议凭证，不写 `凭证/`。 |
| `src/invoice_hub/bank/jierui.py` | 凭证审核表（带边框、下拉审核）、读回审核表、逐张校验、按月写捷锐导入模板、`做账习惯.json` 与 `已导出凭证.json`。 | 只导出“通过”的凭证；任一凭证不合格则该月整月不导出；同一凭证签名不重复导出。 |
| `src/invoice_hub/bank/export_profiles.py` | 通用凭证导出（BK-01）：内部统一凭证模型 `Entry/Aux`、声明式配置 `Profile`；内置捷锐（已实测）、柠檬云与用友 T3/U8 文本（实验）；`profile_from_template/match_columns` 按上传模板表头同义词对列；`write` 写 xlsx 或 GBK 文本。 | 由 `jierui.export` 在写文件一步调用；页面经 `company_vouchers.export_formats/_export_profile`。守护测试 `tests/test_export_profiles.py`。 |
| `src/invoice_hub/bank/voucher_cli.py` | `python -m invoice_hub.bank.voucher_cli draft|export` 命令行。 | 输出到公司资料夹 `做账草稿/`；只读 `凭证/`。 |
| `src/invoice_hub/bank/workpaper.py` | 发现源文件（按首页识别版式；`parse_receipts=False` 时只解析对账单，供公司账簿）、分析、建表、原子写出私有与脱敏 JSON/XLSX、`往来单位.json` 合并。 | 两份底稿由同一构建函数经不同视图产出；不覆盖人工角色。 |

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
| `src/invoice_hub/services/__init__.py` | 导出 `AppState`、过期选择（来自 `errors.py`）、预览和打印异常及 `create_state`。 | API 应用工厂依赖。 |
| `src/invoice_hub/services/app_state.py` | 组装根：构造全部领域服务并作为公开属性暴露（`state.bookkeeping`、`state.settings` 等），持有 config、活动 TargetProfile 与 RLock，保留 health、切换 watch_dir（`update_settings`）与删除所选两条跨域编排；不再有转发方法（ENG-08）。 | 上接 API 路由与测试，下接 `services/` 下的领域服务；服务读共享状态一律经 provider，跨服务协作经 lambda 每次现查对方服务方法（对服务类或实例的打桩因此全局生效），由 `tests/test_appstate_service_wiring.py` 守护（含“AppState 不再长出转发”检查）。 |
| `src/invoice_hub/services/company_ledger.py` | 公司发票账簿纯算法 `build_invoice_ledger`（WS-07 第 3 步发票部分）：同票家族去重、三项金额与守恒判定、按月/季/年分期、期间范围、日期未识别、票面差额、各期纳税人类型、主体与跨目录提示，以及后端守恒校验。 | 由 `services/company_views.py::company_ledger` 调用；复用 `invoice_selection.selection_family_key/selection_money_value`。守护测试 `tests/test_company_ledger.py`。 |
| `src/invoice_hub/services/company_bank.py` | 公司账簿的银行流水（WS-07 第 3 步银行部分）：`list_files`/`list_bank_pdfs` 有界列出、`CachedFolderReader` 按文件签名缓存的只读解析（抵扣清单也复用）、`BankFlowReader`（只解析对账单）、`build_bank_ledger` 按账户与月/季/年汇总期初/收入/支出/期末、缺月与余额校验、对账单自检。 | 由 `company_views.py::company_ledger` 调用，复用 `bank/workpaper.discover`、`bank/checks.py`；不写公司资料夹，不后台扫描。 |
| `src/invoice_hub/services/company_deduction.py` | 抵扣核对（WS-07 第 4 步）：`parse_deduction_workbook` 读电子税务局“用途确认信息”导出（只认“发票”表、所属期与必需表头，空清单无所属期）、`read_deduction_lists`（相对路径命名、未识别清单）、`DeductionListReader`（签名缓存）、`build_deduction_check`（按号码匹配、当期/前期开票、清单有目录无、目录有清单无、未勾选、重复勾选、税额核对与后端校验）。 | 由 `company_views.py::compare` 调用；复用 `company_ledger` 的家族与月份规则；只读。 |
| `src/invoice_hub/services/company_inventory.py` | 进销存（WS-07 第 4 步）：`build_inventory_check` 按品类（`goods_family` 标准名称 + 单位，与账套库存商品明细一致）汇总两个目录的明细行，规格只作下拉细分；进货额按开票参考口径（不含税 + 不可抵扣税金），逐月调用 `bank.vouchers.cost_of_sales` 做月末一次加权；`read_book_inputs` 只读公司资料夹 `做账草稿/账套读回/序时账_*.txt` 与 `凭证/科目表.json`，期初经 `stock_opening` 取得，读回不足时按 0 起算并说明。 | 由 `company_views.py::_compare_inventory` 调用；复用 `bank/vouchers.py`（`load_booked`、`stock_opening`、`goods_family`）、`bank/ledger.py` 与 `projections/cost_analysis.py`。 |
| `src/invoice_hub/services/company_settlement.py` | 往来核对（WS-07 第 4 步）：`build_settlement_check` 应付/应收两向，户名唯一归属（含截断前缀）、本公司账户识别，红冲抵销 → 一对一同额 → 唯一 2—3 张组合的确定性匹配，未逐笔对应流水、非发票流水、户名不唯一，按往来单位的期初/本期/期末与守恒校验。 | 由 `company_views.py::compare` 调用；对账单来自 `BankFlowReader`；发票规则复用 `company_ledger`。 |
| `src/invoice_hub/services/company_payroll.py` | 工资社保（WS-05 第三阶段）：`read_excel`（两行表头按名称识别列，另读人员明细表）、`read_pdf`（文字层按 token 流识别 所属期 + 险种 + 11 个数值）、图片列为不识别；`_checks` 合计与费率核对；`mask_name/mask_id` 脱敏；`save_confirmed` 带 revision 写 `申报数据.json` 的 `社保明细`。 | 由 `company_views.py::payroll/save_payroll` 调用；草稿计提在 `bank/vouchers.py`。守护测试 `tests/test_company_payroll.py`。 |
| `src/invoice_hub/services/source_move.py` | 属期文件夹核对与移动（WS-05 第二阶段）：`folder_period` 只解析文件夹名作提示，`period_folder_check` 按内容期间（抵扣清单税款所属期、单月对账单）对照；`SourceMoveService` 计划 → 确认 → 逐文件签名复核、fsync 意图、无覆盖改名、记录结果，日志在 `runtime/local_state/source-moves/`。 | 由 `company_views.py::period_folders/prepare_source_move/confirm_source_move/source_move` 调用；复用 `company_deduction.parse_deduction_workbook`、`bank/workpaper.discover`。守护测试 `tests/test_source_move.py`。 |
| `src/invoice_hub/services/company_same_number.py` | 同号检查（WS-04）：`build_same_number_check` 按 `selection_family_key` 合并每边的发票（同票多格式只算一张），列出两边都有的号码并判断疑似重复 / 双方同一张票（两家公司一方开具一方取得），金额或销售方不同时标出；无号码的单列；校验从原始记录复算张数。 | 由 `company_views.py::same_number` 调用；复用 `invoice_selection.py`、`company_ledger.py`。守护测试 `tests/test_company_same_number.py`。 |
| `src/invoice_hub/services/company_projects.py` | 公司项目汇总（WS-03）：`remark_projects` 从成本明细读备注项目名称，`ProjectAssignmentStore` 读写公司资料夹根目录 `项目归属.json`（revision、锁、损坏拒绝覆盖），`build_project_summary` 按项目归集并与发票账簿交叉校验。 | 由 `company_views.py::company_projects/save_project_assignments` 调用；复用 `company_ledger`。 |
| `src/invoice_hub/services/company_vouchers.py` | 凭证草稿审核（WS-05 第一阶段）：`list_drafts/read_draft/save_draft` 读写公司资料夹 `做账草稿/凭证草稿_*.xlsx` 的“凭证审核”表；读取用导出的 `read_review_xlsx`，校验用导出的 `validate`（只读 `凭证/科目表.json`、`辅助核算档案.json`）；保存带文件 SHA-256 revision，只改已有行的摘要、科目编码（同步科目名称）、借贷、供应商与审核列，以及所属期 / 记账日期（移月重编号、不能选未来月份），审核通过被拒时整批不写，原子替换；`_check_sheets` 只读返回草稿的核对表；`rebook_invoice` 写记入期调整并按记住的生成参数重新生成，`_source_documents` 给出发票凭证的同期 / 跨期；`draft_inputs/generate_draft` 按命令行同一入口生成草稿，覆盖前备份到 `做账草稿/历史/` 并按来源配对沿用审核（`_review_state/_identity/_carry_review`）；`export_draft` 在确认、制单人与 revision 复核后调用 `jierui.export`（与命令行同一输入与输出位置，进程内串行）。 | 由 `company_views.py::voucher_drafts/voucher_draft/save_voucher_draft` 调用；复用 `bank/jierui.py`、`bank/ledger.py`。守护测试 `tests/test_company_vouchers.py`。 |
| `src/invoice_hub/services/invoice_tags.py` | 发票标签（WS-06）：`InvoiceTagStore` 读写本机标签定义（校验、revision、整体替换）与公司资料夹 `发票标签.json` 标记（按发票号码），删除标签时按公司清除标记，读取时忽略已删除的标签。 | 由 `company_views.py` 调用（定义路径取公司清单同目录）；只用于显示与筛选。 |
| `src/invoice_hub/services/company_registry.py` | `CompanyRegistryService`：`runtime/local_state/companies.json` 的唯一写入者（RLock + revision CAS + 原子替换，损坏时保留原文件并拒写）；六类标准子目录与识别提示（前四类复用 `dossier.BUSINESS_DOSSIER_DIR_HINTS`）、纳税人身份生效期（`taxpayer_type_for`）、子目录补建 `plan_hash` 预览/确认与仅新建空目录。 | 上接 `api/routes/companies.py`；读活动 TargetProfile 只用于标记 `monitored`；`services/company_views.py` 从这里取公司与子目录，不把它当第二个 watch_dir；写入改变活动公司当月纳税人类型时回调 `state.costs.refresh_workbook_tax_profile`。守护测试 `tests/test_api_companies.py`。 |
| `src/invoice_hub/services/company_setup.py` | WS-02 确认后新建公司根 / 六类空目录并登记；与注册服务共用锁和校验，runtime 计划 / 排他执行标记 / 意图 / 观察持久化，失败保留、未知只查不重放。 | `CompanyRegistryService.setup`；`POST /api/v1/companies/setup-jobs` 与 confirm / GET；`tests/test_company_setup.py`。 |
| `src/invoice_hub/services/dossier.py` | `BusinessDossierService`：解析当前公司资料夹、一次有界扫描快捷入口/统计并限制打开路径（ENG-03 从 AppState 原样迁出；扫描上限常量也在此）。路由以 `state.dossier` 直接调用，做账经 `business_dossier_root()` 取公司目录。 | `/api/v1/business-dossier*` 和首页消费；不得改变 `watch_dir` 扫描语义；截断统计必须明确为下界。 |
| `src/invoice_hub/services/document_rendering.py` | MuPDF 文档打开和安全分页 PNG 渲染的共享适配。 | preview/print 共用；缺依赖、加密、空文档、页尺寸和渲染失败保持结构化错误。 |
| `src/invoice_hub/services/file_preview.py` | 短期源文件预览 job、闲置续租、页面/文本缓存、SVG/XML/图片安全边界。 | 保留已选源文件顺序；15 分钟闲置 TTL、页数、像素、作业数和缓存上限防止内存滥用。 |
| `src/invoice_hub/services/invoice_printing.py` | 短期同票 PDF 打印 job 和分页 PNG 缓存。 | 不持久化票面；只接收受控 PDF，过期/容量/加密失败明确返回。 |
| `src/invoice_hub/services/preview_print.py` | `InvoicePreviewPrintService`：把首页勾选转成当前 watch_dir 内的预览源/同票 PDF 打印源，创建 job、续租、读页与受限打开，并记录事件（ENG-03 从 AppState 原样迁出）。 | AppState 创建 `FilePreviewService`/`InvoicePrintService` 后传入（目录切换时由 AppState 清空；临时识别共用预览池）；勾选校验与同票分组/来源身份/文件格式规则直接取自 `invoice_selection.py`；创建预览持 AppState 同一把 RLock。 |
| `src/invoice_hub/services/invoice_list.py` | `InvoiceListService`：普通汇总 CSV 读取缓存、手改覆盖与手改写入、筛选/排序/统计、一致性分组、详情与打开源文件（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.invoices` 直接调用，并保留 `_clear_invoice_cache`/`_manual_overrides_path`/`_format_file_mtime` 供后台同步、重建、重命名、删除、诊断调用；缓存字段归本服务（测试经 `state._invoices` 访问）；列表构建持 AppState 同一把 RLock，手改写入持目标 profile 的 monitor 同步锁。 |
| `src/invoice_hub/services/invoice_rename.py` | `InvoiceRenameService`：按 `YY-MM-DD_销售方&购买方_金额元.ext` 批量重命名源发票，两阶段临时名、失败逆序回滚、手改覆盖随文件迁移、完成后重建（ENG-03 从 AppState 原样迁出，含命名格式常量）。 | 路由以 `state.rename` 直接调用；发票列表、monitor 状态、重建、目录检查、清缓存为其它服务的方法，以同名回调注入、每次现查。 |
| `src/invoice_hub/services/invoice_selection.py` | 首页勾选的同票分组/来源身份/金额/格式纯函数，以及 `InvoiceSelectionService`：按当前发票列表复核 `invoice_key + source_path`、勾选合计（ENG-03 从 AppState 原样迁出）。 | 单据、预览/打印直接依赖它；发票详情路由、AppState 的删除所选与路由经 `state.selection` 调用 `validated_invoice_selection`/`invoice_selection_summary`。发票列表来自 `InvoiceListService`，经回调每次现取（测试会在实例上替换）；合计持 AppState 同一把 RLock。 |
| `src/invoice_hub/services/background_sync.py` | `BackgroundSyncService` 与 spawn 子进程入口 `_run_background_sync_process`：首轮启动同步、代际与 TargetProfile 身份校验、过期结果 `server.background_stale`、旧子进程有界退役与结果等待上限（ENG-03 从 AppState 原样迁出，含超时常量）。 | AppState 与删除所选、切换目录经 `state.background.run_background_diagnostics` 触发（测试在本类上打桩以跳过启动同步），`health`/`bridge_progress` 读本服务的 `status`；测试对 `multiprocessing.get_context`、子进程入口与超时常量的打桩改为本模块。 |
| `src/invoice_hub/services/bookkeeping.py` | `BookkeepingService`：账套确认、科目/辅助核算查询、凭证生成/决定/审核、映射规则预览与保存、定向重算、捷锐导出与导入批次、状态/映射迁移（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.bookkeeping` 直接调用。活动 TargetProfile、config、公司资料夹与成本明细路径经回调实时读取，不缓存快照；写入先取 AppState 同一把 `_lock`，再取 `bookkeeping_write_lock`。 |
| `src/invoice_hub/services/company_views.py` | `CompanyViewService`（`state.company_views`，WS-07 第 2 步）：各子目录的投影身份、上次投影状态、有界只读的过期判断（`directory_freshness`），以及按目录的只读发票列表（临时 `InvoiceListService` 只调 `list_invoices`；活动目录交给 `state.invoices`）；`company_ledger` 取进项/销项两目录行交给 `company_ledger.py`。 | 上接 `api/routes/companies.py`；不建目录、不修复状态文件、不触发汇总。守护测试 `tests/test_company_views.py`。 |
| `src/invoice_hub/services/costs.py` | `CostService`：`CostProjectionService` 工厂、成本快照、分页视图、开票参考状态保存与打开成本汇总（ENG-03 从 AppState 原样迁出）。 | 与 `projections/costs.py` 分工：这里只决定读哪个 TargetProfile、持哪把锁，算法在投影层。每次调用在 AppState 同一把 RLock 下复制活动目标与加价率，再在该目标的 monitor 同步锁内读写；保存后清发票缓存经回调调用 `InvoiceListService.clear_invoice_cache`。 |
| `src/invoice_hub/services/diagnostics.py` | `DiagnosticsService`：诊断摘要、配置健康检查、日志尾部与脱敏支持包导出（ENG-03 从 AppState 原样迁出，含支持包上限与排除清单常量）。 | AppState 构造，路由以 `state.diagnostics` 直接调用；只读汇总设置、发票列表、monitor、成本、单据等状态，协作者以 AppState 方法同名注入、每次调用现取；支持包不含源发票与投影文件。 |
| `src/invoice_hub/services/documents.py` | `DocumentService`：单据默认值、单据目录状态、首页批量入库核对、入/出库预览、导出状态、导出与打开（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.documents` 直接调用；`_document_index` 与 `_inbound_details` 仍由 AppState 创建后传入（documents 路由直接读索引状态）。活动 TargetProfile、成本明细路径、出库目录经回调实时读取，首页批量入库核对（`_validated_inbound_selection`）在本服务内经 `InvoiceSelectionService` 复核；出库目录的保存/最近记录仍属设置用例留在 AppState。 |
| `src/invoice_hub/services/errors.py` | `StaleInvoiceSelectionError`、`UnsupportedStartupSurfaceError`，AppState 与拆出的领域服务共用。 | 放在中立模块以免 `app_state` 与领域服务循环导入；`services` 包与 `app_state` 仍重导出同一个类。 |
| `src/invoice_hub/services/monitor_control.py` | `MonitorControlService`：API 侧的 monitor 启停/状态/健康、同步进度、手动重建与打开日志/运行目录（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.monitor` 直接调用；设置、诊断、关闭经回调每次现查 `bridge_status/bridge_stop`（测试在本类上打桩）；手动重建持目标 profile 的同步写锁，仅当该 profile 仍为活动目标时清缓存与发事件；后台状态经回调读取。 |
| `src/invoice_hub/services/monitor_bridge.py` | monitor 子进程命令、状态真值、ready 等待和启停。 | AppState 与 control 调用；与 daemon/state 构成生命周期闭环。 |
| `src/invoice_hub/services/server_shutdown.py` | `ServerShutdownService`：结构化 localhost 关闭请求（只接受一次、按偏好保留或停止 monitor）与 Uvicorn 退出后的收尾（ENG-03 从 AppState 原样迁出）。 | 路由与应用生命周期以 `state.shutdown` 直接调用；SSE 仅在请求被接受后结束；monitor 状态/停止与偏好保存是对应服务的方法，经回调每次现查（测试在 `MonitorControlService` 类上打桩）。 |
| `src/invoice_hub/services/settings.py` | `SettingsService`：设置页数据、config 文件中的 watch_dir/最近目录/出库目录持久化与移除、偏好读写校验、监控目录检查/选择（ENG-03 从 AppState 原样迁出，含偏好与最近目录常量）。 | AppState 构造，路由以 `state.settings` 直接调用；切换 watch_dir（`update_settings`）跨 monitor/缓存/目标/启动同步，留在 AppState。config 对象归 AppState，本服务改写配置后调用 `reload_config` 回调；其它领域的协作者以 AppState 方法同名注入。 |
| `src/invoice_hub/services/skins.py` | 皮肤 ZIP 安全验证、运行态存储、启用和文件服务。 | API、AppState、common.js 使用；安全回归在 API 测试。 |
| `src/invoice_hub/services/about.py` | `AboutService`：About 构建身份、公开链接、更新检查/后台定时检查与委托宿主安装（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.about` 直接调用；`UpdateService` 由 AppState 创建后传入（测试经 `state._update_service` 替换传输层）。宿主审批 `_host_update_*` 状态归本服务，`_host_update_lock` 非阻塞串行检查/安装；Tauri 判定用 `host_rpc.desktop_host_mode_enabled()`。 |
| `src/invoice_hub/services/appearance.py` | `AppearanceService`：皮肤导入/替换/启用/重置/文件与应用图标切换（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.appearance` 直接调用；写入持 AppState 同一把 RLock；Tauri 宿主下先由宿主换图标再持久化。 |
| `src/invoice_hub/services/ocr.py` | `OcrService`：OCR 页的候选文件选择/列表与“未内置本地 OCR”状态（ENG-03 从 AppState 原样迁出）。 | AppState 构造，路由以 `state.ocr` 直接调用；活动目标与 config 经回调读取。 |
| `src/invoice_hub/services/update_service.py` | HTTPS 白名单更新检查、ETag/cache、版本/契约/平台产物选择和错误状态。 | About/API/启动后台检查消费；绝不执行安装。 |

## 13. 平台与发布

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `src/invoice_hub/platform/__init__.py` | 导出 Windows 平台 API。 | AppState 只通过此边界调用选择器和打开路径。 |
| `src/invoice_hub/platform/host_rpc.py` | Tauri 私有 picker/updater client、直接 backend 启动时的凭据捕获与 descendant 环境清理。 | Host 只向直接启动的后端传递 private configuration；Python 125 秒请求预算必须覆盖 Rust 120 秒 dialog 和响应余量；updater 只接受固定 `update_check/update_install`，只回传版本或成功；monitor、同步和原生子进程不得继承 token/secret。 |
| `src/invoice_hub/platform/native_dialogs.py` | Tk 原生目录/文件选择子进程。 | `platform/windows.py` 从项目根启动；取消选择也返回结构化结果。 |
| `src/invoice_hub/platform/windows.py` | 打开文件/目录、运行原生选择器、OCR 扩展名。 | AppState 在 Tauri mode 通过 Host RPC 传入固定 picker enum；其它模式保留 Tk，所有子进程清除 host credentials。 |
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
| `tests/test_appstate_service_wiring.py` | ENG-03 接线守护：每个从 AppState 拆出的服务在切换 watch_dir 后，锁、活动目标与 config 仍是 AppState 的同一对象。 | 新拆出服务须登记到 `SERVICES`；构造时快照或私有锁会使对应参数失败。 |
| `tests/test_api_contract.py` | API 字段、设置、关闭、诊断、SSE、皮肤、成本、选择合计、重命名，以及 monitor recovery HMAC request/response/replay/empty-body contracts。 | `api/app.py`、`AppState` 与领域服务、skins、costs、summary。 |
| `tests/test_file_preview.py` | 预览 job、来源复核、分页、文本、容量与安全边界。 | file_preview、document_rendering、AppState、API。 |
| `tests/test_file_preview_frontend_contract.py` | 首页预览 DOM、交互和静态资源契约。 | index.html、page-index.js、app.css。 |
| `tests/test_documents.py` | 单据状态、预览、人民币大写、模板扩行、导出和路径限制。 | documents、AppState documents API。 |
| `tests/test_frontend_contract.py` | 模板、JS、CSS、资源版本、表格、SSE、设置和皮肤静态契约。 | `web/**` 与 API 字段名称。 |
| `tests/conftest.py` | 会话级守护：测试前后对仓库 `runtime/`、`发票文件/`、`config/` 做快照，任一文件变化即让整轮失败。 | 测试必须用 `tmp_path` 配置；本 checkout 有在运行的服务时可设 `INVOICE_HUB_SKIP_REPO_STATE_GUARD=1` 跳过。 |
| `tests/test_workspace_frontend.py` | `/workspace` 外壳路由、no-store、OpenAPI 隔离、提交构建的 `?v=` 内容哈希与文件集合、无 sourcemap/本机路径、前端依赖精确版本。 | `frontend/` 构建、`web/static/app/`、`api/app.py` 的 workspace 路由。 |
| `tests/test_desktop_icon.py` | 图标生成一致性、native 配置继承、PNG 位深、ICO/ICNS 尺寸和透明度/对比度。 | 图标生成器、Tauri 配置与图标资源。 |
| `tests/test_website.py` | 标准库官网资源、打包白名单、缺失资源、构建一致性和更新地址检查。 | 不依赖 pytest；实际执行 alpha 资源复制，不构建 App 或安装器。 |
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
| `tests/test_company_ledger.py` | 公司发票账簿：多格式去重、冲突/未识别/不守恒不计入、免税与“10% 不是零税率”、红字冲减、文件名号码家族、季/年分期与各期纳税人类型、期间范围与日期未识别、主体与跨目录提示、种子合成账簿逐月对照，以及 API（两目录、手改字段生效、参数校验）。 | services/company_ledger、services/company_views、api/routes/companies。 |
| `tests/test_company_bank.py` | 银行流水账簿：月度期初/收支/期末、季度汇总、缺月不补 0、季度内缺月不成立、范围外月份、余额错误使自检不成立、签名缓存与文件变化、回单只计数不解析、API（并列返回、只读、`include_bank=false`、缺目录、无对账单）。 | services/company_bank、company_views、bank/workpaper；合成中国银行对账单 PDF。 |
| `tests/test_company_deduction.py` | 抵扣核对：按真实导出版式在测试内生成合成清单；解析、当期/前期匹配与各类单列、税额不一致、跨期重复勾选、合计行不符、空清单与未识别文件、期间范围、旧版发票代码号码，以及 compare API（只读、顺序无关、拒绝无关组合与非法月份、缺目录）。 | services/company_deduction、company_views；不含真实清单。 |
| `tests/test_company_inventory.py` | 进销存：跨月加权与品目表合并、小规模/普票/待核对的进货额、卖超与进项中没有、非货物与不可读行、期间范围从滚动库存起算（含无发票的月份）、规格是品类的细分、多单位分行、账套读回期初（按品类落行、期初月之前发票不重复、读回不足保持 0 起算、损坏/缺科目表降级、无单位分录不猜），以及 compare API（未汇总时 `no_details`、汇总后结果、读取不改任何文件、放入读回后取账套期初）。 | services/company_inventory.py、company_views.py |
| `tests/test_export_profiles.py` | 通用导出：捷锐输出与引入导出配置之前的导出代码（冻结在 `tests/fixtures/jierui_export_golden.json`）逐单元格一致并沿用账套模板列序、柠檬云 35 列与“记-N”、用友 V800 文本与 GBK、已导出凭证换格式仍跳过、上传模板按表头对列与缺列报告、页面导出格式选择与拒绝越界 / 缺列 / 未知格式。 | bank/export_profiles、bank/jierui、services/company_vouchers。 |
| `tests/test_company_payroll.py` | 工资社保：按电子税务局版式读 Excel、`--` 为空、图片不识别、合计与费率不成立标出、文字层 PDF（整行与逐格两种排版）、脱敏与显示原值、确认写入保留其他键 / revision 冲突 / 手工录入月份 / 删除月份、无或损坏 申报数据.json 拒绝且不覆盖、确认后生成的草稿按该月计提、API 读取不写文件。 | services/company_payroll、company_vouchers、bank/vouchers。 |
| `tests/test_source_move.py` | 属期文件夹：文件夹名只作提示、按内容期间判定放错 / 未归属 / 无单一属期、确认后新建 `YYYY-MM` 并移动、重放不重做、同名不覆盖 / 越界 / 非法新文件夹名 / 已在目标 / 链接拒绝、计划后文件变化不移动、与监控目录重叠拒绝，以及 API（核对、计划不写公司资料夹、确认、读日志、不返回绝对路径）。 | services/source_move、company_views。 |
| `tests/test_company_same_number.py` | 同号检查：同票多格式只算一张、无号码单列、金额与销售方不同、疑似重复与跨公司双方同一张票、两家都取得仍为疑似重复，以及 API（同一公司、跨公司、有勾稽关系的组合与非发票目录拒绝、读取不改文件）。 | services/company_same_number、company_views。 |
| `tests/test_company_settlement.py` | 往来核对：一对一与唯一组合、多组不对应、同额先开先结、户名不唯一、期间期初、应收方向、红冲抵销与无原票红字、未识别发票、对账单自检失败，以及 compare API（合成中国银行对账单 PDF，只读）。 | services/company_settlement、company_views。 |
| `tests/test_company_projects.py` | 项目汇总：备注识别与人工优先、备注冲突列未归属、期间与粒度、未识别金额排除，以及 API（读取不写文件、保存写入公司资料夹、重新汇总后保留、版本冲突、清除、非法请求、损坏文件拒绝覆盖、跨源写拒绝）。 | services/company_projects、company_views。 |
| `tests/test_invoice_tags.py` | 发票标签：定义校验与版本、改名保留 id、打标记与定义顺序、目录列表附带标签且其余字段不变、按标签筛选、重新汇总后保留、删除标签清除各公司标记、损坏文件不覆盖且列表照常、跨源写拒绝。 | services/invoice_tags、company_views。 |
| `tests/test_company_views.py` | 按公司只读目录与纳税人类型优先级：投影/过期判断（新增、改动、删除、坏记录）、读取不建目录不改文件、只读列表与分页、活动目录交接、`company_taxpayer_for` 按月份、清单类型计价与保存拒绝、清单变化重写工作簿、所有 `CostProjectionService`/`MonitorSynchronizer` 构造都传入查找。 | services/company_views、targets/companies、projections/costs、services/company_registry。 |
| `tests/test_company_vouchers.py` | 凭证草稿审核：按导出规则校验（借贷不平、科目可用、供应商档案）、写回同一单元格且导出读取器可见、其他工作表保留、不平凭证不能审核通过且整批不写、改过的已通过凭证需重新审核、过期 revision 拒绝、跨凭证行与越界文件名拒绝、改编码同步科目名称、非法请求体，以及 API 列表 / 读取 / 结构化拒绝原因。 | services/company_vouchers、company_views、bank/jierui。 |
| `tests/test_company_voucher_generate.py` | 页面生成草稿与改记入期：与 `voucher_cli draft` 逐单元格一致、重新生成先备份并沿用未变凭证的审核与改过的摘要、内容变了列入重新审核、只接受列出的读回文件与合法月份、缺发票明细的生成失败提示；改记入期后凭证移到新月份并标跨期、命令行读同一调整、撤销与调到范围外、revision 冲突与损坏文件拒绝。 | services/company_vouchers、bank/vouchers、bank/voucher_cli。 |
| `tests/test_api_companies.py` | 公司清单 API：空清单不建文件、子目录识别与歧义回退、revision CAS、根目录重复/嵌套、相对/绝对路径保存、子目录越界、纳税人生效期、补建预览/确认/过期、链接逃逸、损坏文件拒写、删除不碰文件、`monitored` 标记且不切换目录、跨来源拒绝。 | services/company_registry、api/routes/companies。 |
| `tests/test_company_setup.py` | 公司 picker 只填草稿、固定私有能力、来源与空 body、取消 / 脱敏失败 / 超时；新建计划不写用户根，确认仅执行一次，非法路径、重复 / 嵌套、父身份变化、部分失败、崩溃与登记观察未知、相对路径登记。 | `company_registry.py`、`company_setup.py`、`api/routes/companies.py`。 |
| `tests/test_api_bookkeeping.py` | 做账 API、错误模型和废弃接口 410。 | AppState、api、bookkeeping。 |
| `tests/test_bookkeeping_decisions.py` | W9 会计决定与提案 revision。 | decisions、vouchers。 |
| `tests/test_bookkeeping_export.py` | 批次 manifest、XLSX、签名和 finalize。 | import_file、batches、validator。 |
| `tests/test_bookkeeping_mapping.py` | 映射影响预览、CAS、胜者和定向重算。 | mapping、repository。 |
| `tests/test_bookkeeping_mapping_migration.py` | 映射 v1/v2 preview/apply。 | mapping_migration。 |
| `tests/test_bookkeeping_profile.py` | 账套、科目和辅助档案绑定。 | catalogs、validator。 |
| `tests/test_bookkeeping_projection.py` | 凭证生成、posting key 和 revision。 | vouchers、status。 |
| `tests/test_bank_vouchers.py` | 合成公司资料夹上的科目定位、进项抵扣推断、增值税测算与申报差异、审核导出、习惯学习、重复导出保护、账套读回匹配与补记编号、银行对账与原件链接、CLI。 | bank/ledger、vouchers、jierui、voucher_cli。 |
| `tests/test_bank_workpaper.py` | 合成中国银行对账单/回单 PDF 的解析、勾稽、匹配、建议分录、脱敏 fail-closed 与 CLI。 | bank 全部模块；不得引用真实业务资料。 |
| `tests/test_bookkeeping_status.py` | 严格状态仓储与迁移。 | repository、status。 |
| `tests/test_bookkeeping_validator_w9.py` | W9 可执行性 blockers。 | validator、decisions、catalogs。 |
| `tests/test_runner_dryrun.py` | batch-bound dry-run 与禁止猜测最新文件。 | runners、scripts/tools。 |
| `tests/test_summary_and_costs.py` | 金额防污染、同票纠偏、结构化成本、均价、参考状态和 schema 刷新。 | extraction、summary、cost_analysis、costs。 |
| `tests/test_development_documentation.py` | 文件地图、链接/定位锚点、Agent 入口体积与规则可达性、接口路由、基线、旧事实和敏感路径门禁。 | 本架构文档、README、AGENTS、CLAUDE 和 Git 指南。 |
| `tests/test_tauri_foundation.py` | 版本派生、单点 drift 修复、doctor fail-closed、固定 origin、MSRV resolver、Cargo/pnpm lock 与非安装 bootstrap。 | Tauri foundation scripts, configuration, and plan; Rust compile is separately recorded, and no platform smoke test is claimed. |
| `tests/test_tauri_dev_app.py` | Development `.app` allowlist staging、ordinary/recovery manifest 可重复性、固定不可安装 updater tuple、无权限的空 plugin-config 占位、launcher 哈希绑定与 app-only 构建参数契约。 | `scripts/dev/tauri_dev_app.py`、`src-tauri/tauri.dev.conf.json`；只证明开发组装输入，不证明 DMG/NSIS、签名、公证或平台发布。 |
| `tests/test_tauri_recovery_smoke.py` | L10-E App plist/manifest identity、临时路径、marker scope、health/monitor identity 和闭合 HTTP allowlist 契约。 | `scripts/dev/tauri_recovery_smoke.py`；不模拟 check/install，真实 startup-recovery runtime 由 L10-E 有边界的平台样本单独记录。 |
| `tests/test_tauri_public_preview_smoke.py` | mounted-DMG public-preview App identity、精确 disabled updater、隔离 Application Support、LaunchServices 启动、临时 host/backend 归属和闭合 shutdown HTTP surface。 | `scripts/dev/tauri_public_preview_smoke.py`；锁定 smoke 输入与清理边界，不替代最终 Tag DMG 的 Finder/Gatekeeper 成品验收。 |
| `tests/test_tauri_host_rpc.py` | Python Host RPC URL/token/enum、updater response narrowing、失败不回退和子进程凭据清理。 | `platform/host_rpc.py`、`platform/windows.py`。 |
| `tests/test_tauri_lifecycle_contract.py` | Tauri 生命周期静态配置、无 WebView IPC、HMAC/liveness、manifest hash 与 updater candidate/order source contract。 | `src-tauri` lifecycle boundary。 |
| `src-tauri/tests/lifecycle_contract.rs` | Fixed port、identity、OpenAPI methods、Host RPC authorization/revocation、manifest hash、candidate expiry and update order Rust integration contracts. | `backend.rs`、`host_rpc.rs`、`BackendLifecycleAuthority` delegation tests。 |

## 15. 前端公共资源

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `web/static/css/app.css` | 全站布局、表格、状态、响应式和无皮肤默认样式。 | 所有普通模板引用；修改需更新模板 `?v=` 和前端契约。 |
| `web/static/css/settings-actions.css` | 首页/设置页操作、确认对话框和通知样式。 | `index.html`、`settings.html` 引用；版本参数需同步。 |
| `web/static/js/common.js` | API 包装、转义、表格 TSV、皮肤、SSE 和导航过渡。 | 所有页面 JS 依赖；SSE 页面通过 `connectEvents` 复用重连语义。 |
| `web/static/js/system-controls.js` | 普通页面共享的关闭偏好、外部服务保护、电源确认、重试和焦点控制。 | 先于 page-settings 加载；同一 shutdown API 成功确认后通知 common.js 结束 SSE。 |
| `web/templates/system_controls.html` | 请求转圈与唯一关闭弹窗片段。 | `api/app.py::_template` 只替换固定 `{{system_controls}}`；不增加任意模板入口。 |
| `web/templates/appearance_toggle.html` | 品牌名旁的太阳/月亮切换片段。 | 九个普通模板通过固定占位替换；backend/打印页不加载。 |
| `web/static/js/appearance.js` | 明暗切换、CSS 预加载、失败提示、重复点击保护与页面状态同步。 | 复用 skins enable/reset；保留业务草稿，不在皮肤包中执行 JS。 |
| `web/static/icons/sun.svg` | Lucide Sun 本地 CSS mask。 | 默认浅灰太阳，ISC/Feather MIT 许可。 |
| `web/static/icons/moon.svg` | Lucide Moon 本地 CSS mask。 | Dark 的白色月亮，ISC 许可。 |
| `web/static/icons/power.svg` | Lucide 1.8.0 电源图标，作为固定 CSS mask。 | 所有普通页顶栏共用；悬停与键盘焦点为浅红色。 |
| `web/static/icons/LICENSE-lucide` | 电源及明暗图标 ISC 与 Feather MIT 许可。 | 随 `web/` 打包，来源同步第三方声明。 |
| `tests/frontend_interactions.test.cjs` | Node 内置 test/VM 执行真实公共 JS、关闭控制器和单据队列。 | 验证批量停止/结果未确认/迟到预览、并发请求、失败清理、按钮恢复、浏览器返回、关闭/SSE；无需新增 npm 依赖。 |
| `web/static/js/page-index.js` | 首页目录草稿、发票列表、筛选、预览续租/自动恢复、批量打印/入库交接、勾选合计和 monitor 操作。 | 消费 settings/invoices/preview/keep-alive/print/selection/bridge API；弹窗关闭必须停止续租。 |
| `web/static/js/page-costs.js` | 成本标签、表格、行级加价和状态保存。 | 消费 preferences/cost-analysis/bridge API；对应成本工作簿 sheet。 |
| `web/static/js/page-detail.js` | 发票详情、成本拆分、手改和打开文件。 | 消费 invoice detail/manual/open API。 |
| `web/static/js/page-documents.js` | 入出库标签、目录草稿、模板列宽预览、逐票批量队列、导出策略和打开操作。 | 消费 documents/preferences API；身份交接、停止/未知结果与目标切换保护，并监听汇总事件。 |
| `web/static/js/page-ocr.js` | OCR 候选目录和禁用服务状态。 | 消费 preferences/ocr API；当前不执行正式 OCR。 |
| `web/static/js/page-consistency.js` | 同票多格式一致性表。 | 消费 consistency-report API。 |
| `web/static/js/page-settings.js` | 设置中心、运行控制、重命名、偏好与诊断。 | 消费设置/bridge/documents/skins/ocr/diagnostics；关闭入口委托先加载的 system-controls.js。 |
| `web/static/js/page-skins.js` | 皮肤 ZIP 导入、替换、启用和重置。 | 消费 skins API；不执行包内 JS。 |
| `web/static/js/page-bookkeeping.js` | 凭证人审、映射规则、账套设置和批次状态。 | 消费 `/api/v1/bookkeeping/*`，持续展示服务端 blockers。 |

## 15.1 Vue 工作区前端

新界面（多公司工作区等）在 `frontend/` 实现，构建产物提交到 `web/static/app/`，因此发布打包、白名单和 Core Build ID 继续只消费 `web/`。旧页面（`web/templates` + `web/static/js`）在迁移完成前保持原样。

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `frontend/package.json` | 前端依赖（精确版本）、pnpm 版本与 `build/typecheck/test` 脚本。 | 升级依赖须同步 `pnpm-lock.yaml`、THIRD_PARTY_NOTICES 并重建提交产物。 |
| `frontend/pnpm-lock.yaml` | 前端依赖 integrity lock。 | CI `--frozen-lockfile` 安装；不含 registry tarball 地址。 |
| `frontend/vite.config.ts` | Vite 构建：`base=/static/app/`、固定文件名、单 bundle、无 sourcemap、`?v=` 内容哈希插件、开发代理与 Vitest 配置。 | 输出到 `web/static/app/`；改文件名会改变发布包文件集合和 FILE_MAP。 |
| `frontend/tsconfig.json` | TypeScript 严格模式配置。 | `vue-tsc --noEmit` 类型检查。 |
| `frontend/env.d.ts` | Vite 客户端类型声明。 | 类型检查入口。 |
| `frontend/index.html` | 开发与构建的 HTML 入口。 | 构建后成为 `web/static/app/index.html`。 |
| `frontend/src/main.ts` | 创建 Vue 应用并挂载 Pinia 与路由。 | 全局插件入口。 |
| `frontend/src/App.vue` | 工作区外框（WS-01）：最左模块列（首页为 Vue 工作区；成本分析、单据、做账、OCR、一致性、设置在迁移前链接经典页面；左下“更新”进设置、“经典界面”回首页）、错误横幅与 `KeepAlive` 包裹的路由视图；双击 `hi.` 只刷新当前首页标签并重读公司清单。 | 模块切换保留各视图实例（页面缓存）；`stores/workspace.ts::refreshActive`。 |
| `frontend/src/router.ts` | 客户端路由与 `/workspace/` history 基址：`/` 为首页（HomeView），旧的 `/companies`、`/directory` 与未知路径重定向到首页。 | 新模块在此登记；深链接由 FastAPI 回落到同一外壳。 |
| `frontend/src/api/client.ts` | 同源 `/api/v1` 请求封装：超时、JSON、`detail/message` 错误映射为 `ApiError`，结构化错误带 `code` 与逐项原因 `details`；`acceptPartial` 让带逐项结果的 `ok:false`（子目录补建部分失败）返回给调用方。 | 所有视图请求经此；与后端错误模型一致。 |
| `frontend/src/api/types.ts` | 已消费 API 字段的类型子集。 | 后端字段变化时同步。 |
| `frontend/src/stores/system.ts` | health/settings 只读快照；刷新失败保留上次结果并给出错误。 | Pinia 全局状态。 |
| `frontend/src/stores/companies.ts` | 公司清单状态（WS-07）：读取、新建、修改、移除都带清单 revision，`COMPANY_REVISION_CONFLICT` 时重新读取再提示重试；子目录补建预览与按 `plan_hash` 确认；新建 setup 计划 / 确认 / 查询；`companySourceKey` 只按根与相对映射生成稳定来源键。 | 消费 `/api/v1/companies*`。 |
| `frontend/src/format.ts` | 纳税人类型、子目录状态与是否最新的中文标签；金额在十进制字符串上分组千分位，不经过浮点。 | 公司模块各组件共用。 |
| `frontend/src/views/HomeView.vue` | 首页模块（WS-01）：工作区侧栏 + 顶部标签（公司、目录、项目、⇄ 比较、添加公司、发票标签）；每个打开的标签以 `v-show` 常驻（筛选、结果、滚动保留），关闭即丢弃；全部关闭显示起始页（版本、后台状态、当前监控目录）；首次进入自动打开监控中的公司一次；公司被删除时其标签自动关闭；窄屏侧栏改为抽屉。 | 路由 `/workspace/`；`stores/workspace.ts`。 |
| `frontend/src/stores/workspace.ts` | 首页的标签、置顶、展开的公司、侧栏宽度与“选择以进行比较”的目录；标签 id 由类型 + 对象组成（同一对象只开一个）；`refresh` 计数让双击 `hi.` 只重建当前标签；置顶、展开与宽度存本机 `localStorage`（`invoicehub.workspace.v1`，仅界面偏好）；`clampSidebar` 限制 220—460px 且内容区至少 620px。 | `HomeView.vue`、`WorkspaceSidebar.vue`、`App.vue`。 |
| `frontend/src/components/WorkspaceSidebar.vue` | 工作区侧栏：`InvoiceHub ⌄` 菜单（刷新公司清单、发票标签、返回经典界面）、添加公司资料夹、置顶区、公司 › 项目 / 六类目录树（项目在展开时才读取；监控中目录带绿点；缺失目录灰显）、右键 / 行尾 ⋯ / Shift+F10 菜单（打开、置顶、选择以进行比较、与已选项进行比较，无勾稽关系或不同公司时禁用并说明）、已选时可比较的行直接显示“⇄ 比较”、悬停名片（全名与路径）、可拖动调宽的分隔条（键盘左右键、Home/双击复位、到限位提示）与底部监控状态。 | `relations.ts`；`/api/v1/companies/{id}/projects`。 |
| `frontend/src/relations.ts` | 同一公司可勾稽的四组目录（抵扣、进销存、应付、应收）与 `relationFor`，以及可做同号检查的发票目录 `INVOICE_DIRS` 与 `SAME_NUMBER`；只用于提供后端接受的组合，不做任何计算。 | `CompanyCompare.vue`、`WorkspaceSidebar.vue`。 |
| `frontend/src/components/CompanyPanel.vue` | 公司标签：名称、纳税人身份与资料夹路径，目录 / 发票账簿 / 项目 / 勾稽 / 凭证草稿 / 工资社保 / 设置七个分区；`v-show` 保留各分区状态，账簿、项目、勾稽、凭证草稿与工资社保首次打开才加载。 | 由 `HomeView.vue` 渲染。 |
| `frontend/src/components/DirectoryPanel.vue` | 目录标签：子目录状态、是否最新、上次汇总、重新检查与“设为监控目录”，下方为该目录发票列表。 | `/api/v1/companies/{id}/directories`；`DirectoryInvoices.vue`。 |
| `frontend/src/components/DirectoryInvoices.vue` | 目录发票列表（上次投影；非监控目录只读）：标签色点列，右键 / Shift+F10 打标签（只更新该行；在多行勾选中的行上作用于全部勾选的发票，打开时读取当前标记），按标签筛选与后端开票时间排序 / 分页，显示大类与业务样式及经典格式配色；监控目录且非临时结果时有勾选列（表头勾选本页，含部分选中），“全选筛选结果”按同一筛选分页读取全部记录；删除后保留逐文件结果面板；勾选预览使用 `SourcePreview.vue`，投影或监控身份变化时清除旧选择，迟到列表 / 全选不覆盖新状态。 | `/api/v1/companies/{id}/directories/{key}/invoices`、`invoice-tags`；`DirectorySelectionBar.vue`。 |
| `frontend/src/components/DirectorySelectionBar.vue` | 勾选底部操作条：张数与价税合计、合计详情（三项金额、有效计入张数、冲突 / 缺失 / 折叠提示）均来自 `selection-summary`；“预览”把完整选择交给目录页的共用原票面板；打印（先开窗再填 `print-jobs` 的地址）、开具入库单（会话交接到单据页，最多 1000 条）、删除所选（`trash-jobs` 预备清单 → 条内确认 → 响应丢失只读执行日志），取消勾选与全选筛选结果。 | `/api/v1/invoices/selection-summary`、`print-jobs`、`trash-jobs*`。 |
| `frontend/src/components/WatchSwitchConfirm.vue` | “设为监控目录”确认：说明只监控一个目录，确认后调用 `PUT /api/v1/settings` 并刷新系统快照与公司清单。 | `CompanyDirectories.vue`、`DirectoryPanel.vue`。 |
| `frontend/src/components/CompanyCreateForm.vue` | 登记已有资料夹 / 从零新建向导：独立原生选择只填草稿；新建填写上级位置、根名称与六类相对目录，计划 / 显式确认 / 未知只 GET；纳税人不默认。 | `stores/companies.ts::create/planSetup/confirmSetup/getSetup`。 |
| `frontend/src/components/CompanyDirectories.vue` | 公司的子目录表（状态、上次汇总、是否最新）、补建预览与确认、设为监控目录；“查看发票”打开该目录的标签。 | `/api/v1/companies/{id}/directories`、`subdirs/*`；`WatchSwitchConfirm.vue`。 |
| `frontend/src/components/CompanyLedger.vue` | 公司发票账簿：粒度与期间筛选、票面口径说明、守恒校验（成立时收起、任一不成立时展开并标红）、提示、分期表与合计、未计入的发票。 | `/api/v1/companies/{id}/ledger`。 |
| `frontend/src/components/CompanyBankLedger.vue` | 公司账簿的“银行流水”区：目录不可用 / 无对账单的说明、余额校验（成立时收起、不成立时展开标红）、对账单问题、按账户的分期表（缺月行标红、余额显示“—”）与来源计数。 | 由 `CompanyLedger.vue` 渲染 `ledger.bank`。 |
| `frontend/src/components/CompanyCompare.vue` | “勾稽”外壳（公司标签的“勾稽”分区与侧栏打开的 ⇄ 比较标签共用，`relation` 预选关系；提供类目聚焦，渲染明细抽屉与并排原始记录，重新核对时清除聚焦）：关系选择（成本发票 ⇄ 进项抵扣、成本发票 ⇄ 开具发票、成本 / 开具发票 ⇄ 银行流水，切换即重新核对）与期间、口径说明、核对校验（不成立时展开标红）、提示，再按关系交给结果组件。 | `/api/v1/companies/{id}/compare`。 |
| `frontend/src/compareFocus.ts` | 比较明细的注入键与类型（WS-04）：结果组件把点到的类目（标签、`record_ids`、`steps`）交给比较页。 | `CompanyCompare.vue` provide；各结果组件 inject。 |
| `frontend/src/components/CompareDrawer.vue` | 类目明细抽屉：来源条数与后端计算过程，打开时焦点到关闭按钮，Esc 关闭。 | 由 `CompanyCompare.vue` 渲染。 |
| `frontend/src/components/CompanySameNumber.vue` | 同号检查标签：说明口径、校验、提示、同号发票表（疑似重复 / 双方同一张票，金额或销售方不同标红）；点号码打开明细抽屉并收窄并排原始记录。 | `/api/v1/companies/{id}/same-number`；`CompareSources.vue`、`CompareDrawer.vue`；由 `HomeView.vue` 渲染。 |
| `frontend/src/components/CompanyPayroll.vue` | 公司标签“工资社保”分区：电子税务局两行表头版面、后端核对结果、按月确认 / 取消确认、手工录入一个月、人员明细默认脱敏可临时显示原值、未识别文件提示。 | `/api/v1/companies/{id}/payroll`；由 `CompanyPanel.vue` 渲染。 |
| `frontend/src/components/PeriodFolderCheck.vue` | 进项抵扣 / 银行流水目录标签的“属期文件夹核对”：可能放错与未归属文件、逐行选目标（建议 / 新建）、计划 → 确认 → 逐文件结果，确认响应丢失只读日志。 | `/api/v1/companies/{id}/period-folders*`；由 `DirectoryPanel.vue` 渲染。 |
| `frontend/src/components/CompareSources.vue` | 两个目录的原始记录并排（`records.a/b`）；有聚焦类目时两边只留其 `record_ids`，可“显示全部”；后端带 `preview` 的记录（监控目录）有“原票”，打开 `SourcePreview.vue`。 | 由 `CompanyCompare.vue` 渲染。 |
| `frontend/src/components/SourcePreview.vue` | 目录勾选与比较记录共用原票面板：创建 `preview-jobs`，名称每组最多 100 项且能按序号访问完整队列，当前文件缩略图每组最多 12 页、大图与翻页；XML 显示纯文本、可取消读取且丢弃迟到正文；打开期间续租，`404/410` 重建并保留文件与页码，图片 / XML 持续失败的立即恢复有界。 | `/api/v1/invoices/preview-jobs*`；由 `DirectoryInvoices.vue` 或 `CompareSources.vue` 打开。 |
| `frontend/src/components/CompanyDeductionResult.vue` | 抵扣核对结果：各所属期表、清单有目录无、已勾选并对上（税额不一致标红）、目录有清单无、重复勾选与未识别文件。 | 由 `CompanyCompare.vue` 渲染。 |
| `frontend/src/components/CompanyInventoryResult.vue` | 进销存结果：品类表（明细科目编码，期初/购入/销售/成本/期末，卖超与“进项和期初中没有”标红），品类前的 ▸ 在同一列下展开规格行（只有购入、销售与净增，期初与成本显示 —），“逐月”在品类下展开整行明细（加权单价与说明），合计、未计入期初的账套明细与未计入的明细行。 | 由 `CompanyCompare.vue` 渲染。 |
| `frontend/src/components/CompanySettlementResult.vue` | 往来核对结果：往来单位余额表（“明细”整行展开未对上发票与未逐笔对应流水）、逐笔对应、红字发票、户名不唯一、非发票流水（折叠）与未识别发票。 | 由 `CompanyCompare.vue` 渲染。 |
| `frontend/src/components/CompanyProjects.vue` | “项目”分区（项目标签以 `focus` 标出该项目并列出各期）：粒度与期间、与账簿一致的校验、项目汇总表（未归属单列），未归属与已人工指定发票的项目输入（已有项目名候选），只提交改动并带 revision，冲突时刷新提示。 | `/api/v1/companies/{id}/projects*`。 |
| `frontend/src/components/CompanyVouchers.vue` | “凭证草稿”分区：选择审核表与月份、只看有问题的；每张凭证一张卡片，逐格编辑摘要 / 科目编码 / 借贷 / 供应商，输入时显示借贷合计（只作显示），审核下拉（待审核 / 通过 / 不导入）；每张凭证可改所属期与记账日期（改月时日期移到月末并提示重新编号）；草稿核对表折叠只读显示；发票凭证的原始单据与同期 / 跨期、“改记入期”；“生成草稿…”面板（起止年月、统一记月末、序时账读回与科目表快照，结果列出沿用 / 需重审 / 新增 / 消失）；“导出已审核…”面板列出各月通过张数、可填账套已用到的号、必填制单人，确认后导出并逐项显示结果（有未保存改动时禁用）；保存只提交改动行、审核状态与所属期 / 日期并带 revision，冲突时刷新提示，审核通过被拒时保留改动并在凭证旁列出后端原因。 | `/api/v1/companies/{id}/voucher-drafts*`。 |
| `frontend/src/components/InvoiceTagsEditor.vue` | 发票标签管理：颜色、名称、意义的增删改，整表保存带 revision，删除时说明会移除已打标记，冲突时刷新。 | `stores/tags.ts`，`/api/v1/invoice-tags`；首页“发票标签”标签。 |
| `frontend/src/stores/tags.ts` | 标签定义的 Pinia store：读取、整表保存（带 revision，冲突时重读）与按 id 查找。 | `InvoiceTagsEditor.vue`、`DirectoryInvoices.vue`。 |
| `frontend/src/components/CompanySettings.vue` | 公司名称、六类相对目录映射与纳税人身份生效期编辑（不移动 / 改名文件）、从清单移除（说明不删除任何文件）；只在切换公司时重置草稿；显示成本汇总表是否已按新身份重写。 | `stores/companies.ts::update/remove`。 |
| `frontend/src/styles.css` | 外框基础样式、模块列、工作区侧栏与标签、窄屏布局（900px 以下侧栏改抽屉，640px 以下模块列横排）。 | 仅作用于 `/workspace`。 |
| `frontend/tests/directory-preview.spec.ts` | WS-01 目录排序与勾选原票、101 个文件的窗口 / 跳转、XML 纯文本与迟到正文、持续失效恢复、监控切换。 | Vitest + Vue Test Utils；相邻比较预览仍由 `companies.spec.ts` 覆盖。 |
| `frontend/tests/company-setup.spec.ts` | WS-02 原生选择重复 / 取消 / 迟到、从零向导先计划后确认、确认失联只 GET、映射只保存改动引用、目录选择 / 旧路径 / 监控确认失效与未保存项目草稿保护。 | Vitest + Vue Test Utils；服务端文件系统边界由 `test_company_setup.py` 覆盖。 |
| `frontend/tests/client.spec.ts` | 请求封装的成功、错误、`ok:false`、请求体与超时测试。 | Vitest + happy-dom。 |
| `frontend/tests/companies.spec.ts` | 公司标签：侧栏列出公司并默认打开监控中的公司、新建带 revision 且不假定纳税人身份、版本冲突后重新读取、补建必须先预览并发送 `plan_hash`、预览过期要求重新预览、守恒校验失败标红且展开、非监控目录只读、金额分组。 | Vitest + Vue Test Utils，桩接 `fetch`。 |
| `frontend/tests/app.spec.ts` | 外框与首页（WS-01）：无公司时的起始页与 health、旧路径重定向、未迁移模块链接经典页面、刷新失败保留快照；侧栏节点打开为标签且不重复、隐藏标签保持挂载、全部关闭后停在起始页、项目展开时才读取、Shift+F10 菜单置顶并写入本机偏好、同公司有勾稽关系才可比较（无关系与不同公司禁用并说明）并以预选关系打开 ⇄ 标签、双击 `hi.` 只重载当前标签、侧栏宽度限位。 | Vitest + Vue Test Utils，桩接 `fetch`。 |
| `web/static/app/index.html` | 提交的构建外壳，引用带 `?v=` 的资源。 | 由 `/workspace/*` 以 no-store 返回；不手改。 |
| `web/static/app/assets/app.js` | 提交的 Vue 应用 bundle（含 Vue/Pinia/Vue Router）。 | `?v=` 存在时按 immutable 缓存；CI 校验与源码构建逐字节一致。 |
| `web/static/app/assets/app.css` | 提交的工作区样式。 | 同上。 |

## 16. 内置皮肤资产

`web/static/skins/website-dark/skin.json` 声明只读 Dark 深色 `1.0.0`；`web/static/skins/website-dark/skin.css` 以官网墨黑/荧光/灰白覆盖既有选择器并保留纸质预览原色；`web/static/skins/website-dark/asset-sources.json` 记录原创 CSS 来源与许可，不增加任何外部资源。三者与 SkinService、明暗控件及皮肤恢复契约同步。

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

## 17.1 独立产品官网

| 文件 | 职责与入口 | 关系与修改影响 |
|---|---|---|
| `website/index.html` | Hi 品牌官网、发票/成本/单据/工具四视图、功能动效、开源入口与 FAQ。 | 独立静态页面，不替换业务 WebUI；资源使用独立版本参数。 |
| `website/style.css` | 官网排版、色彩、响应式、表格和 dialog。 | 桌面/手机、焦点、滚动与减少动态效果需浏览器验收。 |
| `website/app.js` | 页面内筛选、合计、成本、CSV、预览翻页/放大、打印动画、明细 TSV、单据行数与工具交互。 | 消费合成数据和图标；本地 `/website/` 模式显示返回工作台，不请求生产 API，不写业务投影。 |
| `website/demo-data.js` | 固定合成票头/明细、整数分金额、同票去重、打印候选、分组与税额概念换算。 | Node 合同守护，不能替代生产算法或发票真值。 |
| `website/paper-scene.js` | 五层原创 Canvas 票纸/标签独立展开、归拢及有界调度。 | 只命中票据区域，支持键盘/触屏、屏外/后台/静止停止与减少动态效果。 |
| `website/assets/mark.svg` | 原创 h/i 字母 favicon。 | 只用于官网，不改变软件图标偏好或桌面 surface。 |
| `website/assets/display.woff` | 本地 Dela Gothic One Latin 字体。 | 来自仓库已许可字体，配合字体许可证分发。 |
| `website/assets/OFL-DelaGothicOne.txt` | 官网展示字体的 SIL OFL 许可。 | 与字体一起保留。 |
| `website/assets/icons.js` | 精选 Lucide 节点的生成文件。 | app.js 生成 SVG 图标；源码入口采用 GitFork 通用图标。 |
| `website/assets/LICENSE-lucide` | Lucide ISC 许可。 | 与精选图标一起保留。 |
| `website/scripts/vendor-icons.cjs` | 从显式已安装 Lucide 包机械生成精选图标。 | 不自动下载依赖；生成 icons.js 与许可。 |
| `website/scripts/preview.cjs` | 可选的 Node loopback 静态预览。 | 只提供官网目录，不复用或改变业务固定端口；不用于生产。 |
| `website/tests/demo.test.cjs` | 去重、明细边界、打印缺 PDF 阻断、换算分位、图层调度及资源/链接契约。 | Node 内置测试，不依赖 Python 或业务运行态；不替代浏览器截图。 |
| `website/README.md` | 官网运行、维护、验证假设与未覆盖项。 | 明确直接打开 HTML、可选预览和独立部署边界。 |
| `website/ASSETS.md` | 原创视觉与第三方图标/字体的来源、许可和生成方式。 | 新资源必须同步登记，不引入业务资料。 |

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

## README 产品展示与使用说明

| 文件 | 职责与约束 |
|---|---|
| `docs/USER_GUIDE.md` | 面向使用者的目录、汇总、成本、单据、监控及外观恢复说明；README 的详细操作入口。 |
| `docs/screenshots/README.md` | 三张当前版本截图的来源、空目录事实和隐私处理说明；不保存原始业务 DOM。 |
| `docs/screenshots/invoicehub-home.png` | 真实汇总首页截图，只在截图会话中隐藏本机路径。 |
| `docs/screenshots/invoicehub-costs.png` | 同版本成本分析零记录截图，不伪造业务数据。 |
| `docs/screenshots/invoicehub-appearance.png` | 同版本图标与皮肤管理截图，拍摄不保存新的外观设置。 |

以上只用于 GitHub 文档展示，不增加包内业务资源或改变当前 Release 输入。
