# 变更日志

## 未发布

### 2026-11-26 工作区 Phase 2：跨公司全局检索（WS-11）与文件级增删改查/通用文件视图（WS-12）

- 需求与起点：基于同一工作树 `InvoiceHub-workspace-crud-search`（分支 `codex/workspace-crud-search-p1`）的 Phase 1 本地检查点（`0669348`），按用户确认继续落地 Phase 2 两项核心能力：（1）`WS-11` 跨目录/跨公司只读全局检索、侧栏折叠公司项目检索与点击命中自动跳转定位；（2）`WS-12` 工作区通用文件与子文件夹浏览、拖放/选择文件无覆盖导入、活动监控目录单票 6 字段手改/安全改名与跨目录计划确认移动归档，以及原生回收站文件删除。
- 采用方案：
  - **WS-11 后端与前端**：
    - 新增 `src/invoice_hub/services/workspace_search.py`（组合于 `CompanyViewService.search`，零改动 `AppState`）与 `src/invoice_hub/api/routes/workspace_search.py`：提供只读 `GET /api/v1/workspace/search`（跨公司/单公司、多词 AND、购销方/项目/金额/税率/日期/角色组合检索，严格仅读已有投影与 `项目归属.json`/`发票标签.json`，有界上限保护，绝不扫描磁盘、不建 `runtime/targets/<id>`、不切 `watch_dir`，同时返回匹配目录/项目与未汇总目录计数）及 `GET /api/v1/workspace/project-index`（为侧栏折叠公司提供零写盘项目索引）。
    - 新增 `frontend/src/components/WorkspaceSearchModal.vue`（挂载于 `App.vue`，支持 `⌘K / Ctrl+K` 与侧栏按钮直达），点击发票命中调用 `stores/workspace.ts::locateInDirectory` 自动打开目标目录并由 `DirectoryInvoices.vue` 消费 `pendingLocate` 自动带入定位过滤；升级 `WorkspaceSidebar.vue` 支持侧栏检索自动加载折叠公司项目、自动展开并过滤匹配子目录/项目，以及一键跳转跨公司全局搜发票；`CompanyBankLedger.vue` 新增银行账户与期间表内快速过滤。
  - **WS-12 后端与前端**：
    - `monitoring/state.py` 与 `services/invoice_list.py`：将受保护手改字段 `EDITABLE_FIELDS` 扩展至 6 项核心字段（`销售方`、`购买方`、`开票金额`、`发票号码`、`开票时间`、`税率`），更新时合并保留既有手改字段并在增量重建中持久生效。
    - 新增 `src/invoice_hub/services/workspace_files.py`（组合于 `CompanyViewService.files`）与 `src/invoice_hub/api/routes/workspace_files.py`：实现目录与嵌套子目录有界浏览（标记并禁用符号链接）、`create_empty_subdir` 安全新建子文件夹、导入冲突预览（`import-preview`）与零额外依赖有界二进制流上传（`upload`，复用 `request.stream()` 与 `O_EXCL` 绝不覆盖同名文件，支持 `rename`/`skip`）、单文件安全重命名（无覆盖并自动迁移 `manual_overrides.json`）、跨目录移动（`move/preview` → 持久化意图日志 `workspace-moves/<job_id>.json` → `plan_hash` + `confirm: true` 无覆盖原子移动 + 手改迁移 + 只读失联结果查询）及原生回收站删除（`trash/preview` → `plan_hash` + `confirm: true` → `move_to_trash`，严禁永久删除降级）；严格遵守 `BOOKKEEPING.md`，非监控发票目录拒绝打开/重命名/移动/删除现有原票。
    - 新增 `frontend/src/components/WorkspaceFileBrowser.vue`、`InvoiceManualEditModal.vue` 与 `FileMoveModal.vue`，接入 `DirectoryPanel.vue`（非发票/普通资料目录直接呈现通用文件视图，发票目录保留默认发票列表并提供「发票列表 / 文件管理与导入」切换）与 `DirectoryInvoices.vue`（活动监控目录右键与批量菜单新增编辑手改字段、重命名原文件、移动到其他目录，非监控目录严格隐藏），重建并提交 `web/static/app/`。
  - **隔离实机预览布局修复**：在独立合成后端（`127.0.0.1:18769`，数据全位于 `/tmp/ih-p1p2-preview`）实机浏览器走查中同步修复 4 处细节：（1）`prototype.css` 为 `.ws-sidebar-toggle` 增加 `flex: none; white-space: nowrap;`、为 `.ws-tabs` 增加 `flex: 1 1 0; min-width: 0;`，防止多标签打开时“公司与目录”按钮被挤压竖排折行；（2）`WorkspaceSidebar.vue::openMenu` 改用 `nextTick` 实测浮层宽高做视口边界夹紧，修复新增公司右键项后底部略裁切；（3）`WorkspaceFileBrowser.vue` 为文件表 `.row-actions` 启用自动换行并为文件名列加 `max-width` 单行省略，消除窄容器下右侧操作按钮裁切；（4）`prototype.css` 将 `.filters .field :is(input,select)` 与 `.invoice-tags input, .invoice-tags select` 的 `min-height: 36px; padding: 0 10px;` 调整为 `height: 36px; padding: 6px 10px; line-height: 22px;`，修复主筛选栏、高级筛选栏及标签设置中原生 `<select>` 文字贴顶未垂直居中的问题。
- 验证范围：
  - 前端：`pnpm run typecheck`（0 错误）、`pnpm test`（23 份测试文件 185 项全部通过，含新增 `frontend/tests/workspace-phase2.spec.ts` 4 项）、`pnpm run build`（刷新 `web/static/app/`）。
  - 后端：`pytest tests/test_workspace_search_and_files.py tests/test_company_crud_and_search.py tests/test_company_folders.py tests/test_company_setup.py tests/test_company_views.py tests/test_company_directory_guards.py tests/test_api_companies.py tests/test_appstate_service_wiring.py tests/test_workspace_frontend.py tests/test_api_contract.py`（226 项全部通过）、`python -m compileall src tests`、`ruff check`、`pytest tests/test_development_documentation.py` 与 `git diff --check`。
- 未覆盖项：未覆盖真实默认配置、正式 Windows BAT、浏览器前台实机拖放/交互、系统原生选择器弹窗、macOS/Windows 真机原生回收站端到端调用与双平台打包产物。

### 2026-11-26 工作区 Phase 1：公司级增删改查闭环与单目录深度查询增强

- 需求与起点：基于已合入 PR #34 的干净主线 `origin/main@2c809d817cb984d550bcf46abe71f97fd6a6e365`，在隔离工作树 `InvoiceHub-workspace-crud-search`（分支 `codex/workspace-crud-search-p1`）推进用户新增遗漏需求的 Phase 1：（1）补齐自建/导入公司资料夹及工作区公司级增删改查闭环（重点解决已创建/导入公司资料夹缺少直达移除与原生回收站删除选项、根目录无法重定位/硬盘改名、自建不能按需选目录与附带自定义目录、导入不能顺带纳入其它子目录）；（2）修复实测发现的查询硬缺陷（开具发票搜购买方失效、日期区间放行空日期、关键字无法搜项目/金额/税率且不支持多词、自定义目录角色未同步）并补齐高级组合筛选与排序。Phase 2（跨目录/跨公司全局检索、文件拖放导入/单票手改/重命名与跨目录移动归档、通用文件视图）同步登记至 `docs/PRODUCT_BACKLOG.md`（`WS-11`、`WS-12`）。
- 采用方案：
  - **后端公司级 CRUD 闭环**：
    - `src/invoice_hub/services/company_folders.py` 与 `src/invoice_hub/api/routes/companies.py` / `company_folders.py`：新增 `POST /api/v1/companies/{company_id}/trash-preview` 与 `POST /api/v1/companies/{company_id}/trash`（有界扫描文件/子目录数与字节数、明确列示外部导入目录不受影响、阻断监控中/系统根/用户主目录/程序根/跨公司重叠、带 `plan_hash` + `confirm: true` 与全公司子目录写锁调用 `move_to_trash` 移入系统原生回收站并解除登记，严禁永久删除降级）；新增 `POST /api/v1/companies/{company_id}/open-root` 与 `POST /api/v1/companies/{company_id}/folders/{key}/open` 安全打开本地目录（拒绝缺失/链接目录）。
    - `src/invoice_hub/services/company_registry.py`：`create_company` 支持校验并持久化可选 `hidden_subdirs` 与 `custom_folders`；`update_company` 为 `root_dir` 重定位补齐与本公司外部文件夹重叠校验，并新增可选 `rename_root_on_disk` + `new_root_name` 安全硬盘改名（通过 `CompanyFolderService.rename_company_root_with_overrides` 在全子目录写锁内原子改名并迁移全部公司内子目录的 `manual_overrides.json`，清单写入失败自动回滚）。
    - `src/invoice_hub/services/company_setup.py`：支持可选 `selected_standard_keys`（未选标准目录不建盘并记入 `hidden_subdirs`）与 `custom_folders`（纳入同一 `plan_hash` 与防篡改 `_mkdir` 流程）；不传时与旧版 100% 兼容。
    - `src/invoice_hub/services/company_detection.py`：`_inspect` 额外扫描根内未被 6 类占用的真实一级子目录返回 `extra_folders`（含建议角色、文件数并绑定 `extra_identities` 入 `plan_hash`），`register` 支持可选 `import_extra_folders` 一次性以 `inside_root` 自定义目录纳入（零文件移动）。
  - **后端单目录深度查询与缺陷修复**：
    - `src/invoice_hub/services/invoice_list.py`、`src/invoice_hub/services/company_views.py`、`src/invoice_hub/api/routes/invoices.py` 与 `companies.py`：在 100% 保留经典 `search_scope=invoice|filename|all` 单串兼容语义前提下，新增 `workspace`、`party`、`buyer` 深度搜索范围并支持空格分词多词 AND 匹配（覆盖销售方、购买方、票号、文件名、项目、金额、税率及标准化百分数、发票大类、业务类型、开票日期）；修复 `date_from`/`date_to` 放行空日期记录的缺陷；新增精确 `Decimal` 金额区间（`amount_min`/`amount_max`，非法输入 422）、标准化税率筛选（`tax_rate` 及 `__missing__`）、项目筛选（`project` 及 `__unassigned__`）、未打标签筛选（`tag=__untagged__`）、多字段排序（`sort_by`/`sort_dir`，兼容旧 `date_sort`，缺失值统一排尾）以及目录级全量 `filter_options` 元数据。
  - **Vue 3 工作区前端交互**：
    - 新增 `frontend/src/components/CompanyDeleteModal.vue`（遵循 `WORKSPACE_UI_STANDARD.md` 令牌与 `WsModal`，默认“仅从清单移除”，可选“移入系统回收站并移出清单”预览勾选确认），接入 `WorkspaceSidebar.vue`（公司右键新增编辑设置/打开文件夹/移除或删除公司、目录右键新增打开文件夹）、`CompanyPanel.vue`（页头快捷操作与失效根目录重定位提示）及 `CompanySettings.vue`（新增公司根目录路径重定位、原生目录选择器与可选硬盘改名）。
    - 更新 `CompanyCreateForm.vue`（自建支持勾选标准目录子集与新增自定义子目录；导入向导展示并允许勾选顺带导入 `extra_folders`）、`DirectoryPanel.vue`（页头新增打开文件夹）、`DirectoryInvoices.vue`（改用 `effectiveFolderRole` 修复自定义目录提示与项目列；默认 `workspace` 多词搜索 + 回车直搜 + 搜索范围切换 + `重复发票` 状态 + 可折叠高级筛选栏 + 金额与开票时间排序 + 一键重置筛选 + 活动监控目录单行预览/打开原文件/在文件夹中显示）、`stores/companies.ts`、`api/types.ts`、`prototype.css`，重建并提交 `web/static/app/`。
- 验证范围：
  - 前端：`pnpm run typecheck`（0 错误）、`pnpm test`（22 份测试文件 181 项全部通过，含新增 `frontend/tests/workspace-crud-search.spec.ts` 4 项）、`pnpm run build`（生成 `web/static/app/`）。
  - 后端：`pytest tests/test_company_crud_and_search.py tests/test_company_folders.py tests/test_company_setup.py tests/test_company_views.py tests/test_company_directory_guards.py tests/test_workspace_frontend.py tests/test_api_contract.py`（169 项全部通过）、`python -m compileall src tests`、`ruff check`（涉及源码与测试全部通过）、`pytest tests/test_development_documentation.py` 与 `git diff --check`。
- 未覆盖项：未覆盖真实默认配置、正式 Windows BAT、浏览器前台实机交互、系统原生选择器真实弹窗、macOS/Windows 真机原生回收站端到端调用与双平台最新打包产物。

### 2026-11-25 支持公司自定义与默认文件夹全生命周期管理及基准功能指向

- 需求与起点：基于已合入 PR #33 的干净主线 `origin/main@da6491cec736203b494e5ebd7aeb6e4fa9debdb2`，新建隔离工作树与分支 `codex/company-custom-folders`，解决 `v1.0.0` 发布前用户提出的紧急必要需求：（1）公司资料夹下除默认 6 类目录外，支持用户自定义文件夹的新建、删除、重命名与导入已存在文件夹（涵盖默认目录的创建、隐藏恢复与回收站删除）；（2）自定义与导入的文件夹支持以默认 6 类目录为基准的功能指向，并开放完整单目录操作同时默认隔离公司总账/成本 V2/凭证草稿口径。
- 采用方案：
  - **后端文件夹生命周期与数据契约**：
    - `src/invoice_hub/services/company_folders.py`（新增）与 `src/invoice_hub/api/routes/company_folders.py`（新增，挂载至 `api/app.py`）：在 `CompanyRegistryService` 同一把 RLock 与 revision CAS 下新增 10 条 `/api/v1/companies/{company_id}/folders/*` 路由，支持未登记目录发现（`discover`）、新建空文件夹预览/确认（`create/preview`、`create`，复用 `company_directory_guard.create_empty_subdir` 防链接/TOCTOU）、公司内（`inside_root`）与公司外任意本地目录（`external`）导入（拒绝符号链接/junction、系统根/项目根/公司根及公司内/跨公司重叠路径，按 `serialize_config_path` 规范化保存）、显示名/角色编辑及可选硬盘原子改名（监控或写锁占用阻断，清单写入失败自动回滚）、非破坏性移除/隐藏（`files_touched: 0`）、恢复隐藏默认目录、原生回收站预览/确认（有界文件数/字节数统计 + 外部路径警示 + `plan_hash` + `confirm: true` → 调用 `platform/trash.py::move_to_trash`，严禁永久删除降级），以及公司内自定义目录二次确认晋升为主标准槽位（原主槽位保留为自定义目录）。对未同步目录改用 `_try_profile_lock` 先查状态目录再取锁，避免凭空生成 `runtime/targets/<id>`。
    - `src/invoice_hub/services/company_registry.py` 与 `src/invoice_hub/targets/companies.py`：在保持 `companies.json` `schema_version: 1` 兼容前提下新增严格校验的可选字段 `custom_folders`、`hidden_subdirs`、`subdir_labels`（畸形/嵌套/越界均返回 `COMPANY_REGISTRY_CORRUPT` 并拒写），保留默认 6 键并附带 `hidden` 标记，扩展 `company_for_dir` 支持外部导入目录最深路径归属查找（跳过链接）及 `folder_roles` 元数据输出。
  - **按基准功能指向分发**：
    - `services/company_refresh.py`、`services/company_views.py`、`services/source_move.py`、`services/company_bank_layouts.py`、`api/routes/companies.py` 与 `api/routes/company_workspace.py`：默认后台刷新覆盖可见发票类默认与自定义目录；目录发票、同号检查（先校验发票角色再判勾稽关系）、属期核对与确认移动、`GET .../bank-layouts?dir_key=...` 与 `GET .../payroll?dir_key=...` 均按目录 `role` 分发单目录能力，公司总账/成本 V2/凭证草稿仍严格只消费默认标准槽位。
  - **Vue 3 工作区前端与实机验收修复**：
    - 新增 `CompanyFolderCreateModal.vue`、`CompanyFolderEditModal.vue`、`CompanyFolderDeleteModal.vue` 三套 `WsModal` 组件，接入 `WorkspaceSidebar.vue`、`CompanyDirectories.vue`、`DirectoryPanel.vue`、`BankLayouts.vue`、`CompanyOverview.vue`、`CompanySettings.vue`、`WorkspaceModule.vue`、`stores/companies.ts`、`stores/workspace.ts`（新增 `closeDirectory` 同步关闭目录页/比较页/侧栏置顶与比较基点）及 `relations.ts`，重建并提交 `web/static/app/`。
    - 在隔离合成后端实机浏览器验收中发现并当场修复 3 项问题：（1）`DirectoryPanel` 改用独立 `editTarget`/`deleteTarget` 快照，修复保存改名或移除后 `companySourceKey` 刷新置空 `directory.value` 导致弹窗提前卸载、吃掉关闭与关页回调的竞态；（2）统一通过 `workspace.closeDirectory` 按 `tabId({ kind: "directory", ... })` 关闭目录标签页，消除移除后残留 `dir_...` 错误标签页；（3）`CompanyDirectories` 表格包裹 `.overview-table-wrap` 并为 `.row-actions` 启用换行，修复 1280px 与 390px 窄屏下操作列裁切。
  - **PR #34 自动评审修复（P1 / P2）**：
    - `targets/companies.py`、`services/company_directory_guard.py`、`services/company_folders.py` 与 `services/company_registry.py`：`resolve_external_folder` 改为词法拼装不跟随链接，新增 `external_path_snapshot` 与 `external_path_is_real_dir` 逐级前缀 `lstat` 校验；外部目录或任一上级事后被替换为软链/junction 时，`_public` 报 `outside_root`、`_trash_plan` 阻断（`can_trash=False`）、硬盘改名返回 409、`company_for_dir` 与重叠检查均不跟随链接目标，且导入阶段同时拒绝链接父目录。
    - `services/company_payroll.py`、`services/company_views.py` 与 `frontend/src/components/DirectoryPanel.vue`：`read_payroll` 新增 `include_saved: bool = True`，自定义工资社保目录预览传 `include_saved=False` 仅解析本目录文件、不再混入公司 `做账草稿/申报数据.json` 已确认月份；前端同步保留并标红展示后端 `checks_ok=false` 及失败核对项、消费 `files` 非 `parsed` 项统计未识别文件数并完整提交重建的 `web/static/app/`（含 `app.css`/`app.js`/`index.html`）。
    - `services/company_folders.py::_rename_disk_with_overrides`：标准与自定义文件夹硬盘重命名时按目标 ID 序持锁、将原 profile 的 `manual_overrides.json` 按新目录路径重写键并原子迁移至新 profile（清单保存失败时同时回滚目录名与手改文件，成功后清理旧 profile 迁移项），保护用户手改字段不因改名丢失。
    - `frontend/src/components/CompanySettings.vue`：引入 `baseSubdirs` 基线快照追踪标准目录映射；外部改名或晋升后自动刷新未编辑项（保留公司名等未保存草稿），并对存在冲突的过期映射草稿阻断保存并提示先刷新，避免常驻设置页静默把改名/晋升后的标准槽位写回旧路径。
  - **文档同步**：同步更新 `docs/architecture/FILE_MAP.md`、`INTERFACES_AND_FLOWS.md`、`DATA_AND_ALGORITHMS.md`、`AGENT_TASK_MAP.md`、`COMMENT_RATIONALE_MAP.md`、`docs/architecture/rules/BOOKKEEPING.md`、`docs/architecture/rules/WEB_UI.md` 与 `IMPLEMENTATION_STATUS.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：后端新增 `tests/test_company_folders.py` 与既有公司/视图/移动/成本 V2/契约/文档全套 pytest（473 项）、`ruff check src tests`、`python -m compileall -q src tests`、`git diff --check`；前端 `vue-tsc --noEmit`、`vitest run`（21 份测试文件 176 项，含新增 `frontend/tests/company-folders.spec.ts`）与 `vite build`；独立临时合成后端（`127.0.0.1:18767`，数据全位于 `/tmp/ih-cf-verify` 并已收尾清理）实机内置浏览器完成桌面 1280×860 浅/深色、`?no_skin=1`、390×844 窄屏及创建预览确认、跨路径外部导入并读出合成发票、硬盘改名并切换银行流水角色渲染属期/版式、回收站预览检查、非破坏移除关页与默认目录隐藏恢复全流程验证（修复复验后 0 控制台/页面报错）。
  - 未覆盖项：未覆盖真实业务资料夹与真实默认配置、系统原生目录选择器弹窗（浏览器验收直接输入合成外部路径）、真实操作系统回收站实移（后端单测已覆盖 `move_to_trash` 调用契约，实机浏览器仅验到预览与勾选门禁）、正式 Windows BAT、浏览器前台拉起与双平台最新打包产物验收；待本分支经用户确认推送合入 `main` 后再统一对齐双平台 `v1.0.0` 正式打包验收。

### 2026-11-25 修复 Windows 锁定运行时准备脚本 `-I` 忽略 `PYTHONDONTWRITEBYTECODE` 导致的 `__pycache__` 打包阻断

- 需求与起点：Windows x64 实机按 `codex/release-v1.0.0@d5bbe65` 构建 `v1.0.0` Tauri portable 候选包时，在锁定 runtime 校验阶段触发真实门禁阻断：`locked Windows runtime contains cache content: Lib\__pycache__`。核查确认为 `scripts/dev/prepare_windows_runtime.ps1` 在 `normalize-windows` 清理字节码缓存后，后续对产品 `python.exe` 的 `pip check`、`import` smoke（使用 `-I`，会忽略 `PYTHONDONTWRITEBYTECODE=1`）与 `runtime_manifest write` 以及 `scripts/dev/build_windows_portable.ps1` 调用 `build_core` 均未显式传 `-B`，重新生成了字节码缓存。
- 采用方案：
  - `scripts/dev/prepare_windows_runtime.ps1`：对 `normalize-windows`、`pip check`（`-I -B`）、import smoke（`-I -B`）和 `runtime_manifest write`（`-B`）四处产品 `python.exe` 调用显式加 `-B`，并在 `write` 之后增加对 `$runtimeDir` 残留 `__pycache__`/`.pyc`/`.pyo` 的 fail-closed 检查。
  - `scripts/dev/build_windows_portable.ps1`：给 `$buildArgs` 补充 `"-B"`，避免构建核心包时通过 `$runtimePython` 重新写入字节码缓存。
  - `tests/test_windows_release_contract.py`：补充 `-B`/`-I -B` 与末尾无缓存检查的脚本契约断言，并新增 `test_windows_runtime_isolated_checks_with_B_leave_no_bytecode_cache` 动态回归验证 `-I -B` 不产生字节码且 `-I` 会忽略 `PYTHONDONTWRITEBYTECODE=1`。
  - 同步更新 `docs/architecture/rules/RELEASE.md` 与 `docs/architecture/COMMENT_RATIONALE_MAP.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：macOS ARM64 本机 `.venv` 运行 `tests/test_windows_release_contract.py`、`tests/test_tauri_windows_portable.py`、`tests/test_release.py`、`tests/test_release_identity.py`、`tests/test_development_documentation.py`、`ruff check`、`git diff --check` 与 CRLF 换行核验；不涉及 `BUILD_INPUTS` 业务核心改动，`core_build_id` 保持不变。
  - 未覆盖项：未在 macOS 本机执行 Windows PowerShell 真机打包与 6 项真机冒烟、正式 Windows BAT、真实默认配置、浏览器前台拉起与原生目录选择器弹窗；待 PR #33 远端双平台 CI 全绿并合入 `main` 后，由 Windows x64 实机从最终 `main` clean commit 执行打包与真机冒烟验证。

### 2026-11-24 合入 PR #32 至 main 并执行 v1.0.0 正式升版与 macOS ARM64 候选包构建验收

- 需求与起点：基于已合入 PR #32 的干净主线 `main@50996436ae52e081f9f12d91b3e729609b50a4e3` 新建 `codex/release-v1.0.0`，将统一架构基线切换至新 `main`，把产品版本由 `1.0.0-beta.1`（`beta`）升至 `1.0.0`（`stable`），完善 `stable` 通道的更新元数据校验并构建验证 macOS ARM64 `v1.0.0` 候选 DMG。
- 采用方案：
  - **版本与稳定通道升级**：在 `src/invoice_hub/version.py` 将 `PRODUCT_VERSION`、`PYTHON_PACKAGE_VERSION` 升至 `1.0.0`、`UPDATE_CHANNEL` 切为 `stable`；在 `release/update_metadata.py` 与 `release/windows_alpha_metadata.py` 补齐 `stable` 通道校验（拒绝 prerelease/devrelease 版本）；运行 `scripts/dev/tauri_version_sync.py --write` 同步 `package.json`、`src-tauri/Cargo.toml`、`src-tauri/tauri*.conf.json`、`docs/release/WINDOWS_REPACKAGE_CONFIG.json` 与 `docs/release/WINDOWS_PUBLIC_PREVIEW_CONFIG.json`，同步更新 `src-tauri/tauri.windows.conf.json`、`src-tauri/Cargo.lock`、`.github/workflows/windows-public-preview.yml`、`scripts/dev/*.ps1`、`scripts/dev/verify_tauri_*.py`、`scripts/dev/tauri_public_preview_smoke.py`、`macos/InvoiceHubMac/script/*.sh` 及对应契约测试与主线基线文档。
  - **macOS ARM64 候选构建与验包**：在提交干净的 `codex/release-v1.0.0` commit 上运行 `scripts/dev/tauri_public_preview.py`（输入锁定 runtime `dist/runtime-inputs/20260909-optimized-macos/python`），产出并经 `verify_tauri_public_preview.py` 复验 `InvoiceHub-v1.0.0-macos-arm64-preview.dmg` 与 schema-4 收据（保留在 ignored `dist/candidates/` 下，不提交入仓）。
- 验证范围与未覆盖项：
  - 已运行并通过：`tauri_version_sync.py --check`、Rust `1.85.0` `cargo clippy --offline --locked --all-targets -- -D warnings` 与 `cargo test --offline --locked`、Ruff、Python `compileall`、`bash -n macos/InvoiceHubMac/script/*.sh`、版本/更新/发布/文档契约全套 pytest（含 `test_release_identity.py`、`test_update_metadata.py`、`test_update_service.py`、`test_windows_alpha_metadata.py`、`test_tauri_foundation.py`、`test_tauri_public_preview.py`、`test_macos_release_contract.py`、`test_windows_release_contract.py`、`test_api_contract.py`、`test_website.py`、`test_development_documentation.py`），以及 macOS ARM64 `v1.0.0` 候选 DMG 打包与独立验包。
  - 未覆盖项：未覆盖 Apple Developer ID 正式签名/公证、Sparkle 线上升级、Windows x64 实机同源打包与 BAT 验收、真实默认配置与系统原生选择器弹窗；待 `codex/release-v1.0.0` 经你确认推送并合入 `main` 后，基于最终 `main` clean commit 执行双平台正式打标发布。

### 2026-11-24 推进 v1.0.0 里程碑 3：完成 FEEDBACK-01 方案 A 降级、首次使用引导、跨页面文案体检与门面文档刷新

- 需求与起点：基于已推送至 `origin/codex/workspace-p3@dfdc778` 的里程碑 2 提交，按用户确认推进 `FEEDBACK-01` 方案 A（暂不部署公网中转，降级为一键复制脱敏信息并跳转 GitHub Issue）、补齐工作区首次启动三步引导与跨页面文案体检，并刷新 `README.md`、`docs/USER_GUIDE.md` 与 `website/index.html` 对齐 `1.0.0-beta.1` 实际能力。
- 采用方案：
  - **FEEDBACK-01（方案 A 优雅降级）**：`services/feedback.py::configuration()` 补充只读 `issue_tracker_url` 并更新未配置中转提示；`frontend/src/components/FeedbackDialog.vue` 在 `!config.enabled` 时展示「复制脱敏信息并打开 GitHub Issue」操作与硬编码公开链接 `https://github.com/lyc1126/InvoiceHub/issues/new`，仅复制白名单环境字段或用户已填内容（绝不读取路径/发票/日志），同时保留 `INVOICE_HUB_FEEDBACK_URL` 中转模式及原禁用/回执契约；补充 `tests/test_feedback.py` 与 `frontend/tests/feedback.spec.ts` 用例。
  - **首次启动三步引导与跨页面文案体检**：
    - `frontend/src/views/HomeView.vue`、`frontend/src/prototype.css` 与 `frontend/src/App.vue` 在无任何已登记公司时于起始页展示三步引导卡（添加公司资料夹 → 设为监控目录 → 核对/做账与按需接入 OCR），提供「添加公司资料夹」「先试临时识别」「连接服务器目录」直达入口；已登记公司后保持原「今天处理哪家公司？」起始页。补充 `frontend/tests/app.spec.ts` 用例。
    - `web/static/js/page-settings.js` 更新 `renderOcr()` 展示 `OCR-01` 识别模式（未启用 / PaddleOCR 官方 API / 自建服务）与中文就绪态，刷新 `web/templates/settings.html` 资源版本至 `page-settings.js?v=20261124-ocr-settings-1` 并同步 `tests/test_api_contract.py`、`tests/test_frontend_contract.py`；同步修订 `frontend/src/views/TemporaryRecognitionView.vue` 扫描件引导提示至「OCR」页；重建 `web/static/app/`。
  - **门面与用户文档刷新**：按用户明确确认刷新 `README.md`、`docs/USER_GUIDE.md` 与 `website/index.html`，准确呈现多公司工作区、成本 V2、四维勾稽、通用凭证默认导出、按需 PaddleOCR、SMB/SFTP 只读服务器来源（试验版）、缓存治理与端口冲突引导恢复；顺带补齐 `website/tests/demo.test.cjs` 的 `app.skinBypassRequested` mock 使 15 项官网测试全过，并同步 `docs/PRODUCT_BACKLOG.md`、`docs/architecture/rules/WEB_UI.md` 与 `docs/architecture/INTERFACES_AND_FLOWS.md`。
  - **PR #32 评审缺陷与 CI 超时修复**：
    - `projections/costs.py` 与 `services/cost_item_types.py`：修复非监控公司（`export_to_source=False`）保存品目归类后，因源目录无固定 `成本发票明细.csv` 而跳过代际发布、导致 V2 分析继续读到旧品目表的问题；改为在 `source_exported=False` 场景下直接在 workspace 发布新代际（不向源目录写 CSV/XLSX），并经同一 `read_only_inputs()` 读路径二次核验，补充 `tests/test_cost_v2_completion.py` 回归。
    - `services/company_refresh.py`：修复关闭服务时在持有不可重入 `self._guard` 锁期间调用 `self._update_dir()` 触发死锁的问题，改为释放锁后再写入 `cancelled` 状态，补充 `tests/test_company_refresh.py` 回归。
    - `.github/workflows/ci.yml`：将 `windows` 任务 `timeout-minutes` 由 `30` 放宽至 `45`，避免 1550+ 条全量测试偶发 30 分钟超时。
  - **实机浏览器验收与修复**：在独立空目录本地服务（`http://127.0.0.1:18766`）完成真实浏览器 6 项核验（首次启动三步引导、深/浅色与 `?no_skin=1`、设置页 OCR 摘要、反馈弹窗方案 A、OCR 页、390×844 窄屏无横向溢出与内嵌官网），全程 0 控制台错误；验收中发现空公司态下 `/workspace/ocr` 因被归入需绑定监控公司的经典模块而隐藏 iframe，随即在 `frontend/src/components/WorkspaceModule.vue` 将 `ocr` 与 `settings` 一并改为全局可见模块并补齐 `frontend/tests/app.spec.ts` 回归与 `web/static/app/` 重建。
- 验证范围与未覆盖项：
  - 已运行并通过：`node --check web/static/js/page-settings.js`、`node --test website/tests/demo.test.cjs`（15/15）、`node --test tests/frontend_interactions.test.cjs`（20/20）、Vue `vue-tsc --noEmit`、`vitest run`（20 文件 171 项）、`vite build`；Ruff、Python `compileall`、`git diff --check`；Python 回归涵盖 `test_feedback.py`、`test_website.py`、`test_workspace_frontend.py`、`test_frontend_contract.py`、`test_api_contract.py`、`test_tauri_foundation.py`、`test_windows_release_contract.py`、`test_development_documentation.py`；实机内置浏览器完成隔离空目录（`127.0.0.1:18766`）桌面 1280×860 与窄屏 390×844 目视与 DOM 验收（含深/浅色与 `?no_skin=1`）。
  - 未覆盖项：未覆盖主 8766 端口真实默认配置、Ink Pulse / Animal Island 经典装饰皮肤、正式 Windows BAT、浏览器前台拉起、系统原生选择器与双平台打包产物验收。

### 2026-11-24 推进 v1.0.0 里程碑 2：实现 ENG-09 缓存容量治理、OCR-01 PaddleOCR 接入、BK-01 通用凭证默认导出与 ENG-04 架构入口文档收拢

- 需求与起点：基于已推送至 `origin/codex/workspace-p3@15c2a23` 的里程碑 1 提交，按 `v1.0.0` 收口顺序连续推进 4 项无外部样本阻塞的必做项（`ENG-09`、`OCR-01`、`BK-01`、`ENG-04`），并修复 PR #32 CI 中暴露的 1 处 Rust 回环 mock 测试分包读取偶发失败及 1 处 Windows OFD 缓存测试平台字段失配。
- 采用方案：
  - **修复 CI 暴露的跨平台测试稳定性**：`src-tauri/tests/lifecycle_contract.rs` 新增 `read_http_request()` 按 `Content-Length` 完整读取 HTTP 请求体，消除 `headers + body` 分次 `write` 时单次 `read` 遗漏 JSON 正文的竞态；`tests/test_ofd_rendering.py::test_component_verification_cache_invalidates_on_file_changes` 在 Windows 上同步将 `platform` 与 `_platform_id` 对齐为 `windows-x64`（此前写死 `macos-arm64` 却在 Windows 创建 `java.exe`，导致 `Windows Python and release contracts` 1546 过 / 1 败）；`extraction/ocr_client.py::OcrResultCache._connect` 改为 `@contextmanager` 显式关闭 SQLite 连接以避免 Windows 文件句柄占用。
  - **ENG-09（完整代际与原始解析缓存容量治理）**：
    - `storage/generations.py` 新增 `pin_generation` 进程内读者固定、`prune_generations`（保护当前 manifest、回执引用代际与固定读者，坏 manifest 跳过不删，先改名 `.pruning-*` 墓碑再删除以支持崩溃续接，并清理超时 `.candidate-*`）与 `generation_usage`，并在 `publish()` 后自动有界回收。
    - `storage/parse_cache.py` 兼容升级旧 6 列 `raw` 表补充 `last_used` 列，新增 `ParseCache.prune(active_paths, version_prefixes, max_rows, max_bytes)` 与 `prune_damaged_caches`；`projections/incremental.py` 与 `services/source_worker.py` 在完整发布/解析后按前缀清理孤儿与旧解析器版本行。
    - `storage/source_cache.py` 新增 `evict_objects`（清理超时 `.part`/墓碑/孤儿并按 `last_used_at` LRU 回收未固定副本）、`prune_summary_generations` 与 `cache_usage`；`services/sources.py` 与 `source_worker.py` 在下载/汇总/修改预算/提交后传入活动预览租约 `pinned_objects`，严守绝不删除在读预览副本、源票、人工状态或导出回执。新增 `tests/test_cache_governance.py`。
  - **OCR-01（PaddleOCR 官方 API / 自建服务接入与社保截图识别）**：
    - 新增 `extraction/ocr_client.py`：支持 `disabled`（默认）/ `paddle_api`（官方 API）/ `paddle_self_hosted`（用户自建 HTTP 服务）三种模式，使用标准库 HTTP 客户端（零新增依赖），实现 URL/凭据边界校验、按文件内容 SHA-256 缓存的 `OcrResultCache`（防重复计费）、坐标排序、401/429/超时/断网无令牌泄露诊断，以及复用 PDF 提取规则并二次校验发票号码位数、合法税率与 `金额 + 税额 = 价税合计` 的 `extract_validated_invoice_fields`。
    - `services/ocr.py` 与 `api/routes/ocr.py` 将非敏感设置存 `runtime/ocr-settings.json`、Access Token 独立存 `runtime/.ocr-secrets.json`（`0o600`，不进 `app.local.json` 或 API 返回），云端模式要求显式隐私确认与按公司单独授权；`services/company_payroll.py` 抽出 `parse_payroll_text()` 并接入 `OcrService.payroll_reader_for_company`，支持社保缴费截图按公司授权走同一确定性表格解析与算术校验；升级 `web/templates/ocr.html` 与 `web/static/js/page-ocr.js`（资源版本升至 `20261124-ocr-paddle-1`）。新增 `tests/test_ocr_paddle.py`。
  - **BK-01（凭证导出默认切换「通用凭证表」与去品牌化）**：
    - `bank/export_profiles.py` 新增 18 列软件无关标准 `generic`（`通用凭证表（标准）`，状态 `standard`，前缀 `通用凭证导出`）并置于 `PROFILES` 首位，新增 `read_generic_entries()` 实现导出后无损读回验证；保留 `jierui`（`verified`）黄金模板逐单元格不变。
    - `services/company_vouchers.py` 与 `frontend/src/components/CompanyVouchers.vue` 将默认导出格式切换为 `generic` 并适配 `standard` 状态展示，重建 `web/static/app/` 产物，补充 `tests/test_export_profiles.py` 无损读回与去品牌断言。
  - **ENG-04（架构入口文档只描述当前状态）**：将 `docs/DEVELOPMENT_ARCHITECTURE.md`、`IMPLEMENTATION_STATUS.md`、`docs/architecture/AGENT_TASK_MAP.md` 与 `docs/architecture/PLATFORM_ARCHITECTURE.md` 顶部堆叠的历史日期流水段落收拢为简洁的当前状态总览（历史记录全部保留在 `CHANGELOG.md`），同步更新 `INTERFACES_AND_FLOWS.md`、`DATA_AND_ALGORITHMS.md`、`FILE_MAP.md`、`PRODUCT_BACKLOG.md` 与 `COMMENT_RATIONALE_MAP.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：本机 macOS ARM64 固定 Rust `1.85.0` 的 `cargo fmt --check`、`cargo clippy --offline --locked --all-targets -- -D warnings`、`cargo test --offline --locked`（107/107）；Ruff、Python `compileall`、`git diff --check`；Python 回归涵盖 `test_cache_governance.py`、`test_incremental_projections.py`、`test_server_sources.py`、`test_sftp_source.py`、`test_company_refresh.py`、`test_ocr_paddle.py`、`test_company_payroll.py`、`test_export_profiles.py`、`test_company_vouchers.py`、`test_bank_vouchers.py`、`test_ofd_rendering.py`、`test_workspace_frontend.py`、`test_frontend_contract.py`、`test_api_contract.py`、`test_development_documentation.py`；Vue `vue-tsc --noEmit`、`vitest run`（20 文件 171 项）、`vite build`。
  - 未覆盖项：未覆盖 PaddleOCR 官方 API 实网调用与真实扫描发票/社保截图实测、真实非捷锐记账软件（如柠檬云/用友/金蝶）真实账套导入、真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器与双平台打包产物验收；本轮改动先在本地提交至 `codex/workspace-p3`，待确认后再推送 PR #32 触发 Windows 与全平台 CI 复验。

### 2026-11-24 收口 Windows 发布版本配置漂移与工程项 ENG-01 / ENG-02 / ENG-10

- 需求与起点：基于 `codex/workspace-p3@9f3d485` 按 `v1.0.0` 版本收口路线推进第一批代码与工程收尾：修复 `1.0.0-beta.1` 升级后遗留的 Windows 发布配置版本漂移、清零 PR #32 采集的 3 条 Windows Rust clippy dead-code 警告并开启 `-D warnings` 阻断（`ENG-01`）、判定并修复开票参考保存时工作簿独有状态漏合并问题（`ENG-02`），以及实现固定 8766 端口冲突识别与用户确认后优雅关闭旧 InvoiceHub 的引导恢复（`ENG-10`，保留桌面窗口创建失败转默认浏览器兜底）。
- 采用方案：
  - **Windows 发布配置版本对齐与同步守护**：将 `docs/release/WINDOWS_REPACKAGE_CONFIG.json`、`docs/release/WINDOWS_PUBLIC_PREVIEW_CONFIG.json` 及 `.github/workflows/windows-public-preview.yml` 的版本与产物流水名同步至 `1.0.0-beta.1`；扩展 `scripts/dev/tauri_version_sync.py` 在 `--check` / `--write` 中同步校验并写回两份 Windows 发布配置锁，防止后续升至 `1.0.0` 再次漂移，并扩展 `tests/test_tauri_foundation.py` 覆盖两份配置锁漂移修复。
  - **ENG-01（Windows Rust clippy 清零并阻断）**：为 `src-tauri/src/host_rpc.rs` 中仅 macOS 重启路径使用的 `UpdaterRuntimeState::prepare_relaunch`、`HostRelaunchError::{BackendUnavailable, BackendShutdownFailed, StateTransitionRejected}` 与 `HostRelaunchRequester::{app_handle, runtime_gate}` 加上 `#[cfg(target_os = "macos")]`（Windows updater 2.10.1 经 `on_before_exit` 直接退出并拉起安装器，不走 `request_relaunch`）；将 `.github/workflows/ci.yml` 中 `windows-latest` 的 `clippy_flags` 切换为 `-D warnings`。
  - **ENG-02（开票参考保存合并工作簿独有状态）**：确认 `projections/costs.py::save_reference_status` 此前读取 `_read_reference_status_from_workbook()` 后丢弃导致保存 A 行时会清空仅存于 `成本发票汇总.xlsx` 的 B 行已开/自定义加价率状态；改为仅合并非默认（`invoiced_quantity > 0` 或非默认加价率）的工作簿独有条目及既有条目空白字段，移除 `# noqa: F841`，并在 `tests/test_summary_and_costs.py` 新增 `test_save_reference_status_preserves_workbook_only_status_for_untouched_rows`（含显式归零重置验证）。
  - **ENG-10（固定 8766 端口冲突识别与引导恢复）**：严守固定 `127.0.0.1:8766`、不换端口、不接管/不强杀未知进程边界，在 `src-tauri/src/backend.rs` 新增 `ExistingInvoiceHubClaim`、`parse_existing_invoicehub_claim`（要求 `ok=true`、`pid>0`、`api_contract_version`、`product_version`、`package_type`、`config_path`、`runtime_dir` 完整契约字段并剔除控制字符）、`resolve_port_conflict_with` / `resolve_port_conflict_at` / `resolve_fixed_port_conflict`；在 `src-tauri/src/startup_diagnostics.rs` 新增 `offer_existing_invoicehub_shutdown`（Windows 用默认选“否”的 `MessageBoxW`，macOS 用 `tauri-plugin-dialog` 确认框，`--no-startup-dialog` 直接拒绝）；在 `src-tauri/src/main.rs` 的 `BackendHost::launch` 前接入冲突恢复：仅在用户明确确认且二次重检仍为同一 PID/版本/运行目录时，发送标准 `POST /api/v1/server/shutdown`（`{"shutdown_behavior":"keep_monitor","remember":false}`）并等待端口释放，超时或占用者变化立即 fail closed；既有桌面窗口创建失败转默认浏览器兜底链路及全部 `startup_tests` 保持不变。同步更新 `docs/PRODUCT_BACKLOG.md`、`docs/architecture/rules/TAURI_HOST.md` 与 `docs/architecture/COMMENT_RATIONALE_MAP.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：本机 macOS ARM64 固定工具链 `1.85.0` 的 `cargo fmt --check`、`cargo clippy --offline --locked --all-targets -- -D warnings`、`cargo test --offline --locked`（共 107 项全过：lib 61、main 6、lifecycle_contract 10 含新增 ENG-10 状态机与真实回环 HTTP 测试、monitor_recovery_contract 17、update_coordinator_contract 12、windows_marker_store_contract 1）；Ruff、Python `compileall`、`tests/test_windows_release_contract.py`、`tests/test_tauri_foundation.py`、`tests/test_tauri_lifecycle_contract.py`（含新增 ENG-10 契约测试）、`tests/test_tauri_host_rpc.py`、`tests/test_tauri_recovery_smoke.py`、`tests/test_source_snapshot.py`、`tests/test_build_manifest.py`、`tests/test_summary_and_costs.py`、`tests/test_company_costs.py`、`tests/test_development_documentation.py`、`git diff --check`。
  - 未覆盖项：Windows `clippy_flags: "-D warnings"` 与 Windows `MessageBoxW` 端口冲突弹窗仍需推送触发远端 `windows-latest` CI 与 Windows x64 实机验证；未覆盖真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器与双平台打包产物验收；本轮未推送远端或合并 `main`。

### 2026-11-24 收口 SSH / SFTP 只读试验版交互与诊断并完成本机 OpenSSH 端到端联调（WS-09 方案 A）

- 需求与起点：基于 `codex/workspace-p3@9569f5f` 按用户确认的方案 A 对 SSH / SFTP 只读试验版做上线前轻量收口：补齐路径规范化、添加后自动指纹探测、SSH Agent/网络/权限细分诊断，并补一轮真实 OpenSSH `sshd` + `sftp-server` + `ssh-agent` + OFD 预览端到端联调（密码/系统钥匙串凭据、跳板机与远程写入维持后续版本边界）。
- 采用方案：
  - **路径规范化与细分诊断**：`services/sources.py::add` 对 SFTP 根目录去除首尾空白并规范化非根路径尾斜杠（如 `/invoices/2026/` → `/invoices/2026`，`/` 保留，仍拒绝 `..`、`//` 与相对路径），同步裁剪 `host`/`username` 首尾空白；`storage/source_adapters/sftp.py` 新增只读 `_ssh_agent_auth_message()`（调用无提示 `ssh-add -l`，区分「未连接 SSH Agent」「Agent 已运行但未加载私钥、给出 `ssh-add` 提示」「服务器拒绝公钥认证」），并拆分 `Connection refused`、DNS 解析失败、超时、`subsystem request failed`、主机指纹失配及 SFTP 状态码 `2/3` 与符号链接重定向提示；放宽 `probe()` 允许主机公钥行尾附带注释字段，仍严格校验 key 类型与 base64。
  - **连接弹窗体验收顺**：`frontend/src/components/ServerConnectModal.vue` 在添加 SFTP 来源后自动触发一次 `{ kind: "probe" }` 读取主机密钥指纹（与 SMB 自动 `scan` 对齐），并在表单内明确说明「仅支持已解锁 SSH Agent 的只读 SFTP（试验版），不保存密码或私钥」；重建 `web/static/app/` 并同步功能规则与注释地图。
- 验证范围与未覆盖项：
  - 已运行并通过：Ruff、Python `compileall`、`tests/test_sftp_source.py`、`tests/test_server_sources.py`、`tests/test_ofd_rendering.py`（携带 `INVOICE_HUB_TEST_OFD_COMPONENT=runtime/components/ofd-preview`）、`tests/test_workspace_frontend.py`、`tests/test_frontend_contract.py`、`tests/test_api_contract.py`、`tests/test_development_documentation.py`、Vue `vue-tsc --noEmit`、`vitest run`（20 文件 171 项）、`vite build`、`git diff --check`。
  - 真实 OpenSSH 联调：在临时隔离目录内启动真实回环 `/usr/sbin/sshd`（`/usr/libexec/sftp-server`）与独立 `ssh-agent`，端到端验证 SFTP 尾斜杠路径登记、`ssh-keyscan` 真实指纹核验、扫描、子目录汇总、OFD 双页 Java 21 原生 PNG 渲染（`15,343` / `16,224` bytes）+ XML 预览、断连后离线显式预览，以及 `ssh-add -D` 空 Agent 触发 `auth_required` + `ssh-add` 诊断提示，随后彻底终止临时进程并清理临时目录。
  - 开发版打包：本地 DCO 提交后使用 `scripts/dev/tauri_dev_app.py build` 从干净提交重建 macOS ARM64 开发版 `InvoiceHub.app`（保留产物在 `src-tauri/target/release/bundle/macos/InvoiceHub.app`，未强行中断当前运行中的 `/Applications/InvoiceHub.app`）。
  - 未覆盖项：未覆盖跨网段/公网真实 Linux 或 NAS 服务器、VPN、Windows 11 OpenSSH 客户端实机、真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器与签名/公证 DMG；本轮仅本地提交，未推送远端或合并 `main`。

### 2026-11-24 修复开发版桌面端与 SMB 只读模式 OFD 预览并补齐双平台发布验包门禁

- 需求与起点：基于 `codex/workspace-p3@979c5e7` 专项排查并修复用户实测 SMB 只读模式下 OFD 识别正常但无法预览的问题。根因核实为三层叠加：(1) 本地 macOS Tauri 开发版 `InvoiceHub.app` 内含 `invoice-hub-build.json` 触发打包分支，导致 `OFDRenderer` 只查 `.venv/components/ofd-preview` 而找不到仓库内已构建的 `runtime/components/ofd-preview`；(2) 双平台正式/预览组包与验包脚本尚未对 `components/ofd-preview` 实施 fail-closed 强校验；(3) 服务器只读预览透传了无效的“也可使用系统打开原文件”引导，且多页 OFD 在 `ServerPreviewDrawer` / `SourcePreview` 中并发加载缩略图 `<img>` 会撞上单 worker `_RENDER_SLOT`（`ofd_renderer_busy`），渲染期 `422` 错误也会被泛化为“授权过期”。
- 采用方案：
  - **OFD 组件定位与共享校验函数**：`services/ofd_rendering.py` 抽出共享 `verify_ofd_component()`（按目标平台校验 `component.json`、`ofdrw-2.4.0`、Java 21、`COMPONENT_SOURCE_FINGERPRINT`、无符号链接及逐文件 SHA-256）；发布模式（存在 `invoice-hub-package.json` 或 `INVOICE_HUB_RELEASE_MODE=1`）继续严格只信 `sys.prefix/components/ofd-preview` 并忽略开发变量；非发布开发包支持绝对路径 `INVOICE_HUB_DEV_OFD_COMPONENT`（同样走完整加密指纹与哈希校验）。`scripts/dev/tauri_dev_app.py` 在开发启动脚本中导出 `INVOICE_HUB_DEV_OFD_COMPONENT` 指向仓库 `runtime/components/ofd-preview`；正式/预览启动脚本（`tauri_public_preview.py`、`tauri_alpha_release.py`、`tauri_windows_preview_stage.py`）显式清空该开发环境变量。
  - **双平台发布组包与验包 fail-closed 门禁**：`verify_tauri_windows_portable.py`（同时将 `python/components/` 纳入 `dependency` 扫描范围）、`tauri_windows_portable.py`、`tauri_windows_preview_stage.py`、`tauri_alpha_release.py`、`verify_tauri_public_preview.py` 与 `verify_tauri_alpha.py` 均强制核对对应平台 `components/ofd-preview` 存在且指纹与逐文件哈希匹配，缺失或篡改直接拦截。
  - **SMB 只读预览文案、多页 OFD 防并发碰撞与错误诊断**：`services/file_preview.py` 新增 `allow_system_open`（默认 `True` 保持本地/经典链路不变），`services/sources.py` 传入 `allow_system_open=False` 去掉只读模式无效的“系统打开原文件”引导；`ServerPreviewDrawer.vue` 与 `SourcePreview.vue` 对多页 `.ofd` 改用页码跳转按钮避免并发缩略图请求触发 `ofd_renderer_busy`，并在 `ServerPreviewDrawer.vue`、`ServerSourcesPanel.vue` 与 `SourcePreview.vue` 图片加载失败时读取后端真实 `422/409` `detail`（`404/410` 保持单次自动重建）；重建 `web/static/app/` 并同步 `docs/OFD_PREVIEW.md`、架构地图与功能规则。
- 验证范围与未覆盖项：
  - 已运行并通过：Ruff、Python `compileall`、Vue `vue-tsc --noEmit`、`vitest run`（20 文件 170 项）、`vite build`、`node --test tests/*.test.cjs`（40 项）、`scripts/dev/tauri_dev_app.py stage` 后模拟开发包 `invoice-hub-core` + `INVOICE_HUB_DEV_OFD_COMPONENT` 真实双页 OFD 原生 PNG 渲染（`1063×591` / `591×1063`），以及携带本机 `INVOICE_HUB_TEST_OFD_COMPONENT=runtime/components/ofd-preview` 的相邻 pytest 套件（含本地与挂载共享源原生 Java 21 + OFDRW 多页渲染、发布验包正/负向门禁与文档契约）。
  - 既有无关基线说明：`tests/test_windows_release_contract.py::test_windows_repackage_config_is_complete_and_matches_release_identity` 仍存在源自 `cddafd2` 的 `WINDOWS_REPACKAGE_CONFIG.json` 版本号（`0.3.0-alpha.2` vs `1.0.0-beta.1`）既有漂移，本轮未修改该无关文件。
  - 未覆盖项：未覆盖真实局域网 SMB 业务 OFD 票面目视核对、重新安装覆盖 `/Applications/InvoiceHub.app`、真实默认配置、正式 Windows BAT、Windows x64 实机 OFD 组件构建/执行、浏览器前台拉起、系统原生选择器与签名/公证 DMG；本轮仅本地提交，未推送远端或合并 `main`。

### 2026-11-24 优化 SMB 服务器链接体验并补齐主工作区只读原生汇总、筛选、勾选合计与批量预览（WS-09）

- 需求与起点：基于 `codex/workspace-p3@30f06a6` 响应用户实测反馈：当前 SMB 试验版连接与浏览形态与原型差距较大，大共享盘下全根扫描/汇总易受无关目录和非发票 PDF 影响，且缺少原生发票汇总表、多维筛选、勾选合计拆组与批量原票预览。经用户确认采用「右侧轻量目录浏览 + 主工作区标签页铺开原生发票工作台（方案 A）」的一期设计。
- 采用方案：
  - **已挂载共享发现与按目录范围增量汇总**：`storage/source_adapters/__init__.py` 新增只读 `discover_mounted_shares()`（枚举系统已挂载网络共享卷，不主动发起挂载）并细化大共享盘枚举进度上报；`services/source_worker.py` 支持按 `parent_id` 仅拉取/解析所选子目录、自动跳过 macOS `._*` 伴随文件，并在混合目录出现非发票 PDF 成本解析异常时保留票头汇总且显式返回 `cost_error`，二次一致性核对同步收敛至当前子树，避免无关项目变动打断当前目录汇总；同步支持单任务批量下载 `entry_ids`（上限 100）。
  - **后端原生筛选/排序/分页、勾选合计与批量来源预览**：`services/sources.py` 与 `api/routes/sources.py` 新增 `GET /api/v1/sources/mounted-shares`、`POST /api/v1/sources/{sid}/selection-summary`、`POST /api/v1/sources/{sid}/previews/{job_id}/keep-alive` 及多文件预览内容路由 `files/{file_number}/text|pages/{page}`；扩展 `GET /api/v1/sources/{sid}/summary` 支持本目录或最近祖先汇总匹配、服务端全量 `keyword`/`file_ext`/`status`/`invoice_type`/`date_sort` 筛选排序、分页及原生四项统计 `invoice_stats`；勾选合计复用 `selection_family_key` 与 `selection_cost_breakdown`，继续严格绑定不透明 `entry_id`、汇总代际与来源隔离预览租约，不写入服务器、不切换活动监控目录。
  - **独立连接弹窗、原型对齐右侧栏与主工作区只读发票视图**：新增 `stores/sources.ts`、`ServerConnectModal.vue`（`WsModal` 共享文件夹 / SSH-SFTP 双分页、自动发现已挂载共享与收藏管理，无密码框）、重构 `ServerSourcesPanel.vue`（顶部目录/文件横向标签与蓝色进度条、目录级「汇总此目录」及一键打开主工作区入口）；在 `stores/workspace.ts` 与 `HomeView.vue` 新增 `server-dir` 标签并接入 `ServerDirectoryPanel.vue`、`ServerSelectionBar.vue` 与 `ServerPreviewDrawer.vue`（4 KPI 卡、多维筛选排序分页、显示列自定义、TSV 复制、勾选合计详情宽弹窗与 100 文件分组缩略图批量原票预览）。重建 `web/static/app/` 并同步架构五图与 `WEB_UI.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：`tests/test_server_sources.py`、`tests/test_sftp_source.py`、`tests/test_file_preview.py`、`tests/test_api_contract.py`、`tests/test_workspace_frontend.py`、`tests/test_frontend_contract.py`、`tests/test_development_documentation.py`、Ruff、Python `compileall`、Vue `vue-tsc --noEmit`、`vitest run`（20 文件 168 项）、`vite build`、`git diff --check`。
  - 未覆盖项：未覆盖真实 SMB/VPN 局域网共享与 SSH Agent 实服联调、真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生目录选择器与 Tauri 打包产物；本轮未推送远端或合并 `main`。

### 2026-11-24 调整工作区发票列表标签色点尺寸、标签列紧凑宽度与工具栏按钮间距

- 需求与起点：基于 `codex/workspace-p3@4d229dc` 响应用户反馈：工作区发票列表左侧标签色点偏小且与销售方列之间空白显得过宽；同时一并修正目录工具栏中「重新汇总」与「检查变动」按钮分散排版的问题。
- 采用方案：
  - **标签色点放大与叠放清晰度**：`DirectoryInvoices.vue` 用 `.tag-dots`（`inline-flex`）包裹色点确保居中对齐；`frontend/src/styles.css` 将表内 `.tag-cell .tag-dot` 由 `10px` 调整为 `14px × 14px`、叠加 `1.5px var(--surface)` 分隔环与 `-3px` 叠放（标签菜单 `.tag-dot` 同步调至 `12px`），在浅色、`website-dark` 与 `?no_skin=1` 下均清晰可辨。
  - **紧凑标签列宽与工具栏对齐**：`frontend/src/prototype.css` 与 `styles.css` 将 `.directory-invoices-table .tag-cell` 及 `.select-cell` 固定为 `width: 1%`（`min-width: 44px` / `40px`），并收紧 `.tag-cell` 右侧与紧邻首列左侧内距（`padding-right: 2px` / `padding-left: 6px`），避免隐藏部分数据列后 `table-layout: auto` 将多余表宽分配进标签列；同步将 `.directory-toolbar button` 改为 `.directory-toolbar button:first-of-type { margin-left: auto; }`，使「重新汇总」与「检查变动」在工具栏右侧成组对齐。重建 `web/static/app/` 并更新 `WEB_UI.md` 与 `frontend/tests/directory-preview.spec.ts`。
- 验证范围与未覆盖项：
  - 已运行并通过：Vue `vue-tsc --noEmit`、`vitest run`（20 文件 167 项）、`vite build`、`tests/test_workspace_frontend.py`、`tests/test_frontend_contract.py`、`tests/test_development_documentation.py`、`node --test tests/*.test.cjs`（40 项）、Ruff、`git diff --check`。
  - 合成 Chromium 实测（使用最新构建 `app.css` 与 `website-dark/skin.css`，覆盖 1100px 浅色/深色与 390px 窄屏）及独立隔离本地预览服务实机预览（`1280×800`，零控制台错误）：确认 `.tag-dot` 为 `14×14px`、`.tag-cell` 收束为 `48px`、工具栏按钮间距 `12px`、390px 无整页横向溢出；临时预览服务与合成目录已清理。
  - 开发版打包：本地 DCO 提交后使用 `scripts/dev/tauri_dev_app.py build` 重建 macOS ARM64 开发版 `InvoiceHub.app` 并更新至 `/Applications/InvoiceHub.app`。
  - 未覆盖项：未覆盖真实默认配置、正式 Windows BAT、Windows 打包产物、系统原生选择器与签名/公证 DMG；本轮仅本地提交，未推送远端或合并 `main`。

### 2026-11-23 解析器版本感知自动重算、成品油业务类型与工作区活动目录「重新汇总」

- 需求与起点：基于 `codex/workspace-p3@380a359`（保留同日未提交的工作区发票列表列宽/显隐/居中改动，本轮一起提交），排查并根治用户升级至 `1.0.0-beta.1` 后成品油专票在界面上仍显示空白销售方的问题。只读核查确认：新版解析器（BUG-04）本身已完整提取销售方、购买方、除税价与税金，界面空白源自三项叠加原因：(1) 既有工作区汇总文件停留在 BUG-04 之前且无 `projection-manifest.json`；(2) `MonitorSynchronizer` 未检测解析器版本变化，文件未变动时不自动重算；(3) 新版工作区对当前活动监控目录缺少手动「重新汇总」入口；同时用户确认将「成品油」补齐为独立特定业务类型，并在提交后更新本机开发版 `InvoiceHub.app`。
- 采用方案：
  - **解析器版本感知自动重算**：`storage/generations.py::publish` 在 `projection-manifest.json` 写入 `parser_versions`（`summary: PARSER_VERSION`、`cost: COST_PARSER_VERSION`），`publish_exports` 保留该字段；新增 `generations.parser_versions_stale`；`projections/incremental.py` 新增 `current_parser_versions()` 并写入新代际；`monitoring/sync.py::MonitorSynchronizer._run_sync_locked` 将 `parser_stale` 纳入 `should_rebuild`（排除在 `schema_only_refresh` 外，回报 `parser_refreshed`），升级后自动触发一次增量重建并保留手改字段，重建后稳态周期恢复零重解析。`services/company_views.py::directory_freshness` 对缺失清单或规则过期的非监控目录返回 `state: "stale"`、`parser_stale: true` 与“识别规则已更新”提示，`CompanyDataRefreshService` 非强制刷新亦会触发重建。
  - **特定业务类型新增「成品油」**：`extraction/classification.py` 登记 `BUSINESS_TYPE_REFINED_OIL = "成品油"`（含别名「成品油发票」），由 PDF 左上角业务标签坐标、OFD 坐标/CustomTag 与 XML 显式业务字段触发，公司名与商品名不触发；`web/templates/index.html` 特定业务筛选补充「成品油」；`services/document_index.py::CACHE_VERSION` 升至 `3` 使旧单据索引重提。
  - **工作区活动监控目录补齐「重新汇总」**：`frontend/src/components/DirectoryPanel.vue` 与 `CompanyDirectories.vue` 为当前活动监控发票目录提供「重新汇总」按钮（复用 `POST /api/v1/bridge/rebuild`，处理中保持 `aria-busy`、切换/卸载丢弃迟到响应，完成后弹 toast、派发 `workspace:company-refreshed` 并刷新）；非监控目录因规则升级过期时显示「（识别规则已更新）」，不显示「新增 0、改动 0、删除 0」。同步重建 `web/static/app/` 与更新架构地图及功能规则。
- 验证范围与未覆盖项：
  - 已运行并通过：新增后端/前端回归（`test_monitor_sync_auto_rebuilds_when_parser_version_changes_or_manifest_missing`、`test_parser_version_change_marks_non_monitored_directory_stale_and_refresh_rebuilds`、`test_refined_oil_business_type_uses_context_not_company_or_item_names`、`selection-summary-and-refresh.spec.ts`）；本机 macOS/Python 3.14.7 全量 pytest 除 1 项与本轮无关的既有发布配置版本基线失败（`test_windows_release_contract.py::test_windows_repackage_config_is_complete_and_matches_release_identity`，源于 `cddafd2` 未同步 `WINDOWS_REPACKAGE_CONFIG.json`）外全部业务与契约测试通过；Vue `vue-tsc --noEmit`、`vitest run`（20 文件 167 项）、`vite build`、`node --test tests/*.test.cjs`（40 项）、Ruff、Python `compileall`、`tests/test_development_documentation.py`、`git diff --check`。另在本机真实成品油 PDF 上做内存只读提取核对，确认 `invoice_type=增值税专用发票`、`business_type=成品油`、购销方与三项金额完整一致（不写入源目录或仓库）。
  - 开发版打包：本地 DCO 提交后使用 `scripts/dev/tauri_dev_app.py build` 重建 macOS ARM64 开发版 `InvoiceHub.app` 并更新至 `/Applications/InvoiceHub.app`。
  - 未覆盖项：未覆盖正式 Windows BAT、Windows 打包产物、系统原生选择器、签名/公证 DMG 及真实业务完整写盘验收；本轮仅本地提交，未推送远端或合并 `main`。

### 2026-11-23 调整工作区发票列表列宽间距、列显隐与居中对齐

- 需求与起点：基于 `codex/workspace-p3@380a359` 响应用户三项工作区发票列表排版与交互需求：(1) 收紧销售方与购买方之间的过大空白间隔，调整到合适宽度；(2) 支持隐藏发票列表不需要查看的数据列并支持随时恢复显示；(3) 发票列表所有显示列居中对齐。
- 采用方案：
  - **合理列宽与防撑宽截断**：`DirectoryInvoices.vue` 将列表包裹在 `.directory-invoices-wrap` 横向滚动容器内并保持真实 `<table>`（`display: table; width: 100%`）；为销售方/购买方（`.invoice-party__text`，`max-width: 196px`）及项目名（`.invoice-project__text`，`max-width: 180px`）增加 `inline-block` 单行省略与完整 `title` 悬停提示，防止单条超长单位名在 `table-layout: auto` 下将整列拉宽并在销售方与购买方之间留出大段空白，同时保留可选择文本与 Excel/WPS TSV 完整复制路径。
  - **列显隐与恢复持久化**：`frontend/src/stores/workspace.ts` 在 `localStorage`（`invoicehub.workspace.v1`）按目录类型 `dirKey` 持久化 `hiddenInvoiceColumns`（例如在成本发票隐藏购买方不影响开具发票显示购买方），并守护至少保留 1 个可见数据列及损坏配置自动回退；`DirectoryInvoices.vue` 在列表头右侧提供「显示列」勾选菜单（隐藏时显示「已隐藏 N」徽标与「恢复全部列」快捷入口），同时支持右键表头快速打开菜单，Esc 与视口边界约束遵守 KeepAlive 隐藏标签规则。
  - **显示列居中对齐**：`frontend/src/styles.css` 与 `frontend/src/prototype.css` 仅针对 `.directory-invoices-table` 将全部表头与数据单元格（含 `.num` 开票金额，保留 `tabular-nums`）设为 `text-align: center; vertical-align: middle;`，不影响账簿/成本/凭证等其它表格的数字右对齐规范。同步重建 `web/static/app/` 产物及更新 `WEB_UI.md`、`FILE_MAP.md`、`COMMENT_RATIONALE_MAP.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：Vue `vue-tsc --noEmit`、`vitest run`（20 文件 166 项，含 `frontend/tests/directory-preview.spec.ts` 新增列显隐持久化、最少 1 列保护、右键表头、居中与列宽上限回归）、`vite build`、`tests/test_workspace_frontend.py`、`tests/test_development_documentation.py`、`node --test tests/*.test.cjs`（40 项）、Ruff、Python `compileall`、`git diff --check`。
  - 隔离合成浏览器实测（本机 Chrome，独立临时目录，不触碰真实默认配置）：验证浅色 1440×900 全部列计算样式 `text-align: center`、超长销售方截断至 196px 且 `销售方` 列宽收束在 216px、隐藏/重载持久化/右键表头/恢复全部列，`website-dark` 深色皮肤与 `?no_skin=1` 390px 窄屏无横向溢出且菜单未出界，全程零控制台/页面错误。
  - 未覆盖项：未覆盖真实默认配置业务目录、正式 Windows BAT、真实前台桌面宿主拉起、系统原生选择器与 Tauri 打包产物验收（本机如需桌面端生效须重启服务或重打 `InvoiceHub.app`）。

### 2026-11-23 补齐项目归属全量人工调整、目录批量改项目与项目重命名（WS-03）

- 需求与起点：基于 `codex/workspace-p3@cddafd2`（`1.0.0-beta.1`）响应用户需求：不仅未归属发票，所有已识别发票（含发票备注自动识别的项目）都须支持人工手动调整项目归属，并且项目名称必须支持重命名（及合并到已有项目），同时不修改源发票且保持项目汇总、发票目录、侧栏项目树与成本分析 V2 口径一致。
- 采用方案：
  - **受保护数据模型扩展（向后兼容 v1）**：`src/invoice_hub/services/company_projects.py` 扩展 `项目归属.json` 可选字段 `aliases: {原名: 目标名}` 与单票 `unassigned: true`（显式移出至未归属、覆盖备注；空字符串继续清除人工条目并恢复备注）；`apply_rename` 在重命名/合并时同步重写人工归属并单跳折叠 `aliases`（满足 `keys ∩ values == ∅` 无环不变量），损坏/自映射/含环文件 409 拒绝覆盖。
  - **XML 备注提取与全消费者共享口径**：`projections/cost_analysis.py::analyze_xml_costs` 补齐 XML `<Remark>` 提取 `备注项目名称`；`company_views.py`、`cost_reports.py`、`company_projects.py` 统一调用 `project_fields(..., aliases)`；非监控成本/开具发票目录列表同步挂载 `project` / `project_source`。
  - **项目重命名预览确认接口**：新增 `POST /api/v1/companies/{company_id}/projects/rename/preview` 与 `POST /api/v1/companies/{company_id}/projects/rename`，在 `PRICING_LOCK -> _projects._lock` 锁序下重验 `revision` 与 `preview_hash`，支持预览人工/备注影响张数、是否与已有项目合并及同步更新 `服务成本归集.json`。
  - **前端工作台与侧栏交互**：新增 `frontend/src/components/ProjectRenameModal.vue` 供 `CompanyProjects.vue` 与 `WorkspaceSidebar.vue` 侧栏项目节点共用；`CompanyProjects.vue` 展示全量发票归属调整表（来源/项目/关键词筛选、直接改派备注发票、移出未归属、恢复备注）；`DirectoryInvoices.vue` 与 `DirectorySelectionBar.vue` 在成本/开具目录展示项目列并支持单行右键及勾选批量「调整项目…」。同步重建 `web/static/app/` 与更新架构五图、做账规则及 `PRODUCT_BACKLOG.md`。
- 验证范围与未覆盖项：
  - 已运行并通过：`tests/test_company_projects.py`（12 项，含 3 项新增回归）、`tests/test_company_views.py`、`tests/test_company_costs.py`、`tests/test_workspace_frontend.py`、`tests/test_development_documentation.py`（16 项）、Ruff、Python `compileall`、Vue `vue-tsc --noEmit`、`vitest run`（20 文件 164 项，含新增 `frontend/tests/project-management.spec.ts`）、`vite build`、`git diff --check`，并重新构建本机 `InvoiceHub.app`。
  - 未覆盖项：真实默认配置与业务资料实测、正式 Windows BAT、真实前台桌面/原生弹窗及远端新一轮 CI 均待独立验收。

### 2026-11-23 升级版本号至 1.0.0-beta.1 并重打本机 macOS 开发版 InvoiceHub.app

- 需求与起点：PR #32（`codex/workspace-p3@1d73f5c`，CI run `45174070913` / `45174070835` / `45174070850`）实现 9/9 项远端检查全绿（含 `Windows Python and release contracts`、`macOS ARM64 Python`、`Synthetic browser regressions (Linux)`、`Tauri host Rust (macos-15 / windows-latest)`、`Workspace frontend (Vue)`、`Python static analysis`、`DCO` 与 `macOS reference shell`）。按用户要求在全绿后将源码版本标注升级为 `1.0.0-beta.1`，并重新构建本机 macOS ARM64 开发版 `InvoiceHub.app` 供本机实机验收。
- 采用方案：
  - `src/invoice_hub/version.py` 升级为 `PRODUCT_VERSION = "1.0.0-beta.1"`、`PYTHON_PACKAGE_VERSION = "1.0.0b1"`、`UPDATE_CHANNEL = "beta"`（`UPDATE_FEED_URL` 随通道切至 `/updates/beta/latest.json`）；`src/invoice_hub/release/windows_alpha_metadata.py` 改为跟随 `UPDATE_CHANNEL` 与 `UPDATE_CHANNEL_PRE_RELEASE_KINDS` 校验单平台预发布 Feed。
  - 通过 `scripts/dev/tauri_version_sync.py --write` 同步 `package.json`、`src-tauri/Cargo.toml`、`src-tauri/tauri.conf.json`、`tauri.alpha.conf.json`、`tauri.public-preview.conf.json`、`tauri.windows-preview.conf.json`，并同步 `src-tauri/tauri.windows.conf.json`、`src-tauri/Cargo.lock`、`scripts/dev/` 与 `macos/InvoiceHubMac/script/` 发布/验包脚本及版本/更新契约测试。
  - 提交本地 DCO 检查点后使用 `scripts/dev/tauri_dev_app.py build` 重新构建 `src-tauri/target/release/bundle/macos/InvoiceHub.app`，核对 `Info.plist` 与内嵌 `invoicehub-desktop-host.json` 的版本标识为 `1.0.0-beta.1` 且指向当前干净提交。
- 验证范围与未覆盖项：
  - 已运行并通过：`tauri_version_sync.py --check`、版本/发布/更新/Tauri/API/文档契约 Python 测试套件、Ruff、`compileall`、Rust `cargo fmt --check` / `cargo clippy --offline --locked --all-targets -- -D warnings` / `cargo test --offline`、`git diff --check`，以及 `InvoiceHub.app` 构建与包内身份元数据核对。
  - 未覆盖项：本版本升级提交暂仅保留在本地 `codex/workspace-p3`（尚未推送至远端）；本机打包产物为开发版 `InvoiceHub.app`（非签名/公证 DMG 或正式发布包），真实业务金额、正式 Windows BAT、Windows 成品与最终用户前台/原生弹窗验收仍需独立执行。

### 2026-11-23 补齐新版工作区登记自动读数、合计详情查询、做账排版修复与文案优化

- 需求与起点：基于 `codex/workspace-p3` 响应用户四项新版界面改进需求：(1) 登记已有公司资料夹成功后自动后台读取三类发票目录数据（实时监控、弹窗通知与文件增删改仍以当前监控目录为基准，未监控源目录不写入导出文件）；(2) 发票列表底部操作条「合计详情」补齐与经典版/原型一致的开票项目、规格型号、单位、均价汇总及搜索/税率筛选弹窗；(3) 修复做账页左侧凭证列表多行时上下重叠与右侧分录表摘要列过窄；(4) 优化系统内偏技术术语、拗口的提示文案。
- 采用方案：
  - **非监控目录按需/自动只读读取**：`storage/generations.py::publish` 新增 `export_to_source: bool = True` 并在 `projection-manifest.json` 记录 `source_exported`，`recover_exports` 跳过 `source_exported=False` 代际以防向未监控源目录写文件；`projections/incremental.py::rebuild_generation` 透传该参数；新增独立领域服务 `src/invoice_hub/services/company_refresh.py::CompanyDataRefreshService` 与 `POST/GET /api/v1/companies/{company_id}/refresh-data` 路由，在目标 profile 写锁下后台增量构建三类发票目录并发布至本机 `runtime/targets/<id>/workspace/`，跳过当前活动 `watch_dir`、不切监控、不弹通知，完成后发 `company.data_refreshed` SSE 事件。前端在登记已有资料夹成功后自动触发读取，并在公司总览、目录页、成本分析 V2 提供“读取数据 / 更新数据”入口与自动重载。
  - **勾选合计详情宽弹窗**：`frontend/src/components/DirectorySelectionBar.vue` 消费现有 `POST /api/v1/invoices/selection-summary` 返回的完整 `cost_breakdown`，点击「合计详情 ›」打开宽 `WsModal`，展示三项总额卡、告警提示、关键字搜索与税率筛选（不改变顶部勾选总额）、按开票项目+明细税率拆组的数量/除税/价税合计及规格型号算术/加权均价表，以及可点击跳转原票预览的来源列表。
  - **做账页凭证列表与表格排版修复**：`frontend/src/prototype.css` 为 `.voucher-list button` 补齐 `flex: 0 0 auto; width: 100%; align-items: center;`，根除 `min-height: 0` 在 `max-height: 70dvh` 纵向 Flex 容器中被压缩导致的上下行重叠；移除 `.voucher-workbench .voucher__lines` 的 `display: block` 并为摘要/供应商列补足最小宽度。
  - **缺失子目录单独创建、同标签页返回按钮、原始凭证标签防截断与单据批量预览修复**：
    - `company_registry.py::subdir_plan/create_subdirs` 与 `/api/v1/companies/{id}/subdirs/plan|create` 支持可选 `keys` 单独预览与创建单个缺失空目录；`WorkspaceSidebar.vue` 缺失目录的 `…` / 右键菜单新增「创建此文件夹…」（`WsModal` 预览确认），`CompanyDirectories.vue` 缺失目录行新增「创建文件夹」按钮。
    - `CompanyPanel.vue` 维护同标签页内分区历史栈并在页头显示 `<` 返回按钮与当前分区面包屑，切换目录/账簿/项目/设置后可一键返回上一页。
    - `OverviewDocuments.vue` 与 `prototype.css` 为 `.overview-doc__meta .tag` 固定 `flex: 0 0 auto` 并将长项目名限制在 `.overview-doc__project` 内省略，修复「已对流水」胶囊被长项目名挤扁截断的问题。
    - `web/static/js/page-documents.js`（版本升级至 `20261123-batch-preview-1`）修复 `/documents?batch=inbound` 在 `selection_only=true` 模式下 `inbound_invoices` 为空导致点击批量行「预览」时下拉框选不中发票、无法显示预览与导出的缺陷；`App.vue` 跳转 `/documents?batch=inbound` 时同步选中监控公司确保嵌入帧立即可见。
  - **添加/设置公司纳税人身份生效月份日历化**：[MonthPicker.vue](frontend/src/components/MonthPicker.vue) 支持 `disabled`/`placeholder` 并将年月弹层 `Teleport` 至 `body`（`z-index: 85`）避免被弹窗裁切；[CompanyCreateForm.vue](frontend/src/components/CompanyCreateForm.vue) 与 [CompanySettings.vue](frontend/src/components/CompanySettings.vue) 的「生效月份」均改为使用 `MonthPicker` 日历面板选择年月，解决 macOS WKWebView 下原生 `<input type="month">` 退化为空白文本框的问题。
  - **平实文案优化**：调整 `FRESHNESS_MESSAGES`、`FRESHNESS_LABELS` 及工作区总览、账簿、目录、做账凭证、成本 V2、侧栏核对提示中“守恒校验 / 同票家族 / 勾稽关系 / 阻断 / 由生成命令写入”等偏术语表达为更直白的日常说明，同时保留票面口径与只读边界事实。
  - **同步 Tauri 浏览器启动契约测试**：修正 `tests/test_tauri_lifecycle_contract.py::test_tauri_startup_surface_uses_the_pinned_host_only_opener_and_empty_webview_capability`（此前 `e77d2fa` 切到 `backend_workspace_url()` 后导致 PR #32 在 macOS/Windows Python 均仅余该 1 项失败），改为同时校验 `main.rs` 调用 `backend_workspace_url()` 且 `lib.rs` 将其固定在 `backend_origin()` 下。
  - 同步重建并更新 `web/static/app/` 前端产物，以及 `FILE_MAP.md`、`INTERFACES_AND_FLOWS.md`、`DATA_AND_ALGORITHMS.md`、`BOOKKEEPING.md`、`WEB_UI.md`。
- 验证范围与未覆盖项：
  - 已运行并全部通过：本机 macOS 全量 `pytest`、`tests/test_tauri_lifecycle_contract.py`（17 项）、`tests/test_company_refresh.py`（新增）、`tests/test_development_documentation.py`（16 项）、Ruff、Python `compileall`、`node --test tests/*.test.cjs`（40 项）、Vue `vue-tsc --noEmit`、`vitest run`（19 文件 161 项，含新增 `selection-summary-and-refresh.spec.ts`）、`vite build`（三份产物逐字节复现）及 `git diff --check`。
  - 未覆盖项：未执行真实默认业务目录实测、正式 Windows BAT、真实桌面浏览器前台/原生选择器弹窗与 Tauri 打包成品验收，需在重启本机服务或重新打包后复核。

### 2026-11-23 将 Tauri 默认启动入口切换至新版工作区并收尾 Windows 单测

- 需求与现场：macOS 本机 Tauri 实机验收发现桌面窗口启动默认打开经典首页 `/`，且经典页顶栏无进入 `/workspace/` 的入口；同时 PR #32 `c5d84b0` 远端 CI 中 7/8 项全绿（含首次全过的 Linux Playwright 浏览器 E2E 双向各 3 轮与 macOS Python 全量），`Windows Python` 仅余 1 项 `test_company_receipts.py::test_changes_during_parse_are_not_cached`（1,517 passed / 1 failed）。
- 修改方案：
  - `src-tauri/src/lib.rs` 新增 `backend_workspace_url()`（`http://127.0.0.1:8766/workspace/`），保持 `backend_origin()`（`http://127.0.0.1:8766`）不变以守住 Host RPC/Origin/打印弹窗边界；`src-tauri/src/main.rs` 的桌面主窗口、browser 模式与托盘打开改用 `backend_workspace_url()`。
  - `web/templates/index.html` 顶栏在主导航右侧新增“新版工作区”（`href="/workspace/"`），不改动 7 项主导航契约，且在 `/workspace/` 嵌入 iframe 下随 `.topbar` 自动隐藏，实现新旧界面双向互切；同步 `docs/architecture/rules/TAURI_HOST.md`。
  - `tests/test_company_receipts.py::test_changes_during_parse_are_not_cached` 改为写入不同字节数 `b'newer'`，避免 Windows NTFS 同 15.6ms 时钟滴答内等长覆写导致 stat 签名未变。
- 验证范围与未覆盖项：本机通过 Rust `cargo fmt --check`、`cargo clippy --locked --all-targets -- -D warnings`、`cargo test --lib`、重新构建 macOS ARM64 `InvoiceHub.app` 并实机验证桌面启动直接进入 `/workspace/`，以及 Python 受影响前端/契约/回单/文档测试；远端 Windows Python 100% 全绿以本提交推送后的 PR #32 CI 结果为准，真实业务金额与 Windows 实机验收继续独立跟进。

### 2026-11-23 修复 PR #32 远端 CI 与 Windows 跨平台兼容性问题

- 需求与现场：PR #32（`codex/workspace-p3@0502541`）首轮 GitHub Actions（run `45119681382`）中 `DCO`、`ruff`、`macOS ARM64 Python`、`Tauri Rust (macos-15 / windows-latest)` 与 `macOS reference shell` 均已通过，同时暴露 2 个 Linux Node 作业配置问题及 138 项 Windows Python 兼容性失败（另有 3 条 Windows Rust clippy dead-code 警告已登记至 [ENG-01](docs/PRODUCT_BACKLOG.md#eng-01)）。
- 根因与修复：
  - **Linux Vue / 浏览器 CI（`.github/workflows/ci.yml`）**：`actions/setup-node@v5` 默认开启 `package-manager-cache: true`，在 `corepack enable` 执行前检测根 `pnpm-lock.yaml` 并调用 `pnpm` 失败；两处显式配置 `package-manager-cache: false`。
  - **Windows 只读句柄 `fsync` 失败（`EBADF`）**：`storage/files.py::atomic_write_json` 改为在 `os.replace` 前对可写临时文件 `flush + os.fsync`，移除 `company_setup.py`、`company_detection.py`、`company_export_jobs.py` 在替换后以 `"rb"` 打开并调用 `os.fsync` 的非 Windows 安全写法。
  - **Windows UTF-8 编码缺失（`charmap`）**：为 `storage/generations.py`、`company_detection.py`、`company_export_jobs.py`、`scripts/dev/build_agent_handoff.py`、`scripts/dev/build_ofd_preview.py` 及 26 个测试文件中的 `read_text/write_text/open` 显式补齐 `encoding="utf-8"`。
  - **Windows 文件身份与符号链接异常对齐**：`company_bank.py::list_files` 改用 `os.lstat(entry.path)`，解决 Windows `DirEntry.stat()` 返回 `(0, 0)` 而与 `company_bank_layouts.py` 的 `Path.lstat()` 不一致导致 `BANK_LAYOUT_STALE`；`company_files.py::read_relative` 在 Windows 符号链接/联结分支改抛 `OSError(errno.ELOOP, ...)` 以匹配 POSIX `O_NOFOLLOW` 的 HTTP 409 语义；`company_receipts.py` 预览任务同时绑定原文件 `source_sha256`，解决 Windows `st_ctime_ns` 为创建时间导致同大小同 mtime 替换未失效的问题；`tests/test_company_views.py::_tree` 统一 `.as_posix()`、`tests/test_company_ledger.py` 兼容 `\` 路径分隔符。
- 第二轮补修（PR #32 `af36d86` 远端复跑将 Windows 失败由 138 项降至 11 项，Linux Vue 已绿，Linux 浏览器 E2E 首轮全过但在第 2 轮捕获真实界面竞态）：
  - **Linux 浏览器 E2E / 服务成本刷新竞态**：`frontend/src/components/CostServiceCosts.vue` 在归类保存触发 `load()` 重载期间禁用“添加一行 / 预览 / 确认保存”，避免用户或 E2E 在重载返回前新增行后被回包清空卸载；已重新执行 `pnpm --dir frontend run build` 并同步提交 `web/static/app/` 产物。
  - **OFD 组件源码指纹恢复**：恢复 `scripts/dev/build_ofd_preview.py` 至原锁版本（仅读取纯 ASCII 锁文件），修复 macOS 与 Windows 的 `COMPONENT_SOURCE_FINGERPRINT` 校验。
  - **剩余 Windows 兼容项**：`storage/source_adapters/__init__.py::Mounted.entries` 改用 `os.lstat(item.path)` 对齐 `signature()` 的 `(st_dev, st_ino)`；`scripts/dev/build_agent_handoff.py` 显式追踪 POSIX 可执行成员集合，不依赖 Windows 文件系统 `st_mode & 0o111`；`tests/test_workspace_prototype_ledger.py` 为 `subprocess.run(..., text=True)` 补 `encoding="utf-8"`；`tests/test_temporary_recognition.py` 改按原字节 UTF-8 核对 `get_text` 保留原始行尾的 XML 预览。
- 验证范围与未覆盖项：本机 macOS 通过 `ruff`、`compileall`、受影响后端测试、`pnpm --dir frontend run typecheck / test / build`、`test_workspace_frontend.py`、`test_frontend_contract.py` 及 `git diff --check`；远端全量结果以 PR #32 新一轮 GitHub Actions 运行为准；真实默认配置与双平台成品验收继续独立推进。

### 2026-11-23 确认 v1.0.0 发布路线并推进远端 CI 与 Draft PR

- 需求与决策：用户认可 `v1.0.0` 与 `v1.1+` 范围切分（`WS-01`–`08`/`WS-10`/`COST-01`–`06`/`OCR-01`/`ENG-09`/`ENG-01/02/04`/`FEEDBACK-01` 及 `BK-01`/`BANK-01`/`COST-07` 有限收口归入 `v1.0.0`；`AGENT-01`–`04`、完整税务政策引擎 D0–D5、服务器跨公司模块深度消费与装饰皮肤恢复挪至 `v1.1+`/`v1.2+`），并明确双平台验收当前以 macOS 为主、Windows 侧从 GitHub 克隆分支后再验。
- 执行过程：先以 DCO 显式清单将 `BUG-06` 修复与既有规划文档固定为本地提交 `8b7d4a1`，随后同步更新 [未来工作总览](docs/PRODUCT_BACKLOG.md) 目标版本与两阶段节奏及 [分支状态](docs/BRANCH_STATUS.md)；对 `main..HEAD` 全量差异执行禁止文件、本机路径、敏感凭据与 DCO 核查（0 违规、0 漏签），准备推送 `codex/workspace-p3` 并创建 Draft PR 以运行远端 GitHub Actions CI 并供 Windows 端克隆验证。
- 验证范围与未覆盖项：纯文档规划提交已通过文档契约与本地链接测试及 `git diff --check`；未合入 `main`、未打正式发行包，真实默认配置、macOS/Windows 成品与远端 CI 结果以 PR 实跑及后续验收记录为准。

### 2026-11-23 修正服务品目被凭证草稿计入库存

- 按引用开发规划执行首项 BUG-06，接续 `codex/workspace-p3@95bad31412102c69c26a3c9fe1db71cdfb1b4753` 的成本 V2 开发线；开工本地 `main/origin/main` 为 `ee0f2c2`，保留五份既有规划文档修改、无关未跟踪 HTML 和 ignored 配置/运行资料。未新建 worktree；随后按用户授权将本轮修复与既有规划文档以 DCO 显式清单本地提交，未推送、合并或发布。
- 新增 `bank/voucher_items.py`，草稿在按品类合并前先解析同公司品目标准名与类型。同票 200 元盘螺+30 元检测服务只计库存 200，服务金额及原名称/发票来源单列；有精确已确认可用非库存科目则带入，缺少、不可用、矛盾或库存映射冲突则留空编码和待补，仍保持借贷各 230。页面审核和 CLI/页面整月导出复用原 validator，不以提示代替阻断。
- 工作区生成与改记入期将完整代际明细和映射来源状态成对交给共用入口；CLI 根 CSV 使用相邻状态文件。严格拒绝坏/未来状态及重复 JSON 键，生成前后核对状态原字节与目录身份，变化不覆盖原审核表。服务数量不进入历史期初更正、销项出库或成本结转，也不误报待匹配库存品名；零税额票不再生成被正金额校验拒绝的零税额行，库存隐式匹配复用已有编码。
- 新增 24 项合成专项回归，覆盖两入口、确认/缺科目、别名与冲突、旧货物档案、混合销项/历史数量、审核/整月导出、完整代际/来源切换/改记入期及生成期间变化。最终 macOS/Python 3.14.7 全量 pytest 1512 项通过、16 项跳过、24 项子测试通过（149.32 秒）。首轮有 4 项子进程测试因源码未安装、缺少子进程 `PYTHONPATH` 失败；依据 daemon 日志补明确源码路径后全量通过，没有放宽断言或修改相关产品逻辑。保留 5 条既有 Swig 弃用警告。
- Ruff、Python 编译与差异格式检查通过；同步实现状态、迁移/待办、功能规则和架构五图。现有工作区 P3 与成本 V2 合成浏览器在本机已安装 Chrome 各通过一次，成本归档 PUT 仍仅一次、冻结下载与原 Vue 资源哈希一致；本轮未修改前端资源，不重建 Vue 或宣称 GitHub Linux/配套 Chromium 已运行。沙箱内 Chrome 启动被系统拒绝后，使用允许的隔离执行完成浏览器回归。
- 专项隔离浏览器实际核对库存 200、服务 30、借贷各 230；缺科目尝试审核返回预期 422 且导出禁用，确认非库存科目后审核成功，重新进入仍为通过。浅/深色、390px 与 no_skin 已核对，并检查相关截图；除预期拒绝外无页面异常。文档契约 16 项通过；13 份变更 Markdown 的 575 处本地链接和 168 处锚点通过，补回检查发现的既有 WS-10 短锚点。新增 diff/文件的本机路径及凭据模式扫描无命中。本轮浏览器/测试进程已收束，临时合成目录、截图、下载、编译缓存与测试目录已清理，私人任务摘要只保存在仓库外。
- 真实默认配置的完整业务金额、正式 Windows BAT、正式入口浏览器前台、系统原生选择器、Tauri 下载、网络盘、双平台打包产物与真实账套未在本轮验收；三轮实测仍为 15/37。更广的服务收入/费用科目引擎和服务成本入账继续按 COST-07 的实际样本评估。

### 2026-11-22 安排凭证草稿修复和成本交付验收

- 从 `codex/workspace-p3@95bad31` 核对两次本地提交。父提交 `af987d8` 固定成本 V2，当前提交增加浏览器 CI 和经典首页修复。后续业务和双平台验收统一从当前提交开始。按完整提交号查询 GitHub Actions 尚无对应的 CI 运行。[分支现场](docs/BRANCH_STATUS.md)
- 用同一张合成进项票对照进销存、工作区凭证生成服务和 CLI。200 元盘螺和 30 元已标为服务的检测费，进销存购入为 200 元，两个入口生成的草稿均借记库存 230 元。登记 BUG-06 为首项代码修复，列明有科目和缺科目两种验收情形。更广的服务科目映射保留在 COST-07。[缺陷复现](docs/PRODUCT_BACKLOG.md#bug-06)
- 业务验收优先复核两类纳税人的 BUG-01，同步安排正式入口、双平台成品与远端 Linux 回归。后续银行版式、其他记账软件模板及缓存容量分别按样本和设备条件推进。三轮实测仍勾选 15/37 项。[近期开发计划](docs/PRODUCT_BACKLOG.md#next-delivery) · [交付验收清单](docs/MIGRATION_GAP_CHECKLIST.md#cost-v2-delivery)
- 本次变更限于规划文档，金额复现使用临时合成副本，结束后已清理。16 项文档契约测试、变更行的本地链接与锚点、三轮清单计数和 `git diff --check` 均通过。真实默认配置下的业务金额、真实账套、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Tauri 下载及打包产物仍待验收。

### 2026-11-22 接入浏览器持续集成并修正首页局部刷新

- 按关联规划推进 ENG-05，接续同目录的成本 V2 候选；新增顺序回归入口、共用浏览器/夹具生命周期与 trace/失败诊断，锁定 Playwright 1.65.1 和独立 Linux x64 后端二进制哈希。CI 重建前端资源、三组各独立运行三次，再验证指定重绘故障，合成诊断保留 7 天；不扩大产品发行平台或生产 API。
- 首页全选/清空不再重建 tbody；读取按目标、位置键与源路径复用内容未变的行，阶段变化重建可操作状态。筛选/排序/家族合计仍消费原 API，SSE 保留焦点、内部滚动与目录草稿，迟到响应继续丢弃；翻页修正实际表格容器定位。截图复核另发现目录有草稿时会残留已恢复的失败提示，补状态追踪和明确恢复/草稿说明。最终首页资源版本为 `20261122-invoice-row-refresh-2`，同步预览、打印及前端契约、功能规则、架构五图、状态/迁移与后续计划。
- 本机 Playwright 1.65.1 配已安装 Chrome 156.0.8078.82，最终 P3/成本/首页各三次连续通过；首页覆盖 104 条记录/103 张家族、跨页勾选、三项合计、SSE、一次 503 后恢复、迟到筛选与空态，以及默认/深色/经典两款皮肤/390px/no_skin。恢复整表重绘的开发故障被指定 `CLASSIC_LOCAL_REFRESH_LOST` 断言检出，不能以其它失败冒充通过；截图目视核对了窄屏和恢复后的深色提示。
- 最终 macOS/Python 3.14.7 全量 pytest 1488 项通过、16 项跳过、24 项子测试通过（149.01 秒）；Vue 类型检查、154 项组件、生产构建、Node 39 项、Ruff、Python 编译、工作流 YAML、本地 64 份 Markdown 的 695 处链接及差异检查通过。首轮全量仅发现预览/打印两处旧版本断言，按最终资源版本同步后重新全量通过，未放宽业务断言。保留 5 条既有 Swig 弃用、字体运行时解析和包体提示。
- 成本候选另从干净源码导出冻结安装并重建，三份 Vue 资源与提交逐字节一致，在该导出重跑 P3 与成本归档/查询/下载亦通过。依赖镜像慢速/超时后沿用缓存和官方元数据补齐精确锁，frozen 安装通过，未升级既有依赖；合成资料根由父进程收束清理，输出在任务收尾清理。
- 当前默认源码服务只读核对：health 的配置/runtime 归属本 checkout，实际首页与 no_skin 均提供最终脚本版本，JS SHA-256 为 `ec91cb98578f457cb1ae33a542bc184670e7890e8ff49004e9fe1d7f88014349`，DOM 已加载局部刷新函数、控制台无错误；当前皮肤为无皮肤，未保存设置或执行真实业务写入。此项不算真实金额或正式启动验收。
- GitHub Linux 作业及配套 Chromium 尚未运行，本机 Docker daemon 不可用；不推送/合并/发布。真实默认业务金额、正式 Windows BAT、正式入口前台拉起、系统原生选择器、Tauri 附件下载、网络盘及打包产物继续单独待验，服务科目归集仍按 COST-07 评估。

### 2026-11-22 固定成本分析第二版本地候选

- 按关联规划先固定已有成本 V2 成果；任务 `eng05-browser-regression-20261122` 从 `codex/workspace-p3@5835f5e` 开工，核对本地与远端 main 均为 `ee0f2c2`。既有 31 个修改文件、18 个未跟踪项按明确清单收齐，排除无关 `pelican-bicycle.html`，不纳入 ignored 配置、运行态或发布产物。
- 同一工作区复跑 Python 全量：1486 项通过、16 项跳过、24 项子测试通过；Vue 类型检查、154 项组件测试、生产构建、Node 38 项、Ruff、Python 编译与差异格式检查通过，保留既有 Swig 弃用、字体解析和包体提示。重建 JS SHA-256 仍为 `5dd20d5c24cdb2ae53eac725a933ae15d1485f7404c5515f8f2cf5e0488788f8`。
- 隔离合成 Chrome 重跑工作区 P3 与成本 V2：银行映射、凭证结构保存、手工税费，以及服务分析、报价归档响应丢失后原 ID 查询和冻结金额 XLSX 下载通过；归档 PUT 仅一次，预期 503 之外无控制台错误。仅保存本地候选，不推送、合并或打包；真实默认业务金额、Windows 正式 BAT、正式入口前台、原生选择器、Tauri 下载及成品继续待验。

### 2026-11-22 更新成本分析第二版进度与交付计划

- 从 `codex/workspace-p3@5835f5e` 核对已完成的开发记录、工作区源码、浏览器回归脚本与构建资源。服务项目毛利、统一加价率提示、疑似同物异名提示，以及归档响应丢失后查询原记录并下载报价表，均已有实现和合成回归，已移出近期开发队列。当前前端 JS 的 SHA-256 与 11 月 21 日回归记录一致。
- 更新[分支现场](docs/BRANCH_STATUS.md)和[实现状态](IMPLEMENTATION_STATUS.md)。[交付计划](docs/PRODUCT_BACKLOG.md#next-delivery)先固定本地候选，再并行业务金额与双平台验收。明确新旧成本口径的逐行核对方式，保留合同价偏差百分比的待核对项。后续工程优先补 ENG-05 的 Linux CI 和经典首页，成本业务先按 COST-07 评估服务科目归集。
- 按[三轮清单](docs/MIGRATION_GAP_CHECKLIST.md#ws-real-acceptance)重新计数，已勾选 15/37 项。本轮只更新文档与排期，16 项文档契约测试通过，另核对了变更行的本地链接和锚点、前端资源哈希、勾选数及 `git diff --check`。业务、默认配置、正式入口、原生交互和成品沿用上轮的覆盖说明。

### 2026-11-21 补齐成本分析第二版开发范围

- 需求与现场：用户引用“规划后续开发方向”要求完成成本分析 V2；已读取关联聊天并按其第1/3/4项补齐可重复回归、服务项目毛利和价格/品名提示。起点为 `codex/workspace-p3@5835f5e`（本机 main/origin/main 为 `ee0f2c2`），保留此前23个修改文件、12个未跟踪文件及 ignored 配置/运行态，无关 `pelican-bicycle.html` 保持原样；未提交、推送、合并或发布。
- 服务归类与毛利：品目表新增显式服务类型，V2读取双方品名并提供预览确认的类型弹窗；别名组沿最终标准名一致归类，保存复用原品目表/兼容工作簿链与捕获profile的monitor同步锁，保留别名、品目税率和旧已开快照。仅服务销项按同公司、同月、同非空项目匹配人工成本，列收入/成本/毛利/来源；明确零成本可算，缺成本、归属/金额未知、无收入或销项过期不补零，不混入货物利润或声称净利润。
- 价格证据：期间内同票同品目/规格/单位归成一个实际样本，以原月销售成本计算加价率，至少3个、到0.01个百分点全部一致才提示，未知/排除样本阻止全期间结论。相同规范规格与单位且名称相近或库存品类相同的品名列人工候选，保留E/大小写与来源，最多50组/20000次比较；查询不自动改价、改名或合并。
- 恢复与相邻保护：新期间读取失败清除旧结果，映射变化/卸载丢弃迟到响应。服务成本/库存对照遇共享来源更新作废旧预览、保留已编辑草稿，未知写入只查询；归类严格拒坏状态/未来版本与矛盾别名类型。经典成本页补服务选项并升级资源版本，Vue资源由构建生成；同步状态、设计、迁移/待办、功能规则与架构五图。
- 自动化：新增15项后端合成回归及7项Vue回归；首轮全量发现旧测试仍将新增的service类型当非法输入，改用unknown继续验证拒绝坏类型。最终macOS隔离配置全量pytest 1486通过、16跳过、24子测试通过（142.28秒），保留5条既有PyMuPDF/Swig弃用警告；Vue类型检查、18文件154项组件测试、38项旧页面Node交互、全仓Ruff、Python编译、文档契约/本地链接及diff检查通过。前端重复构建三份资源逐字节一致，JS的SHA-256为 `5dd20d5c24cdb2ae53eac725a933ae15d1485f7404c5515f8f2cf5e0488788f8`；保留既有字体运行时解析与大于500kB包体提示（当前513.62kB）。
- 浏览器：`scripts/dev/cost_v2_e2e.mjs` + 合成夹具使用真实Vue/FastAPI/Chromium，走服务归类→人工成本→项目毛利/价格证据→报价→归档→原记录查询→XLSX下载；一次已落盘响应丢失注入503后归档PUT仅1次，服务成本/归类PUT各1次。下载文本金额与冻结记录一致，最终实际资源哈希与上述构建相同，浅/深/390px/no_skin无整页横向溢出，截图已目视核对。首次受沙箱限制的Chrome启动失败，修正夹具调用后在允许的隔离执行中通过；除预期503之外控制台无错误。浏览器及测试合成目录/下载/截图均在收尾清理。
- 后续衔接：服务分析记录不等于已入账成本，服务品目与凭证科目/库存的进一步衔接登记COST-07，明确证据、验收标准与影响范围；本轮不从毛利记录生成账套分录。
- 当前源码运行态：收尾发现默认localhost仍为旧后端、未加载新增接口；以UTF-8核对进程启动根、源码入口和本机配置后，通过标准 `keep_monitor` 关闭接口退出，再用 `invoice_hub.api.main` 同配置启动当前源码。watch_dir/target未变，monitor原本未运行且前后一致；新接口已加载，默认端口HTML/JS与上述构建哈希一致。只读Chromium核对当前无皮肤与no_skin入口DOM，控制台无错误；这是源码默认配置启停/资源检查，不是业务金额或正式前台启动验收。
- 未覆盖：真实默认配置下的完整业务金额核验、正式Windows BAT、正式启动入口前台拉起、系统原生选择器、Tauri附件下载、Windows/网络盘竞态及打包产物均未在本轮验收；不操作真实迁移/审批/账套/申报。自动行情、特殊计税与政策核验继续独立排期，真实/双平台交付验收保持开放。

### 2026-11-21 安排近期开发顺序

- 核对 `codex/workspace-p3@5835f5e` 上的既有工作区修改、成本 V2 实现和三轮验收记录，在[未来工作总览](docs/PRODUCT_BACKLOG.md)登记候选回归、金额与平台复验、服务项目毛利、价格与品名提示的先后顺序及完成依据。目标版本待定。
- 本次只调整规划，核对范围为文档契约、本地链接和差异格式。业务与平台实测列入后续验收。

### 2026-11-21 成本 V2 接手复核与未知保存恢复

- 需求与现场：用户确认接手成本分析 V2、原 Claude Code 及后台写入已停止；按交接任务认领 `codex/workspace-p3@5835f5e` 的既有 P1 改动，保留全部既有文件与无关原型，不扩展 P2、不提交或推送。
- 复核修正：归档 PUT 返回网络/5xx 未知结果时，阻止创建新预览和新记录 ID；原记录查询提示独立于试算错误，重新试算不会将其清除，查询失败继续锁定。规则与旧加价率迁移在成功读回同一版本后也能解除未知状态；缺失快照或失败读取不解锁，须重新预览和明确确认，不自动重放。新快照、切换公司或卸载后丢弃相关迟到预览/保存响应，避免旧确认恢复或旧公司数据回流。
- 自动化：接手时成本定价、公司成本、扩展、库存、v1 汇总、API 及前端/文档契约共 405 项通过；修正后 Vue 17 文件 147 项、类型检查与构建通过，新增相同版本读回解锁、归档待确认时重新试算、迟到确认作废等相邻回归。重建后的前端/文档契约 53 项、产物 JS 语法及 `git diff --check` 通过；文档契约含本地链接检查。保留既有字体运行时解析与大于 500 kB 的构建提示。
- 浏览器：隔离合成 FastAPI + Chrome 前台验证保存成功但响应丢失的归档查询、保存未落盘的迁移/规则同版本读回解锁、显式重新迁移及归档 XLSX 下载。服务计数为归档 PUT 1 次、迁移 PUT 2 次（失败一次后明确重新预览确认）、规则 PUT 1 次，无自动重放；控制台仅有三次故障注入的预期 HTTP 503。核对浅色 390px、桌面深色与 `no_skin` 恢复入口及当前构建资源。
- 范围：本轮复核既有 P1，未全量重跑产品后端；真实默认配置/业务资料、正式 Windows BAT、正式启动入口前台拉起、系统原生选择器、Tauri 附件下载与打包产物未验。P2 服务毛利及统一加价率/同物异名提示仍见 COST-05/06。

### 2026-11-21 成本 V2 前端工作台与旧加价率迁移

- 需求与起点：用户以 Codex 线程链接要求“完成成本分析 v2”，确认原执行者已停止、范围为 P1（前端 + 工作簿迁移）。链接未在交接工具登记，改为按 `InvoiceHub-public/cost-v2-gaps-20261121` 任务认领；起点 `codex/workspace-p3@d1d962a` 有未提交的成本 V2 后端及并行功能改动。成本后端与完整代际/服务器来源/反馈/工资改动共享文件、无法干净拆分，经用户选择整体提交为检查点 `5835f5e`（全量 pytest 先行通过，未纳入无关 `pelican-bicycle.html`）。
- 后端：规则文件 `pricing` 增加可选 `legacy_migrated`，列入的品目不再读时套用 v1 人工加价率；rules/preview 与 PUT 接受该完整列表，省略即沿用已保存值并纳入 preview_hash。GET V2 增加每品目 `legacy_state`、`v1_reference` 及顶层 `legacy_migrated`、`customers`。新增只读 `GET …/v2/migration`（v1 历史均价口径价、V2 当前规则价、差额、不沿用时的 V2 价）与 `POST …/v2/migration/export`（绑定 revision 的内存 XLSX：V2 开票参考/新旧对照/版本与口径），不改 v1 工作簿、已开快照或 `watch_dir` 三件套。
- 前端：工作区“成本分析”模块选中公司默认显示 V2 工作台，含定价助手（客户/品目/数量/税率/阶梯金额/市场依据→报价、代入式、分位合计、归档预览确认与未知结果查询）、品目与迁移、定价规则编辑试算、毛利分析、价格监控、库存对照与账面核对、报价记录与导出、服务成本录入；经典 v1 页面保留为单独标签，仍要求活动监控目录。所有写入预览后以 preview_hash 确认，409 先重读再提示且不重放，网络/5xx 锁定直到成功读回，换公司丢弃迟到响应；未知成本/毛利显示待核对，不补零。重建 `web/static/app` 资源（`app.js` 约 501 kB，越过 Vite 500 kB 提示线，保持单文件未拆包）。
- 过程修正：4 个并行子代理因 API 额度错误终止且未留文件，组件改由主线程编写；首轮组件测试发现服务成本/库存对照 409 后重读会清掉冲突原因，改为先重读再显示；经典成本 iframe 曾被改为懒加载导致既有缓存用例失败，已恢复常驻挂载、仅改可见条件。
- 验证：新增后端合成回归 6 项（迁移对照无写盘、转换/不沿用/后续编辑保留/显式清空复活、非法清单 422、导出版本绑定与内存附件）；`test_company_costs` 38 项及成本/库存/凭证/API 相邻测试通过。前端新增 16 项组件测试，vitest 17 个文件 142 项、`vue-tsc`、`vite build`、`test_workspace_frontend`/`test_frontend_contract` 通过。最终 macOS 全量 pytest 1470 项通过、16 项跳过、24 项子测试通过（133.23 秒，5 条既有 PyMuPDF/Swig 弃用警告）；全仓 Ruff、`compileall src tests`、`git diff --check` 通过。
- 浏览器验收（同日后续）：用户放开专用 Chrome 后，经用户同意结束占用 CDP 端口的旧自动化 Chrome（旧配置，辅助工具判为未知服务），由辅助工具重新拉起并以其端点经 Playwright `connectOverCDP` 连接；合成公司（两种钢材、一条 v1 12% 旧加价率）冒烟服务上从侧栏选公司，走通报价→归档→记录导出、品目总览、新旧对照与导出、旧加价率迁移确认、新增规则试算保存、毛利分析、价格监控、库存对照、服务成本录入及在分析中单列、经典 v1 标签，控制台无错误；核对磁盘：规则文件含迁移规则与 `legacy_migrated`，v1 状态 12% 保留，服务成本与归档写入各自文件，两份 xlsx 表名与数值（差额 +18.67、合计 632.81）正确。
- 验收发现并修复：报价/品目/对照中的结存加权单价原样显示 50 位小数，新增仅显示用的 `unitCost`（字符串 BigInt 四舍五入到 4 位，悬停看完整值，不回传）；快照顶部警告为 `{code,message}` 对象却按字符串渲染成 JSON，改为显示 message。补 1 项前端测试（共 143 项）并重新构建。另发现辅助工具自己拉起的自动化 Chrome 在第二次调用时不满足其归属检查（缺 `--incognito`、语言不同），复用其首次给出的端点完成验收，未修改受保护的启动器配置。
- 未覆盖：Tauri 宿主的附件下载、真实默认配置、正式 Windows BAT、系统原生选择器、打包产物与真实业务数据均未验；浏览器验收仅为合成数据。服务收入匹配/服务毛利、统一加价率与疑似同物异名提示、自动行情仍待做（COST-05/06）。临时冒烟目录已删除。

### 2026-11-21 成本 V2 库存核对、报价留痕与分析后端

- 需求与起点：用户要求继续补后端缺口，并明确服务成本由用户按月份/项目录入、保留来源说明；沿已授权的 `codex/workspace-p3@d1d962a` 接续，保留既有修改，不操作真实业务、不提交/推送/合并或打包。
- 库存：新增本公司根目录的显式库存科目对照、期初和完整读回月份声明，绑定账套科目表；V2、进销存比较与凭证草稿共用解析及原月末加权核心。连续月份缺失、非月末、单位冲突、重叠库存分录、未映射或来源不完整均待核对，不补零；差额为账面期末减发票滚动期末，确认期初不会被历史发票自动纠正。
- 留痕与导出：报价/规则试算可独立预览、确认归档，冻结原成本、规则、市场证据及计算结果；同 ID 同内容重放返回原回执，来源移走仍可查询原记录。显式确认对应内容 hash 后从归档导出 XLSX，含前后试算与市场依据，金额按十进制文本保留并防公式注入；不写旧工作簿或投影。
- 分析与服务：增加实际货物收入/成本/毛利的品类单位、客户、项目、月份汇总、来源追溯、采购价格波动/低毛利/票面税率设置差异提示；客户/项目成本采用累计分位舍入保持品类月成本守恒。当前月只到今天并标暂计，未知成本不补零。服务成本有独立预览/确认保存、修订核对和来源说明，按月/项目单列，不从工资推算或分摊到货物毛利。
- 兼容与边界：旧 v1 价格、已开快照、工作簿及 monitor 代际不变；新增状态有界、绑定公司、原子替换并读回，同进程串行，不承诺外部编辑器/CLI 跨进程事务。前端/既有工作簿显式迁移、服务收入与人工成本匹配、统一加价率/疑似同物异名提示、自动行情及政策核验仍见 COST-04/05/06。
- 验证：本轮新增 32 项合成回归，成本/库存/公司比较/凭证相邻测试共 97 项通过；macOS 隔离配置全量 1464 项通过、16 项跳过、24 项子测试通过，143.16 秒，保留 5 条既有 PyMuPDF/Swig 弃用警告。全仓 Ruff、282 个 Python 文件内存编译、16 项文档契约/本地链接与 git diff --check 通过；全量临时目录自动清理，聚焦测试临时目录收尾清理。未验真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Windows/网络盘竞态、Tauri/打包成品或真实账套；自动化不代替最终用户验收。

### 2026-11-20 成本分析 V2 第二批定价规则后端

- 需求与起点：用户引用上一成本 V2 任务要求继续完善后端；核对首批已完成记录，在已获授权的 `codex/workspace-p3@d1d962a` 接续，保留既有代码、文档、前端与运行态，不提交、推送、合并、打包或操作真实资料。
- 方案与结果：沿用公司 V2 quote/preview/save 增加阶梯与人工市场价参照。阶梯按单行数量或显式除税基准金额、整行应用命中档；市场参照带来源/有效期，成本未知或证据缺失/过期不猜价。含税市场价保留金额权威，取整后复核最低加价底线；原最低毛利保持只提示。六类规则共用优先级、期间和 Decimal 核心。
- 保存与兼容：报价上下文完整参与 preview_hash，改数量、基准金额或市场来源后拒绝沿用确认；规则文件只保存规则，不保存市场依据。旧四类规范化与存储保持兼容，不改 v1、工作簿、已开快照、库存算法或投影代际；补充设计、状态、迁移、待办、成本规则及架构五图。
- 验证：新增 55 项合成回归，覆盖阶梯边界、坏输入、市场有效期/底线与含税守恒、只读、试算篡改、保存读回及旧保护；两轮阶段定价/公司 HTTP 检查 120 / 129 项通过，再补外层继承、零成本和优先级边界后运行完整回归。最终 macOS 隔离临时配置全量 pytest 1,432 项通过、16 项跳过、24 项子测试通过，保留 5 条既有 PyMuPDF/Swig 弃用警告；全仓 Ruff、275 个 Python 文件内存编译、文档契约/本地链接与 git diff --check 通过，仓库运行态保护未报变化。测试临时目录自动清理。
- 未覆盖：真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Windows/网络盘竞态、Tauri/打包与真实业务；前端/工作簿接入、完整分析/价格监控、行情联网、报价导出、依据归档与科目映射仍待做，自动化不代替最终用户验收。

### 2026-11-19 成本分析 V2 首批后端

- 需求与起点：用户要求开发成本分析 V2 后端，并明确在已有改动的 `codex/workspace-p3@d1d962a` 接续；反馈任务运行期间暂停，用户要求继续且反馈执行者已释放目录后开始。保留全部前置工作，不提交、推送、合并、打包或操作真实资料。
- 成本底座：新增公司级只读 V2 服务，读取两侧同代际投影并按计划日期截断，复用 `company_inventory → cost_of_sales` 的品类 + 单位月末一次加权；规格不分摊期初/成本。返回结存单价、最近进价、历史均价，来源过期/不完整、历史卖超、零结存/相关排除不偷换历史均价；进项税按逐票历史身份计入，科目未对照明确提示。
- 规则与兼容：新增无 I/O 的 Decimal 首批引擎，提供加价率、目标毛利、固定加价、固定含税/除税价、尾数/取整、最低毛利提示、规则/单行税率、客户/品目层级和生效期冲突校验。旧人工行只读迁移，自动生成默认率不遮蔽客户规则；实际销项与手填快照分开且不相加，不改 v1 API、页面、工作簿或已开快照。
- 接口与保存：GET V2、POST quote、POST rules/preview、PUT rules 独立于旧接口，有界同源 JSON、严格字段/数值/重复键校验。规则另存本公司成本目录，确认时重新试算、核对内容 hash/修订号/目录与投影来源，进程内串行原子替换并读回；坏文件、跨公司、来源变化、目录替换或重放拒绝，无变化不写。外部编辑器/CLI 不属于跨进程事务。
- 文档：同步设计当前实现、状态、迁移/待办、成本规则和架构入口/五张地图。V2 前端/工作簿迁移、完整毛利分析/监控、报价导出、科目映射替换、阶梯/市场价仍是后续范围。
- 验证与修正：首批 78 项新增合成回归与 281 项成本/公司/库存/API/完整代际相邻回归通过。首轮全量暴露旧投影夹具与启动扫描的竞态、现有状态文档中的提交标识和完整路由登记缺失，分别隔离两项投影读取夹具的启动扫描、将精确起点留在日志、补全路由地图；随后成本/API/文档 172 项通过。最终 macOS 隔离配置全量 pytest 1,377 项通过、16 项跳过、24 项子测试通过，保留 5 条既有 PyMuPDF/Swig 弃用警告；全仓 Ruff、274 个 Python 文件编译、文档契约/本地链接与 git diff --check 通过。最终全量临时目录自动清理。未验真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Windows/网络盘真实竞态、Tauri/打包成品或真实账套；自动化不能代替最终用户验收。

### 2026-11-19 应用内建议与反馈、关于技术详情折叠

- 需求与起点：用户要求在关于页更新日志右侧加建议 / Issue 入口，并隐藏截图蓝框的四项构建身份；确认软件内填写 → 独立中转 → GitHub Issue，沿 `codex/workspace-p3@d1d962a` 保留全部既有改动。本轮明确只做代码与本机验收，不部署、不创建真实 Issue。
- 方案：新增 Vue `FeedbackDialog` 复用 WsModal，类型 / 标题 / 描述、可选环境白名单、预览与显式公开确认；设置 iframe 经已有来源 / token 导航桥打开外壳对话框，保留设置草稿，独立经典页有恢复参数入口。包类型 / Package ID / 核心 Build ID / API 契约收进默认折叠“技术详情”，平台架构继续显示；设置和桥接脚本升级资源版本，前端产物由 Vite 生成。
- 提交链：独立本机反馈服务/API 有界同源 JSON、先落持久意图再单次 HTTPS，重复 / 并发 / 断线 / 重启只查原回执；GitHub 写令牌只在独立中转，固定仓库、无重定向、匿名 @ 提及隔离、有界并发和持久限流。两端回执库不存标题/正文/发票/日志；默认不附环境，不提供附件 / 联系方式输入。无中转地址时明确未开通，仍能填写和复制。
- 自动化：新增反馈协议/隐私/幂等/限流与 Vue 回归。完整 pytest 1,298 通过、16 跳过、24 子测试通过；随后新增晚到成功回执样例的聚焦反馈/文档/页面/工作区 76 项通过；Vue 类型检查、126 项 Vitest、生产构建、Ruff 与 Node 38 项通过。保留既有 PyMuPDF/Swig 弃用与 display.woff 构建提示。浏览器与最终检查结果在本节收尾补记。
- 边界：未验真实默认配置、正式 Windows BAT、正式入口浏览器前台拉起、系统原生选择器、Tauri/打包成品、真实 GitHub / 大陆公网；未配置真实地址或令牌，不部署、暂存、提交、推送、合并或打包。上线、令牌轮换、滥用与保留治理登记 [FEEDBACK-01](docs/PRODUCT_BACKLOG.md#feedback-01)，架构、状态与规则同步。

### 2026-11-19 WS-01—05 开发缺口补齐

- 需求与起点：按用户要求逐项核对 WS-01—05，在 `codex/workspace-p3@d1d962a` 及既有未提交成果上补齐 WS-02 同类候选目录选择、WS-05 工资表与工资计提；WS-01/03/04 已有核心范围继续保留真实/平台验收状态。未扩大到隔离皮肤重新启用、非监控原票操作、OCR 或完整税务政策引擎。
- WS-02：检测表列出无跨类歧义的安全直接子目录，多候选须明确选择；可显式选标准名并另行补建。部分选择过滤空值，根变更丢弃旧响应；所选映射与所有候选身份绑定计划，同名替换须重新检测，仍只创建明确勾选的空目录。
- WS-05：新增有界 `.xlsx/.xlsm` 仅值工资读取与默认脱敏预览。明确表头/表内年月、应发/扣款/实发逐行及总计校验，未知扣款不补零、公式不执行，同月多文件由用户选择。确认重新解析原表、补明确费用科目，写 `申报数据.json.工资明细`；与社保及草稿共锁/CAS，坏状态保留、来源变化失效、未来月拒绝，未知保存只查询。关闭完整显示后立即隐藏原值，失败也不残留。
- 计提：页面与 CLI 共用已确认应发工资，按明确科目借费用/成本、贷应付职工工资；不自动发薪/扣税，不重复扣记社保个人部分。已读回入账月份跳过，缺科目进入待补并阻断审核，原表变化阻止生成并保留旧审核表。
- 文档与自动化验证：同步当前状态、迁移/待办、架构五张地图及做账/页面规则。macOS 合成配置下全量 pytest 1,276 项通过、16 项跳过、24 项子测试通过；Vue 类型检查、121 项 Vitest、生产构建、Node 38 项、全仓库 Ruff、Python 编译、文档契约/本地链接及 `git diff --check` 通过。保留既有 5 条 PyMuPDF/Swig 弃用警告与 `display.woff` 构建提示。
- 浏览器验证：独立合成资料的真实 FastAPI/Chromium 完成多候选选择登记 → 工资脱敏读取 → 明确费用科目确认 → 生成工资计提 → 工资凭证审核保存；合成两人工资应发 10,000、扣款 1,120、实发 8,880，计提借贷各 10,000。检查浅色/深色、1280/390px 与 `no_skin`，修正窄屏候选下拉箭头被表格挤出的局部布局；最终无全页横向溢出、新增页面错误或 HTTP 错误，浏览器实际静态脚本 SHA-256 与最新构建 `680c312a35f388404d5dd1ccfc3abdc037f77b0d482f98a53d9fb109b17cf4f0` 一致。合成验收不替代最终用户验收。
- 未覆盖与授权：仅合成资料，不覆盖真实默认配置、正式 Windows BAT、正式入口浏览器前台拉起、系统原生选择器、Windows/网络盘并发、Tauri/打包成品或真实账套/申报；未暂存、提交、推送、合并或打包，保留原有改动。

### 2026-11-19 WS-06—09 补齐与接续验收

- 需求与起点：按用户追加要求和恢复指令，在 `codex/workspace-p3@d1d962a` 的现有未提交成果上继续非监控目录批量标签、WS-07 缺口修复、WS-08 增量汇总与 WS-09 服务器只读试验版；保留既有改动、原型及 ignored 配置，不操作真实业务资料与账套，未暂存、提交、推送、合并或打包。
- WS-06 / WS-07：非监控公司目录支持跨页勾选、全选筛选结果及带 revision 的批量标签，预览/打印/删除等源文件动作仍受活动目录约束。新增显式只读期初 v1，科目发生额只取已提供序时账；成本参考和进销存按逐票月份取纳税人身份，无新票但身份依赖变化也可刷新。往来预付款不匹配未来发票，直接执行原型生成器作账簿、抵扣及确定性匹配对照。
- WS-08：新增逐文件原始解析缓存、完整无链接清单、每日/显式内容核验、增量/全量重建与普通/成本完整代际。API、公司视图、单据及工作区草稿读取同一 manifest；固定 CSV/XLSX 保持兼容导出，按回执恢复中断并保留未知手改。10,000 个合成文件热缓存解析 0 个，3 增 2 改 1 删只解析 5 个，与全量结果一致。浏览器验收发现系统 `/var` 与 `/private/var` 别名混用导致公司目录读取失败，现以规范路径核对代际来源，兼容旧别名 manifest，仍拒绝异根及别名改指向。
- WS-09：新增独立 SourceProfile、已挂载共享/OpenSSH SFTP v3 只读适配、指纹确认、可终止 worker、目录分页/子树汇总、离线副本及独立预览租约；来源投影只写本机私有缓存，不切 monitor、不写服务器。Vue 右栏包含真实阶段、目录下拉/面包屑及主区内放大还原。子树可读文件数由后端返回，不支持格式仍列元信息并提示空内容；离线打开入口明确标注副本，重开恢复已保存角色和预算，关闭/切换释放预览。真实点击另发现批量选择条遮挡标签菜单，现提高菜单层级并在初始/异步加载后约束窗口边界，长菜单内部滚动。
- 文档与验证：同步实现状态、迁移、待办、设计、五张架构地图及所属规则。macOS 隔离合成配置下全量 pytest 1,244 项通过、16 项跳过、24 项子测试通过，保留 5 条 PyMuPDF/Swig 弃用警告；Vue 类型检查、113 项 Vitest 和 Vite 构建通过（保留既有 display.woff 运行时解析警告），Node 交互 38 项通过。浏览器与最终静态/文档检查的具体覆盖见实现状态。
- 后续边界：标准 SMB/SFTP 仍完整核对元数据，没有可靠游标；SFTP v3 无稳定 file ID，不能承诺远程原子快照。公司绑定只供身份上下文，现有公司/成本/库存/做账/税费模块尚未消费服务器来源；系统凭据引用、历史缓存容量治理另列待办。真实 SMB/SFTP/SSH Agent、真实默认配置、正式 Windows BAT、正式前台拉起、系统原生选择器、Tauri/打包成品均未验；合成自动化不替代最终用户验收。

### 2026-11-19 WS 现有后端收尾与状态核对

- 需求与范围：用户要求 WS 部分后端收尾；从 `codex/workspace-p3@d1d962a` 接续已有 WS-01—07 / WS-10，本轮不扩展 WS-08/09、工资计提、往来 / 科目期初格式或政策自动计算，不操作真实资料与账套，不推送、合并或打包。开工已有未跟踪原型与 ignored 配置 / 运行态均保留。
- 社保确认：发现嵌套 `社保明细` 损坏会退为空对象、非法金额可被当作空值、确认与草稿生成未共锁。现保留坏状态并拒绝写入，严格校验月份 / 金额 / 人数 / 费率，每个险种至少一方应缴已知；无效批次整批不写。申报文件采用 2 MiB 有界无链接读取和目录身份约束的原子替换，锁内核对 SHA、替换前复核 SHA 与目录身份，与凭证生成 / 编辑 / 导出共用进程内写锁；不承诺外部 CLI / 编辑器跨进程事务。
- 手工税费测算：发现前期留抵不符后，下一月可因前期结果为空恢复出数。现连续手工假设段传播 `TAX_CARRY_UNRESOLVED`，缩短查询范围不能绕过；修正前期后重算同源结果 / 解释。没有 assessment 的断档不补数，下一段仍只采用显式手工期初，未解锁政策计算。
- 文档收尾：更新 WS-01 / WS-10 总览、WS-05 / WS-07 当前实现与余项，移正 WS-02 体验待办的锚点归属；同步规格、实现状态、迁移清单、接口 / 数据 / 文件 / 任务 / 原因地图与所属规则。真实验收仍按原 37 项逐项记录，本轮不新增勾选。
- 执行与验证范围：新增 34 项合成边界回归，覆盖嵌套损坏、脏值、同源、混合批次、并发 CAS、共锁、目录替换、外部改动、连续异常 / 断档 / 修正恢复；相邻运行社保、凭证审核 / 导出 / 生成、银行、P2/P3 与公司 / API 回归。首次全量使用相对 `PYTHONPATH=src` 导致两个临时目录 daemon 无法导入包，日志确认后改用绝对源码路径，未改 monitor 代码；后续发现当前事实文档不允许固定 commit 标识，已将起点保留在本日志与私有检查点。
- 最终验证结果：macOS 下以绝对 `PYTHONPATH` 运行全量 pytest，1,201 项通过、16 项跳过、24 项子测试通过，保留 5 条 PyMuPDF / Swig 弃用警告；Node 交互测试 38 项通过。全仓库 Ruff、Python 编译、文档契约及 `git diff --check` 通过，61 个受跟踪 Markdown 文件的 608 处本地链接无断链。
- 未覆盖：真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Tauri / 打包成品及 Windows / 网络盘真实竞态；未执行真实社保确认、审批、导出 / 导入、迁移、申报或缴纳。自动化结果不替代用户验收。

### 2026-11-18 交接后复核与本地提交

- 在 `codex/workspace-p3@2a577af` 接手续做，用户确认按 BUG-04、BUG-05 与科目表/验收记录分两次本地提交；不推送、不合并、不操作真实资料或账套。既有验收来自 2026-11-17 的资料副本，不替代真实默认配置、正式 Windows BAT、正式浏览器前台拉起、系统原生选择器或成品验证。
- 在 macOS 重跑全量 pytest（1,167 通过、16 项 Windows/原生 OFD 组件测试跳过）、Python 编译、Ruff、文档契约与本地链接、Node 交互 38 项、Vue 类型检查、Vitest 107 项与 Vite 构建；重建前端与待提交的三个静态文件逐字节一致。隔离配置与合成资料的 Chrome CDP 回归覆盖工作区映射、凭证保存、税费与浅色/深色/390px/`no_skin`，另核对版本化静态响应与凭证页科目表来源提示。未在真实默认服务重启或执行实际账套导入。

### 2026-11-17 多公司工作区第二轮真实验收（写入类，副本）与 BUG-04 / BUG-05 复验

- 需求：用户要求修完 BUG-05 与科目编码后做第二轮写入类验收。同一家真实公司，真实资料夹先做逐文件 SHA 基线，所有写入在仓库外临时副本与独立配置上执行，命令行对照用同一副本的第二份拷贝；凭证草稿与勾稽两页用专用 Chrome（CDP）核对显示，控制台无错误。结束后真实资料夹 129 个文件与基线一致，副本已删除。
- 复验：BUG-04 的成本发票目录重新汇总后销售方为空的发票为 0；BUG-05 的油费 4 行移入“未计入的明细行”并提示金额，库存科目编码全部取到（读回快照），期末 5 个明细与账套 9 月末余额一致，差异只剩资料夹缺票的切割件和 1 个品类的取整差；读回前三个月序时账生成的做账草稿，9 月末库存与账套一致。
- 第二轮结果（18 项）：通过 6 项（从零新建工作区、子目录映射编辑、发票标签、项目人工归属、页面生成草稿、读回快照校验口径）；部分 7 项（监控切换未看 SSE、补建未测链接、冲突保护未测申报数据与页面未保存提示、凭证导出未在 Excel / WPS 与账套核对、改记入期未覆盖有销售的品类与已入账月份、属期移动只在副本模拟放错、改所属期未测整月拦截）；未测 5 项（废纸篓、打印、批量入库单 Excel / WPS、工资社保 Excel / PDF、其他记账软件），需要用户本机、账套或电子税务局操作。页面导出与 `voucher_cli export` 3 个月导入文件逐单元格一致，页面生成与 `voucher_cli draft` 三组参数逐单元格一致。
- 未改代码；验证范围是接口与两页显示，平台、打包与 Windows 不在本轮。

### 2026-11-17 BUG-04：成品油与电费电子发票的购销方和金额

- 需求：第一轮真实验收发现成品油电子专票只识别出价税合计；用户补充两张电网公司开具的电费电子发票（专票、全部不征税的普票各一张）同样缺销售方，并要求真实材料先脱敏，再用来稳定读取功能。起点 `codex/workspace-p3@2a577af`。
- 根因：三张原票的 PDF 文本把“购/买/方/信/息”逐字分行，名称在随后的“名称:”行，原有购销方规则都要求标签连写；金额先印“合计 ¥除税 ¥税额”再印价税合计，三元组只从价税合计向后找，只看到总额。
- 修改（`extraction/parsers.py`）：新增 `_extract_split_label_parties`，两个标签必须各自紧跟“名称”行且两名不同才采用，先列两个标签再列名称的版式两边都不取；三元组锚点增加独占一行（含逐字分行）的“合计”，嵌入词（金额合计、合计电费）不算，仍要求页内唯一且算术成立；新增 `_extract_pdf_untaxed_pair`，仅当同页没有任何百分比税率、有不征税/免税字样、合计行与价税合计之后各恰好一个相等金额时取税额 0.00。`services/document_index.py` 的 `CACHE_VERSION` 改为 2，旧缓存记录重新提取。
- 脱敏：测试只用保留 PyMuPDF 行序、名称/税号/号码/金额全部替换的合成文本，另加嵌入词、算术不符、税率存在、缺不征税字样、多余金额、标签先于名称等负向用例；原票和真实字段不进仓库。
- 验证：三张原票（只读）的购销方、除税额、税额、价税合计、税率逐字段与票面一致；新旧解析器在本机 128 份 PDF（53 张发票）上影子对照，只有这 3 张由空变为有值，原有非空字段无一变化。`tests/test_summary_and_costs.py` 79 项、单据索引/单据测试、Ruff 与全量 pytest 通过。
- OFD 补充（同日用户要求“OFD 的解析格式同样要覆盖”）：`_record_from_ofd` 在结构化 `CustomTag` 或文本回退之后调用 `_fill_from_ofd_layout`，用 `Content.xml` TextObject 坐标只补空的购销方与金额：“名称：”与同一行右侧值配对、按最近的购/销标记定方向，要求一购一销且不同名；金额要求唯一“合计”行与“（小写）”标签、按标签纵向带取值且算术成立，不征税对条件同 PDF；结构化金额与坐标不一致时整组不补。测试用 `_write_layout_ofd` 生成的合成 OFD（4 项）；本机真实 OFD 新旧解析结果一致。
- 2026-11-18 接手复核：合成双页 OFD 复现第一页“合计”和第二页“小写”被拼成一组金额，也可能跨页拼购销方；坐标补空收紧为单页且同一文档至多一个模板，保留现有结构化和文本提取路径，新增用例锁定不跨页补值。
- 未覆盖与提示：已汇总的目录在文件未变时不会自动重新提取，需要在页面“重新汇总”或强制同步后才看到新字段；XML 路径未改；真实目录里没有缺字段的 OFD，坐标补空只由合成样本验证；Windows、打包产物未验。

### 2026-11-17 BUG-05 与科目表口径：进销存排除非库存行，页面统一用草稿的科目表

- 需求：第一轮真实验收发现进销存把油费发票计入“燃油（升）”库存品类、期末库存虚增（BUG-05），且进销存的科目编码只读 `凭证/科目表.json`，账套后来新增的 4 个库存科目显示为空；用户要求修这两项。
- 方案：`bank/vouchers.py` 新增 `purchase_family_treatment`（燃油 → 费用；库存商品下没有电梯明细时电梯 → 固定资产；其余 → 库存），草稿生成分支与 `services/company_inventory.py` 共用。进销存遇到非库存品类的行，进销项两侧都列入 `excluded`（原因“燃油：做账记费用，不计入库存”等），新增 `non_stock` 提示；电梯的 `account_code` 与草稿一样取库存商品下含“电梯”的明细。`read_book_inputs` 改读最新 `做账草稿/账套读回/科目表_*.json`，没有快照才用 `凭证/科目表.json`，没有序时账也读；`opening.ledger` 返回所用科目表。`services/company_vouchers.py::_books(root, name)` 按 `草稿生成参数.json` 记的 `ledger` 取科目表（命令行生成的表用最新快照），列表统计、读取、保存、导出都用同一份；记录的快照不在时 `books_error` 说明且全部不可审核；读取结果新增 `books_source`，Vue 凭证草稿页显示“科目按 … 校验”。
- 验证：新增 `test_goods_booked_outside_stock_are_listed_not_counted`、`test_newest_books_snapshot_names_the_accounts_and_keeps_project_elevators_in_stock`、`test_review_checks_codes_against_the_chart_the_draft_was_generated_with`（均为合成数据）；全量 pytest、Ruff、`vue-tsc`、vitest 107 项、前端构建通过。
- 未覆盖：按销售方的已确认映射规则与导出习惯可在草稿里改记科目，进销存暂不读取；同一公司的资料副本已复验，用户实际目录另验。

### 2026-11-17 多公司工作区第一轮真实验收（只读）

- 需求与起点：用户确认按建议推进，指定一家真实公司做第一轮 12 项只读验收。起点 `codex/workspace-p3@3b17cb3`（同日“P3 收口”本地提交），工作区仅有无关 `pelican-bicycle.html`。同时按用户要求删除 26 个已并入当前开发线的本地分支和拆分备份分支（备份与现有提交只差两份较旧文档，代码一致）；保留 `main`、当前分支、`InvoiceHub-ws07` worktree 占用的分支和 5 个未并入的旧分支，远端分支未动。
- 方法：先对真实公司资料夹做逐文件 SHA 基线，再复制到仓库外临时目录；用独立配置（不读本机默认配置）登记公司、在副本上为成本 / 开具发票建投影，调用发票账簿、银行、三类勾稽、项目、目录、标签、草稿、税费、工资等只读接口，并经专用 Chrome（CDP）检查目录页、勾选合计、原票大图与比较明细抽屉。独立真值用资料夹内账套读回的序时账和银行对账单。结束后真实资料夹 129 个文件与基线完全一致，临时副本、配置与截图已删除。
- 结果：8 项通过（登记、非活动目录保护、发票账簿、银行流水、抵扣核对、往来核对、项目汇总、比较明细抽屉），逐项依据写在[待真实验收清单](docs/MIGRATION_GAP_CHECKLIST.md#ws-real-acceptance)；进销存部分通过；同号检查无样本；原票预览、筛选与跨页勾选只覆盖了 PDF 与单页场景。
- 发现：登记为 [BUG-04](docs/PRODUCT_BACKLOG.md#bug-04)（成品油电子专票购销方与金额未提取，已被正确单列为金额未识别）和 [BUG-05](docs/PRODUCT_BACKLOG.md#bug-05)（进销存把油费发票行算作库存品类）；WS-02 增记同类候选文件夹多于一个时的检测体验，WS-05 增记科目编码口径证据。本轮未改代码。
- 未覆盖：真实默认配置与正式入口、写入类操作（第二轮）、OFD 与同票多格式、超过 100 个文件、15 分钟续租、切换监控目录、跨页与标签筛选、同号检查、Windows BAT、原生选择器与打包产物。

### 2026-11-17 P3 收口：E2E 双浏览器模式、BUG-02/03

- 需求与起点：用户确认 P3 检查后的下一步建议，要求 ENG-05 真实浏览器测试支持两种方式：用本机默认浏览器测试，或交给 Codex 自行启动 Chrome。起点 `codex/workspace-p3@6d7e325`，保留无关 `pelican-bicycle.html` 与既有 ignored 状态；不切换分支、不推送；按用户要求作为一个本地提交。
- ENG-05：`workspace_p3_e2e.mjs` 新增 `P3_E2E_CDP=<地址>`，连接外部已运行的 Chrome，只关闭本脚本创建的 context，不关闭外部浏览器；未设置时仍 `launch` 本机 Chrome（Codex/普通终端）。就绪探测改由浏览器访问 `/api/v1/health`：本机 Agent 沙箱禁止 Node 进程连接 127.0.0.1 上除 CDP 外的端口（`Operation not permitted`，脱离沙箱亦同），浏览器则可访问。
- BUG-02：复核 `bank/jierui.py` 已于 `4d7af81` 用 `TYPE_CHECKING` 导入 `export_profiles`，`ruff check src tests scripts` 全部通过，登记改为已解决，本轮未改代码。
- BUG-03：成本页首次构建 / 空快照的 `sync` 原先缺 `review_count`、`not_parsed_count`，页面显示“undefined 张”，且 `review_count || 0` 把未知写成 0。后端临时快照改为显式 `null`，`page-costs.js` 新增 `costSyncText`：只有非负整数显示“N 张”，其余显示“待统计”；完整投影的合法 0 不变。
- 验证：后端全量 pytest（绝对 PYTHONPATH）通过；Ruff（src/tests/scripts）、`node --test tests/*.test.cjs` 38/38、Vue 类型检查、Vitest 107、Vite 构建（产物无漂移）通过。ENG-05 经 CDP 连接本机专用 Chrome 全流程通过，11 张截图、零控制台错误；合成空目录成本页 1280 / 390px 横幅显示“待统计”，无 undefined、无控制台错误。
- 未覆盖：`launch` 模式本轮未在本机重跑（本机进程树禁止直接启动 Chrome，留给 Codex 或普通终端）；BUG-03 未在真实默认配置、Windows BAT 与打包成品上复验；ENG-05 的 CI、旧首页与局部刷新回归仍在待办。

### 2026-11-17 工作区 P3 第 1—6 项

- 需求与起点：用户确认完成第 1—6 项，增量缓存与服务器链接 WS-08/09 另做。从 `codex/workspace-p2@36f8dfa` 在同目录进入 `codex/workspace-p3`，保留无关 HTML 和既有 ignored 配置/资料；不推送、不合并、不打包、不操作真实账套。
- B7.2：无账号列时可在映射弹窗手填本方账号，保留前导零，与预览哈希/revision 绑定。文件出现账号列时须完整唯一且一致，未映射也不能隐藏冲突；档案含私有账号，不可直接分享。保存计划保留根身份，避免并发列目录淘汰文件引用后写错位置。
- B7.1：银行目录逐文件显示内置/确认/未识别版式、交易行数、余额链断点和简单整表页脚；仅未识别文件提供映射按钮。共用受限无链接字节读取，目录 2000 文件/2 秒；每请求最多 32 冷文件/5 秒，可终止解析子进程。缓存绑定公司/目录/文件签名/档案哈希，待处理项不缓存，来源变化返回 409。
- B7.3：CLI 显式 `--company`、页面账簿/往来和凭证生成共用公司版式；页面生成及改记入期使用登记的自定义银行目录。公司版式不套用到公司根外输入；BOC 优先，回单在全部对账单之后解析，不修改源文件。
- WS-10：凭证编辑器补期间行、十进制借贷合计、无框输入和增删分录；结构变动仍用 SHA 冲突校验、与导出共锁及整批原子拒绝，审核须重新通过，来源转到存留首行，新增行不继承数量/学习槽位，公式或合并审核表拒绝结构编辑。库存提供精简/明细切换，社保按选择属期高亮；公司凭证/税费页不预加载经典 active-target frame。
- B8.1：税费表增加计税依据、税率和排除企业所得税的完整合计门禁；未提供应税销售额时计税依据保持 null，手工净税额仅在测算/解释中展示；附加税/印花税登记官方原文候选与独立 Decimal 样例。无人工复核签署，自动税种及完整合计仍为 null/needs_review，不用已知增值税小计冒充全部税费，不执行申报。
- ENG-05：新增独立合成公司/配置的真实 FastAPI + Chromium 脚本，无 HTTP 拦截；覆盖映射重验/保存/断链禁存、凭证增删保存并从 XLSX 重读、税费展开、浅深/390px/无皮肤入口及主按钮计算样式，零控制台错误。临时公司与浏览器退出清理；脚本可重复执行，截图不进入公开树。
- 验证：最终后端全量 1145 通过、16 跳过、24 个 subtests 通过（5 条既有 SWIG 弃用警告）；首轮相对 PYTHONPATH 导致 monitor 子进程 2 项导入失败，改用绝对 PYTHONPATH 后全量通过。Vue 类型检查、107 项 Vitest、37 项 Node 测试、Vite 构建、定向 Ruff、compileall、文档契约/本地链接与 diff 检查通过；构建保留既有 display.woff 运行时解析提示。
- 未覆盖：真实默认配置/业务资料、正式 Windows BAT、正式入口浏览器前台拉起、系统原生选择器、Tauri 宿主与打包产物；不以本地自动化或合成浏览器替代最终用户验收。OFD/OCR/复杂银行表格、税务 D0—D5 和 ENG-05 的 CI 扩展继续留在待办。

### 2026-11-17 工作区 P1/P2 按风险拆分提交

- 需求与现场：用户要求按风险程度拆分提交，并要求每个提交完整、批准安装 Rust 工具链。起点 `codex/workspace-p2@ab9d4b8`，modified 105 / untracked 46（含与项目无关的 `pelican-bicycle.html`）；未推送、未开 PR、未合并 `main`。
- 方案：按风险分组并按依赖排序（文档 → B6 成本 / monitor → 公司工作区后端 → 经典页 → Vue 前端 → Tauri），`app.py`、`test_api_contract.py`、`test_company_views.py` 按代码块分入对应提交。七个提交的哈希、风险与验证见 [分支状态](docs/BRANCH_STATUS.md)。
- 过程中发现与处理：首轮拆分因状态清单被截断漏看 `workspace-embed.css/js`、`workspace_embed.test.cjs`、`test_company_directory_guards.py`，曾以补漏提交追加，导致三个提交单独检出时缺嵌入资源。按用户要求在本地未推送范围内重放，把它们并入对应提交，最终树与改写前相同；首轮提交保留在备份分支 `backup/workspace-p2-split-20261117`。
- Rust：本机 `~/.rustup` 已有项目固定的 1.85.0 工具链与 crate 缓存，仅缺 rustup 代理，未重新安装；直接用该工具链离线运行。
- 验证：每个代码提交在临时 worktree 独立检出后跑后端全量（1022 / 1109 / 1124 / 1124 通过）与 Node 测试；Vue 提交另跑类型检查、Vitest 102 项与构建，构建结果与提交产物一致。Rust `cargo test --lib --offline` 56 项通过（含原生拖入判定），4 项回环套接字测试因本机会话禁止连接 127.0.0.1 失败（`Operation not permitted`，与代码无关，涉及文件本轮未改）。
- 未覆盖：上述 4 项 Rust 回环测试需在普通终端复跑；真实资料、Windows BAT、正式入口前台拉起、原生选择器、Tauri 宿主与打包产物。

### 2026-11-17 工作区 P2 前后端对接核对与后续规划

- 需求与现场：用户要求对接 Codex 已完成的 P2 后端，并规划后续前后端开发。分支 `codex/workspace-p2@ab9d4b8`，保留全部既有 modified/untracked；未暂存、提交、推送或合并。
- 核对结论：B3/B5/B7/B8 的路由与 Vue 调用、字段一致，Codex 已同时完成前端接入。开工时后端相关 28 项、前端 100 项通过。
- 修正：
  - B7：预览只验证余额链，保存还要求唯一本方账号列。缺账号列的网银导出在页面显示“余额链成立”、按钮可点，提交后 422。`company_bank_layouts.preview` 现先跑保存时同一 `statement()` 检查，返回 `save_blockers`；Vue 逐条显示并禁存。
  - 弹窗：`WsModal` 传送到 `<body>`，`#app button.primary` / `#app button.danger` 不作用于弹窗，所有弹窗主按钮显示为普通按钮。补 `.ws-modal` 选择器。
  - 映射弹窗按原型 `openMapping` 重排：列头上方下拉、来源小签（表头词典命中 / 已确认版式 / 手动指定 / 方向由余额链确认 / 未使用）、原始列名与样例、方向 checkline。
  - 税费：做账“税费”表改为原型一行一税种、点击行展开算法，状态胶囊只按后端字段是否为空命名；总览与表格 null 显示“未测算 / 未录入”。B5“未对流水”改琥珀胶囊。
- 规划：在开发方向文档新增 P3 表（提交拆分、B7.1 版式识别表、B7.2 手填本方账号、B7.3 CLI 接线、WS-10 余项、B8.1 税率与合计受税务门禁、ENG-05、WS-08/09），待用户排序；WS-10、BANK-01 同步证据。
- 验证：相关后端 170 项通过（新增 `test_bank_preview_reports_save_blocker_without_account_column`）；前端类型检查、Vitest 102 项（新增 2 项）、Vite 构建、Node 交互/嵌入 23 项通过。合成 localhost（临时目录、合成 CSV 与税费记录）+ 专用 Chrome CDP：1440 浅/深核对缺账号文件禁存与阻断提示、有账号文件保存后显示“已确认版式”、弹窗主按钮恢复墨底；做账税费表展开算法，390px 布局正常。
- 未覆盖：真实银行导出与业务资料、正式 Windows BAT、正式入口前台拉起、原生选择器、Tauri 宿主与打包产物；未跑后端全量回归；其它弹窗（向导、导出、关机）的主按钮恢复只经样式规则推断，未逐个截图。

### 2026-11-17 工作区后端 P2：标签计数、凭证墙、银行版式与税费手工基础

- 需求与现场：接续引用的 P1 聊天实施 B3/B5/B7/B8。起点 `codex/workspace-p1@ab9d4b8`，main 核验为 `ee0f2c2`，保留开工 modified 99/untracked 42 与 ignored，在同目录建立 `codex/workspace-p2`。未暂存、提交、推送、合并或打包；新增修改与前序共用文件，保留开工文件副本用于增量审阅，不把前序内容混入本轮提交。
- B3/B5：标签计数按全部登记公司的可见标记、票号全局去重，离线资料显式列出并显示已知计数；刷新不覆盖未保存标签草稿。凭证墙消费服务端 flow_match/project，实际匹配家族显示已对流水，红冲/源过期/银行解析错误显示未知；缺完整月份不能显示未匹配，项目沿用人工优先规则。
- B7：新增公司领域路由、版式服务与有界表格算法，支持 CSV、单表 XLSX、可还原表格文字 PDF，三种金额及顺逆序/两种方向独立验证，只接受唯一全链成立假设。预览含原始行样例与断点；文件引用绑定公司/根/目录/签名，计划绑定字节/映射/revision，保存前重验；无链接读取、原子替换、坏状态保留。确认版式在公司账簿/往来自动复用并重新校验，profile 哈希变更清缓存，原 BOC 保留。首笔倒推期初仍须原件核对；OFD/OCR/复杂表格/CLI与凭证生成复用未实施，BANK-01继续开放。
- B8：公司根税费记录与旧草稿分离，六税种分月独立录入申报/缴纳，null不当零，确认零亦需来源。普通一般计税仅运行明确四项手工假设，Decimal结果与解释/trace绑定同一身份与记录快照；月度正额不跨月冲抵，留抵不符阻断，短查询不能绕过。空范围仅记录覆盖期，页面明示。用户 P2 请求不等于政策复核签署：自动规则、表式映射、征期与申报表导入未实施，完整税务工作台 D0—D5 保持门禁。
- 前端：新增银行映射与税费宽弹窗、总览税费数字及做账税费表，映射修改后重校验才能保存；未知网络/5xx写响应锁定查询，409不自动重放，税费查询比对完整假设及金额。编辑月份/税种先读取对应记录与revision。窄屏合成检查暴露映射表最小宽度覆盖不足，修正为局部表格规则；样例保持横向滚动。前端构建产物由Vite生成。相邻Ruff暴露既有jierui类型注解缺导入，补TYPE_CHECKING，不改导出运行行为。
- 验证：后端产品回归1092通过、16跳过、24个subtests通过（88.74秒，5条既有SWIG弃用提示）；最终增量163项通过（含文档契约/链接、损坏文件、版式不可读与同源写校验），未重复全量。前端最终100项（包含同期P1新增2项）、类型检查与构建通过，Node 37项通过；定向Ruff和compileall通过。合成浏览器核对标签计数、映射/保存与后续匹配、手工税费回填/独立零缴纳记录及税费标签，浅色/深色/390px/no_skin证据随本地审阅包保留。隔离脚本因缺少main guard在spawn诊断子进程重复初始化而报错，未将该诊断算作产品验收；验收服务/标签和接口读取正常，服务及临时资料收尾关闭清理。同期另一轮P1对接修正已出现在共享目录，全部保留；现场增量审阅须按归属清单区分，不作为本轮独立P2提交。
- 未覆盖：真实默认配置/业务资料、正式Windows BAT、正式入口前台拉起、原生选择器、Tauri宿主及打包产物；没有真实申报/缴纳/账套操作。README按首页维护约定不改。实现状态、规格、待办、迁移、规则与四份架构地图同步，真实验收清单不自动勾选。

### 2026-11-17 工作区 P1 前后端对接核对与修正

- 需求与现场：用户要求核对 Codex 已完成的 P1（B1/B2/B4/B6）前后端对接，确认后动手修正。分支 `codex/workspace-p2@ab9d4b8`，Codex 同时在同一目录开发 P2；本轮只改 P1 文件，保留全部既有 modified/untracked，未提交、推送或合并。
- 核对结论：四项字段契约一致，前端均已接通。发现并修正：
  - B4：正式导出先落盘“待核对”回执再校验，确定的事前拒绝（账套不可用、审核表冲突、参数无效）也会让回执永远停在 `unknown`，页面只能刷新。现记为 `state:rejected`；Vue 报错后只 GET 一次回执，`rejected` 才放开按钮，`unknown` 仍只读查询，同 token 不重放；写出中途的 `VOUCHER_DRAFT_UNREADABLE` 保持 `unknown`。做账页头“导出凭证（N）”改为已审核未导出张数。
  - B2：登记记为 `failed`（只发生在写公司清单之前）后同一计划不能再执行，向导只能关掉重开；冲突/计划过期后同一路径不会重新检测。现同一计划再次提交时旧记录改名保留并重新执行；Vue 读到 `failed` 自动重新检测，并新增“重新检测”按钮；检测报错在换路径后清除；读回完成后选中新公司。
  - B6：嵌入成本页原先连销项税率也锁死，与用户 2026-11-10“成本页只改销项税率”的决定冲突，且工作区没有其它改税率入口。现只锁纳税人身份（胶囊显示身份或回退口径），税率与保存按钮恢复；`costs.html` 重复的 `class` 属性合并，脚本版本号改为 `20261117-company-tax-rate-editable`。
  - B1：目录合计在有缺金额 / 多格式金额不一的同票时显示未计张数。
- 未改：`GET /api/v1/companies/{id}/cost-tax-profile` 仍无页面消费方，按用户“可以先不接”保留。
- 自动化：相关后端 146 项通过（含新增导出拒绝回执、写出中途保持 unknown、失败登记可再执行）；前端类型检查、全量 Vitest 100 项（新增 2 项）、Node 交互/嵌入测试、定向 Ruff、前端契约测试通过；Vite 重新构建 `web/static/app/`，构建包含当时同目录 Codex 的 P2 前端源码。
- 未覆盖：浏览器实测与截图、真实默认配置与业务资料、正式 Windows BAT、正式入口前台拉起、原生选择器、Tauri 宿主与打包产物；未跑后端全量回归。

### 2026-11-17 工作区后端 P1：统计、资料夹检测、凭证预览与公司成本口径

- 需求与现场：按用户要求先开发规格 B1/B2/B4/B6，P2 与税务实施保持原边界。起点 `codex/cost-select-all-transitions@ab9d4b8530c9212c9427e6e498e2e0f9faf53d73`；核验 main 为 `ee0f2c2`。规格依赖已有工作区开发线，保留全部既有 modified/untracked/ignored 后在同目录新建 `codex/workspace-p1`；未创建 worktree、未提交、未推送或合并。已有未提交内容与本轮共用文件，四项独立提交须先整理前序基线，禁止混入前序工作。
- B1：目录标签与关键字/格式/状态等全部筛选后、分页前重算统计；首页与目录合计复用勾选同票家族规则，以 Decimal 累加并返回两位十进制字符串。新增计入/缺失/冲突家族张数；非法金额不计入，同号多格式只计一次；Vue兼容旧数字一个版本，标签筛选后继续显示合计与计入张数。
- B2：新增只读 `/api/v1/companies/detect`，六类子目录状态、受限文件数与目录身份绑定哈希；不登记、不创建、不切监控。登记带 revision/plan_hash/create_missing，创建前重检、仅补所选空目录，保留原文件和未选目录。runtime登记日志与排他意图支持结果查询，未知响应不重复创建/登记；替换目录为409。Vue300ms防抖并丢弃迟到响应，未知后锁写按钮，原生取消保留草稿。合成浏览器发现新检测表撑宽向导、复选框被文本框样式放大，已以网格最小宽度和表单控件限定修正，窄屏表格局部横向滚动。
- B4：审核表列表和单表返回后端 months 索引及不可读表诊断；页头月份/数量不再遍历前端凭证计算。dry_run与正式导出共用校验、整月阻断、已导出跳过、编号和列映射，返回列名/未匹配列/最多五行样例，金额保持十进制；不写文件、历史、习惯或执行回执。可选month同时限制预览与正式导出，空值为当前审核表全部月份。正式导出仍需确认；request_id意图在产生文件前落盘，完成后保存回执，未知只能GET查询，同token不重放；旧CLI/API兼容。补审核表目录链接拒绝，避免预览/导出采用另一公司文件。Vue增加预览代际、选表读取代际与未知结果查询入口。
- B6：新增按公司/月读取生效身份与该公司保存销项率的只读接口；链接/不可用成本目录或链接状态文件拒绝读取。工作区成本页显示只读身份/税率胶囊，未设置明确回退，保留品目表入口。实际v1投影仍按当月身份，历史月份查询不等于历史成本重算。同公司开具映射取代已登记公司的全局开具源；全部API/daemon/spawn/手动构造传相同来源，读取fingerprint纳入映射，旧来源缓存从页面和工作簿排除；未实际读取时不伪造读取时间。已开快照和品目表继续公司独立保存。
- 自动化：最终代码后端全量1093通过、16跳过、24个subtests通过（87.28秒，5条SWIG弃用警告），覆盖目录/状态链接拒绝和来源缓存读取时间修正。Vue类型检查、93项Vitest、Vite构建通过；Node交互及嵌入测试通过；compileall、定向Ruff、文档契约/本地链接和diff检查通过。初次后台回归因新增spawn参数与测试替身不一致、daemon测试相对PYTHONPATH在临时根失效，已修测试参数并以绝对源码PYTHONPATH完成回归。保留既有SWIG弃用提示及Vite运行时解析display字体提示，不将其描述为无警告。
- 合成浏览器：隔离localhost、合成公司/源XML/审核表，检查B1标签过滤后226.00与1张、B2六类检测表、B4期间与列名/样例、B6只读身份；1440浅/深及390px截图核对，不执行真实登记、真实导出或账套操作。经典做账后台账号/辅助档案接口因合成根未配置账套返回400，已明确未将其算作真实账套验收。
- 未覆盖：真实默认配置与业务资料、正式Windows BAT、正式入口浏览器前台拉起、系统原生选择器弹窗、Tauri原生宿主与打包产物；完整税务引擎和历史成本重算未实施。WS真实/平台验收清单不自动勾选。规格、WS-10、实现状态、迁移与架构/规则已同步，README按首页维护约定不改。

### 2026-11-16 原型弹窗化、前端收尾与前端设计标准

- 需求：用户确认临时识别、添加公司保持原型弹窗形式；前端由本轮收尾（含全局提示条与关机流程）；后端功能写开发方向交 Codex；前端设计风格与标准以原型定为硬性要求，后续新功能前端按此开发。接续 `codex/cost-select-all-transitions@ab9d4b8`，未提交、未推送。
- 弹窗：新增 `WsModal`（640 / 1100px、标题栏 + ×、Esc、html+body 滚动锁计数、焦点归还、`open` 让内容常驻）。临时识别改为外壳弹窗，`/workspace/temporary` 路由保留（桌面原生拖入目标），关闭回到打开前的视图，模块列按钮改工具样式不高亮，弹窗内为原型提示条、分段视图切换与虚线拖放区；Esc 先关预览再关弹窗。添加公司资料夹改为弹窗向导：路径与选择同行、字段标签 12.5px、纳税人身份必选 radio（一般 / 小规模 / 稍后设置，系统不默认）、选身份前“登记”禁用、新建计划用表格；登记结果改 toast，新公司在首页标签打开。
- 关机：模块列电源不再切到“设置”模块，外壳直接弹出确认（读取关闭偏好、保留 / 停止监控、记住选择），与经典页同一 `/api/v1/server/shutdown` 契约与受理判定；失败或未知只提示、由用户重试；桌面宿主托管后端时禁用并说明。
- 提示条：新增全局 toast（底部居中、2.4 秒），仅用于成功 / 中性反馈。
- 做账：页头改原型结构——“做账 · YYYY 年 M 月”、信息提示 i、只能选有草稿月份的年月小日历（绿点标记）、“全部月份”、“导出凭证（N）”主按钮（无通过凭证或有未保存改动时禁用）；页头与凭证组件经模块 store 按公司同步，凭证组件仍拥有草稿；导出面板改宽弹窗，确认与结果规则不变。年月选择器新增 `marked / only`。
- 目录：新增原型四项统计（全部记录 / 待核对 / 同票其他格式 / 当前筛选合计，全部取后端 `stats`；标签筛选时合计不显示，因后端在标签筛选前计算）与关键字（300ms 防抖）/ 格式 / 状态 / 标签筛选，均由服务端筛选后再排序分页，全选沿用同一筛选。
- 文档：新增[前端设计标准](docs/design/WORKSPACE_UI_STANDARD.md)（令牌、排版、布局、组件、交互、深色 / 窄屏、验收清单），在页面规则与任务导航标为强制；新增[原型后端缺口开发方向](docs/WORKSPACE_PROTOTYPE_BACKEND_SPEC.md)（B1—B8 接口、不变量、验收与前端接入点）；WS-10、设计索引、文件地图同步。
- 验证：`pnpm run typecheck`、`pnpm test`（90 项；建公司与导出用例改为在 `<body>` 对话框内查找）、`pnpm run build`、工作区 / 标签 / 文档契约通过；合成浏览器核对临时识别 / 添加公司 / 关机三弹窗外观，× / 取消 / Esc 关闭后滚动锁释放、路由回到原视图；做账页头与目录统计筛选 1440 截图核对。
- 未覆盖：未实际执行关机（合成环境只验证打开与取消）；有草稿时的做账页头日历与导出预览、凭证编辑器余项无数据未实测；桌面原生拖入临时识别、系统原生选择器、Tauri 窗口与打包产物未测；后端 B1—B8 未实施。

### 2026-11-16 工作区原型复刻续：逐页视觉对齐

- 需求与起点：用户反馈现有前端与原型有偏差，要求“设计、风格一模一样”；确认以磁盘上的 `docs/design/workspace-sidebar-prototype.html` 为准、保留既有未提交修改、全量逐页截图比对。起点 `codex/cost-select-all-transitions@ab9d4b8`，接续交接任务 `ws-prototype-replica-20261116`；未切分支、未提交、未推送。
- 方法：专用 Chrome + CDP 对原型与合成 localhost（隔离临时根，未启动 monitor）逐页截图并读取计算样式（坐标、字号、字重、内边距、颜色）比对。并行审计子 Agent 中 3 个因账号 API 403 中途失败，相应区域改为人工比对。
- 外壳与首页：模块列补分隔线、“关于与更新”在设置页不再高亮成 lime；侧栏常驻“置顶”分组与空提示，公司 / 目录 / 置顶行按原型 1px 边 + 6px 内距 + 18px 箭头列对齐，⋯ 按钮悬停才占位、角色标签让位；期间切换贴页头基线、标签改为“N 月 / X季度 / 今年 / 全部”并移除冗余“刷新”（双击 hi. 仍可刷新本页）；KPI ≥1 万显示“xx.xx 万”（整数分舍入，悬停显示精确值）；表头 13px/600 正文色；凭证墙 212px 自适应四列、142px 缩略图；修正票面口径提示因 flex 拆开粗体产生的空隙。
- 目录页：页头改为面包屑 / 目录名 / 路径 + 右侧“当前监控目录”状态（不推断 daemon 运行），非监控目录显示琥珀提示与“设为监控目录”；税率显示为百分比（非小数分数原样显示），状态为彩色胶囊，单元格不折行并横向滚动；勾选操作条改为原型墨色条：lime 计数、可点开合计详情的合计框、无框图标按钮、右端“全选筛选结果”与 ×。
- 做账：去掉页头整宽分隔线，面包屑 13px、路径等宽；流程条按原型尺寸，“资料齐全”按子目录实况显示 ✓ / !；做账标签改原型下划线式（不再是白色方块）；无草稿时隐藏审核表下拉等空控件并显示虚线空态卡片；税费改空态卡片；映射规则 / 账套设置时下方经典页占满剩余高度；凭证列表外框、左侧 lime 竖条选中态、通过 / 待审 / 阻断彩色胶囊；月份选择器改 4 列、加粗当前月、底部“本月”。
- 设置：页头“设置 / 全局设置，不随公司切换”，标签表常驻（不再折叠），颜色改色块 + 七色命名下拉（旧色值显示“自定义”保留），新增在右上、删除为 ghost 按钮；整列滚动，经典设置页保持一屏高度。
- 成本分析（嵌入经典页，仅 `workspace-embed.css`，独立经典页不变）：外壳页头已有公司 / 模块 / 路径，隐藏经典重复标题、路径、连接状态、最近文件夹与六张统计卡；同步状态改原型提示条；“本公司设置 | 销项数量比对”在 iframe ≥760px 时并排；下划线标签 + 右侧刷新 / 重新汇总 / 更多；算法说明 ! 改 17px 圆形信息钮；勾选工具右对齐；底部操作条改墨色条（深色为抬升面）。嵌入样式版本 `20261116-prototype-3`。
- 验证：`pnpm run typecheck`、`pnpm test`（90 项）、`pnpm run build`、`tests/workspace_embed.test.cjs`（6 项）、`tests/test_workspace_frontend.py` 与 `tests/test_invoice_tags.py` 通过。合成浏览器 1440 浅色核对首页 / 目录 / 勾选条 / 成本三标签与操作条 / 做账 / 设置，深色核对目录勾选、成本开票参考与操作条、做账，390px 核对首页与侧栏抽屉；外观已切回浅色。
- 未覆盖：凭证列表 / 编辑器 / 导出与编辑器内月份弹层无草稿数据，仅按源码改样式未实测；合计详情弹窗、比较视图、银行 / 抵扣 / 工资目录页、品目表等成本对话框未逐项截图；未测真实默认配置、正式 Windows BAT、正式入口浏览器前台、系统原生弹窗、Tauri 窗口与打包产物；Ink Pulse / Animal Island 继续隔离未复验。结构性差异登记 [WS-10](docs/PRODUCT_BACKLOG.md#ws-10)。

### 2026-11-16 工作区原型复刻（进行中）与明暗外观协调

- 需求与起点：用户要求在继续 WS 开发前，以 `docs/design/workspace-sidebar-prototype.html` 为准复刻整个工作区；接手后追加要求修正此前不到位处，并协调明暗皮肤：深色下按钮点击不明显、按钮框外露、遮罩色差。起点 `codex/cost-select-all-transitions@ab9d4b8`，接续既有 WS 未提交修改，不切分支、不提交、不推送。
- 原型复刻（Codex 阶段，未完成）：72px 模块列 + 292px 常驻侧栏、原型 SVG 图标、`prototype.css` 视觉基线；公司首页改为连续总览（服务端账簿 / 项目合计，税费测算与申报显示未接入）；模块各自记住选中对象，经典模块只在选中对象等于监控目录时显示；凭证列表 + 编辑分栏与月份弹层；外壳关机按钮只打开设置页既有确认框。
- 接手修正：补完中断的总览原始凭证墙接线（期间与账簿 / 项目共用一个范围，`ledger.checks` 缺失不再报错，读取失败与无数据分开提示）；凭证墙进入视口后才读取两组银行流水比较，保持总览打开开销与勾稽标签懒加载。
- 明暗协调：根因是 `website-dark` 皮肤对裸 `button` 的底色 / 边框 / 悬停规则在 Vue 外壳中晚于原型样式加载，盖出侧栏、模块列与标签的方框并抹掉期间切换等选中态。规则改以零特异度 `:where(body:not([data-page="workspace"]))` 仅作用于经典页面；深色补充选中 / 边框 / 悬停变量，主按钮与选择条不再反成近白块，按钮按下有位移反馈；嵌入经典页的墨色主按钮仅限浅色。
- 遮罩：经典对话框只遮住 iframe，模块列与侧栏仍亮。页面桥新增展示消息 `modal`，外壳以与 `.modal-backdrop` 同色同模糊的遮罩覆盖其余区域，iframe 置于其上；重载、隐藏、卸载即清除。窄屏侧栏遮罩改用同一变量。适配器资源版本 `20261116-prototype-2`。
- 自动化：前端类型检查、90 项 Vitest（新增遮罩桥鉴权 / 清除用例，勾稽懒加载断言收窄到抵扣关系）、Node 交互 / 嵌入适配器 23 项（新增对话框可见性上报）、JS 语法、工作区 / 前端 / API 契约 115 项通过；Vite 构建产物重新生成；文档契约与 `git diff --check` 通过，`compileall src` 通过。全量 pytest（`PYTHONPATH=src`）仅两项 monitor daemon 子进程测试失败、其余通过：本机 `.venv` 未安装 `invoice_hub` 包，子进程无法导入，与本轮改动无关，未修复。
- 合成浏览器：隔离临时根 / 配置（未启动 monitor）与专用 Chrome，1280 浅色 / 深色核对首页总览、单据、做账、设置、公司选中、期间切换与关机确认遮罩，390 深色核对侧栏抽屉与遮罩、无横向溢出。合成环境下经典单据页显示“加载已中断”，独立经典页同样出现，非嵌入导致，未处理。
- 未覆盖与剩余：原型复刻整体仍未完成（成本分析布局、目录筛选 / 选择弹窗、临时识别弹窗、新建公司弹窗、设置标签区、做账主期间选择器等），不宣称完成；未测真实默认配置、正式 Windows BAT、正式入口浏览器前台、系统原生弹窗、Tauri 窗口或打包产物；Ink Pulse / Animal Island 在工作区继续隔离，未复验。

### 2026-11-16 补齐项目列与比较凭证明细（WS-03 / WS-04）

- 需求与起点：完成 WS-03、WS-04 的开发余项；在 `codex/cost-select-all-transitions@ab9d4b8` 接续既有 WS 实现，保留已有源码、文档、服务器设计原型与 ignored 本机状态，不切分支、不提交、不推送、不合并、不打包。
- 项目列：经典首页增加“项目（票面口径）”，与项目汇总共用人工优先 / 唯一备注规则；同票多格式（含文件名号码家族）一致，冲突留空，人工保存无需重建即反映。附加字段不改变发票行身份、金额或投影；人工文件嵌套损坏保留并拒写。
- 比较交互：后端生成库存 / 往来 / 抵扣汇总卡片和逐行明细，沿既有算法 ID 联动抽屉与并排记录；跨期来源在步骤中披露，不猜分摊。新增每组最多六项的发票 / 银行回单墙、对应源页大图和回单识别字段 → 流水 → 发票联动。隐藏标签停止续租，迟到请求丢弃，XML 仍作纯文本；非监控发票必须先设为监控目录。
- 来源保护：银行回单只在请求时只读发现，使用独立公司 API 与原 PNG renderer；HMAC 绑定公司、目录链身份、唯一源文件 SHA / 版本 / 页码，不接受任意路径。同名来源不唯一不给预览，链接 / junction 拒绝，目录替换、源变化或渲染中变化使旧能力失效。共用银行 / 抵扣缓存增加 ctime、dev / inode，并在解析后复核签名，避免等大小恢复 mtime 的替换复用旧字段。
- 相邻修正：实际浏览器发现长流水摘要将明细按钮挤出桌面可见区，改为各栏独立横向滚动并保留可读列宽；经典首页列宽、占位 colspan 和资源版本同步。构建产物由 Vite 生成。
- 自动化：前端类型检查、89 项 Vitest、22 项 Node 交互与 JS 语法通过；后端项目、回单、往来、银行、抵扣、库存、公司目录 / 同号 / 账簿、标签、预览、API / 服务接线 / 目录保护回归通过，文档 / 静态资源 / 工作区契约通过，变更 Python ruff 通过。测试仅使用合成 PDF / XML / 清单，不代表真实银行版式或账套验收。
- 合成浏览器：独立临时根 / 配置 / runtime 与专用 Chrome，未启动 monitor；health 指向隔离环境、JS / CSS 与当前源码及构建逐字节一致。1280 / 390 检查浅色、深色、no_skin 恢复、项目列、六项分页、汇总 / 流水抽屉、回单第 2 页大图与翻页 / 关闭，页面无横向溢出，控制台无脚本错误。工作区 Ink Pulse / Animal Island 继续按此前用户确认隔离，本轮不重新启用。
- 文档与未覆盖：同步实现状态、待办、迁移、分支记录、架构入口及文件 / 接口 / 数据 / 原因 / 导航、页面与做账规则。WS-03 / WS-04 当前登记开发范围完成，37 项真实验收保持未勾选；未测真实默认配置、正式 Windows BAT、正式入口浏览器前台拉起、系统原生弹窗、Tauri 窗口或打包产物。
- 收尾现场：专用浏览器与两次合成 localhost 已关闭、8874 端口释放；验收生成的资料、截图与 npm 下载缓存收尾清理。工作树为 modified 69、deleted 0、untracked 27、ignored 38，无 Git warning，包含保留的既有修改 / 原型 / HTML 与本机依赖和运行态；未提交、未推送。仓库外任务检查点保留用于追溯，后续无须恢复时可移除。


### 2026-11-16 服务器链接入口图标调整

- 需求与起点：用户提供 macOS 连接服务器图标，要求替换原型现有符号；接续 `codex/cost-select-all-transitions@ab9d4b8`，保留既有未提交内容。
- 方案与结果：将“服务器链接”前的文字符号替换为原创 20px 内联 SVG，以圆角显示器、支线和网络节点参考截图形态，继承入口文字颜色；装饰图标不进入可访问名称，原按钮文本及点击配置行为保持。设计说明同步，不引入图片资源或产品代码变更。
- 验证与边界：JS 语法、离线 DOM 的 SVG 结构/点击打开配置检查及 `git diff --check` 通过；未做真实浏览器视觉检查，未覆盖真实默认配置、Windows BAT、浏览器前台拉起、原生弹窗或打包成品。未提交、推送或打包，无临时文件。

### 2026-11-16 服务器目录选择回归右侧标签与面板边界调整

- 需求与起点：用户要求撤回独立“服务器文件列表”工作区，恢复“打开服务器文件列表”按钮；用当前目录名替代右栏“目录汇总”，下拉选择子目录并汇总。移除全屏，放大只到本机公司侧栏右边界。接续 `codex/cost-select-all-transitions@ab9d4b8`；保留开工 52 份 modified、20 份 untracked、38 项 ignored，无删除和 Git 警告。
- 方案与结果：仅修改隔离原型脚本和设计文档，撤去服务器公司树、独立内容区与原模块点击拦截；入口只开右侧面板。本机公司列表、标签和模块继续使用原 DOM。根目录标签显示实际连接根名称，支持下拉直接子目录、上一级与面包屑返回；统计取所选目录及子目录的完整缓存，不重复解析旧票。空目录和只有不支持内容的目录均显示“无可读取的文件”，筛选无匹配、首次无缓存另行提示。
- 面板与保留能力：右上角只保留开关/放大还原，删除 Fullscreen API 及其入口；普通和放大宽度均限主内容区，通过边界测量、窗口 resize 与 ResizeObserver 跟随公司栏拖宽。保留来源隔离、固定合成样本跨页面缓存、增量游标/核对回退、离线预览和取消/断连/崩溃恢复。跨模块来源绑定继续作为未来设计，不将右侧合成统计写成已接入生产模块。
- 同步与验证：更新设计 §4/10/12、WS-09、实现/迁移状态及架构导航/流程/数据/文件/注释地图、页面规则。JS 语法、离线 happy-dom 50 项交互断言与文档契约 16 项通过；原 HTML 与本轮开工前逐字节相同，本机公司栏/模块 DOM 内容未变；本地文档链接和 `git diff --check` 通过。边界验证使用可控测量值与 ResizeObserver 回调，只证明计算/响应逻辑。
- 未覆盖：浏览器工具此前禁止 file 协议，本轮未绕过；未实测真实浏览器桌面/390px 视觉、实际拖宽/面板尺寸或宿主窗口。未测真实服务器、真实默认配置、当前皮肤、正式 Windows BAT、正式入口前台拉起、系统原生弹窗或打包产物。临时检查与备份收尾清理；未提交、推送、合并或打包。

### 2026-11-16 服务器工作区控件、公司目录与跨模块增量设计补充

- 需求与范围：接续 `codex/cost-select-all-transitions@ab9d4b8` 的服务器设计任务，按用户新截图补充右侧文件标签开关、放大/还原、全屏及“服务器文件列表”；保留已有 52 份 modified、20 份 untracked 和 ignored 运行态，不改生产功能、分支或原有原型 HTML。
- 原型结果：独立脚本新增右上角三个控件；网页全屏须用户点击，API 缺失/宿主拒绝有提示。服务器文件列表切入独立公司六类目录及未归属目录，返回本机恢复原 DOM 与导航；服务器各模块读取同一合成来源/公司/目录/完整代际，未归属不进入公司。首页/成本/单据/做账/一致性/OCR/临时识别/设置展示各自计算或能力边界，没有伪造真实识别、凭证或导出。
- 缓存与方案：同协议/服务器/账号/根重连复用快照，异来源隔离；固定示例的合成缓存可跨页面重载，自填连接信息仅会话保存。增加离线模拟变化、可靠变更游标与标准目录核对模式、游标过期回退，epoch 丢弃迟到候选。设计 §11—12 细化服务器持久日志的必要条件、游标与完整代际同提交、SourceBinding、模块准备度及人工覆盖保护；标准 SMB/SFTP 不承诺免目录枚举，新增/修改/删除都传播依赖。
- 文档同步：更新 WS-08/09、设计索引、实现/迁移状态、架构入口及任务/文件/流程/数据/注释地图、页面与监控规则；仍是未来设计，没有新增生产接口、连接器或增量引擎。
- 验证：JS 语法通过；离线 happy-dom 55 项交互断言覆盖控件、SSH 校验、跨模块同代及滚动、本机 DOM/导航保留、同来源复用/不同来源隔离、重载缓存、损坏缓存回退、离线预览、增量/取消/崩溃/迟到任务及全屏成功/拒绝/不支持分支；文档契约 16 项通过，13 份文档的 352 个本地链接有效，原型 HTML 与本次补充前逐字节一致，`git diff --check` 通过。离线环境补齐 structuredClone API，不能冒充真实 WebView。
- 未覆盖：沿用前轮浏览器工具阻断，未绕过 file 协议限制；未实测真实浏览器桌面/390px 视觉、全屏尺寸或 Codex 宿主窗口。未测真实服务器、默认配置、当前皮肤、正式 Windows BAT、正式入口前台拉起、原生弹窗或打包产物。临时检查脚本及备份收尾清理；未提交、推送、合并或打包。

### 2026-11-16 服务器链接试验版设计与汇总缓存增量刷新（WS-08 / WS-09）

- 需求与起点：用户要求新增未来服务器链接设计，参考 macOS 共享配置、SSH 添加与 Codex 文件侧栏，并登记刷新目录只处理增删改。任务 `server-cache-design-20261116` 从 `codex/cost-select-all-transitions@ab9d4b8` 接续；保留开工已有 50 份 modified、18 份 untracked 与 ignored 配置/运行态，不切换分支、不操作真实资料。
- 方案与结果：新增 `SERVER_CONNECTION_AND_CACHE_DESIGN.md`，解释 SSH 与 SFTP、SMB/外网/VPN 路线、来源身份/凭据、元数据与原文件/解析/快照分层缓存、同票家族和成本依赖更新、完整代际发布、源版本核验、离线预览和断连/崩溃恢复。登记 WS-08（P1）与 WS-09（P2），均待评估、未排版本。核对现状为已有签名差分、变化后仍调用全目录普通汇总；不将其误报为逐文件增量。
- 原型：只在已有 `workspace-sidebar-prototype.html` 增加一行脚本引用；新脚本在独立 Shadow DOM 中演示共享地址/收藏、SSH/指纹、右侧路径/文件标签/蓝色加载条、文件预览、无变化与增删改刷新、取消/断连/崩溃恢复。所有内容为合成会话状态，不联网、不输入真实凭据、不读写业务资料。远程只读投影放本机的路径例外须正式开发前评审，当前成本三件套规则不变。
- 验证：文档契约16项通过；Node语法与离线 happy-dom 交互检查通过（配置/收藏、SSH指纹前置、文件标签/蓝条、无变化解析0、1增1改1删仅解析2、离线有/无副本、取消/迟到结果、崩溃恢复、来源隔离及原模块DOM保持）。原型原文件与开工副本比对仅多一行脚本引用。最终13份相关文档的351个本地链接、文档契约复验及 `git diff --check` 通过；临时离线检查脚本与开工副本已清理。收尾 modified 52、deleted 0、untracked 20、ignored 38，含原有修改与运行态，无 Git warning。
- 未覆盖：Playwright CLI 因本机 npm 缓存权限失败，提升权限重试随后中断且核对无残留进程；内置浏览器安全策略禁止 file 协议并要求不绕过，未做真实浏览器桌面/390px、视觉与控制台验收。离线 DOM 检查不能替代这些验收。没有测试真实服务器、默认配置、正式 Windows BAT、正式入口前台拉起、系统原生弹窗、Tauri或打包产物；不运行无关产品全量回归，未提交、未推送、未合并、未打包。

### 2026-11-14 公司目录计划保护与工作区皮肤隔离（WS-02）

- 需求与起点：用户要求继续 WS-02 后端，并隔离 WS-01 中效果不满意的内置皮肤；经确认，仅暂停工作区中的 Ink Pulse、Animal Island，保留浅色 / 深色与单独经典页面。任务 `ws-02-backend-20261114` 接续 `codex/cost-select-all-transitions@ab9d4b8`；实时核对本地 / 远端 main 为 `ee0f2c2`，保留既有 WS-01 源码、文档、未跟踪 HTML 和 ignored 运行态，不切换、不提交、不推送、不合并。
- 后端：补建预览绑定根与全部目录前缀的设备 / inode 身份；同名替换、根链接、根内链接、junction 和父路径同名文件不能沿用旧计划。逐层创建空目录并在每步核对父身份，支持两个映射共用上级目录；不移动 / 改写 / 删除原文件，不切换 watch_dir。新建向导登记前复核全部已创建目录，前面目录在创建后续目录时被替换则保留现场并停止登记。
- 状态保护：公司清单拒绝布尔 schema / revision、重复身份、缺失 / 越界 / 嵌套映射与非法纳税人记录；写前先验证清单，避免共享纳税人读取抢先报错。新建任务读取校验 binding hash、精确六类计划、有限时间戳与已创建目录签名，损坏记录不展示、不确认、不覆盖，保持既有未知结果不重放语义。
- 皮肤隔离：`api/workspace.py` 维护可恢复的集中隔离名单，服务端首屏、Vue 读回与经典嵌入页的每次皮肤应用共同执行。保存皮肤与原资产保留，普通经典页面继续使用原偏好，默认浅色 / website-dark / no_skin、业务草稿和模块缓存保留。嵌入皮肤页说明暂停范围；公共脚本版本同步为 `20261114-workspace-skin-isolation-1`，前端重新构建。
- 自动化：显式 `PYTHONPATH="$PWD/src"` 的全量 Python 回归 1060 passed、16 skipped、24 subtests passed，compileall、变更 Python 文件 ruff、全部 36 项 Node 回归通过；前端类型检查、86 项组件测试、构建通过。初次子进程导入失败来自非 editable 环境 / 相对 PYTHONPATH 随子进程 cwd 改变，绝对源码路径复验通过，不以失败样本宣称产品正常。pnpm / npx 下载等待已收束，前端直接使用已安装锁定依赖的等价脚本，不升级依赖。
- 合成浏览器：独立配置 / runtime / 合成客户父目录，不启动浏览器 smoke 的 monitor、显式禁用启动同步。health 身份与当前 JS / CSS 字节和哈希一致；确认新建六类空目录并登记，默认 / 两款隔离皮肤 / 深色 / no_skin 的 1280 / 390 共十组、经典独立页面偏好、恢复不写设置、明暗切换不重建成本 frame 均通过。六个真实缓存模块逐一读回后仍不应用隔离皮肤，公共脚本版本一致，字体 / 有限动画稳定后的截图另行复看；无页面脚本异常，做账未配置账套产生五条预期 HTTP 400。截图另发现成本空快照显示 `undefined 张`，独立登记 BUG-03，不混入 WS-02 目录保护。
- 范围：37 项真实验收仍未勾选；不操作真实公司资料，不覆盖真实默认配置、正式 Windows BAT、正式入口前台拉起、系统原生选择器、Tauri 窗口、Windows / 网络盘 syscall 级并发或打包成品。自动审批服务曾因用量限制未能执行浏览器矩阵，用户要求继续后重新核对服务 / 浏览器并完成；不改变稳定 main、Release 或源码授权范围。
- 收尾：工作区 / 文档 36 项与最终文档 16 项通过，14 份修改文档的 345 个本地链接无失效，`git diff --check` 与三份前端产物逐字节重现通过。专用 Chrome 与精确归属的合成服务已退出，8766 端口释放，临时合成资料 / 截图 / 脚本 / 工具缓存已清理。现场 modified 50、deleted 0、untracked 18、ignored 38（含原有修改 / HTML 与配置、依赖、缓存、运行态和产物），无 Git warning；已登记的 BUG-02 / BUG-03 保留待办，未提交、未推送。

### 2026-11-14 临时识别与六模块缓存（WS-01 第五阶段）

- 需求与起点：用户要求继续 WS-01，沿用原聊天已确认的“Vue 内独立缓存视图复用现有页面与控制器”方案。任务 `ws-01-completion-20261114` 从 `codex/cost-select-all-transitions@ab9d4b8` 接手暂停状态，核对原执行者与后台进程已停止，保留起点 32 份 modified、13 份 untracked 与 ignored 本机状态；分支、HEAD 与 main 均未改变。
- 实现：六模块在 Vue 外壳内各自常驻 iframe，首页与临时识别为独立 Vue 视图；切换保留对象、草稿、筛选与滚动，首页标签只在首页显示。双击 `hi.` 只刷新当前标签 / 当前模块浏览上下文，详情仍保留当前对象；设置 › 关于只改分区、不丢设置草稿。批量入库沿用已有 sessionStorage 身份草稿，经工作区导航显式交接新批次。
- 页面桥：固定经典页面只在显式嵌入时注入布局 / 导航适配，原控制器继续处理业务确认与 CAS；消息核对 origin、source window 与当前 token，隐藏模块拒绝导航，加载失败 / 超时可显式重试。外壳保持单一 SSE，隐藏模块暂停 transport、保留原事件消费者，返回 onopen 重新核对，避免六个常驻连接占满 HTTP/1。皮肤同步增加代次保护，迟到响应不得覆盖新的恢复状态；资源版本为 `20261114-workspace-2`。
- 临时识别：独立页面完成选择 / 浏览器回退 / 原生拖入、队列指针与键盘排序、后台识别、历史改名 / 删除、设置、复制和 PNG / XML 预览，均复用既有后端。修正运行任务挤掉当前历史来源复核的问题，两者分别轮询；其它任务失效不清空当前有效结果。隐藏停止复核并清空未复核展示，队列与设置草稿保留；复制前重新核验来源、TSV 不含操作列，创建结果未知不自动重提，旧预览超时只取消自己的读取。侧栏改称“当前监控目录”，不再从公司归属标记推断 daemon 正在运行。
- 原生边界：Rust 固定 origin 允许列表增加 `/workspace/temporary` 及尾斜线，其他工作区模块、详情及远端继续拒绝；不扩大 Host RPC / OpenAPI 或正式投影范围。
- 自动化：类型检查、84 项 Vitest、Vite 构建、35 项经典 / 临时 / 勾选 / 新页面桥 Node 测试通过；工作区 / 临时识别 / 预览 / 原生接口及相邻经典 API 聚焦回归通过，文档契约 16 项、变更 Python 文件 ruff / compileall 通过。Rust 固定 1.85 工具链库测试 60 项、所有 target 编译及格式检查通过。源码 worker 的测试命令显式设置 `PYTHONPATH=src`；此前未安装为 editable 的虚拟环境未给子进程提供该路径，相关两项失败不作为产品通过证据。
- 合成浏览器：临时根、独立配置 / runtime、合成公司 18 份 XML 与临时 2 份 XML / 1 份两页原创 PDF；禁用启动后台同步、不启动 monitor。实取 health 身份与当前 JS / CSS 内容哈希一致；六模块实际加载、独立实例 / 当前刷新、设置未保存草稿、成本页 500px 滚动、关于分区复用、临时排序 / 模块往返 / PNG 翻页 / XML 文本 / 复制 / 改名、来源变化清空、删除历史保留原文件均通过。无页面脚本异常；未配置账套的做账页有两条预期的 accounts / aux-values HTTP 400。进一步的外观与交接检查见本节收尾补记。
- 收尾补记：实际目录勾选 18 张交接至单据批量入库队列，其他模块实例保留；外壳明暗切换同步六个缓存页面。默认 / 深色 / Ink Pulse / Animal Island / 恢复入口分别覆盖 1280 / 390，共十组，核对临时 PDF 原色、皮肤身份、iframe 尺寸与无横向溢出，恢复不改保存皮肤；两款皮肤等待实际数据和入场动画稳定后复看截图，body / main opacity 均为 1。浏览器会话中断后重新核对隔离服务身份并恢复复验。最终类型检查、84 项组件测试、工作区 / 文档 36 项、14 份修改文档的 345 个本地链接、`git diff --check` 与三份构建逐字节重现均通过。
- 清理与现场：专用 Chrome 与合成 localhost 已退出，固定端口释放，临时合成资料 / 截图 / 脚本已删除；未启动 monitor。收尾为 modified 34、deleted 0、untracked 16（含保留的原有 HTML）、ignored 38（既有配置、依赖、缓存与产物目录），无 Git warning；全部保留为未提交修改。
- 文档与范围：文件 / 接口 / 数据 / 设计原因地图、任务导航、页面 / 做账 / 宿主规则、实现状态、待办、迁移与分支记录同步；WS-01 当前登记开发范围已实现，仍待真实与平台验收，37 项真实验收保持未勾选。不覆盖真实默认配置、正式 Windows BAT、正式入口前台拉起、系统原生选择 / OS 拖入、Tauri 窗口、打包产物或真实公司 / 账套；未提交、未推送、未合并、未打包。

### 2026-11-14 Vue 工作区明暗与皮肤衔接（WS-01 第四阶段）

- 需求与起点：按已核对的 WS 任务线继续开发并及时同步进度；任务 `ws-01-appearance-20261114`，从已整合 WS 实现的 `codex/cost-select-all-transitions@ab9d4b8` 接续。保留上一轮九份文档修改、原有未跟踪 HTML 及 ignored 配置 / 运行态 / 产物，不切换主线、不推送、不操作真实公司资料。
- 实现：`/workspace/*` 复用经典页面的活动皮肤首屏注入与 `no_skin` 判断；Vue 基础样式使用同一组皮肤变量，表格、表单、侧栏、标签、操作条与明细浮层随皮肤变化，源票面保持原色。模块列增加明暗切换，先在不生效的 link 中加载 CSS，成功后才保存并替换当前样式；保存结果需匹配目标皮肤，重复点击受控，失败保留当前外观与草稿，保存响应未知不自动重试，卸载取消待处理请求 / 样式。恢复入口固定浅色且不保存设置，旧路径 / 未知深链接重定向及经典模块、侧栏返回链接保留恢复参数。
- 进度：WS-01 的 Vue 明暗 / 皮肤衔接已实现；临时识别入口和六个经典模块的 Vue 迁移 / 缓存仍待开发。其他 WS 状态不变，37 项真实验收仍全部未勾选；本阶段合成检查不能转记为真实资料或平台成品通过。
- 浏览器发现并修正：Ink Pulse / Animal Island 的全局 `overflow-x:hidden` 形成额外纵向滚动容器，长列表使 sticky 模块列 / 侧栏滚出视口；工作区以 html/body 的 `overflow-x:clip` 保留装饰裁剪并恢复吸顶，复跑桌面长列表实际位置检查。Vue Router 对重复查询值保留数组，恢复判断取最后一项，与服务端一致。
- 自动化：工作区 / 页面 API、前端静态与文档契约合计 123 passed；前端类型检查、69 项 Vitest、构建及三份产物逐字节重建比对通过；经典相邻交互 Node 16 passed，修改的 Python 文件 ruff 与 compileall、文档本地链接及 `git diff --check` 通过。pnpm 全局 shim 版本切换无输出后已停止，前端采用现有锁定依赖目录的同名可执行文件运行 package scripts，不安装或更新依赖。
- 合成浏览器：独立临时配置 / 公司目录、18 份 XML 与 1 份原创 PDF；当前 localhost health 的目录身份及两份带 `?v=` 资源与本轮构建字节一致。默认 / website-dark / Ink Pulse / Animal Island 与恢复入口各覆盖 1280 / 390，共 10 组，检查布局、控制台、目录勾选、PDF 面板与票面原色、关闭保留选择、桌面长列表吸顶；另验证未保存公司表单与实例保留、CSS 加载失败不保存 / 选择保留及显式重试、经典首页共用保存结果。无页面异常，唯一控制台网络错误来自主动阻断 CSS 的负向样本；本样本禁用启动后台同步且不启动 monitor，不作为 ready / 监控验收。
- 未覆盖：真实默认配置、正式 Windows BAT、浏览器正式入口前台拉起、系统原生选择器、Tauri 窗口与打包产物、真实资料 / 账套验收。本轮不改变发布状态。
- 收尾：12 份修改文档的 322 个本地链接与文档契约复验通过，37 项真实验收保持未勾选；临时 Chrome、localhost 服务、合成资料 / 脚本 / 截图已清理，固定端口已释放。工作区保留未提交源码与构建产物、前轮文档及原有未跟踪 / ignored 文件；既有 BUG-02 静态门禁待办不在本阶段修复范围。

### 2026-11-13 核对 WS 任务线与待真实验收清单

- 需求与起点：核对当前 WS-01—07 的实现、开发余项及待验收 list；任务 `ws-status-acceptance-audit-20261113`，起点为主目录 `codex/cost-select-all-transitions@ab9d4b8`。开工无 tracked 修改，已有未跟踪 HTML 与 ignored 配置 / 运行态 / 构建产物保留。
- 现场核对：本地成本线与 WS 独立 worktree 的分支同指 `ab9d4b8`；本地 main、origin/main 和远端实际 main 同指 `ee0f2c2`，开发线领先 69 个提交。只读核对 Git、源码、测试定义与最新文档，不启动产品或操作真实公司资料。
- 结果与方案：实现状态新增七条 WS 当前汇总，区分已实现、仍待开发与限制；WS-02 当前登记范围已实现待真实 / 平台验收，其他条目保留开发余项。修正页面规则“页面不提供导出”、库存按规格计算、往来部分 / 预付分摊等过时表述，库存采用品类 + 单位、规格细分，往来剩余流水单列不分摊；明确既有捷锐实测不替代当前 WS 页面导出验收。原型已在当前分支，但生成器逐项对照仍未完成；Vue 明暗 / 皮肤衔接列入 WS-01 余项。
- 清单：原 32 项补入非活动目录保护、跨页筛选勾选、冲突 / 损坏保护、界面缓存与外观、真实默认配置与入口一致性，共 37 项（12 / 18 / 7），均未勾选；“只读轮”允许写本机公司登记，但不改业务资料。分支记录、架构入口与任务导航同步指向当前状态和三轮清单，历史阶段记录继续保留。
- 验证：文档契约 `tests/test_development_documentation.py` 16 passed；本轮修改文档的本地 Markdown 链接检查与 `git diff --check` 通过，清单计数为 37 待验 / 0 已验；无新增工程文件，不运行无关产品回归。
- 未覆盖：未新增真实默认配置、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Tauri 成品、打包产物或真实资料 / 账套验收结论；已有 BUG-02 静态门禁问题仍保留待办，本轮未修复、未复跑 ruff。只修改文档，未提交、未推送、未合并、未打包。

### 2026-11-13 公司资料夹选择、新建工作区向导与目录映射编辑（WS-02）

- 需求与起点：用户要求继续原 WS 规划，从 `codex/ws-07-company-registry` 的 `c1ed677` 接续。已有依赖软链与主目录未跟踪 HTML 保留；本轮仅合成资料开发验收，不推送、不改 main、不写真实公司资料。
- 原生选择：新增空请求 `POST /api/v1/companies/pick-directory` 与 Python / Rust 固定 `pick_company_directory`，沿用同源、host 精确 origin / ownership 与原生异步主线程调度；选择只返回待登记路径，取消保留草稿，手工改过或关闭后的迟到结果不覆盖，重复点击受控，Tk 子进程超时与 private host 错误均返回脱敏 503。
- 从零向导：已有上级文件夹 + 新公司文件夹名 + 六类相对映射 → 计划 → 显式确认 → 创建空目录并登记。`services/company_setup.py` 是公司清单的伴随用例，共用 RLock、revision CAS 和路径校验；计划与逐步观察存于 `runtime/local_state/company-setups/`，首次持久化排他执行标记后才 mkdir。禁止覆盖、链接逃逸、注册根重复 / 嵌套和与当前监控目录重叠；父目录身份变化、清单变化或计划超过 5 分钟须重做计划。失败保留已创建空目录；登记写入后事件异常按未知结果披露，不自动重试。确认响应丢失只 GET 执行记录。
- 映射编辑：公司设置可编辑六类相对路径，只改变资料类型指向，不移动、改名或补建文件；修改后已打开目录、账簿、比较与侧栏项目缓存按稳定来源键更新，旧请求不能覆盖新来源。未保存项目归属保留并阻止按过期资料保存；工资手工草稿保留，普通公司对象刷新不重载。
- 验证：新增 17 项合成 API 用例通过；Python 全量 1021 passed / 16 skipped / 24 subtests（5 条既有 PyMuPDF / SWIG 弃用警告），compileall 通过；前端 typecheck、Vitest 55 项、build 与构建产物契约通过，文档 / 前端契约 21 项及 305 个本地链接通过。临时 Rust 1.85 工具链组件经官方 SHA-256 校验，macOS 原生 cargo test 103 项、fmt 与 clippy `-D warnings` 通过。Chrome 合成资料在 1280 / 390 宽度验证计划不创建、确认失联后只读查询（仅一次确认 POST）、六类空目录、中文空格路径、监控不变、映射不移动文件与旧路径 / 确认清除；无页面异常，唯一网络控制台错误来自主动模拟确认响应丢失。系统目录选择使用 mock，未打开原生弹窗；小屏公司标签改为横向滚动。全库 ruff 命中起点已有的 `bank/jierui.py` F821（已登记 BUG-02）；本轮变更 Python 文件 ruff 通过。
- 未覆盖：真实公司、系统原生选择器弹窗、真实默认配置、正式 Windows BAT、浏览器前台拉起、网络盘 / Windows 文件系统、经典皮肤 / no_skin 恢复入口、Tauri 成品与打包产物。源文件与活动监控目录未改动。

### 2026-11-13 目录发票列表补齐原票预览、开票时间排序与分类配色（WS-01 第三阶段）

- 需求与起点：用户要求按原 WS 规划逐步推进，先补齐 WS-01 目录列表。在 `codex/ws-07-company-registry` 的 `131bb33` 上继续；既有依赖软链与主目录未跟踪 HTML 保留。本轮只本地开发，不推送、不改 main，不操作真实公司资料。
- 方案：勾选操作条增加“预览”，把完整 `target_id + invoice_key + source_path` 队列交给现有 `SourcePreview` 与 `preview-jobs`，同票多格式逐文件保留；名称窗口每组最多 100 项，可翻组、按序号跳转完整队列，当前文件缩略图每组最多 12 页。比较原票与目录预览共用一套续租、重建、PDF 翻页与 XML 纯文本显示。
- 开票时间表头接入已有后端 `date_sort=asc/desc`，先全量排序再分页，标签筛选和全选沿用相同排序参数；页面显示后端的发票大类与特定业务样式，PDF / OFD / XML 与专票 / 普票沿用经典配色，不新增提取或金额算法。
- 浏览器发现并修正：最后一页按钮禁用后焦点可能移到 body，原先仅面板内的 Esc 监听失效；改为只对当前可见面板监听窗口 Esc，隐藏缓存标签不消费按键。桌面目录宽表改为容器内滚动，保留购销方最小宽度。
- 相邻保护：异步列表、全选与 XML 正文使用代际校验；关闭面板取消 XML 读取与续租；持久失效的 XML 只立即重建一次。公司监控身份变化时重新读取已打开目录并清除旧勾选和预览；普通公司对象刷新不重载列表。
- 验证：前端类型检查、Vitest 48 项与 Vite 构建通过；新增测试覆盖同票多格式、101 个文件的完整队列、XML 安全显示与迟到正文、持续过期的有界恢复、排序迟到响应与监控切换。最终全量 pytest：1004 passed、16 skipped、24 subtests passed，仅第三方 SWIG 弃用警告；compileall 通过（含活动 / 只读目录先排序再分页的两组 API 用例）。专用 Chrome（无头 CDP）在合成公司上核对正倒序、3 条源记录按 2 张票计金额但原票保留 3 个文件、PDF 两页翻页与 Esc 关闭、非监控目录无勾选；1280 / 390 均 scrollX=0、页面宽度不超视口，控制台无错误。
- 未覆盖：真实默认业务资料、真实目录长时预览、经典皮肤 / no_skin 恢复入口（Vue 外壳原本不注入经典皮肤）、正式 Windows BAT、浏览器前台拉起、系统原生选择器、Tauri 与打包成品。待办保留临时识别入口与未迁移模块的页面缓存，后续按 WS-02 等条目继续。

### 2026-11-13 通用凭证导出配置：捷锐、柠檬云、用友与自定义模板（BK-01 / WS-05 第四阶段）

- 需求：用户 2026-11-13 第 5 项：保留捷锐（在用），其他如柠檬云、金蝶、用友可能有自己的导入格式，查一下网络上是否存在通用格式。起点 `52e5d96`。
- 调研结论（来源见 BK-01 与本节）：柠檬云、金蝶精斗云 / 云星辰 / KIS、用友好会计 / T+ / T3 / U8 都能导入凭证，但模板都是私有格式，官方页面大多只说“下载模板”；只有用友 T3/U8“总账工具·凭证引入”有完整字段规范（经销商转载的手册）。GB/T 24589（2024 版已代替 2010 版）与 GB/T 19581 是从会计软件导出给审计用的标准，没有找到记账软件支持导入，不作为目标。各家共有的列只有 日期 / 凭证字 / 凭证号 / 摘要 / 科目编码 / 借 / 贷。
- 方案：
  - 新增 `bank/export_profiles.py`：内部统一凭证模型（凭证头 + 分录 + 辅助核算列表）与声明式导出配置；内置捷锐（已实测）、柠檬云（35 列，表头直接读自第三方仓库的 `凭证导入模板.xls`）、用友 T3/U8 文本（首行 `填制凭证,V800`，GBK，21 个按位置字段）；`profile_from_template` 读用户上传的空白模板表头，按同义词对列，对不上的列留空并报告，缺必需列不可用。
  - `jierui.export` 只把写文件一步换成配置，整月拦截、重编号、`after`、重复导出跳过（不分格式）、习惯学习不变；默认仍为捷锐并沿用 `凭证/导入/模板原件.xlsx` 列序。
  - 页面：`GET .../voucher-drafts` 返回 `formats[]`（含 `做账草稿/导出模板/` 里的自定义模板），导出面板增加“导出格式”，实验与自定义格式显示醒目提示，缺列模板禁用；导出请求带 `format`。
  - 校验提示“请确认捷锐已建档”改为“请确认账套里已建档”。
- 实现中发现并修正：黄金测试最初在测试里用 `git show` 读取改造前代码，CI 浅克隆时没有那段历史，且文档契约不允许在地图里写提交号；改为把改造前代码的输出冻结成测试夹具。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、任务导航、设计原因地图、未来工作总览 BK-01 / WS-05、实现状态、待真实验收清单。
- 验证：新增 `tests/test_export_profiles.py` 6 项（捷锐黄金测试：改造前的导出代码对同一合成审核表的输出冻结为 `tests/fixtures/jierui_export_golden.json`，现代码导出的单元格与工作表名与之完全一致，带账套模板时列序跟随模板；柠檬云 35 列、“记-1 / 记-2”、行号、借贷本币、供应商只有名称不编造编码；用友 V800 首行、GBK、21 字段、供应商编码留空；已导出凭证换柠檬云格式仍跳过；上传模板对列与未对上列、缺列报告；页面导出选择自定义模板、拒绝缺列 / 越界 / 未知格式）；`tests/test_bank_vouchers.py`、`tests/test_company_vouchers.py` 不变；前端 Vitest 43 项（导出用例增加格式选项、缺列禁用、实验提示与请求体 `format`）、`vue-tsc`、`vite build`；全量 pytest 1002 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成甲公司审核表）：导出面板选柠檬云显示“实验格式，未经实际导入验证”，导出写出 `柠檬云导入_2026-06_*.xlsx`；随后选用友，同一凭证显示“已导出过，跳过”；390 宽无横向滚动、无控制台错误。
- 未覆盖：任何非捷锐格式的实际导入（柠檬云、用友均未在真实软件里导入核对，已列入待真实验收清单）；金蝶 / 好会计 / T+ 内置配置（需要用户账套下载的真实模板）；辅助核算编码（目前只有供应商名称）；页面与默认导出仍以捷锐命名；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 工资社保页面（WS-05 第三阶段）

- 需求：用户 2026-11-13 第 4 项：工资社保页面按真实报表排版，真人信息脱敏；导入电子税务局社保明细导出，没有 Excel 时 PDF / 图片也要支持——随后决定本轮先不支持图片、页面默认脱敏可临时显示全名。版面参照用户资料夹里的电子税务局截图（费款所属期 / 险种 / 应缴费额合计 + 单位部分 / 个人部分各 5 列）。起点 `b10a16d`（中途暂停一次，恢复后先修了 PDF 分支未初始化的变量）。
- 方案：
  - 新增 `services/company_payroll.py`：Excel 按两行表头名称识别列，另读人员明细表；PDF 只读文字层，按 token 流识别“所属期 + 险种 + 恰好 11 个数值”（整行或逐格排版都能读）；图片列为不识别并提示；`--` 为空。后端核对“单位 + 个人 = 合计”与单人时“基数 × 费率 = 应缴”。确认某月后由后端从险种行求和，写入 `申报数据.json` 的 `社保明细.{月份}`（单位部分、个人部分、来源、险种明细），带 SHA-256 revision 原子重写并保留其他键。人员姓名、证件号默认脱敏，`reveal=true` 才返回原值。
  - 路由 `GET/PUT /api/v1/companies/{id}/payroll`；前端新增 `CompanyPayroll.vue`，公司标签增加“工资社保”分区。
- 实现中发现并修正：费率最初显示为“16.00%”“0.500%”，改为与原表一致的“16%”“0.5%”；单位部分 / 个人部分分组表头未居中（`.grid th` 的左对齐优先级更高），提高选择器优先级。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、任务导航、设计原因地图、未来工作总览 WS-05 / OCR-01、实现状态、待真实验收清单。
- 验证：新增 `tests/test_company_payroll.py` 10 项（按截图数字合成的 Excel：五个险种、单位 1,282.57 / 个人 529.96 / 合计 1,812.53、核对成立；合计与费率改错后 3 条核对不成立；整行与逐格两种文字层 PDF；图片不识别；脱敏与显示原值；确认写入保留其他键、revision 冲突、手工录入与删除月份；无或损坏 申报数据.json 拒绝且不覆盖；确认后在页面重新生成的草稿 8 月有社保计提、贷方合计 1,812.53；API 读取不写文件）；前端 Vitest 43 项（新增“版面、核对标红、图片提示、脱敏与显示原值、确认请求体”）、`vue-tsc`、`vite build`；全量 pytest 996 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成测试公司工资社保目录：8 月 Excel 含人员明细、9 月 PNG）：显示 2026-08 五个险种与“单位 1,282.57 · 个人 529.96 · 合计 1,812.53”，PNG 提示需 OCR，人员显示“张*三 / 320***********1234”；确认后写入 申报数据.json 并标“已确认”；390 宽无横向滚动、无控制台错误。
- 未覆盖：用户真实的电子税务局 Excel / PDF 导出（版式以截图为准，拿到真实导出后才能标为已验证，已列入待真实验收清单）；图片识别；工资表读取与工资计提凭证；多人参保时的逐人费率核对；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 属期文件夹核对与移动放错的文件（WS-05 第二阶段）

- 需求：用户 2026-11-13：“文件属期如果放错了要调整，需要真的移动文件”；目标文件夹从已有属期文件夹选，缺少时新建 `YYYY-MM`。起点 `55cc30b`。用户资料夹里按属期分文件夹的是进项抵扣（`5月`、`6月`）与已抵扣项（`10月份属期抵扣项`），发票目录是平铺的。
- 方案：
  - 新增 `services/source_move.py`：`folder_period` 解析文件夹名（“2026-07”“2026年7月”“6月”“10月份属期抵扣项”）只作提示；`period_folder_check` 对进项抵扣（`.xlsx`，读税款所属期）与银行流水（`.pdf`，逐文件识别对账单，单月才算单一属期）列出可能放错、未放在属期文件夹与无单一属期的文件，并给出建议目标。`SourceMoveService` 照删除流程：计划 → 确认 → 逐文件签名复核、fsync 意图、无覆盖改名、记录结果；重放只返回记录；目标只能是同一子目录下已有属期文件夹或新建 `YYYY-MM`；拒绝链接、越界、同名覆盖与监控目录重叠。
  - 路由 `GET .../period-folders`、`POST .../period-folders/moves`、`POST .../moves/{job_id}/confirm`、`GET .../moves/{job_id}`；只返回子目录内相对路径。
  - 前端新增 `PeriodFolderCheck.vue`，挂在进项抵扣与银行流水的目录标签。
- 实现中发现并修正：对账单只记录文件名，按名字在子目录里找回文件可能找到另一个属期文件夹里的同名文件；改为逐个文件解析。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、任务导航、设计原因地图、未来工作总览 WS-05、实现状态、待真实验收清单。
- 验证：新增 `tests/test_source_move.py` 5 项（文件夹名解析、按内容判定放错 / 未归属 / 空导出不推断、确认后新建 2026-07 并移动且重放不重做、同名 / 越界 / 非法新文件夹 / 已在目标 / 链接拒绝、计划后文件变化不移动、与监控目录重叠拒绝、API 核对 / 计划不写公司资料夹 / 确认 / 读日志 / 不返回绝对路径）；前端 Vitest 42 项（新增“属期文件夹核对：默认只列放错、建议目标、计划后才确认、确认响应丢失只读日志”）、`vue-tsc`、`vite build`；全量 pytest 986 passed、16 skipped（首次运行因接口流程表里的路由写了缩写被文档契约测试拦下，改为完整路径）。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成甲公司进项抵扣：`5月/` 一份 202605、`6月/` 一份 202607）：核对列出 `6月/用途确认信息 (1).xlsx` 可能放错，选“2026-07（建议）（新建）”，计划显示“→ 2026-07/（新建文件夹）”，确认后文件实际移到 `进项抵扣/2026-07/`，重新核对没有放错的文件；390 宽无横向滚动、无控制台错误。
- 未覆盖：真实资料夹上的移动（须当回合授权、先在副本上做，已列入待真实验收清单）；银行流水真实对账单的逐文件识别耗时；发票目录与监控目录内的移动（未开放）；Windows 改名语义与网络盘；Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 原始单据同期 / 跨期与改记入期（WS-05 第二阶段）

- 需求：用户 2026-11-13 第 2 项：原始凭证标注同期 / 跨期，可把单据“发送到”另一个属期、界面立即显示；凭证属期是生成数据，只更正数据（放错属期文件夹的源文件移动另做）。起点 `52f8e29`。
- 方案：
  - `bank/vouchers.py`：新增 `load_period_overrides`（`做账草稿/记入期调整.json`，损坏即报错），`build_drafts` 在 `book_month` 处优先采用调整（调到范围外的不进本表、不再按读回判断已入账），`carry_note` 写明“人工调整记入期”；首月期初应有数量扣除所有范围前开票、记入本草稿的票（含销项，带正负号）。`prepare` 读取调整，命令行与页面一致。抵扣月份逻辑不变。
  - `company_vouchers`：记入期调整的带 revision 读写（损坏拒绝覆盖）、生成参数记录（`草稿生成参数.json`）、`rebook_invoice`（保存调整后按记住的参数重新生成，命令行生成的表按文件名起止月与默认值）；`read_draft` 为发票凭证给出原始单据、开票日期、同期 / 跨期与人工调整，银行凭证标为不可单独调整。新路由 `POST .../voucher-drafts/{name}/rebook`。
  - `CompanyVouchers.vue`：凭证下列出原始单据与同期 / 跨期标签（跨期悬停说明常见原因），“改记入期”选月份与原因后保存并重新生成，可“恢复为开票月”；表外月份提示到该月草稿查看。
- 实现中发现并修正：`vouchers.py` 原来没有导入 `re`，调整文件存在时读取会报错（只有文件存在的路径才会触发，测试覆盖后发现）。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、设计原因地图、未来工作总览 WS-05、实现状态、待真实验收清单。
- 验证：`tests/test_company_voucher_generate.py` 新增“改记入期”1 项（7 月进项改记 8 月后凭证移到 8 月并标跨期与原因、命令行读同一调整得到同样结果、撤销回 7 月、调到 6 月离开本表、revision 冲突 / 未来月份 / 未知发票拒绝、调整文件损坏时读取提示且改记与生成都拒绝）；`tests/test_bank_vouchers.py`、`tests/test_company_inventory.py` 原有期初更正用例不变；前端 Vitest 41 项（新增“改记入期请求体、重新生成后显示跨期与原因、银行凭证不可调”）、`vue-tsc`、`vite build`；全量 pytest 981 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成测试公司）：进项发票凭证显示“开票 2026-07-10 · 同期”，改记入 2026-08 后凭证变为 2026-08 第 001 号、标“跨期”“人工调整记入期（次月到票）”，`记入期调整.json` 写入一条；390 宽无横向滚动、无控制台错误。
- 未覆盖：真实公司资料夹（含已入账读回月份的票改记入期）的增值税、库存与月度核对结果；银行流水单笔改记入期（不提供）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 页面生成凭证草稿、重新生成沿用审核（WS-05 第二阶段）

- 需求：用户 2026-11-13 决定第 1 项“可选年份、月份，时间按统一记月末”，重新生成时“备份旧表并沿用未变凭证的审核”。起点 `d813465`。
- 方案：
  - `company_vouchers.generate_draft` 与 `POST /api/v1/companies/{id}/voucher-drafts`：直接调用 `bank.vouchers.prepare` 与 `jierui.write_review_xlsx`（含命令行说明页），输入为起止年月（不能是未来月份）、是否统一记月末（默认是），以及从 `做账草稿/账套读回/` 列出的序时账与科目表快照中勾选的文件；缺 申报数据.json 时与命令行一样写出模板并提示补填。
  - 覆盖已有同期表前先复制到 `做账草稿/历史/`；新旧凭证按来源配对（发票号；银行流水 row_id + 借方合计；其他按来源 + 月份 + 科目集合），导出签名不变的沿用“通过 / 不导入”，改过的摘要在行数一致时沿用，内容变了的列入需重新审核；返回沿用、需重审、新增与消失清单。与导出共用进程内锁。
  - `GET .../voucher-drafts` 增加 `inputs`；`CompanyVouchers.vue` 增加“生成草稿…”面板与结果清单，空状态改为提示点“生成草稿…”。
- 实现中发现并修正：需重新审核清单最初显示新生成的默认摘要，用户认不出是哪张；改为显示沿用的人工摘要。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、任务导航、设计原因地图、未来工作总览 WS-05、实现状态、待真实验收清单。
- 验证：新增 `tests/test_company_voucher_generate.py` 3 项（页面生成与 `voucher_cli draft` 各工作表逐单元格一致；重新生成先备份、沿用 2 张审核与 1 行摘要，改发票后该张列入重审、摘要保留；读回文件越界、月份不合法、未确认都拒绝且不写表，缺发票明细时生成失败提示）；前端 Vitest 40 项（新增“生成面板默认值与请求体、结果清单、打开新表”）、`vue-tsc`、`vite build`；全量 pytest 980 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，用银行凭证测试同一合成公司：对账单 PDF、科目表、发票明细）：空状态点“生成草稿…”生成 2026-07—08，9 张凭证并写出申报数据模板；审核通过 1 张后重新生成，旧表备份到 `做账草稿/历史/`，沿用审核 1 张；390 宽无横向滚动、无控制台错误。
- 未覆盖：真实公司资料夹的页面生成与命令行结果对照（已列入待真实验收清单）；大目录生成耗时（请求超时 180 秒）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 凭证草稿页面导出（WS-05 第二阶段 B）

- 需求：WS-05 方案“只导出审核通过的”；此前页面只能审核，导出要回命令行 `voucher_cli export`。起点 `6828bb9`。
- 方案：
  - `company_vouchers.export_draft` 与 `POST /api/v1/companies/{id}/voucher-drafts/{name}/export`：须 `confirm: true`、制单人（1—20 字，捷锐实测必填）与可选 `after`（各月账套已用到的号，0—999 整数）；缺科目表 409；在进程内导出锁里复核文件 revision，再直接调用 `jierui.export`（输入与命令行一致：`凭证/科目表.json`、`辅助核算档案.json`、`凭证/导入/模板原件.xlsx`，输出到 `做账草稿/`）。不开放“允许再次导出”；返回只含文件名。
  - `CompanyVouchers.vue`：“导出已审核…”在有未保存改动或没有通过的凭证时禁用；面板列出各月通过张数、账套已用到的号输入、必填制单人，“确认导出”后显示写出的文件、整月未导出的月份与原因、已导出过而跳过的凭证与提醒。
- 实现中发现并修正：`v-model` 在 number 输入框上给出数字，按字符串 `trim()` 时报错、导出请求没有发出（前端测试发现），改为同时接受数字与空字符串。
- 文档：做账规则（页面导出）、页面规则、接口流程（新路由）、文件地图、设计原因地图、未来工作总览 WS-05、实现状态、待真实验收清单。
- 验证：`tests/test_company_vouchers.py` 8 项（新增“未确认 / 缺制单人 / after 越界 / revision 过期都拒绝且不写文件；只导出通过的 001，凭证号接在 005 之后为 006、制单人写入；第二次导出跳过；通过但不合格时整月不写”）与 `tests/test_bank_vouchers.py`；前端 Vitest 39 项（新增“有改动时禁用、未填制单人不能确认、请求体、结果显示文件与整月未导出”）、`vue-tsc`、`vite build`；全量 pytest 977 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成审核表）：面板列出 2026-06 通过 1 张，填制单人后导出 1 张、写出 `做账草稿/捷锐导入_2026-06_*.xlsx`，再次导出显示“已导出过，跳过”；390 宽无横向滚动、无控制台错误。
- 未覆盖：真实审核表的页面导出与捷锐实际导入（账套操作需当回合授权，已列入待真实验收清单）；带真实 `模板原件.xlsx` 的列顺序；导出响应丢失后的页面提示（重复点击只会跳过已导出的）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 凭证草稿改所属期与记账日期、显示核对表（WS-05 第二阶段 A）

- 需求：WS 线按 6 → 4 → 5 继续。WS-05 方案要求每张凭证可改所属期（整张移到该月）与记账日期（必须落在所属期内，否则不能审核），所属期不能选未来月份；库存等核对结果在页面可见。起点 `19377c6`。税费测算属税务工作台，CLAUDE.md 规定仍为设计阶段，本轮不做。
- 方案：
  - `company_vouchers.save_draft` 增加 `move_month`、`date`：未来月份与格式错误 422；移到另一个月的凭证接在目标月已占用号（不含本次移出的，含本次先移入的）之后重新编号，只改日期时保留原号；移动或改日期视同改动，原“通过”须重新审核；日期不在所属期内可以保存，审核时由导出的 `validate` 拦截。返回 `moved[]`。
  - `read_draft` 返回草稿的只读核对表（月度核对、银行对账、库存核对、待补科目，每表最多 2000 行）与 `current_month`。
  - `CompanyVouchers.vue`：每张凭证头部有所属期（月份输入，最大为当前月）与记账日期（限在所属期内）；改月份时日期若不在新月份内改为该月最后一天并提示“保存后移到…重新编号”；保存提示列出移动前后的凭证号；核对表折叠只读显示。
- 实现中发现并修正：旧测试的保存响应没有 `moved`，页面读取时报错——改为缺省按空列表处理。
- 文档：做账规则、页面规则、接口流程、数据与算法、文件地图、设计原因地图、未来工作总览 WS-05、实现状态、待真实验收清单。
- 验证：`tests/test_company_vouchers.py` 7 项（新增“移月重编号、移回撞号改为 002 并清空审核、只改日期保留原号、日期不在所属期不能审核、未来月份与格式错误拒绝”“核对表只读返回”）；前端 Vitest 38 项（新增“改所属期后日期到月末、请求体、重新编号提示、核对表”）、`vue-tsc`、`vite build`；全量 pytest 976 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成审核表）：把 2026-06 第 002 号的所属期改为 2026-05，日期自动变为 2026-05-31，保存后提示“2026-06 第 002 号 → 2026-05 第 001 号”，列表变为 2026-06 第 001 号与 2026-05 第 001 号；390 宽无横向滚动、无控制台错误。
- 未覆盖：真实审核表移月后再跑 `voucher_cli export` 的编号与整月拦截（已列入待真实验收清单）；移入凭证在目标月内的排列（按表内行位置，不按日期重排）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 比较记录查看原票（WS-04）

- 需求：WS-04 剩余“缩略图与大图，复用现有预览管道，只对监控目录开放”。起点 `7d6389a`。
- 方案：
  - 后端 `company_views.py::_attach_previews`：比较（四种关系按 `RECORD_SIDES` 确定每边目录）与同号检查返回 `records` 后，只给监控目录、列表非临时结果的发票记录附 `preview: {target_id, items}`，身份取自该目录当前首页列表、按 `selection_family_key` 合并同票各格式（最多 100 条）；其它目录、银行流水与清单行不带。
  - 前端新增 `SourcePreview.vue`：并排记录里带 `preview` 的行显示“原票”，打开右侧面板，原样提交 `POST /api/v1/invoices/preview-jobs`；缩略图条（最多 12 页）+ 大图、翻页，多个文件可切换，XML 显示受限纯文本；打开期间按闲置期限的 1/5（30—120 秒）续租，`404/410` 时重建并保留当前文件与页码，关闭即停止；图片出错只重建一次，仍失败提示到经典首页预览。
- 实现中发现并修正：390 宽浏览器验收发现勾稽与同号检查标签可横向滚动 60px。逐元素测量定位到新加的“原票”列表头 `.sr-only`：窄屏下 `.grid` 改为可横向滚动的块，但不是定位容器，绝对定位的 `.sr-only` 逃出表格撑宽整页。为 `.grid` 加 `position: relative` 后各标签均为 390、无横向滚动。上一提交（同号检查）的 390 验收是在另一标签上测的，没有发现这一问题。
- 文档：页面规则（原票、窄屏 `.grid` 定位）、接口流程（`records[].preview` 与 `/workspace` 消费 `preview-jobs`）、文件地图、设计原因地图、未来工作总览 WS-04、实现状态、待真实验收清单。
- 验证：后端新增 `test_only_the_monitored_folders_records_open_the_original_invoice`（附带身份可真实创建预览作业、只读目录不带、勾稽另一侧不带）；前端 Vitest 37 项（新增“原票：只对带 preview 的行、请求体原样、缩略图与翻页、410 后重建并保留第 2 页、关闭后不再续租”）、`vue-tsc`、`vite build`；全量 pytest 974 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成甲公司成本发票为监控目录，内含同号的合成两页 PDF 与 XML）：同号检查中只有成本发票一侧有“原票”，面板列出 PDF 与 XML 两个文件，PDF 大图 1240×875、两张缩略图均已渲染，Esc 关闭；1280 与 390 宽无横向滚动、无控制台错误。
- 未覆盖：真实 PDF / OFD 票面（OFD 渲染组件未在本轮验收）；面板打开超过 15 分钟的真实续租与过期重建（只由前端测试的假定时器验证）；非监控目录的原票（按规则不开放）；银行回单缩略图；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 同号检查：没有勾稽关系的发票目录，可跨两家公司（WS-04）

- 需求：WS-04 剩余“不同公司或没有勾稽字段的两类资料不做关联，只并排展示并检查同号发票；纳税人身份不同时提示税额不可直接比较”。起点 `5cf999b`。
- 方案：
  - 新增 `services/company_same_number.py::build_same_number_check`：每边按 `selection_family_key` 合并（同票多格式只算一张），按发票号码取交集；两家公司且一方是开具发票、另一方是成本发票 / 费用报销时判为“双方同一张票”（同一笔交易的两端），其余同号判为“疑似重复”；两边价税合计或销售方不同单独标出；无号码的单列不参与；校验从原始记录复算“有号码 + 无号码 = 合并后张数”。
  - `company_views.py::same_number` 与 `GET /api/v1/companies/{id}/same-number?a=&b=&b_company=`：只读两边上次投影；非发票目录、同一目录、同一公司有勾稽关系的组合都拒绝（422）；投影过期、两家纳税人身份不同时提示。
  - 前端：侧栏“与已选项进行比较”对没有勾稽关系的两个发票目录（含另一家公司的）开放，打开“同号检查”标签（`CompanySameNumber.vue`，复用并排原始记录与明细抽屉）；其它组合仍禁用并说明原因。标签 id 只在有第二个对象时追加字段，原有标签不变；任一公司删除时关闭相关标签。
- 实现中发现并修正：浏览器验收时跨公司那一行因两边销售方不同被标红，但只有打开明细才看得出原因，改为在判断列直接写“金额不同 / 销售方不同”。
- 文档：接口流程（新路由与 `/workspace` 消费）、文件地图、数据与算法（同号检查）、页面规则（侧栏比较）、做账规则（同号检查）、任务导航、设计原因地图、未来工作总览 WS-04、实现状态、待真实验收清单。
- 验证：`tests/test_company_same_number.py` 3 项（多格式只算一张、无号码单列、金额与销售方不同、疑似重复与跨公司同一张票、两家都取得仍为疑似重复、API 同一公司 / 跨公司 / 拒绝组合 / 不写文件）；前端 Vitest 36 项（更新“拒绝无关组合”，新增“跨公司同号检查并点号码看明细”）、`vue-tsc`、`vite build`；全量 pytest 973 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成甲、乙两家公司）：甲公司成本发票 ⇄ 费用报销列出 1 张疑似重复（金额不同标红，明细抽屉给出两边摘要与提示）；甲公司成本发票 ⇄ 乙公司开具发票列出 1 张双方同一张票；390 宽无横向溢出、无控制台错误。
- 未覆盖：真实公司资料夹（已列入待真实验收清单第一轮）；大目录（上万张）的响应时间；缩略图与大图；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 多行批量打标签（WS-06）

- 需求：用户定 WS 线按 6 → 4 → 5 顺序继续。WS-06 剩余“对已勾选的多行切换标签”。起点 `fc3f9b8`。
- 方案（只改前端，后端接口不变）：
  - `DirectoryInvoices.vue`：勾选另存每行的发票号码（只供批量打标签，传给选择条前剥掉）；在多行勾选中的某行右键 / Shift+F10 时进入批量菜单，按发票号码去重（同票多格式共用标签），没有号码的行跳过并写明张数；打开时 `GET /api/v1/companies/{id}/invoice-tags` 读当前标记（勾选可能跨页），每个标签按全部 / 部分 / 没有显示勾选 / 半选（`aria-checked="mixed"`）/ 不勾；点击时全部已有则全部移除，否则只给缺的补上，一次 `PUT` 带 revision，冲突时重新读取并提示再点一次，不自动重放；保存后按响应里的全部标记局部更新本页色点，不重载列表、保留勾选。不在勾选里的行仍只给自己打标签。
- 文档：页面规则（标签菜单）、文件地图、设计原因地图、未来工作总览 WS-06。
- 验证：前端 Vitest 35 项（新增“勾选中的行批量打标签：跨格式同号去重、无号码跳过、半选、只补缺的、全部移除、不重载、选择条请求体不变、未勾选行只打自己”）、`vue-tsc`、`vite build`；全量 pytest 970 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成公司两张成本发票）：勾选本页后右键，菜单为“已勾选 2 张，2 个发票号码”，勾“待核实”后两行出现色点，再取消后色点消失；390 宽无横向溢出、无控制台错误。
- 未覆盖：真实公司资料夹上的批量打标签（已列入[待真实验收清单](docs/MIGRATION_GAP_CHECKLIST.md#ws-real-acceptance)第二轮）；上千张勾选的保存耗时；旧首页列表；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 登记 WS 线待真实验收清单

- 需求：用户要求把 WS 线各项“没测过的实际验证”写入文档，后续逐步测试。
- 方案：在 `docs/MIGRATION_GAP_CHECKLIST.md` 顶部新增“多公司工作区（WS 线）待真实验收”，把 2026-11-10 起各 WS 小节“未覆盖”中的实测项按三轮排列：真实公司资料夹只读、写入类操作（先用副本）、平台入口与产物；测完逐项勾选并回写 CHANGELOG。写入、导出与账套操作仍需当回合授权。
- 验证：`tests/test_development_documentation.py`、`git diff --check`。纯文档，未运行产品回归。

### 2026-11-13 凭证草稿在页面审核与修改（WS-05 第一阶段）

- 需求：继续 WS 线（用户 11-11 暂停后要求继续；11-13 再次要求接着完成）。WS-05 要求在页面上展示参考凭证并允许编辑：借贷实时校验、改动后须重新审核、借贷不平禁止审核，不写 `凭证/` 真值、不执行账套操作，页面结果与命令行草稿一致。起点 `fc925c5`。
- 方案：不另建凭证存储，页面直接读写命令行 `voucher_cli draft` 生成、`voucher_cli export` 读取的同一份 `做账草稿/凭证草稿_*.xlsx`，保证导出行为不变。
  - 新增 `services/company_vouchers.py`：`list_drafts` 只列 `做账草稿/` 内非链接的 `凭证草稿_*.xlsx`；`read_draft` 用导出的 `read_review_xlsx` 读“凭证审核”表、用导出的 `validate` 以只读 `凭证/科目表.json`、`辅助核算档案.json` 校验每张凭证，返回借贷合计、错误、提示与文件 SHA-256 revision；`save_draft` 只改已有行的摘要、科目编码（同步科目名称，未知编码清空）、借贷、供应商与审核列，revision 不符 409，要审核通过的凭证任一校验不过 422 并逐张列原因、整批不写，改过的已通过凭证若本次未重新审核则清空“通过”，原子替换文件。
  - 路由 `GET /api/v1/companies/{id}/voucher-drafts`、`GET/PUT .../voucher-drafts/{name}`；公司路由的错误响应可带 `error.details`，前端 `ApiError` 增加 `details`。
  - 新增 `CompanyVouchers.vue`（公司标签“凭证草稿”分区）：选择审核表、按月份与“只看有问题的”筛选；逐格编辑，输入时显示借贷合计与“不平 / 金额无法识别”（只作显示，以保存时后端校验为准）；审核下拉（待审核 / 通过 / 不导入）；保存只提交改动行与审核状态，冲突时刷新提示，审核被拒时保留改动并在凭证旁显示原因。
- 实现中发现并修正：保存时读表失败与畸形请求体原会成为 500，改为 422；金额写回原用 float，改为与生成命令一致的 Decimal；测试夹具的 `辅助核算档案.json` 原用了与 `load_aux_values` 不符的扁平格式，导致“供应商不在档案中”的误提示，改用真实的 `dimensions` 格式并断言无此提示。
- 文档：做账规则（页面审核凭证草稿）、页面规则（凭证草稿分区）、接口流程（两条路由与 `/workspace` 写操作）、文件地图、数据与算法（审核表可由页面改的列）、任务导航、设计原因地图、未来工作总览 WS-05 / WS-07、实现状态。
- 验证：`tests/test_company_vouchers.py` 5 项（导出规则校验、写回同一单元格且导出读取器可见、其他工作表保留、不平不能通过且整批不写、改后需重新审核、过期 revision、跨凭证行与越界文件名、改编码同步名称、畸形请求、API 结构化原因）与 `tests/test_bank_vouchers.py`；全量 pytest 970 passed、16 skipped；前端 Vitest 34 项（新增“编辑凭证草稿、实时合计、审核被拒时保留改动”）、`vue-tsc`、`vite build`。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成公司与合成审核表）：不平凭证显示“借 900.00 · 贷 800.00 · 不平”，选“通过”保存被拒并提示、未写文件；把第 5 行贷方改为 900 后合计即时变为平衡，保存成功并显示“已保存：改动 1 行、审核状态 1 张”；390 宽无横向溢出；控制台只有审核被拒那次预期的 HTTP 422。
- 未覆盖：真实公司资料夹与命令行生成的真实审核表；保存后再跑 `voucher_cli export` 的端到端导出（测试只用导出的读取器读回）；在 Excel / WPS 中打开保存后的工作簿核对超链接与格式；导出可选的 `--ledger` 读回快照（页面校验只读 `凭证/科目表.json`）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-13 目录标签的勾选与底部操作条（WS-01 第二阶段）

- 需求：继续 WS 线（用户 11-11 暂停后要求继续）。WS-01 要求目录页保留经典首页的勾选能力：全选 / 清除、勾选价税合计与合计详情、打印、批量开具入库单、删除所选，勾选后底部浮出操作条。起点 `7bf54a4`。
- 方案：
  - `DirectoryInvoices.vue`：只在监控目录且列表不是临时结果（`snapshot.provisional`）时显示勾选列；表头勾选本页（含部分选中），“全选筛选结果”按同一标签筛选每页 200 条读取全部记录；勾选只保存 `invoice_key + source_path`。
  - 新增 `DirectorySelectionBar.vue`：张数、价税合计与合计详情（三项金额、有效计入张数、冲突 / 缺失 / 同票折叠提示）全部来自 `POST /api/v1/invoices/selection-summary`（勾选变化后 250ms 去抖，旧请求结果丢弃，409 时清掉旧数字并提示）；打印先在点击内开窗，再把 `print-jobs` 返回的打印页地址填入；开具入库单沿用经典首页的会话交接（`invoicehub.inbound-selection`，最多 1000 条）后打开单据页；删除所选先 `POST trash-jobs` 列出文件（每组 100 个），条内“确认移入废纸篓”后才 `confirm`，确认响应丢失时只读 `GET trash-jobs/{id}`，不再确认；完成或部分完成后清空勾选、重载列表，并在列表上方保留逐文件结果。
  - 源文件预览暂不迁移，操作条提示到经典首页进行。
- 实现中发现并修正：操作条最初在立即执行的 `watch` 之后才声明删除计划，一勾选就抛错（测试发现）；删除完成后清空勾选会卸载操作条，部分完成的逐文件结果随之消失，改为交给列表保留。
- 浏览器验收中观察到（未改动）：验收数据先以 `/tmp/...` 汇总、再把监控目录切换为解析后的 `/private/tmp/...` 时，`trash-jobs` 以“不在目录内”拒绝（409）。这是后端既有的路径边界校验；按解析后的路径重新生成验收数据后正常列出文件。
- 文档：页面规则（目录标签勾选）、文件地图、接口流程 `/workspace` 行、设计原因地图、未来工作总览 WS-01、实现状态。
- 验证：前端 Vitest 33 项（新增“监控目录勾选：合计请求体、打印、删除只确认一次并读日志、结果面板保留”与“非监控目录无勾选”）、`vue-tsc`、`vite build`；全量 pytest 965 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799，合成资料）：把合成公司“成本发票”设为监控目录后勾选本页，操作条显示已勾选 1 张、价税合计 82,490.00，合计详情 73,000.00 / 9,490.00 / 82,490.00；“删除所选…”列出 a.xml 待确认后取消（未执行移入废纸篓，避免改动本机废纸篓）；390 宽无横向溢出、无控制台错误。
- 未覆盖：真实点击“确认移入废纸篓”（只由前端测试桩接验证）；打印窗口真实打印；入库单跳转后的单据页；源文件预览；真实公司资料夹；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 比较明细抽屉与原始记录并排（WS-04）

- 需求：继续 WS 线，做 WS-04：比较页每个类目能点开看来源与逐步计算，下方两个目录的原始文件并排，点类目后只留相关记录。起点 `59d07b6`。
- 方案：
  - 后端（三种关系都只读、不改算法）：`company_inventory.py` 每条明细带发票记录 id，返回 `records.a/b`（按发票合并，所选期间内）、品类与规格的 `record_ids`，逐月行的 `steps` 由 `_month_steps` 用 `cost_of_sales` 实际数值生成（销售成本写成“金额 × 销售数量 ÷ 可售数量”，与舍入前的计算一致）；`company_settlement.py` 返回期内发票与全部期内流水（含非发票流水、户名不唯一）为 `records`，往来单位与逐笔对应带 `record_ids`，往来单位带“期初 + 本期发票 − 本期收付 = 期末”；`company_deduction.py` 返回期内与对上的发票、清单行为 `records`，所属期与对上的清单行带 `record_ids`，所属期带行数构成与有效抵扣税额之和。
  - 前端：新增 `compareFocus.ts`（注入键）、`CompareDrawer.vue`（明细抽屉，焦点到关闭按钮，Esc 关闭）、`CompareSources.vue`（并排原始记录，按 id 过滤、“显示全部”）；进销存品类名与规格名、往来单位名与逐笔对应的“来源”、抵扣所属期改为可点。抽屉只显示后端 `steps`，页面不重算。
  - 实现中发现并修正：并排两列在窄屏改为单列时用了 `1fr`，被表格最小宽度撑开导致 390 宽横向溢出；改为 `minmax(0, 1fr)`。
- 文档：接口流程 compare 行、数据算法（比较明细与并排记录）、页面规则（WS-04 只显示后端 steps、按后端 id 过滤、非监控目录不接预览）、文件地图（3 个新文件）、设计原因地图、未来工作总览 WS-04、实现状态。
- 验证：后端新增 `test_categories_point_at_their_invoices_and_explain_the_month`、`test_parties_and_matches_point_at_their_rows_side_by_side`，抵扣用例补 `record_ids` 与 `steps` 断言；前端 Vitest 31 项（新增“点品类打开计算过程并收窄并排记录”）、`vue-tsc`、`vite build`；全量 pytest 965 passed、16 skipped。专用 Chrome 经 CDP + Playwright（临时根目录 8799）：从侧栏比较打开进销存，点“螺纹钢”后抽屉显示期初 4 吨 / 15,000.00、购入 15 吨 / 61,000.00、加权单价 4,000.00、销售成本 = 12 × 76,000.00 ÷ 19 = 48,000.00、期末 7 吨 / 28,000.00，两边记录各 1 条；1280 与 390 宽无横向溢出、无控制台错误。
- 未覆盖：缩略图与大图（预览管道只服务监控目录）；不同公司或无勾稽字段时的同号发票检查；汇总卡片与单笔流水的明细；真实公司资料夹；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 工作区外框第一阶段：模块列、公司侧栏与首页标签（WS-01）

- 需求：用户要求“做剩下的 WS”。按原型（`docs/design/workspace-sidebar-prototype.html`）与待办 WS-01 先做外框：左侧模块列、`InvoiceHub ⌄` 公司 › 项目 / 目录侧栏、只属于首页的标签、页面缓存、双击 `hi.` 只刷新本页、侧栏可拖动调宽且限位、右键置顶与“选择以进行比较”。起点 `8ae52bb`（开发线已快进到同一提交）。
- 方案：
  - 新增 `stores/workspace.ts`：标签（id = 类型 + 对象，同一对象只开一个；关闭时激活右侧或左侧相邻标签）、置顶、展开的公司、侧栏宽度（`clampSidebar`：220—460px，且内容区至少 620px）、比较选择；置顶 / 展开 / 宽度存 `localStorage`（`invoicehub.workspace.v1`），只是界面偏好。
  - 新增 `WorkspaceSidebar.vue`：置顶区、公司树（项目在展开公司时才读 `projects`，读失败只在该处提示）、六类目录（进项 / 销项 / 流水 / 抵扣 / 工资 / 报销标记，监控中绿点，缺失灰显），右键 / 行尾 ⋯ / Shift+F10 同一菜单（键盘上下移动、Esc 返回原行），悬停 450ms 出名片（全名、所属公司、路径），分隔条可拖动、键盘左右键调宽、Home 或双击复位，到限位时提示“已到最小 / 最大宽度”；底部显示唯一的监控目录。
  - 新增 `HomeView.vue`：标签栏（键盘左右切换、Delete 关闭、中键关闭）与常驻的标签内容（`v-show`，key 含刷新计数）；全部关闭后显示起始页（版本、后台状态、当前监控目录）。首次进入只自动打开一次监控中的公司；公司被删除时其标签自动关闭。900px 以下侧栏改为抽屉（点遮罩或 Esc 关闭）。
  - 原“公司”页拆为 `CompanyPanel.vue`（公司标签）、`DirectoryPanel.vue` + `DirectoryInvoices.vue`（目录标签与发票列表，标签打标逻辑原样迁入）、`WatchSwitchConfirm.vue`（两处共用的“设为监控目录”确认）；`CompanyDirectories.vue` 的“查看发票”改为打开目录标签。比较关系表移到 `relations.ts`，`CompanyCompare.vue` 接受 `relation` 预选，`CompanyProjects.vue` 接受 `focus` 标出项目并列出各期。删除 `CompaniesView`、`OverviewView`、`DirectoryView`，旧路径重定向到首页。
  - `App.vue` 模块列：首页为 Vue 工作区，成本分析、单据、做账、OCR、一致性、设置链接经典页面（不在 Vue 里重写业务）；双击 `hi.` 只给当前标签的刷新计数加一并重读公司清单。
- 实现中发现并修正：`DirectoryPanel` / `DirectoryInvoices` 起初用返回数组的 getter 监听 `[company.id, dirKey]`，公司清单每次刷新都会让列表重新请求；改为字符串键，并写入页面规则与设计原因地图。
- 文档：页面规则（Vue 工作区前端：外框、偏好存储、比较可用条件、watch 键）、文件地图（9 个新文件、3 个删除、相关职责）、接口流程 `/workspace` 行、任务导航 9.2 与 10.4、设计原因地图、未来工作总览 WS-01、实现状态。
- 验证：前端 `vue-tsc`、Vitest 30 项（`app.spec.ts` 重写为外框与首页 11 项：起始页、旧路径重定向、经典链接、标签去重与常驻、全部关闭后不再自动打开、项目懒加载、键盘菜单置顶与持久化、比较可用条件与预选关系、双击只刷新当前标签、宽度限位；`companies.spec.ts` 15 项改为经侧栏与公司标签操作）、`vite build`、`tests/test_workspace_frontend.py` 通过。专用 Chrome 经 CDP + Playwright 在临时根目录（8799 端口）看了合成公司：1280 宽下展开公司、打开目录标签、右键“选择以进行比较”后行内“⇄ 比较”打开进销存标签、拖到最大宽度时显示“已到最大宽度”且宽度 460px 写入本机偏好；390 宽下侧栏为抽屉、无横向溢出、无控制台错误。
- 未覆盖：目录页的经典首页发票列表全部能力（勾选合计、`>>` 菜单、预览 / 打印 / 入库单 / 删除、底部操作条）仍未迁移；临时识别入口；真实公司资料夹；Windows、Tauri 桌面窗口与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 进销存按品类计算，期初从账套读回（WS-07）

- 需求：上一轮留给用户的问题是“账套库存按品类记、进销存按规格算，期初怎么对”。用户定：**根据品类合计计算期初，规格作为下拉细分**。起点 `codex/ws-07-company-registry` 的 `6c58435`。
- 方案：
  - `services/company_inventory.py`：库存单元从“标准名称 + 规格 + 单位”改为品类 `goods_family(标准名称)` + 单位，也就是账套库存商品明细和做账草稿用的同一个口径。逐月仍调用 `bank.vouchers.cost_of_sales`。规格行只汇总购入数量、购入金额与销售数量（另给净增），期初与成本不分摊到规格；新增 `spec_breakdown` 校验：各规格之和必须等于品类合计。
  - 新增 `read_book_inputs`：请求时只读公司资料夹 `做账草稿/账套读回/序时账_*.txt`（`load_booked`）与 `凭证/科目表.json`。起算月（`start`，未给则为最早发票月）之前有读回月份、且科目表能唯一定位“库存商品”时，期初 = `stock_opening` 的累计数，按科目名称与单位放到品类行；这些月份的发票已在账套余额里，不再计入。读回不足、文件损坏或缺科目表时按 0 起算，`opening.error` 和提示写明原因。账套分录没有单位、而该品类发票有多个单位时不猜，列为“未计入期初”。同一品类有多个单位时分行计算并提示。
  - 返回新增 `opening`、`items[].account_code`、`items[].specs[]`、`totals.open_amount`；`items[]` 不再有 `spec`。
  - 页面（`CompanyInventoryResult.vue`）：首列改为品类和明细科目编码，▸ 在同一组列下展开规格行（期初、成本、期末金额显示 —，悬停说明不分摊）；规格名与品类同名时只显示规格，避免 1280 宽下表格被挤出；下方列出未计入期初的账套明细。
- 验证：`tests/test_company_inventory.py` 12 项（新增规格细分、多单位、读回期初、读回不足、损坏/缺科目表、无单位分录 6 项，API 用例补“放入读回后取账套期初”）；全量 pytest 963 passed、16 skipped；前端 `vue-tsc`、Vitest 23 项（进销存用例改为品类 + 规格展开 + 读回期初）、`vite build` 通过。专用 Chrome 经 CDP + Playwright 在临时根目录（8799 端口）看了合成公司：两种螺纹钢规格 + 盘螺，读回 5 月库存商品分录；1280 与 390 宽度下数值为 螺纹钢 期初 4 吨 / 15,000.00、购入 15 吨 / 61,000.00、销售 12 吨、成本 48,000.00、期末 7 吨 / 28,000.00，规格行 10 + 5 = 15、12 + 0 = 12，四项校验成立，无控制台错误、无横向溢出。
- 未覆盖：真实公司资料夹与真实序时账读回；往来核对的账套期初（序时账不带往来单位辅助核算，仍按 0 起算）；建账期初余额（科目期初不在序时账里，提示中已写明）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 发票自定义标签（WS-06）

- 需求：继续 WS 线，做待办 WS-06：设置里自定义标签（颜色、名称、意义），发票列表右键打标签、悬停看意义、按标签筛选；标签按受保护的人工数据保存，不改变金额、状态与勾选合计。起点 `b78e45f`。
- 方案：新增 `services/invoice_tags.py::InvoiceTagStore`。标签定义存 `runtime/local_state/invoice_tags.json`（与公司清单同目录，本机级；整表替换，带 revision，名称 1—12 字不重复、颜色 `#RRGGBB`、意义 ≤120 字、最多 30 个）；标记存公司资料夹根目录 `发票标签.json`（按发票号码）。删除标签时逐个公司清除标记，不可用的资料夹列入 `purge_failed`，读取时忽略已删除的 id。损坏文件拒绝读写。`CompanyViewService.directory_invoices` 给每行附加 `tags`、支持 `tag` 筛选（先筛后分页），标记文件读不出时列表照常并返回 `tags_error`。新增 `GET/PUT /api/v1/invoice-tags` 与 `GET/PUT /api/v1/companies/{id}/invoice-tags`（同源写）。前端：左栏“发票标签”按钮打开 `InvoiceTagsEditor.vue`；`CompanyDirectories.vue` 的发票列表名称前固定一格放色点（多个叠放，悬停显示名称与意义），右键或 Shift+F10 打开标签菜单（焦点进入菜单，Esc 回到原行），打标签后只局部更新该行；按标签筛选。新增 `stores/tags.ts`。
- 实现中发现并修正：`directory_invoices` 原先在首页服务返回的 payload 上原地追加公司字段，活动目录时可能让首页响应带上这些字段；现在先复制 payload 和每一行，并在守护测试中断言首页响应不含 `tags`。
- 文档：接口流程（四条路由与目录列表参数）、数据算法（发票标签）、做账规则与页面规则、文件地图（5 个新文件，`CompanyDirectories.vue` 职责）、任务导航 10.4、设计原因地图、未来工作总览、实现状态。
- 验证：新增 `tests/test_invoice_tags.py`（4 项），`tests/test_company_views.py` 的活动目录用例改为剥离标签后比较并检查首页不被污染；前端 `vue-tsc`、Vitest 23 项（新增打标签与筛选用例）、`vite build` 通过；真实浏览器（专用 Chrome 经 CDP + Playwright，临时根目录 8799 端口，合成公司 2 张成本发票）：新建“待核实”标签、右键第一行打上，色点悬停显示“待核实：金额待和供应商确认”，Shift+F10 菜单焦点落在复选框、Esc 回到行，按标签筛选剩 1 行，`发票标签.json` 已写入，无横向溢出与控制台错误。macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：多行批量打标签；旧首页列表；深色与其它皮肤（工作区不加载皮肤）；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 公司项目汇总与人工项目归属（WS-03 / WS-07 第 5 步）

- 需求：继续 WS 线。第 4 步比较已全部就绪，账套读回期初需要用户决定库存科目与规格的对应方式，先做待办里已有明确方案的 WS-03：项目取自发票备注“项目名称：xxx”，没有的人工填写并按受保护字段保存，未归属单列不分摊。起点 `da8815b`。
- 方案：新增 `services/company_projects.py`。项目名来自两个目录 `成本发票明细.csv` 的“备注项目名称”（成本投影已从备注提取）；一张票只有一个名称才采用，多个名称列入未归属。人工归属由 `ProjectAssignmentStore` 写入公司资料夹根目录 `项目归属.json`（按发票号码，带 revision 与锁；空值清除；损坏文件拒绝读写，不当空文件覆盖），人工值优先于备注。`build_project_summary` 与发票账簿同一家族、金额与期间规则，并与 `build_invoice_ledger` 交叉校验张数与价税合计。新增 `GET /api/v1/companies/{id}/projects` 与 `PUT .../projects/assignments`（同源写）。前端新增“项目”标签（`CompanyProjects.vue`）：项目汇总表（未归属单列）、未归属与已人工指定发票的项目输入（已有项目名候选），只提交改动并带 revision，冲突时刷新再提示。
- 文档：接口流程（两条路由）、数据算法（项目汇总）、做账规则与页面规则、文件地图（3 个新文件，`CompaniesView.vue` 职责）、任务导航 10.4（产物新增 `项目归属.json`）、设计原因地图、未来工作总览（WS-02/03/07 总览状态改为进行中，WS-07 进度）、实现状态。
- 验证：新增 `tests/test_company_projects.py`（5 项）；前端 `vue-tsc`、Vitest 22 项（新增项目归属用例）、`vite build` 通过；真实浏览器（专用 Chrome 经 CDP + Playwright，临时根目录 8799 端口，合成公司 2 张成本发票、1 张开具发票，均无备注）：保存前全部未归属，给两张填“甲项目”保存后甲项目进项 1,130.00、销项 1,695.00、差额 500.00，未归属剩 1 张，与账簿一致 4 项成立，`项目归属.json` revision 为 1；1280px 与 390px 无横向溢出，控制台无错误。macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：PDF 备注的项目名识别只沿用成本投影既有提取（本轮未改提取，也未用真实发票验证）；旧首页项目列；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 往来核对：发票 ⇄ 银行流水（WS-07 第 4 步）

- 需求：用户要求继续完成 WS 线。起点 `codex/ws-07-company-registry` 的 `6c7b023`（进销存）。
- 方案：新增 `services/company_settlement.py::build_settlement_check`，应付（成本发票销售方 ⇄ 支出）与应收（开具发票购买方 ⇄ 收入）共用一套算法。发票沿用账簿的家族与金额守恒规则；对账单户名在 NFKC、去空白、大小写折叠后与发票对方相等，或是 ≥4 字的截断前缀且只命中一家时才归属。命中多家的列为“户名不唯一”；本公司（公司清单名称、发票本方名称、对账单户名）列为本公司账户；其余列为非发票流水。匹配顺序：红字发票冲销同单位金额相反的蓝字票 → 一笔流水对一张同额发票（同额多张按开票先后）→ 唯一一组 2—3 张发票合计相等（多组可行时不对应并提示）→ 剩余流水为“未逐笔对应”，不分摊。期初按 0 起算并标注，`start` 之前的发票与流水进入期初。后端校验：各单位期末合计等于截至期末全部发票 − 全部收付（从原始清单复算）；本期流水四类之和等于对账单笔数；本期发票四类之和等于张数；对账单自检无错误。`company_views.py` 的 `COMPARE_RELATIONS` 新增两组关系，`_compare_settlement` 读 `BankFlowReader` 与发票投影。前端新增 `CompanySettlementResult.vue`（往来单位余额表，“明细”整行展开未对上发票与未逐笔对应流水；逐笔对应、红字发票、户名不唯一、非发票流水折叠），“勾稽”标签新增两个关系。
- 实现中发现并修正：最初的余额校验是用往来单位行自己的数复算，永远成立，改为从原始清单复算；红字票只冲减余额时被冲的蓝字票仍显示“未付”，改为先做红冲抵销；红冲后净额为 0 的单位曾被过滤掉，改为只要本期有发票或流水就列出。
- 文档：接口流程、数据算法（往来核对算法）、做账规则与页面规则、文件地图（3 个新文件）、任务导航 10.4、设计原因地图、未来工作总览、实现状态。
- 验证：新增 `tests/test_company_settlement.py`（9 项）；前端 `vue-tsc`、Vitest 21 项（新增往来用例）、`vite build` 通过；真实浏览器（专用 Chrome 经 CDP + Playwright，临时根目录 8799 端口，合成公司 4 张成本发票与 6 月中国银行对账单 PDF：付 11,300、付 7,910、手续费 16、供应商退款 200）1280px 与 390px：期末应付 3,590.00，一对一 1 笔、两张组合 1 笔，3,390 那张未付，退款列为未逐笔对应，手续费为非发票流水，校验 4 项成立，无横向溢出、无控制台错误。macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：账套读回期初；回单（户名更全）参与归属；比较与原始文件并排联动；真实目录页面验收；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 进销存：成本发票 ⇄ 开具发票（WS-07 第 4 步）

- 需求：继续 WS 线，按用户当天的决定做进销存：按品目表标准名 + 规格 + 单位归并，期初库存按 0 起算并明确标注。
- 起点：`codex/ws-07-company-registry` 的 `1203c55`（抵扣核对）。
- 方案：
  - 新增 `services/company_inventory.py::build_inventory_check`。
    - 两个目录的明细行都经 `canonical_reference_rows` 归并：品目表标准名称，规格统一全半角并去掉空白，费用和固定资产剔除。键为标准名称 + 规格 + 单位，不含税收分类文字。
    - 进货额与成本页开票参考同口径：不含税金额加不可抵扣税金。小规模纳税人全部计入；一般纳税人按 `input_tax_index` 判断；类型待核对的按不含税计并提示。
    - 从最早有发票的月份逐月调用做账草稿的 `bank.vouchers.cost_of_sales`，月末一次加权，期初按 0 起算。卖超时照算并写明，不凑平。
    - `start/end` 只筛选显示的月份，库存仍从最早月份滚动。
    - 后端校验：进项、销项计入数量分别等于各品目之和；每个品目每月期初 + 购入 − 销售 = 期末（数量与金额）。提示四类：期初按 0、销项品目在进项中找不到（可到品目表合并）、卖超、类型待核对。
    - 开票日期、数量、单位或进项金额读不出的明细行列入“未计入”。
  - `projections/costs.py` 新增 `CostProjectionService.read_only_inputs()`，只读返回明细行、发票校验行、品目表和税务设置。原有的 `snapshot` 会刷新 schema、重写工作簿，不能用在非监控目录上。
  - `CompanyViewService.compare` 改为按关系分派（`_compare_deduction` / `_compare_inventory`），`COMPARE_RELATIONS` 新增成本发票 ⇄ 开具发票；构造 `CostProjectionService` 的代码合并到 `_cost_service`。两个目录都还没有成本明细时返回 `state=no_details`。
  - 前端：`CompanyCompare.vue` 改为外壳（关系、期间、口径、校验、提示），切换关系即重新核对，不显示另一关系的旧结果。结果拆到 `CompanyDeductionResult.vue` 与新增的 `CompanyInventoryResult.vue`（品目表，卖超与“进项中没有”标红；“逐月”在品目下方整行展开，显示加权单价与说明）。
- 文档：接口流程、数据算法（进销存算法）、做账规则与页面规则、文件地图（3 个新文件，`costs.py` 与 `CompanyCompare.vue` 职责）、任务导航 10.4、设计原因地图、未来工作总览、实现状态。
- 验证：
  - 新增 `tests/test_company_inventory.py`（7 项）：跨月加权与品目合并，6 月成本 20,000.00，7 月 (20,000 + 42,000) ÷ 15 × 12 = 49,600.00，结存 3 吨 / 12,400.00；小规模、普票、待核对三种进货额；卖超与“进项中没有”；非货物与不可读行；范围从滚动库存起算（含无发票的月份）；规格分开；API 未汇总、汇总后结果、读取前后文件 mtime 不变。公司相关测试全部通过。
  - 前端 `vue-tsc`、Vitest 20 项（新增“切换到进销存并标出卖超”）、`vite build` 通过。
  - 真实浏览器（专用 Chrome 经 CDP 加 Playwright，临时根目录，8799 端口，合成公司：成本发票 6、7 月各 10 吨，开具发票 6 月 5 吨、7 月 12 吨，另有一行从未进货的“盘螺”，两个目录都已汇总）在 1280px 与 390px 下：钢筋购入 20 吨 / 82,000.00，销售成本 69,600.00，结存 3 吨 / 12,400.00；盘螺标“进项中没有”并标红，逐月说明显示“无库存却销售 2 吨”；三条提示齐全。页面无横向溢出（表格在自身容器内横向滚动），控制台无错误。验收时把逐月明细从“说明”格里的子表改成整行展开（原来在窄屏被截断），链接颜色改为继承正文颜色（主题色是亮绿，在浅底上看不清）。
  - macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：账套读回期初（期初只能按 0）；往来核对；真实目录上的页面验收；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 抵扣核对：成本发票 ⇄ 进项抵扣清单（WS-07 第 4 步）

- 需求：继续 WS 线。用户确认了第 4 步的口径：进销存按品目表标准名 + 规格 + 单位归并，期初按 0 起算并标注；勾选清单“已有，直接脱敏”。
- 起点：`codex/ws-07-company-registry` 的 `6a83a6c`（第 3 步银行部分）。
- 格式核实：用户资料夹里有电子税务局“抵扣类勾选”导出的 `用途确认信息.xlsx`（3 份）。只读查看了工作表结构和表头，没有复制任何数值：
  - “发票”表首行是“发票清单”；第 2 行是纳税人识别号、税款所属期（YYYYMM）、纳税人名称；第 3 行是 20 列表头；之后是数据行，最后一行是“合计”。金额以 Excel 数字存放。
  - 当期没有勾选时，整张表只有一格“发票清单”，没有所属期。
  - 另有一份 PDF，是网页打印件，不使用。
  - 测试与验收只用按同一版式生成的合成清单。解析器只读跑过这 3 份真实文件，只输出计数与校验结果：1 份 10 行，合计行一致；另 2 份是空清单。
- 方案：
  - 新增 `services/company_deduction.py`。
    - 解析器只认表头齐全、有所属期的“发票”表；缺表、缺所属期、缺列、某行没有号码、文件打不开，都列为未识别。空清单报告为“所属期未知”，不按文件夹名推断。
    - 文件按共同父目录下的相对路径显示，因为每月的导出文件都叫 `用途确认信息.xlsx`。
    - 读取复用 `company_bank.py` 中由 `BankFlowReader` 抽出的 `CachedFolderReader`（有界列出、签名缓存，跳过 `.` 与 `~$`）。
  - `build_deduction_check` 按发票号码（优先数电发票号码）对照成本发票的家族（与账簿同一规则），只有“已勾选”的行算勾选，结果分为以下几类：
    - 对上的发票，再按开票月与所属期分为当期、前期、开票晚于所属期、日期未识别；
    - 清单有、目录无；
    - 未勾选；
    - 目录有、清单无的专票，附上所属期不早于开票月的已有清单，以区分“未勾选”和“还没有清单”；
    - 普票只计数；
    - 票种未识别的单独列出；
    - 跨清单重复勾选。
  - 后端校验四类：
    - 每份清单逐行金额、税额、有效抵扣税额之和等于合计行；
    - 每个所属期：对上 + 目录无 + 未勾选 + 重复 = 清单行数；
    - 没有重复勾选；
    - 已勾选发票的税额与发票一致。
  - 新增 `GET /api/v1/companies/{id}/compare?a=&b=`（`CompanyViewService.compare`），由 `COMPARE_RELATIONS` 按两类资料的关系选择算法，`a`、`b` 顺序无关。没有勾稽关系的组合返回 422 `COMPANY_COMPARE_UNSUPPORTED`，月份不合法返回 422 `COMPANY_COMPARE_INVALID`。结果标注“已勾选不等于已申报”。
  - 前端在公司详情页新增“勾稽”标签（`components/CompanyCompare.vue`，首次打开才加载）：关系选择、期间、核对校验（不成立时展开并标红）、各所属期表，以及上面各类的明细表；税额不一致的行标红。
- 文档：接口流程（compare 行）、数据算法（抵扣核对算法）、做账规则与页面规则、文件地图（3 个新文件，`company_bank.py` 与 `CompaniesView.vue` 职责）、任务导航 10.4、设计原因地图、未来工作总览、实现状态。
- 验证：
  - 新增 `tests/test_company_deduction.py`（10 项），银行与抵扣相关 21 项通过。
  - 前端 `vue-tsc`、Vitest 19 项（新增“勾稽”用例，原设置用例改用标签 id 定位）、`vite build` 通过。
  - 真实浏览器（专用 Chrome 经 CDP 加 Playwright，临时根目录，8799 端口，合成公司：3 张成本发票 XML 已汇总，6 月清单 3 行，其中 1 行税额不符、1 行目录无原票，另有 5 月空清单）在 1280px 与 390px 下：校验第 4 项标红，有效抵扣税额 456.00，前期开票 1 张，目录有清单无 1 张且标“2026-06 未勾选”，空清单提示显示为 `5月/用途确认信息.xlsx`。页面无横向溢出，控制台无错误。验收时把空清单提示里只有文件名改成了相对路径。
  - macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：进销存、往来核对（第 4 步其余）；海关缴款书、代扣代缴、农产品加计扣除等其它工作表（目前只读“发票”表）；真实目录上的页面验收；Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-11 公司账簿加入银行流水（WS-07 第 3 步银行部分）

- 需求：用户要求完成未来工作总览里多公司工作区（WS）这条线。WS-07 第 3 步的银行流水、勾选清单与账套读回期初一直在等主目录未提交的 `bank/`。
- 起点：主目录开发线 `codex/cost-select-all-transitions` 先按主题拆成 4 个本地提交（税务设计与工作区原型的真值文档、Agent Handoff 工具、`bank/` 命令行模块、成本页说明浮层），之后由 worktree `../InvoiceHub-ws07` 的 `codex/ws-07-company-registry`（`2886983`）合并进来（`a82df67`）。合并冲突都在文档里，两边内容都保留：银行流水文档保留原编号，公司清单改为任务导航 10.4、接口流程 §3.5.3、数据算法 §4.8，引用同步更新。
- 方案：
  - 新增 `services/company_bank.py`。`list_bank_pdfs` 有界列出银行流水目录的 PDF（2,000 个文件或 2 秒，跳过 `.` 开头，不跟随链接）；列不全时整体不汇总，避免缺掉的月份看起来像没有收支。`BankFlowReader` 在内存中按目录缓存 `{路径: (mtime_ns, size)}` 和解析结果，签名完全一致才复用。
  - `bank/workpaper.py::discover` 改为只看首页识别版式，只有对账单才读全部页面；新增 `parse_receipts=False`，账簿只解析对账单、回单只计数。命令行默认行为不变。
  - `build_bank_ledger` 按账户把每份对账单分到月：期初取该月首行前余额，期末取末行余额，期间内无交易的月份期初等于期末。按月、季、年汇总时，期初取期间首月、期末取期间末月；期间内缺对账单的月份记入 `missing_months`，余额为 `null`（不补 0），该期“期初 + 收入 − 支出 = 期末”判为不成立。对账单自检（逐行余额、页脚合计、期间断档与重叠、重复行，复用 `bank/checks.py`）出现任一“错误”，银行校验即不成立。多个账户合并的期初、期末只在每个账户该期都成立时给出。
  - `CompanyViewService.company_ledger` 把结果作为 `bank` 与发票账簿并列返回（`include_bank=false` 可关闭），状态分 `ok/no_statements/missing_dir/unreadable`；`bank.checks_ok` 不并入发票的 `checks_ok`。银行口径和票面口径分开标注。
  - 前端新增 `components/CompanyBankLedger.vue`，放在“发票账簿”标签下方：余额校验全部成立时收起，任一不成立时展开并标红；缺月的行标红，余额显示“—”；按账户分表；列出对账单问题与来源计数（回单不参与汇总）。
- 文档：接口流程（ledger 行的 `bank` 字段）、数据算法（银行流水汇总算法）、做账规则与页面规则（缺月不补 0、只读、不并入发票校验）、文件地图（3 个新文件，`workpaper.py` 职责）、任务导航 10.4、设计原因地图、未来工作总览 WS-07 进度、实现状态。
- 验证：
  - 新增 `tests/test_company_bank.py`（11 项）：月度期初/收支/期末、季度汇总、缺月不补 0、季度内缺月不成立、范围外月份、余额错误使自检不成立、签名缓存与文件变化、回单只计数、API（并列返回、公司资料夹文件不变、`include_bank=false`、缺目录、无对账单）。银行与公司相关 53 项通过。
  - 前端 `vue-tsc --noEmit`、Vitest 18 项（新增 2 项：缺月显示为缺失而不是 0；缺目录只显示说明）、`vite build` 通过，`tests/test_workspace_frontend.py` 通过。
  - 真实浏览器：专用 Chrome 经 CDP，加上临时虚拟环境里的 Playwright；后端用临时根目录和 8799 端口，两家合成公司，甲缺 8 月对账单、乙 7—8 月完整，不使用本机配置。1280px 与 390px 下数字与合成数据一致：甲 8 月行标红、余额为“—”，校验展开；乙校验收起。页面无横向溢出，控制台无错误。根据截图修了两处：对账单问题列表字号过大，表格标题里尾号与户名连在一起、月份被断行。
  - macOS 本机全量 pytest（绝对 `PYTHONPATH`，`-x`）退出码 0；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：勾选清单与账套读回期初（仓库里还没有这两类文件的读取器，需要一份脱敏样例确定格式，没有按猜测的表头实现）；其他银行与 Excel/CSV 对账单；真实对账单目录、Windows、Tauri 与打包产物。只做了本地提交，未推送、未合并到 main。

### 2026-11-10 工作区“公司”模块：WS-07 后端的第一个页面（WS-02 / WS-07）

- 需求：进销存（WS-07 第 4 步）依赖主工作区未提交的 `bank/`：做账库存的 `cost_of_sales` 和从账套读回的期初都在那里。用户选择先不动那条线，改做工作区界面。
- 起点：`codex/ws-07-company-registry` 的 `fe031de`，独立 worktree 施工；`frontend/node_modules` 用软链接复用主工作区按同一锁文件安装的依赖（锁文件与 `package.json` 逐字节相同，基线构建与提交产物逐字节一致），收尾时删除。
- 方案：Vue 工作区新增路由 `/workspace/companies`（模块列“公司”）。新增 `stores/companies.ts`：写入都带清单 revision，冲突时先重读再提示。新增 `views/CompaniesView.vue`：左栏公司清单，标出监控中、缺几个子目录、当前纳税人身份；右栏三个标签：
  - 目录（`components/CompanyDirectories.vue`）：子目录状态、上次汇总、是否最新；补建缺失子目录先预览再确认；设为监控目录需确认并说明旧目录停止监控；按目录查看只读发票并分页。
  - 发票账簿（`CompanyLedger.vue`）：粒度与期间筛选；守恒校验成立时收起，任一不成立时展开并标红；提示；分期表、合计、未计入的发票；标注票面口径。
  - 设置（`CompanySettings.vue`）：改名、纳税人身份生效期，显示成本汇总表是否已按新身份重写；从清单移除并说明不删除文件。草稿只在切换公司时重置。
  - 另有新建公司表单（`CompanyCreateForm.vue`），纳税人身份不填即“未设置”。
  - `api/client.ts` 的错误带上 `code`，新增 `acceptPartial`，用于拿到子目录补建部分失败时的逐项结果；`format.ts` 在十进制字符串上分组千分位，不经过浮点。旧页面与 `web/static/js` 未改动。
- 文档：文件地图登记 8 个新前端文件，并更新客户端说明；接口流程页面路由行；页面规则新增“公司”模块约束；任务导航 10.3 节；设计原因地图；未来工作总览中 WS-02 改为进行中并列出未做项。
- 验证：前端 `vue-tsc --noEmit`、Vitest 16 项（新增 `frontend/tests/companies.spec.ts` 8 项）、`vite build` 通过，`tests/test_workspace_frontend.py` 通过。真实浏览器：专用 Chrome 经 CDP 加临时虚拟环境里的 Playwright，后端用临时根目录与 8799 端口、合成的两家公司 8 张 XML 发票，不使用本机配置。核对了：
  - 清单默认选中监控中的公司，子目录状态与是否最新正确；
  - 账簿逐月金额与手算一致：进项 6 月 90,400.00（两份同号只计一次），7 月 41,697.00（含红字 −4,633.00）；销项 6 月 81,360.00、7 月 43,392.00；不守恒的一张单列；10 项校验成立；
  - 非监控目录 3 张发票只读；乙公司补建 5 个空文件夹，磁盘上与预览一致；保存小规模纳税人身份后清单标签更新；
  - 1280px 与 390px 下页面无横向溢出，控制台无错误；据截图修掉了期间断行、窄屏单元格竖排、按钮被拉满宽。
- 未覆盖：原生目录选择器（需粘贴路径）、Tauri WebView、Windows、深色与其他皮肤（工作区本就不加载皮肤）、打包产物；“设为监控目录”只在合成目录上操作过；本机 Bash 不能直连 localhost，接口只经浏览器验证。只做了本地提交，未推送、未合并。

### 2026-11-10 多公司工作区后端第 3 步（发票部分）：公司发票账簿（WS-07）

- 需求：用户同意先做第 3 步中不依赖银行流水的部分。银行流水用的 `src/invoice_hub/bank/` 仍只在主工作区、未提交，本轮不涉及。
- 起点：`codex/ws-07-company-registry` 的 `5bf602a`（第 2 步），独立 worktree 施工，主工作区未改动。
- 方案：新增纯算法 `services/company_ledger.py::build_invoice_ledger` 与 `CompanyViewService.company_ledger`，接口为 `GET /api/v1/companies/{company_id}/ledger`。
  - 数据来源：进项取成本发票目录、销项取开具发票目录，都读上次投影的首页行，已套用手改字段，不触发汇总。
  - 同票去重：与首页勾选合计同一家族规则（发票号 → 文件名 20 位号码 → 源文件路径），多格式只计一次，返回合并的份数。
  - 计入条件：价税合计、不含税、税额三项都识别出来、各格式一致、且“不含税 + 税额 = 价税合计”（±0.01）。免税、不征税或 0% 税率且不含税等于价税合计时，税额按 0。其余分为“金额未识别 / 格式间冲突 / 不守恒”三类单独列出，不计入。之所以不按字段分别累计，是因为那样三列合计会来自不同的票集合，账簿本身就不守恒。
  - 分期：按月、季或年；可选起止月份。范围外的票只计数，日期未识别的票单独报告，有范围时不计入合计。红字票按负数冲减。Decimal 累加，输出时四舍五入到分。
  - 其它输出：各期列出当期在用的纳税人类型；后端计算守恒校验（各期之和 = 合计；已识别 + 不计入 + 范围外 = 总张数）；提示进项购买方或销项销售方不止一个名称、两者无交集、同号发票同时出现在两个目录、格式间日期不一致，以及来源目录过期或未汇总。不按公司名称剔除任何发票。结果标注票面口径：差额不是利润，也不是应纳税额。
- 文档：接口流程 §3.5.1、数据算法 §4.6（账簿算法）、做账规则的公司清单节、文件地图、任务导航 10.3 节、设计原因地图、未来工作总览 WS-07 进度。
- 验证：新增 `tests/test_company_ledger.py`（5 项），其中种子合成账簿 2 × 300 张票，多格式、红字、个别格式丢失金额，逐月与另写的逐张求和对照一致。macOS 本机全量 pytest（绝对 `PYTHONPATH`）835 项通过、16 项跳过（均为既有平台或环境跳过），另有 20 个子测试通过；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：银行流水、勾选清单、账套读回期初（第 3 步其余部分）；没有与原型的合成账簿生成器逐项对照（原型文件不在本分支）；无前端消费者、无浏览器、Windows 与打包产物验证。只做了本地提交，未推送、未合并。

### 2026-11-10 多公司工作区后端第 2 步：按公司只读目录，纳税人类型以公司清单为准（WS-07）

- 需求：用户决定纳税人身份以公司清单为准，并要求继续 WS-07 第 2 步。
- 起点：`codex/ws-07-company-registry` 的 `f72dff7`（第 1 步），仍在独立 worktree 施工，主工作区未改动。
- 方案（第 2 步）：新增 `services/company_views.py::CompanyViewService`（`state.company_views`）。每个子目录用它作为 `watch_dir` 时的 TargetProfile 找到上次的普通汇总与成本明细；`target_profile_for` 是纯函数，读取不建任何目录。过期判断只在请求时进行：读 `processed_files.json`（坏文件不修复，判为 `unknown`），有界递归列出 PDF/OFD/XML（20,000 项或 2 秒，不跟随目录链接），按 `mtime_ns + size` 比对，得出 `fresh/stale/never_built/unknown`；活动目录直接报 `monitored`。之所以不用 `MonitorState`，是因为它的构造会建目录、读坏文件时会修复重写。非活动目录的发票列表由绑定该目录 profile 的临时 `InvoiceListService` 只调用 `list_invoices` 生成：行结构与首页相同，但标 `read_only`、清空 `detail_url`；活动目录交给 `state.invoices`。监控、设置、后台同步等仍只有活动目录这一份。这就是最初“按公司构造服务实例”的落地形态：只建读侧，不复制整套服务。
- 方案（纳税人类型）：新增 `targets/companies.py`，提供各进程共用的只读查找 `company_taxpayer_for(config, 目录, 月份)`；它放在 `targets/`，是因为 monitor daemon 与 spawn 子进程不经过 AppState。`cost_analysis.py::effective_tax_profile` 用清单当月类型替换状态文件里的类型，销项税率仍取成本页保存值（不替用户在 3%/1% 之间选择，非常用税率沿用原有提示）；有效类型不写回状态文件。全部 6 处 `CostProjectionService` 构造和 `MonitorSynchronizer` 都传入 `company_taxpayer`：API 每次现查；daemon 每次同步现查；后台首轮同步子进程由父进程查好后作为第 6 个位置参数传入。`build_cost_analysis_outputs` 在解析完成、写工作簿前才取值。分页读缓存的指纹包含有效类型。成本页提交与清单不同的类型返回 400，提示到公司清单修改。清单增删改让活动公司当月类型变化时，释放锁后在投影写锁下重写工作簿；锁被同步占用时交给那次同步（`cost_workbook.reason=sync_running`）。只比较类型，改名不重写。
- API：新增 `GET /api/v1/companies/{company_id}/directories`（`check_freshness` 可关）、`GET /api/v1/companies/{company_id}/directories/{key}/invoices`（与 `/api/v1/invoices` 同参数），错误码 `COMPANY_DIRECTORY_NOT_FOUND`（404）。`reference_tax_profile` 新增 `taxpayer_source`、`company_name`；清单写接口在类型变化时附 `cost_workbook`。既有字段与路由不变。
- 文档：接口流程 §3.5.1、数据算法 §4.6 与 §9.3、成本规则与做账规则的公司清单节、文件地图（新增 `targets/companies.py`、`services/company_views.py`、`tests/test_company_views.py`）、任务导航第 5 节与 10.3 节、设计原因地图、架构入口、未来工作总览 WS-07 进度与遗留项。
- 验证：新增 `tests/test_company_views.py`（8 项）；接线测试登记 `company_views`；测试中 4 个后台同步替身函数增加可选 `company_taxpayer` 参数。macOS 本机全量 pytest（绝对 `PYTHONPATH`）866 项：0 失败，16 项跳过（均为既有平台或环境跳过）。`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：`/costs` 页面未改。纳税人类型选择框仍可操作，选不同类型保存时由后端 400 拒绝并在横幅显示原因；没有显示来源，也没有禁用选择框（主工作区另一条线正在改 `page-costs.js`，本轮不碰）。开票参考仍按当月的单一类型计价，未按每张进项票的开票月份分别判断。跨月生效且期间没有同步时，工作簿要到下一次同步才更新。无前端消费者、无浏览器验收、无 Windows 与打包产物验证。只做了本地提交，未推送、未合并。

### 2026-11-10 多公司工作区后端第 1 步：公司清单（WS-07）

- 需求：用户确认开工 WS-07，并让 Agent 自行判断方案。评估结论：ENG-08 之后各服务通过 provider 读取活动目录，可以按公司构造，但监控、设置、后台同步、诊断、删除所选等必须保持活动目录单例；而且按公司构造服务的前提是先有“公司清单”。因此本轮先做 WS-07 第 1 步，按公司只读视图留到第 2 步。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `1ace01b`（ENG-08 尚未进入 `main`，WS-07 依赖它）。在独立 worktree 的 `codex/ws-07-company-registry` 施工；主工作区另一条线的未提交修改（成本页、`bank/`、交接脚本等）未改动。
- 方案：新增 `services/company_registry.py::CompanyRegistryService`（`state.companies`）与 `api/routes/companies.py`。清单存于 `runtime/local_state/companies.json`（schema v1），与单目录设置分开；由共享 RLock、revision CAS 和原子替换保护；文件损坏、版本不符或缺字段时返回 `COMPANY_REGISTRY_CORRUPT`，保留原文件并拒写。每家公司记录名称、资料夹根（项目内相对、包外绝对）、六类子目录相对路径（成本发票、开具发票、银行流水、进项抵扣、工资社保、费用报销），以及纳税人身份生效期。登记时未给出的子目录按“标准名 → 唯一无歧义提示词命中 → 标准名（待创建）”推断，前四类提示词复用业务资料夹。根目录不得重复或嵌套，子目录不得越界、相同或嵌套。补建子目录分两步：`GET …/subdirs/plan` 零写预览，`POST …/subdirs/create` 凭 `plan_hash` 加 `confirm=true` 只新建空目录；链接或越出根目录的路径不创建。删除公司只删条目。列表标记活动 `watch_dir` 落在哪家公司、哪个子目录（`monitored`），但不切换目录或监控。
- API：新增 `GET/POST /api/v1/companies`、`GET/PATCH/DELETE /api/v1/companies/{company_id}`、`GET /api/v1/companies/{company_id}/subdirs/plan`、`POST /api/v1/companies/{company_id}/subdirs/create`；错误码 `COMPANY_INVALID`（422，带 `field`）、`COMPANY_NOT_FOUND`（404）、`COMPANY_REVISION_CONFLICT`/`COMPANY_PLAN_STALE`/`COMPANY_REGISTRY_CORRUPT`（409）、`COMPANY_CONFIRM_REQUIRED`（422）。既有路由、握手能力清单与 `API_CONTRACT_VERSION` 不变。
- 文档：接口流程新增 §3.5.1 并补错误模型 422 行；数据算法新增 §4.6 与运行态条目；文件地图登记服务、路由与测试；任务导航新增快速索引行与“10.3 公司清单”；做账规则页新增“公司清单”规则；设计原因地图、架构入口服务列表同步更新；未来工作总览中 WS-07 改为进行中（第 1 步完成），WS-02 改为后端已完成、界面待做。
- 验证：新增 `tests/test_api_companies.py`（16 个测试函数，参数化后 29 项），接线测试登记 `companies`。macOS 本机全量 pytest（绝对 `PYTHONPATH`）857 项：0 失败，16 项跳过（均为既有平台或环境跳过）；`compileall src tests`、`ruff check --select E9,F`、`git diff --check` 通过。
- 未覆盖：没有前端或页面消费者（`/workspace` 侧栏属 WS-01/WS-02）；未在 Windows、网络盘、大小写敏感卷上实测路径判断；Windows 跳过链接用例；没有原生目录选择器接入；纳税人身份尚未接入成本页 `tax_profile`；未启动 localhost 做浏览器验收；未重建打包产物。只做了本地提交，未推送、未合并。

### 2026-11-10 路由直接依赖领域服务，删除 AppState 转发（ENG-08）

- 需求：ENG-03 完成后，用户要求不等 WS-07，直接把 ENG-08 做掉，去掉 AppState 的转发。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `ac51c09`；在独立 worktree 的 `codex/appstate-direct-services` 施工，主工作区未改动。
- 方案：16 个领域服务从 `self._bookkeeping` 等私有属性改为公开属性（`state.bookkeeping`、`state.documents`、`state.costs`、`state.dossier`、`state.preview_print`、`state.selection`、`state.invoices`、`state.rename`、`state.settings`、`state.monitor`、`state.background`、`state.diagnostics`、`state.about`、`state.appearance`、`state.ocr`、`state.shutdown`）。从现有转发自动生成“方法名 → 服务.方法”映射（123 项），用基于 Python tokenize 的改写器批量改写调用点：只改代码中的属性访问，跳过字符串与注释，按 token 偏移原地替换；接收者限定为 `_state(request)`、`….state.invoice_hub`、已知的 AppState 变量与 app_state.py 内的 `self`。改写覆盖路由 10 个模块、`api/app.py`、AppState 内部回调与 `create_state`、9 个测试文件，共 270 处；`test_tauri_host_rpc.py` 的 `state` 实为 `AboutService`，误改后整份撤回。随后删除 123 个转发。
- 跨对象调用：改写后 AppState 与路由会调用服务的私有方法，11 个改为公开名（`clear_invoice_cache`、`manual_overrides_path`、`monitor_bridge`、`monitor_state`、`outbound_invoice_dir_text`、`persist_watch_dir_config`、`preferences_path`、`recent_outbound_invoice_dirs`、`recent_watch_dirs`、`watch_dir_message`），`BackgroundSyncService` 增加只读属性 `status`；各服务内部持有的同名回调属性不变。跨服务回调全部是每次现查对方服务方法的 lambda。
- 测试迁移：类级打桩 `AppState.run_background_diagnostics`（字符串路径 71 处、`setattr(AppState, …)` 11 处、子进程脚本内 3 处）改为 `BackgroundSyncService`；`AppState.bridge_status/bridge_stop` 改为 `MonitorControlService`；实例打桩 `setattr(state, "方法", …)` 改为打桩在对应服务实例上；读取路由源码文本的两处契约断言改为新的调用写法。接线测试的服务键改为公开属性名，并新增“AppState 公开方法只剩 11 个核心与编排成员”的检查，防止转发回潮。
- 结果：`app_state.py` 770 → 368 行，只剩组装、共享的 config/活动目标/RLock、`health`、任务与事件读取，以及切换 watch_dir、删除所选两条跨域编排；各服务模块说明中“AppState 保留同名转发”的表述改为“路由以 `state.<服务>` 直接调用”。
- 验证：改动前后在临时根目录构建应用，OpenAPI 与路由表 JSON 逐字节一致（路由函数名未变）；静态扫描 `src/`、`tests/`、`scripts/`，没有对已删除 AppState 方法的调用；ruff、compileall 通过；全量 pytest 791 通过、16 跳过；改动前 790 通过，差额是新增的“不再长出转发”检查。变异核对：构造结束后把单据服务的出库目录回调换成提前绑定的方法对象，`test_outbound_partial_preview_and_status_reuse` 失败，说明构造后在服务实例上的打桩会经现查传到其它服务；关闭测试在构造前打桩，提前绑定对它没有影响，这一点如实记录。
- 文档：文件地图、架构入口（依赖方向、服务表、债务表改为当前实现）、设计原因、任务导航、接口流程中的“AppState 转发/经 AppState”改为直接调用；两份设计稿中引用的 AppState 方法改为对应服务；ENG-08 标为已完成。
- 未覆盖：未启动真实 localhost 逐页操作，未重建打包产物，未运行正式 Windows BAT/Tauri 宿主；外部入口（BAT、Tauri、Swift）只经 HTTP 访问，不受影响。

### 2026-11-10 完成 AppState 领域拆分（ENG-03 第七至十六步）

- 需求：用户要求“继续，直到完成 AppState 的全部拆解”。
- 起点与分支：本地开发线 `codex/cost-select-all-transitions` 的 `1dfd3ae`；为少动主工作区，剩余各步在同一个 worktree 分支 `codex/appstate-decomposition` 上逐步提交，最后一次合并。
- 做法：每步都是原样搬移，AppState 保留同名转发；服务读共享的 config、活动 TargetProfile 一律经 provider，每次调用现取，写入持 AppState 同一把 RLock；跨服务协作者以 AppState 方法同名注入，因此测试在 AppState 类上的打桩（`run_background_diagnostics`、`bridge_status/bridge_stop`）仍全局生效。每步用 AST 逐方法比对搬移前后源码，只允许依赖替换；临时根目录构建应用比对 OpenAPI 与路由表 JSON 逐字节一致；ruff 与全量 pytest 通过后才提交。
- 第七步：皮肤/应用图标 → `services/appearance.py`，OCR 页 → `services/ocr.py`。新增 `tests/test_appstate_service_wiring.py`，按服务参数化检查切换 watch_dir 后锁、活动目标、config 仍是 AppState 的同一对象（此前各步拆出的服务一并纳入）。
- 第八步：About 与更新生命周期 → `services/about.py`（`AboutService` 持有宿主更新审批状态、非阻塞生命周期锁与后台检查定时器；`UpdateService` 仍由 AppState 创建）；新增 `host_rpc.desktop_host_mode_enabled()` 供共用。宿主更新测试改为构造空的 `AboutService`，属性名与断言不变；About 链接测试的 `open_external_url` 打桩迁到新模块。
- 第九步：发票列表、手改、一致性、详情与打开源文件（27 个方法）→ `services/invoice_list.py`，读缓存归该服务；AppState 保留 `_clear_invoice_cache` 等供后台同步、重建、重命名、删除调用；第六步留下的两个勾选规则别名删除。读写缓存、替换 `_summary_rows`、打桩 `write_summary_xlsx` 的测试迁到 `state._invoices` 或新模块。
- 第十步：源发票重命名 → `services/invoice_rename.py`（含命名格式常量）。设置页源码契约测试改为读取整个 `services/` 目录，检查的字符串不变。
- 第十一步：设置页数据、config 文件持久化、最近/出库目录、偏好、watch_dir 检查与选择（25 个方法）→ `services/settings.py`（含常量）。切换 watch_dir（`update_settings`）牵动 monitor、缓存、活动目标与启动同步，留在 AppState。config 对象仍归 AppState：原先 3 处“改写配置文件后重新赋值 `self.config`”改为调用注入的 `reload_config`，在同一把 RLock 内给 AppState 重新赋值；变异核对时把它改成空操作，单据测试会失败。`UnsupportedStartupSurfaceError` 移到 `services/errors.py`。
- 第十二步：诊断摘要、配置健康、日志尾部与脱敏支持包 → `services/diagnostics.py`（含支持包上限与排除清单常量）；AppState 里已无用的后缀/投影文件名常量与 `_format_file_mtime` 别名删除。
- 第十三步：后台启动同步（spawn 子进程入口、超时常量与 12 个方法）→ `services/background_sync.py`，后台状态、代际与进程登记归该服务；AppState 保留 `run_background_diagnostics`，`health`/进度读该服务的状态。测试对 `multiprocessing.get_context`、子进程入口与超时常量的打桩，以及对后台状态字段的读写，迁到新模块与 `state._background`。
- 第十四步：monitor 启停/状态/健康、同步进度、手动重建与打开日志/运行目录 → `services/monitor_control.py`。
- 第十五步：结构化关闭 → `services/server_shutdown.py`（含关闭状态字段）；AppState 保留 `server_shutdown_requested` 属性与两个方法转发。
- 第十六步：纯重排。`__init__` 按依赖顺序构造服务，并配一段统一说明（删除已与实际顺序不符的逐步注释）；类体依次为核心成员、两条跨域编排、按服务分组的转发；补模块说明，整理导入顺序。AST 校验：136 个方法源码逐字相同，`__init__` 的 33 条语句集合相同，模块级代码不变。
- 结果：`app_state.py` 3045 → 770 行（全程 5779 → 770）；AppState 只剩组装、共享状态、`health`、切换 watch_dir 与删除所选两条跨域编排，以及 136 个转发。“删除所选”本身只有 31 行，底层已是独立的 `InvoiceTrashService`，又要协调 monitor 写锁、发票与预览缓存和启动同步，属于跨域编排，故留在 AppState。
- 验证：分支上每步全量 pytest 通过，最终 790 通过、16 跳过（11 项 Windows 专用、5 项需另行构建的原生 OFD 组件），起点 774 通过，差额是 16 条参数化接线测试。每个新服务都做了变异核对（锁换成私有 RLock、活动目标或 config 改为构造时快照），接线测试或既有行为测试都会失败。
- 文档：文件地图逐一登记新文件与接线测试；架构入口、设计原因、任务导航中指向实现位置的 `AppState.xxx` 改到新模块，经转发仍成立的表述未改；ENG-03 标为已完成，新增 ENG-08（路由直接依赖领域服务、删除转发门面，建议随 WS-07 一起做）。
- 未覆盖：未启动真实 localhost 逐页操作，也未重建任何打包产物或运行正式 Windows BAT/Tauri 宿主；转发门面与类级打桩仍在，路由尚未直接依赖领域服务（ENG-08）。

### 2026-11-10 AppState 拆出发票勾选服务（ENG-03 第六步）

- 需求：用户要求继续 ENG-03。上一轮建议把勾选合计连同勾选复核辅助方法拆成发票勾选服务，让单据、预览/打印直接依赖它，去掉第二、五步留下的勾选回调。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `829cb00`；在独立 worktree 的 `codex/appstate-selection-service` 施工，主工作区未改动。
- 方案：新文件 `services/invoice_selection.py`。AppState 原有的 5 个勾选规则静态方法（文件名 20 位号码、来源身份、同票分组键、金额解析、文件格式）改为模块级纯函数；勾选复核（`validated_invoice_selection`）、勾选合计及其两个辅助方法迁入 `InvoiceSelectionService`。单据专用的入库勾选核对 `_validated_inbound_selection` 从 AppState 移入 `DocumentService`；单据与预览/打印改为直接依赖勾选服务和纯函数，原先的 5 个勾选回调删除。发票列表 `list_invoices`（缓存、一致性、重建）仍在 AppState，以回调交给勾选服务，每次调用现取（`test_documents.py` 会在实例上替换它）。AppState 保留 `_validated_invoice_selection` 转发（发票详情路由与删除所选仍调用）、`invoice_selection_summary` 转发，以及列表/一致性代码仍在用的 `_invoice_number_from_filename`、`_file_format_from_source` 两个别名。`services/__init__.py` 改为直接从 `errors.py` 导出 `StaleInvoiceSelectionError`（同一个类，`app_state` 不再导入它）。
- 结果：`app_state.py` 3216 → 3045 行，方法 197 → 189；新文件 `invoice_selection.py` 221 行；`documents.py`、`preview_print.py` 只改构造参数与调用名。
- 验证：搬移前后逐函数/方法对比，只有名称替换（去掉 `self.` 与下划线前缀、回调改为直接调用）；OpenAPI 与路由表 JSON 逐字节一致；ruff 通过；新增两条测试——切换 watch_dir 后旧目录的勾选被判为过期、服务读到新目标，且发票列表经 AppState 实例现取；勾选合计会等待 AppState 的锁。变异核对三种：活动目标改为构造时快照、锁换成私有 RLock、发票列表在构造时绑定，各自被对应测试抓住。既有的单据、预览/打印守护测试照常通过。全量 pytest 774 通过、16 跳过，基线 772 通过（差额即两条新测试）。
- 未覆盖：未在真实浏览器操作首页勾选合计、批量入库、预览与打印；未重建打包产物。`INTERFACES_AND_FLOWS.md` 中 `AppState.invoice_selection_summary()` 的表述经转发仍成立，且该文件在主工作区有未提交修改，本轮未改。

### 2026-11-10 AppState 拆出预览/打印编排服务（ENG-03 第五步）

- 需求：用户要求继续 ENG-03 下一步，即上一轮建议的预览/打印。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `b20b030`；在独立 worktree 的 `codex/appstate-preview-service` 施工，主工作区未改动。
- 方案：把首页勾选转成预览源与同票 PDF 打印源、创建/读取/续租 job、受限打开的 16 个方法原样迁到新的 `services/preview_print.py::InvoicePreviewPrintService`，AppState 保留 9 个同名转发。`FilePreviewService` 与 `InvoicePrintService` 实例仍由 AppState 创建后传入：AppState 在切换目录与重建时清空它们，临时识别共用预览池，测试也直接读取 `state._file_preview_service`。勾选校验、同票分组键、来源身份与文件格式这 4 个辅助方法属于发票列表/勾选规则，仍在 AppState，以回调注入；创建预览仍持 AppState 同一把 RLock，活动目标经回调实时读取。预览拆走后 `AppState._path_is_under_root` 别名已无调用，随之删除。
- 测试迁移：`test_file_preview.py` 预览“打开文件/位置”用例的 `open_local_path` 打桩目标从 `services.app_state` 改为 `services.preview_print`，断言不变。
- 结果：`app_state.py` 3515 → 3216 行，方法 204 → 197；新文件 `preview_print.py` 398 行。
- 验证：搬移前后逐方法对比，只有回调与受控根判断的名称替换；OpenAPI 与路由表 JSON 逐字节一致；ruff 通过；新增两条测试——切换 watch_dir 后旧目录源文件被预览拒绝（`source_changed`）、打印不再选用、服务读到的是新目标；预览创建会等待 AppState 的锁——变异核对时（构造时快照、私有 RLock）各自失败。全量 pytest 772 通过、16 跳过，基线 770 通过（差额即两条新测试）。
- 未覆盖：未在真实浏览器打开预览弹窗或打印页；未重建打包产物。

### 2026-11-10 AppState 拆出业务资料夹服务（ENG-03 第四步）

- 需求：用户要求继续 ENG-03，拆业务资料夹。做账已依赖它推断公司目录，多公司工作区（WS-02/WS-07）也会直接复用。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `eebae53`；在独立 worktree 的 `codex/appstate-dossier-service` 施工，主工作区未改动。
- 方案：公司目录推断、有界扫描、快捷入口与受限打开的 9 个方法，连同只在这里用的 4 个扫描常量（目录名、子目录提示、目录项上限、时间上限），原样迁到新的 `services/dossier.py::BusinessDossierService`；AppState 保留 `business_dossier`/`open_business_dossier` 转发。唯一有意的改名：`_business_dossier_root` 在服务里改为公开的 `business_dossier_root`，做账的公司目录回调改为直接调用它，不再经 AppState 私有方法。统计“发票源”文件的后缀集合改为引用 `extraction/parsers.py::SUPPORTED_EXTS`（与 AppState 原常量同为 `.pdf/.ofd/.xml`），避免反向导入 `app_state`。资料夹代码本来不取 AppState 锁，迁移后仍不取。
- 测试迁移：`test_business_dossier_scan_is_bounded_and_marks_partial_counts` 与 iterator-OSError 用例的打桩目标从 `services.app_state` 改为 `services.dossier`（扫描上限常量、`os.scandir`），断言不变。
- 结果：`app_state.py` 3815 → 3515 行，方法 211 → 204；新文件 `dossier.py` 362 行。
- 验证：搬移前后逐方法对比，只有上述改名一处；OpenAPI 与路由表 JSON 逐字节一致；ruff 通过；新增 `test_business_dossier_follows_watch_dir_switch`（切换 watch_dir 后资料夹、快捷入口与打开范围都指向新公司，旧公司路径拒绝打开）。变异核对：资料夹服务改为构造时快照后，这条新测试和既有的做账目录跟随测试同时失败。全量 pytest 770 通过、16 跳过，基线 769 通过（差额即新测试）。文档同步了架构地图、设计原因、任务导航与两份税务设计稿里的符号引用；`rules/BOOKKEEPING.md` 的代码定位行因与主工作区未提交修改相邻，本轮未改。
- 未覆盖：未在真实 localhost 首页点击资料夹入口；未重建打包产物。

### 2026-11-10 AppState 拆出成本编排服务（ENG-03 第三步）

- 需求：用户同意继续 ENG-03，上一轮建议的下一块是成本。开工后实测发现成本在 AppState 里只剩 5 个方法、约 110 行（算法早已在 `projections/` 里），比上一轮描述的小。已向用户说明这一点，并改为建议下一步拆业务资料夹；成本按约定先做完。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `7e47fbd`；在独立 worktree 的 `codex/appstate-cost-service` 施工，主工作区未改动。
- 方案：`cost_service`、`cost_snapshot`、`cost_view`、`save_cost_reference_status`、`open_cost_summary` 原样迁到新的 `services/costs.py::CostService`，AppState 保留同名转发（AppState 内其它 7 处 `cost_service()` 调用和测试不变）。服务拿到 AppState 同一把 `_lock`、SQLite 仓库与 `layout.db_path`，活动 TargetProfile、config（加价率）与最近目录经回调读取；保存开票参考后清发票缓存是 AppState 的职责，经回调注入。只依赖 TargetProfile 的 `_background_profile_identity` 移到 `targets/paths.py::profile_identity`，AppState 以原名导入，避免循环导入。
- 结果：`app_state.py` 3905 → 3815 行；5 个方法都是公开方法，方法数不变（211）；新文件 `costs.py` 173 行。
- 验证：搬移前后逐方法对比，只有依赖替换（活动目标、数据库路径、身份函数名）；OpenAPI 与路由表 JSON 逐字节一致；ruff 通过；新增两条测试——切换 watch_dir 后成本视图与 `cost_service()` 指向新目录、成本视图会等待 AppState 的锁——变异核对时（构造时快照、私有 RLock）都会失败。全量 pytest 769 通过、16 跳过，基线 767 通过（差额即两条新测试）。
- 未覆盖：未在真实 localhost 成本页操作；未重建打包产物。

### 2026-11-10 AppState 拆出单据服务（ENG-03 第二步）

- 需求：用户确认继续 ENG-03，按计划拆单据（入库/出库）用例。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `7ab3f5d`（已含第一步）；在独立 worktree 的 `codex/appstate-document-service` 施工，主工作区未改动。
- 方案：单据两段代码（默认值与单据目录状态、首页批量入库核对、入/出库预览、导出状态、导出、打开，共 27 个方法）原样迁到新的 `services/documents.py::DocumentService`，AppState 保留 15 个同名公开方法转发。边界取舍：出库目录的选择/校验/保存/最近记录会改写配置，属于设置用例，留在 AppState；首页勾选身份校验（`_validated_inbound_selection`）依赖发票列表规则，也留在 AppState，以回调注入。服务通过构造参数拿到 AppState 同一把 `_lock`、SQLite 仓库，以及由 AppState 创建的 `DocumentIndex`/`InboundDetails`（documents 路由仍直接读 `_document_index` 状态）；活动 TargetProfile、成本明细路径、出库目录一律经回调实时读取。出库预览文件名元数据缓存改由服务持有（AppState 其它代码从未使用）。`StaleInvoiceSelectionError` 移到新的 `services/errors.py`，避免与 `app_state` 循环导入，`app_state` 与 `services` 包仍导出同一个类。预览与单据共用的受控根判断改为 `targets/paths.py::path_is_under_root`，AppState 的 `_path_is_under_root` 指向它。
- 测试迁移：两处打桩随代码迁移——`test_documents.py` 的“文件被占用”改为打桩 `DocumentService._document_path_occupied`；`test_progressive_loading.py::test_outbound_partial_preview_and_status_reuse` 改为打桩 `state._documents.document_state` 与 `services.documents.build_outbound_preview`，断言不变。
- 结果：`app_state.py` 4209 → 3905 行，方法 224 → 211；新文件 `documents.py` 423 行。
- 验证：搬移前后逐行对比，只有依赖替换（成本明细路径、出库目录、最近出库目录、勾选校验、受控根判断、默认值路径）和空行差异；OpenAPI 与路由表 JSON 逐字节一致；ruff 通过；新增两条测试——切换 watch_dir 与出库目录后 `/api/v1/documents/state` 跟随新目录、单据导出会等待 AppState 的锁——变异核对时（回调改为构造时快照、锁换成私有 RLock）各自失败。全量 pytest 767 通过、16 跳过，基线 765 通过（差额即两条新测试）。
- 未覆盖：未在真实 localhost 页面导出/打开单据，也未用 Excel/WPS 打开导出文件（工作簿写出函数未改动）；未重建打包产物。

### 2026-11-10 AppState 拆出做账服务（ENG-03 第一步）

- 需求：用户要求先处理 ENG-03。`services/app_state.py` 5779 行、234 个方法，多公司工作区（WS-07）之前需要按领域拆开；未来工作总览定的顺序是先做账、再单据。
- 起点：本地开发线 `codex/cost-select-all-transitions` 的 `3b88a74`（领先 `main`，含路由拆分）；主工作区有未提交修改，本轮在独立 worktree 的 `codex/appstate-bookkeeping-service` 施工，未改动主工作区。
- 方案：做账区段（33 个方法，含 10 个私有辅助）原样迁到新的 `services/bookkeeping.py::BookkeepingService`，只替换两处对 AppState 的依赖（公司资料夹、成本明细路径）。服务通过构造参数拿到 AppState 同一把 `_lock` 与 SQLite 仓库，活动 TargetProfile、config、公司资料夹与成本明细路径一律经回调实时读取，不缓存快照（切换 watch_dir 会替换这些对象）。AppState 保留 23 个同名公开方法转发，路由、测试调用和 monkeypatch 路径都不变；方法内的延迟导入原样保留。
- 结果：`app_state.py` 5779 → 4209 行，方法 234 → 224（剩余的做账方法只是一行转发）；新文件 1706 行。
- 验证：搬移前后逐行对比，除 6 处依赖替换外完全相同；临时根目录构建应用，OpenAPI（128 条路径）与路由表 JSON 逐字节一致；ruff 通过；新增两条测试——切换 watch_dir 后 `/api/v1/bookkeeping/setup` 指向新公司资料夹、做账写入会等待 AppState 的锁——并做变异核对：把回调改成构造时快照、把锁换成私有 RLock 后两条测试都会失败。全量 pytest 765 通过、16 跳过（11 项 Windows 专用、5 项需另行构建的原生 OFD 组件），基线同口径 763 通过（差额即两条新测试）。
- 未覆盖：未启动真实 localhost 页面点做账流程（HTTP 契约由 API 测试覆盖）；未重建打包产物；路由仍经 AppState 转发，直接调用领域服务并删除转发留到后续步骤。

### 2026-11-09 修复测试导入 api.app 时改写仓库运行态（ENG-07）

- 需求：用户要求先修复 ENG-07。现象：在主工作区跑全量 pytest 会改写仓库自身的 `runtime/`（`server_state.json`、`invoice_hub.db`、默认 target 汇总与监控状态）和 `发票文件/` 下的空成本产物；若本机配置指向真实目录，跑测试就会同步真实发票目录。
- 原因：`api/app.py` 末尾的模块级 `app = create_app()`，任何 `import invoice_hub.api.app`（11 个测试文件在进程内导入）都会按仓库默认配置构造 AppState 并执行启动同步。
- 方案：删除模块级实例；`api/main.py` 在设置 `INVOICE_HUB_ROOT/CONFIG` 并做端口预检后调用 `create_app()`，仍只构造一份 AppState 与一条 startup sync（BAT、Tauri、Swift 均经 `python -m invoice_hub.api.main` 启动，无其它 `api.app:app` 引用）。新增 `tests/conftest.py` 会话级守护：测试前后快照 `runtime/`、`发票文件/`、`config/`，任一文件变化即让整轮失败（`INVOICE_HUB_SKIP_REPO_STATE_GUARD=1` 仅供本 checkout 有服务在运行时跳过）；新增子进程测试断言导入模块不构造 AppState。工作分支 `codex/fix-api-import-side-effect`，基于本地开发线 `codex/cost-select-all-transitions`。
- 验证：全量 pytest 840 通过、16 跳过，前后快照无变化；新测试在旧代码上失败、新代码上通过；守护在“测试全部通过但写入 `config/` 探针文件”时使退出码为 1，并列出文件；ruff 通过；既有 CLI 单 AppState、初始状态目录与参数缩写测试通过。
- 未覆盖：未重新运行真实 BAT/Tauri/Swift 启动（入口命令未变，仅 `main.py` 内部构造方式变化，由 CLI 子进程测试覆盖）；验证旧代码时又对仓库默认空目标做过两次同步，内容仍是空汇总，未恢复。

### 2026-11-09 工程门禁、API 路由拆分与 Vue 工作区前端基础

- 需求：新界面原型落地前，用户请求评估工程防护与架构（含“Tauri 多层嵌套是架构灾难”的说法），并按评估建议实施；前端框架选定 Vue 3。
- 起点：`codex/cost-select-all-transitions` 的 `ed90a2b`（该分支领先 `main` 9 个提交且未合并）；主工作区的未提交修改保持不动，本轮在独立 worktree 的 `codex/engineering-guardrails` 施工。
- 评估结论：Tauri + Python 后端本身不是问题，WebView 无 IPC、业务只在 Python 的边界成立；主要风险是三套桌面入口并存、固定 TCP 端口带来的所有权代码、`AppState` 单体（约 5800 行）、`api/app.py` 单文件 127 条路由、前端缺少行为测试、约 1 万行 Rust 未进 CI、无静态检查。
- CI 与静态检查：新增 hash 锁定的 ruff（独立 `lint-tools` 锁，不改动 Windows 重打包绑定的 test-tools 锁），规则 E9+F，修复 32 处（24 处未使用导入、3 处仅注解内的未定义名、未使用变量等，无行为变化）；`costs.py::save_reference_status` 的未使用工作簿读取保留并登记 ENG-02。新增 Rust 作业（macOS 以 `-D warnings` 阻断，Windows 暂只报告，ENG-01），清理 macOS 上的 12 处 clippy 警告（语义等价）。`host_rpc` 的 socket 测试在无法连接时改为 5 秒内失败，不再挂起整个测试二进制。Node 交互测试 `tests/*.test.cjs` 进入两平台 CI；Swift 参考壳测试改为路径触发。
- 路由拆分：`api/app.py` 由 1546 行降为约 330 行；领域路由进入 `api/routes/{settings,invoices,costs,documents,dossier,appearance,monitor,bookkeeping,ocr,system}.py`，辅助进入 `api/common.py`，各路由组在原位置 `include_router`。拆分前后 OpenAPI 逐字节一致，792 个方法×路径样本命中同一端点。读取源码文本的契约测试改为读取全部 API 模块。
- Vue 前端基础：`frontend/`（Vue 3.5、Vue Router 5、Pinia 4、Vite 8、TypeScript 5.9、Vitest 5，精确版本 + pnpm 锁）；构建以固定文件名提交到 `web/static/app/`，`?v=` 内容哈希刷新缓存，发布打包与白名单无需改动；FastAPI 新增 `/workspace/*`（no-store、不进 OpenAPI）。外框含模块列、`KeepAlive` 页面缓存、只读概览/目录视图；THIRD_PARTY_NOTICES 增加 Vue/Vue Router/Pinia。
- 文档：FILE_MAP（目录规则、API 路由组、15.1 Vue 前端）、接口流程（`/workspace` 与路由分布）、任务导航（9.2 新任务、API 入口、常用命令）、WEB_UI 规则（Vue 工作区前端）、设计原因、平台验证分工、架构债务表、AGENTS.md 一条全局约束；未来工作总览新增 ENG-01—06（含延后的 AppState 拆分、入口文档去日志化、真实浏览器 E2E）。
- 验证：全量 pytest 通过（Windows 专用用例跳过）；ruff 通过；`cargo fmt --check` 与 macOS `clippy -D warnings` 通过；`cargo test` 97 项通过，4 项真实回环 socket 测试因本机网络策略禁止回环 TCP 连接而失败（Python 同样无法连接回环端口，非代码问题）；Node 交互测试 30 项通过；前端类型检查、8 项组件测试通过，构建两次逐字节一致；release 内容扫描对构建产物通过；临时后端（临时目录、端口 8899）+ 专用 Chrome 核对 `/workspace` 概览/目录/深链接、`?v=` 资源、390px 无横向溢出、旧首页可加载。
- 未覆盖：GitHub CI 未实际运行（未推送）；Windows clippy 结果未知；未重建 Windows/macOS/Tauri 打包产物；未覆盖正式 Windows BAT、原生选择器、皮肤与 `?no_skin=1`（`/workspace` 不注入皮肤）；`KeepAlive` 在真实浏览器只能间接核对（生产构建不暴露组件实例），由组件测试覆盖。

### 2026-11-09 Agent 接入设计提案

- 需求：用户希望未来设计中 InvoiceHub 能让各个 Agent 接入并即时读取、操作，接入方式以 Vibe Island 这类软件为例。
- 过程：在本机只读观察 Vibe Island 的接入形态（按 Agent 写入 hook / 插件适配器并先备份配置、统一桥接程序带来源标签、本机 socket 与对端身份核验、权限请求在应用内批准后 Agent 继续），对照现有 HTTP 接口表、同源写校验、SSE 事件与做账授权边界。结论：hook 只能让 Agent 推送事件，不能查询数据，所以借鉴其安装、通道、身份与审批形态，数据面改用 MCP。
- 方案：新增 `docs/AGENT_ACCESS_DESIGN.md`（`invoicehub mcp` + 后端 Agent 网关、配对令牌、L0 只读 / L1 可撤销写 / L2 落盘 / 禁止项四级、应用内审批与活动面板、一键安装适配器、与现有不变量的对照、分阶段与验收要点）；未来工作总览新增设计索引行与 AGENT-01—03；文件地图新增该文件。§0 列出待用户确认的决策。
- 用户确认（同日）：接入形态即参照 Vibe Island；先只读，目标是灵活控制；首批 WorkBuddy 优先，其次 Codex、Claude Code。据此在设计中补充 §5.6 灵活控制模型（规则 = Agent × 目录 / 期间 × 模块 × 明细粒度 → 允许 / 询问 / 拒绝；预设、询问卡片、规则表与模拟三层界面），本机只读观察 WorkBuddy 的 MCP 配置、skills 目录与 hooks 形态写入 §7；AGENT-01 并入控制模型与 WorkBuddy 优先，AGENT-03 改为 P3 暂缓。
- 辅助导入（同日用户提出）：用户放入 Excel / PDF（对账单、回单等）而软件识别不好时由 Agent 辅助识别纠错。设计新增 §8：软件先识别，失败才生成“需要协助”的导入任务；Agent 优先起草版式档案、兜底逐格更正（必须指向原文坐标）；软件用 `bank/checks.py` 同类校验（余额链、合计笔数、衔接、回单匹配）零写入核对，Agent 可反复修改；通过后只进导入暂存，用户确认才入底稿，版式档案入库后同版式不再需要 Agent；无自检结构的表逐行人工确认。未来工作总览新增 AGENT-04（依赖 BANK-01、AGENT-01、AGENT-02），BANK-01 增加关联说明。
- 验证：文档契约测试与 `git diff --check`。
- 未覆盖：纯设计，未实现任何接口；WorkBuddy 是否支持 stdio 型 MCP 条目及各 Agent 配置格式落地时再逐一核实。随本次本地提交，未推送。

### 2026-11-08 提交设计稿、原型与未来工作总览

- 需求：用户要求先把设计文件提交，避免这几轮的设计决策只留在本地未跟踪文件里。
- 范围：`docs/PRODUCT_BACKLOG.md`（未来工作总览：设计稿与原型索引、COST / WS / BANK / BK / OCR 条目与 BUG-01）、`docs/COST_ANALYSIS_V2_DESIGN.md`（含 2026-11-05 / 11-08 决策：税率、科目不另建、品目表首版范围）、`docs/design/workspace-sidebar-prototype.html`（多公司工作区原型，含新版成本分析模块）、税务工作台设计四份（`TAX_WORKBENCH_DESIGN`、`TAX_ALGORITHMS_AND_POLICY`、`TAX_POLICY_SOURCES_AND_REVIEW`、`TAX_WORKBENCH_VALUE_AND_READINESS`）、`docs/architecture/rules/TAX_WORKBENCH.md` 与 `docs/design/tax-calculator-prototype.html`；未来工作总览的设计索引链接到税务设计，所以一并提交以免断链。同步只与这些文件相关的索引行：文件地图条目、任务快速索引的“税务”“未来工作”两行与税务任务小节、AGENTS.md / CLAUDE.md 的税务与未来工作两句、架构总入口的税务设计入口、成本 / 做账 / 提取规则页的“待开发优化”行、文档契约测试的税务规则页名，以及记录这些文件来历的 CHANGELOG 小节。`docs/AGENT_HANDOFF.md` 及交接工具、`bank/` 等其他未提交工作不在本次范围。
- 检查：提交前扫描这些文件，未含真实公司名称、票号、金额或本机路径（原型只有“示例××”合成数据）；全部本地链接均指向已跟踪文件或本次文件；导出暂存树运行文档契约与全量测试。
- 未覆盖：设计稿和原型都不是已实现能力；原型只用合成数据。未推送。

### 2026-11-08 开票参考全选、sheet 平滑切换与工作区原型成本分析模块

- 需求：用户认可上一步，要求新增全选 / 清空全选；sheet 选择点击后页面刷新非常突兀，改成平滑过渡；成本分析板块针对新版页面做适配，经确认指多公司工作区原型里的“成本分析”模块。
- 起点：移除与操作区重排先在 `codex/cost-reference-exclusions-ui` 本地提交 `c062d1a`（只暂存本轮改动；导出暂存树单独测试 756 passed）；从该提交新建 `codex/cost-select-all-transitions`。
- 排查：切换 sheet 走“重新读取”流程——显示读取进度条、`render()` 清空并重建全部四个表格和设置 / 销项面板 / 统计卡片；清空瞬间页面变短。浏览器 A/B（上一提交 vs 本轮，同一份真实目录副本，6 次切换）：旧版每次切换都出现进度条（共 30 次显示变化）、每次重画面板 12 处；第一次切到开票参考时滚动从 420 被拉回 0。逐帧追踪确认根因：切换瞬间对空表排了一次高度测量，得到约 620px 的上限，行数据到达后撤掉保底高度时表格仍被该上限截短，页面高度短暂降到一屏，浏览器把滚动收回；另有后台事件流重连触发的自动刷新在数据未变时也整页重建。
- 方案：`loadCostsNow` 把 `tab` / `page` 视为视图切换（不显示进度条），同一修订号只渲染目标 sheet；`render()` 拆出 `renderCostChrome()`，自动刷新且修订号未变时只更新状态文字；整页重绘时保留当前 sheet 高度与滚动位置；`setText` / `setHtml` 值不变不写 DOM；切换时未渲染的 sheet 先保持原 sheet 高度并标 `aria-busy`，`finishCostViewSwap` 先按新行同步测量表格高度再释放；空表不提前测量；新 sheet 140ms 透明度淡入（`prefers-reduced-motion` 时不播）。开票参考面板新增“全选（N 行）/ 清空全选”，全选按同一修订号逐页读取全部行（修订号变化即中止并提示），操作条显示“已选 N / M 行”，“取消选择”改名“清空全选”。资源版本依次 `20261108-cost-smooth-tabs` → `-2` → `-3`。工作区原型 `docs/design/workspace-sidebar-prototype.html` 的“成本分析”由占位改为可交互模块：按公司计算（纳税人身份取自公司资料夹，销项直接读同公司“开具发票”，不再有全局开具目录；缺目录可一键创建；服务型销项说明不按数量比对；未归属公司的目录只看明细），数量在前的开票参考（来源 N 张、按销项更新、全选 / 清空全选、从开票参考移除与已移除管理、品目表合并与类型），底部深色操作条沿用首页样式且勾选只做局部更新，sheet 子标签切换不播入场动画并保留滚动；原型说明新增一条。
- 文档：成本规则页（全选与视图切换规则）、设计原因、实现状态、未来工作总览原型索引。
- 验证：全量 `pytest` 834 passed、16 skipped；`node --check` 通过。真实目录副本 A/B 结果（本轮，两轮一致）：6 次切换滚动位移均为 0、CLS 0、进度条显示 0 次、面板重画 0 处，已渲染过的 sheet 约 30ms 显示；全选得到“已选 37 / 37 行”，第 2 页 7/7 已勾选，清空后操作条消失；页面无脚本错误。原型经专用 Chrome 加载：成本分析模块在示例商贸显示设置与比对面板（数量一致 0 / 待更新 3 / 销项超过进项 1），勾选与全选不替换表格元素，按销项更新后 3 行未保存、保存后数量一致 2，移除 / 恢复、来源发票抽屉正常，示例建设显示服务型说明，示例科技成本口径为含税，无脚本错误；截图检查。验收后停止服务并删除 `/tmp` 副本。
- 未覆盖：深色 / 其他皮肤、窄屏、Windows、打包产物；原型只用合成数据，不代表后端已支持按公司读取开具发票（WS-07）。随本轮本地提交（原型与未来工作总览为未跟踪的设计文件，不在本次提交内），未推送。

### 2026-11-08 开票参考移除与成本页操作区重排

- 需求：开票参考要能选择内容 / 发票来源进行移除；成本分析页按钮太多、勾选后按钮也多，要求用 UI 设计 skill 按思路重新设计排版。用户确认“移除”只是从开票参考排除（可恢复，不动源文件），并先提交品目表。
- 起点：品目表在 `codex/cost-item-catalog` 本地提交 `0d35fe9`（只暂存本轮改动；导出暂存树单独测试 752 passed，排除需 git 仓库的发布锁哈希测试）；从该提交新建 `codex/cost-reference-exclusions-ui`。
- 设计：调用 ui-ux-pro-max（数据密集型财务工具），采用其每屏一个主按钮、溢出菜单、勾选后批量操作条、可撤销 / 恢复代替确认弹窗、操作结果反馈、键盘可达等原则；配色与字体沿用项目现有皮肤以保持全站一致，不引入其推荐配色与字体。
- 方案：`cost_analysis.py` 新增 `reference_invoice_id`、`parse_reference_exclusions`（严格）、`reference_exclusions_from_status`（容错）；`canonical_reference_rows` 与 `canonical_outbound_items` 接受移除清单（来源发票整张排除；被移除行的销项不再算未对上）；`STATUS_PRESERVED_KEYS` 加入 `reference_exclusions`。`costs.py` 行新增 `sources`（按发票汇总的来源），快照新增 `reference_exclusions`（含显示信息与是否仍在明细中），保存接受 `reference_exclusions` 并补全显示信息；工作簿同口径。`/costs`：命令栏为视图切换 + 刷新 + 重新汇总 + “更多”（打开成本分析表、复制当前表格，菜单可 Esc 关闭、点击外部关闭）；“本公司设置”面板放入品目表入口；开票参考新增“来源 N 张”列与来源发票弹窗、“已移除 N 项 · 管理”弹窗（逐项 / 全部恢复）；底部浮出操作条按“已开数量（设为全部已开 / 清零 / 按销项更新）· 加价率（应用并锁定 / 解锁）· 从开票参考移除 / 取消选择”分组，有草稿时显示“N 行未保存 · 放弃修改 · 保存状态”，有草稿时禁止移除；操作条出现时内容区预留底部空间。数量比对单元格允许换行，长提示不再压到相邻列。`#referenceTable` 为 19 列重排列宽（最小 2228px）；移除未使用的 `.cost-actions` 样式。资源版本先后为 `20261108-cost-actions-redesign` 与 `20261108-cost-actions-2`（改动单元格包裹后未升版本时浏览器沿用缓存旧脚本，已补升）。
- 文档：成本规则页（移除语义、操作区规则、资源版本提醒）、数据与算法 §9.3.2、接口与流程、设计原因、任务导航、实现状态。
- 验证：全量 `pytest` 834 passed、16 skipped；新增 4 项覆盖移除品目行后统计 / 工作簿排除而明细与已开状态保留并可恢复、移除来源发票后数量减少、非法清单拒绝且不写文件并在其他保存与重新汇总写入后保留、被移除行的销项不算未对上。真实目录副本（复制到 `/tmp`，原目录只读）启动源码服务，经专用 Chrome DevTools 协议（禁用缓存）：初始无操作条；“更多”打开后焦点进入首项、Esc 关闭；勾选 2 行出现选择区“已选 2 行”；“设为全部已开”后出现“2 行未保存”且移除禁用，“放弃修改”清空；移除 2 行后 37 → 35 行并提示未删除文件；螺纹钢 18E 来源 5 张，移除 1 张后数量 49.404 → 37.056；管理弹窗恢复 1 项、再全部恢复回到 37 行与 49.404；Esc 取消勾选；页面无脚本错误；逐元素检查数量比对单元格无溢出，截图检查命令栏、操作条、两个弹窗与换行。
- 未覆盖：深色 / 其他皮肤、窄屏（< 1100px）下操作条换行、TSV 复制新列、Windows、打包产物。随本轮本地提交，未推送。

### 2026-11-08 品目表首版（COST-02）

- 需求：用户问新系统要不要像电子账套那样设置科目，还是只设库存名称供人工修改。按建议确认：本系统不另建科目体系（账套是科目与账本真值），只维护品目表；科目对照以后从读回的账套选择、做账时接入；固定科目按导入模板配置（BK-01）。决策写入成本分析 v2 设计 §0、§3.1、§3.3 与 COST-02，随后开始做品目表。
- 起点：COST-03 与排版调整先在 `codex/cost-outbound-invoiced` 本地提交 `9154334`（只暂存本轮改动；导出暂存树单独测试 745 passed，排除需 git 仓库的发布锁哈希测试）；从该提交新建 `codex/cost-item-catalog`。
- 核查：真实目录同时有“螺纹钢 18E”和“螺纹钢 18”，是不同牌号，原待办中“E 后缀规范化”会误合并，改为只统一全角半角与空白（不改大小写）；同一材料在不同发票上叫“三级抗震盘螺HRB400E”与“盘螺”，导致开票参考拆成两行、销项对不上；油品、电梯混在开票参考里。
- 方案：`cost_analysis.py` 新增品目表解析（`parse_item_catalog` 严格 / `item_catalog_from_status` 容错）、`resolve_item`（沿改名链取最终标准名称与其类型、税率）、`normalize_spec_text`、`canonical_reference_rows`（分组前归一并保留 `_member_key`）、`canonical_outbound_items`（销项汇总按品目表重新归组，不重读文件）、`merged_status_item`（按成员键查已保存状态：合并相加、拆分按数量分摊、需要时带 `merge_note`）与 `item_catalog_overview`；两个状态写入函数统一保留 `STATUS_PRESERVED_KEYS`（`tax_profile`、`item_catalog`）。工作簿、`costs.py` 读取与保存都先归一；保存品目表时 `_migrate_statuses_to_catalog` 把已开状态一次性写到新键（`member_keys`、`quantity_total`）并移除被并入的旧键，退出开票参考的名称保留原状态。非货物不进开票参考与其统计；品目税率覆盖公司税率，行字段 `reference_output_tax_rate(_percent)` 供页面联动。快照新增 `item_catalog`，行新增 `member_keys/merge_note`；`POST /api/v1/cost-analysis/reference-status` 接受可选 `item_catalog`。`/costs` 工具栏新增“品目表”弹窗（标准名称带全部名称候选、类型、销项税率、规格数、单位、数量合计），开票参考有草稿时禁止保存；合并 / 拆分后需核对的行在数量比对列标“已开数量待核对”。资源版本 `20261108-cost-item-catalog`。
- 文档：成本规则页、数据与算法 §9.3.1、接口与流程、设计原因、任务导航、实现状态、未来工作总览 COST-02、成本分析 v2 设计 §0 / §3.1 / §3.3 / §9。
- 验证：全量 `pytest` 830 passed、16 skipped；新增 7 项覆盖改名合并后数量与已开快照相加并写回新键、拆分按数量分摊、非货物排除与品目税率、全角规格归一后找到旧键状态、其他保存与重新汇总写入不丢品目表及非法输入拒绝且不写文件、销项按品目表重新归组、无已开数量且加价率一致时合并不提示核对。真实目录副本（复制到 `/tmp`，原目录只读）启动源码服务，经专用 Chrome DevTools 协议在弹窗中把“三级抗震盘螺HRB400E”并入“盘螺”、油品设为费用、电梯设为固定资产并保存：开票参考 37 行变 31 行，盘螺 8 = 52.909 + 120.34 = 173.249、盘螺 10 = 5.77 + 122.951 = 128.721，油品与电梯移出，无销项由 18 降为 12，未误报“待核对”，页面无脚本错误；截图检查弹窗与表格。
- 未覆盖：科目对照（第二层）；按规格设置别名；税收分类不同的同名品目不会合并；深色 / 其他皮肤、TSV 复制、Windows、打包产物。随本轮本地提交，未推送。

### 2026-11-08 销项比对按数量一致为原则调整排版

- 需求：用户用真实公司目录（副本）看过销项比对后，认为比之前有优化，要求优化排版；并明确开票中价格有变动属正常，原则是保证库存数量与票面一致。
- 核查：原排版把税务设置与销项比对上下堆叠，开票参考表 18 列中数量比对位于最右，需横向滚动才看到；`updateReferenceRowByKey` 按固定下标更新单元格，调整列顺序会错位。
- 方案：税务设置与“销项数量比对”改为并排两栏（≤1100px 上下排列），比对面板顶部用状态标签显示数量一致 / 待更新 / 销项超过进项 / 无销项（`outbound_overview` 按全部行与保存的已开数量统计，新增 `quantity_match_count/quantity_pending_count/oversold_count/no_outbound_count`），读取统计一行、未对上品目折叠、目录路径放到悬停提示。开票参考表列顺序改为 选择、发票代码、名称、规格、单位、数量、已开数量、销项数量、数量比对、未开数量、开票状态，其后才是含税单价、加价率、实际加价率、参考价税合计、已开参考价税合计、未开参考金额、成本口径；“销项比对”列改名“数量比对”，销项超过进项用危险色，实际加价率不着色。草稿联动改为按列 key 定位单元格（`referenceColumnIndex`）。`#referenceTable` 列宽按新顺序重排，最小宽度 2156px（前 11 列 1222px 在常规窗口内不用滚动）。资源版本统一为 `20261108-cost-quantity-layout`。工作簿列顺序不变。
- 验证：全量 `pytest` 823 passed、16 skipped。真实目录副本（复制到 `/tmp`，原目录只读）启动源码服务，经专用 Chrome DevTools 协议：1500px 下两栏同一行、表头前 12 列无需滚动可见，计数“数量一致 0 / 待更新 19 / 销项超过进项 0 / 无销项 18”；1000px 下两栏上下排列；对一行点“按销项更新”后，同一行已开、未开、开票状态、数量比对、已开参考价税合计、未开参考金额均更新到正确列；页面无脚本错误。
- 未覆盖：深色 / 其他皮肤、TSV 复制列顺序实测、Windows、打包产物；真实目录本身未写入。随本轮本地提交，未推送。

### 2026-11-06 开票参考销项比对（COST-03）

- 需求：BUG-01 修完后开始下一步。用户选“读取销项发票”，并要求保留手填已开数量，以防销项还没保存到目录；有实际销项时再比对、刷新。
- 起点：BUG-01 先在 `codex/cost-output-tax-rate` 本地提交 `063839e`（只暂存本轮改动，混在同一文件里的旧未提交改动未带入；用 `git checkout-index` 导出暂存树单独跑测试 739 passed，唯一需 git 仓库的发布锁哈希测试在导出目录不适用并已排除）；从该提交新建 `codex/cost-outbound-invoiced`，即叠在尚未合并的 BUG-01 分支上。
- 核查：开具发票目录 `outbound_invoice_dir` 是全局设置（单据页），出库单用 `analyze_cost_invoice` 解析其明细，字段与成本明细同构；单据索引只缓存票头、不缓存明细；monitor 不监控开具目录。
- 方案：新增 `projections/cost_outbound.py`：手动重新汇总在成本分析后读取开具目录，按发票号把 PDF/OFD/XML 同票合并为一份（复用 `_select_cost_analysis`），只采用销售方属于本目录进项购买方的发票（开具目录是全局设置，切换公司后可能仍指向别家），与 `watch_dir` 重叠时不读取；按开票参考分组键汇总数量 / 金额 / 税金 / 张数，红字票按负数冲减。文件签名与明细缓存、汇总结果写 profile 工作区 `cost_outbound_files.json` / `cost_outbound_summary.json`，不写 `watch_dir` 或开具目录；汇总进入成本读取指纹；读取失败只记提示。`cost_analysis.py` 新增 `outbound_reference_fields`（销项数量、销项除税单价、实际加价率 = 销项单价 / 成本单价 − 1、比对“无销项 / 一致 / 销项多 / 手填多 / 销项超过进项”、建议已开数量）与 `outbound_overview`（读取统计、未对上品目、已对上 ≥ 3 个品目实际加价率相同时的统一加价率提示），工作簿与 API 共用。快照新增 `outbound_summary`，开票参考行新增 `outbound_*`、`actual_markup_*` 字段；重新汇总返回 `detail.cost_analysis.outbound`（不含逐品目明细）。工作簿“开票参考”末尾新增“销项数量”“销项除税单价”“实际加价率”“销项比对”。`/costs` 新增销项比对面板、开票参考表末尾三列、单行“按销项更新”与工具栏“已选按销项更新”，只写草稿，保存仍走既有快照语义；手填已开数量不被自动覆盖。`#referenceTable` 为第 15—18 列设宽度并把最小宽度改为 2170px（修正 BUG-01“成本口径”列被挤压）；`app.css` 与 `page-costs.js` 资源版本统一为 `20261106-cost-outbound`。
- 文档：成本规则页、数据与算法 §9.4、接口与流程、文件地图、设计原因、任务导航、实现状态、未来工作总览 COST-03 / COST-05、成本分析 v2 设计落地顺序。
- 验证：python.org Python 3.14 全量 `pytest` 823 passed、16 skipped；新增 6 项覆盖多格式去重与非本公司排除、缓存复用与变更重解析、比对状态与超过进项、统一加价率提示、目录缺失 / 重叠 / 读取失败，以及 `PUT /api/v1/documents/outbound-dir` + `POST /api/v1/bridge/rebuild` 后成本 API 与分页视图返回比对。真实页面验收：`/tmp` 合成配置（进项 12E 2 吨、14E 1 吨；本公司销项 12E 1.5 吨并存一份副本、16E 1 吨，另一家公司销项 1 张）启动源码服务，经专用 Chrome DevTools 协议：重新汇总前提示未读取；之后面板显示读取 3 张、采用 2 张、非本公司 1 张、未对上“钢筋 / 16E / 吨”；12E 显示销项 1.5、实际加价率 20%、“销项多 1.5”与按钮，点击后已开草稿 1.5、状态“部分开具”、比对“一致”，保存后保持；无销项行勾选时批量按钮禁用；新列宽 150/96/104/260px、页面加载新 `?v=`、读取时间显示本地时间、无脚本错误。验收后停止服务并删除 `/tmp` 数据。
- 未覆盖：品名叫法不同的销项对不上（待 COST-02 品目表）；monitor 自动重建不重新读取开具目录；未测大量 PDF 销项的读取耗时；未覆盖深色 / 其他皮肤、窄窗口、TSV 复制、正式 Windows BAT、真实默认配置与业务目录、系统选择器、桌面宿主与打包产物。随本轮本地提交，未推送。

### 2026-11-05 开票参考按公司税务设置计价（BUG-01）

- 需求：用户要求先修复 BUG-01：开票参考销项税率写死 13%、成本固定取不含税金额，小规模纳税人（3% / 1%）与劳务类公司参考价算错。用户确认税率本轮只按公司设置（品目级覆盖随 COST-02 品目表再做），一般纳税人取得的普通发票进项税同步计入成本。
- 起点：`codex/selection-workflow` 与 `main` 同为 `ddf5ab6`；新建 `codex/cost-output-tax-rate`，工作区既有未提交改动（选择工作流文档、成本页浮层、`bank/`、交接工具等）原样保留，未纳入本轮判断。
- 核查：13% 在四处各自计算——工作簿 `_invoice_reference_summary`、API 读取 `_build_reference_rows`、状态保存 `save_reference_status`、`page-costs.js` 草稿联动（`0.13` / `1.13`）；发票类型只在“发票校验”行里（`发票大类/特定业务类型/类型识别状态`），成本明细 CSV 没有。
- 方案：公司税务设置存于 `watch_dir/成本开票状态.json` 顶层 `tax_profile`（纳税人类型、销项税率），随公司资料夹走，不新增配置文件；缺失时按一般纳税人 13%，旧状态结果不变。`cost_analysis.py` 新增 `ReferenceTaxProfile`、`parse_reference_tax_profile`（严格，非法 `400`）、`reference_tax_profile_from_status`（容错）、`input_tax_deductibility`、`reference_cost_basis`：成本单价 = sum(金额(除税) + 不可抵扣税金) / sum(数量)，小规模全部计入；一般纳税人只计入已确认的增值税普通发票（旅客运输除外），类型未确认的按不含税并标注“N 张发票类型待核对”。四处计价统一用该成本与公司税率；两个状态写入函数在改写行状态（含重新汇总合并工作簿状态）时保留 `tax_profile`。`POST /api/v1/cost-analysis/reference-status` 接受可选 `tax_profile`；快照新增 `reference_tax_profile`，开票参考行新增 `reference_cost_unit_price/reference_cost_basis/reference_cost_note/reference_cost_basis_text`，`average_unit_price` 仍为纯不含税均价。工作簿“开票参考”末尾新增“成本口径”“销项税率”两列（旧工作簿缺列会按既有 schema 自愈重写）。`/costs` 新增“本公司税务设置”（纳税人类型、13/9/6/5/3/1/0%），有未保存的开票参考草稿时不允许保存；开票参考表末尾新增“成本口径”列；算法说明浮层改为新公式；`page-costs.js` 资源版本 `20261105-cost-tax-profile`。已开快照不随税务设置重算。
- 文档：成本规则页、数据与算法 §9.3、接口与流程（cost API 字段与 reference-status 载荷）、设计原因、任务导航高风险提醒、实现状态、未来工作总览 BUG-01（改为进行中）与成本分析 v2 设计落地顺序。
- 验证：本机 python.org Python 3.14（未新建虚拟环境）`PYTHONPATH=src python3.14 -m pytest tests/test_summary_and_costs.py tests/test_frontend_contract.py tests/test_invoice_classification.py` 通过；其中新增 13 项覆盖默认一般纳税人 13%、小规模 1% 含税成本与工作簿两列、一般纳税人专票 / 普票 / 旅客运输混合、类型待核对标注、改税务设置不动已开快照且行保存不丢设置、6 类非法输入拒绝且不写文件、重新汇总读取并保留设置、重新汇总写入函数保留设置。`node --check web/static/js/page-costs.js` 通过。2026-11-06 用户为该 Python 补装 fastapi / uvicorn / certifi / httpx2 后，`tests/test_api_contract.py` 与 `tests/test_progressive_loading.py` 通过，全量 `pytest` 817 passed、16 skipped。真实页面验收：在 `/tmp` 用合成配置（端口 8799、合成专票与普票各一张）启动源码服务，经专用 Chrome DevTools 协议操作 `/costs`：默认一般纳税人 13% 时成本口径“部分含税”、参考含税单价 123.87（=(200+200+6)/4×1.08×1.13）；改为小规模 1% 保存后为“含税”、117.81，工作簿“开票参考”同为 117.81 / 471.23 且末列“成本口径=含税”“销项税率=1%”，状态 JSON 写入 `tax_profile`；有加价率草稿时“保存税务设置”禁用并提示，草稿行按已保存税率联动为 119.99；页面无脚本错误。验收后停止服务并删除 `/tmp` 数据。
- 未覆盖：TSV 复制未实测（列配置相同，未读剪贴板）；未覆盖深色 / 其他皮肤、窄窗口、正式 Windows BAT、真实默认配置与业务目录、系统选择器、桌面宿主与打包产物。“成本口径”列位于开票参考表最右侧，需要横向滚动。通行费电子普通发票未单独识别，会按不可抵扣计入成本；专票是否已勾选抵扣未读取进项抵扣目录。征收率优惠未写入代码，仅在小规模选择非 0/1/3/5% 时提示核对。已本地提交 `063839e`，未推送。

### 2026-11-05 成本分析 v2 设计按用户决策修订，登记 BUG-01

- 需求：用户要求深入成本分析 v2，并回答待定问题：售价会因客户变化；定价方式要多样；多数销项 13%，部分公司为小规模（3% / 1%），劳务类公司也有 3%、1% 等税率；成本口径不熟悉，按建议处理；其余按建议写回设计稿。
- 核查：对照源码发现设计稿遗漏四点——成本分析按规格分组，而做账库存（`bank/vouchers.py` 的 `cost_of_sales`）按账套库存科目滚动、发票品名靠写死关键字的 `goods_family()` 归类，两边粒度不同；销项税率写死为 `REFERENCE_OUTPUT_TAX_RATE = 0.13`、成本固定取不含税金额；按客户定价会改变“一个品目一行一个价”的页面与快照语义；月末一次加权滚动后的结存单价已能解决 COST-01 的主要问题，先进先出缺少批次依据。
- 文档：`docs/COST_ANALYSIS_V2_DESIGN.md` 新增 §0 已确认决策、品目表（别名、库存科目、货物 / 服务、默认税率，取代 `goods_family()`，科目层结存一致）、进项税是否计入成本、成本口径（默认结存加权单价 + 最近进价，先进先出与移动加权不进首版）、销项税率与计税方式（公司 / 品目设置，征收率来自税务政策中心，特殊计税首版只提示）、规则分两批与 4 层优先级（同层生效期不得重叠）、定价助手页面、已开部分以实际销项为准、小规模迁移显示新旧对照、修订后的落地顺序与未决事项。`docs/PRODUCT_BACKLOG.md` 更新 COST-01、COST-02、COST-06，新增缺陷 BUG-01（P0，待评估）；同步成本规则页与文件地图。
- 验证：文档契约测试与 `git diff --check`，结果见本轮回复。
- 未覆盖：只改文档，未改 `projections/`、`bank/`、`/costs` 页面或 API；税率与征收率政策未重新核验官方原文。未提交、未推送。

### 2026-11-03 未来工作总览、成本分析 v2 设计与原型第六版

- 需求：用户要求页面缓存默认保留，但可以双击 `hi.` 图标手动清空 / 刷新；保留设计原型，并确认架构地图里有没有“未来功能设计 / 待办 / 待修复”的统一文件，没有就新增，方便各 Agent 接手；把新原型的后端逻辑加入待办；重新设计已落后的成本分析，让加价更灵活；做账模块去掉单一记账软件的标识，凭证导出参考通用凭证数据格式；做账所属期改为可选年份、月份的小日历；OCR 更新加入待办，思路是使用 PaddleOCR 的 API。
- 核查：已有 `docs/PRODUCT_BACKLOG.md` 只登记功能待办，没有设计稿索引和缺陷区；设计稿分散在 `docs/` 与 `docs/design/`。现有发布包 OCR 为关闭状态（`ocr_settings` 返回 `disabled`），AGENTS.md 把本地 OCR 正式打包版列为当前不做。PaddleOCR 官网提供以星河社区 Access Token 调用的 API 在线服务，官网称目前限时免费；额度与价格以官方为准，未在本轮实测。
- 文档：`docs/PRODUCT_BACKLOG.md` 改为“未来工作总览”，新增设计稿与原型索引、待修复区（macOS 隔离 HOME 烟测指向迁移缺口清单，不重复登记）；新增 COST-06（成本分析 v2）、WS-07（多公司工作区后端：公司清单、按目录投影、公司账簿聚合、比较与明细、用户数据与刷新语义、API 草案与验收）、BK-01（通用凭证导出与导入模板适配）、OCR-01（PaddleOCR 官方 API / 自建服务，隐私、Token 存储、字段校验与计费缓存）；更新 WS-01、WS-05。新增 `docs/COST_ANALYSIS_V2_DESIGN.md`：公司级品目台账、四种成本口径、六类定价规则与优先级、可解释代入式与试算、快照、页面结构、兼容迁移与落地顺序。同步 AGENTS.md 收尾规则、任务快速索引、文件地图，以及成本、做账、提取三个规则页的待开发入口。
- 原型：`hi.` 改为按钮，双击只清空“当前模块 + 当前对象”的视图缓存并重新读取，其他模块缓存与用户保存的修改保留；做账所属期、凭证所属期与单据记入期统一用年月小日历（可翻年份、不能选未来月份、有资料月份带标记），所属期改为“年-月”，没有资料的月份显示空状态；“导出导入表”改为“导出凭证”弹窗，默认通用凭证表（xlsx / csv），可选按记账软件导入模板导出，制单人必填，“科目—单位名”拆成科目与辅助核算，原型中不再出现具体记账软件名称。
- 验证：本机专用 Chrome 经 DevTools 协议执行脚本：双击 `hi.` 后本页筛选、勾选、滚动清空且标签保留；未双击时切模块往返滚动位置一致（475 → 475）、筛选保留；小日历翻年、未来月份禁用、有资料标记 4 个、选无资料月份显示空状态、凭证移到 2026-06 并改记账日期为月末、单据改记入期；导出弹窗生成通用表行、未填制单人时拦截；页面不含具体软件名称；借贷不平仍禁止审核、全部节点 × 模块 × 做账标签渲染无错误、比较页守恒行全部成立。文档契约测试与 `git diff --check` 见下。
- 未覆盖：原型与设计文档都不是产品实现，未改 `web/`、API、`bank/` 或 OCR 代码；PaddleOCR API 未调用实测；GB/T 24589 字段命名未核对标准原文；未做深色 / 其他皮肤与 Windows 验收。未提交、未推送。

### 2026-11-03 多公司工作区原型第五版：比较明细、模块缓存与发票列表细节

- 需求：用户审阅第四版后要求：各模块允许没有标签页的空页面（参考 Codex 起始页）；同一公司的目录比较也要保留文件并排，且比较页类目可点击看明细，避免只有汇总看不懂来源和原理；切到其他模块时不显示首页标签，但各模块要有页面缓存；发票列表标签预留一格竖向对齐、多标签叠放，格式与发票类型恢复原多色区分，重新设计勾选后的操作按钮，并排查点击按钮 / 勾选时页面抖动。
- 排查：抖动来自每次局部操作都整页重绘内容区并重放 `.view` 的 0.16s 位移入场动画；返回首页时滚动位置偏差来自先隐藏标签栏、内容区变高后浏览器截短滚动位置，再保存。
- 方案：入场动画只在“模块 + 对象”变化时播放，勾选改为局部更新（行状态、表头勾选框、操作条）；渲染外框前先记录滚动位置，按“模块 + 对象”恢复。标签页只属于首页，可全部关闭显示起始页；其他模块隐藏标签栏，首次进入沿用首页对象，之后各自记住对象，未选时显示模块空页面；目录筛选条件按目录缓存。发票列表名称列左侧固定标签位、多标签叠放并悬停列出全部意义；格式与发票类型沿用现有首页配色（普票名称改为“增值税普通发票”）；勾选后列表底部浮出深色操作条，删除在条内二次确认，Esc 取消勾选。比较页的汇总卡片、品目、往来单位、流水、未对上发票、勾选状态与公司指标都可点开明细抽屉（来源记录 + 逐步计算），下方新增两个目录的原始文件并排，点类目后只留相关记录。
- 验证：本机专用 Chrome 经 DevTools 协议执行脚本：匹配算法与真实收付款逐笔一致（0 处不一致）；3 种期间 × 9 月流水读与不读 × 12 组比较的守恒行全部成立，逐个点开 752 个可点击类目均打开明细且无错误、无不成立的校验行；钢筋明细把并排列表从 21 条收窄为 6 条，“显示全部”可恢复；关闭全部标签显示起始页；做账模块隐藏标签栏、换对象不影响首页标签，回到首页滚动位置一致（590 → 590）；勾选不替换内容区节点、不重放动画，表头部分选中 / 全选、删除二次确认、合计详情、Esc 取消均正常；名称列左边缘一致，三种格式颜色不同；上一版的创建目录、借贷不平、凭证改期、右键标签、版式确认、向导与全部节点渲染回归通过，无脚本错误。另截图检查列表、比较明细、并排联动、往来明细、起始页与做账页。
- 未覆盖：原型不是产品实现，未改 `web/`、API 或 `bank/`；未做深色 / 其他皮肤、窄窗口操作条换行、Windows 与打包验收。未提交、未推送。

### 2026-11-03 多公司工作区原型第四版：保留发票列表、标签、勾稽比较与银行版式

- 需求：用户审阅第三版后提出：保留现有首页发票列表的格式 / 发票分类列与勾选、一键全选、`>>` 菜单、勾选合计详情；做账所属期、记账日期与单据日期可自由调整但要有悬停提示；没有内置模型时如何精准提取各家银行的流水 / 对账单 / 回单；比较页缺少 `⇄` 标记，同一公司两个目录的数据必须真正关联对比且算法不能错；设置页自定义标签、发票列表右键打标签并悬停看意义；侧栏分栏可拖动且有限位，过长文字省略并悬停显示全文。起点 `codex/selection-workflow`（HEAD `ddf5ab6`），其余未提交改动不动。
- 方案：原型改为由一份合成账簿派生同一公司的进项、销项、银行流水与勾选清单（含同票多格式、金额未识别、卖超、跨月勾选、清单有目录无、缺一个月流水等场景），公司总览、目录列表、做账库存与比较页都读这份数据。比较页按目录关系选择算法：进销存勾稽（逐月一次加权，与做账库存共用函数）、往来核对（期初 + 本期发票 − 本期收付款 = 期末；流水按一对一 → 2—3 张组合 → 部分 / 预付 → 非发票流水确定性匹配）、抵扣核对（按发票号对照勾选清单），每页输出守恒校验行；不同公司或无勾稽字段时只并排展示。目录页沿用现有首页列表列与勾选合计口径（同票家族只计一次、缺少合法金额单独说明），合计详情含项目税率分组、来源、算术 / 加权均价；新增标签设置与右键标签菜单、悬停说明组件、侧栏拖动（220—460px，内容区至少 620px，双击复位）。做账凭证可改所属期（整张移月）与记账日期（不在所属期内不能审核），原始凭证标注同期 / 跨期并可单独改记入期。银行流水页演示版式识别、新版式列映射确认与余额链方向判定。
- 文档：`docs/PRODUCT_BACKLOG.md` 更新 WS-01 / 04 / 05，新增 WS-06（标签）与 BANK-01（通用银行对账单版式引擎方案）；同步文件地图与实现状态。
- 验证：通过本机专用 Chrome 的 DevTools 协议加载原型并执行脚本：四家合成公司的流水匹配结果与生成时的真实收付款逐笔比对 0 处不一致；余额链全部成立，未确认 9 月版式时恰好断开 1 行；三种期间 × 9 月流水读取与否 × 12 组比较的全部守恒校验行均成立；勾选合计、合计详情筛选、右键标签、`>>` 菜单、凭证改期 / 改日期、标签设置、列映射重复校验、分栏限位与比较标签均按预期，页面无脚本错误；另截图检查列表、合计详情、比较、做账、银行、设置、悬停提示与窄侧栏。文档契约测试与 `git diff --check` 见下。
- 未覆盖：原型不是产品实现，未改 `web/`、API、monitor 或 `bank/` 代码；未做跨皮肤 / 深色、Windows、桌面宿主与打包产物验收；匹配与余额链只在合成数据上验证，未用真实银行样本。未提交、未推送。

### 2026-11-01—11-02 多公司工作区交互原型与分阶段待办

- 需求：用户最大的痛点是界面一次只能看一个发票目录、业务资料夹只关联一家公司，多公司、多项目的进项、销项、利润和税款要人工重复计算。要求参考 Codex 界面（模块列、可置顶的工作区侧栏、↑ 更新入口）、在不大改现有界面与色系的前提下先出原型，并补充：项目从发票备注“项目名称：xxx”识别、没有时人工填写；公司资料夹缺子目录时一键创建、支持从零建工作区；多目录同时监控暂不做；做账模块把凭证（可编辑）、库存、工资、社保、各税种测算可视化。起点 `codex/selection-workflow`（HEAD `ddf5ab6`），工作区已有的文档、银行模块、成本页与交接工具改动保持不动。
- 过程：11-01 迭代三版单文件原型 `docs/design/workspace-sidebar-prototype.html`（合成数据，不读写真实目录）；第三版写完并自测后会话因电脑休眠与登录失效中断，11-02 接手核对文件完整后补齐本条记录、文件地图、实现状态与待办登记。
- 原型内容：左侧模块列（首页下方「临时识别」、左下 ↑ 更新入口跳转 设置 › 关于）；侧栏 `InvoiceHub ⌄` 按公司 › 项目 / 目录分层，右键、行尾 `⋯` 或 Shift+F10 置顶；仿 VS Code 的「选择以进行比较 → 与已选项进行比较」打开 `A ↔ B` 标签（目录比较标出同号发票，纳税人身份不同时提示不可直接比较）；公司/项目票面汇总（未归属项目单列不分摊）、发票与回单缩略图；六个标准子目录（成本发票、开具发票、银行流水、进项抵扣、工资社保、费用报销）缺失检测、一键创建与新建工作区向导；做账页分凭证（借贷实时校验、改动须重审、只导出已审核）、库存（月末一次加权平均，卖超照算并提示）、工资社保（无明细不猜拆分）、税费（测算 / 已申报 / 已缴分开，优惠资格未确认不减免）。
- 文档：`docs/architecture/FILE_MAP.md` 登记原型；`docs/PRODUCT_BACKLOG.md` 新增 WS-01—05 分阶段条目（外框 → 公司清单与子目录 → 票面汇总与项目识别 → 比较与缩略图 → 做账可视化）；`IMPLEMENTATION_STATUS.md` 注明尚未实现。
- 验证：11-01 用无头 Chrome 截图检查各视图，并用注入脚本走通“创建缺失目录 → 放入文件”“改科目解除阻断 → 审核”“借贷不平禁止审核”“人工填写项目”“向导新建公司”等交互；11-02 本机 Chrome 受沙箱限制无法启动，只对原型内联脚本做了 `node --check` 语法检查。文档契约测试与 `git diff --check` 见下。
- 未覆盖：原型不是产品实现，未改 `web/`、API、monitor 或配置；未做真实浏览器跨皮肤/窄屏验收、Windows BAT、桌面宿主与打包产物；成本分析优化方案待用户决定。未提交、未推送。

### 2026-10-26 成本页算法说明浮层越界修复

- 需求：成本页视图切换栏左侧的 `!`（平均单价算法说明）悬停后，浮层大半藏到窗口左边界外，用户要求按界面位置自适应显示、不得被边界遮挡。起点 `codex/selection-workflow`（HEAD `ddf5ab6`），工作区已有的文档、银行模块与交接工具改动保持不动。
- 原因：按钮已移到切换栏最左侧，但浮层仍以 `right: 0` 锚定按钮右缘、向左展开 460px，只有 ≤820px 媒体查询才改为左锚定；桌面宽度下必然越过视口左缘。深色外观下箭头还因皮肤 `:is()` 选择器无法匹配 `::after` 而保持白色菱形。
- 方案：`page-costs.js` 新增 `positionCostFormulaTooltip`，每次悬停/聚焦时实测按钮与浮层尺寸：水平以按钮为中心、夹在视口左右 12px 边距内；上方（扣除吸顶导航栏）放不下而下方放得下时翻到下方（`data-placement="bottom"`）；两侧都放不下时取较大一侧并限制高度、正文内部滚动；箭头通过 `--cost-tooltip-arrow-x` 始终指向按钮；打开期间滚动/缩放用 rAF 重算。`app.css` 默认改为左锚定作无 JS 回退，删除窄屏专用覆盖，箭头背景改为 `inherit`。模板增加 `.cost-formula-tooltip__body` 承载滚动，避免裁掉箭头。
- 资源版本：`app.css` 改为 `20261026-cost-tooltip-viewport`（全部模板与契约测试同步；其它公共资源仍为 `20260907-desktop-integrated-2`），`page-costs.js` 改为 `20261026-cost-tooltip-viewport`。
- 验证：`test_frontend_contract.py` 新增浮层定位契约；前端/预览/打印/API/文档/成本契约 154 项通过，`frontend_interactions.test.cjs` 16 项通过，`node --check` 通过。另用仓库源码在隔离端口 8791（临时配置与空 `watch_dir`）起服务，无头 Chrome 实测 1000/1440/700/390 宽、滚动后、矮视口（330 高，内部滚动）、键盘聚焦、上方不足翻转下方，覆盖默认浅色、`?no_skin=1`、Animal Island、`website-dark`：浮层均完整位于视口内且不压吸顶导航，箭头底色与面板一致，无控制台错误。
- 2026-10-27 效果复查追加修正：① 打开期间的捕获式 `scroll` 监听会被浮层自身正文滚动触发，重算时先去掉 `max-height` 导致 `scrollTop` 归零，矮窗口里无法向下阅读，现忽略浮层内部滚动；② 按钮与浮层之间 10px 间隙不属于悬停区，鼠标移向浮层即关闭，新增 `::before` 透明悬停桥（随上下方向切换）；③ CSS `100vw` 含经典滚动条宽度而 JS 以 `clientWidth` 夹边，窄屏可能越出约一个滚动条宽度，现由 JS 写入 `max-width`；④ 深色外观下段落分隔线原为固定 `#eef2f7` 亮白线，改为 `color-mix` 跟随正文色并保留旧值回退。复测：契约测试增加对应断言；无头 Chrome 复测桌面、翻转下方、两向悬停桥、矮窗口内部滚动保持 `scrollTop`、390 宽、Animal Island 与 `website-dark`，均在视口内、无页面错误。
- 未覆盖：未重启或替换正在运行的 `/Applications/InvoiceHub.app`（8766 仍为旧资源），未打包、未覆盖 Windows BAT、Tauri 桌面窗口、真实经典滚动条环境与 Ink Pulse 皮肤实测。
- 2026-11-11 提交时追加：这批改动一直没提交，期间其它提交已把公共资源版本升到 `20261108-cost-smooth-tabs-3`，浮层改动叠在上面却没再刷新版本。提交前把 `app.css` 与 `page-costs.js` 统一改为 `20261111-cost-tooltip-viewport`（10 个模板与 3 个前端契约测试），前端 / 预览 / 打印 / 文档契约 41 项通过；未重新做浏览器复测。

### 2026-10-24 新增产品待办清单

- 需求：用户希望把开票参考的优化建议写成“下个版本考虑修”的清单，并能从地图查到。
- 方案：新增 `docs/PRODUCT_BACKLOG.md`，采用常见的产品待办格式（编号、优先级 P0—P3、状态、目标版本、问题与证据、方案、验收标准、影响范围）和“登记 → 分级 → 排期 → 关闭”流程；首批登记 COST-01—05（开票参考成本基数、品名别名、自动已开数量、与账面库存核对、合同价参照与固定加价率提示），证据取自真实客户回测的脱敏结论。AGENTS.md 收尾规则、任务快速索引、文件地图与成本规则页同步加入入口。
- 同时清理本分支此前写入 CHANGELOG、做账规则、代码注释与测试中的真实往来单位名称与金额，改为脱敏表述。
- 验证：`tests/test_development_documentation.py` 与银行模块测试。

### 2026-10-20—10-24 凭证与对账单比对、账套读回补记与库存成本

- 需求与起点：用户以一家真实客户的季度补账为验收场景，要求凭证与对账单比对正确、简洁，提供源文件速查，科目参考账套实际习惯，默认短摘要可改，并检查已结账月份漏记。工作在 `codex/selection-workflow`（HEAD `ddf5ab6`），银行模块此前未提交，本轮在原工作区改动上继续。真实对账单、账套读回、草稿与导入文件只留在公司资料夹，本记录不含户名、票号或金额。
- 读回与对账：新增 `voucher_cli draft --booked`（捷锐“序时账”复制文本）与 `--ledger`（私有科目表读回快照）。已入账月份只补记对不上的银行流水与漏记发票；银行分录先一对一、再按“摘要点名对方的合计组合”匹配；发票按税额在读回分录中一对一消耗匹配，允许 0.05 元舍入容差；已结账月份的漏记发票补记到草稿首月。审核表新增“银行对账”“月度核对”（含申报应纳与发票测算差异）、“库存核对”，原件超链接与数量/单位列。
- 缺陷修复：中国银行对账单每页序号重排导致 `row_id` 撞号、第 2 页行覆盖第 1 页行的分类；合并分录丢数量；无对账单月份被跳过；同日同分录凭证被导出去重误判；导出编号从 001 起与账套已有凭证撞号（新增显式 `--after`）；应收账款未按账套实际启用的辅助维度带户名。
- 进项抵扣：`申报数据.json` 新增 `勾选清单已登记月份`、`抵扣依据`，清单已登记的月份中未出现的发票挂待认证进项税额，不再推定已抵扣；缺清单时由申报数倒推的组合须标注“推断”。
- 库存与成本：新增月末一次加权平均销售成本结转；期初取读回账套，期初数量与“进项 − 销项发票数量”不符时在首月生成“更正前期出库数量”凭证（未来适用法，差额进主营业务成本）；卖超时照算并写明缺口。
- 凭证可读性：`--month-end` 统一记月末；只有收付款凭证摘要前带 yymmdd 实际日期；往来资金摘要统一“收/还X往来款”（按用户在账套中的改法）；分录先借后贷，月内按进货、卖货、抵扣、成本、资金、计提排列。
- 其它：社保按 `社保明细`（单位/个人）月末计提；项目用转售设备在存在对应库存明细时记库存商品；捷锐导入实测“制单人”必填，export 新增必填 `--preparer`。
- 验证：`tests/test_bank_vouchers.py`、`tests/test_bank_workpaper.py`、`tests/test_development_documentation.py` 共 45 项通过，新增分页序号、合并来款匹配、已入账月份补记与编号、申报差异、数量合并、勾选清单与跨月补记、加权成本与卖超、期初数量更正、月末日期与排序、1 分容差、社保计提、编号起点与同日重复凭证用例。真实账套导入已由用户逐月完成；未覆盖：捷锐导入的辅助核算全维度、工资计提生成、产品全量回归（本轮只改 `bank/` 命令行模块与文档）。

### 2026-10-09 双平台工作流完善与源码集成打包

- 需求与起点：用户要求把渐进读取、临时识别/预览和勾选工作流一起提交、推送，并生成Mac包，Windows由用户取同一源码自行打包。本轮继续 `codex/selection-workflow`，起点为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`；银行底稿、税务设计、交接工具和其它未授权资产保留在工作区，不进入本次产品输入。
- 平台完善：Windows除PreDeleteItem永久删除拒绝外，再核对PostDeleteItem实际回收站目标，缺少目标不能报成功；Mac继续调用Foundation原生废纸篓。Tauri原生拖入按固定origin和首页路径校验，允许详情返回/恢复皮肤查询参数；握手新增分页成本和删除计划/查询/确认API门禁。两端继续共享同一业务核心和页面。
- 构建修正：图标生成显式使用BASIC字形布局，消除Pillow可选Raqm在Mac/Windows间的间距差异，保留原图标像素。核心指纹排除不入包的editable egg-info元数据，继续纳入全部真实源码；不清理用户原有环境，不放宽包内白名单。
- 源码验证：在独立干净范围的测试目录完成一次Python全量回归，726通过、16跳过、20项子测试通过；唯一失败是拆分未提交银行功能后留下的文档锚点，已修正并单独复测文档契约。Node30项、Rust101项通过，图标像素和源码身份回归均通过。PyMuPDF/SWIG弃用警告保留。完整测试数与此前不同是因为银行/交接工具未进入本次范围。Mac组包与验包结果以实际receipt及后续收尾记录为准。
- 构建跟进：首个Mac候选完成release编译、ad-hoc签名、DMG挂载内容/收据闭环核验；重用旧target的只读Java许可导致覆盖失败，换独立构建目录后恢复。源码归档扫描命中Windows验包测试的假凭据字面量，改为运行时拼接并保持正反例及扫描规则不变；后续源码与成品精确身份由最终receipt绑定。隔离LaunchServices烟测因已有版本占用8766而在拉起前停止，未操作既有进程或默认业务配置。
- 边界：只推送功能分支，不合并main、不发布Release/Feed、不安装替换用户应用。Windows实机回收站、正式BAT和成品由Windows端验收；Mac包按现有ad-hoc预览流程构建，不能冒充Developer ID/公证。

### 2026-10-09 勾选删除、汇总来源追溯与大量文件预览

- 需求与起点：按三项截图需求新增删除所选源文件、项目明细搜索/税率筛选/来源详情返回，并处理全选超过100条无法预览。使用 ui-ux-pro-max 检索确认交互与无障碍规范。从核验的 `main@ee0f2c2557d2b2a3640e9c00d9b8241581db4409` 创建 `codex/selection-workflow`，完整保留此前未提交改动；未提交、推送、合并、打包或替换安装版。
- 删除方案：菜单新增“删除所选文件”，展示相对文件名、数量与取消/确认。服务端5分钟计划绑定 target、当前记录键/路径和设备/inode/size/mtime/ctime；提交在活动目录锁与非阻塞monitor写锁内全量及逐项校验，只移走所选源路径，不扩展同票家族。macOS Foundation、Windows IFileOperation 送入废纸篓，Windows PreDeleteItem veto 阻止永久删除；不增加依赖，不做永久删除回退。意图/结果追加持久日志，未知结果只查询，部分失败停后续、重复提交不再执行；完成后沿原同步链更新投影并保留人工修订。
- 汇总方案：搜索项目、规格、单位、票号和文件名，与税率取交集，包含“税率未识别”；顶部金额仍是全部勾选。税率右侧chevron展开该组来源发票，点击进入身份校验后的详情；左上角“< 返回”恢复勾选、首页分页/筛选与汇总搜索/税率。原有同票去重和金额冲突口径不变。
- 大量预览：100条是本项目的批次防护，非开源插件限制。首页完整保留选择，每次只准备当前1份，支持跨100项翻阅和序号跳转，名称下拉和删除清单按100项窗口显示。沿用页数/字节/作业数/闲置保活约束，目录切换和迟到响应不能覆盖新来源。index/detail及独立样式最终资源为 `20261009-selection-6`。
- 验证：删除/来源/预览关键链路与相邻API回归通过，包含部分失败、全部预检、链接拒绝、同步锁占用、重复确认/重启未知结果、投影删除与人工修订保留；Node30项通过，含7003份选择只准备当前1份和迟到响应。macOS原生使用唯一合成文件完成移入、读取核对、恢复并清理；Windows仅COM ABI/回调与永久删除保护模拟，未做Windows实机。
- 浏览器：隔离125份合成源文件，全选、跨100份翻阅、跳至125、搜索/税率、来源详情返回恢复、删除取消及清单第二组均核对；默认/Ink Pulse/Animal Island/no_skin桌面与390px检查，修正窄屏来源浮层越界、补summary键盘焦点及危险按钮皮肤覆盖；资源版本、health与根滚动锁已核对，未见页面脚本错误。
- 完整回归：首次775通过、16跳过、3失败；修正本轮新增API文档注册缺项后，最终781通过、16跳过、2失败（另24项子测试通过）。保留两项既有失败：图标生成像素差异、ignored egg-info导致staging身份差异；PyMuPDF/SWIG弃用提示仍存在。最终资源更新后41项前端/文档契约与30项Node回归通过，不把自动化或合成样本当作最终用户验收。
- 未覆盖：真实默认业务配置、正式Windows BAT、系统浏览器前台拉起、系统原生选择器、新打包产物及Windows原生回收站；未操作真实业务资料。临时服务、合成目录与venv收尾清理，私有检查点/验证日志和界面截图留在仓库外供复核，原有ignored缓存不清理。


### 2026-10-09 临时识别原文件预览

- 需求与起点：在临时识别中增加“预览”，说明历史线程汇总字段；继续 `codex/temporary-recognition`，起点 HEAD 与 main 均为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`，保留此前未提交修改，无提交、推送、合并或打包。
- 方案与结果：队列与识别结果逐文件提供预览，PDF/OFD 按需渲染 PNG、XML 以纯文本展示，支持翻页、放大、返回及 Escape；复用首页有界内存渲染池，不扫描父目录、不写原票或正式投影。历史预览核验线程归属和全部原文件，读取前后复核，源变化或网络失败清空内容；3秒复核、缓存过期重建及迟到响应保护。预览操作列不进入 TSV，静态资源更新为 `20261009-temporary-8`。
- 自动化：临时识别/预览/打印/API/前端相邻回归130项通过；补充文档/构建契约/Host RPC等68项通过；最终共用缓存调整后121项相关回归通过；Node25项、JS语法、compileall通过。全量首次763通过、16跳过、4失败；两项监控失败由隔离 venv 未配置源码导入路径引起，补充外部 `.pth` 后两项复测通过。剩余图标生成像素不一致、源码工作树与allowlist staging指纹不一致未在本轮修复（后者既有 ignored egg-info 影响仍存在）；不宣称全量通过。
- 浏览器：隔离合成目录覆盖队列/历史预览、PDF两页、XML原文、放大、返回/Escape、其它线程成员移动后清空、复制反馈与表格操作列排除；默认、Ink Pulse、Animal Island、no_skin 在桌面与390px检查，静态版本、health及根滚动锁已核对，未见页面脚本错误。PDF用于预览布局验收，不作为字段提取准确性证据。
- 未覆盖：真实默认业务配置、正式Windows BAT、系统浏览器前台拉起、原生选择器/OS拖放和新打包产物；本轮原生选择返回为合成适配，OFD沿用既有组件，本轮未做真实OFD票面验收。界面截图及私有日志留在仓库外，临时服务和测试环境收尾清理。


### 2026-10-09 首页临时识别工作区

- 需求与起点：按用户草图在首页目录按钮行增加“临时识别”，支持平滑弹窗、文件排序、识别列表及可改名的日期历史；设置增加实用选项。从已核验的 `main@ee0f2c2557d2b2a3640e9c00d9b8241581db4409` 新建 `codex/temporary-recognition`，保留上一轮渐进加载、交接/税务设计/银行底稿及其它既有未提交修改。
- 设计：使用 ui-ux-pro-max 的设计检索与无障碍/动态效果规则，保持现有荧光绿和皮肤变量。原生 dialog 使用240ms进入、150ms退出和 reduced-motion；已选文件后缩小加号区，固定44px排序/移除按钮，支持手柄拖动和上下移动、Escape及焦点返回。历史以首个文件名命名、右侧显示识别日期，支持改名和仅删除记录；结果是真实 table，可复制 TSV。独立 CSS/JS 最终资源版本 `20261009-temporary-6`。
- 实现：新增独立服务/路由，在 runtime 保存可重建临时会话，单个子进程只解析显式选择的 PDF/OFD/XML，逐文件发布进度；不扫描父目录、不切换 watch_dir、不改变普通汇总、成本三件套和 monitor。子进程300秒截止，父进程管道断开即退出，正常 shutdown 收束；重启后 running 标为 interrupted。
- 来源与设置：短期选择 id 保留30分钟；每批默认20/最大50，单文件32 MiB，历史最多200条。设置可编辑批次上限及是否自动打开结果。查看和复制检查原路径、设备/inode/size/mtime及内容 SHA-256；任一来源移动、删除、替换或变化时不返回旧线程明细，并显示文件名提示。缓存中的项目内路径相对 root 保存；删除历史不删除原文件。
- 平台边界：Tauri 新增固定私有 `pick_temporary_files` RPC 和只面向固定 localhost 首页的原生拖入事件，token 不进入 Web；启动握手增加临时识别 API 必需路径。普通浏览器不能给出原文件绝对路径，拖入后须在原生多选框确认位置，不保留上传副本冒充源文件。当前图片/纯扫描件不提供 OCR。
- 验证：功能及相邻 API/前端/平台/文档 Python 回归163项通过；最终 worker 生命周期变更后12项临时服务回归通过；Node22项通过，包含迟到历史/选择器、失效清空、离线隐藏和队列顺序；Rust check 与100项 Rust 单元/契约测试通过，包含新增多选与旧 backend 握手拒绝。最终静态语法、编译与差异检查见本轮验收日志。
- 浏览器：隔离合成三文件，原生选择结果采用测试适配器；确认重排后识别顺序、历史改名、TSV复制、源文件移动后清空旧结果、设置保存及关闭自动打开后的查看入口、Escape返回焦点和最终资源加载。检查默认、Ink Pulse、Animal Island、no_skin恢复入口和390px布局；修正皮肤悬停对比度及窄屏通用按钮挤压文件名的问题。
- 全回归说明：一次全仓库 Python 回归为759通过、16跳过、3失败；两处旧首页资源版本断言已同步上一轮 `20261009-progressive-3` 并在上述聚焦回归通过。剩余 `test_alpha_staging_and_build_identity_include_the_same_site` 的差异仅为工作区既有 `src/invoice_hub.egg-info` 五个开发安装元数据文件，公开源输入逐文件无差异；保留原环境，不放宽发布身份校验。PyMuPDF/SWIG 弃用提示仍存在，不宣称全仓库全通。
- 未覆盖：真实默认业务配置、正式 Windows BAT、宿主前台拉起、系统原生多选弹窗及 OS 文件拖入、打包产物、扫描件 OCR。本轮源码与合成浏览器测试不替代原生平台验收；未提交、推送、合并或替换已安装应用。
- 文档与清理：同步实现状态、迁移清单、架构/平台/接口/数据/文件/任务/注释地图及页面规则；不改写 README。测试服务、合成运行目录、临时虚拟环境和图片转换文件收尾清理，私有检查点与验证日志留在仓库外；原有 ignored 开发安装/构建缓存保留供后续开发复用。

### 2026-10-09 首页、成本与单据渐进读取

- 需求：大量初始数据时尽早显示可用列表，减少进入成本页及选票生成单据的重复等待。按用户确认的“单据按需准备 → 分页完整快照 → 首次解析分批展示”顺序实施。起点为本地 `main@ee0f2c2557d2b2a3640e9c00d9b8241581db4409`，工作分支 `codex/progressive-data-loading`；保留此前交接、税务设计、银行底稿等未提交修改。
- 单据：成本 CSV 按签名缓存分组，仅展开选中的入库票；首页批量入口先取配置与所选队列，点击刷新列表或出库标签再加载完整索引。普通入库候选先发布，出库首条和后续批次通过 revision 更新；临时预览禁止正式导出，完整索引就绪后重建预览。export-status 复用源签名有效的目标文件名元数据，避免重复解析，源变化和正式导出仍实时核验。
- 列表：普通汇总按文件/手改签名复用列表构造结果；API 全量筛选、排序及统计后只返回当前页，首页每页 100 条，全选仍覆盖全部筛选结果。成本四标签按需分页（30/60/100），完整代际保存在档案 workspace 的可重建 SQLite 缓存；忙时显示上次完整结果而不等待整轮写锁，保留跨页选择/草稿和按固定 revision 复制完整 TSV。
- 首次读取：普通汇总与成本各自在解析阶段向临时读取视图追加首批及后续批次。临时结果明确只读，不用于正式身份选择、开票状态保存或导出；成本汇总/参考/校验等待完整结果。失败或终止后保留临时提示，锁释放不被当作成功。正式 CSV/XLSX/JSON 的投影规则与源发票权威性不变，SQLite 不作为发票主存储。
- 过程与修正：浏览器验收发现批量优先模式的空候选总数容易被误解，改为“当前优先处理首页已勾选”的提示，并保证主动刷新后继续跟踪完整索引；补充临时失败不可编辑、复制过程中 revision 核对和出库预览前后源签名核对。三个页面脚本最终版本 `20261009-progressive-3`。
- 计量：隔离目录中 7,003 条合成数据，首页全量/100 条页响应分别为 4,854,043 / 68,786 bytes；成本完整/30 条明细页响应分别为 13,477,639 / 16,358 bytes。此为同一合成数据集的响应体计量，不能代替真实 PDF/OFD 解析吞吐；首次建立完整成本缓存仍需一次原聚合，成本明细解析仍遵循普通汇总完成后的原流程。
- 验证：相关 Python 回归 222 项通过，覆盖 progressive loading、document_index、documents、summary_and_costs、monitoring、api_contract、invoice_classification、frontend_contract；Node 前端交互 16 项通过。新增用例暂停第二张解析并确认第一批可见、健康请求可响应，同时覆盖完整统计、分页身份、缓存失效、旧代际保存拒绝、失败临时明细只读、状态不重复预览。后续首批发布边界、提示和资源版本修改后，progressive_loading、frontend_contract、development_documentation 共 43 项通过；三个 JS 语法、8 个修改/新增 Python 模块内存编译与 git diff --check 通过。Node 16 项在最终脚本上再次通过。
- 浏览器：隔离合成 localhost 实际加载当前脚本；核对首页 100 行/跨页全选 7,003 张，成本 30 行/跨页勾选及数量草稿、复制 7,004 行 TSV，入出库预览与首页批量交接。检查 Ink Pulse、Animal Island、no_skin 恢复入口的桌面/390px、滚动与控制台；当前已安装 App 和用户真实配置未替换。
- 文档：同步实现状态、迁移清单、架构入口与文件/接口/数据/任务/注释地图，以及页面/成本规则。现有首页 README 未改写。
- 未覆盖：真实默认业务配置、正式 Windows BAT、宿主启动时浏览器前台拉起、系统原生选择器、Excel/WPS 原生打开及新打包产物。自动化出现 PyMuPDF/SWIG 类型的弃用 warning，不影响通过；文档契约首次拒绝把精确 commit 写入当前架构状态页，已改为从本条历史记录引用。未提交、推送、合并或发布。

### 2026-10-10 参考凭证草稿与捷锐导入文件（命令行）

- 需求：用户补充 6 月对账单和成本发票清单后，评价另一 Agent 接手产出的季度做账建议包（多份 PDF、35 个工作表）“细致但无从下手”，要求收敛为：提供应纳税款信息与银行流水 → 预生成参考凭证 → 人工修改/审核 → 直接导入捷锐，并随凭证增多学习账套习惯。在当前工作分支 `codex/selection-workflow`（`ddf5ab6`）上继续，银行流水代码仍为未提交状态。
- 方案：新增 `bank/ledger.py`（按名称路径在 `凭证/科目表.json` 定位末级科目）、`bank/vouchers.py`（销项/进项发票、银行流水、待认证进项转出、月末增值税与附加、季度印花税）、`bank/jierui.py`（审核表、校验、按月写捷锐导入模板、做账习惯与导出记录）与 `bank/voucher_cli.py`（draft/export）。会计人员只需维护一份 `申报数据.json`（首次运行从缴税回单预填），审核表一行一条分录，带边框与“通过/不导入”下拉，另附待补科目与试算表。
- 账套习惯：沿用科目表与映射规则体现的做法（供应商预付与货款同记应付账款并挂供应商辅助核算、库存商品按品类、其他应付款按往来户名设明细、手续费按月汇总）；人工在审核表中改过的科目按槽位记入 `做账习惯.json`，下次生成优先沿用。
- 修正：往来角色中只有人工条目优先，自动写入的“未知”不再压过发票证据；同凭证同科目分录合并（如社保多个险种）。
- 结果：用户本机第三季度资料生成 47 张参考凭证，三个月借贷平衡，草稿中银行存款变动与对账单逐月一致；9 月增值税按“本月票 + 8 月待认证票勾选”测算为 5,633.63，与另一 Agent 的同口径情景一致；列出 9 项需在捷锐先补建的科目与供应商档案。补入 6 月对账单后断档错误消失，6 月 30 日账银差额 40,000 对应 6 月 26 日一笔往来款转入，待核实是否漏记。导出流程在临时副本上演练：合格凭证按模板列导出、缺科目凭证被拦截且该月整月不导出、重复导出被跳过。真实产物只写在公司资料夹 `做账草稿/`。
- 验证：新增 `tests/test_bank_vouchers.py`（7 项，合成科目表与发票），银行相关 17 项与文档契约 16 项通过；完整 Python 回归（仓库外临时虚拟环境，按 `requirements/dev-py314.lock` 重建）792 项通过、16 项跳过。首轮因临时环境被系统清理缺少 fastapi 导致收集错误，重建环境后全部通过，与本次改动无关。`compileall` 与 `git diff --check` 通过。
- 未覆盖：捷锐导入格式（凭证字、编号、辅助核算）未实测，首次须只导入一张核对；未生成销售成本结转、工资社保计提、企业所得税与期末损益结转；未接入页面/API，不进入 W8/W9 状态链；未覆盖 Windows BAT、浏览器、原生选择器与打包产物。未提交、未推送。

### 2026-10-02 银行流水底稿与脱敏输出（命令行）

- 需求：用户准备季度补账，要求设计并开发“银行对账单/回单 → 做账报税辅助”的流程，并做好数据脱敏，宗旨是辅助财务人员而非自动入账。起点为 `main@ee0f2c2`，在 `codex/bank-statement-workpaper` 分支施工，保留既有未提交的税务设计与交接文档改动。
- 过程：先只读检查用户本机样本，确认流水与回单均为带文本层的中国银行 PDF（对账单为定宽竖线表格，回单一页两张且文本层中标签与值顺序不稳定，缴税回单附税费种明细）。据此放弃“以 Excel 为基准”，改为“每家银行一个适配器 → 统一标准记录”。
- 方案：新增 `src/invoice_hub/bank/`（models、boc 适配器、checks、matching、classify、redaction、workpaper、`__main__`）。按内容识别版式；逐行余额、页脚合计、月度断档/重叠、账面期初差额和重复行进入校验结果；回单先按流水号+金额、再按日期+金额+方向唯一匹配；缴税回单按税费明细拆分到应交税费与社保；往来角色优先取私有 `往来单位.json`，其次由发票明细推断客户/供应商；每条建议分录带置信度、依据、需补资料和复核标记，并明确为“建议，待人工确认”。
- 脱敏：同一构建函数经私有/脱敏两种视图输出。自由文本只保留用途关键词白名单；户名用私有密钥 HMAC 稳定化名，公共机构只保留机构类型；账号留尾号 4 位；回单编号、验证码、客户号、业务编号、税号等改为不可逆标记；源文件名改为序号；金额与日期保留。写出前全量泄漏扫描，命中即不写任何底稿（退出码 3）。密钥与化名对照表只在私有输出目录。
- 结果：用户本机真实样本端到端运行成功，全部流水行匹配到回单，脱敏底稿泄漏扫描通过；校验结果准确报出缺失月份对账单和账面期初与银行余额的差额，供会计人员核实。真实产物只写在用户公司资料夹，不进入仓库。
- 规则与地图：做账规则新增“银行流水底稿规则”；FILE_MAP（目录规则与 10.2 节）、AGENT_TASK_MAP（快速索引与 10.3 任务入口）、DATA_AND_ALGORITHMS 4.6、INTERFACES_AND_FLOWS 3.5.1（命令行、退出码与时序图）、COMMENT_RATIONALE_MAP、DEVELOPMENT_ARCHITECTURE、MIGRATION_GAP_CHECKLIST 与 IMPLEMENTATION_STATUS 同步。
- 验证：新增 `tests/test_bank_workpaper.py`（10 项，测试内生成合成 PDF，覆盖方向翻译、续行拼接、余额断裂、断档/账面差额/重复、未知版式拒绝、回单坐标解析与匹配、端到端私有/脱敏输出、人工角色保留、fail-closed、词边界扫描与 CLI）。完整 Python 回归（仓库外临时虚拟环境，按 `requirements/dev-py314.lock` 安装并以路径文件指向 `src`）740 项通过、16 项跳过；首次运行因临时环境未让 monitor 子进程导入项目包，2 项 monitor 用例失败，修正环境后全部通过，与本次改动无关。`compileall` 与 `git diff --check` 通过。
- 未覆盖：仅支持中国银行版式，未做 Excel/CSV 或其他银行适配器；未接入页面/API；建议分录不进入 W9 凭证链、不生成导入批次、不操作捷锐或电子税务局；未覆盖 Windows BAT、浏览器、原生选择器与打包产物。未提交、未推送。

### 2026-09-12 税务工作台价值评估与政策中心交付形态

- 用户询问计算器完成度与政策信息合集的意义，并要求把痛点与判断记录下来供开发者重新评估。沿当前 main 与既有未提交修改继续，只改文档，不新增代码、抓取或外部请求。
- 新增 [价值评估与就绪度](docs/TAX_WORKBENCH_VALUE_AND_READINESS.md)（决策文档）：会计五项痛点、计算器就绪度核查、旧草稿定位结论、政策中心价值与护城河、最小可用形态，以及按仓库实验纪律组织的开发者重新评估清单（假设 / 会改变决策的结果 / 最小样本 / 停止条件 / 不得执行的实验）。
- 核查结论：仓库内没有生产 tax 代码、路由与测试；`src/invoice_hub/tax/` 只剩字节码与空 `rules/`；原型 297 行且无任何金额运算（无 `parseFloat`/`toFixed`/`Number()`）。旧 MVP 草稿源码在工作树、两个 stash 与全部 Git 历史中均不存在，可能在发布工作树之外的私有归档，本轮未核实 —— 因此设计文档中“D0 逐文件迁入 MVP”的前提不成立。
- 据此修正 [工作台设计](docs/TAX_WORKBENCH_DESIGN.md)：§1 现状表与 D0 改为“先定位草稿并只读核对；不可得时按规格重新实现”，并写明预期值取自官方正文与独立手算。
- [政策来源与核验](docs/TAX_POLICY_SOURCES_AND_REVIEW.md) 新增第 6 节“从治理到交付”（订阅与待办、覆盖声明与漏报保障、版本差异展示、运营成本与复核人力），明确不做资讯流、不自行撰写解读、漏报必须可通过覆盖声明被检验、无固定复核人力时退回最小形态；后续小节顺延编号。
- 规则页与地图同步：`rules/TAX_WORKBENCH.md` 增加投入前评估与草稿定位、政策中心交付形态两条；FILE_MAP、AGENT_TASK_MAP（首先阅读与 2026-09-12 决策补充）、DEVELOPMENT_ARCHITECTURE、MIGRATION_GAP_CHECKLIST、IMPLEMENTATION_STATUS 一并回填。
- 验证：`python3 -m pytest tests/test_development_documentation.py` 通过，`git diff --check` 通过。本轮仅改文档：未验证任何被引用的运行时事实之外的行为，未运行产品回归（无 `.backend-venv`），未覆盖浏览器、原生界面、打包或真实税务数据；草稿是否存在于私有归档未核实，未据此推断其可复用性；未提交、未推送。

### 2026-09-12 税务设计补政策来源治理与“从测算到申报”交付物

- 用户要求按上一轮会计/税务专业评审的建议优化现有设计并更新时效政策内容。沿当前 main 与既有未提交修改继续，只改设计文档，不新增产品代码、API、抓取任务或外部请求。
- 新增 [政策来源、核验与政策中心](docs/TAX_POLICY_SOURCES_AND_REVIEW.md)：按 A 级官方原文（法律法规、财政部与总局公告及规范性文件）、B 级解释与征管口径（解读、答问、税费种认定与期限提示、地方口径）、C 级专业线索、D 级视频号与自媒体四级分层；只有 A 级可进规则包，B 级只产生待核对提示，C/D 级只进线索箱。给出获取难度实测评估（原文易、结构化与地方口径难、适用性判断最难）、四层政策中心（原文/条款/口径/适用）、变更流水线与发布纪律、`reviewer/reviewed_at/coverage_through/review_status` 签署与时效管理。
- [工作台设计](docs/TAX_WORKBENCH_DESIGN.md) 增加第 8 节“从测算到申报”：申报表映射（绑定表式版本，改版后 stale，缺样例不输出行次）、征期与申报期限（记录来源与核对日期，期限只作提醒）、留存备查清单（来自本次实际引用的规则与证据）。同时补入税费种认定作为“该报哪些税”的第一判据、资格与认定按生效期间回放、税会差异调整项台账、三单匹配视图、进项转出与分摊首轮不做自动计算，以及不输出筹划方案、不替用户选口径、不把测算表述为“应当缴纳”的输出边界；API 草案增加 `filing-calendar` 与 `form-mapping` 两条未注册路由，D2/D3/D5 交付与验收同步细化。
- [算法规格](docs/TAX_ALGORITHMS_AND_POLICY.md) 在解释验收中增加跨期例与政策变更例两类样例及定义，样例表补两条独立预期（跨期递推、规则包中途更新），并写明结果必须随附规则包版本与 `coverage_through`，核验局限补充“表式行次、征期、地方口径、留存模板均未核验”。
- 规则页与地图同步：[税务规则](docs/architecture/rules/TAX_WORKBENCH.md) 增加来源分级、三项申报交付物、税费种认定、资格回放与输出边界条目；FILE_MAP、AGENT_TASK_MAP 税务行（D2/D3/D5 与最低验收）、DEVELOPMENT_ARCHITECTURE、COMMENT_RATIONALE_MAP（四条新不变量）、MIGRATION_GAP_CHECKLIST 与 IMPLEMENTATION_STATUS 一并回填。
- 验证：`python3 -m pytest tests/test_development_documentation.py` 通过，`git diff --check` 通过。本轮仅改文档：未运行产品 Python 回归（本工作树无 `.backend-venv`），未覆盖浏览器、原生界面、Windows BAT、打包产物或任何真实税务申报对照；未执行任何政策抓取，未核验新的文号、比例或地方口径，设计中的政策事实仍以 2026-09-11 核对范围为准；未提交、未推送。

### 2026-09-12 配置用户级全局 Agent Handoff 入口

- 用户希望工具可放在用户 `.agents` 目录并从任意项目调用。沿当前 main 与既有未提交修改继续；核对 Codex 官方用户技能目录和本机 Claude 技能链接方式后，采用“工具本体、共享技能、全局命令、私有状态”分离布局。
- 已将 SHA 匹配的 1.1 Mac 便携包安装到用户 `.agents/tools/agent-handoff`；简短技能放在 `.agents/skills/agent-handoff`，Claude 的 `.claude/skills/agent-handoff` 使用相对软链接共享规则；`.local/bin/agent-handoff` 为启动脚本，可用 `AGENT_HANDOFF_TOOL_DIR` 指定其它解压位置。既有 PATH 已包含该 bin 目录，未修改 Shell 配置、全局 AGENTS/CLAUDE 或权限设置。
- 技能按保存/接手/交接意图发现，正文约 2.2 KB，不要求每次对话加载或写检查点；其它项目明确传 project/workspace，不沿用 InvoiceHub 默认项目名。个人安装、技能与审计留在仓库外，不纳入源码或便携包输入。
- 验证：原包外层 SHA 与全部成员校验通过；技能 frontmatter 验证通过；全局命令在工作区外返回 1.1.0，另一临时项目的 init/resume/release/ticket 通过且未生成源目录状态文件；Claude 链接解析到同一技能。系统临时目录中的验证器解释器缺少 PyYAML，已改用项目验证环境完成同一验证，未安装额外依赖；工具运行本身只依赖内嵌标准库。
- 本轮只配置本机用户级入口并同步说明，不重复业务回归或调用模型测试自动匹配；新会话的技能发现遵循各客户端机制，未覆盖其它电脑、Windows 全局安装或新的权限授权。个人安装持续保留供使用，暂存解压和临时验证资料收尾清理；未提交、推送或发布。

### 2026-09-12 优化任务链接定位与检查点开销

- 用户要求切换 Agent 时能明确指定任务线，核查是否可用线程深度链接/ID 接手，并减少轮询、SSD 重复写入和模型上下文冗余。沿已授权 main（起点 `ee0f2c2`）继续，保留前序工具与设计修改。
- 核查确认无后台定时轮询；原实现会每次保存完整状态并重写同项目所有 CURRENT，且一份实际 CURRENT 为 19,826 bytes，存在正文/JSON 重复。1.1 增加本地 bind/resolve/ticket，支持明确 handoff URI、已登记线程链接与 UUID；未登记或歧义均拒绝猜测，不读取聊天数据库或调用模型。
- 默认摘要预算 3,000 字符、按需 section/full 展开；省略关键约束时显式要求展开，全文保留。默认 resume 不扫描文件，claim 只校验一次；无变化不增加 revision、不写检查点；只更新当前任务 CURRENT，v2 后续事件保存增量并保持 v1 历史原字节可读。交出任务可用 release --input 合并保存，list 默认有界，入口规则禁止逐工具调用保存或循环轮询。
- 便携构建支持从可信 SHA 的旧包仅复用已验证 runtime，重新复制当前公开工具/说明，本轮无运行时网络下载。64 项聚焦测试和 4 个子测试通过；包含新旧日志混合读取、错误 delta 拒绝、同内容不写盘、其它任务 CURRENT 不被改写、默认读取不哈希、claim 仅哈希一次、引用歧义与预算/全文保留。相关源码编译与 diff 检查通过。
- 同一真实历史检查点的默认 CURRENT 从 19,826 bytes 降为 4,766 bytes（约 76%）；默认 resume 为 2,632 字符。同一历史认领事件的完整/增量编码对比为 4,885/413 bytes。原 journal 没有为测量或压缩重写；仅对原 CURRENT 执行一次显式 repair。上述是字节/字符计量，不宣称精确模型 token 或物理 SSD 写入量。
- 最终 1.1 Mac arm64 ZIP 为 41,753,765 bytes，SHA-256 `2fd0c122cdb792edbe94ed5f0d33230f724b2c9f4687ffe9634474f5e1fb7570`；Windows x64 ZIP 为 12,328,124 bytes，SHA-256 `af58cc3dde112b0ef929c698fa8c8d09171316a887679f1b5c0be248df060dd9`。两包当前源码/说明逐字节一致，私有状态成员为零。Mac 在新中文/空格目录、内嵌 Python 下完成 19 次 CLI 调用验收，覆盖链接/ID、无变化零改写、摘要按需展开、显式漂移检查与增量交接。
- 私有状态、真实引用和验收报告均留在仓库外；1.0 包保留作回退，1.1 包与 SHA 留在 ignored `dist/agent-handoff/`。未重新调用模型做全文总结，未提交、推送或发布。Windows 原生、GUI 双击/Gatekeeper、网络盘互斥和 InvoiceHub 业务验收未覆盖；本轮临时验收脚本/目录与新增缓存收尾清理。

### 2026-09-12 实现通用任务检查点与便携接力工具

- 用户要求完整实施通用交接架构、随后交给 Claude Code 补充，检查点不绑定厂商，并能打包解压使用；仓库外私有内容不得上传。沿用户此前明确选择继续 main（开工 `ee0f2c2`），保留已有规则重组、税务设计和未跟踪草稿。
- 新增标准库单文件 CLI 与通用协议：项目索引、任务检查点、文件/Git 指纹、CAS 更新/认领/释放、已开始/未知/确认操作和损坏恢复。私有状态默认位于用户目录下 `.agent-handoff`，不落入公开工作树。入口只规定阶段性维护，不宣称安装了自动 hook 或模型切换服务。
- 便携包从明确公开白名单与 SHA 固定的 Mac arm64/Windows x64 CPython 3.14.6 原始运行时组装，保留许可、使用固定 ZIP 时间/顺序并生成逐文件 manifest 和外层 SHA；不递归复制本机配置、日志、检查点、Git 历史或业务数据。
- Claude Code 已从同一私有检查点实际核对、认领、补充实现与 13 项测试、保存并释放，Codex 按协议接回。首轮因 Claude 会话缺少私有目录与指定命令许可而停止；仅补齐本次会话权限后续接，未放宽全局配置。一次回合上限中断后的检查点收尾也已完成，审计记录只保留在仓库外。
- Codex 独立复核后补齐跨 project 共用私有根目录锁（避免扫描后并发双认领）、Git 环境覆盖变量隔离、普通文件交互入口、UTF-8 输出，以及 Mac runtime 九项跨平台辅助文件精确移除与未知 Windows 载荷拒绝。53 项聚焦测试、4 个子测试和相关编译检查通过；文档契约继续守护两份入口与规则导航。
- 最终 Mac arm64 ZIP 为 41,752,045 bytes，SHA-256 `e69a8f0cd1e38ce1ccbf6bb4b50eed2df25b859f7d4538867b3bc9248b43c463`；Windows x64 ZIP 为 12,326,406 bytes，SHA-256 `2979044e6ee1affcd2096954768a0616aaf994b727f5e0ec033d7c47659d4b45`。两包内工具/协议/许可与本轮公开源文件逐字节一致，逐文件清单通过，私有检查点/模型审计成员为零；Windows Python 的 PE x64 身份已静态核对。
- Mac 最终包从新的中文/空格路径解压，以内嵌 Python 3.14.6 arm64、排除系统 Python 的 PATH 和无效 PYTHONHOME/PYTHONPATH 完成 16 步 CLI 验收：普通文件任务、通用 actor 接手、状态漂移、未知结果阻断、确认后完成与投影修复均通过，工作目录仅保留原合成源文件。Windows 仅静态验证，未运行原生 Windows/msvcrt、双击 Terminal、Gatekeeper/quarantine、签名/公证或网络盘并发；不等同于 InvoiceHub 产品启动/业务/发行验收。
- 便携包与校验文件保留于 ignored `dist/agent-handoff/` 供使用，私有任务及 Claude 审计/验收报告留在仓库外；本轮临时下载、解压和验证脚本收尾清理。未提交、未推送、未发布应用或工具 Release。

### 2026-09-11 精简 Agent 必读入口并按功能组织规则

- 用户要求保留 AGENTS.md 的通用必读内容，将功能细则划入架构地图以便快速查找问题；随后明确可以在 main 执行。开工在 `codex/tax-workbench-design`，与本地 main 同为 `ee0f2c2`；切回 main 时完整保留既有税务设计、原型、未跟踪文件和 ignored 运行态。
- AGENTS.md 保留开工、项目/数据/公开历史边界、文档与注释、Git/授权、验收和收尾；功能规则逐条迁入 `docs/architecture/rules/` 的提取、成本、监控、页面、做账、税务、Windows、macOS、Tauri 与发行十个专题。目录细则归 FILE_MAP，Git 命令细则归现有 Git 指南；必读规则按命中功能完整读取，跨功能取并集。
- 任务地图前部增加问题关键词 → 强制规则 → 原有任务行的索引与稳定锚点；更新各专题、文件地图和架构入口的引用，修复失效的“到 AGENTS 读功能细则”指引。CLAUDE.md 改为共用入口，保留架构快捷查询与税务设计定位，并统一 README 定点维护约定。未改产品代码、真实配置、原型或发布输入，也未增加交接脚本。
- 验证：AGENTS.md 从 72,780 bytes 缩至约 13.4 KB，CLAUDE.md 为 2,770 bytes；核对原 AGENTS 的 262 个规则块，260 个原文保留（仅规范化空白和迁移链接），另 2 项分别合并到更完整的验收清单、改为按所属规则归档风险，约束未删减。16 项文档契约通过，覆盖新增专题的文件地图/链接、双向定位锚点、入口大小预算与既有规则语义；`git diff --check` 通过。保留旧 CLAUDE 的前端、监控与原生停止补充约束到对应专题。纯文档与文档契约变化，未运行产品全回归，未覆盖前端、localhost、Windows BAT、原生壳、账套操作或打包产物验收；未提交、未推送。

### 2026-09-11 同步 CLAUDE.md 与 AGENTS.md 入口约束

- 用户要求以 `AGENTS.md` 及其它现行真值文档为准更新 `CLAUDE.md`；随后补充三项要求：删除 `AGENTS.md` 中过期的开发主线计划行、把税务工作台/税务计算器这条新功能线写入两份总文档、并让 `CLAUDE.md` 具备架构地图的快捷查询能力。继续在 `codex/tax-workbench-design` 施工，保留前序设计与原型修改。
- `CLAUDE.md` 修正过期基线：删除“下一开发主线为 `codex/tauri2-unified-desktop`、起始 `0.3.0-alpha.1`”这类已失效表述（该分支已合并清理，Tauri 2 已在 `main` 的 `src-tauri/` 内），版本与发布参照改指 `src/invoice_hub/version.py` 和 `release/build_manifest.py` 的 `API_CAPABILITIES`，并明确已发布资产不授权更新 Feed 或启用 updater；分支、提交与工作区状态一律以实时 Git 为准，不再写入该文件。
- `CLAUDE.md` 新增“架构快捷查询”一节：列出六张地图各自回答什么、按改动类型给出首要入口与对应章节（提取、分类、成本、路径、monitor、设置、前端、单据与打印、做账、Windows 平台、macOS 壳、Tauri host、发行、API/存储、税务），并写明同一任务内必须回填的地图。
- 两份总文档同步写入税务工作台规则：`CLAUDE.md` 新增“税务工作台与公司资料”，`AGENTS.md` 新增“税务工作台与税务计算器规则”，并删除项目边界中那条过期计划行（Tauri 的所有权边界仍保留在“开源冻结与 Tauri 2 规则”一节，未丢失约束）。规则写明当前只是设计阶段：不注册 API、不读取公司资料、不入包；未知用 `null` 不用 `0.00`；金额税率走 Python `Decimal`、解释与结果共用 `CalculationTrace`；公司绑定独立于 `watch_dir`；自定义税率只作用户假设；D0 必须替换旧草稿错误规则。
- 验证：`python3 -m pytest tests/test_development_documentation.py` 15 项文档契约通过（含两份总文档的本地链接可解析、无本机绝对路径、无 commit 式哈希、无 stale marker），`git diff --check` 通过。本轮仅改文档，不运行产品 Python 回归（本工作树无 `.backend-venv`，系统 `python3` 亦无 fastapi），未覆盖前端、浏览器、原生界面、Windows BAT 或打包产物验收；未提交、未推送。

### 2026-09-11 缩小计算器界面并增加自定义税率

- 用户要求完整按键无需下划，并增加自定义税率；继续在 `codex/tax-workbench-design`（开工主线 `ee0f2c2`）调整设计与原型。
- 计算卡由约 360px 收至 292px，整体双栏约 660px；按可用高度分配 44—54px 按键，正面独立布局，长背面不再参与正面高度，结果区单独滚动。普通短窗口优先显示全部 20 键，低高度横屏将显示与键盘并排，极小视口保留可达性兜底。
- 税率新增“自定义”，与 6%/9%/13% 预设共用一行；支持 0—100%、最多四位小数，非法值阻止计算，自定义标记用户假设并使旧结果/解释待重算。原型不计算自定义税额，后端百分数归一化与契约写入后续设计；切换合成场景/恢复示例会同步恢复预设税率，避免旧输入与示例结果混用。
- 同步设计、接口/数据/任务/注释/文件地图、实现状态和缺口清单。15 项现有文档契约通过，原型 JavaScript 语法、20 键结构、DOM 引用、15 个自定义税率边界及无业务 IO 检查通过；按固定尺寸预算复核 540/600/768/900 高度与 360/400/480/539 低高度横屏的按键空间。尺寸预算不替代实际浏览器渲染，本轮仍未做像素/点击、当前皮肤/恢复入口、真实配置/BAT/原生界面或成品验收。
- 本轮仅原型与设计变化，不跑完整产品或税务算法回归，不改产品源码或真实配置，不执行产品启停、申报、打包、提交或推送；既有本地文件预览的浏览器策略限制保持，不绕过访问。

### 2026-09-11 固定计算器置顶入口在首页左侧

- 用户明确置顶栏图标应位于“首页”左侧、纵向居中，不能穿插模块；继续在 `codex/tax-workbench-design`（开工主线 `ee0f2c2`）调整原型。
- 将计算器工具槽移到整组模块导航之前，与导航通过 flex 居中对齐；保留首页、成本、单据的连续顺序，位置切换仍移动同一个入口。同步设置说明、工作台设计、接口/任务/注释地图与实现状态。
- 本轮仅原型布局及文档变化，验证原型结构、JavaScript 语法、文档契约与 diff；不运行完整产品回归。未覆盖实际浏览器像素/点击、当前皮肤与恢复入口、真实默认配置、正式 BAT、原生选择器或打包产物，未提交/推送。

### 2026-09-11 缩小计算器入口并增加位置选项

- 用户补充要求缩小计算器图标，并在设置选择界面内悬浮或收入“首页”按钮所在置顶栏；继续在 `codex/tax-workbench-design` 完成同一设计任务。
- 原型入口改为约 20px 图标、32px 可见按钮及 44px 有效点击区；设置新增互斥位置选项，即时移动同一个入口并保留计算草稿。悬浮支持拖动、视口边界和重置，拖动后不误触打开；置顶栏模式不重复显示悬浮图标。
- 设计将位置保存纳入现有 preferences 字段，独立于公司资料夹；原型仅会话内保存。同步架构接口、数据、任务、注释、文件地图及实现/缺口状态；与前述原生目录选择流程一并交付，产品代码与真实偏好未变。
- 验证：15 项现有架构文档契约、原型 JavaScript 语法、DOM ID/标签/选择器引用、无业务 IO、设计链接/围栏与 diff 检查通过。未新增产品代码，不运行完整产品回归；正式位置持久化、实际浏览器布局/点击、当前皮肤与 `no_skin=1`、默认配置/BAT/原生窗口及平台成品验收仍属 D1/D2。沿用前轮本地文件预览受浏览器策略限制的说明，本轮没有绕过访问限制。

### 2026-09-11 补充公司资料夹原生目录选择设计

- 用户补充“选择公司业务资料夹可拉起原生选择器”；继续在 `codex/tax-workbench-design`（开工主线 `ee0f2c2`）维护设计与原型，保留前序修改。
- 核对现有 `pick_directory`、Tauri `select_path` 和 Host RPC 枚举，设计独立 `pick_tax_company_dir` 用途与 `POST /api/v1/tax/workspace/pick-directory` 草案。系统窗口只返回待保存路径，检测/保存后才绑定；取消、失败和过期返回均保护原草稿与绑定，不改变发票 `watch_dir`。
- 原型增加明确标为模拟的本地目录选择流程，支持选择示例、取消和不可用，再单独检测/保存；同步工作台设计、接口/平台/任务/注释/文件地图与实现状态。真实原生能力接入及 Windows/macOS 验收列入 D2，本轮不变更产品 API、Host RPC 或真实目录。
- 验证：与本次小入口调整一起完成 15 项文档契约和原型静态检查；未实际拉起系统窗口，不冒充 Windows/macOS 原生选择器验收。仅设计与模拟交互变化，不运行税务算法回归、产品启停、正式 BAT 或成品打包，也不提交/推送。

### 2026-09-11 税务计算器交互与公司财税工作台设计

- 需求：以最新产品为基础，设计首页左侧计算器、图标展开、税种切换/勾选并列、翻面解释及可选公司资料读取。开工分支 `codex/redacted-screenshot-gallery` 与稳定 `main`、远端主线同为 `ee0f2c2557d2b2a3640e9c00d9b8241581db4409`，从该 `main` 新建 `codex/tax-workbench-design`；保留既有未跟踪文件与 ignored 配置/运行态。
- 核对三个关联任务、当前源码/架构与保留税务草稿，确认已发布参照为 `v0.3.0-alpha.2-opt.1`，程序内版本仍为 `0.3.0-alpha.2`；旧计算器尚未集成当前主线，草稿和历史验证不视为现行已验收能力。
- 新增设计、算法/政策规格与独立合成交互原型：明确纯计算/资料测算/申报对照、独立 nullable 公司绑定、按需资料角色、后端 Decimal/trace/解释共源、逐月留抵和季度累计预缴、任务取消/快照失效及分阶段验收。原型只播放预设案例，任意输入显示待重算，不在浏览器实现税务算法。
- 官方核对纠正营业账簿每本 5 元、产权税目一律万分之五、六税两费任意当地比例和过期依据；2026 起征点采用“未达到”，与教育费免征“不超过”的边界分开。读取官方法律、公告与印花税率表附件；资料只保留脱敏设计结论与官方链接，未复制真实季度/月度业务数据。
- 验证：15 项现有架构文档契约通过，新文档链接/围栏/本机路径检查、原型 JavaScript 语法/DOM 引用/无业务 IO 检查、价税分离/逐月留抵/附加/资本增量/累计预缴的独立 Decimal 合成复核及 diff 检查通过。原型静态复核还修正了跨税种草稿隔离并补齐图标许可。
- 浏览器本地文件 URL 策略拒绝加载原型，未继续绕过该限制；未完成像素、实际点击、窄屏/皮肤/`no_skin=1` 视觉验收。未获取真实完整季度账簿、企业资格或电子税务局舍入样例；算法文档明确现行教育费附加全文和到分舍入的待补证项。
- 本轮仅设计文档及独立合成原型，未运行完整产品回归或构建，因为产品源码、运行入口与包输入没有改动；未覆盖真实默认配置、Windows BAT、浏览器前台拉起、原生选择器、实体打印或打包产物。不改变真实配置、发票/成本/凭证、原 stash 或 Release，不执行申报、外部账套写入、提交或推送；临时官方正文与附件在核对后清理。

### 2026-09-10 alpha.2 优化版 1 同源构建与发布

- 主线同步的首个 PR 被 DCO 拒绝：两份 Windows 原始提交缺少 sign-off。为保留已发布来源与 Tag，在新的 `codex/opt1-release-integration` 分支通过带 `-x` 来源记录和 `-s` 签署的 cherry-pick 集成，逐字节确认与已核验树一致；不 rebase、不强推、不改写原提交或制品。

- Windows 已推送 `codex/windows-alpha2-release-source`，本机 fetch 核实为 `0d5239f113ac5017174fbbf09dd30817ebeed432`；与收据及上一轮同步代码一致，前次缺少原始 Git 提交的阻塞解除。原文档修改与既有未跟踪文件先完整保存，本工作区切到精确 detached commit 完成构建，再恢复文档与原文件；没有把工作树草稿写入制品。
- 新优化批次 Tag 为 `v0.3.0-alpha.2-opt.1`，程序内版本仍为 `0.3.0-alpha.2`，优化内容为 OFD 原票预览、HTTP 响应分帧、PYTHONHOME 隔离、spawn 诊断和 Windows 暂存发布有界重试。旧 alpha.2 Tag/资产保留；两端共同 core build ID 为 `0f41b453964c635dc6d0623c98d7abffef8614f6d65709853da877d7733b53b0`。
- Mac 从干净的同一提交构建 App/DMG，包含 Python 3.14.6 与平台专用 Java 21/OFD 组件；DMG 为 `169041824` bytes，SHA-256 `c9076f464e8544391314eda0bd277aee047ba27623f572c265d1d91e8e7cd6da`。中断续作的 pending 收据末尾被写成了字面转义，已只修正 JSON 编码，再真实验包、finalize 并默认复验；App/DMG 字节未因此改变。
- App/DMG/receipt、包/host/launcher/runtime/OFD 清单和 153 项 Mac 核心源码字节核对通过，Windows 平台载荷为 0；包内解释器和组件完成两页合成 OFD 的文字、矢量、图片分区及横纵方向核验，源文件未改变。实际 App 使用 Application Support 配置达到 health/background ready，两个首页入口各 8 项静态资源匹配，monitor start-ready-stop 后恢复原 false；新 App 保留供使用。
- 隔离 HOME 自动样本仍未通过，用户手动打开的实例落在真实 Application Support，已单独记录；临时启动实例退出后，从保留目录启动的完整 App 通过上述正常配置验收。此结果不冒称隔离运行、所有业务版式、原生 picker/实体打印、完整浏览器/托盘、公证或 updater 验收。沿用同源码此前的 99 项 Rust、57 项 Python 和 25 项 OFD 结果；交付提交现有 Windows/macOS CI 均通过，不重复累计。
- 发布资源共 10 项，包含双端程序、SHA-256、receipt 及平台 Python/OFD 两类 SBOM。Mac 与 Windows 的 OFD SBOM 使用明确的平台文件名，避免同名覆盖；优化版 Pre-release 已公开（Release ID `386044541`），10 项服务器大小与 SHA-256 均和本地发布清单匹配。首页只新增用户要求的维护约定，并定点调整优化批次下载入口与 OFD 随包说明，不重做整体布局、话术、截图和未来计划。

### 2026-09-09 接收 Windows 优化包并准备 Mac 同步

- 从 `main@b3d69f636e5dab17aa856630b0a56fa9d9accfab` 创建 `codex/alpha2-optimized-release`；保留既有未跟踪文件和 ignored 配置/运行态。用户要求同步 Windows 启动加固补丁和 OFD 组件至 Mac，完成后发布有明确优化标识的新 Tag。
- Windows receipt 记录来源 `0d5239f113ac5017174fbbf09dd30817ebeed432`，核心身份 `0f41b453964c635dc6d0623c98d7abffef8614f6d65709853da877d7733b53b0`。全分支 fetch 与精确 SHA fetch 后 GitHub 仍返回 `not our ref`；普通 patch 能恢复内容，不能还原原 Git commit 身份。本轮不伪造来源、不复用旧 alpha.2 Tag。
- 已核查并应用附带 patch 的代码与技术文档，首页的启动修复流水段落未带入，按用户要求只新增首页维护约定，并将该约定同步到 AGENTS。核心指纹重算与 Windows receipt 一致；完整同源组包需补齐该原始 commit 或包含它的 Git bundle。
- Windows ZIP 的实际大小和 SHA-256、receipt、静态 verifier 以及外置 Windows/OFD 两份 SBOM 与包内原件逐字节一致，151 项非生成核心文件与当前源码一致。Mac 已有组件的 31 个 JAR、Mac 平台和源码指纹校验通过，Python 3.14.6 + Java 21.0.12.1 组合 runtime 已准备到 ignored 的 `dist/runtime-inputs/20260909-optimized-macos/python`，迁移目录后再次通过 runtime manifest 与导入探针；不复制 Windows 组件或旧 core。
- Rust 99 项测试通过。首次四项回环绑定被沙箱拒绝，主机权限复验通过；Python 启动/Host RPC/portable/文档 57 项通过，Mac OFD 组件/API 25 项通过。API 初次因测试专用 httpx2 缺失未执行，按哈希锁准备独立测试环境后补验通过；存在上游 PyMuPDF SWIG 弃用提示。格式、文档契约和 diff 检查通过；没有重复全仓 Python、实际默认目录、Windows 真机/BAT、原生面板或最终 Mac DMG 验收。
- 组合 runtime 和 `dist/candidates/20260909-optimized-preparation/preparation-status.json` 保留供收到源码后继续；临时测试环境另行清理。拟使用独立优化批次 Tag 标识 alpha.2 优化版与 OFD/启动内容，包内产品版本保持 alpha.2；当前未创建 Tag、Release 或替换公开资产。

### 2026-09-09 Windows alpha.2 启动加固与修复优化包（交付方记录）

- 从 `codex/repackage-ofd-main@f71323b` 开工，七份既有 OFD 打包文档保存在 stash `474bdd8aab5379ed2653fad01b9c9e4a48c3842c`；首次 GitHub TLS 失败，原地址重试成功。main 快进到 PR #24 的 `b3d69f6`，新建 `codex/windows-alpha2-startup-hardening`。保留本机配置、旧包、ignored 运行态及未跟踪压缩包，不推送或修改 Release/Feed。
- 核对新增内容为 HTTP 响应分帧、阶段诊断、单次启动方式与 Windows 浏览器兜底；原 OFD 专用渲染继续保留。实验以真实 Winsock abortive close 检验完整 200/204 与截断响应，并以随包 Python 的错误 PYTHONHOME 检验初始化隔离，结果决定加固范围；不冒充公测原机复现。
- 内置 Python 在错误 PYTHONHOME 下出现 encodings 初始化失败，清除后成功；host 在创建子进程前移除该变量，monitor/worker 继承清理后的环境。spawn 前重置本次探测日志，spawn 失败保留脱敏系统错误码，不记录环境值或凭据；不改变用户全局环境、配置或严格 ownership。
- 验证与新包身份在成品验收后补齐；产品版本保持 `0.3.0-alpha.2`，修复优化包以独立候选目录、源码提交、receipt 和 SHA-256 区分，不覆盖旧公开资产。
- Windows 原主线 Rust 97 项通过；改动后库回归除新增夹具外通过，新增 Winsock 夹具最初在 read 前 reset，系统直接丢弃未读数据（10054），不属于完整响应后错误的假设。将真实 abort 调度在 read 交付字节之后，新回归通过，且证明截断仍返回 10054；没有放宽生产响应检查。Python 启动/Host RPC/文档/portable 聚焦 56 项通过；新增文档中的固定 SHA 被文档契约拒绝，改为 PR 来源导航后 15 项通过。compileall 与 diff 检查通过；完整 Python 回归、成品与原生验收仍待下方记录。
- 首次运行时副本被缓存门禁拒绝，重新生成无字节码副本并重算 manifest；递归缓存清理被自动审批阻止，原目录保留。组包暂存目录重命名重复出现 WinError 5，较短路径也未解决；对 Windows 5/32/33 增加最多 20 次、累计 1.9 秒的发布重试后实际 stage 成功，确定性测试覆盖短暂成功、持续失败及无关错误不重试，7 项 portable 契约通过。不修改权限、不跳过验证，不将暂存失败归因为已经查明的特定安全软件。

### 2026-09-09 提交并整合启动修复

- 用户明确授权提交、推送和合并。按精确文件清单提交 HTTP framing、诊断、浏览器兜底、合成回归及文档，使用 DCO sign-off 和普通 PR merge；没有上传外部日志/附件、本机配置、真实业务文件、运行态或构建产物。
- 架构入口、实现状态、排障说明和分支记录统一维护 main 源码基线，功能分支仅保留为来源；公开 alpha.2 制品和更新 Feed 不因源码合并改变。精确合并身份和 CI 结果以对应 PR、实时 Git 及本次任务结果为准。沿用此前完整测试证据，文档同步另跑契约；不追加未实际执行的平台原生或成品验收承诺。

### 2026-09-09 修复桌面启动探测与浏览器兜底

- 根据公测反馈的脱敏结论，后端可启动且成功响应，但桌面探测反复重试。任务从 `main@f71323b` 建立 `codex/fix-backend-startup-probe`；外部日志、原始路径和附件不进入仓库。现有日志不能证明外部机器的具体 socket 错误。
- 最小实验假设：HTTP 完整响应后连接重置会被旧读取循环误判失败；结果决定是否更换响应完成判定。使用一个合成 reader 分别提供合法 `200 + Content-Length`、`204`，随后返回 ConnectionReset；从旧源码提取的读取函数均返回 ProbeFailed，达到停止条件。此实验不冒充 Windows 原机复现。
- 新增有界 HTTP 响应组件，按 Content-Length、204/304 无正文和 chunked 终止标记完成读取；无长度旧响应仍须正常 EOF。保留 128 KiB 总响应上限、16 KiB 响应头上限，拒绝截断、重复 proof/头、长度冲突、非法 chunk 和未定义 trailer；单次握手的连接/写入/读取共用 5 秒预算，启动重试共用 20 秒预算，child 提前退出立即返回。
- `startup_probe.log` 保存本次 host/Python PID、尝试次数、耗时、清理前子进程状态和失败接口/阶段/字节数/系统错误码；不记录令牌、challenge、响应头或正文。诊断区分宿主 PID 和后端 PID，列出三份日志，并说明清理后的无监听状态不能还原此前故障。
- 新增仅本次生效的 `--browser` / `--desktop`；两者冲突拒绝，不改保存偏好。Windows 仅在后端已通过握手而桌面窗口创建失败时询问是否改用浏览器，确认后再次验证 child 与完整身份；拒绝、身份失效或浏览器失败仍走既有收尾。没有增加每次启动弹窗，浏览器不能绕过后端检查；普通关闭窗口、单实例、托盘与 monitor 语义继续复用现有流程。
- 最终验证：锁定 Rust 1.85.0 的 `cargo test --locked --offline --tests` 共 99 项通过，覆盖 9 项传输、6 项 surface 编排和既有 lifecycle/ownership/updater/marker；Python 全套收集 696 项，16 项按平台/组件条件跳过，初轮 2 项监控子进程因测试启动未传源码 PYTHONPATH 失败，补齐本次环境后这 2 项复跑通过，其余通过。compileall、格式与 diff 检查通过。首次默认 Python 缺少 certifi，使用既有开发 venv 解决；测试导入错误已修正。Windows target 标准库未安装，本轮未编译 Windows 条件分支，也未验收 Windows 真机、真实默认配置、正式 BAT、原生兜底弹窗、浏览器前台拉起、原生选择器或新 ZIP；已发布 alpha.2 不含此次修复。临时复现与 Python 测试目录已清理，既有 `src-tauri/target/` 编译缓存保留供后续构建，可在成品验收后清理。

### 2026-09-09 收束 OFD 评审与组件校验开销

- PR 自动评审提出模板页、Unicode 与重复哈希问题。核对 OFDRW 2.4.0 源码确认 `PageInfo.getAllLayer()` 已合并模板和正文层；新增模板独占内容的真实组件回归，正常票面与原页面 PNG 一致，模板缺字形时阻断。
- 上游 `AWTMaker` 同样使用 `charAt` 和 UTF-16 偏移；只将预检查改为 code point 会放行上游无法正确绘制的代理对，因此保留与引擎一致的失败保护，并增加未映射补充平面文字负向回归。该限制不宣称已解决罕见字完整支持。
- 修复每次翻页/选票都读取整个 Java 组件的问题：实例内缓存已验证身份，复用前检查目录、清单和全部成员的路径/inode/类型/大小/时间元数据；任何变化重新完整校验，校验失败清空缓存，首次哈希前后也核对同一快照。
- 25 项 OFD 测试通过，含真实 Mac 引擎、模板层、Unicode 失败保护、混选 API 和缓存失效。依赖锁和 Java 二进制未改变，无须重新打包组件；完整平台成品和其它业务版式仍不在该结果内。

### 2026-09-08 提交 OFD 预览并整合主线

- Windows CI 暴露 ZIP 名称预归一化：`ZipInfo.filename` 会替换反斜杠并截断 NUL，安全边界改为校验 `orig_filename`。负向夹具直接构造原始 ZIP 成员名字节，同时覆盖 NUL 和跨平台模拟的 Windows 分隔符归一化；保留原拒绝规则，不放宽错误码或跳过测试。

- 用户明确确认后授权提交、推送和合并 main；按受保护主线流程提交 OFD 专用组件、构建锁、合成测试和脱敏文档，采用 DCO sign-off 和普通 merge，保留功能历史。
- 架构入口、README、实现状态和分支记录统一按 main 源码基线维护，已发布 alpha.2 制品保持不变。真实发票、临时票面/演示副本、运行态、本机配置和构建二进制不进入提交。
- 本机重验已构建 Mac 组件的原生渲染与 API/相邻预览/打印/文档契约；远端依照仓库规则执行 Windows、macOS 和 DCO。真实单票浏览器效果已经用户确认；Windows 原生 OFD worker、正式 BAT、新桌面包、其它皮肤与原生选择器未覆盖，不作发行验收承诺。

### 2026-09-08 在 InvoiceHub 内打开真实 OFD 预览

- 用户进一步要求在 InvoiceHub 内查看，故通过既有 keep-monitor 关闭协议结束已核对身份的旧 WebUI（监控原本未运行），在固定 localhost 端口以当前源码启动开发服务。使用系统临时目录中的单票副本、独立配置和运行态，原发票、用户设置与已发布 App 文件未修改。
- health 确认为 development、backend/background ready；在真实浏览器界面从发票列表勾选该 OFD，经“更多勾选操作 → 预览”打开产品原有弹窗，截图确认真实票面已显示。预览由页面请求当前 API 与新组件生成，不是系统 Preview 或静态演示页。
- 当前开发服务、可见预览标签和临时单票目录为用户继续查看而保留；通过产品关闭入口停止后可清理本次临时目录。只覆盖浏览器默认浅色的这一单票路径，不扩大为原生桌面壳、Windows、全部皮肤或成品发行验收。

### 2026-09-08 打开真实 OFD 票面并由用户确认效果

- 按用户要求，读取下载目录中的一份单页真实 OFD，用本轮独立组件直接渲染，生成 1240×945 PNG，并在系统 Preview 打开；用户明确确认预览效果良好。没有修改原发票，也没有把真实文件、公司信息、号码或票面写入公开工作树。
- 本次确认只覆盖这一代表文件的可见预览效果，不等于所有业务版式、数字签名验真、软件内弹窗或双平台成品验收。当前运行的 alpha.2 仍未替换；功能分支没有因单样本确认而自动提交、合并或发布。为保持用户已打开的预览，临时 PNG 仅留在系统临时目录，关闭后可清理。

### 2026-09-08 清理已合并分支并实现独立 OFD 预览

- 按用户要求先核对主工作区、远端和工作树归属，从 `main@fda171d` 开工。普通删除 4 个已合并本地分支，以及已合并的 Desktop/文档同步 3 个远端分支；含独立提交或未提交改动的旧工作树、图标/搜索线、stash 和 Dependabot 保留。随后在同一工作目录创建 `codex/ofd-preview-renderer`，未推送新功能、未合并 main。
- 当前 OFD 被交给 MuPDF，旧测试仅在 ZIP 中放两张 PNG，不能证明真实 OFD 排版。新增 OFDRW 2.4.0 专用逐页 PNG 子进程、真实 OFD 页面树样本；复用现有预览 API、弹窗、分页/续租和缓存，识别、成本提取和 PDF 打印来源规则保持原口径。组件缺失/损坏、忙碌、超时、不安全结构及字体缺失都有逐文件中文诊断与系统打开入口。
- Java 21 JDK 和 31 项运行依赖以 URL、长度、SHA-256 锁定，提供无需 Maven 的离线构建及显式下载入口；jlink 裁剪运行时，保留 PNG 共享的字体、混合绘制与签章结构依赖。源文件清单指纹进入 Python 核心身份，组件带逐文件哈希和单独 SBOM；正式包从内嵌 Python 的 components 目录加载，源码开发使用 ignored runtime 组件，不搜索 PATH Java。
- 实验发现 OFDRW 会吞掉局部绘制异常，且缺少 cmap 字形时可能静默漏字；加入告警阻断及页面/模板文字字形预检查。Mac 非内嵌宋体/仿宋缺省时使用系统 Songti 映射，包内字体仍优先。ZIP 解包前校验路径、重复/链接/加密和容量，XML 拒绝 DTD/实体；Java 策略不授予网络或进程执行权限，只在独立临时副本、组件和字体范围读取，PNG 仅通过管道返回内存。
- 完整 converter 依赖与精简依赖、完整 JDK 与 jlink 运行时在两页合成样本上输出完全相同 PNG；排除 Batik、iText layout/font-asian、相关 XML 库、OFD writer 模块和未使用的 JSON 导出，显式保留 TIFF 解码；依赖从约 30.7 MiB 缩减至约 22.5 MiB。包含 Java 的组件约 75 MiB，最终精确测量与验证记录见 `docs/OFD_PREVIEW.md`。
- 自动验证覆盖 148 个不同的相关 Python/原生组件测试用例；首轮失败修正和最终依赖裁剪后，受影响的 45 项复验通过。16 项 Node 交互、69 项 Swift 回归及修改文件编译通过；完整/精简两页 PNG 逐字节一致，组件 ZIP 逐文件哈希复核通过。
- 本轮验证以本地组件、合成 OFD、Python/API/静态契约为范围；未将用户问题 OFD、真实默认配置、正式 Windows BAT、浏览器前台拉起、原生选择器或 Windows/macOS 完整打包成品记为通过。已发布 alpha.2 不含本功能，未修改 Release、Tag 或 Feed。

### 2026-09-08 发布 alpha.2 双平台预览并整理产品首页

- 所有者明确确认既有验收范围后，将注释 Tag `v0.3.0-alpha.2` 从 `eb425bc2690b374a61be67172e4acdbdc1e35c6e` 改指两端共同源码 `55a59870630198b7b8b055b85decfaa5bb360db6`；使用旧 Tag 对象身份的 force-with-lease，只更新该引用，不改写 main 或独立功能历史。
- GitHub Pre-release 已公开，Release ID `384542627`，8 项资源包括 Windows portable ZIP、Mac preview DMG、各自 SHA-256/receipt 及平台 Python SBOM；服务器报告的所有大小、SHA-256 与本地清单逐项一致。未重打程序、未开启安装 updater，也未发布 Feed；公开资源重新下载并逐项校验，8 项文件大小与 SHA-256 全部一致；网络中断后使用断点续传完成两个大文件复验。
- 发布说明保留 Windows 为用户验证后交付、本机静态验包的证据界限；Mac 25 项离线核验、实际默认空目录的启动/页面/monitor 验收，以及 62 项聚焦契约和 15 项文档契约均分别说明。隔离 HOME 自动烟测未通过、原生 picker/打印/完整浏览器与托盘交互/公证/updater 未覆盖，源归档器合成负向夹具误报仍存在；所有者确认只按这一预览范围发布，不将其改写成全量通过。
- 用户要求将 GitHub README 改为官网 hi. 风格的产品首页。新增居中标识/标题、真实版本和平台徽章、直接下载入口、简短场景介绍与官网已有 OCR/做账/税额换算后续方向；许可证保持 AGPL-3.0-or-later，不采用参考图中的 MIT、排名或下载量。使用指南移至 `docs/USER_GUIDE.md`，开发状态放入折叠区并保留架构导航。
- GitHub 实际 Markdown 渲染已检查，标题、徽章、截图和下载地址正常。首轮 Windows/macOS CI 仅因 README 工具链命令被缩写而失败，已在折叠开发区恢复两条完整入口，保留现有契约不放宽；产品代码不变。
- 三张截图来自当时运行的 alpha.2 默认空目录页面：汇总、成本分析、图标与皮肤。仅在独立截图浏览器内将本机路径替换为明确隐藏标记；未增加演示发票、修改金额、保存皮肤或改变当前 App 配置，原始 DOM 快照不进入仓库。截图来源、文件地图与发布真值在本轮同步。

### 2026-09-08 main 同步、Mac 候选与过期引用清理

- 本轮从 `codex/tauri2-alpha2-main-baseline@8d1c904` 收束到公开 `main`，本地 `main`、`origin/main` 和文档分支同步到 `55a59870630198b7b8b055b85decfaa5bb360db6`。税费计算器与 Mac 工作区的脏改动完整保存在 stash `df6451e0018c0de4db9734efecdae09da89a0eb0`，不作为公开源码、候选构建或 Release 输入；独立功能不因本轮同步改变。
- 已普通 `git branch -d` 删除六个只指向已合并历史的本地分支：`codex/tauri2-alpha2-main-baseline`、`codex/tauri2-alpha2-packaging`、`codex/tauri2-alpha2-postmerge-baseline`、`codex/tauri2-alpha2-public-preview-fix`、`codex/tauri2-alpha2-receipt-gate` 和 `codex/tauri2-unified-desktop`。唯一旧 Mac alpha baseline 的远端引用也已删除，并用 `git ls-remote --heads origin` 复核；`codex/desktop-latest`、`codex/desktop-main-docs`、图标/搜索/税费/更新恢复和 Dependabot 引用继续保留。旧的 dirty `codex/alpha2-dual-platform-release-prep` worktree 保留，本轮不执行 `git worktree prune`。
- 从精确 `main@55a59870630198b7b8b055b85decfaa5bb360db6` 构建 macOS arm64 alpha.2 preview：目录为 `dist/candidates/20260908-macos-main-55a5987/`，产物为 `InvoiceHub-v0.3.0-alpha.2-macos-arm64-preview.app`、`.dmg` 和 `build-receipt.json`；core build ID 为 `c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`，DMG 为 `109535179` bytes，SHA-256 为 `21715661a3bffa48e8afd0034a81eb975758280f3a6ed6d2356d982ec5607298`。该候选为 ad-hoc、未公证、host updater disabled，finalized receipt verifier 已通过。
- Mac 包内源码、官网、运行时、锁和签名的离线核验通过；隔离 HOME smoke 尚未通过；Mac smoke 未得到属于隔离 HOME 的 health；其后观察到构建身份正确且后台 ready 的实例，却使用真实 Application Support，不能计入隔离烟测通过，因此不能把候选描述为 public-preview 成品验收、签名/公证结果或 Release 资产。已收到与 Mac 同源的 Windows x64 portable 候选、SHA sidecar 和 build receipt：`source_commit=55a59870630198b7b8b055b85decfaa5bb360db6`、`core_build_id=c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`、ZIP 大小 `58040173` bytes、SHA-256 `f7c03a502d06d19faa61ee5f9ed859c4da3f57c6789f52014dec3fd4005a6ff3`，unsigned portable 且 `updater_enabled=false`。Windows 完整包由用户说明已验证后交付；本机独立静态验包和收据/实际 ZIP SHA-256 核对通过，不能把本机检查描述为 Windows 真机运行验收。
- 远端 `v0.3.0-alpha.2` Tag 仍为 `eb425bc`，不能与本轮 `55a5987` Mac 候选或其它 source snapshot 配对；本轮没有修改 Tag、GitHub Release、资产或更新 Feed。源码快照导出曾因 `tests/test_tauri_windows_portable.py` 中既有的合成负向 secret 值命中扫描而失败，没有绕过或放宽该扫描。后续双平台候选仍需以同一 source/core 身份闭合 ZIP、SHA-256、receipt 和 SBOM；构建入口使用现有 `scripts/dev/tauri_windows_portable.py` 的精确参数 `--root`、`--python`、`--runtime-dir`（指向含 `python/python.exe` 的父目录）、`--pnpm`、`--output-dir` 和 `--source-commit`，不把脚本部署或环境自动准备描述为已完成，也不复用旧 release-prep 输入。
- Mac 离线深验 25 项通过，源码/web/website 与构建提交逐字节一致，运行时及 App/DMG/receipt 签名与哈希闭合；未生成新包。检查器初次中文 Git 路径解析、构建后文档状态和上游既有 bytecode 分类误报已纠正；本轮检查生成的缓存已通过从只读 DMG 恢复 App 消除，并重新校验原 receipt 的 App SHA 与签名。旁置运行时哈希表 2621 条验证通过，报告不包含本机绝对路径。
- 用户确认已允许并打开软件后，主代理核实先前只剩临时宿主、8766 无监听，按精确身份收束该宿主并从保留的候选 App 正常重启。新包在实际 Application Support 默认空目录达到 health/background ready，原生首页实际渲染；普通首页和 `?no_skin=1` 各 8 项静态资源与当前源码字节一致，首页脚本为 `20260907-large-list-1`。monitor 从原 false 启动到 running/ready，再停止并恢复 false，后端保持 ready，新 App 保留供用户使用。原生 picker 因控制工具返回 noWindowsAvailable 未完成，不冒充通过。该当前配置证据不能替代失败的隔离 HOME smoke，先前仅据 spctl 拒绝断言无法启动的归因撤回。
- 本轮聚焦测试通过 62 项，覆盖 Mac 发布/烟测契约、Tauri foundation、图标、release identity 和 build manifest；另有 15 项文档契约通过，版本派生与 diff 检查通过。没有重复全仓 CI、Windows BAT、原生选择器、实体打印或真实 updater。最小无业务 App 证实同样的 LaunchServices `--env HOME=...` 传参能正确隔离；正式候选的 quarantine/Gatekeeper 首次打开与隔离运行仍须闭合，不能删除 quarantine 来制造通过。

### 2026-09-08 Desktop 主线合并检查

- 结果：最终功能提交 `f9eebca` 的 Windows/macOS push 与 PR CI、DCO 全部通过，审查意见修复并解决后，以普通 merge 合入 PR #20，主线产品基线为 `53544e3c96ba01906520637fae60cbc215b7808b`。本地主线同步，随后用纯文档分支同步 README、实现状态、分支记录及全部架构附录的统一基线；保留完整提交历史，不创建 Release/Feed。
- 文档收尾 PR #21 将当前状态表改为 main/PR 身份与实时 Git 查询，精确当次合并 SHA 仅作本节历史记录，避免下次主线演进后把固定值误当当前 HEAD；产品代码不变。
- 本地聚焦检查分别为 40 项前端契约、59 项缓存/单据相关回归和 38 项监控/索引/文档回归，源码 compileall 通过。CI 覆盖完整双平台 Python 回归、Windows 发布契约/PowerShell 解析和 macOS Swift 测试；本轮没有新增 BAT、原生选择器、实体打印或平台成品验收。审计脚本、远端 CI 日志和合成测试文件保留在 ignored 的 `runtime/desktop-merge-check/` 供回溯，无需复现后可清理；业务数据与本机配置未提交。
- 用户授权将 `codex/desktop-latest` 合入 `main`，从已推送的 `482dff6` 开始复核。首次远端 CI 在 Windows/macOS 各有两项失败，均为预览/打印前端契约仍引用旧首页脚本版本；分别已有 661/652 项 Python 测试通过。
- 将两处测试版本预期同步为页面已使用的 `20260907-large-list-1`，保留现有产品源码、缓存参数及已验 Desktop 包；继续运行聚焦回归与远端 CI，合并结果以本节后续记录为准。
- PR #20 的首轮 CI/DCO 已通过，但同提交 push 场景出现索引 phase=complete 后状态写入失败。为单据缓存发布增加仅针对 Windows 5/32/33 的有界重试，最多 20 次、累计等待 0.95 秒；持续拒绝仍抛错。新增最终 ready 写入共享冲突和持续/非 Windows 错误的确定性测试。该源码修复尚未进入此前的本地 ZIP，不将旧包宣称为本次精确成品。
- PR 自动审查发现 `MonitorBridge.stop()` 的前置状态读取被完整汇总锁阻塞，停止请求和 20 秒超时可能数分钟后才开始。核对后将状态读写放入独立短锁，写入仍按 sync -> status 顺序串行；回归覆盖长汇总锁未释放时读取与停止/超时可达。该修复同样仅在源码，不重打旧包。

### 2026-09-08 Desktop 推送重试与分支整理完成

- 从 `codex/desktop-latest@f35d314` 继续用户已授权的推送；GitHub 成功接收完整整合提交，分支已跟踪同名远端，`git ls-remote` 核对一致。稳定 `main` 仍为 `eb425bc`，未创建 PR、Release 或 Feed，也未上传本机配置、业务数据与 ZIP。
- 远端接收后，重新核对七个冗余本地引用均只指向稳定基线、没有独立提交或工作树绑定，使用 `git branch -d` 删除；有独立历史的开发线和构建快照继续保留，完成状态见 `docs/BRANCH_STATUS.md`。
- 本轮只涉及 Git 操作及文档同步，复核远端 SHA、提交范围、工作区分类和文档 diff，不重复已通过的产品测试、BAT 或成品验收；`runtime/desktop-push-check/` 保留供源码整合审计回溯，无需复现时可按精确目录清理。

### 2026-09-07 最新 Desktop 源码整合与分支整理

- 用户授权整理分支，并提交、推送最新版 Desktop 的全部更新。实时 fetch 后稳定 `origin/main` 仍为 `eb425bc`；从该基线建立 `codex/desktop-latest`，保留当前所有已验源码、资源、测试与文档，恢复同基线的本地 main 跟踪分支。
- 本次以最新 Desktop 构建快照核对内容，不重写其它功能分支或构建快照的历史。七个仅指向稳定基线、无独立提交的本地分支在整合推送成功后删除；其余来源线/构建快照保留并由 `docs/BRANCH_STATUS.md` 说明用途。
- 提交使用精确文件清单，排除本机配置、业务源文件/投影、缓存/日志、用户压缩档与发行 ZIP；代码/资源沿用最近已验 Desktop，文档与分支状态另行同步。验证结果和最终远端提交身份以本次实际 Git 检查及任务结果为准；不合并 main、不发布 Release/Feed、不创建 PR。
- 提交前发现文件地图未逐项列出图标及深色皮肤资源，官网测试的旧脚本分界标记已删除，导致误执行诊断控制器；补齐路径并给测试添加有效分界断言，不改变产品代码。敏感内容扫描命中两项验包负向测试的固定合成字符串，人工确认后按精确值记录例外。
- 整合提交 `5331187` 已完成，15 项文档契约、31 项前端/官网交互、compileall 和 diff 检查通过；产品代码/资源仍与已验 Desktop 快照一致。三次 GitHub HTTPS 推送遇到连接超时或连接重置，尚未推送成功，七个冗余本地引用依约保留至远端核对成功。本机审计与测试目录 `runtime/desktop-push-check/` 保留供后续推送复核，完成后可清理；没有新增全仓、BAT、原生选择器、macOS 或成品验收。

### 2026-09-07 大列表响应与单据断点缓存

- 从公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 转入 `codex/fix-large-list-responsiveness`，保留全部前序修复，未推送/合并。用户要求解决大目录持续处理中及模块卡顿，并支持保留进度和终止加载。
- 定位到保存目录在事件循环全目录解析、出库预览重复扫描、首页及单据选项全量 DOM。改为轻量目录校验、spawn 子进程索引、快速状态与独立进度轮询；保存/打开/导出同步工作卸载到线程池。预览只重新解析所选来源，仍检查目录/号码身份。
- 每个 TargetProfile/开具目录在 runtime `local_state/documents/index/<scope>/` 保留逐文件缓存。按路径、大小、mtime/ctime 和版本复用，停止/重启后可继续。SQLite WAL/NORMAL 避免逐文件 FULL 同步慢，断电可能丢失少量近期进度；不写源发票或业务投影。暂停不被普通刷新重启，旧 job_id 不得停止新任务；Windows 进度替换瞬时读失败保留最后有效状态。
- 首页每页 100 条，入/出库候选每页 100 项并可搜索号码/销售方，全选仍针对完整筛选结果，批量上限保留。单据新增进度、失败数、停止及继续。脚本和新增样式版本 `20260907-large-list-1`。
- 最小实验为 7,003 条合成记录和 7,003 个合成 XML，用于决定是否保留分页及独立进程。真实 Chromium 搜索/重置/翻页、加载中导航、停止/继续通过；测得首页 276ms、单据 233ms、停止 58ms、切设置 106ms，暖缓存复用 7,003 文件。仅代表本机合成样本。初轮发现同步写盘慢和进度读问题，修正后复测通过。
- 聚焦单据/缓存/HTTP/Node/文档契约及最终 Desktop 产物见本节后续补充；不作为全仓、macOS、正式 BAT、原生选择器或实体打印的新验收。
- 最终验证：63 项单据/索引/前端静态/文档测试、7 项搜索与 health API 测试、16 项 Node 交互、compileall 与 diff 检查通过。两款皮肤/默认无皮肤及恢复入口在 1440/390 宽度通过；窄屏加载工具和分页单独修正尺寸约束。
- 最终包为 `dist/candidates/20260907-large-list-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，SHA256 `e62a437deeff4b79e9565a2ec8ab1dfa1e443fe8e1436d3b8692e9d9f50bab07`；源码快照 `8e723cfd8fd1124a67de6648308c9f5f5f399ae4`，core build `1177db99a7f6dfdd3aab7e7a79a7027b8aa32f2eda5efcdb87b265285c243acf`。独立 verifier、Python runtime smoke/pip check、148 份包内源码/资源比对通过。
- 真实默认配置已切换新 EXE，health/build 身份及资源版本匹配；当前无皮肤及 `no_skin=1` 的真实 DOM 生效。实际保存目录 6,688 文件完成，errors=0；加载中停止约 69ms、切设置约 101ms，恢复复用 2,261 文件，后续重新核对复用全部 6,688。就绪页面最多 100 个业务选项，处理中指示已消失；监控保持原 false。仅输出聚合计数，未保存业务响应/DOM/截图。
- 旧 search-scope ZIP/hash/receipt 已撤下，旧解包保留回退。合成测试服务及浏览器均关闭；`runtime/large-list-check/` 保留合成复现、验证脚本与截图，`runtime/desktop-integrated-source/` 保留可追溯构建快照及既有依赖连接，可在无需复现/重打后另行清理。工作区 modified 95、deleted 0、untracked 33、ignored 27，73 条既有不可访问/缺失缓存目录警告；本机配置未暂存或上传。

### 2026-09-07 首页搜索范围与文件名误命中

- 用户反馈搜索供应商混入空销售方记录；在公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 的工作区保留全部前序修改，转入 `codex/fix-invoice-search-scope`。只读统计当前 API 命中字段，不保存业务响应，不修改真实发票、配置或投影，不推送。
- 当前搜索同时匹配文件名，而表格隐藏文件名，导致用户无法解释命中；没有发现不满足旧规则的记录。用户确认默认搜索销售方/发票号码，文件名单独选。首页增加搜索范围，保留显式全部范围；文件名参与搜索时展示转义文件名，无匹配显示筛选专用空态。
- API 新增 `search_scope=invoice|filename|all`，缺省 all 兼容旧调用者，非法枚举返回 422。关键字逐字段、不区分大小写匹配，不跨字段拼接。首页默认与重置为 invoice，刷新沿用已提交范围，迟到响应保留 generation 保护。脚本版本为 `20260907-search-scope-1`。
- 验证计划与阶段结果：7,003 条合成 API 记录覆盖范围、旧调用兼容、组合筛选、空结果、非法范围、统计与字段边界；Node 的 7,000 条迟到响应检查通过。pytest 默认临时目录权限错误与新基目录缺父目录在独立测试目录准备后解决，没有改系统权限。浏览器和最终包只使用合成数据进行界面验收，实际配置仅只读核对命中统计；最终结果后补。
- 最终检查：2 项搜索 API、17 项前端静态、15 项架构文档检查及 15 项 Node 交互通过，compileall/diff whitespace 通过；没有完整 pytest 或新增 Rust 行为回归。浏览器 101 条合成记录完成默认范围、文件名 60 条、文件名可见、无结果、重置 101 条，以及 1440×1000/390×844、两款皮肤和 `no_skin=1`。首次 7,001 行全量 DOM 的 Playwright 操作/快照超时，未宣称大列表渲染性能通过；大量数据搜索正确性由 API 和迟到响应回归覆盖，不能把本轮范围修复表述为完整性能优化。
- 新成品：`dist/candidates/20260907-search-scope-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，快照 `29395af61632d13ca573f0565f4ab94a122df2a7`，58,032,891 字节，SHA256 `bfa4cca521687276c58635295227287cbe5575cdad28b4be3f593f922181fd79`。独立 verifier、runtime smoke、pip check 通过，146 份包内源码/前端资源与快照及当前工作区逐字节核对；保留既有皮肤、图标、启动与监控修复。release 编译保留 3 项既有 updater dead-code warning，仍为 unsigned/updater-disabled。
- 当前运行：接替前旧 Desktop 已自行退出，未停止外来进程；新 EXE 使用原用户配置启动，health/build/package manifest 均有效，后台 ready、monitor 保持关闭。实际页面在移除初次加载的限定查询路由后提交原关键词，当前 1 条结果均满足 invoice 范围，新 JS 版本、控件计算尺寸、默认无皮肤与恢复入口已复核；本次当前数据与最初截图时不同，不将记录数变化全部归因于搜索修复。没有将真实业务响应、DOM 或截图保存到仓库。
- 清理与边界：源码烟测 8881 与两个 Playwright 专用会话已关闭，新 Desktop 保留供使用；旧 startup-diagnostics ZIP/hash/receipt 已删除，旧解包目录保留短期回退。`runtime/search-scope-check/` 保留合成夹具、脚本、截图和诊断，`runtime/desktop-integrated-source/` 复用既有目录绑定 `codex/search-scope-snapshot` 供复现；确认新包稳定后可按精确目录清理验收材料，构建目录继续遵守既有 junction 边界。没有推送、修改用户配置或手工重写业务投影，未覆盖本轮 BAT 启停、原生目录选择器、macOS、签名安装器或 updater。

### 2026-09-07 旧 ZIP 与中间候选授权清理盘点

- 用户明确授权盘点和清理；继续在 `codex/startup-conflict-diagnostics@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 工作，保留既有 modified/untracked/ignored 内容，主工作区 index 不变。当前仓库没有本地 `main` 引用，未创建或更改引用。
- 可读产物区找到 17 个产品 ZIP，其中 1 个为当前最终包，16 个为旧包。清理白名单共 18 个精确文件/目录目标，包含旧 ZIP、对应收据/哈希、两份旧解包目录和三个空候选目录，共 7,485 个文件、1,197,160,480 字节。完整本机清单位于 `runtime/startup-diagnostics-check/old-candidate-inventory.md`，保留供执行清理与核对，完成清理后可连同既有验收记录处理。
- 删除前核验目标均在 `dist` 内、无 reparse point、无已观察到的运行程序、不含当前最终包；当前 Desktop/backend 均运行于 startup-diagnostics-desktop-final，health 正常，最终 ZIP SHA256 与上轮收据一致。构建源码、依赖、用户配置、业务数据和专用 evidence 目录保留。
- 结果：自动审批仍在创建命令进程前拒绝删除，只有 `blocked by policy`，无具体原因；实际删除 0 项，未修改权限或改工具绕过。构建源码区内 `.windows-portable-staging` 另有文件系统拒绝枚举，未纳入候选数量或清理范围。上轮旧包磁盘残留限制仍有效。
- 验证边界：本轮为只读盘点与文档记录，没有产品代码变更、重打包、启停或推送，因此不重复运行产品回归；复核文件存在性、新包哈希、实际运行身份及 Git 状态。
- 后续执行：用户再次要求清理后，明确文件路径的非递归删除成功，已清理全部 16 个旧 ZIP 和 30 个配套哈希/收据，共 46 个文件、897,616,059 字节。批量递归目录删除与后续空目录删除仍被自动审批以 `blocked by policy` 拒绝，故旧解包和空目录暂留；没有改权限或删除解包内部文件。已复核可读候选区仅剩 startup-diagnostics-desktop-final 的产品 ZIP，新包 SHA256 不变，原 backend PID 仍 health ok。清单已同步实际状态，源码、配置、业务数据、构建源码和 evidence 保留；本轮不运行产品回归、不重打包、不推送。

### 2026-09-07 启动冲突诊断与桌面进程可见性

- 需求与开工：开发、测试与 Desktop 启动冲突必须向用户展示原因和占用者，不能只把错误写入隐藏终端；正式 Desktop 应能在任务管理器按产品名称定位。由 `codex/fix-source-bat-handshake@eb425bc` 转入同一公开 main 基线的 `codex/startup-conflict-diagnostics`，保留全部既有代码、皮肤、图标、握手修复和本机运行态，不推送。
- 假设与最小验证：GUI subsystem 下的 stderr 和跨目录单实例唤回会造成静默失败或打开错误环境。先追踪两个入口的失败/重复启动分支，再用一个隔离监听器验证冲突提示、PID/路径、日志和未知占用保护；正常启动、相同实例唤回及 monitor 保留/停止为相邻验证。新包必须来自包含本轮修改的当前工作区快照，不能复用旧 EXE。以可见提示、可定位进程、受影响自动检查与 Windows 成品验证通过为停止条件。
- 成品发现与修正：首个本轮候选在端口冲突时仍退出 101；实际 stderr 表明 Tauri 将 setup 推迟至事件循环并对返回的 `Err` panic，外层 build 错误分支无法捕获。改为 setup 内清理后直接提示并请求有序失败退出，新增守护测试和仅供自动化的 `--no-startup-dialog`。该首次候选不交付，最终 ZIP 必须重新编译并复验实际失败退出码。
- 实现结果：BAT 失败释放启动锁后保存独立诊断并显示原生前台弹窗，根 `检查启动环境.bat` 支持坏配置和无 Python 的只读检查；PS7/PS5.1 共用真实监听 PID 查询。Desktop 使用 Windows 原生监听表、进程路径和父进程线索，新增托盘诊断、按 EXE/runtime 隔离单实例，并通过 `run_return` 保留失败退出码。直接 CLI 在 AppState 初始化前检查端口，诊断子进程沿用 Host RPC 环境清理；服务自报字段仅作诊断，不授予 ownership，不杀未知进程或自动换端口。
- 最终包：`dist/candidates/20260907-startup-diagnostics-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，来源快照 `96d149b373926be1b354ce0913a22c767de6d9e1`，大小 `58032592` 字节，SHA256 `26ae9d64b3f05cb1fb1f27ff9af9a0f790e27312959941b0a1b81ec4d4bdf3a3`。独立 verifier、locked runtime 导入与 pip check 通过；146 份包内源码/资源与快照及当前工作区逐一核对，其中前端 62 份、官网 10 份，另核对 host 修改与图标输入。图标选择、最新前端和两款皮肤继续保留。最终验收记录属于构建后的文档更新，不改变包内输入。
- 自动检查：启动/Windows/Tauri/API 的首组 49 项通过；最终 CLI 凭据清理等 2 项、Tauri 生命周期 17 项和文档 15 项定点通过。Rust 原整组 79 项通过，新增诊断检查后 4 项诊断测试通过，最终 release 编译成功；既有 3 项 updater dead-code warning 保留。没有把重跑累计为新增用例，没有执行完整 pytest。
- 真机入口：PS7/强制 PS5.1 根 BAT 在隔离配置完成启动、重复启动、普通停止保留相同 ready monitor PID、stop-all 停止两者。真实默认配置根 BAT 在释放 Desktop 端口后成功启动，重复启动复用相同 backend PID，health/config/state 一致，再通过正式停止入口退出；此前“默认 BAT 尚未成功”缺口已补齐。
- 精确成品验收：固定 8766 上与源码冲突返回 1，诊断指出原 PID/config 且原服务继续存活，无 panic；默认弹窗的真实窗口标题为“InvoiceHub 启动与运行诊断”。隔离用户目录完成 desktop→browser→desktop、两模式重复启动、另一环境明确拒绝、keep_monitor 保留同一 ready PID、stop_monitor 停止并重启确认。验收脚本先修正 bridge start/status 字段口径，并等待后端 health 之后的桌面窗口初始化，正常用户操作时序下完整流程通过。立即在窗口构造期间通过外部 API 关闭会中断 setup 并返回诊断，不记为正常完成启动。
- 当前运行与未覆盖：最终 EXE 已恢复真实用户目录配置，health 为 ok、background_status=ready，窗口与进程名均为 InvoiceHub，PE ProductName/FileDescription 均为 InvoiceHub，原启动偏好为 desktop、monitor 保持关闭。前端本轮未再修改，以资源字节核对衔接前轮当前皮肤与 `no_skin=1` 的 DOM 验收。本轮没有任务管理器 GUI/窗口像素截图，没有重做浏览器前台与原生选择器操作；前轮相同前端资源的操作证据保留。未覆盖 macOS 新成品、签名安装器、updater、实际纸张打印和真实业务目录压力测试。
- 清理限制与保留：最终只交付 startup-diagnostics-desktop-final 新包；删除失败首候选目录及上一轮 ZIP/hash/receipt 的精确命令被自动审批以 `blocked by policy` 拒绝，未执行、未绕过，旧文件仍在磁盘且不再作为当前候选。`runtime/startup-diagnostics-check/` 保留诊断与验收脚本/日志，`runtime/desktop-integrated-source/` 的最终 snapshot-release 分支保留构建复现。后续具备清理条件时删除确切的旧候选和验收目录；构建目录须先按既有 junction 边界移除链接。前轮被拒绝的清理不重试。本机配置和 ignored 运行态不入提交，主工作区 index 未动，没有推送。

### 2026-09-07 源码 BAT 虚拟环境握手修复

- 需求与开工：继续处理源码 BAT 开发启动的独立握手故障；从公开 `origin/main@eb425bc` 的 `codex/desktop-current-package` 转入 `codex/fix-source-bat-handshake`，保留全部已有 modified/untracked/ignored 内容及 index，不推送。
- 实验计划：假设 Windows venv 转发器的真实 executable 为基础 Python，而命令行首项仍为 venv Python，导致严格进程校验误拒绝。使用一个隔离空目录配置通过根 BAT 启动，对照 CIM executable、命令行和 health；若仅该差异成立则修正可信解释器集合的匹配，仍严格绑定模块/root/config，错误路径和未知 Python 必须拒绝。停止条件为 PS7/PS5.1 正式启停、重复启动和相邻身份负向回归通过；不重打未包含 BAT 的 Tauri ZIP。
- 结果：隔离配置的旧实现复现 20 秒握手失败；修复后根 BAT 约 5 秒返回 ready。实际 CIM 确认 executable 为 venv 声明的基础 Python，argv 首项为 venv Python。`Test-IHProcessIdentity` 分别核验这两项均属于当前启动上下文，再保留原有精确模块/root/config 检查，启动复用与 PID 停止共用该修复。release 单候选和完整 CIM 矛盾拒绝语义保留。
- 验证：23 项 Windows 契约及 15 项架构文档检查通过，compileall 与 diff whitespace 检查通过；新增 PS7/PS5.1 的 venv 转发、直接 Python、release 单候选和外来执行文件/命令/模块/root/config/额外参数负向回归。真实根 BAT 在隔离配置完成显式 Development、自动源码识别、PS7/强制 PS5.1 启动及重复启动；首页与 health 成功、PID/state 与实际进程一致。普通停止保留相同 running/ready monitor PID，stop-all 后复核两个进程退出、monitor ready=false、server state=stopped；日志无启动异常。
- 当前运行与未覆盖：先前手动启动的源码实例已通过 keep_monitor API 退出；随后默认 8766 被用户目录配置的 Desktop 实例占用，根 BAT 正确报身份不匹配，未接管或结束该实例。真实默认配置的源码 BAT 成功启动仍未覆盖；没有单独的根 `.lnk` 可测，根 BAT 已覆盖。未复验浏览器前台、原生选择器、成品离线 BAT 或 macOS；没有修改前端或 Tauri 包内输入，因此保留上一轮最终 ZIP、皮肤和图标修复，不重打。
- 清理与限制：后台组合诊断命令被自动审批拒绝，仅返回 `blocked by policy`，改用直接根 BAT 与独立只读检查完成验证。本轮 `runtime/source-bat-handshake-check/` 已确认无存活测试进程、无 reparse point，但精确目录清理同样被自动审批拒绝，未绕过；配置、空目录产物与 pytest 临时目录暂留本地作故障复核，后续获允许后删除该精确目录即可，前序保留目录不在清理范围。本机配置保持本地、index 未动，没有提交或推送。

### 2026-09-07 最新工作区桌面包与内置皮肤适配

- 需求与基线：复核上一线程的双启动检查，保留页面关闭后残留 host 的故障修复；用户明确要求撤下不含最新工作区更新的旧候选 ZIP，适配两款原有皮肤后重新打包。由 `codex/default-ui-polish@eb425bc` 保留全部已有工作区修改，转入基于同一公开 `origin/main` 的 `codex/desktop-current-package`。不推送、不部署、不切换公开 Feed。
- 决策与方案：desktop/browser 原本共用一套后端，不新增启动器。保留 watcher 原子撤销 ownership 后退出 host 的修复；host 主动退出先撤销 ownership，避免重入。当前工作区复用既有 portable builder/verifier，补官网精确白名单；只构建 ZIP，不移入旧候选的应用源码或 Feed/handoff 流程。Windows GUI host 隐藏 child 控制台并将日志写到 owned runtime。
- 皮肤：Ink Pulse 升至 `1.4.0`、Animal Island 升至 `2.1.0`；新顶栏图标工具不位移、批量单据沿用皮肤配色、全局关闭弹窗不局限设置页。按用户最新要求保留 Ink Pulse 深色单据预览，Excel 导出和真实票面不受皮肤影响；动态模板内容版本、清单与测试同步。
- 最小验证计划：先验证当前源码两款皮肤的首页/设置/成本/单据、桌面与手机布局、关闭弹窗和恢复入口；仅以当前工作区干净快照组包，最终 ZIP 逐文件核对官网/新图标/JS/皮肤及修复，复验 desktop→browser→desktop、单实例、关闭与监控。若输入字节不一致或修复失效则停止交付。结果与未覆盖项在本节收尾追加。
- 包内实测补充：旧候选曾使用相同的设置脚本版本 URL，浏览器复用旧脚本后与最新全局关闭脚本重复声明变量，导致设置页停在初始化。当前模板及静态/API 契约改为独立的 `20260907-current-desktop-1`，以刷新资源缓存；据此重新生成候选，不能交付首次试打包。
- 用户指出图标选择缺失后的范围纠正：当前前端工作区基于公开 main，但图标选择、打印弹窗偏好、监控状态串行读取、同步进度与 Windows 启动恢复位于 `codex/fix-desktop-search-filter` 的公开后代。此前只搬入 watcher 修复不足以保留既有功能，第二次试打包同样不交付。本轮以共同基线三方合入这些运行代码和守护测试，冲突处保留最新官网、批量单据、全局关闭控制器与外观切换，不回退当前页面。
- 图标恢复：设置外观与皮肤页提供四款内置图标，新增 `website` 为默认白底 hi.，原 `orange/teal/violet` 选择继续有效。Python 与 Rust 共用枚举边界；先请求 owned host 更新窗口/托盘，再保存运行态；浏览器 favicon 同步。第四款从现有母版生成，原三款使用已存在公开分支中的资源。最终公共资源统一为 `20260907-desktop-integrated-2`、图标为 `20260907-app-icon-v3`。
- 最终产物：`dist/candidates/20260907-current-workspace-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，来源为当前工作区完整快照 `6c4821dfc817a0888702b2c3eb9e23062f8b6cc5`，大小 `58013606` 字节，SHA256 `fbd260fd789532680b01cf6d8f94e5cf16437812045ed5aa0a56075e9ba88fe3`。旧 desktop-surface 包及两份中间试包的 ZIP/hash/receipt 已删除；最终收据和 SHA 文件与新包同目录。独立 verifier、locked runtime 导入与 pip check 通过，146 份包内源码/资源逐一与快照及当前工作区核对一致，其中官网 10 份；host 的源码与图标输入同样核对。只在本地保留 unsigned、updater-disabled ZIP，没有推送、签名或发布 Feed。
- 自动检查：整合后的 93 项图标/Host RPC/前端/单据/生命周期检查通过；203 项 API/监控/发布/启动相邻回归中 1 项平台跳过，3 项旧基线断言或缺少烟测脚本在修正后定点复验通过；15 项架构文档检查通过。Rust 77 项测试通过（43 单元、6 lifecycle、12 monitor recovery、12 updater coordinator、4 Windows marker），Node 14 项交互检查、compileall、cargo fmt 与 diff whitespace 检查通过。Rust 保留 3 项既有 updater dead-code warning；没有执行完整 pytest 全库回归。
- 最终 ZIP 真机范围：隔离 LocalAppData、固定 8766，完成 desktop→browser→desktop；默认浏览器实际拉起，第二实例退出且 backend PID 不变；页面 keep_monitor 关闭后 host/backend 退出而 monitor 仍 running/ready，关闭浏览器标签不停止两者，stop_monitor 关闭后复核全部退出，随后可再次启动。原生目录选择弹窗打开/取消通过。图标在桌面模式切到青碧并持久化，浏览器模式可改罗兰紫，重启仍保留；四款 PNG、两款皮肤及 `no_skin=1` 在最终包实际读取并核验。真实默认源码配置、390×844 与桌面视口、合成 15 行单据、皮肤弹窗滚动锁和成本标签另有浏览器检查；Ink Pulse 深色预览保留，最终包用逐字节核对绑定同一资源。
- 运行与限制：所有新 ZIP 验收 host/backend/monitor 均已退出。当前 8766 恢复为当前仓库实际配置的源码服务，health ok、皮肤恢复原 website-dark、图标恢复默认 hi.，新 HTML 版本和计算样式已复核。根 BAT 的 Development 启动实际运行后仍在该本机虚拟环境身份握手失败，已结束失败进程；不把源码服务或 Tauri EXE 结果记成 BAT 成功。未覆盖 BAT 成品离线启动、macOS 新成品、签名/安装/updater、真实发票目录大规模处理、Excel/WPS 原生打开、纸张打印及原生任务栏图标像素截图；图标 native apply 的成功响应已覆盖。
- 保留与清理：自动审批拒绝删除中间 worktree 的依赖 junction，返回仅 `blocked by policy`，未继续删除或绕过。保留 `runtime/desktop-current-source/`、`runtime/desktop-current-source-r2/` 和各自 snapshot 分支；最终 `runtime/desktop-integrated-source/`（`codex/desktop-integrated-snapshot`）保留作构建复现，依赖 junction 指向共享缓存，后续清理必须先移除链接本身，不能递归进入目标。`runtime/desktop-review-20260907/` 为本轮脚本/测试/日志，`runtime/desktop-current-check/`、`runtime/desktop-current-check-r2/`、`runtime/desktop-final-check/` 为已停止的隔离解包验收，验收认可且清理获允许后按这些精确目录删除。此前旧线程目录及既有受限 pytest/pnpm 残留不在本轮清理范围。本机配置未纳入快照或上传，主工作区 index 保持原状。

### 2026-09-06 官网明暗外观与白底桌面图标

- 需求与开工：在 `codex/default-ui-polish` 延续前端任务，起点仍为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`；保留官网集成与前序批量单据修改。新增顶部品牌名旁太阳/月亮动效、官网深色外观、设置“关于”的 `hi.` 及第四款 desktop 默认图标；按最新补充，桌面图标最终采用官网纸白底。没有提交、推送、合并或重打发行包。
- 外观方案：White 仍为默认“无皮肤”，Dark 为 `website-dark` 只读内置 CSS，使用墨黑、荧光 `hi.` 与灰白文字，覆盖表格、输入、禁用态、提示及弹窗。沿用现有 skin enable/reset 与状态文件，不增加第二套偏好。先预加载 CSS（8 秒超时），再保存和切换，保持当前草稿、勾选与滚动；重复点击受保护，失败恢复控件并明确提示。服务器在 body 首绘前注入受校验的皮肤身份，避免暗色换页闪白；`no_skin=1` 固定浅色且不改写保存状态。单据白纸与源票面不反色，动效遵循减少动态效果偏好。
- 图标与相邻修正：第四款为 `#f8f9f5` 纸白、墨黑官网字体 `hi.` 和荧光折角；本地 Pillow 与已许可 OFL 字体确定性生成 1024 母版、512px 8-bit RGBA PNG、9 尺寸 ICO 与 ICNS。Tauri 默认清单显式绑定平台资源，现有构建 overlay 继承；已安装应用不会自动更新。真实浏览器修正了深色电源配色被通用按钮覆盖、关于标记句点换行、320px Ink Pulse 宽字形挤压按钮的问题；设置外观概览与列表同步更新。公共资源最终版本为 `20260906-appearance-3`，相关契约、素材许可、真值和架构文档同步。
- 自动验证：最终 50 项 Python 检查通过（前端/预览/打印静态契约 24、开发文档 15、图标 2、Tauri scaffold 1、皮肤及相邻页面 API 8），14 项 Node 交互检查通过，四个修改脚本语法及 compileall 通过。覆盖保存前 CSS 加载、双击、CSS/网络失败恢复、草稿保留、恢复入口、后端重建后状态、平台图标容器与字节一致性。首次夹具缺父目录和小尺寸抗锯齿的像素采样口径已修正后复验；没有把失败或重跑累计为新增通过项。
- 浏览器范围：实际配置的 8766 首页/设置和隔离合成数据的首页/成本/批量入库交接/15 行单据预览，在 1440×1000、390×844 与 320px 窄屏核验。White、Dark、两款原有内置皮肤和 `no_skin=1` 均检查；暗色页保持 4 条勾选与未保存目录，批量交接按 3 张票显示，预览白纸及无“人民币”前缀保留。手机关闭弹窗完整落在视口内，html/body 均锁定滚动；320px 宽字形加载完成后按钮无重叠。图标母版和 16/24/32/48/64/128px 对照图已目视检查。减少动态效果只做 CSS 契约，未切换操作系统偏好。
- 当前运行与未覆盖：当前 `http://127.0.0.1:8766/` 已恢复无皮肤默认浅色，health 为 ok/ready，config/runtime 属于当前仓库；最终 HTML、六项静态资源精确字节和 DOM 样式已复核。正式 BAT 未带 Development 因缺少随包 Python 失败，Development 停止报告已停止，原源码实例随后经 keep_monitor API 关闭；Development 启动仍在既有 identity/health handshake 失败，未放宽校验，当前为单独启动的源码服务，build/package manifest valid 均为 false。未覆盖完整 pytest、正式 BAT 成功启动、浏览器前台拉起、系统原生选择器、真实运行监控停机、桌面壳新构建、已安装程序图标、Windows/macOS 成品、Excel/WPS 原生打开或实际纸张打印。
- 临时材料与清理：隔离 8878 服务与启动进程已结束，端口不再监听；保留当前源码服务供试用。本轮 `runtime/ui-appearance-check/` 含图标对照 PNG、生成对照脚本、隔离日志及 `api/`、`api-final/`、`api-final-3/` 测试树；三个测试树经路径归属和无 reparse point 检查后，自动审批仍以 `blocked by policy` 拒绝递归删除，未绕过或重试，后续具备清理许可时只清理该确切检查目录。既有 `runtime/ui-documents-check/` 合成夹具与历史测试残留保持原清理边界，不能穿过其中的依赖 junction。本机配置没有修改或上传。

### 2026-09-05 官网标记、批量入库单与单据版式补充

- 需求与开工：在 `codex/default-ui-polish` 延续默认前端优化，基线为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`。新增官网粗体 `hi.`、首页勾选跳转批量开具入库单、预览/实际导出的对齐修正及移除大写金额“人民币”前缀；保留既有官网集成、未提交资产及本机配置，没有提交或推送。
- 批量流程：首页 `>>` 菜单新增入口，同标签页传递 30 分钟内的 `target_id + invoice_key + source_path` 草稿。只读核对最多 1000 条记录，同票家族逐张导出；已有文件显式跳过或导出副本，显示进度和逐票结果，可停止剩余。服务端在同一目标锁内复核身份与真实源文件到写出，目录切换、缺明细和冲突明确提示；网络结果未确认停止剩余且不自动重试。
- 版式与相邻修正：预览通过 colgroup 消费真实模板列宽，补足入库 11 行/出库 10 行；出库表头采用一致的三组合并布局。Excel 插行同步移动行高、合并及页尾，扩展打印范围并重复表头，长文本自动增加行高。大写与导出共用无前缀算法。浏览器发现重复源文件可能使单据明细重复累计，现仅折叠内容完全一致的完整来源组，保留同来源内重复明细，冲突阻断且不修改成本 CSV。预览拒绝迟到响应覆盖新选择，单张导出期间锁定当前选择。
- 默认界面：普通页面使用官网本地字体 `hi.`，保留此前吸顶、页面过渡、转圈与电源确认。手机批量表保持发票号单行及容器横向滚动。最终公共资源及修改的页面脚本版本为 `20260905-default-ui-7`，相关模板、HTTP/静态契约、架构导航与真值文档已同步。
- 自动验证：27 项单据测试、23 项前端/源预览/打印契约、15 项开发文档契约、11 项相邻页面/皮肤/关闭/勾选合计/官网 API 检查通过，共 76 项 Python 检查；11 项 Node 交互检查通过。包含单据 5/15 行、零/负数/分位、身份过期/越界/缺源文件、明细缺失/副本/冲突、已有文件保护、停止/未知结果和迟到预览。修改 JS 的语法检查、`compileall -q src tests` 和 `git diff --check` 通过；未把重跑累计为新增数量。
- 浏览器与实际产物：隔离合成数据验证 4 条勾选折叠成 3 张、1 张缺明细、逐张导出、停止后剩余可继续、5 行入库与 15 行出库预览。四份 5/15 行入/出库 XLSX 通过 openpyxl 结构检查及 artifact-tool 渲染人工检查。桌面 1440×1000 与手机 390×844、默认/Ink Pulse/Animal Island/`no_skin=1` 已检查；手机皮肤滚动后功能栏 top 与顶栏 bottom 同为 134px，无整页横向溢出。隔离服务使用 keep_monitor 关闭，关闭前 monitor 原本未运行。
- 当前运行与边界：真实默认配置的 `http://127.0.0.1:8766/` 已重新启动源码服务，health 为 ok/ready，config/runtime 指向当前仓库，当前无皮肤且发票源目录为空；HTML 新版本、CSS/JS 与本地文本一致、DOM 字体加载和恢复入口已核验，电源悬停为 `rgb(255, 180, 180)`。正式停止 BAT 报“已停止”但未接管旧源码进程，旧进程随后经现有关闭 API 结束；正式启动 BAT `-Development -NoBrowser` 再次在开发身份握手失败，不能记为正式入口通过，也没有放宽校验。当前 build/package manifest valid 均为 false。未覆盖 Excel/WPS 原生打开、纸张实打、浏览器前台拉起、原生目录选择器、真实运行监控关闭、桌面壳或 Windows/macOS 打包成品。
- 保留与收尾：新增 `runtime/ui-documents-check/` 的合成输入、四份渲染与导出、脚本及日志保留便于对照；`runtime/ui-documents-pytest-1/` 至 `-4/`、`ui-documents-api-final/`、`ui-documents-api-version/`、`ui-documents-api-version-2/`、`ui-documents-settings-final/`、`ui-documents-static-final/`、`ui-documents-contract-final/` 为 ignored 测试记录，复核结束后可按这些精确目录清理。此前自动审批以 `blocked by policy` 拒绝旧临时目录递归清理，本轮没有绕过或重试该操作；不要递归穿过 `ui-documents-check/node_modules` 的依赖 junction。当前源码服务及其 `runtime/ui-polish-server.*.log` 保留供使用，隔离测试进程已结束。本轮没有修改或上传本机运行配置。

### 2026-09-05 默认前端融入官网设计语言与交互优化

- 需求：按官网设计语言适度优化默认界面、布局与体验，改善页面过渡，为耗时操作增加转圈反馈，滚动时固定功能栏，并在顶部增加悬停浅红色的荧光电源入口。
- 开工：从公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 新建 `codex/default-ui-polish`；保留已有官网与随包集成修改、`website.rar` 和 ignored 本机配置/运行态。没有提交、推送、部署或重打成品。
- 界面：默认样式复用官网 `hi`、本地 Dela Gothic One 字体、荧光黄绿、墨黑与纸白，收敛面板边框并压缩成本统计布局。顶栏、发票/成本/单据/做账视图操作栏与设置分类使用实际顶栏高度定位；窄屏操作条保持可达。内置皮肤继续使用自身配色，`?no_skin=1` 保留默认恢复入口。
- 交互：页面沿用浏览器原生跳转和历史，移除人为延迟与先淡出到空白，支持跨文档过渡及减少动态效果；返回或取消导航时清理加载标记。公共 API 并发计数在 180ms 后显示转圈，最后一个响应正文读取结束或失败后收回，预览续租保持静默。真实处理中按钮保留尺寸、原图标节点和禁用态，普通禁用不转圈；成本刷新补齐失败提示与收尾。
- 关闭：新增固定本地 `system_controls.html` 片段和 `system-controls.js`，九个普通页面共用电源及设置关闭控制器；backend 与打印页不增加入口。电源始终确认，以保存偏好初始化选项；设置内记住后直接执行的语义保留。继续复用后端监控关闭复核、归属保护和失败重试，只有关闭响应明确被接受才结束 SSE 并显示“关闭中”。电源图标采用随包 Lucide SVG，附许可。
- 相邻修正：浏览器实测发现吸顶容器的 overflow 规则会覆盖预览弹窗的 body 滚动锁，现让预览、合计与关闭弹窗的 html/body 锁优先于全局和皮肤规则，并补充静态契约。相关架构入口、文件图、接口时序、注释原因、任务导航与真值文档已同步；本轮资源版本统一为 `20260905-default-ui-4`。
- 自动验证：23 项前端/源文件预览/打印静态契约、15 项开发文档契约、8 项页面/关闭/偏好/官网 API 检查、8 项 Node 交互检查通过；修改的四个 JS 语法检查和 `compileall src tests` 通过。Node 覆盖并发与 JSON 失败收尾、预览续租静默、按钮恢复、原生导航返回、确认/取消/重试、外部服务归属保护和 SSE 关闭；没有把重复运行累计为新增测试数。
- 浏览器与运行：真实默认配置下的 `http://127.0.0.1:8766/` 已加载本轮资源，health 指向当前仓库 config/runtime，`ok=true`、`background_status=ready`；当前默认为无皮肤，源发票目录为空。另以隔离的 120 份合成 XML 和 1.2 秒延迟检查慢请求转圈、完整列表、选中金额、单份 XML 原文预览及合计弹窗、成本标签互斥、1440×1000 与 390×844 布局、Ink Pulse/Animal Island 与恢复入口。手机皮肤成本操作栏实测 top 与顶栏 bottom 同为 134px；电源悬停计算色为 `rgb(255, 180, 180)`。合成实例经电源确认 `keep_monitor` 后页面正常显示“关闭中”，状态为 stopped、monitor_running=false，端口与进程已退出；该实例关闭前监控本就未运行。
- 验证边界：正式根 BAT `-Development -NoBrowser` 启动过后端，但开发身份握手失败，不能记录为 BAT 启动通过；未放宽启动检查。当前可用实例由源码后端独立启动，build/package manifest valid 均为 false。未覆盖浏览器前台拉起、原生选择器、真实运行中监控的浏览器关闭、桌面壳、正式停止 BAT 或 Windows/macOS 打包成品；合成量与人为延迟只验证 UI 反馈，不代表真实大目录识别吞吐。未手工修改真实默认配置。
- 保留与清理：`runtime/ui-polish-server.stdout.log`、`runtime/ui-polish-server.stderr.log` 随当前源码服务保留用于诊断，服务停用后可清理。自动审批以 `blocked by policy` 拒绝临时清理，未提供具体原因，因而保留 `runtime/ui-polish-check/`、`runtime/ui-polish-env/`、`runtime/ui-polish-final-api/`、`runtime/ui-polish-final-lock-tests/`、`runtime/ui-polish-pytest/`、`runtime/ui-polish-pytest-api/`、`runtime/ui-polish-check.py` 及两份 `ui-polish-check.*.log`；后续允许删除时只清理这些本轮临时路径。它们均 ignored，测试进程已退出，既有官网测试目录未清理。

### 2026-09-05 软件官网按钮连接本地随包资源

- 需求：用户确认官网为正式介绍资源，暂不部署公网服务器；软件「官方网站」按钮应直接打开已完成的网站。
- 开工：继续 `codex/invoicehub-official-website`，基线为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`；保留已有官网/文档修改、`p3/`、`website.rar` 及 ignored 配置和运行态，不提交、不推送、不重打成品。
- 方案与结果：About 返回固定 `/website/`，设置模板在接口加载前即可点击，同窗口进入官网；官网只在该 localhost 路径下显示「返回工作台」，回到「设置 → 关于」。保留主题及演示；官网版本为 `20260905-3`，设置脚本版本为 `20260905-local-website`。远端官网常量及更新 Feed 保持不变，下载链接仍只接受 HTTPS。
- 随包资源：新增 `website.py` 的 10 个资源白名单，联动 HTTP、Core Build ID、源码快照、Windows portable、Tauri development/alpha/public-preview 和 Swift 参考组包器；字体/图标附许可并登记第三方声明，维护文件不公开。资源跟随实际 Web bundle，未知路径返回 404，缺失或越界返回脱敏 503。
- 自动检查：15 项 Node 演示/导航/脚本运行检查、6 项标准库资源/复制/Build ID 检查通过，修改脚本语法和 `compileall src tests` 通过。使用隔离目录实际执行 alpha 资源复制，源码与暂存核心 Build ID 一致，不构建 App。当前环境缺 pytest/httpx2，按项目锁安装测试工具因 `httpcore2==2.9.1` 无可用分发失败；新增 API/build manifest/Tauri pytest 契约未通过完整 pytest 执行，不能记作全量回归。
- 运行检查：正式根 BAT 使用 `-Development -NoBrowser` 与隔离空目录配置启动了 backend，但启动器身份握手失败；该开发环境虚拟解释器转到共享基础 runtime，health 为 development 且 build/package manifest valid 均为 false。未改变握手或启动规则，不能记录为正式 BAT 启动通过。该实例实际 HTTP 验证首页/health、About、本地重定向、官网与 10 个资源逐字节一致、HEAD、5 个非公开路径拒绝、设置及 `?no_skin=1` 新版本 HTML；对实际服务脚本执行 Node VM，确认官网链接与返回路径。随后通过结构化 shutdown 关闭测试实例，状态为 stopped、monitor_running=false，复核端口关闭。
- 未覆盖：真实默认配置、用户当前启用皮肤、浏览器前台拉起/真实 DOM 点击/截图/画布像素、系统原生选择器、桌面壳交互、正式停止 BAT 与 Windows/macOS 新打包成品。已覆盖隔离默认无皮肤与 `?no_skin=1` 的 HTML/脚本；不等于浏览器视觉验收。旧浏览器访问拒绝仍有效，没有换浏览器或端口绕过。
- 清理：测试进程已退出；自动审批以 `blocked by policy` 拒绝删除新建的 `runtime/website-link-check/`，保留其中隔离配置、空目录投影与诊断日志，后续具备清理许可时只删除该目录。此前同样被拒的 `runtime/website-dom-check/` 未重试删除。两者均 ignored，不是官网或发行输入。
- 收尾：15 项既有文档断言与 2 项设置页静态契约通过标准库直接调用，`git diff --check` 通过。工作区分类为 modified 27 个已跟踪文件，deleted 0，untracked 为官网、新资源模块与测试、既有 `p3/` 和 `website.rar`，ignored 2000 项原有/本轮运行态与缓存保留，warning 为 28 条既有 pnpm 链接缺失。未修改真实默认配置或业务资料，未提交、推送或部署。

### 2026-09-05 官网功能展示与分层动效补充

- 需求：保持 Hi / hi 主题，补充源文件预览、批量打印、项目明细汇总与自适应单据，替换主打的一致性演示，并让首屏票纸与标签分别展开、归拢。
- 开工：继续在 `codex/invoicehub-official-website`（基于公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`）施工，保留已有官网和文档修改、`p3/`、用户新增的 `website.rar` 与 ignored 运行态。
- 方案与结果：演示改为发票/成本/单据/工具四视图，加入逐份预览与放大、PDF 家族去重及缺票整批阻断的打印动画、独立项目明细分组与 TSV、入/出库类型与动态行数。工具区据当前源码标注 OCR 配置入口、做账开发状态；未找到独立税率计算器实现，因此只提供明确标注的官网概念换算。
- 视觉：沿用现有色彩、字体与构图，把首屏拆为两张票纸和三个标签，只在插画命中区展开，移开归拢；键盘/触屏可切换。新增放大镜、打印出纸、明细归集和 OCR 扫描场景，保留暂停与减少动态效果；动画收敛、屏外和后台停止调度。资源统一更新为 `20260905-2`，48 个 Lucide 图标保留本地许可。
- 验证：13 项 Node 演示、资源与图层调度检查通过，覆盖同票去重、缺 PDF 整批阻断、项目/税率/规格/单位分组、税额分位守恒及无持续帧调度；第一次检查修正一处测试预期金额笔误。脚本语法检查通过。当前环境缺少 DOM 库，临时获取 `linkedom` 被网络权限拒绝，没有新增项目依赖。此前浏览器访问被拒，本轮请求重新授权尚未收到，因此未执行浏览器交互、桌面/手机截图或画布像素验收。
- 边界：全部数据为合成示例，打印不调用系统打印；不读取真实默认配置，不触碰业务 API、真实发票、应用皮肤 / `?no_skin=1`、正式 Windows BAT、浏览器前台拉起、原生选择器、桌面壳或打包产物，也未将这些路径纳入验收。不提交、不推送、不部署、不改变 Release 或 Feed。
- 相邻检查：补齐触屏 `pointerleave` 先于 click 的处理，连续两次轻点可展开再归拢，新增对应 VM 断言；15 项既有文档断言、HTML 标签配对与 ID 唯一性检查通过。文档检查直接调用标准库函数，非完整 pytest 回归。
- 收尾：`git diff --check` 通过；modified 为 10 份官网相关文档，deleted 无，untracked 为官网、既有 `p3/` 和用户 `website.rar`，ignored 配置/业务产物/依赖/运行态保留，warning 为 28 条既有 pnpm 依赖链接缺失。自动审批以 `blocked by policy` 拒绝递归清理新建的 `runtime/website-dom-check/`，因此保留该目录下的 npm 检查日志与时间标记；它不是官网依赖，后续具备清理许可时只删除该检查目录。本轮没有仍运行的预览或检查进程。

### 2026-09-05 InvoiceHub 独立品牌官网

- 需求：以 `I / H` 组成的 `Hi / hi` 建立开源项目的产品官网，以产品经理与设计视角介绍已有能力。
- 开工：从实时核对的公开 `origin/main`（`eb425bc2690b374a61be67172e4acdbdc1e35c6e`）建立 `codex/invoicehub-official-website`；原分支与已有测试残留、ignored 运行态保留。
- 方案：新增 `website/` 自包含静态站点，采用荧光黄绿、墨黑、纸白和原创纸票画布；使用包内字体与精选 Lucide 图标并附许可。产品信息只陈述本地识别、汇总、成本参考、核对和独立监控的公开能力，安装包与正式入账保持既有边界。
- 结果：实现响应式导航、三视图演示、筛选与排序、同票去重合计、金额缺失提示、行级加价率、合成 CSV 导出、预览与开始使用弹窗、FAQ、动画暂停与减少动态效果。演示完全使用内存合成数据，不连接业务 API、不读取配置，不写源发票或投影。
- 验证：8 项 Node 演示/资源/图标/文件地图契约通过，修改脚本通过语法检查，`git diff --check` 通过。当前 Python 环境缺少 pytest，因此用标准库直接调用 `tests/test_development_documentation.py` 的 15 个断言函数，全部通过；这不是完整 pytest 回归。浏览器访问本机文件 URL 与本地预览未获许可，未执行实际 DOM 点击、桌面/手机截图或画布像素验收。当前结果不是软件真实默认配置、正式 Windows BAT、浏览器前台拉起、原生选择器、皮肤 / `?no_skin=1` 或打包产物的验收。本次不部署、不推送、不重打应用；临时官网预览进程已停止并清理其两份日志。

- 2026-08-28 `alpha.2` receipt gate 发布基线同步：receipt finalization 门禁已合入公开 `main`，并已通过聚焦门禁及 PR CI；旧的远端 `v0.3.0-alpha.2` Tag 仍指向此前基线，不能用作构建或发布输入。最终仍须把干净 `main` 经新的明确授权重建为同名 Tag，再构建 DMG、完成 Finder/Gatekeeper 与平台成品验收；没有 GitHub Release、资产、Feed、SignPath 请求或最终平台烟测。

- 2026-08-26 macOS public-preview receipt finalization 门禁：组包器先写入唯一允许的 pending receipt，并只在内部 verifier 调用中显式接受它；首次验证成功后才写入与实际 DMG SHA-256 精确绑定的 finalized record，再以默认 verifier 复验。默认验证会拒绝未完成、字段扩展、篡改或与 DMG 不一致的 finalizer；verifier 失败或 120 秒超时会同时报告 stdout/stderr。远端 `v0.3.0-alpha.2` Tag 已按授权重置到当时公开 `main`，但它早于本门禁；只有从包含该门禁的最终干净 `main` 经新授权重建 Tag 后才能构建。没有 GitHub Release、资产、Feed、SignPath 请求或最终平台烟测。

- 2026-08-26 Windows public-preview 交付证据闭环：受控配置新增安装器 SHA-256 sidecar 名称；PowerShell 组包器和 GitHub-hosted SignPath 工作流均在签名后写入安装器、SHA-256 与 receipt。工作流会复核单次 NSIS marker、内层 EXE 字节一致性及应用/外层安装器的 Authenticode 状态，随后只上传三项 Actions artifact，不修改 GitHub Release。新增 Windows 真机操作手册，固定 Tag/变量/两次 SignPath/三项 artifact/签名与卸载烟测顺序；未触发 SignPath 或任何 Windows 安装、启动、卸载验收。

- 2026-08-26 `alpha.2` public-preview 合并后基线同步：macOS public-preview 的 package manifest、LaunchServices/quarantine 烟测与 SSE 结构化关闭修复已经进入公开 `main`。当时的同名 Tag 已按授权重置到该基线；后续 receipt finalization 门禁已在候选树实现，最终干净 `main` 仍须经新授权重建 Tag，不能把中间 Tag 用作任何构建或 Release 输入。GitHub Release、资产、Feed、SignPath 请求和平台成品烟测仍未执行。

- 2026-08-26 macOS public-preview 启动与结构化关闭修复：新增独立的 DMG 成品烟测入口，先独立复核 App/DMG/receipt，再挂载、复制、ad-hoc 验签并为临时 App 写入 quarantine；Tauri App 只允许由 LaunchServices 的 `open -n -W -g` 启动，并仅注入隔离 `HOME`，不传 development state override。烟测只访问固定 health/monitor/shutdown allowlist，覆盖 monitor start/ready/stop 与 `stop_monitor` 结构化退出。`GET /api/v1/events/stream` 现会在已接受结构化关闭后结束生成器，避免 WKWebView 的 EventSource 阻止 Uvicorn 正常退出。聚焦 public-preview/release/recovery 测试共 22 项通过；此前候选仅用于定位该关闭缺陷，最终干净 Tag 的 DMG、真实 Finder/Gatekeeper 交互和 Release 资产仍待执行。

- 2026-08-25 macOS public-preview 组装门禁修复：共享 staging 器对 internal-alpha 保留 `dmg` 包型缺省值，public-preview 显式覆盖为 `preview-dmg`，使其独立 package ID 能通过 fail-closed package manifest 校验。新增回归契约，此修复尚未获新 Tag 或平台成品证据。

- 2026-08-25 `v0.3.0-alpha.2` 双平台公开预览组装基础：同步产品版本和现有构建身份；新增 macOS arm64 public-preview DMG 的独立 staging、release profile、ad-hoc receipt/verifier，以及 Windows x64 current-user NSIS/SignPath workflow、WebView2 SHA-256 锁和双层签名顺序。最初创建的 `v0.3.0-alpha.2` Tag 没有 GitHub Release 或资产，且因后续修复只能由新的干净 Tag 取代；updater、Feed 与平台成品烟测仍未执行；Windows 卸载器在本 alpha 中明确未签名。

- 2026-08-24 Tauri L10-E 非安装恢复烟测边界与运行证据：普通 development `stage/build`
  与 internal-alpha 继续生成 `updater.enabled=false`；新增显式
  `stage-recovery/build-recovery`，development manifest 只有在 endpoint 等于固定、
  不可达的 HTTPS loopback 地址且 public key 等于无验签能力的 sentinel 时才允许
  激活 L10-D startup restore，任一额外字段、任意 endpoint 或 key 都拒绝。新增隔离
  runner，使用临时 HOME/state/runtime/watch、`auto_check_updates=false` 和预置 marker，
  其 localhost 请求面只允许 health、monitor status 与 monitor stop，不调用
  `update_check/update_install`。运行预检先修复 runner 将 Tauri display name 误当作
  `CFBundleExecutable` 的问题，并把 App plist、host manifest 与 product version
  绑定；第一次启动随后在 backend/monitor 之前因缺省 `plugins.updater` 被 Tauri
  反序列化为 `null` 而 fail closed，development overlay 现只提供空 `pubkey` 配置
  对象，不携带 endpoint 或验签权限。锁定 Rust 1.85/Tauri CLI 2.11.4 离线重建后，
  macOS arm64 隔离样本以 build ID
  `8e40363fa673017e993727cf3f5dec347b24927c5ce1a0a4b945601737621873`
  通过：owned backend/monitor 身份与路径匹配，monitor 达到 `running && ready`，marker
  被删除，显式 stop 成功，runner 报告 `update_requests=0`；样本 PID、固定端口和临时
  目录均已清理。该结果只证明 authenticated startup restore，不授权或覆盖 Feed、
  候选、下载、验签、安装、重启、DMG/NSIS、签名、公证或发布。
- 2026-08-24 旧工作区功能与故障回溯治理：新增脱敏查询索引，按功能类别、
  常见症状、不变量和当前源码/测试入口提供回溯路线；原始非公开 Changelog 及其
  附件、路径、局部摘录和验证记录继续只留在私有归档外部，不复制、链接、暂存或
  提交到公开工作树、测试夹具或发布输入。
- 2026-08-24 文档治理：将本文件既有记录统一译为中文，并把后续
  `CHANGELOG.md` 使用中文的规则写入工程治理。新增或修改跨功能流程时，
  代码必须在交接点说明上游输入、下游消费者、执行顺序或不变量，以及失败
  边界；本次不改变产品行为。
- 2026-08-24 Tauri L10-D 认证恢复/重启运行时协调器：在既有的后端私有桌面
  所有权 secret 下，以 HMAC-SHA256 将每一条 Rust monitor 恢复请求及精确的
  Python 响应绑定到一个全新的 challenge；拒绝不完整、被篡改、非空 body 或
  重放的认证请求，且不改变普通 bridge 调用。以域分隔的 artifact identity
  保留完整的 host-owned updater candidate；只有 owned startup gate 已释放且
  `BackendHost` 已被管理后才激活 updater runtime，并在接受 updater 操作前
  恢复任何平台恢复 marker。`update_install` 现在先保留一个全新的 candidate，
  在 execute/cancel latch 后启动私有 worker，写入并 flush 精确的成功响应，
  然后才执行受锁保护的 Tauri 下载/签名校验 -> 暂停 monitor -> 安装 -> 重启
  协调器。writer/spawn/latch 丢失会显式进入 `CommitLost`，不产生 update 或
  monitor 副作用；startup restore 或 transaction 失败会保留后端供诊断，并
  阻断后续 updater 工作。Windows 在启动安装器前通过 `on_before_exit` 确认受管
  backend 已终止；macOS 先停止 backend、标记已准备重启，再请求 restart，私有
  commit 进行期间阻断普通 Quit。本项只有源码与契约集成：未运行或获授权运行
  产品进程、真实 Feed/update、monitor、安装器、重启、产物构建、签名、发布或
  平台运行烟测。
- 2026-08-23 Tauri L10-C 基础切片：新增固定 loopback 的
  `PythonMonitorRecoveryBridge`、纯 verified-artifact update coordinator，
  以及共享既有 child、ownership 和 lifecycle handle 的可 clone
  `BackendLifecycleAuthority`。新增 Windows marker-store 源码契约：使用相对
  于已打开目录的 handle 并拒绝 reparse point，同时保留 Unix 的
  descriptor-pinned marker primitive。这些仅为源码层接缝：遵循目录锁协议的
  Unix store 会串行化整个 load/publish/clear 操作，在持有锁时重读过期 clear，
  并在最终 publish/clear link 操作后持久同步目录元数据（绕过该协议的直接编辑
  不在保证范围内）。最小 `x86_64-pc-windows-msvc` 临时 crate 交叉编译通过；
  没有 Windows runtime 证据，完整 Tauri Windows target check 仍被需要
  `assert.h` 的 `ring` 阻断。所有切片都未接入 Host RPC、updater、startup
  restore 或真实 monitor；updater 仍会消费 candidate 并 fail closed。聚焦验证
  通过 56 项 Rust 检查（backend authority 14、bridge 9、coordinator unit 2 加
  contract 12、recovery 17、Windows host static 1、strict OpenAPI 1）和 42 项
  Python contract（lifecycle 13、development documentation 12、foundation 17）。
  strict OpenAPI handshake 要求 `GET /api/v1/bridge/status`、
  `POST /api/v1/bridge/stop` 和 `POST /api/v1/bridge/start`；缺失或方法错误的
  `/bridge/start` 会被拒绝。未来 updater 接线必须先公开保留 candidate，再进行
  私有 fixed-enum commit，因为锁定的 updater `2.10.1` 会在 Windows
  `Update::install()` 时退出进程，而 macOS 仍需 `request_restart`；commit loss
  与恢复失败必须保持为显式失败状态。
- 2026-08-23 L10-C bridge 边界：固定 loopback monitor adapter 没有请求级
  ownership authentication，不能作为 ownership proof。实际接线前，每个
  request/response 都必须绑定后端私有的 fresh challenge/HMAC 或等价认证 header，
  在请求前后保留 lifecycle revalidation，且绝不能把 bearer secret 发送给候选
  固定端口。
- 2026-08-20 Tauri L10-R monitor 恢复基础：为未来 host-owned monitor 恢复
  协调器新增纯源码、fail-closed 的 transaction。它捕获已释放的 owned
  lifecycle lease（generation、phase、health、owned 和 process PID 及 state
  scope），拒绝既有恢复义务或未 ready 的 monitor，且只在随后观察到 owned
  `running && ready` 后清除 marker。Unix marker 持久化使用固定目录 descriptor
  的 no-follow `openat`/atomic no-clobber `linkat`/`unlinkat`；非 Unix 构建明确
  返回 unavailable。该 transaction 不包含 Host RPC、真实 monitor、下载器、
  安装器、重启、bundle、签名或 release 集成，`update_install` 仍消费 candidate
  并 fail closed。
- 2026-08-19 Tauri internal-alpha 组装：新增有边界的 macOS arm64
  `internal-alpha` profile、clean-snapshot staging、内嵌 Python 3.14.6 runtime
  输入、manifest/launcher hash binding、receipt 生成与独立 fail-closed verifier。
  已安装 pnpm wrapper 不可用时，builder 可使用直接锁定的 Tauri CLI path。本项
  仅用于本地验证：未启用 Release、Feed、updater installation、Developer ID、
  notarization 或 GitHub mutation。
- 2026-08-19 Tauri internal-alpha 证据：从 clean commit
  `1892a52bf5eba4ae3b24720fbc32899a4e6003a0` 构建一个 arm64 `.app` 和同源码
  ad-hoc `.dmg`；独立 App/DMG/receipt verifier 通过，另一次临时 HOME launch
  smoke 在固定端口达到 `ready`，package/build/source identity 相符。产物仍仅
  用于内部，不形成 Release、Feed、updater installation、签名、notarization 或
  最终用户安装的声明。
- 2026-08-19 Tauri internal-alpha runtime gate：只允许解析后 target 仍位于
  embedded runtime 内的相对 runtime symlink；staging copy 仍会解引用它们，最终
  artifact verifier 拒绝 symlink。这允许使用固定的 python-build-standalone
  launcher link，同时不放宽 bundle containment。
- 2026-08-19 Tauri internal-alpha receipt 修复：将已签名 `.app` 表示为确定性的
  directory-tree digest 与文件总字节数，而非把 bundle 目录当作普通文件；DMG
  记录仍为普通文件 hash。
- 2026-08-19 Tauri internal-alpha bundle 映射：将已验证的 embedded Python
  runtime 纳入 `Contents/Resources/python`；verifier 现在检查与 App 相同的
  launcher-visible path。
- 2026-08-19 Tauri internal-alpha receipt 隐私：receipt 保存 artifact name 而非
  本机绝对 build path；hash、source identity 和 verification field 不变。
- 2026-08-18 Tauri setup cleanup 确认：在 `BackendHost::launch` 后，tray 或选定
  desktop/browser surface 的初始化可能在正常 `ExitRequested` handler 建立前失败。
  setup 会让 child 保持本地状态直到所有可失败初始化成功；失败时重试既有结构化
  `keep_monitor` shutdown，并以显式 kill-and-wait fallback 持续到确认 owned child
  已终止；child lock 或 `try_wait` error 视为未确认并进入 forced termination，
  而不是 graceful exit。仅在此后才返回原始 surface error。聚焦 lifecycle
  contract 禁止把 cleanup error 返回给 `Drop`；这不会启用 update installation 或
  形成 release 证据。
- 2026-08-17 Tauri Windows CI fixture 修复：development-app contract 不再假定
  POSIX execute-mode bit 在 Windows 上控制 `os.access(..., X_OK)`。其不可执行
  virtual-environment sample 现在只拒绝精确的 executable-access probe，从而在
  每个 hosted platform 确定性触发现有 fail-closed production branch。production
  staging、validation、packaging 与 runtime behavior 不变；聚焦及 hosted
  verification 已记录在 Tauri execution plan。
- 2026-08-17 Tauri exit/update timeout 修复：macOS application menu 现在使用
  带 Cmd-Q 的自定义 Quit item，它与 tray Quit 都请求同一 `app.exit(0)` path。
  每个收到的 `ExitRequested` 都先执行结构化 `keep_monitor` backend shutdown；
  menu 不使用可能绕过该 event 的 native predefined Quit selector。external
  termination path 不被宣称为有序 shutdown mechanism。API failure 或 timeout
  会显式 kill 并等待 owned child；无法确认终止时阻止 host exit，而非依赖 process
  `Drop`。host updater metadata check 现在使用五秒总 timeout，避免 stalled Feed
  永久占用 updater mutex 或 Host RPC connection capacity。聚焦验证已记录在
  Tauri execution plan。一个 clean-commit macOS development sample 向前台 app
  发送真实 Cmd-Q，观察到 shutdown POST、stopped state、host/backend exit、固定
  端口释放和 PID cleanup。打开的 SSE connection 使 backend 写入 `stopped` 后仍
  需要显式 kill-and-wait fallback；这只证明受支持的 custom-menu/Cmd-Q path，
  不启用 update installation，也不把结论扩大到 external termination。
- 2026-08-17 Tauri P1 transport/container 修复：私有 Python Host RPC request
  现在使用显式 no-proxy loopback transport，因此配置的 `HTTP_PROXY` 无法接收
  bearer token。development state-root containment 现在将完整 macOS `.app`
  bundle，而非仅 `Contents/Resources`，视为 protected；`Contents` sibling 的
  state path 也会被拒绝。聚焦 Host RPC 与 Rust lifecycle contract 通过；这仍是
  源码层安全修复，不是 product-process、updater、installer 或 platform-release
  结果。
- 2026-08-17 Tauri P1 lifecycle/provenance 修复：`update_install` 当时会刻意
  消费所有 candidate 并返回 unavailable，直到具备完整 recovery/relaunch
  coordinator，以避免更新进行到一半就下载、停止 monitor、安装或重启。tray Quit
  现在请求既有结构化 `keep_monitor` shutdown 并等待 owned backend；其 direct
  child kill 原本是有界 timeout/error fallback，现已由上述后续修复用于每次
  application exit。移除了 dormant monitor-stop/install response fragment，
  以免 Rust host 暗示可执行 coordinator。development assembly 将 dirty
  allowlisted input 记录为 `<HEAD>+dirty`，development state 现在要求显式、
  已存在且与 bundle 双向不相交的 canonical root。锁定的 Rust formatting、16 项
  library test、6 项 lifecycle integration test、desktop binary check、version
  sync、聚焦 Python contract、`compileall` 与 diff whitespace check 均通过，且
  Rust 无 warning。脱敏 candidate scan 仅发现 ignored dependency build metadata
  和已记录的 deterministic ledger-fixture false-positive 类别；tracked/non-ignored
  source 不含本机 identity、credential、business output、runtime 或 release
  artifact。这不是 product-process、installer、signed-update、native-panel 或
  platform release-smoke 结果。
- 对齐 public-history execution record 与已准备的 sanitized-root Tauri
  development line，同时保留 no-Tag/no-Release/no-Pages 边界。
- 2026-08-17 Tauri development application L8-S/L9：新增确定性的
  development-only assembler，用其 staging allowlisted core、schema-3 host
  manifest 和显式 virtual-environment launcher，并将 raw manifest 和 launcher 的
  SHA-256 值绑定进 host build。macOS arm64 development `InvoiceHub.app` 曾构建
  一次，并以 isolated development state root 进行一次 smoke test：owned backend
  精确绑定 `127.0.0.1:8766`，health 与 background startup 达到 ready，homepage
  和 static asset 已加载，`desktop_available=true` 且为默认 desktop surface。随后
  一次 external AppleScript quit 释放 process、port 和 PID，却绕过 structured
  shutdown 并留下 stale server state，因此撤回该不受支持 exit 子结论。P1-Q 随后
  以 clean commit `399b20c` 重建并使用真实 Cmd-Q，只建立受支持的 structured-exit
  path。该 app 是本地 ignored development artifact，未触碰真实用户的
  Application Support state。development profile 禁用 updater delegation，拒绝
  release/relative state-root override。最初的 macOS tray initialization failure
  可追溯到 16-bit RGBA icon；图标现为 8-bit RGBA，且 IHDR-focused regression
  保护该机制。这不是 DMG、NSIS、Developer ID、notarization、Feed、Release、
  真实 updater、native-panel、browser/tray 或 Windows smoke 证据。
- 2026-08-16 Tauri release-input L7：完成只读 readiness audit。source 刻意
  禁用 Tauri bundling，且没有用于 schema-2 desktop host manifest 及其 compile-time
  SHA-256 的确定性 generator 或 stager；既有 Windows portable 和 legacy
  Swift/macOS packager 不能提供 Tauri NSIS 或 DMG/update-archive input。audit 还
  发现当前 static manifest schema 无法安全保存 per-user config/runtime path。
  release assembly 保持阻断；L8 在实现前被记录，以便在任何 generator 出现前定义
  dynamic state-layout 与 manifest-path contract。没有创建 product process、bundle、
  signing、notarization、upload、publication 或 Feed。
- 2026-08-16 Tauri updater L6-RRRRR：让存在竞争的 hosted update check 在
  `append_event` 前返回其只读 busy result，因此不会阻塞在 SQLite event write。
  增加该 blocked-event path 和 private RPC exception 后释放 install lock 的代表性
  contract。目标 isolated Python contract 在将 deprecation 视为 error 时通过 45 项，
  就 event-write 和 exception-release 范围取代 L6-RRRR 的 44 项结果。未运行 Rust、
  product process、update、package、signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRRR：修正 hosted-Tauri update check 的范围。当
  Tauri marker 和 private Host RPC 都配置时，API、settings 和 background check
  使用严格 fresh-Feed/candidate preflight；只有 non-Tauri/non-host check 保留普通
  cache/ETag path。install lock contention 现在立即失败，不消费 approval 也不发送
  第二次 Host RPC。目标 isolated Python contract 在将 deprecation 视为 error 时
  通过 44 项，取代 L6-RRR 的 42 项结果，但其 event-write 和 exception-release
  范围又已被 L6-RRRRR 取代。未运行 Rust、product process、update、package、
  signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRR（已取代）：将普通 update check 保持在 host
  lifecycle lock 之外；存在竞争的 Tauri host approval 立即返回非持久 busy result，
  不进行 metadata/candidate 工作，也不清除既有 approval。已获得锁的 host path
  仍通过显式 `try/finally` release 串行化 strict metadata、candidate 与 one-shot
  install。该项被 L6-RRRR 取代，因为其 42 项结果未建立更严格的 hosted-Tauri
  public-check 范围；未运行 Rust、product process、update、package、signing 或
  platform smoke test。
- 2026-08-16 Tauri updater L6-RR：让 strict host-approval Feed request 显式发送
  `Cache-Control: no-cache`，同时继续省略 ETag 并拒绝 `304`；non-host public
  update check 保留原有 cache/ETag header。明确并锁定独立的四项 picker 与两项
  updater Host RPC command surface。目标 isolated Python contract 在将 deprecation
  视为 error 时通过 40 项；未运行 Rust、product process、update、package、signing
  或 platform smoke test。
- 2026-08-16 Tauri updater L6-R：要求 host-install approval path 重新验证新鲜的
  allowlisted Feed `200` body，不使用 cache、ETag 或 `304` reuse，同时保持 non-host
  public check caching。在五分钟后由 bounded listener loop 主动清扫 one-shot host
  candidate，并以 generation-check 删除，使旧 expiry sweep 不能清除新 slot。修正
  当前文档，只描述 token 从 host 交给其直接启动的 Python backend，随后在 startup
  capture 并清理 descendant-environment。isolated Python selection 通过 31 项，
  Rust 1.85 offline contract 通过 13 项 library 加 5 项 lifecycle test；未运行
  product process、`8766` bind、update/download、package、signing 或 platform
  smoke test。
- 2026-08-16 Tauri updater L6：将 raw desktop bundle manifest 绑定到未来
  staged-manifest packager 注入的 compile-time SHA-256，使 source checkout 以
  exit-78 fail-closed。新增 host-delegated `update_check` 和 one-shot
  `update_install` command，带有五分钟 candidate bound、allowlisted
  Feed/version-match approval gate、empty-body HTTP install API 与脱敏的 503
  failure。installation 现具有固定顺序：download 加 Minisign verification、
  monitor stop 与 independent recheck，然后 install/restart。controlled Rust
  contract 与 isolated FastAPI TestClient contract 通过；未运行 product process、
  real update、bundle、signing 或 platform smoke。
- 2026-08-16 Tauri 2 lifecycle 与 startup-surface 边界：新增 fixed-port backend
  ownership、child identity/manifest/OpenAPI-method check、HMAC-SHA256
  challenge-response proof 和四枚举 private native-picker RPC。完成 owned-backend
  handshake 后，host 严格读取持久化的 `desktop|browser` preference：desktop 创建
  zero-permission WebView，browser 以 host-only pinned opener 打开 fixed origin，
  single-instance/tray open 重新打开该 selected surface，而 desktop close 只隐藏
  window、不停止 monitor。缺失 manifest 的 checkout 会在 Tauri startup 前以
  status 78 退出；host credential 从 child environment 移除，bounded liveness
  watcher 撤销 RPC authorization。host 在读取 preference 后重复 ownership proof；
  picker bridge 保留 Rust 的 120-second dialog 与 Python 的 125-second budget，
  并将 private failure 映射为脱敏 HTTP 503。isolated `cargo check`/`cargo test` 和
  聚焦 Python static contract 通过。上方另行记录后续 L6 isolated TestClient
  endpoint contract；两项记录都不代表 Tauri/FastAPI product service、installer、
  signing、native panel、Windows BAT 或 platform smoke test。
- 2026-08-16 Tauri 2 foundation：新增 public execution plan、single-source
  version synchronizer、pinned pnpm Tauri dependency、fixed-localhost host
  scaffold 以及不安装依赖的 Windows/macOS doctor/bootstrap entry point。diagnostic
  从请求的 project root 运行，阻止 Rustup/Corepack auto-download，并在 Windows
  interpreter、MSVC 或 SDK prerequisite 缺失时 fail closed。一个经过 checksum
  verification 的 isolated Rust 1.85.0 environment 现在锁定精确 Tauri crate，
  生成经审查、MSRV-compatible 的 `Cargo.lock`，并通过聚焦 `cargo check`/fixed-origin
  Rust test；普通 user environment 不变。lifecycle、Host RPC、updater、packaging 和
  platform smoke test 仍明确未实现。
- 修正 interface-flow release boundary，使其记录已完成的 public transition，同时
  保留禁止复用 retired private asset 的约束。
- 将 Windows CI 的 release-version argument 从 retired `0.2.0-beta.1` literal
  改为读取 `version.py`，使 source-identity gate 与 public release configuration
  对齐。
- 2026-08-14 public repository transition：在新的 public repository 发布已审计的
  sanitized root；只在 owner-controlled private archive 保留已退休 original graph，
  并启用 public-repository security 与 contribution governance。未复用任何 retired
  package、tag、receipt、Release asset 或 update Feed。
- 准备 sanitized public root：将历史 business fixture 替换为明确的 synthetic data，
  retire pre-publication release evidence，并新增 all-ref 和 hosting verification
  gate。
- 修正 alpha-channel update-feed prerelease validation，并同步 local-candidate
  publication gate 和 Windows source-development guidance。

## 公开基线 - 2026-08-14

- public repository 从经过净化的 source snapshot 开始。较早的 private development
  history、validation narrative 与 release artifact 有意不属于 public Git graph。
- 下一条 development line 是 `0.3.0-alpha.1`，它引入 Tauri 2 desktop host，同时
  保留 Python、FastAPI、Web 与 monitor core。
- 本仓库不发布任何 pre-publication binary 或 tag。未来 public binary 将使用新
  version 和全新、经过审计的 release evidence。

## 兼容范围

- invoice extraction、projection、independent monitor、localhost API 与既有 Web UI
  仍是共享 product core。
- 第一版 Tauri release 面向 Windows 10/11 x64 NSIS 与 macOS 13+ arm64
  DMG/update archive；其他 desktop variant 不在范围内。
