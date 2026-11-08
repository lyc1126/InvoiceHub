# 成本明细与开票参考规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：成本明细、金额校验、成本三件套、加价率与已开快照。
- 代码与验收定位：projections/cost_analysis.py、projections/costs.py；数据算法第 8—9 节、任务导航第 5 节。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-costs) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

## 明细证据与校验

- 成本发票明细解析必须优先使用结构化或坐标来源：PDF 使用坐标/表格结构还原，XML 使用结构化明细节点，OFD 优先使用 `CustomTag.xml` 的明细字段引用，必要时才使用 `Content.xml` 文本对象坐标；不能只靠纯文本行号、抽取顺序或文件名硬拆。商品名跨行、OFD `item` 多段拆分、金额/税额先于数量/单价出现等情况必须在结构层或坐标层归位。
- PDF 业务版式成本明细必须先识别可靠表头，再按行基线映射列；建筑服务发生地/项目名称、旅客/货运专属列、不动产权证号等只能用于版式定位，不得挤入金额、税率或税额。无可靠表头时不得猜明细；同票候选优先选择除税金额和税额均校验通过的来源。
- 成本发票校验差异必须显式进入结果和页面，不得只写日志或在解析阶段吞掉。

## 产物与开票状态

- 成本分析 v1 产物固定写入当前选择器 `watch_dir`：
  - `watch_dir/成本发票明细.csv`
  - `watch_dir/成本发票汇总.xlsx`
  - `watch_dir/成本开票状态.json`
- `workspace` 只保留普通汇总与运行状态工作区；成本页面和 API 不得让用户误以为成本汇总表在 `workspace`。
- “刷新”和“重新汇总”语义必须分开：刷新只重新读取当前状态，不生成文件；重新汇总才扫描当前发票目录并重建普通汇总与成本分析。
- 成本分析表“开票参考”sheet 与 `/costs` 页面“开票参考”标签必须以当前成本明细为来源，按 `发票代码(**内文字) / 内部项目名称 / 规格型号 / 单位` 汇总；不能输出销售方和涉及发票号码；开票加价率不再固定，默认 `8%` 只作为行级 fallback，每条开票参考行可在 `watch_dir/成本开票状态.json` 中单独保存 `reference_markup_rate/reference_markup_rate_percent/reference_markup_locked`，勾选后的批量加价率操作只作用于已选行。API 必须持续暴露兼容字段 `reference_markup_rate`，但页面不得再提供顶部全局加价率设置。
- 开票参考按本公司税务设置计价：`watch_dir/成本开票状态.json` 顶层 `tax_profile = {taxpayer_type: general|small_scale, output_tax_rate, output_tax_rate_percent}`，缺失或不可读时按一般纳税人、13%，旧状态文件结果不变。成本单价 = sum(金额(除税) + 不可抵扣税金) / sum(数量)：小规模纳税人全部税金计入；一般纳税人只计入“发票校验”中已确认为增值税普通发票且非旅客运输的税金，类型未确认的按不含税计并在“成本口径”标注待核对，不得因识别缺口抬高参考价。参考税金与含税单价用 `tax_profile.output_tax_rate`。工作簿、`costs.py` 的读取与保存、`page-costs.js` 草稿联动四处必须同一公式；任何改写状态 JSON 的路径（含重新汇总合并工作簿状态）都必须保留 `tax_profile`。改税务设置不重算已开快照；页面有未保存的开票参考草稿时不允许保存税务设置。
- 开票参考的销项比对（COST-03）：只有手动“重新汇总”读取 `outbound_invoice_dir`（monitor 重建沿用上次汇总），解析结果与文件签名缓存只写 profile 工作区，不写 `watch_dir` 或开具目录。开具目录是全局设置，必须只采用销售方属于本目录进项购买方的发票，并显示被排除张数；开具目录与 `watch_dir` 重叠时不读取。同票多格式按发票号只计一次，红字票按负数冲减。手填 `已开数量` 始终是保存值：比对只显示销项数量、实际加价率（销项除税单价 / 成本单价 − 1）与“一致 / 销项多 / 手填多 / 销项超过进项”，“按销项更新”只写页面草稿，保存仍走既有快照语义。全部已对上品目（至少 3 个）实际加价率相同时只提示留存定价依据，不改金额。读取失败只记提示，不使重新汇总失败。比对以“库存数量与票面一致”为原则：开票中价格变动属正常，实际加价率只中性展示、不因偏离参考价告警；数量差异必须醒目（待更新为警示色，销项超过进项为危险色），面板按全部行统计数量一致 / 待更新 / 销项超过进项 / 无销项。`/costs` 开票参考表的数量列（数量、已开、销项、数量比对、未开、开票状态）必须连续排在价格列之前；草稿联动按列 key 定位单元格，列顺序与 `#referenceTable` 列宽必须同步。
- 开票参考状态保存时必须按同一汇总键持久化到当前 `watch_dir/成本开票状态.json`，并锁定当次 `已开数量` 与已开参考金额/税金/价税合计快照。后续新增同键发票只能增加未开部分，不能让已开金额随新汇总漂移。
- 底层 `成本发票明细.csv` 必须保持一条明细一行、票面字段不留空；工作簿和页面可以合并展示同票票面字段，但不能改变 CSV 逐行口径。
- 调整成本字段时必须同步更新工作簿 sheet、`GET /api/v1/cost-analysis`、`POST /api/v1/cost-analysis/reference-status`、`/costs` 前端和契约测试。

## API 与页面契约

- 分页读取缓存仅作可重建投影：完整四标签同代际原子发布，读取繁忙时保留上次完整结果而不取消原写锁；首次无完整结果只展示临时明细，停止/失败不能把临时结果升级为可编辑状态。
- 分页保存须校验页面的 target_id/revision，不能将旧草稿静默套用到新汇总；跨页选择、数量/加价草稿和全量 TSV 复制语义保留，复制过程中代际或目录变化须中止。旧完整 API 保持兼容。

- `/api/v1/cost-analysis` 必须持续返回：
  - `watch_dir/source_dir/target_id`
  - `output_detail_csv_path`
  - `output_summary_xlsx_path`
  - `reference_status_path`
  - `invoice_reference`
  - `reference_status_stats`
  - `reference_markup_rate`
  - `reference_tax_profile`（纳税人类型、销项税率、是否已保存、提示）
  - `outbound_summary`（开具目录、读取时间、读取 / 采用 / 排除 / 无明细张数、对上与未对上品目、提示）
  - `sync`
- `/costs` 页面中与工作簿 sheet 对应的标签必须互斥显示；新增或调整标签时必须检查 `hidden/aria-selected/aria-hidden`、`.cost-view[hidden]` 和复制 TSV 口径。

页面交互同时遵守 [页面规则](WEB_UI.md)，票头取证同时遵守 [提取规则](INVOICE_EXTRACTION.md)。
