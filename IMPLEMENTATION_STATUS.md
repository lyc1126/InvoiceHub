# IMPLEMENTATION_STATUS

## 2026-11-13 凭证草稿页面导出（WS-05 第二阶段 B，工作分支 `codex/ws-07-company-registry`）

- “凭证草稿”可以“导出已审核…”：确认并填写制单人（可填各月账套已用到的凭证号）后，与 `voucher_cli export` 相同地写出账套导入文件到公司资料夹 `做账草稿/`；某月有不合格凭证整月不导出，已导出过的跳过。导入账套仍由会计人员手工完成。
- 未完成：通用导出格式（BK-01）、页面生成草稿、原始凭证跨期标注、工资社保页面；税费测算仍属税务工作台设计阶段。

## 2026-11-13 凭证草稿改所属期与记账日期（WS-05 第二阶段 A，工作分支 `codex/ws-07-company-registry`）

- “凭证草稿”每张凭证可改所属期（不能选未来月份；移到另一个月后接该月已有号重新编号，需重新审核）与记账日期（不在所属期内不能审核）；草稿的月度核对、银行对账、库存核对、待补科目在页面只读显示。
- 未完成：页面导出、页面生成草稿、原始凭证跨期标注、工资社保页面；税费测算仍属税务工作台设计阶段。

## 2026-11-13 比较记录查看原票（WS-04，工作分支 `codex/ws-07-company-registry`）

- 勾稽与同号检查下方的并排记录里，监控目录的发票行有“原票”：右侧面板显示缩略图与大图（XML 为原文），经首页同一预览管道，打开期间自动续租、过期自动重建。非监控目录的记录没有原票，须先设为监控目录。
- 未完成：总览常驻缩略图墙、银行回单缩略图、汇总卡片与流水行的单独明细。

## 2026-11-13 同号检查（WS-04，工作分支 `codex/ws-07-company-registry`）

- 侧栏“选择以进行比较 → 与已选项进行比较”对没有勾稽关系的两个发票目录（成本发票 / 开具发票 / 费用报销，可跨两家公司）打开“同号检查”：列出两边都有的发票号码，区分疑似重复与双方同一张票（一家开具、另一家取得），金额或销售方不同标红；只读。
- 未完成：比较页的缩略图与大图、汇总卡片与流水行的单独明细。

## 2026-11-13 多行批量打标签（WS-06，工作分支 `codex/ws-07-company-registry`）

- 监控目录的发票列表勾选多行后，在任一勾选行右键（或 Shift+F10）可给全部勾选的发票打或取消标签；菜单显示全部 / 部分 / 没有三种状态，同一发票的多种格式按号码只算一张，没有号码的跳过并说明。非监控目录没有勾选，仍逐张打标签；旧首页列表未接入。

## 2026-11-13 凭证草稿页面审核（WS-05 第一阶段，工作分支 `codex/ws-07-company-registry`）

- 公司标签新增“凭证草稿”分区：读取公司资料夹 `做账草稿/` 里命令行生成的凭证审核表，逐张显示分录、借贷合计、导出同一套校验的错误与提示；可改摘要、科目编码、借贷金额、供应商与审核状态，保存写回同一工作簿（带 revision）。借贷不平、科目不可用的凭证不能审核通过，改过的凭证要重新审核；不写 `凭证/`、不连接账套，导出仍用 `voucher_cli export`。
- 未完成：页面导出、页面生成草稿、所属期与记账日期调整、库存 / 工资社保 / 税费页面。

## 2026-11-13 目录标签的勾选操作条（WS-01 第二阶段，工作分支 `codex/ws-07-company-registry`）

- 监控目录的目录标签可以勾选发票（表头勾选本页、全选筛选结果、取消勾选），底部浮出操作条显示张数与价税合计，“合计详情”列出三项金额与提示；打印、开具入库单、删除所选（先列文件、条内确认、移入废纸篓）都调用经典首页同一组接口。非监控目录与临时结果不能勾选。
- 未完成：目录页的源文件预览（仍在经典首页）、开票时间排序、“发票分类与业务”列。

## 2026-11-11 比较明细与并排原始记录（WS-04，工作分支 `codex/ws-07-company-registry`）

- 比较结果新增 `records.{a,b}`、各类目的 `record_ids` 与后端计算过程 `steps`；“勾稽”与 ⇄ 标签里，点进销存品类 / 规格、往来单位 / 逐笔对应的“来源”、抵扣所属期，右侧弹出明细抽屉（逐步计算），下方两个目录的原始记录并排并只留相关记录。
- 未完成：缩略图与大图（只对监控目录可做）、同号发票检查、汇总卡片明细。

## 2026-11-11 工作区外框第一阶段（WS-01，工作分支 `codex/ws-07-company-registry`）

- `/workspace/` 首页改为：最左模块列（首页；成本分析、单据、做账、OCR、一致性、设置在迁移前链接经典页面；左下“更新”“经典界面”）+ `InvoiceHub ⌄` 侧栏（置顶、公司 › 项目 / 六类目录，监控中的目录带绿点，缺失目录灰显，右键 / ⋯ / Shift+F10 菜单，悬停名片，可拖动调宽 220—460px 且内容区至少 620px，置顶 / 展开 / 宽度存本机浏览器）+ 顶部标签（公司、目录、项目、⇄ 比较、添加公司、发票标签；同一对象只开一个，打开的标签常驻保留状态，可全部关闭回起始页）。双击 `hi.` 只重建当前标签并重读数据。侧栏“选择以进行比较 → 与已选项进行比较”只在同一公司、有勾稽关系的两类目录间可用，打开预选关系的 ⇄ 标签。旧 `/workspace/companies`、`/workspace/directory` 重定向到首页。
- 未完成：目录页的经典首页发票列表全部能力（勾选合计与详情、`>>` 菜单的预览 / 打印 / 入库单 / 删除、底部浮出操作条），这些仍在经典首页；临时识别入口；未迁移模块在 Vue 中的页面缓存。

## 2026-11-11 进销存按品类计算并读回账套期初（WS-07，工作分支 `codex/ws-07-company-registry`）

- “勾稽”的进销存改为按品类（`goods_family` 标准名称 + 单位，与账套库存商品明细和做账草稿一致）做月末一次加权；品类前 ▸ 展开规格行，规格只列购入、销售与净增，不分摊期初与成本，各规格之和与品类合计由后端校验。
- 期初：公司资料夹 `做账草稿/账套读回/序时账_*.txt` 有起算月之前的月份、且 `凭证/科目表.json` 能定位“库存商品”时，用账套库存商品分录累计（`stock_opening`），起算月之前的发票不再重复计入；否则仍按 0 起算，并写明原因。只读，请求时读取。
- 未完成：往来核对的账套期初（序时账读回没有往来单位辅助核算，暂按 0 起算）；建账期初余额（科目期初，不在序时账里）的读取。

## 2026-11-11 发票自定义标签（WS-06，工作分支 `codex/ws-07-company-registry`）

- `/workspace/companies` 左栏“发票标签”管理颜色、名称与意义；公司目录的发票列表在名称前显示标签色点（悬停看名称与意义），右键或 Shift+F10 打标签，可按标签筛选。标签定义存本机，标记存公司资料夹 `发票标签.json`；不改变金额、状态、勾选合计或任何投影字段。
- 未完成：多行批量打标签；旧首页列表接入（随 WS-01）。

## 2026-11-11 公司项目汇总（WS-03，工作分支 `codex/ws-07-company-registry`）

- `/workspace/companies` 新增“项目”标签与 `GET/PUT /api/v1/companies/{id}/projects*`：按发票备注的项目名称归集进项与销项，没有或不一致的可人工指定，人工值存在公司资料夹根目录 `项目归属.json`（带 revision，重新汇总不覆盖）；未归属单列不分摊；合计与发票账簿交叉校验。
- 未完成：旧首页的项目列；与 WS-01 侧栏“公司 › 项目”树合并。

## 2026-11-11 往来核对（WS-07 第 4 步，工作分支 `codex/ws-07-company-registry`）

- “勾稽”标签新增“成本发票 ⇄ 银行流水（应付往来）”“开具发票 ⇄ 银行流水（应收往来）”：按往来单位给出期初、本期发票、本期收付、期末；流水先红冲抵销，再一对一同额，再唯一 2—3 张组合，对不上的不猜；非发票流水、户名不唯一、本公司账户单独列出；余额与笔数守恒由后端从原始清单复算。只读。
- 未完成：账套读回期初；比较与原始文件并排联动（WS-04）；第 5—6 步。

## 2026-11-11 进销存（WS-07 第 4 步，工作分支 `codex/ws-07-company-registry`）

