# 工作区原型后端缺口：开发方向（交给 Codex 实施）

- 状态：P1（B1/B2/B4/B6）本地已实现（2026-11-17）；P2 B3/B5/B7 本地已实现，B8 已接入手工基础、自动政策计算待复核。真实/平台验收与独立提交仍待完成。对应待办 [WS-10](PRODUCT_BACKLOG.md#ws-10)。
- 视觉与交互真值：[工作区原型](design/workspace-sidebar-prototype.html) 与 [前端设计标准](design/WORKSPACE_UI_STANDARD.md)。前端占位已就绪的项会标注“前端接入点”。
- 通用约束（每项都适用）：
  - 先读 [AGENTS.md](../AGENTS.md)，再按 [任务导航](architecture/AGENT_TASK_MAP.md) 读取命中的规则页。
  - 新 API 放 `src/invoice_hub/api/routes/`，用例放独立服务模块。
  - 同步 [接口与流程](architecture/INTERFACES_AND_FLOWS.md)、[数据与算法](architecture/DATA_AND_ALGORITHMS.md)、[文件地图](architecture/FILE_MAP.md)。
  - 金额一律用十进制字符串，不经过浮点。
  - 页面只显示后端结果，不自算。
  - 写操作带 `revision`；冲突返回 409 由前端刷新，不自动重放。
  - 响应未知的写操作只能查询结果，不得重复提交。
  - 真实业务资料与凭据不进入测试夹具。

## 优先级与顺序

| 序 | 编号 | 内容 | 优先级 | 前端状态 |
|---|---|---|---|---|
| 1 | B1 | 目录列表统计：标签筛选后重算、金额改十进制字符串 | P1 | 已实现：标签后统计、同票十进制合计 |
| 2 | B2 | 公司资料夹预检测（向导“检测结果”表） | P1 | 已实现：检测表、所选补建与结果查询 |
| 3 | B3 | 标签使用计数（设置“使用中 N 张”） | P2 | 已实现计数、离线提示与刷新 |
| 4 | B4 | 做账期间索引与导出预览（列名 chips、预览表） | P1 | 已实现：期间索引、无写预览与查询回执 |
| 5 | B5 | 凭证墙“已对流水 / 未对流水”与项目归属字段 | P2 | 已实现后端胶囊/项目字段 |
| 6 | B6 | 成本分析按公司取纳税人身份（只读） | P1 | 已实现：公司身份只读、回退提示与销项隔离 |
| 7 | B7 | 银行流水版式映射（预览 / 保存版式档案） | P2 | 已实现公司表格映射、余额链与复用 |
| 8 | B8 | 增值税测算、已申报 / 已缴录入与税费标签 | P2（受税务规则约束） | 手工记录/测算已接入；自动政策测算未实施 |

## B1 目录列表统计

- 实施状态（2026-11-17）：本地已实现；自动化/合成浏览器范围见 CHANGELOG 同日记录，未进入 main/发行。

- 现状：`GET /api/v1/companies/{id}/directories/{key}/invoices` 透传首页服务的 `stats.all / stats.filtered`（`invoice_list.py::_invoice_stats`）。存在两个问题：
  - `tag` 筛选在 `company_views.directory_invoices` 里于统计之后才执行，`filtered` 不含标签筛选；
  - `total_amount` 是 `round(float, 2)`。
- 方向：
  - 标签筛选之后重算 `stats.filtered`（同票家族去重口径与首页勾选合计一致）。
  - `total_amount` 改为十进制字符串，新增 `total_amount_valid_count` 表示计入了多少张。
  - 首页 `/api/v1/invoices` 同步改字段类型，前端兼容两种类型一个版本。
- 验收：
  - 标签筛选与关键字 / 格式 / 状态组合后，统计与列表一致；
  - 同号多格式只计一次；
  - 非法金额不计入，并给出张数。
- 前端接入点：`DirectoryInvoices.vue` 的 `.dir-stats`，拿到正确值后去掉“按标签筛选时不显示合计”分支。

## B2 公司资料夹预检测

- 实施状态（2026-11-17）：本地已实现；自动化/合成浏览器范围见 CHANGELOG 同日记录，未进入 main/发行。

- 原型：向导里选择路径后立即出现“检测结果”表，列为子目录 / 检测（找到 · N 个文件，或未找到）/ 处理（勾选“创建空文件夹”）。
- 方向：
  - 新增只读接口 `POST /api/v1/companies/detect`，请求 `{root_dir}`，返回 `{root_status, subdirs:[{key,label,status,path,file_count,suggested_action}], plan_hash}`。
  - 不登记、不建目录、不改监控目录；拒绝链接 / junction 越界（复用 `company_directory_guard`）。
  - 登记接口 `POST /api/v1/companies` 增加可选 `create_missing:[key]` 与 `plan_hash`：服务端重新检测，`plan_hash` 不一致返回 409，然后复用现有子目录补建任务（预览 → 确认 → 只查询结果）。
- 验收：
  - 检测期间目录被替换时 `plan_hash` 失效；
  - 只创建勾选的空目录；
  - 不移动、不改名、不覆盖现有文件；
  - 原生选择器取消时保留草稿。
- 前端接入点：`CompanyCreateForm.vue` 在“已有资料夹”模式下的路径输入框之后插入检测表，“登记”按钮带上 `create_missing / plan_hash`。

## B3 标签使用计数

- 实施状态（2026-11-17）：本地已实现：可见标记按票号全局去重，离线资料返回已知计数与不可用公司，不读取源发票。

- 方向：`GET /api/v1/invoice-tags?include_usage=1` 返回 `usage:{tag_id: count}`。
  - 计数口径为全部已登记公司资料夹内、可见标记的发票号去重数；
  - 不可用的公司资料夹列入 `usage_unavailable:[company]`，不当作 0。
- 验收：删除标签后计数归零；资料夹离线时提示而不是显示 0。
- 前端接入点：`InvoiceTagsEditor.vue` 增加“使用中”列（原型宽 90px，右对齐“N 张”）。

## B4 做账期间索引与导出预览

- 实施状态（2026-11-17）：本地已实现；自动化/合成浏览器范围见 CHANGELOG 同日记录，未进入 main/发行。

- 现状：
  - 页头期间来自已载入草稿的 `vouchers[].month`，未载入时没有月份可选；
  - 导出弹窗没有列名 chips 和预览。
- 方向：
  - `GET /api/v1/companies/{id}/voucher-drafts` 增加 `months:[{month, vouchers, approved, blocked, exported}]`，与现有审核表一一对应，只读；年月选择器的绿点与“导出凭证（N）”取这里的值。
  - `POST /api/v1/companies/{id}/voucher-drafts/{name}/export` 增加 `dry_run: true`：
    - 返回 `{format, columns:[...], unmatched:[...], sample_rows:[...≤5], months:[{month, approved, blocked_reason}]}`；
    - 不写文件、不记已导出，制单人必填规则不变。
- 验收：
  - dry_run 与正式导出的列、整月阻断判定一致；
  - 正式导出仍需二次确认；
  - 响应未知时只查询结果、不自动重放。
- 前端接入点：
  - `CompanyVouchers.vue` 导出弹窗的格式选择下方加列名 chips（原型 `.export-cols`）和预览表；
  - `modules.book[companyId].months` 改由接口填充。

## B5 凭证墙对流水状态与项目

- 实施状态（2026-11-17）：本地已实现：沿用真实匹配家族和人工优先项目；红冲、解析错误、过期投影为 null，缺完整月份不能标未匹配。

- 方向：总览原始凭证行（`OverviewDocuments` 的数据源）增加以下字段，全部取自现有比较结果，不在前端推断：
  - `flow_match: "matched" | "unmatched" | null`，`null` 表示不适用或未计算；
  - `project`；
  - `project_source: "remark" | "manual" | null`。
- 前端接入点：卡片右下角显示“已对流水 / 未对流水”胶囊和“· 项目（人工）”。

## B6 成本分析按公司取纳税人身份

- 实施状态（2026-11-17）：本地已实现；自动化/合成浏览器范围见 CHANGELOG 同日记录，未进入 main/发行。

- 原型：“本公司设置”显示公司资料夹的纳税人身份与销项税率，是只读胶囊；销项直接读同公司的“开具发票”，不再有全局开具目录。
- 方向：
  - 成本服务按所选公司与月份读取 `taxpayer_periods`，返回 `{taxpayer_type, source:"company"}`；
  - 全局税务设置只在公司未设置身份时作为回退，并在页面明示“未设置，按 … 计算”。
- 验收：切换公司时口径随之变化，不串用别家公司身份；已开数量与品目表按公司分别保存（遵守 [成本规则](architecture/rules/COST_ANALYSIS.md) 中的现有不变量）。
- 前端接入点：嵌入成本页的 `#costTaxProfile`，在工作区模式下纳税人身份改为只读胶囊，保留“品目表”按钮。
- 2026-11-17 修订：按用户 2026-11-10 的决定（纳税人身份以公司清单为准、成本页只改销项税率），销项税率在工作区模式下保持可改；上文原型“税率也只读”的描述不再适用。

## B7 银行流水版式映射

- 实施状态（2026-11-17）：本地已实现公司内首批表格映射：CSV、单表 XLSX、可还原表格文字 PDF；原始行样例、断点禁存、revision/源身份重验，后续同版式文件在公司账簿/往来自动套用。OFD/OCR/复杂表格和 CLI/凭证生成复用仍属 BANK-01。

- 原型 `openMapping`：
  - 一个宽弹窗“确认列映射 · 文件名”，内含说明 notice；
  - 每个列头一个下拉，下方有绿色 / 琥珀小提示；
  - 一行方向判定（成立显示绿、不成立显示红）；
  - 底部按钮“确认并保存为版式档案”。
- 方向：按 [BANK-01](PRODUCT_BACKLOG.md#bank-01) 实现，提供以下接口：
  - `POST /api/v1/companies/{id}/bank-layouts/preview`，请求 `{file_ref}`，返回 `{columns, guessed_mapping, balance_chain:{ok, breaks}, layout_hash}`；
  - `POST /api/v1/companies/{id}/bank-layouts`，请求 `{mapping, layout_hash, revision}`。
  - `file_ref` 只接受服务端列出的目录内文件身份，不接受任意路径。
- 验收：余额链断开时禁止保存，并标出断点行；同版式的后续文件自动套用。

## B8 增值税测算、已申报 / 已缴与税费标签

- 实施状态（2026-11-17）：部分实现：公司根税费记录、六税种分月申报/缴纳录入、普通一般计税显式手工假设及 trace/同源解释已接入。缺少已复核政策包、表式映射与征期，自动税务测算/申报表导入和完整税务工作台未实施。

- 约束：税务工作台当前仅为设计（见 [税务规则](architecture/rules/TAX_WORKBENCH.md)、[设计](TAX_WORKBENCH_DESIGN.md)、[算法与政策](TAX_ALGORITHMS_AND_POLICY.md)），本轮 P2 请求授权工作区手工基础实施，不代替政策内容复核；完整 D0—D5 未完成，不得把原型的合成数字当真值。
- 方向：
  - `GET /api/v1/companies/{id}/vat-filing?start&end` 返回测算值（附算法 ID 与步骤）和已录入的申报 / 缴纳记录；
  - `PUT` 用于录入或导入申报表结果，带 `revision`；测算值永不自动变成“已申报”。
  - 税费标签按税种返回行与可展开的算法说明。
- 前端接入点：总览 `.overview-vat`（现为“尚未接入 / 未录入”、按钮禁用），做账“税费”标签的空态卡片。

## 交付要求

每项单独提交，提交内容须包括：
- 后端单测与 API 契约测试；
- 前端消费改动与 Vitest 测试；
- 合成浏览器下的浅色 / 深色截图核对；
- CHANGELOG 记录；
- 本文对应条目改为“已实现”，并回写待办 WS-10 的状态。

## 2026-11-17 P1 交付说明

B1 增 valid/missing/conflict 家族计数，兼容旧数字一个版本。B2 计划绑定目录身份，runtime 执行日志使未知登记只能查询。B4 预览与正式导出共用全部校验和列映射，支持 month 限定当前审核表，request_id 查询回执防重放。B6 提供公司+月份的只读身份接口；实际 v1 投影按当月身份，历史查询不重算历史成本；同公司开具映射为权威，缓存来源变化即排除旧结果。

本轮保留了起点大量既有未提交工作，新增代码与其共用文件，因此尚未按四项独立提交；禁止直接把前序工作混入 P1 提交。工作分支 `codex/workspace-p1`，待前序基线整理后逐项提交，不默认推送。真实资料/Windows BAT/正式入口前台/原生选择器/成品验收保持待执行；P2 不在本轮。

## 2026-11-17 P2 交付边界

B3/B5/B7 的本地接口与前端已接入；B8 提供独立记录和受限手工场景，自动政策规则保持 null/needs_review。税费结果按月正额合计，不跨月轧差；留抵核对与查询范围无关。空查询范围仅已保存记录首末月，页面明示覆盖期。银行映射保存不修改源文件，独立余额方向只接受唯一全链成立假设；首行倒推期初仍需原件核对。

分支 `codex/workspace-p2`，保留前序大量未提交内容，本轮增量与前序共用文件，尚未独立提交，不默认推送。代码/合成验收不替代真实资料、Windows BAT、原生/成品验收。完整 BANK-01 与税务工作台继续登记在待办。

## 2026-11-17 P2 前后端对接核对

- 契约：B3 `include_usage`、B5 `flow_match/project/project_source`、B7 三个 `bank-layouts` 接口、B8 `vat-filing` GET/PUT 的路由与 Vue 调用、字段一一对应。
- 修正：B7 预览不跑保存时的账号检查，缺“本方账号”列的文件显示余额链成立、按钮可点，保存返回 422。预览新增 `save_blockers`，页面逐条显示并禁存。`WsModal` 传送到 `<body>`，`#app button.primary` 不覆盖弹窗，所有弹窗主按钮退化为普通按钮；已补 `.ws-modal` 选择器。映射弹窗改为原型列头下拉 + 来源小签 + 方向 checkline；税费表改为原型一行一税种、点击展开算法；B5“未对流水”用琥珀胶囊；null 显示“未测算 / 未录入”。

## 后续开发规划（P3，待用户排序确认）

| 序 | 编号 | 内容 | 前端 | 后端 | 依赖 / 门禁 |
|---|---|---|---|---|---|
| 0 | — | 已完成（2026-11-17）：按风险拆成本地提交，清单见 [分支状态](BRANCH_STATUS.md) | — | — | 未推送 |
| 1 | B7.1 | 银行目录“版式识别”表：每个文件显示内置版式 / 已确认版式 / 未识别、行数、余额链、页脚合计；只有未识别文件出现“确认列映射” | 改 `BankLayouts.vue` 文件表 | `GET bank-layouts?files=1` 每个文件附 `recognition{kind,rows,chain_ok,breaks}`，复用公司 bank reader，按文件签名缓存 | 读取量受目录大小影响，需上限与超时 |
| 2 | B7.2 | 文件没有本方账号列时，允许在映射弹窗手填一次账号并存入版式档案 | 弹窗增账号输入 | 档案增 `account_fixed`，`statement()` 接受档案账号；同指纹文件若出现账号列须一致 | 账号属业务数据，档案不再可分享，需在规则页写明 |
| 3 | B7.3 | CLI 与凭证生成改走公司版式适配入口（BANK-01 余项） | — | `bank/workpaper.discover` 统一入口 | 与页面结果一致的回归 |
| 4 | WS-10 余项 | 凭证编辑器期间行、表尾合计 / 加一行 / 删除行、无边框单元格；库存精简视图；工资当月行高亮 | 纯前端 | 增删行须后端校验同现有审核接口 | 需合成草稿数据实测 |
| 5 | B8.1 | 税费表补“计税依据 / 税率”列与“本月税费测算合计（不含企业所得税）” | 列与 KPI 占位 | 附加税、印花税规则包 | 受 [税务规则](architecture/rules/TAX_WORKBENCH.md) D0—D5 门禁，需官方原文与独立样例；未签署前保持 needs_review |
| 6 | ENG-05 | 合成目录 + 本机后端的真实浏览器 E2E，覆盖弹窗按钮样式、映射保存、税费展开 | 测试脚本 | 合成夹具 | 本轮弹窗主按钮缺陷只有浏览器能发现 |
| 7 | WS-08 / WS-09 | 汇总缓存增量刷新；服务器链接试验版 | 按设计稿 | 按设计稿 | 已有设计与原型，未评估 |