- `GET /api/v1/companies/{id}/compare?a=cost_invoice_dir&b=issued_invoice_dir` 与“勾稽”标签的“成本发票 ⇄ 开具发票（进销存）”：按品目表标准名称 + 规格 + 单位归并两个目录上次的成本明细，进货额与开票参考同口径，逐月调用做账库存的 `cost_of_sales` 做月末一次加权；期初库存按 0 起算并标注；卖超、销项品目在进项中找不到、未计入的明细行照实列出，数量守恒由后端校验。只读，不刷新、不写任何投影。
- 未完成：账套读回期初；往来核对；第 5—6 步。

## 2026-11-11 抵扣核对（WS-07 第 4 步，工作分支 `codex/ws-07-company-registry`）

- 新增 `GET /api/v1/companies/{id}/compare?a=cost_invoice_dir&b=input_deduction_dir` 与 `/workspace/companies` 的“勾稽”标签：读进项抵扣目录里电子税务局导出的“用途确认信息”清单，按发票号码对照成本发票，列出当期/前期开票、清单有目录无、目录有清单无（专票）、未勾选、重复勾选与税额不一致；清单合计行、行数、重复与税额四类校验由后端计算。只读，不写文件；已勾选不等于已申报。
- 未完成：进销存与往来核对（第 4 步其余）；账套读回期初；用户数据与前端缓存（第 5—6 步）。

## 2026-11-11 公司账簿加入银行流水（WS-07 第 3 步银行部分，工作分支 `codex/ws-07-company-registry`）

- `GET /api/v1/companies/{id}/ledger` 新增 `bank`：请求时只读解析公司“银行流水”目录的中国银行对账单 PDF（回单只计数），按账户与月/季/年给出期初、收入、支出、期末；没有对账单的月份标为缺失、余额留空，该期校验不成立；对账单逐行余额、页脚合计、期间衔接的自检一并返回。不写公司资料夹，按文件签名缓存在内存。`/workspace/companies` 的“发票账簿”下方显示“银行流水”区。
- 未完成：勾选清单与账套读回期初的聚合（缺格式样例）；其他银行与 Excel/CSV 对账单；比较、用户数据与前端缓存（第 4—6 步）。

## 2026-11-10 工作区“公司”模块（WS-02 / WS-07 界面，工作分支 `codex/ws-07-company-registry`）

- `/workspace/companies` 可以登记公司、查看并补建子目录、把某个子目录设为监控目录、查看非监控目录的只读发票、查看公司发票账簿（含守恒校验与未计入的发票），以及设置纳税人身份。旧页面不变。
- 未完成：原生目录选择器、从零新建向导、与 WS-01 侧栏外框合并；未在 Tauri、Windows 或打包产物上验证。

## 2026-11-10 多公司工作区后端第 3 步（发票部分）：公司发票账簿（WS-07，工作分支 `codex/ws-07-company-registry`）

- 新增 `GET /api/v1/companies/{id}/ledger`：一家公司的进项（成本发票）与销项（开具发票）按月、季、年汇总。同票多格式只计一次；金额未识别、格式间冲突或不守恒的票单独列出、不计入；守恒校验由后端计算；标注票面口径。只读上次汇总结果，不触发汇总。
- 未完成：银行流水、勾选清单、账套期初的聚合（需 `bank/` 模块先提交），以及比较、前端消费。

## 2026-11-10 多公司工作区后端第 2 步：按公司只读目录，纳税人类型以公司清单为准（WS-07，工作分支 `codex/ws-07-company-registry`）

- 新增按公司只读目录（`state.company_views`，`/api/v1/companies/{id}/directories*`）：各子目录的上次汇总与成本明细、请求时的有界只读过期判断、与首页同结构的只读发票列表。非活动目录不在后台扫描、不重建、不写入；活动目录交给现有服务。
- 成本开票参考的纳税人类型改为以公司清单为准（活动目录所在公司当月的登记），销项税率仍按成本页保存值；API、监控进程、后台首轮同步与手动重建同一口径，清单改动后会重写工作簿。成本页提交不同类型会被拒绝。
- 未完成：成本页显示来源并禁用类型选择、按进项票月份分别判断类型、WS-07 第 3—6 步、所有前端消费；未在 Windows 或打包产物上验证。

## 2026-11-10 多公司工作区后端第 1 步：公司清单（WS-07，工作分支 `codex/ws-07-company-registry`，基于未合并的 `codex/cost-select-all-transitions`）

- 后端新增公司清单（`state.companies`，`/api/v1/companies*`，存于 `runtime/local_state/companies.json`）：登记公司名称、资料夹根、六类标准子目录映射（自动识别无歧义的现有文件夹）与纳税人身份生效期；子目录状态检测；缺失子目录先预览、确认后只新建空目录；删除公司只删条目。写入带 revision；清单损坏时保留原文件并拒写。
- 运行模型不变：仍是单活动监控目录；清单操作不切换 `watch_dir` 或监控，只标记活动目录所在的公司。没有清单时行为与之前一致。
- 未完成：页面消费（WS-01/WS-02 界面）、纳税人身份接入成本页、WS-07 第 2 步按公司只读视图及后续聚合、比较、明细。未在 Windows 或打包产物上验证。

## 2026-11-09 工程门禁、API 路由拆分与 Vue 工作区前端基础（工作分支 `codex/engineering-guardrails`，基于未合并的 `codex/cost-select-all-transitions`）

- CI：新增 ruff（E9+F）、Rust（macOS/Windows 的 `cargo fmt --check`、clippy、`cargo test`；Windows clippy 暂只报告）、两平台 Node 交互测试、Vue 前端（类型检查、组件测试、提交构建逐字节可复现）作业；SwiftUI 参考壳的 `swift test` 改为路径触发的独立 workflow。
- 后端：113 条领域路由从 `api/app.py` 拆到 `api/routes/` 的 10 个模块，共享辅助在 `api/common.py`；OpenAPI 与路由匹配结果与拆分前一致。`AppState` 已按领域拆分（ENG-03，2026-11-10）：用例在 `services/` 下 16 个领域服务中；ENG-08 删除转发后路由以 `state.<服务>` 直接调用，`app_state.py` 由 5779 行降为约 370 行，只保留组装、共享状态、health、切换 watch_dir 与删除所选两条跨域编排。
- 前端：`frontend/`（Vue 3 + TypeScript + Pinia + Vue Router + Vitest）提交构建到 `web/static/app/`，`/workspace` 只读预览外框（概览、目录）；旧页面不变。多公司工作区（WS-01 起）在此基础上实现。
- 未覆盖：GitHub CI 尚未实际运行（未推送）；Windows 与 Tauri 打包产物未重建；本机回环网络策略下 4 个 Rust socket 测试无法在本地通过。
- 同日修复 ENG-07：`api/app.py` 去掉模块级实例，`api/main.py` 显式 `create_app()`；pytest 增加仓库运行态守护，全量测试不再改写 checkout 的 `runtime/`、`发票文件/`、`config/`。

## 2026-11-08 开票参考全选、sheet 平滑切换与工作区原型成本分析模块（工作分支 `codex/cost-select-all-transitions`，基于未合并的 `codex/cost-reference-exclusions-ui`）

- `/costs` 开票参考新增“全选（N 行）/ 清空全选”，全选覆盖全部页；切换 sheet 与翻页不再显示进度条、不整页重绘、不把滚动拉回顶部，已看过的 sheet 立即显示并淡入；后台刷新数据未变时不重建表格。资源版本 `20261108-cost-smooth-tabs-3`。多公司工作区原型新增可交互的“成本分析”模块（按公司：纳税人身份取自公司资料夹、销项读同公司开具发票、数量在前的开票参考、全选 / 按销项更新 / 移除与恢复、品目表、来源发票、底部操作条）。全量测试与真实目录副本页面 A/B 验收通过；未覆盖 Windows、其他皮肤与打包产物。

## 2026-11-08 开票参考移除与成本页操作区重排（工作分支 `codex/cost-reference-exclusions-ui`，基于未合并的 `codex/cost-item-catalog`）

- 开票参考可把品目行或来源发票（整张）“从开票参考移除”，只排除、不删除文件，成本明细与已开状态不变；“已移除 · 管理”可逐项或全部恢复。每行新增“来源 N 张”，可查看并移除来源发票。成本页操作区重排：命令栏只留视图切换、刷新、重新汇总（唯一主按钮）与“更多”；品目表入口移到“本公司设置”；批量操作与保存改为勾选 / 有草稿时浮出的底部操作条，按已开数量 / 加价率 / 移除分组，支持放弃修改与 Esc 取消。资源版本 `20261108-cost-actions-2`。全量测试与真实目录副本页面验收通过；未覆盖 Windows、其他皮肤、窄屏与打包产物。

## 2026-11-08 品目表首版（COST-02，工作分支 `codex/cost-item-catalog`，基于未合并的 `codex/cost-outbound-invoiced`）

- `/costs` 新增“品目表”弹窗：列出成本发票上出现的全部名称，可改标准名称（改名即合并）、类型（货物 / 费用 / 固定资产）与销项税率（空 = 跟随公司），保存在当前 `watch_dir/成本开票状态.json` 的 `item_catalog`。开票参考、工作簿、销项比对按标准名称归组，规格只统一全角半角与空白；非货物不进开票参考；品目税率覆盖公司税率。保存品目表时已开状态一次性迁移（合并相加、拆分按数量分摊，必要时标“已开数量待核对”）。未设置品目表时结果不变。本系统不建科目体系（账套为真值），科目对照留作做账时的第二层。资源版本 `20261108-cost-item-catalog`。全量测试与真实目录副本页面验收通过；未覆盖 Windows、其他皮肤与打包产物。

## 2026-11-06 开票参考销项比对（COST-03，工作分支 `codex/cost-outbound-invoiced`，基于未合并的 `codex/cost-output-tax-rate`）

- 手动“重新汇总”在成本分析后读取“单据”页设置的开具发票目录（`projections/cost_outbound.py`），按发票号去重多格式，只采用销售方为本目录进项购买方的发票，按开票参考分组键汇总销项数量与金额；解析缓存和汇总只写 profile 工作区。`/costs` 新增销项比对面板（读取 / 采用 / 排除 / 未对上品目、读取时间、提示），开票参考表末尾新增“销项数量”“实际加价率”“销项比对”，可单行或勾选批量“按销项更新”已开数量草稿；手填已开数量仍是保存值，比对不自动覆盖。全部已对上品目实际加价率相同时提示留存定价依据（COST-05 提示部分）。工作簿“开票参考”末尾新增同名四列。`#referenceTable` 为新增列设置宽度（同时修正 BUG-01“成本口径”列被挤压），2026-11-08 按“库存数量与票面一致”为原则调整排版：税务设置与销项数量比对并排（窄窗口上下），比对面板显示数量一致 / 待更新 / 销项超过进项 / 无销项计数，开票参考表数量列连续排在价格列前，实际加价率中性展示；`app.css` / `page-costs.js` 资源版本 `20261108-cost-quantity-layout`。全量测试与合成数据页面验收通过；未覆盖 Windows、真实业务目录、其他皮肤与打包产物。

## 2026-11-05 开票参考按公司税务设置计价（BUG-01，工作分支 `codex/cost-output-tax-rate`）

- `/costs` 新增“本公司税务设置”（纳税人类型、销项税率 13/9/6/5/3/1/0%），保存在当前 `watch_dir/成本开票状态.json` 的 `tax_profile`，未保存时按一般纳税人 13%，旧结果不变。开票参考的成本单价改为“不含税金额 + 不可抵扣税金”：小规模全部计入；一般纳税人只计入已确认的增值税普通发票（旅客运输除外），类型未确认的按不含税并标注。参考税金与含税单价改用公司税率；工作簿“开票参考”末尾新增“成本口径”“销项税率”两列，开票参考表新增“成本口径”列。已开快照不随税务设置重算。全量测试通过，并已用合成数据在源码服务 + 无头 Chrome 中验收 `/costs` 设置、保存、草稿阻止与工作簿列；未覆盖 Windows、真实业务目录、其他皮肤与打包产物。

## 2026-11-01 多公司工作区设计原型（尚未实现）

- 新增[多公司工作区交互原型](docs/design/workspace-sidebar-prototype.html)（合成数据）：左侧模块列、公司 › 项目 / 目录侧栏、A ↔ B 比较、公司/项目票面汇总、缺失子目录创建与新建工作区向导、做账可视化。它只是界面与交互方向，产品仍为单活动监控目录、单一业务资料夹，未新增 API 或页面改动。分阶段计划登记为[产品待办 WS-01—06](docs/PRODUCT_BACKLOG.md#ws-01)。2026-11-03 第四版补入：保留现有发票列表与勾选合计详情、自定义标签、侧栏拖动调宽、按关系勾稽的目录比较、凭证所属期与记账日期调整，以及银行版式识别与余额链演示；银行版式引擎方案登记为 [BANK-01](docs/PRODUCT_BACKLOG.md#bank-01)。同日第五版补入：比较类目明细与原始文件并排联动、首页空白起始页与模块页面缓存、发票列表标签预留位 / 原配色 / 底部勾选操作条，并消除局部刷新的抖动。第六版补入：双击 `hi.` 刷新本页缓存、做账所属期年月小日历、通用凭证导出（去掉单一记账软件标识）。新增[成本分析 v2 设计](docs/COST_ANALYSIS_V2_DESIGN.md)，待办新增 COST-06、WS-07、BK-01、OCR-01，待办清单改为统一的[未来工作总览](docs/PRODUCT_BACKLOG.md)。仍未改动产品代码。

## 2026-10-26 成本页算法说明浮层

- `/costs` 的平均单价算法说明浮层改为每次显示时按视口实测定位：水平夹在视口内、上方不足时翻到按钮下方、仍放不下时限高内部滚动，并避开吸顶导航；箭头跟随按钮且在各皮肤下与面板同色。`app.css` 与 `page-costs.js` 资源版本为 `20261111-cost-tooltip-viewport`（2026-11-11 提交时由 `20261108-cost-smooth-tabs-3` 升级）。已用源码隔离服务和无头 Chrome 验收，未替换已安装应用、未打包。

## 2026-10-09 双平台集成与构建

用户已授权将渐进读取、临时识别和勾选工作流整理到 `codex/selection-workflow` 并提交推送，Mac生成预览包，Windows由用户取相同提交打包。Windows回收结果确认、带参数首页原生拖入及桌面API握手门禁已补齐；图标BASIC布局与editable元数据指纹隔离用于关闭原有两类构建回归。工作分支尚未合并main；成品身份与已测/未测范围见本轮CHANGELOG和实际receipt，不能沿用前轮结果。

Mac组包的release编译、签名与DMG/receipt核验已通过首轮候选；后续补充测试夹具后重打包，最终source/core以随包receipt为准。原生启动检查因现有服务占用8766而未执行，未覆盖默认配置、系统选择器、浏览器前台或Windows成品。

## 2026-10-09 勾选操作增强

开发分支 `codex/selection-workflow` 基于 本轮开工时核验的稳定 `main`（起点提交记录在 CHANGELOG 与私有检查点），保留此前未提交工作。本轮实现确认移入原生废纸篓、按项目搜索/税率筛选、汇总来源链接与详情返回恢复、超过100份选择的逐文件预览与序号跳转。删除使用当前目标/源签名及monitor互斥锁，日志仅作操作状态，不是发票主存储；自动删除同步不改变原票。

相关实现/接口/算法/最低验收见[勾选工作流任务导航](docs/architecture/AGENT_TASK_MAP.md#task-selection-workflow)。原有临时识别及渐进读取继续保留；后续双平台集成已修正图标像素及egg-info身份差异，提交、构建与最终验收范围统一见本页双平台集成记录及CHANGELOG。正式Windows BAT、默认业务配置、前台拉起和系统选择器仍需独立验收。


## 2026-10-09 临时原文件预览

队列与历史识别结果新增“预览”：PDF/OFD按需票面、XML安全原文，支持翻页/放大/返回、源失效清空与缓存恢复。独立于活动目录和正式投影；源码与合成测试范围见 CHANGELOG，原生选择器、真实默认配置和新成品未验收。

## 2026-10-09 临时识别（工作分支）

- 已实现首页临时识别弹窗、文件排序、渐进识别、历史线程改名/删除/日期及结果 TSV 复制；设置支持批次上限和自动打开。
- PDF/OFD/XML 复用现有票头提取；源文件移走、删除、替换或内容变化后阻止查看旧缓存。独立 runtime 会话，不进入普通/成本投影。
- 桌面原生多选和拖入已接源码；普通浏览器拖入需再次经原生选择器确认原路径。图片和纯扫描件 OCR 不在本轮范围。
- 验证与未覆盖项见本轮 CHANGELOG；当前代码未合并、未发布，用户已安装包保持原状。


## 2026-10-09 渐进读取优化

- 渐进读取最初在 `codex/progressive-data-loading` 从已核验的本地 `main` 建立，现随 `codex/selection-workflow` 集成；精确起点及验收结果见 CHANGELOG。
- 首页服务端 100 条分页；成本按标签及 30/60/100 条分页，更新中保留上次完整快照。首次生成时各解析阶段发布只读临时明细，正式统计、开票状态与导出等待完整结果。
- 单据入库列表先于出库索引发布；首页批量入库不启动无关全目录索引，出库逐批显示候选，文件状态不再重复构建刚完成的预览。
- 三个页面脚本版本 `20261009-progressive-3`。7,003 条合成数据浏览器中首页 100 行、成本 30 行，跨页全选/数量草稿和完整 7,004 行 TSV 已核对；性能计量仅代表该合成场景，不能推导为真实 PDF/OFD 提取吞吐。
- 稳定 main 和发布基线不变；未覆盖真实默认配置、正式 Windows BAT、宿主前台拉起、原生选择器或打包产物。自动化与浏览器具体范围见 CHANGELOG。

## 参考凭证草稿与捷锐导入（2026-10-10，命令行）

- 新增 `python -m invoice_hub.bank.voucher_cli`：draft 由银行流水、`成本发票明细.csv` 与 `申报数据.json` 生成按月编号的参考凭证审核表，科目编码取自 `凭证/科目表.json`；export 只导出人工标“通过”的凭证，校验后按月生成捷锐导入模板，并把最终科目记入 `做账习惯.json` 供下次沿用。规则见[做账规则](docs/architecture/rules/BOOKKEEPING.md)“银行流水底稿规则”。
- 2026-10-20：draft 新增 `--booked`（捷锐序时账复制文本），已入账月份只补记漏记的银行流水并接续账套凭证号；审核表新增“银行对账”“月度核对”（含申报与发票差异）、原件超链接、数量/单位与默认短摘要；修复中国银行对账单分页序号撞号导致的分类覆盖。
- 未自动生成销售成本结转、工资社保计提、企业所得税（无申报数时）与期末损益结转；捷锐导入格式未实测；未接入页面/API，不进入 W8/W9 状态链。

## 银行流水底稿（2026-10-02，命令行）

- 新增 `python -m invoice_hub.bank`：读取中国银行对账单与电子回单 PDF，按内容识别版式，输出余额勾稽（逐行、页脚、月度断档、账面期初差额、重复行）、回单匹配、缴税回单税费拆分、往来角色与建议分录，以及私有/脱敏两份 XLSX/JSON 底稿。详细规则见[做账规则](docs/architecture/rules/BOOKKEEPING.md)“银行流水底稿规则”。
- 脱敏采用用途词白名单、HMAC 稳定化名、账号尾号、编号不可逆标记和源文件名序号化；写出前全量泄漏扫描，命中即不写出。金额和日期保留，脱敏底稿用于 AI 辅助或外部协作，不是公开发布物。
- 当前只支持中国银行版式；未接入页面/API；建议分录不进入 `凭证/` 状态或导入批次，不操作账套与电子税务局。

## 通用任务接力工具（2026-09-12）

- 用户级全局安装已在本机验证：共享技能位于 `~/.agents/skills/agent-handoff`，Claude 个人技能入口引用同一份规则，全局 `agent-handoff` 可从其它目录调用。当前使用 1.1 便携 runtime；这不改变模型权限或其它 clone 的安装状态。

[交接工具与协议](docs/AGENT_HANDOFF.md) 已增加线程链接/UUID 本地映射与明确任务交接码，默认紧凑摘要、按需展开、无变化不写、仅更新当前任务、v2 增量日志兼容旧 v1；没有后台轮询或自动抓取聊天。便携包支持复用 SHA 已确认的既有运行时。实际平台与交接验证、版本和哈希以 CHANGELOG 为准；Windows 原生验证仍单独披露，不新增产品业务或模型调度能力。

## Agent 规则按需导航（2026-09-11）

全局必读规则集中在 AGENTS.md，功能细则迁入 [10 个专题的任务索引](docs/architecture/AGENT_TASK_MAP.md#quick-lookup)；CLAUDE.md 共用此入口。任务行继续负责源码、联动与最低验收，功能规则保持原有约束。只改变文档读取结构，不新增业务或自动交接能力。

## 税务工作台设计（2026-09-11，尚未实现）

- 2026-09-12 就绪度决策新增[价值评估与就绪度](docs/TAX_WORKBENCH_VALUE_AND_READINESS.md)：记录会计痛点、计算器完成度（生产代码为零、原型不进行金额运算）、旧草稿定位核查结论（工作树、stash 与 Git 历史均无其源码）、政策中心价值判断与最小可用形态，并给出开发者重新评估清单与停止条件。[政策来源与核验](docs/TAX_POLICY_SOURCES_AND_REVIEW.md)补入订阅与待办、覆盖声明与漏报保障、版本差异展示、运营成本与复核人力四节。投入开发前先读决策页。
- 2026-09-12 设计补充：新增[政策来源、核验与政策中心](docs/TAX_POLICY_SOURCES_AND_REVIEW.md)（A/B/C/D 来源分级、四层政策中心、变更流水线与签署流程），并在设计中补入“从测算到申报”三项交付物——申报表映射、征期与申报期限、留存备查清单，以及税费种认定第一判据、资格与认定的生效期回放、税会差异台账、三单匹配视图与首轮不做进项转出自动分摊。算法规格增加跨期例与政策变更例。本轮仍只改设计文档：未执行抓取、轮询或外部请求，未新增 API、未读取公司资料。
- 已整理[设计与分阶段入口](docs/TAX_WORKBENCH_DESIGN.md)、[算法和政策核对](docs/TAX_ALGORITHMS_AND_POLICY.md)及[合成交互原型](docs/design/tax-calculator-prototype.html)。它们是后续开发规格，不注册 API、不读取公司资料、不改变当前计算或申报能力。
- 源码基准继续为稳定 `main`，发布参照 `v0.3.0-alpha.2-opt.1`；旧税务 MVP 只作待审查复用草稿。生产接入仍需规则复核、后端/前端/包数据契约、真实浏览器与适用平台验收，详见设计 D0—D5。
- 补充公司业务资料夹“选择本地文件夹”原生入口：设计规定复用现有平台选择能力、选中只回填待保存草稿、检测后保存；原型演示成功/取消/不可用。D2 才接入真实 Windows/macOS 原生窗口，当前未新增生产 picker route 或 Host RPC 命令。
- 入口补充为 20px 图标、32px 可见按钮；原型设置可切换界面内悬浮（支持拖动/重置）或置顶栏“首页”按钮左侧并纵向居中，入口不穿插模块导航。位置偏好与公司绑定独立，原型仅会话内保留；正式持久化及跨皮肤/窄屏验收属于 D1。
- 原型计算卡缩至约 292px，按可用高度分配 44—54px 按键；背面与结果各自滚动，预设/自定义税率在同一行切换。自定义支持 0—100%、最多四位小数，只作用户假设和待重算演示；实际税额运算与浏览器视觉验收仍待 D1。

2026-09-10：alpha.2 优化版 1 已完成同源 Mac 构建并发布，内置平台 Python/Java/OFD 组件；离线、包内两页 OFD 和实际正常配置的 ready/页面/monitor 验收通过。隔离 HOME 自动样本未通过，其他平台原生与签名限制仍保留。精确身份、发布状态与来源见[分支记录](docs/BRANCH_STATUS.md)；后续开发以 main 为准，制品身份由优化批次 Tag 固定。

2026-09-09 Windows alpha.2 修复优化工作基于 main PR #24，在 `codex/windows-alpha2-startup-hardening` 验证 HTTP framing/浏览器兜底，并加固 PYTHONHOME 隔离与 spawn 诊断；成品身份和实际覆盖见 CHANGELOG，不将源码测试视作公测原机复现或 macOS 验收。

2026-09-08：[`v0.3.0-alpha.2` 双平台预览](https://github.com/lyc1126/InvoiceHub/releases/tag/v0.3.0-alpha.2) 已按所有者确认的验收范围发布。Windows x64 portable ZIP 与 macOS arm64 preview DMG 同源，包含校验和、收据和平台 Python SBOM；Mac 离线核验与实际默认配置验收通过，隔离 HOME 自动烟测仍未通过，未启用安装 updater 或更新 Feed。精确发布身份和限制见[分支与发布记录](docs/BRANCH_STATUS.md)。


更新时间：2026-09-08

## OFD 预览开发

- 2026-09-09：组件验证增加带元数据失效的内存缓存，模板图层与上游 UTF-16 文字处理边界已有真实组件回归；未映射的补充平面文字仍明确拒绝，不能把其视为完整罕见字支持。

- 后续已在固定 localhost 的源码开发服务中，通过真实浏览器“列表勾选 → 预览”显示该 OFD 票面；默认浅色弹窗可见，health/background ready。当前 localhost 为隔离临时单票运行态，已发布 App 文件和用户设置未改动。

- 2026-09-08：已用新组件直接渲染一份真实单页 OFD，并在系统 Preview 展示；用户已确认该票面效果。真实文件及图片均未进入公开工作树，此结果不扩大为产品弹窗或成品验收。

- OFD 专用预览以 main 为统一源码集成基线，功能来源 `codex/ofd-preview-renderer`，精确身份见分支记录：OFD 独立使用 OFDRW 2.4.0 → PNG，已接入既有原票预览服务；MuPDF 仅用于 PDF/安全 SVG。真实 OFD 页面树、字体/图形/图片、逐文件失败和独立 worker 边界见 [OFD 预览说明](docs/OFD_PREVIEW.md)。
- 组件以 SHA 锁定的 Java 21 和依赖构建，源码开发产物位于 ignored runtime，正式分发应嵌入 Python runtime 并重新生成外层清单。本功能尚未进入已发布 alpha.2；用户问题票、Windows 真机及双平台成品仍需验收。

## 主线基线

- alpha.2 发布阶段的文档分支 `codex/macos-desktop-main-sync` 已合并并清理，当前源码统一维护在 main；OFD 集成继续复用既有 Desktop 基线。开工前的税费/Mac 脏改动保存在不进入公开输入的 stash，精确引用见[分支整理记录](docs/BRANCH_STATUS.md)。
- 已按用户要求分轮清理已合并的 alpha2、Desktop 与文档同步引用；图标/搜索等仍有独立提交的分支、Dependabot、原 stash 和旧 dirty release-prep worktree 保留，不执行全局 prune。详细引用状态见 [`docs/BRANCH_STATUS.md`](docs/BRANCH_STATUS.md)。
- 合并检查修复监控状态读取等待整轮汇总锁的问题：状态短锁独立，写入仍按 sync -> status 串行；停止请求及原有超时可在汇总过程中执行。旧 ZIP 尚未包含这项补充。
- 最新 Desktop 全量更新已通过 PR #20 合入 `main`，开发实现与后续发行源码统一以该合并提交及其主线后代为准。最终功能提交的 Windows/macOS CI 与 DCO 均通过，原独立提交和构建快照保留回溯；不发布新包。精确提交身份见 `docs/BRANCH_STATUS.md`，下文日期和旧分支名仅记录实现来源。
- 从当前 `main` 构建的 macOS arm64 alpha.2 preview 候选目录与 source 身份见[分支整理记录](docs/BRANCH_STATUS.md)，core build ID 为 `c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`，DMG SHA-256 为 `21715661a3bffa48e8afd0034a81eb975758280f3a6ed6d2356d982ec5607298`、大小 `109535179` bytes。该候选为 ad-hoc、未公证、host updater disabled，finalized receipt verifier 已通过；Mac 包内源码与 runtime 离线核验通过，隔离 HOME smoke 尚未通过，已观察到新包后端及后台同步 ready，但该实例使用真实 Application Support，未满足隔离 HOME 验收条件。
- 已收到与 Mac 同源的 Windows x64 portable 候选、SHA sidecar 和 build receipt：source 身份见[分支整理记录](docs/BRANCH_STATUS.md)，core build ID 同上，ZIP 大小 `58040173` bytes，SHA-256 为 `f7c03a502d06d19faa61ee5f9ed859c4da3f57c6789f52014dec3fd4005a6ff3`，unsigned 且 updater disabled。Windows 完整包由用户说明已验证后交付，本机独立静态验包和收据/实际 ZIP SHA-256 核对通过。`v0.3.0-alpha.2` Tag 已经所有者确认调整到本轮双平台共同源码；已发布的 ZIP、SHA-256、receipt 和 SBOM 按相同身份闭合。

## 大列表响应

- 2026-09-08 合并检查发现 Windows CI 偶发最终状态写入失败；缓存发布对 Windows 5/32/33 拒绝增加最多 20 次、累计 0.95 秒重试，先快照后 ready，持续及无关错误仍抛出。确定性故障注入回归覆盖最终状态发布与重试上限，旧 ZIP 尚未包含该补充。
- `codex/fix-large-list-responsiveness` 保留前序修复；新增独立进程 `DocumentIndex` 与按目录持久缓存，保存目录不再同步解析。`documents/state` 返回 index 及已就绪列表，新增进度/停止/继续接口，缓存校验与预览实时身份复核独立。
- 首页和单据候选按 100 条渲染，单据可搜索，全选仍针对完整筛选结果。脚本及 `large-lists.css` 使用 `20260907-large-list-1`。7,003 条合成浏览器场景通过，早先全量 DOM 超时不再适用于本实现；成品及限制见同日变更日志。

## 首页搜索范围

- 默认“销售方 / 发票号”，文件名和全部范围可显式选择；文件名搜索结果展示来源文件名，空结果使用筛选专用提示。重置恢复默认，刷新保持已提交范围。API 新增枚举 `search_scope`，省略兼容 all，逐字段匹配不跨字段拼接；不修改业务投影或提取规则。首页脚本版本 `20260907-search-scope-1`，大量合成记录与成品验证范围见同日变更日志。
- 搜索阶段交付现已由 `dist/candidates/20260907-large-list-desktop-final/` 替代，旧 search-scope ZIP/hash/receipt 已撤下。新包 148 份源码/资源一致，独立验包、真实默认配置的分页资源与 6,688 文件目录的加载中停止/继续及导航通过。早先 7,001 行全量 DOM 超时由本轮 100 行分页及 7,003 条浏览器回归覆盖。

## 启动环境诊断

- 2026-09-09 启动修复（功能来源 `codex/fix-backend-startup-probe`，源码基线统一 main）：新增有界 HTTP framing，避免完整响应后 EOF/reset 导致误报；分阶段日志保留清理前 Python 状态，提前退出快速失败。Windows WebView 创建失败时可确认浏览器兜底，`--browser/--desktop` 为本次覆盖；始终重验 ownership，不修改保存偏好。验证与未覆盖项见当日 Changelog 和[启动排障](docs/STARTUP_TROUBLESHOOTING.md)，已发布 alpha.2 未替换。

- `codex/startup-conflict-diagnostics` 保留前序修复，Windows BAT 默认以原生弹窗呈现启动失败，`-NoDialog` 供自动化使用；根 `检查启动环境.bat` 为不依赖 Python 成功启动的只读入口。PID 来源为 OS 监听表，CIM/程序路径不可读时明确降级，公开 health 的白名单身份字段仅作诊断。
- Windows Desktop 继续保留 InvoiceHub 产品名/文件描述，新增原生失败提示、托盘诊断及 `--diagnose-startup`；启动日志写到本次 runtime 或用户 diagnostics 目录。单实例沿用官方插件，但按真实程序路径与运行目录派生锁标识，开发/测试/不同包之间不再静默唤回；固定端口和 ownership 保护保留。
- 直接 Python CLI 在构造 AppState 和安排后台发票同步前检查绑定条件，端口冲突打印诊断并非零退出；Uvicorn 仍执行最终绑定。真机与新包验证结果见同日变更日志。
- 启动诊断阶段的 Windows portable 已完成冲突退出 1、原生诊断窗口、同环境复用/异环境拒绝、desktop→browser→desktop 和监控保留/停止；146 份包内源码与资源核对一致。当前交付由上面的大列表修复包接替，旧 startup-diagnostics ZIP 已撤下。此前盘点的 16 个旧 ZIP 及 30 个配套哈希/收据已删除，旧解包和空目录曾受自动审批限制，后续由用户自行处理。签名安装器、macOS、updater 和任务管理器 GUI 截图不在该阶段通过范围。

## 源码 BAT 握手

- 源码握手修复原来自 `codex/fix-source-bat-handshake`，现已整合到上述 main。Windows venv 的实际 executable 与 argv 首项分别核验可信 Python 集合，模块/root/config 继续精确匹配；不放宽 release 或完整 CIM 不匹配保护。
- 23 项原握手契约通过；隔离空目录配置完成根 BAT 的 PS7/强制 PS5.1 启动与重复启动、只停 WebUI 保留 monitor、stop-all 退出两者。本轮诊断任务又在正式退出 Desktop 后，验证真实默认 8766 的根 BAT 成功启动、重复复用和正式停止；被 Desktop 占用时仍正确拒绝接管。Tauri ZIP 不含 BAT 模块，本轮因新增 host/CLI 诊断重新构建。

## 当前工作区 Desktop 包

- 补齐并整合公开开发分支中已完成的图标选择、打印弹窗偏好、WebView 数据目录、原生选择器调度、监控串行读取、同步进度及 Windows 启动恢复。设置外观/皮肤页提供 `website/orange/teal/violet`，默认 `website` 使用当前白底 hi.；旧显式选择保留。当前资源版本为 `20260907-desktop-integrated-2`，覆盖旧候选脚本缓存冲突修复。

- 历史 `codex/desktop-current-package` 曾从公开 `origin/main` 建立并保留官网、外观、单据与故障修复；该来源线已纳入主线整理，旧 desktop-surface 候选不含这些更新，不能作为当前工作区输入。新的隔离干净构建快照必须来自实时 `main`，精确平台候选身份记录于 [`docs/BRANCH_STATUS.md`](docs/BRANCH_STATUS.md)。
- Desktop 支持浏览器/桌面偏好，下次完整启动生效；owned backend 退出时 watcher 同步请求 host 退出并释放单实例。Windows host 使用 GUI subsystem，child 无控制台且日志留在 owned runtime。
- Ink Pulse `1.4.0`、Animal Island `2.1.0` 适配新共享控件、批量单据和全局关闭弹窗；Ink Pulse 深色单据预览按用户偏好保留，真实源票面不反色。默认无皮肤及 `no_skin=1` 保留。
- 复用已有 Tauri portable 构建/验包器并接入官网白名单；不新增 Feed。最终验收、清理和未覆盖项写入当日变更日志。

## 默认前端优化

- 2026-09-06：新增品牌名旁太阳/月亮切换，默认浅色仍为无皮肤；官网 `website-dark` 内置 CSS 外观通过现有皮肤 API 保存。先加载样式再保存，失败可重试；页内草稿/勾选不丢失，首屏身份在 head 注入，恢复入口固定浅色。设置“关于”标记统一 `hi.`，公共资源版本 `20260906-appearance-3`。
- desktop 图标 04 按用户补充改为官网纸白 `#f8f9f5`、墨黑 `hi.` 与荧光折角。确定性生成 1024 母版、512 RGBA PNG、Windows 多尺寸 ICO 和 macOS ICNS，Tauri 配置显式接入默认资源。源码与图标容器验收不等于已安装程序或新桌面包的验收。

- 新增需求：普通页面统一官网字体 `hi.`；发票列表 `>>` 可将最多 1000 条勾选带入单据页，核对同票家族后逐张导出入库单，提供已有文件跳过/副本、进度及停止剩余。服务端重复验证目录与源文件身份；明细冲突及未确认网络结果不会静默略过。
- 入/出库预览改用真实模板列宽和最低明细行，导出同步合并、行高和打印范围，大写统一去掉“人民币”。相同完整来源副本不重复累计，来源内重复明细保留。资源版本 `20260906-appearance-3`，精确验证与未覆盖项见当日新增需求日志。

- `codex/default-ui-polish` 基于公开 `origin/main` 创建，保留先前未提交的官网与集成工作。默认样式加入官网品牌配色和本地字体，压缩成本统计布局；顶栏、列表操作栏和设置分类按实测顶栏高度固定。
- `system_controls.html` 与 `system-controls.js` 统一所有普通页面的关闭确认、失败重试、焦点和滚动锁。全局电源始终先确认，设置入口保留既有记住偏好语义；收到确认响应后结束 SSE，不显示误导的重连告警。
- 公共请求转圈覆盖慢读取、汇总、识别候选和生成类 API；按钮保留原尺寸与图标，普通禁用不转圈，预览续租不闪动。浏览器原生跳转没有人为等待或先淡出到空白，返回后清理导航状态。
- 本轮已运行前端静态契约、关闭/页面 API 与 Node 交互检查，并在当前真实默认配置及隔离合成数据实例检查浏览器。正式根 BAT `-Development -NoBrowser` 仍在开发身份握手失败，源码后端已独立启动供 UI 验收；不视为 BAT、原生选择器、桌面壳或打包成品通过。精确范围见本轮变更日志。

## 产品官网

- `website/` 已实现独立静态官网：原创 `Hi / hi` 印刷风格、纸票画布、产品演示、工作流、本地数据边界、开源入口、FAQ 与开始使用弹窗。页面不访问业务 API、本机配置、真实发票或更新 Feed。
- 演示为发票、成本、自适应单据、工具四视图，新增勾选预览翻页/放大、同票 PDF 打印动画、按项目/明细税率/规格/单位归集与 TSV、入/出库动态行、做账阶段和概念税额换算。首屏五个独立图层展开/归拢，功能区采用放大镜、出纸、归集和扫描动效，均保留减少动态效果与暂停。资源版本 `20260905-3`，全部本地加载，48 个 Lucide 图标与字体附许可。
- 软件「设置 → 关于 → 官方网站」已改为当前窗口打开 `/website/`；About API 返回固定本地链接，官网在该 localhost 路径下显示「返回工作台」。公开更新 Feed 未改动。后端、共享 Core Build ID、Windows 和 macOS/Tauri 组装共用 10 个资源白名单，包含字体与图标许可，排除官网维护文件；缺失资源返回可诊断 503。设置脚本与共享控件的当前版本由模板和前端契约锁定。
- 15 项 Node 演示/导航脚本检查、6 项标准库资源/打包检查通过；完整 pytest 工具未能安装，API 契约与平台成品验收范围以本轮 CHANGELOG 记录为准。此前浏览器访问未获许可，桌面/手机截图、真实点击与画布像素检查仍未执行。未部署网站、未构建或修改已有安装包。

## 公开基线

- 本仓库已将单一、脱敏的根提交发布为公开 `main`。旧的私有提交图、验证记录、二进制包和 Tag 只保留在 owner-only 私有归档中，不属于公开历史，也不会作为 Release 资产上传。
- 当前 alpha.2 已按所有者确认的预览验收范围发布：同源 Windows portable 和 macOS preview 具有 finalized receipt，8 项公开资源重下载哈希一致。Tag 已调整至共同来源，正式签名/公证、隔离 HOME 自动烟测及原生能力的未覆盖项保留；不启用旧 Windows NSIS/SignPath 交付或更新 Feed。
- public-preview 另有专用成品烟测：它从 DMG 挂载复制的 App 复核默认 finalized receipt 与 ad-hoc 签名、写入 quarantine，再通过 LaunchServices 的 `open -n -W -g` 和临时 `HOME` 启动；不允许直接执行 `Contents/MacOS`，也不允许传递 `INVOICE_HUB_DEV_STATE_ROOT`。为使 WebView 的 EventSource 不再拖住 Uvicorn，SSE 生成器会在结构化 shutdown 已被接受后结束。receipt gate 的聚焦契约与既有 smoke 契约已经就绪，但最终干净 Tag 的 DMG、Finder/Gatekeeper 人工交互和成品验收尚未完成。
- 历史净化的范围、私有备份和已完成的公开门槛见 [执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。公开仓库已启用 DCO、Dependabot、Secret Scanning、Push Protection 和私密漏洞报告；仍未创建 Release 或更新 Feed。

## 保留的产品边界

- 产品仍是 `v1 localhost`：单一活动 `TargetProfile`、文件为业务真值，SQLite 只保存任务、事件、设置与缓存。
- 共享核心继续使用 Python、FastAPI、Web、CSV/XLSX/JSON 投影和独立 monitor；不为桌面壳重写发票、成本、单据或做账逻辑。
- Windows 与 macOS 源码同仓，但成品必须严格按平台隔离。用户配置、日志、运行态和业务文件均不进入源码或发布输入。

## 已实现的共享能力

- PDF/OFD/XML 票头与成本明细提取、金额合法性保护、两维分类、同票纠偏、普通汇总与成本投影。
- 独立 monitor、后台 startup sync、文件事件合并、周期兜底、手改三字段保护和可诊断日志。
- FastAPI 页面/API、目录草稿、监控控制、结构化关闭、源文件预览、批量打印、皮肤安全边界和真实表格/TSV 复制。
- 做账 W8/W9 的本地文件真值、状态迁移预览、服务端执行校验、批次 manifest 与只读 dry-run 边界。
- macOS SwiftUI/WKWebView 壳保留为现有平台参考；它不改变共享业务逻辑，也不构成未来 Tauri 发布证据。

## `v0.3` 目标

- 使用 Tauri 2 负责窗口、托盘、单实例、原生面板、打印、后端生命周期、受限 Host RPC 和 updater。
- 固定 localhost 为 `127.0.0.1:8766`；未知占用明确失败，不能换端口或接入未知旧进程。
- 首版目标是 Windows 10/11 x64 NSIS 与 macOS 13+ arm64 DMG/更新归档。Intel Mac、Windows ARM64、MSI、App Store、云端和增量更新不在首版范围。
- host recovery/relaunch coordinator 已完成源码与 contract 接线：启用 updater 的 profile 可在 owned startup gate 释放后执行 Tauri 内置下载/签名验证、monitor 暂停、安装与平台重启；普通 development 与 internal-alpha 制品仍显式禁用 updater。L10-E 只新增一个精确 development recovery-smoke 变体，用不可达 loopback endpoint 和无验签能力的 key sentinel 激活 startup restore；它不是产品更新 profile。macOS arm64 隔离样本已证明 owned startup restore、marker 删除和 monitor 显式停止，但未运行任何真实 Feed、候选、下载、验签、安装或重启，因此不构成产品 updater 或发行验收。

## Tauri 2 生命周期边界与开发 `.app`

- `src-tauri/` 已提供固定 `127.0.0.1:8766` 的后端生命周期代码：未知占用失败、host 启动的 child PID/manifest/identity/OpenAPI 方法严格握手、单实例恢复窗口，以及仅在成功后创建 WebView。初次握手后严格读取 `startup_surface`，再以新的 HMAC challenge 和 identity probe 复核归属才 arm 授权：`desktop` 创建 WebView，`browser` 只由 host-only opener 打开固定 origin；托盘和第二实例重新打开既定 surface，desktop 关闭只隐藏窗口且不停止 monitor。裸源码 checkout 仍因没有经编译绑定的 manifest 以状态 `78` fail-closed；`scripts/dev/tauri_dev_app.py` 的普通 `stage/build` 只生成 updater-disabled schema-3 development manifest、允许清单内 core 与显式 venv launcher，并将 manifest/launcher SHA-256 绑定进本地 arm64 host。显式 `stage-recovery/build-recovery` 只为 L10-E 写入 Rust host 接受的精确不可安装 tuple；两种 build 都可使用绝对 pnpm 或绝对 Tauri CLI，且都不产生 release manifest、DMG、NSIS 或正式发布输入。
- internal-alpha 发行准备已落地并完成一次真实 arm64 构建：`scripts/dev/tauri_alpha_release.py` 从精确 Git snapshot 复制 allowlist core，校验并嵌入 Python 3.14.6 arm64 runtime，生成 schema-3 host manifest、launcher/build/package/runtime manifest 和 schema-4 receipt；`scripts/dev/verify_tauri_alpha.py` 对工作区副本的 App、DMG、哈希、布局、平台污染和 ad-hoc 模式做 fail-closed 校验并通过。完整 `source_commit` 与 `core_build_id` 留在 [L11-A 执行记录](docs/release/L11_A_INTERNAL_ALPHA_PLAN.md)和交付 receipt；该 artifact 明确为 `updater_enabled=false`、`public_release=false`。另以临时 HOME/state root 完成一次独立启动烟测：固定端口 health 到达 `ready`，身份匹配且未触碰真实 Application Support；该结果仍仅是内部评审证据，不是正式签名、公证、发布或最终用户安装证据。
- 归属证明使用后端独有的 256 位 secret、宿主每次新建 challenge 和 HMAC-SHA256 响应；secret 不发送给端口监听者。Host RPC token 只由 host 传给其直接启动的 Python backend，backend 启动时捕获并从 descendant 环境清除，绝不进入 WebView、Tauri command/event、API 响应或日志。私有随机 loopback listener 的 picker 面仅保留四种原生选择器枚举，更新命令面独立地仅为 `update_check/update_install`，WebView 没有 IPC 权限；host candidate 最多保留 300 秒，由 listener loop 主动清除并保存完整 cloneable `Update`，Web 只看到版本。同一进程同时具备 Tauri marker 与 configured private RPC 时，API、设置页和后台 timer 均通过 `check_for_updates` 进入 strict host preflight；只有非 Tauri/非 host 检查不获取 `_host_update_lock` 并保留 `UpdateService` 的 cache/ETag/nonblocking-busy 语义。host 检查锁竞争返回不持久化 busy 且不触发 metadata/candidate、不会清除既有 approval；install 锁竞争立即抛脱敏错误，不消费 approval 或发送第二次 RPC。host approval 必须来自同一 session 内显式携带 `Cache-Control: no-cache`、不带 ETag 的 fresh `200` body，缓存、ETag、`304`、离线或错误不授予 approval，随后才要求版本完全一致。安装接口只接受 `{}`，错误固定为脱敏 `503 Update installation unavailable`。Host updater metadata 与下载对象固定 5 秒时限。托盘 Quit 与 macOS 自定义应用菜单/Cmd-Q 共用 `app.exit(0)` 请求；应用菜单不使用会直达原生 `terminate:` 的 predefined Quit。Host 收到普通 `ExitRequested` 后才请求 `POST /api/v1/server/shutdown` 的 `keep_monitor` 结构化关闭并有界等待 owned child，API 错误或超时后显式 `kill + wait`，无法确认 child 已退出则阻止 host 退出；私有 update commit 期间普通 Quit 同样被阻止，只有 macOS 已准备 update relaunch 可跳过重复 shutdown。外部 AppleScript quit、Force Quit、SIGKILL 等可绕过该事件，不属于有序退出承诺。Rust picker 最多等待 120 秒，Python 保留 125 秒响应预算，四条 picker API 的私有错误固定为脱敏 `503 Native picker unavailable`。授权在 post-preference revalidation 后先 arm，随后由 100 ms 有界 child liveness watcher 撤销。Python 启动后捕获并清除 secret/token，monitor、后台同步和原生子进程不会继承它们。
- L10-R 只完成 source-level 的 Tauri monitor recovery primitive：`BackendHost` 在 tray/surface 成功、`app.manage` 前释放 startup gate，并把 generation、phase、health/owned/process PID 和 state scope 固定为 lifecycle lease。恢复事务会在每次 marker 或未来 bridge 操作前后复核该 lease；仅对已经 `running && ready` 的 owned monitor 写入标记，已有标记、corrupt/cross-scope 标记、未就绪 monitor、ownership 丢失和 bridge failure 都 fail closed。Unix marker store 以 opened-directory descriptor 加 `O_NOFOLLOW`/`openat`/atomic no-clobber `linkat`/`unlinkat` 固定最终操作；在该 L10-R 阶段其它非 Unix 平台返回 unavailable。下方 L10-C source-level slices 后续补充 Windows handle-relative/no-reparse marker store 与 Unix whole-operation protocol hardening。尚未接入 Host RPC、真实 monitor、下载、安装或重启，因此当前 `update_install` 的 candidate-consuming fail-closed 语义不变。
- L10-C 基础切片补齐四个可注入边界：固定 `127.0.0.1:8766` 的 `PythonMonitorRecoveryBridge`、只接收 `VerifiedUpdate` 的 pure `UpdateCoordinator`、共享既有 child/ownership/lifecycle `Arc` 的 cloneable `BackendLifecycleAuthority`，以及 Windows handle-relative/no-reparse marker store。该阶段的 source-level 结果和 Windows 编译限制保留为历史证据；它当时未接入 Host RPC/updater/startup restore，当前行为由下一条 L10-D 取代。
- L10-D 已完成 authenticated recovery/relaunch runtime coordinator 的源码接线。Backend 私有 secret 对三条 recovery 请求和精确响应做 fresh challenge/HMAC-SHA256 双向绑定，Python 以 128 个 challenge 的进程内有界集合拒绝重放并要求空 body，普通 bridge 调用不变。Updater 只在 startup gate 释放、`BackendHost` 注册后激活，从 `expected_identity.runtime_dir` 打开平台 marker store并先恢复；恢复失败保留 marker、WebUI/backend 和诊断，同时阻断 updater。`update_install` 原子消费 fresh 完整候选，worker 在 execute/cancel latch 后等待，精确 `{"ok":true}` 写入并 flush 后才执行 download+verify -> pause -> install -> relaunch；writer/spawn/latch loss 进入 `CommitLost` 且无副作用。Windows installer callback 先确认 managed backend 终止，macOS 安装后先停 backend、标记 relaunch prepared、再 `request_restart()`。这些是源码和 contract 证据，不是任何真实 Feed、monitor、installer、restart 或平台运行证据。
- L10-E 把运行验证限制为一个不可安装的 development recovery-smoke profile：Rust 只接受固定 `https://127.0.0.1:1/invoicehub-recovery-smoke/latest.json` 与明确写着 `NOT A SIGNING KEY` 的 base64 sentinel，且 enabled updater 对象只能有三个精确字段。`scripts/dev/tauri_recovery_smoke.py` 复核 App plist、manifest/launcher/build 身份，再创建临时 HOME/state/runtime/watch、关闭自动更新检查、预置同 scope marker；运行时只读取 health/status，并在恢复后调用 monitor stop，HTTP allowlist 不含 update 或 bridge start。预检修复了 Tauri 实际 `CFBundleExecutable=invoicehub-desktop` 的绑定；首次启动又在 backend 前暴露并修复 development overlay 缺少 updater 配置对象的问题，空 `pubkey` 占位不含 endpoint 或验证权限。离线重建后的 macOS arm64 样本以 build ID `8e40363fa673017e993727cf3f5dec347b24927c5ce1a0a4b945601737621873` 恢复 owned monitor 到 `running && ready`，删除 marker、显式停止 monitor并清理 backend/monitor PID、固定端口与临时目录，runner 报告 `update_requests=0`。
- `scripts/dev/tauri_version_sync.py` 从 `src/invoice_hub/version.py` 同步并校验 Cargo、Tauri 配置和 npm 的产品身份；`pnpm-lock.yaml` 与 `src-tauri/Cargo.lock` 已锁定对应 JavaScript/Rust 依赖。
- `rust-toolchain.toml` 固定 Rust/Cargo `1.85.0`，`.cargo/config.toml` 固定 MSRV-aware resolver。Windows/macOS 的 `doctor/bootstrap` 只诊断或按显式 `--install-js` 安装已锁定的 JavaScript 依赖，绝不安装 Rust、证书、Xcode 或 Visual Studio。
- 固定 endpoint/method/origin 本身仍不是 ownership proof；L10-D 的 host recovery 请求必须持续使用 backend-private secret 的 fresh challenge/HMAC 双向认证和 lifecycle 前后 revalidation，不得向候选固定端口发送 bearer secret，也不得把该认证 secret 扩大到普通页面 bridge 或 Web API。
- 在不修改用户级 Rust 的官方隔离环境中，已解析精确 Tauri crate、审查 lock，并通过 HMAC、固定端口、身份拒绝、OpenAPI 方法、post-preference revalidation、Host RPC 撤权/超时、tray/browser 与 L6 manifest/candidate/order 的聚焦验证。L6-R 另在同一 Rust 1.85 离线环境通过 13 个 library 与 5 个 lifecycle integration tests；干净隔离 Python 环境以项目精确 runtime pins、`pytest==9.1.1` 和 `httpx2==2.9.1` 运行了 31 个 L6-R API/Host RPC/metadata/documentation contracts，并将 `DeprecationWarning` 视为错误。L6-RR 在同一隔离 Python 环境以相同 warning-as-error 门禁运行更新服务、Host RPC 和文档契约，共 40 项通过；L6-RRR 的 42 项历史结果已由 L6-RRRR 的 44 项证据取代，覆盖 hosted strict public preflight、non-host bypass、检查锁 immediate-busy/approval 保留，以及 install 锁 immediate-error/approval 保留/无第二次 RPC；这些数字是对应历史切片，不冒充产品运行。当前 L10-E 收尾另通过 77 项聚焦 Python Tauri/Host RPC/文档契约、锁定 Rust 格式与离线 desktop/tests `cargo check`、版本同步、`compileall` 和 diff whitespace 门禁，并完成上条隔离 startup-recovery 样本。详细命令、通过数量和未覆盖边界见 [Tauri 2 执行计划](docs/release/TAURI2_EXECUTION_PLAN.md)。
- L6-RRRRR 以 45 项通过取代上述 44 项作为当前 host-lock 竞争证据：该历史样本未证明 contended busy 在返回前不会进入 `append_event` 的 SQLite 写入，也未覆盖 private `update_install` 异常后的 `finally` 锁释放。该结果仍不扩展为 Rust、产品进程或真实 updater 证据。
- L8-S/L9 已通过受控 macOS arm64 development `.app` 的组装、资源、固定端口、health/background、首页/静态资源、`desktop_available=true` 和默认 desktop 验证。开发 manifest 使用 schema 3，显式 venv launcher 与 manifest 原始字节均受 SHA-256 绑定；development profile 必须显式给出已存在的绝对 `INVOICE_HUB_DEV_STATE_ROOT`，host canonicalize 后要求它与 bundle/core 双向不包含，release、缺失或相对覆盖 fail-closed，且该变量不会传给 Python child。外部 AppleScript quit 曾绕过 shutdown POST 并留下 stale `ready`，该不受支持路径的有序退出结论仍撤回；P1-Q 随后从 clean source commit 重建并向前台 app 发送真实 Cmd-Q，确认 shutdown POST 200、`server_state=stopped`、monitor 保持停止、host/backend 退出、8766 释放且 server PID 清理。打开的 SSE 连接使 host 在 stopped state 后使用了显式 `kill + wait` 兜底。真实用户 Application Support 目录未被读取或写入，`.app` 及 staging/target 都未加入 Git。最初 tray 初始化因 16-bit RGBA `icon.png` 失败，已改为 8-bit RGBA，并用 PNG IHDR 回归锁定同类问题。该 development profile 明确禁用 updater，不证明原生 picker、browser/tray、单实例、打印、下载/验签/安装或任何发布流程。
- P1-R 接管复核已通过锁定 Rust 格式、16 项 library、6 项 lifecycle integration、desktop binary check、版本同步、聚焦 Python contracts、`compileall` 与 diff whitespace 门禁，Rust 编译无 warning。复核删除了 fail-closed 后不再可达的 monitor-stop/install-success 片段，没有用 dead-code allow 掩盖半实现。该结果只允许形成 DCO 开发提交并从 clean commit 重建一次 development `.app`，不扩大为真实 updater、安装器或平台发布证据。
- P1-RR 进一步修复了两个先前未被代表样本覆盖的私有边界：Python Host RPC 对 private loopback listener 的 bearer 请求显式禁用 `HTTP_PROXY/http_proxy` 等环境代理；development state root 以整个 macOS `.app` 容器为 containment boundary，`Contents/state` 这类不在 `Resources` 内的 sibling 也 fail closed。16 项 Rust library、6 项 lifecycle integration 与 16 项 Host RPC Python contracts 通过；这只允许继续受控开发，不构成真实 native panel、updater、安装器或平台发布证据。
- P1 setup cleanup：`BackendHost::launch` 后的 tray、desktop window 或 browser surface 初始化若失败，host 会在返回原始 setup error 前调用既有 `keep_monitor` shutdown，并在失败/超时时使用显式 `kill + wait`；无法确认 owned child 退出时 setup 保持阻塞并定期重试，child mutex 或 `try_wait` 错误也不得被当作 graceful exit，绝不把 cleanup error 交给 `Drop` 后退出。backend 与 `startup_surface` 只有在全部可失败初始化成功后才会 `app.manage`；L10-D updater 激活还必须发生在 manage 之后。该修复与当前 coordinator 源码接线都不构成真实 updater、安装器或平台发布证据。

## 发布与验证规则

- `src/invoice_hub/version.py` 是版本、协议、通道、公开链接和 package ID 的单一真值。Cargo、Tauri 与 npm 版本只能由同步/校验脚本派生。
- 每项实验必须先记录假设、会改变的决策、最小样本和停止条件。相同机制仅保留一个代表样本；每个 RC 最多一次完整回归。
- 公开前已运行一次候选内容审计和一次保留 refs 全量审计。后续文档或仓库设置变更不刷新该审计；真实命中才隔离或替换，并按受影响机制复核。
- 每个平台最终 RC 只做一次安装、启动、目录选择、托盘和更新烟测；修复后只重跑受影响类别。

## 尚未完成

- development `.app` 烟测覆盖 schema-3 development assembly、固定端口 owned backend、health/background、首页/静态资源、desktop 默认值，以及一个真实 Cmd-Q 的结构化退出样本；internal-alpha 另完成了 App/DMG/receipt 独立 verifier 和一次隔离启动烟测。tray 点击、外部终止和其它平台退出机制没有因此获得同等结论。原生打印、原生 picker、browser/tray、真实单实例与错误端口、合法/篡改更新、真实下载/验签/monitor 停止、安装/重启和其余决策场景仍未在桌面运行环境验证；development/internal-alpha artifact 均不构成平台安装验证。
- 公开 Release、GitHub Pages Feed、正式 Windows 签名、macOS Developer ID/公证和最终用户安装烟测均尚未进行。
- 真实业务做账迁移、审批、导出和外部账套操作必须在用户当回合明确授权后另行执行。

## 验证范围说明

本文只描述当前源码能力与后续范围，不代表对任何历史二进制、真实目录、真实发票、正式 Windows BAT、系统原生面板或正式安装包作出新的验证声明。
