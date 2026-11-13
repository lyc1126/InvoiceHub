# InvoiceHub 注释与设计原因地图

## 2026-11-13 目录列表与共用原票预览（WS-01 第三阶段）

- 目录预览传完整选择、保留同票各格式，金额家族去重不能复用为预览去重；100 个文件名 / 12 页缩略图是渲染窗口，不是队列上限。守护：`directory-preview.spec.ts` 的多格式与 101 文件用例。
- XML `response.text()` 后再检查读取代际：响应头先到而正文很慢时，光在 fetch 后检查仍会让旧文件正文覆盖新文件。关闭取消读取；持续失效只立即重建一次，避免请求循环。守护：迟到 XML 与持续 410 两项用例。
- 最后一页按钮禁用可能让焦点回到 body；窗口 Esc 监听只处理具有可见布局的面板，关闭时移除监听，避免缓存的隐藏标签响应。浏览器实测发现，组件用例与 PDF 翻页后的浏览器复验守护。
- 日期排序复用后端且在分页前执行；列表与全选只接受当前代际。监控身份变化会使可操作的旧首页身份失效，须重读并清除选择；普通公司对象刷新仍不重载。守护：排序竞态 / 监控切换用例，以及既有只局部更新标签和双击刷新测试。

## 2026-11-11 发票标签（WS-06）

- `company_views.py::directory_invoices` 先复制首页服务返回的 payload 与每一行再附加公司字段和 `tags`：活动目录的行来自首页服务，原地修改会让首页响应带上不属于它的字段。守护：`test_active_directory_hands_over_to_the_live_invoice_list`（断言首页响应没有 `tags`/`tags_error`）。
- 标签定义放本机、标记放公司资料夹：标签的含义是使用者的习惯，标记是对某家公司发票的判断，后者要随资料走。删除定义时逐个公司清除；资料夹离线时读侧忽略未知 id，避免删掉的标签又冒出来。守护：`test_deleting_a_tag_removes_its_marks_everywhere`。
- `CompanyDirectories.vue::toggleTag` 只局部更新该行：重新加载列表会重置页码与滚动，用户对“点一下就抖”敏感。守护：前端用例断言打标签后没有再请求列表。

## 2026-11-11 公司项目汇总（WS-03）

- `company_projects.py::ProjectAssignmentStore`：人工项目归属存在公司资料夹根目录而不是 `runtime/`，资料夹换机器或换人接手时人工判断随资料走；它和 `成本开票状态.json` 一样只在用户保存时写，重新汇总不读写。守护：`test_manual_assignment_is_saved_in_the_company_folder_and_survives`。
- 损坏的 `项目归属.json` 拒绝读写而不是当作空文件：当空文件覆盖会一次丢掉全部人工归属。守护：`test_bad_requests_and_a_damaged_file_are_refused`。
- 一张票备注出现两个项目名称时不择一：选哪个都是猜，列入未归属等人工指定。守护：`test_projects_come_from_remarks_and_manual_values_win`。
- `build_project_summary` 与 `build_invoice_ledger` 交叉校验：项目页和账簿页对同一批票必须给出同一个合计，否则用户无法判断哪个对。

## 2026-11-11 往来核对（WS-07 第 4 步）

- `company_settlement.py::_party_index`：对账单“备注”列会截断长户名，只认唯一命中的 ≥4 字前缀；命中多家时不归属，因为把付款记到错误的单位比留着待查更难发现。守护：`test_a_name_that_fits_two_parties_is_not_assigned`。
- 组合匹配只接受唯一一组：两组以上发票都能凑成同一金额时任选一组就是猜。守护：`test_more_than_one_set_of_invoices_is_left_unmatched`。
- 红冲抵销先于收付款匹配：否则余额已经为 0，被冲的蓝字票仍显示“未付”，页面自相矛盾。守护：`test_red_letter_invoices_reduce_the_balance_and_unreadable_ones_are_listed`。
- `party_balance` 与 `flow_accounting` 从原始发票、流水清单复算，而不是用往来单位行自己的数：同义反复的校验永远成立，发现不了漏算。守护：上述各用例的 `_ok`。

## 2026-11-13 通用凭证导出配置（BK-01）

- 只替换写文件一步，业务判断仍只在 `jierui.export`：整月拦截、重编号、重复跳过若在每个格式里各写一份，会出现某个格式漏拦的情况。已导出签名不分格式：同一凭证换格式再导一次会被跳过，避免同一凭证进两个账套。守护：`test_an_exported_voucher_is_skipped_in_any_other_format`。
- 捷锐黄金测试对比引入导出配置之前的导出代码的输出（冻结为 `tests/fixtures/jierui_export_golden.json`）：唯一实测过能导入的格式不能因重构改变任何一个单元格。守护：`test_jierui_output_is_unchanged_from_before_the_profiles`。
- 其他软件只标“实验”：各家导入模板是私有格式，只有用友 T3/U8 有公开字段规范，柠檬云表头来自第三方仓库；未实际导入前不能当作可用。按编码引入的格式没有编码时留空，不用名称顶替（会被当作错误编码导入）。
- 校验提示改为“请确认账套里已建档”：同一提醒现在服务所有格式。

## 2026-11-13 工资社保页面（WS-05 第三阶段）

- 只在用户确认后写 `申报数据.json`，且写入的单位 / 个人部分由后端从所确认的险种行求和：草稿计提只读这两个数，页面传来的合计不被信任。守护：`test_confirming_writes_the_month_into_the_tax_file_and_keeps_its_other_keys`、`test_a_confirmed_month_is_accrued_by_the_generated_draft`。
- 整文件按 SHA-256 revision 重写并保留其他键：`申报数据.json` 同时存月度增值税、季度税费、已抵扣进项发票，由人工维护，社保确认不能冲掉它们；文件损坏时拒绝而不是当作空文件。守护：`test_confirming_needs_a_readable_tax_file`。
- PDF 按 token 流识别、每行恰好 11 个数值：文字层可能整行一行或一格一行，按行切会漏读；数值个数不对就跳过，不猜列。守护：`test_reads_the_same_table_from_a_text_pdf` 两种排版。
- 图片不识别：发布包没有 OCR（AGENTS.md 不做本地 OCR 打包版），用户 2026-11-13 决定本轮不支持图片。
- 姓名、证件号默认脱敏返回：页面、截图和诊断默认不出现完整个人信息，只有显式请求时返回原值。

## 2026-11-13 属期文件夹核对与移动文件（WS-05 第二阶段）

- 文件夹名只作提示：期间仍只按内容判定（“5月”文件夹里的空导出不按文件夹名推断所属期的规则不变），否则改名或放错一个文件夹就会改变抵扣与对账结果。守护：`test_check_compares_the_content_period_with_the_folder`（空导出为 unknown）。
- 移动照删除流程：先计划、确认时复核签名，逐文件 fsync 意图后再改名，响应丢失只读日志；移动不能像删除一样从回收站撤回，同名不覆盖、新文件夹只能是 `YYYY-MM`。守护：`test_a_confirmed_move_creates_the_period_folder_and_never_overwrites`、`test_a_file_changed_after_the_plan_is_not_moved`。
- 对账单逐个文件解析：对账单只记录文件名，两个属期文件夹里可能有同名文件，按名字找回会移错文件。
- 与监控目录重叠时拒绝：监控目录内的文件移动会被看作删除 + 新增，手改字段按路径保存，需要走监控自己的流程。

## 2026-11-13 改记入期（WS-05 第二阶段）

- 调整只存在公司资料夹的 `记入期调整.json` 并由 `build_drafts` 应用，而不是改审核表单元格：增值税、库存加权、待认证转出与月度核对都按 `book_month` 计算，只改单元格会让这些结果与凭证不一致；命令行读同一份文件，两边结果相同。守护：`test_rebooking_an_invoice_moves_its_voucher_and_the_cli_follows`。
- 抵扣月份不随记入期改变：能否抵扣是税务事实（开票月、勾选与申报），记入期是账务选择；记入早于可抵扣月份时挂待认证，到可抵扣月转出。
- 范围前开票、记入本草稿的票全部按“已在当月购销中计算”扣出首月期初应有数量（原来只扣补记到首月的进项）：否则调整进来的票数量重复计算。
- 调整文件损坏时生成失败而不是忽略：静默丢掉人工调整会让凭证回到错误的期间。

## 2026-11-13 页面生成草稿与沿用审核（WS-05 第二阶段）

- 页面生成直接走 `prepare` + `write_review_xlsx` + 命令行说明页：两套入口只要有一处不同，页面审核过的表就不是命令行会导出的表。守护：`test_the_page_writes_the_same_workbook_as_the_cli`。
- 沿用审核按来源配对、按导出签名判定：凭证号会因前面增删凭证而变，按号配对会把审核挂到别的凭证上；签名与重复导出判定同一口径，签名不变才说明导出内容没变。银行流水的 row_id 是对账单序号，必须带借方合计复核。守护：`test_regenerating_backs_up_and_carries_unchanged_reviews`。
- 覆盖前先完整备份、现有表读不了就不覆盖：审核表是用户人工审核的成果，重新生成不能静默丢掉。

## 2026-11-13 凭证草稿页面导出（WS-05 第二阶段）

- 页面导出直接调用 `jierui.export`，不另写：整月拦截、按月重新编号、已导出跳过与科目习惯学习都在那里，复制一份就会与命令行漂移。守护：`test_export_writes_the_approved_vouchers_like_the_cli_and_skips_a_repeat`（用导出写出的文件核对凭证号与制单人、第二次跳过、通过但不合格时整月不写）。
- revision 在导出锁内复核：导出写的是用户审核过的那一版，另一处保存或重新生成后必须先刷新。不开放“允许再次导出”：响应丢失后再点只会跳过已导出的，不会重复导入。
- 导出按钮在有未保存改动时禁用：导出读文件，页面上未保存的修改不会进入导入文件。
- 账套“已用到的号”输入框 `v-model` 在 number 输入上给出数字，不能当字符串 `trim()`（前端测试发现）。

## 2026-11-13 凭证草稿的所属期与记账日期（WS-05 第二阶段）

- 移到另一个月的凭证必须重新编号：`read_review_xlsx` 与导出都按“月份 + 凭证号”分组，沿用原号会和目标月的同号凭证合成一张、借贷与审核都会错。号码取目标月已占用号（不含本次移出的）与本次已分配号的最大值 + 1。守护：`test_moving_a_voucher_to_another_month_renumbers_it_and_dates_outside_block_approval`。
- 记账日期不在所属期内仍可保存、但不能审核通过：用户可能分两步改（先改日期再改月份），只在审核时由 `validate` 拦截，与导出口径一致。守护：同上。

## 2026-11-13 比较记录的原票（WS-04）

- `preview` 只附给监控目录、非临时列表的记录，且身份取自该目录当前的首页列表：`preview-jobs` 按当前 watch_dir 重新校验 `invoice_key + source_path`，其它目录的身份是另一份投影的位置，接上去要么被拒、要么指错文件。守护：`test_only_the_monitored_folders_records_open_the_original_invoice`（用附带的身份真实创建预览作业）。
- 图片出错只重建一次：页面渲染失败（不是过期）时无限重建会反复占用渲染与内存上限。守护：`companies.spec.ts` 的 “opens a monitored record's original invoice…”（410 后重建并保留第 2 页、关闭后不再续租）。
- 窄屏 `.grid` 设 `position: relative`：表头里绝对定位的 `.sr-only` 以初始包含块定位，会逃出表格的横向滚动把整页撑宽 60px（浏览器验收发现，勾稽与同号检查标签都受影响）。

## 2026-11-13 同号检查（WS-04）

- 同号不一律判为重复：两家公司一方开具、一方取得的是同一笔交易的两端，标为“双方同一张票”；其余同号才是“疑似重复”，且只给人工核对，不下结论。守护：`test_issued_on_one_side_and_received_on_the_other_is_one_transaction_across_companies`。
- 有勾稽关系的同一公司组合拒绝做同号检查：否则一组本应做进销存 / 往来核对的目录会被降格为号码比对，掩盖勾稽差异。守护：`test_same_number_api_across_folders_and_companies_without_writing`。
- 每边按 `selection_family_key` 合并：与发票账簿、首页勾选同一口径，同一张票的 PDF / OFD / XML 不会自己和自己“同号”。守护：`test_formats_of_one_invoice_count_once_and_shared_numbers_are_listed`。
- `tabId` 只在有第二个对象时追加字段：已有标签 id 保持不变。

## 2026-11-13 多行批量打标签（WS-06）

- 批量菜单打开时从 `GET .../invoice-tags` 读当前标记，而不是用列表行的 `tags`：勾选可能跨页（全选筛选结果），未加载页的标记页面不知道；保存仍是“整张号码的完整标签列表 + revision”，冲突时重新读取，让用户按现状再点一次。守护：`companies.spec.ts` 的 “tags every selected invoice…”。
- 勾选里额外保存发票号码只供批量打标签，传给选择条前剥掉：`selection-summary`、`print-jobs`、`trash-jobs` 的请求体保持 `invoice_key + source_path`。守护：同上（断言合计请求体）。

## 2026-11-13 凭证草稿审核（WS-05 第一阶段）

- 页面直接改命令行生成的审核表，而不是另存一份：`voucher_cli export` 只读这份工作簿，另存会出现两份草稿、导出拿不到页面的修改。守护：`test_edits_write_back_into_the_same_cells_and_unbalanced_vouchers_cannot_be_approved`（用导出自己的 `read_review_xlsx` 读回，并断言其他工作表仍在）。
- 审核通过只在后端用导出的 `jierui.validate` 判定，任一不过整批不写：页面的实时借贷合计只是显示，另写一份校验会与导出口径漂移；部分保存会让页面与文件不一致。守护：同上与 `test_voucher_draft_api_lists_reads_and_reports_blockers`（`error.details` 逐张原因）。
- 改过的已通过凭证清空审核：否则改了分录仍带旧“通过”被导出。保存带文件 SHA-256：命令行重新生成或别处改过后，旧页面不能覆盖。守护：`test_editing_an_approved_voucher_needs_a_new_review_and_stale_saves_are_refused`。
- 改科目编码时同步或清空表内科目名称：打开工作簿的人看到的名称不能与编码不符。金额以 Decimal 写回，与生成命令一致。守护：`test_an_edited_code_refreshes_the_sheet_name_and_malformed_saves_are_refused`。

## 2026-11-13 目录标签的勾选操作条（WS-01 第二阶段）

- 勾选合计不在 Vue 里算：同票家族去重与三项金额的冲突 / 缺失规则只在后端 `selection-summary`，前端再写一份就是两套口径。守护：`companies.spec.ts` 的 “selects invoices on the monitored folder…”（断言请求体只含 `invoice_key + source_path`）。
- 删除确认的响应丢失时只读执行日志：重新确认可能重复移动文件。删除结果放在列表而不是操作条里：完成后清空勾选会卸载操作条，部分完成的逐文件结果不能随之消失。守护：同上（确认只发一次、随后 GET 日志、结果面板仍在）。
- `DirectorySelectionBar` 的删除计划 `trash` 必须在立即执行的 `watch` 之前声明：否则组件一挂载就抛错。

## 2026-11-11 比较明细与并排原始记录（WS-04）

- 计算过程 `steps` 在后端用 `cost_of_sales` 实际用到的数值生成（销售成本写成“金额 × 数量 ÷ 可售数量”而不是“数量 × 舍入单价”）：前端拼式子会因舍入与真实结果差几分，等于另写一份算法。守护：`test_categories_point_at_their_invoices_and_explain_the_month`。
- 类目与并排记录共用后端 id，前端只过滤：类目归属（品类、往来单位、所属期）是后端判断，页面按名称或金额去猜会与核对结果不一致。守护：`test_parties_and_matches_point_at_their_rows_side_by_side`、抵扣用例的 `record_ids` 断言、`companies.spec.ts` 的 “opens a category's calculation…”。

## 2026-11-11 工作区外框（WS-01）

- 首页标签用 `v-show` 常驻、以 `id#refresh` 为 key：关闭才丢缓存，双击 `hi.` 只让当前标签的 `refresh` 加一而重建，其他标签不受影响。守护：`app.spec.ts` 的 “opens sidebar nodes as tabs once…” 与 “refreshes only the active tab…”。
- `DirectoryPanel` / `DirectoryInvoices` 的 `watch` 用 `公司 id/目录键` 字符串：公司清单刷新会换成新的 company 对象，返回数组的 getter 每次都“变化”，会让列表无故重载。守护：“refreshes only the active tab…”（隐藏的公司标签不重读）。
- 首次进入只自动打开一次监控中的公司（`seeded`）：用户全部关闭后停在起始页，刷新公司清单不得把标签重新打开。守护：同上第一条。
- 侧栏的比较组合只来自 `relations.ts`（与后端 `COMPARE_RELATIONS` 相同的四组），前端不计算任何结果；不同公司或无勾稽关系时禁用并说明，后端仍会拒绝。守护：“compares two folders of one company…”。

## 2026-11-11 进销存（WS-07 第 4 步）

- `company_inventory.py` 调用 `bank.vouchers.cost_of_sales`，不另写加权平均：页面上的销售成本必须与做账草稿的结转同一算法，两处结果才能互相核对。守护：`test_month_end_weighted_average_rolls_stock_forward_and_merges_names`。
- 逐月从最早月份滚到最晚月份（包括没有发票的月份），`start/end` 只筛选显示：从范围首月重新按 0 起算会丢掉之前的结存。守护：`test_range_starts_from_the_rolled_forward_stock`。
- 库存按品类（`goods_family` + 单位）而不是规格计算：账套库存商品按品类设明细，只有同一粒度，账套读回的期初才能落到对应的行；规格行只细分购销，不分摊期初与成本，否则规格成本之和会因舍入与品类不符。守护：`test_specs_are_a_breakdown_of_the_category_row`、`test_opening_comes_from_the_book_readback_per_category`。
- 账套期初只在读回包含期初月份之前的月份时采用，并把这些月份的发票移出滚动：账套余额已经包含它们，再计一次就重复；读回不足时按 0 起算并写明原因，不拿半截读回当期初。没有单位的分录不猜单位。守护：`test_book_readback_without_earlier_months_keeps_the_zero_opening`、`test_unit_less_book_line_is_not_guessed_onto_one_of_several_units`、`test_broken_or_incomplete_books_never_stop_the_check`。
- `projections/costs.py::read_only_inputs`：比较的两个目录多半不是监控目录，`snapshot` 会刷新 schema、重写工作簿，读取就会改动用户目录。守护：`test_compare_api_reads_both_projections_without_writing`（前后文件 mtime 不变）。
- `_qty`：`cost_of_sales` 的零值带两位小数，数量直接 `str` 会变成“5.00 吨”；数量要保留自己的精度（2.345 吨），不能按金额格式化。
- `CompanyInventoryResult.vue` 的逐月明细放在品目下方整行展开：嵌在“说明”格里的子表在窄屏会被截断。

## 2026-11-11 抵扣核对（WS-07 第 4 步）

- `company_deduction.py::parse_deduction_workbook`：当期没有勾选时，电子税务局只导出一格“发票清单”，文件里没有所属期。按文件夹名（“5月”）推断会把用户随手起的名字当成事实，所以只报告为“空清单、所属期未知”。守护：`test_empty_and_unrecognised_files_are_reported_not_guessed`。
- `_amount`：清单金额是 Excel 浮点数，必须经 `str()` 的最短表示再到 Decimal，直接 `Decimal(float)` 会带出二进制尾数，合计行核对会差几厘。守护：`test_parser_reads_period_rows_and_total`。
- `read_deduction_lists` 按相对路径命名：每月导出都叫 `用途确认信息.xlsx`，只给文件名时用户分不清是哪个月。守护：同上空清单用例断言 `5月/用途确认信息.xlsx`。
- `build_deduction_check` 的“目录有、清单无”只列专票，并给出所属期不早于开票月的已有清单：有这样的清单说明“该勾未勾”，没有则只是“还没有清单”，两者不能混为一谈；普票不能抵扣，只计数。守护：`test_lists_and_invoices_are_matched_by_number_and_period`。
- `company_views.py::COMPARE_RELATIONS`：算法由两类资料的关系决定，不由请求决定；没有勾稽关系的组合直接拒绝，避免页面给出拼凑的关联。守护：`test_compare_api_refuses_unrelated_pairs_and_bad_months`。

## 2026-11-11 公司账簿的银行流水（WS-07 第 3 步银行部分）

- `company_bank.py::BankFlowReader.read`：目录列不全（超过 2,000 个 PDF 或 2 秒）时整体拒绝汇总。只汇总列出来的那部分，会让缺掉的月份看起来像“没有收支”。守护：`list_bank_pdfs` 的完整性返回与 `test_receipts_are_recognised_but_not_parsed`。
- `_bucket`：没有对账单的月份不给余额（`null`），任一缺月让该期校验不成立。用 0 或上月期末补齐会让缺月与“当月无交易”无法区分，守恒校验也会被凑平。守护：`test_a_month_without_a_statement_is_missing_not_zero`、`test_a_quarter_with_a_missing_month_fails_even_when_the_ends_exist`。
- `company_views.py::_bank_ledger` 与发票账簿并列返回、`checks_ok` 分开：银行口径（收付款）和票面口径不能互相抵消；银行目录读不了也不能挡住发票汇总。守护：`test_ledger_api_adds_bank_flows_beside_the_invoice_ledger`。
- `bank/workpaper.py::discover(parse_receipts=False)`：账簿只需要余额链，回单逐页按坐标解析很慢；版式改为只看首页识别，对账单才读全部页面。CLI 默认仍解析回单。守护：`test_reader_reuses_the_parse_until_a_file_changes`（断言调用参数）与 `tests/test_bank_workpaper.py`。

## 2026-11-10 工作区“公司”模块（WS-02 / WS-07 界面）

- `frontend/src/api/client.ts::acceptPartial`：子目录补建部分失败时后端返回 `ok:false` 但带逐项 `created/skipped/failed`；默认把 `ok:false` 当错误会丢掉这些结果，用户就不知道哪些文件夹已经建好。守护：`companies.spec.ts` 补建用例。
- `stores/companies.ts::write`：版本冲突时先重新读取清单再抛出提示，不自动重放写入，避免覆盖另一个页面刚做的修改。守护：`reloads the list after a revision conflict instead of overwriting`。
- `CompanySettings.vue` 只在 `company.id` 变化时重置：切换监控目录、补建子目录都会刷新清单，若按对象变化重置，会冲掉用户正在编辑的纳税人身份。
- `CompanyLedger.vue` 的 `<details :open="!checks_ok">`：校验全部成立时收起以免占屏，任一不成立必须展开标红，不能让失败藏在折叠里。守护：`shows failing conservation checks in red`。

## 2026-11-10 公司发票账簿（WS-07 第 3 步发票部分）

- `company_ledger.py::_family_amounts`：三项金额必须同时识别并守恒才计入，否则整张列入 `excluded`。按字段分别累计（首页勾选合计的做法）会让三列合计来自不同的票集合，账簿里“不含税 + 税额 = 价税合计”就不再成立。守护：`test_formats_of_one_invoice_count_once_and_broken_ones_are_listed_not_counted`。
- `_ZERO_TAX_RATE`：免税判断只认整串为 0 或 0%，不能用子串，否则“10%”会被当成零税率，把缺失的税额补成 0。守护：同上用例中的 10% 行。
- `build_invoice_ledger` 先判期间范围再判金额：范围外的票不应出现在“不计入”清单里；日期未识别的票在有范围时不进合计，因为无法证明它属于该期间。守护：`test_periods_ranges_and_undated_invoices`。
- 不按公司名称剔除发票：登记名称与票面全称常不一致，自动剔除会静默丢票；改为提示购买方/销售方不一致。守护：`test_party_and_cross_listing_warnings`。

## 2026-11-10 按公司只读目录与纳税人类型（WS-07 第 2 步）

- `targets/companies.py`：查找放在 `targets/` 而不是 `services/`，因为 monitor daemon 与 spawn 子进程不经过 AppState，`monitoring/` 也不能依赖 `services/`；坏清单读作“无公司”，成本页与同步照常工作，损坏由清单 API 报告。守护：`test_company_taxpayer_lookup_follows_folder_and_month`。
- `background_sync.py::_run_background_sync_process(company_taxpayer=…)`：子进程没有 AppConfig，由父进程查好后传入；daemon 是长驻进程，按每次同步现查以跟随清单修改与跨月。守护：`test_every_cost_projection_and_synchronizer_receives_the_registry_lookup`。
- `cost_analysis.py::build_cost_analysis_outputs` 在解析后、写工作簿前才调用 `company_taxpayer()`：长时间同步期间改了清单，不会被同步开始时读到的旧值覆盖；`services/costs.py::refresh_workbook_tax_profile` 因此在写锁被占用时可以直接返回 `sync_running`。
- `CostProjectionService.read_fingerprint` 含有效类型：类型变化不改任何投影文件，不纳入就会让分页读缓存继续返回旧价格。守护：`test_registry_taxpayer_type_prices_the_reference_and_keeps_the_saved_rate`。
- `effective_tax_profile` 只换类型、不换税率：清单不替用户在 3% 与 1% 之间选择，小规模配非常用税率时由既有 `warning` 提示。`save_reference_status` 拒绝与清单不同的类型，避免页面保存后又被清单覆盖、看起来“保存无效”。
- `company_registry.py::_after_write` 在释放 AppState 锁后才回调成本刷新，并且只比较纳税人类型（改名不重写工作簿）：刷新要取投影写锁，持有 AppState 锁去等它会阻塞其它请求。守护：`test_registry_edit_reprices_the_active_company_and_rewrites_the_workbook`。
- `company_views.py::_read_processed/_scan_signatures` 不用 `MonitorState`：它的构造函数会建目录，`load_processed` 遇坏文件会备份并重写；非活动目录必须完全只读。扫描有 20,000 项 / 2 秒上限，未扫完时删除数不计、无差异只能判 `unknown`。守护：`test_directory_views_report_projection_and_freshness_without_writing`、`test_missing_processed_record_reads_as_unknown`。

## 2026-11-10 公司清单（WS-07 第 1 步）

- `company_registry.py::CompanyRegistryService._load/_corrupt`：损坏、未来版本或缺字段的清单不回退为空，否则下一次保存会抹掉全部公司；保留原文件并拒写。守护：`test_corrupt_registry_is_kept_and_blocks_writes`。
- `_clean_root`：根目录按解析后、大小写折叠的路径比较，禁止重复与嵌套，后续公司聚合才不会把同一文件计入两家公司；`_clean_subdirs` 同理禁止六类子目录相同或嵌套。守护：`test_names_are_unique_and_roots_cannot_repeat_or_nest`、`test_subdir_mapping_must_stay_inside_the_root_and_be_distinct`。
- `detect_subdirs`：同一文件夹命中多类提示词时不归入任何一类，改为提示创建标准目录，避免把抵扣清单当成开具发票读。守护：`test_create_detects_existing_folders_and_never_guesses_ambiguous_ones`。
- `_subdir_status`：`resolve()` 也会跟随已存在前缀里的链接，因此“父目录是指向外部的链接”的缺失子目录在创建前就被拒绝。守护：`test_linked_parent_that_leaves_the_root_is_blocked`。
- `_plan/create_subdirs`：`plan_hash` 绑定清单 revision 与每项路径/动作，确认时在锁内重算；`mkdir(exist_ok=False)` 在预览后出现同名项时不覆盖。守护：`test_subdir_creation_is_preview_then_confirm_and_only_makes_empty_folders`。
- `clean_taxpayer_periods/taxpayer_type_for`：空即未设置，不默认一般纳税人（税务规则“未知不为零”）。守护：`test_taxpayer_type_follows_effective_month`。

## 2026-11-09 工程门禁、路由拆分与 Vue 前端

- `api/app.py::create_app` 的 `include_router` 顺序：每个路由组放在其路由原来注册的位置，FastAPI 0.141 以 `_IncludedRouter` 按序惰性匹配，故重叠路径（发票详情与 trash-jobs、皮肤 `{skin_id}` 与固定动作）的命中顺序不变。守护：拆分时 OpenAPI 逐字节一致、792 个方法×路径样本命中同一端点，以及 `test_api_contract.py`。
- `frontend/vite.config.ts::versionQuery`：构建产物提交在 `web/` 内，固定文件名让发布白名单、Core Build ID 文件集合与 FILE_MAP 不随每次构建漂移；缓存刷新改由 `?v=` 内容哈希承担，与旧页面同一缓存规则。守护：`test_workspace_frontend.py` 与 CI 的构建可复现检查。
- `requirements/lint-tools-py314.lock` 独立于 `test-tools-py314.lock`：后者由 Windows 重打包配置引用，改动会牵动发布核对；lint 工具不进入任何成品。
- `.github/workflows/ci.yml` 的 Windows clippy 不带 `-D warnings`：`cfg(windows)` 代码此前从未经过 clippy，本机 macOS 无法验证；清理后改为阻断（ENG-01）。
- `projections/costs.py::save_reference_status` 的未使用工作簿读取以 `noqa` 保留：删除会改变工作簿损坏时的失败行为，是否应像 rebuild 一样合并工作簿状态待 ENG-02 判定。
- `api/main.py` 在设置 `INVOICE_HUB_ROOT/CONFIG` 后才调用 `create_app()`，`api/app.py` 不再有模块级实例：旧实例让任何导入都按仓库默认配置做启动同步，测试会改写 checkout 的 `runtime/` 与 `发票文件/`（ENG-07）。守护：`test_importing_the_api_module_builds_no_app_state`、`test_cli_creates_exactly_one_app_state` 与 `tests/conftest.py` 的仓库状态快照。
- `host_rpc.rs` 测试的 `accept_within`：阻塞 `accept()` 在发送线程无法连接时会让整个测试二进制挂起，改为有时限失败。

## 2026-10-09 双平台构建保护

- `trash.py::post_delete`：Microsoft明确规定PostDeleteItem的psiNewlyCreated表示回收站中目标，NULL不能证实可恢复；在前置veto后仍验证结果。守护：COM成功/失败/取消/缺少目标测试。依据：[Microsoft PostDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-postdeleteitem)。
- `lib.rs::accepts_temporary_file_drop`：详情返回token只影响首页状态；按固定origin与路径而非整个URL字符串判断，避免返回后拖入失效，保持其它页面和远端拒绝。Rust正反例守护。
- `generate_desktop_icon.py`：固定hi.拉丁字标原稿采用BASIC布局，可选Raqm不能使跨平台重生成像素漂移；原master逐像素回归保持。
- `build_manifest.py::_is_build_cache`：editable安装元数据不进入任何core包，不参与core身份；真实源码仍逐文件纳入。身份测试覆盖元数据无影响与源码变化会改变指纹。

Windows验包测试中的假凭据在运行时拼接：保持生成文件的扫描正反例，同时源码归档不携带凭据形状字面量；不降低 `content_scan` 的识别规则。守护为 `test_tauri_windows_portable_verifier_uses_dependency_scope_for_locked_cpython_lib` 与整份源码归档扫描。

## 2026-10-09 勾选工作流保护

| 判断位置 | 原因与不变量 | 守护测试 |
|---|---|---|
| `platform/trash.py::recycle_guard` / `_windows_trash` | 请求回收仍可能遇到磁盘不支持；PreDeleteItem必须阻止永久删除，COM对象及回调活到释放完毕 | `test_windows_guard_vetoes_permanent_delete`、`test_windows_com_contract_fails_closed` |
| `invoice_trash.py::commit/_record_file` | 原生操作前持久化意图，结果不明只能查询，不能删除同名替换文件；逐项追加避免平方级写入 | `test_trash_confirmation_exact_selection_and_idempotence`、`test_interrupted_journal_is_observed_without_retry` |
| `AppState.commit_invoice_trash` | 活动目录、monitor写入与确认来源串行；忙锁不等待解析，变动只经既有同步更新投影和保留手改 | `test_confirmation_revalidates_all_before_any_move`、`test_stale_cross_origin_symlink_and_busy_rejected` |
| `selection_cost_breakdown` | 金额行去重与来源集合分开，确保来源只归属于该项目/税率 | `test_provenance_tracks_project_tax_and_keeps_money_deduplication` |
| `page-index.js::loadFilePreviewJob/confirmInvoiceTrash` | 全量选择只作导航，当前项按需准备；删除响应丢失只能GET日志，不重发POST | `tests/selection_workflow.test.cjs` |

平台接口依据：[Apple FileManager Trash](https://developer.apple.com/documentation/foundation/filemanager/trashitem(at:resultingitemurl:))、[Microsoft PreDeleteItem](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-predeleteitem)。


## 2026-10-09 临时识别的来源与异步边界

- `TemporaryRecognitionService.preview/_preview_source`：仅选择授权或历史 item 可访问 watch_dir 外文件；返回缓存前后核验整线程，防止预览绕过源失效限制。守护：历史重启、跨线程 id、同元数据改内容、渲染中删除、缓存回收回归。
- `temporary-recognition.js` 的预览代际/序号：切换文件、页码或离开后，迟到内容及校验失败不得清除新视图；XML 仅 textContent，blob URL 在离开时释放。守护：Node 迟到响应、源失效清空、纯文本与返回测试。

- `TemporaryRecognitionService._public/get`：历史不是源文件备份，任一来源失效必须省略全部 items；守护：删除、移动、替换和相同元数据下内容变化测试。
- `recognize_job`：只处理显式选中的来源，进度写 runtime 缓存，禁止扫描所在文件夹或进入正式投影；守护：排序、逐份发布和原文件不变测试。
- `temporary-recognition.js`：generation 拒绝迟到 picker/历史结果；网络失败先隐藏旧表格，复制前再次核验来源；守护：Node 异步竞态回归。
- `main.rs`：只有固定 origin 首页消费原生拖入路径，私有 RPC token 不进入事件；多选复用固定枚举、原生线程调度和120秒预算。


## 2026-10-09 渐进读取保护

| 位置 | 原因与不变量 | 守护验证 |
|---|---|---|
| `ReadViews.read/save_cost` | 同一次读事务绑定页数据与代际；成本四表同事务发布，防止复制跨代际混合 | progressive loading 的分页/过期 revision 回归 |
| `CostService.cost_view`/ `MonitorState.try_sync_write_lock` | 非阻塞读缓存不能取消原投影互斥；锁释放不代表生成成功，失败临时明细永远只读 | 写锁占用时可读、失败后不可编辑 |
| `InvoiceListService.list_invoices`（`services/invoice_list.py`）/ summary 解析循环 | 临时列表在家族校正前可见但不能用于选择、详情、打印和导出；完整结果仍用原位置身份校验 | 暂停第二张解析、分页全量统计及既有选择身份回归 |
| `DocumentIndex.build_index` / `document_state` | 入库准备与出库解析分阶段；首页勾选已给出票的身份，无需触发无关出库扫描 | selection_only 无扫描、进程停止/恢复与候选预览回归 |
| `document_outbound_preview` | 元数据复用仅节省紧随预览的文件状态读取；源文件变化或导出仍需验证 | 状态不重复解析、源文件中途变化拒绝、临时预览导出拒绝 |

## 通用检查点的恢复与私有边界

`agent_handoff.py::Store.save` 先提交 journal 再更新投影，避免多文件中断导致已确认进度丢失；expected revision 与 私有根目录锁防旧执行者覆盖新记录。`build_agent_handoff.py::package` 仅复制公开白名单及固定 runtime，不能递归复制工作目录。对应工具/打包回归覆盖中断、并发、未知结果和私有成员拒绝；actor 是协作标签，不是系统安全边界。跨 project 可用性扫描与写入必须共用私有根目录锁；仅共享扫描而各自加 project 锁仍会发生双认领。Git 采集清除调用环境中的工作区/索引覆盖变量，避免把另一任务的 Git 身份当成本目录真值。

1.1 的 `brief` 明确省略字段与行动前展开标记，防止为了省 token 隐去约束或未知结果；默认 resume 不调用 snapshot，claim 只复核一次。`Store.save` 先比较去除时间/revision 的内容，无变化零提交；增量事件可重建全文，更新一个任务不能改写其它 CURRENT。`resolve_reference` 只查本地明确绑定，多个匹配直接拒绝，不读取聊天或按时间选任务。守护测试覆盖摘要预算/全文保留、无变化无写入、只读不哈希、引用歧义、v1→v2追加和坏delta恢复拒绝。

功能约束按需读取：规则正文维护在 `rules/`，本页维护原因、不变量与守护测试的对应关系。先按 [任务快速索引](AGENT_TASK_MAP.md#quick-lookup) 定位全部命中项，再读取规则全文及对应实现章节；AGENTS.md 保留全局必读规则。

## Agent 入口与功能规则分层

| 维护位置 | 原因与不变量 | 守护 |
|---|---|---|
| AGENTS.md / CLAUDE.md → 任务快速索引 → rules 专题 → 原有任务行 | 新任务没有前一段聊天上下文；全局规则必须完整可读，功能规则必须能从问题定位且不因迁移降级为可选。正文只在所属专题维护，避免两个 Agent 入口各自复制失效细则 | `test_agent_entries_and_scoped_rules_remain_navigable` 锁定入口 16 KiB / 4 KiB 预算、双向规则链接和唯一锚点；原有文档契约继续覆盖文件地图、正文约束、无本机路径、链接与围栏 |

## 税务工作台拟议不变量（2026-09-11）

这里登记[设计](../TAX_WORKBENCH_DESIGN.md)与[政策来源治理](../TAX_POLICY_SOURCES_AND_REVIEW.md)的后续注释位置，不宣称对应生产源码或守护测试已经存在。

| 拟议交接点 | 为什么必须说明 | 未来守护 |
|---|---|---|
| 公司绑定 → 只读归集 | `watch_dir` 导航不是独立税务公司授权，默认空不得偷读父目录 | 空绑定零 IO、跨公司/越界拒绝、旧任务迟到 |
| 原生选择器 → 设置草稿 → 检测/保存 | 复用原生面板但使用独立公司用途，选择不能隐式保存/切换监控目录；取消和迟到返回不得覆盖新草稿 | 双平台原生选择、取消/失败/超时/重复拉起、设置关闭后返回与保存前隔离 |
| 入口偏好 → 单一图标 / 弹窗 | 缩小可见图标仍保留点击范围；置顶入口在首页左侧独立工具槽居中，不打断模块顺序；移动入口不应重建计算器状态；拖动与打开必须区分 | 位置切换保留草稿、入口唯一、拖动后不误开、视口变化与重置、保存失败恢复 |
| 卡片布局 / 自定义税率 → 正面按键 / 待重算 | 长解释和新增输入行不能挤走按键；自定义是输入假设，不能沿用旧官方结果 | 短窗口 20 键、长背面/结果滚动、税率编辑不增高、范围/精度与旧结果失效 |
| 事实快照 → 税务引擎 | 发票、抵扣、义务、记账和缴款期间不同，未知不是零 | 跨月抵扣、红字、多格式、缺期初与单月/季度反例 |
| 引擎 → 正面/翻面 | 用户数字与解释必须属于相同 run、规则和快照，前端不重复计算 | trace 数值与模板同源、结果 stale 时解释失效 |
| 规则选择 → 优惠 | 小规模、微利资格、六税两费和教育免征不是同一开关；2026 临界比较符不同 | 起征点前/等于/后、身份负向、舍入节点复核 |
| 并列选择 → 小计 | 票面额/累计额/已缴额和附加父子项目不能重复求和 | 叶子 ID、量纲/期间、缺资料/旧结果排除 |
| 政策来源 → 规则包 | 视频号与自媒体没有文号、条款定位和有效期，无法在解释中引用也无法判定失效；解释性材料一旦被当成法条，错误会随规则包扩散 | A/B/C/D 分级、线索回溯到官方原文、规则包只含 A 级来源与签署记录 |
| 规则包 → 申报表映射 | 表式随政策版本调整，过期映射比没有映射更危险：用户会照着旧行次填报 | 表式版本变化后映射 stale、缺表式样例时不输出行次 |
| 规则包 → 征期与期限提醒 | 期限只作提醒，不构成已申报证据；推断出的日期会被当成事实 | 记录来源与核对日期、未核验显示“未核验”、税费种认定优先于通用日历 |
| 结论 → 留存备查清单 | 多数优惠是自行判别、申报享受、资料留存备查，算得对但拿不出资料仍是风险 | 清单来自本次实际引用的规则与证据、资格类型可指认证据文件 |
| 资格与认定 → 历史属期 | 纳税人身份、资格和税费种认定会变；用今天的身份算以前的属期是最隐蔽的错算 | 带生效期间的状态回放、跨期递推例、政策变更例 |

合成原型的入口注释与固定小计注释明确其无税务算法/业务 IO 边界；源码语法和交互核对只能验证设计表现，不能冒充生产算法与成品验收。

2026-09-09 `tauri_windows_portable.py::_replace_staging` 对 Windows 5/32/33 最多重试 20 次、累计 1.9 秒，处理新复制 EXE/DLL 后目录发布的短暂占用；持续拒绝与无关错误仍停止，不复制半成品或放宽清单。`test_stage_publish_retries_only_bounded_windows_sharing_errors` 守护成功、次数上限和错误范围。

2026-09-09 `BackendHost::launch` 清除 PYTHONHOME，避免用户 Python/Conda 的标准库路径使随包解释器在 encodings 初始化时退出；spawn 前重置诊断、只输出 OS 错误码，避免旧握手记录和敏感环境值进入新诊断。Windows 随包 Python 污染/清理实验及新包启动验收守护；`windows_abortive_close_preserves_framing_and_reports_truncation` 使用真实 Winsock SO_LINGER 验证完整 200/204 与截断 10054 的区别。

## 参考凭证草稿（2026-10-10）

| 文件与符号 | 设计原因与不变量 | 守护测试 |
|---|---|---|
| `bank/ledger.py::Ledger.find` | 不同账套编码不同，按名称路径定位；不唯一或不存在时留空，避免把分录记到相近但错误的科目 | 科目路径定位用例 |
| `bank/vouchers.py::_input_policy` | 已申报且有抵扣的月份推定已抵扣，防止重复抵扣；已申报且未抵扣的进项记待认证，在未申报月份转入 | 进项抵扣与增值税测算用例 |
| `bank/workpaper.py::analyze` 角色优先级 | 自动写入的“未知”不能压过后来补充的发票证据，只有人工条目优先 | 人工角色保留用例 |
| `bank/jierui.py::export` | 任一凭证不合格则整月不写出，防止只导入半个月；签名去重防止同一凭证重复导入；编号从该月草稿最小号起，补记凭证不与账套已有凭证撞号 | 导出校验、重复导出、已入账月份补记用例 |
| `bank/vouchers.py::_input_policy` 勾选清单 | 清单已登记的月份里没出现的发票就是未勾选，挂待认证；推定已抵扣会虚增进项、与申报表对不上 | 勾选清单与跨月补记用例 |
| `bank/vouchers.py::build_drafts` 发票读回匹配 | 按税额消耗匹配读回分录，避免已入账发票重复入账；已结账月份的漏记发票补记到首月，不改已结账期间 | 勾选清单与跨月补记、已入账月份补记用例 |
| `bank/vouchers.py::match_booked` | 账套曾把同一人多笔来款合成一张凭证，只在摘要点名的对方流水里找合计组合；对不上就补记或列“账有银无”，不按相近金额硬配 | 合并来款匹配、已入账月份补记用例 |
| `bank/vouchers.py::build_drafts` 已入账月份 | 有账套读回的月份发票与月末计提已入账，再生成会重复入账；只补记银行漏记 | 已入账月份补记用例 |
| `bank/workpaper.py::_assign_statement_id` | 中国银行每页序号重排，行号按整份对账单位置编号，否则第 2 页行与第 1 页撞号并覆盖分类 | 分页序号用例 |
| `bank/vouchers.py::merge_lines` 数量 | 合并同科目分录时数量随金额相加，单位不一致则清空交人工，避免库存数量与金额脱节 | 合并分录用例 |

## 银行流水底稿（2026-10-02）

| 文件与符号 | 设计原因与不变量 | 守护测试 |
|---|---|---|
| `bank/boc.py::_finish_row` | 银行对账单“借方发生额”是账户流出，企业账上记贷方；方向写错会让整套建议分录借贷颠倒 | 解析方向用例 |
| `bank/boc.py::parse_statement_pages` 续行拼接 | 定宽列把中文和长编号折行，插空格会破坏流水号与户名，必须无空格拼接 | 摘要/备注续行用例 |
| `bank/boc.py::_pair_fields` | 回单文本层中标签与值顺序不稳定，只能按同行坐标与下一标签边界配对；折行值与首行左对齐 | 合成回单坐标解析 |
| `bank/matching.py::match_receipts` | 同一流水号可同时对应转账与手续费，必须带金额；多候选不猜 | 流水号匹配用例 |
| `bank/classify.py::suggest` | 依据文本不含户名，户名只在 `aux`，脱敏才能统一替换；建议分录不是凭证 | 端到端私有/脱敏对照 |
| `bank/redaction.py::free_text/scan` | 摘要夹带人名和项目名，只能白名单保留用途词；数字按词边界匹配避免哈希串误报，命中即 fail closed | 白名单、词边界、fail-closed 用例 |
| `bank/workpaper.py::run` | 先构建并扫描脱敏表再写私有表，防止半套产物；`往来单位.json` 只补不改 | fail-closed 不写出、人工角色保留用例 |

## OFD 原票预览（2026-09-08）

| 文件与符号 | 设计原因与不变量 | 守护测试 |
|---|---|---|
| `file_preview.py::_entry_for_source/get_page/_ofd_preview_error` | MuPDF 的压缩包图片读取不能还原 OFD 页面；专用渲染必须逐文件失败，混选 PDF/XML 与系统打开继续可用 | 原预览回归、真实组件混选 API |
| `ofd_rendering.py::_read_package/OFDRenderer.render` | 第三方解析器可能跟随资源引用；先校验 `ZipInfo.orig_filename`（避免 Windows 分隔符归一化/NUL 截断隐藏原始危险路径），限制 ZIP/XML 后再在 Java 21 权限策略下处理临时副本，不继承主机令牌，超时必须回收 worker，PNG 不落盘 | 不安全路径/XML、容量、超时清理/环境隔离、真实 PNG |
| `ofd_rendering.py::_checked_component/_component_signature` | 多文件/多页不能反复读取约 75 MiB 组件；缓存只在全部路径/清单/文件元数据未变时复用，变化须重新哈希，失败清空 | 缓存无重复读取、JAR/清单变更失效测试 |
| `Preview.java::checkGlyphs`、`StaticLoggerBinder` | OFDRW 会吞掉局部绘制异常或省略 null cmap 字形；`getAllLayer()` 已含模板；预检查使用与上游 AWTMaker 相同的 UTF-16/CGTransform 索引，拒绝未映射补充平面字符并阻断绘制告警，避免已知残缺 PNG 冒充成功 | 缺失字形负向、分区中文/金额/图形像素检查 |
| `build_ofd_preview.py`、`COMPONENT_SOURCE_FINGERPRINT` | Java 代码/依赖不在 Python wheel 内，但需要进入核心构建身份；固定输入 SHA、核心源码指纹、组件文件哈希与外层 runtime manifest 分层绑定 | 源码指纹与篡改 JAR 契约，完整/精简 PNG 对比 |

2026-09-08 本附录与开发架构总入口统一以 `main` 的 PR #20 合并提交为产品实现及后续发行源码基线，精确身份见 [分支记录](../BRANCH_STATUS.md)；下文旧分支名只记录来源，不能再作为并行真值。源码 CI 不替代平台成品验收。

2026-09-08 `MonitorState.read_status` 不得持完整 sync 锁，否则 `MonitorBridge.stop` 在请求停止与开始超时前就被长汇总阻断；改为独立状态文件短锁，写入固定 sync -> status 顺序，保留 Windows 原子替换互斥。`test_monitoring.py` 覆盖长锁下状态读取、停止请求与超时可达，以及原有跨进程同步写入串行化。

2026-09-08 `document_index.py::_write_cache_json` 只对 Windows 5/32/33 短暂替换拒绝最多尝试 20 次、累计等待 0.95 秒，保证后台先发布目录快照再发布 ready；持续拒绝和其它错误继续抛出，不能把已完成索引误报失败或无限等待。`test_document_index.py` 以最终状态写入共享冲突与持续错误守护。

2026-09-07 `document_index.py` 注释说明独立进程隔离原生解析 GIL、逐文件提交与 WAL/NORMAL 的断电边界、Windows 原子替换瞬时读失败保留状态。`documents.py::build_outbound_preview` 明确缓存仅定位，当前目录/号码仍是授权边界；`page-documents.js::renderInvoiceChoices` 保留跨页选择且限制 DOM。守护为 `test_document_index.py`、单据预览/导出、Node 大列表及真实浏览器皮肤检查。

2026-09-07 `_filter_invoice_items` 的搜索范围注释解释首页可见字段与旧 API 文件名兼容边界；不能为减少空销售方结果删除源记录或改变识别字段。keyword 必须逐字段匹配，避免字段拼接误命中。守护为 `test_invoice_search_scope_with_large_snapshot`、旧字段契约与 Node 迟到响应检查。

2026-09-07 整合约束：图标是包内固定枚举，Rust 解码只接受已编译 8-bit RGBA；窗口更新失败先恢复托盘，Python 收到成功后才保存，防止界面和状态分离。白底 hi. 从同一母版生成 exe 与选择预览。共用关闭控制器后必须换设置脚本缓存版本，否则旧脚本重复声明会使整页初始化失败。Windows marker 使用对齐的重命名缓冲区和 NT 相对路径操作；目录 flush 只忽略明确不支持的错误。守护测试见 app_icon、frontend、tauri_host_rpc、Windows marker 和 lifecycle 契约。

> 本轮状态：只登记注释债，不批量修改生产源码。
> 公共权威基线：单一脱敏根提交；旧私有提交、Tag、包和验证材料不在公开图中。
> 当前边界：`v0.3` Tauri 已有 Host RPC/updater 的专门边界说明，但不能借机重写共享业务核心。
> 原则：注释解释“为什么必须这样做”和“破坏后会发生什么”，不复述 Python/JavaScript/PowerShell 语法；跨功能交接还必须说明上游、下游与顺序。

## 1. 为什么先做地图而不是批量加注释

2026-09-07：`backend.rs` watcher 必须在 owned child 结束后请求 host 退出，否则页面关闭会留下占据单实例的宿主；主动退出先撤销 ownership 避免重入，由两项 Rust 单测和生命周期契约守护。Windows child 无控制台时将 stdout/stderr 写入 owned runtime，避免丢失启动诊断；`WindowsHandle` 的唯一所有权只允许 Send，不增加 Clone/Sync 或放宽 no-reparse。皮肤新工具按钮禁止沿用通用位移动效，全局关闭弹窗不能再只用 settings 页面选择器；Ink Pulse 深色单据预览是用户明确保留的显示选择，不影响 Excel 与真实源票面。组包沿用官网精确白名单，禁止引入网站维护文件，由 portable 验包负向测试守护。

当前复杂逻辑主要由测试和 CHANGELOG 保护，源码中的解释性注释很少。直接按行批量生成注释有三类风险：

1. AI 可能把推测写成事实，让后续开发者更相信错误解释。
2. 大范围改动会制造审查噪声，掩盖换行、编码或缩进等真实行为变化。
3. 注释会和代码一起过时；如果没有关联不变量和测试，它比没有注释更危险。

因此采用“先登记设计原因，后续真实修改到该符号时就地补充”的策略。每次只补与当前变更直接相关的注释，并运行相邻回归。

## 2. 什么值得写注释

应当注释：

- 从代码局部看不出的业务证据边界，例如为什么整数金额必须被拒绝。
- 并发和进程时序，例如 ready 必须在第二次补漏同步后写入。
- 向后兼容原因，例如一个状态为什么同时接受三种 key。
- 安全边界，例如为什么 ZIP 必须先完整校验再写盘。
- 失败保护和恢复语义，例如两阶段重命名如何回滚。
- 看似可以简化但实际不能简化的分支，例如关闭时不能直接删除 PID 文件。
- 跨功能的交接点，例如页面事件为何必须等投影落盘后才发送，或 host 为何必须在后端握手后才开放原生能力。

不应当注释：

- `x += 1`、`return payload`、遍历列表等语法复述。
- 只重复函数名或类型标注的 docstring。
- 没有代码/测试证据的历史猜测。
- 易漂移的行数、测试总数、当前样本数量或本机路径。
- 用 TODO 代替明确任务和验收条件。
- 对每个字段逐行生成相同句式的“保存某某值”。

跨功能衔接注释应紧贴交接或保护分支，至少交代四项中的必要内容：上游输入或状态、下游消费者、顺序或不变量、以及顺序被打破或动作失败的后果。它不要求把每个函数调用串成流水账；能从函数名和类型直接得出的部分应留给代码本身。

## 3. 注释优先级

| 优先级 | 含义 | 处理时机 |
|---|---|---|
| P0 | 数据污染、文件破坏、进程竞态或安全边界 | 下一次触碰该符号时必须补，并跑守护测试 |
| P1 | 兼容、跨层契约或非直觉算法 | 下一次行为变更或重构时补 |
| P2 | 导航性解释，可降低大型文件理解成本 | 拆分/重排模块时补，不单独制造大 diff |

## 4. P0：AppState 编排与事务

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `services/background_sync.py::_run_background_sync_process` 与 `BackgroundSyncService.run_background_diagnostics` | PyMuPDF 等原生解析可能长时间占用 GIL；首轮同步必须在 `spawn` 子进程，而不是把重解析留在 API 进程线程中。retire 和 worker 清理可以并发，`Process.close()` 后读取 `pid/exitcode` 会抛错 | `/` 和 health 不被重解析阻塞；子进程以 `emit_events=false/notify=false` 返回结果，父进程只有在 generation 与完整 TargetProfile 身份仍匹配时才清缓存、更新状态并补发普通同步事件；过期结果只能记 `server.background_stale`；超时事件使用关闭前安全捕获的进程诊断值 | startup child、慢 worker、过期 TargetProfile、关闭后 PID 快照与失败路径 API 测试 |
| `api/app.py::invoice_selection_summary` 与 `InvoiceSelectionService.invoice_selection_summary` | `invoice_key` 是行位置，会在重建后复用，所以请求必须带并复核 `source_path`；业务方法还会做同步文件 I/O 和聚合，必须由异步路由卸载到线程池 | 旧选择不能落到新文件；过期返回 409；selection-summary 进行中 health 仍可调度 | selection-summary 过期/非法/并发 health 测试 |
| `api/app.py::manual_fields/cost_analysis/reference_status` 与 `InvoiceListService.update_manual_fields`、`CostService.cost_snapshot/save_cost_reference_status` | 手改、schema 自愈和状态/工作簿写入都会等待文件锁；留在事件循环会让 health 与其他轻请求饥饿，脱离 profile 锁又会与 monitor 竞争 | JSON 解析后在线程池运行；所有会写投影的路径使用捕获 profile 的写锁；profile 已切换时旧目录可完成自身真值，但不得清当前缓存或发出当前目录事件 | manual fields、cost snapshot、reference status 的 lock/health/stale-profile API 测试 |
| `invoice_selection.py::selection_family_key` / `InvoiceSelectionService._selection_metric_total` | 票头号码和文件名号码必须进入同一命名空间；每个金额字段独立判断冲突 | 同票多格式只计一次；同字段多值整票不计 | selection-summary 去重/冲突/回退测试 |
| `InvoiceRenameService.rename_invoice_files`（`services/invoice_rename.py`）第一阶段 | 临时名先释放所有源名称，避免 A/B 目标互占和顺序覆盖 | 任何 staging 失败都逆序回滚；不覆盖已有非计划文件 | 重命名保持手改与重复目标测试 |
| `rename_invoice_files` 第二阶段 | 全部临时名再提交为最终名，失败时需要同时回滚已提交与未提交项 | 结果必须区分文件已改名但投影重建失败 | 同上；真实目录验收另行执行 |
| `_migrate_renamed_manual_overrides` | 手改状态用源路径作身份，文件改名必须迁移 key | 不丢三项手改，不把旧 invoice_key 当长期身份 | 手改迁移/重建测试 |
| `request_server_shutdown` | stop-monitor 模式必须先停止并复核，失败时保留 WebUI | 响应前不终止服务；monitor 仍 running 时不调度退出 | shutdown API 两种行为测试 |
| `ServerShutdownService.server_shutdown_requested`与 `api/app.py::event_stream` | WKWebView 的 EventSource 可在 shutdown 响应写回后继续持有 SSE；若 generator 不主动结束，Uvicorn graceful shutdown 会一直等待浏览器连接 | 仅在结构化 shutdown 已被成功接受后关闭 SSE；失败会重置 shutdown 标记，普通 EventSource、事件游标与 heartbeat 语义不变 | shutdown 后 SSE EOF API contract、public-preview smoke contract |
| `tauri_public_preview.py::build` 与 `verify_tauri_public_preview.py::_verify_receipt_verification` | 首次验包需要读取尚未写入 verifier 输出的 receipt；若把这一中间态当作公开验收成功，损坏或未完成的 receipt 可被误作发布证据 | pending record 仅可由组包器首轮显式接受；随后写入 exact verifier JSON 并绑定实际 DMG SHA-256，默认 verifier 必须再次通过，字段扩展、篡改或不完整一律拒绝 | macOS public-preview receipt finalizer、builder stdout/stderr/timeout contracts |
| `finalize_server_shutdown` | 正式启动器 PID 可能不是 Uvicorn `os.getpid()`，且关闭期间可能启动新实例 | 仅当 PID 文件内容仍等于请求快照时删除 | shutdown finalize 测试 |
| `BusinessDossierService._scan_business_dossier/business_dossier/open_business_dossier`（`services/dossier.py`） | 公司资料夹是导航边界，不是新的扫描根；完整递归和每链接重复扫描会拖住页面，即使前端超时服务端仍会继续工作 | 单次 `os.scandir` 有目录项/时间上限、跳过符号链接；迭代途中 `OSError` 保留已累计项并以 `unreadable_entries` 标为下界；只打开业务资料夹或当前 watch_dir 内路径，open 同步路径经线程池 | business dossier API/有界扫描/iterator-OSError/线程池与首页刷新容错测试 |
| `BookkeepingService.bookkeeping_*`与 bookkeeping repository | 做账状态写入跨进程且必须绑定当前资源 revision | 只经严格仓储/写锁/CAS；坏 schema 保留原文件并 fail closed | 全部 bookkeeping 状态/API 测试 |
| `AppState.__init__` 构造全部领域服务（`services/*.py`）的 provider 与回调参数 | 切换 watch_dir 会替换 AppState 的 TargetProfile 与 config；服务若在构造时捕获对象，后续做账会落到旧公司资料夹。服务若自建锁，做账写入就不再与目录切换和其它 AppState 写入串行 | 活动目标、config、公司资料夹与成本明细路径一律经回调实时读取；传入的是 AppState 同一把 RLock；单据另经回调读取出库目录与首页勾选校验，切换出库目录后预览/导出不得落到旧目录 | `test_bookkeeping_service_follows_watch_dir_switch`、`test_bookkeeping_writes_wait_for_the_app_state_lock`、`test_document_service_follows_watch_dir_and_outbound_switch`、`test_document_export_waits_for_the_app_state_lock`、`test_cost_service_follows_watch_dir_switch`、`test_cost_view_waits_for_the_app_state_lock`、`test_business_dossier_follows_watch_dir_switch`（资料夹不取锁，只守护目录跟随；做账经它取公司目录，做账那条测试同时覆盖）、`test_preview_print_service_follows_watch_dir_switch`、`test_preview_creation_waits_for_the_app_state_lock`、`test_selection_service_follows_watch_dir_switch_and_live_invoice_list`（另守护发票列表回调每次现取）、`test_selection_summary_waits_for_the_app_state_lock`；所有服务另由 `tests/test_appstate_service_wiring.py` 按服务参数化守护（锁、活动目标、config 为 AppState 同一对象），并检查 AppState 不再长出转发方法。跨服务回调必须是每次现查的 lambda：构造后在服务实例上打桩（如 `state.settings.outbound_invoice_dir_text`）才能传到其它服务，变异核对时提前绑定方法对象会使 `test_outbound_partial_preview_and_status_reuse` 失败 |

## 5. P0：票头、金额与同票纠偏

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `extraction/parsers.py::_normalize_money` | 8-20 位纯数字高度可能是发票号/对象号；上限用于阻止编号污染 | 不把号码片段当金额；合法小数/货币格式仍可用 | 三个金额防污染/合法金额测试 |
| `_extract_pdf_amount_triple/_text_from_pdf` | 票面汇总金额可能早于身份值，购销方后又有重复明细金额；拼接页文本会制造跨页伪证据 | 保留 `\f` 页边界；只收锚点有限窗口内带货币符号的有序候选；唯一且差额不超过 `0.02`；总额来自票面 | 三元组安全边界与真实 48 票影子对照 |
| `_first_money_near` | 160 字符窗口会跨票头、汇总和明细区域，把首个无关金额当标签值 | 只读标签同行或下一非空行的独立货币值；不恢复全文最大数 | 同行/紧邻/跨逻辑区域金额测试 |
| `_extract_einvoice_value_sequence` | 某些电子票按“所有标签后集中输出值”，但主体后的数值也可能只是单价和明细金额 | 必须先锁定 20 位号和日期，只接受两个主体；金额交给独立证据链 | digital invoice value sequence 与两个明细小数拒绝测试 |
| `_clean_company_candidate/_party_value_is_suspicious` | 大写金额、数字对象、地址/项目/标签常被误当主体 | 宁空勿脏；短个人主体仍允许 | 个人销售方与可疑主体纠偏测试 |
| `_ofd_text_objects/_ofd_custom_tag_refs/_record_from_ofd_structured` | `CustomTag` 只给对象引用，真实文本在 `Content.xml` | 结构化优先，缺失时才回退全文 | OFD 结构化票头测试 |
| `apply_invoice_family_corrections` | XML/OFD/PDF 可靠性不同，但不能覆盖有效冲突或人工字段 | 购销方只补空/纠脏；分类只补空，非空冲突保留 | 同票购销方/分类补齐与冲突测试 |
| `classification.py::classify_invoice` | 大类和业务样式是独立证据集合，未知标签不能默认成标准 | 公司/项目词不触发；`XT` 仅显式标签精确值 | 完整分类测试文件 |

## 6. P0：成本坐标、评分与公式

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `cost_analysis.py::_find_header_layout` | 不同业务版式列宽不同，必须从可靠表头中心动态推边界 | 至少项目/金额/税率/税额；无可靠表头不猜 | 多版式表头与无表头拒绝测试 |
| `_group_words_by_baseline` | PDF 同一视觉行的文字 y 值会轻微偏移 | 容差聚类不能让相邻真实行合并；税额轻微提前仍同一行 | 税额基线提前测试 |
| `parse_cost_rows_from_words` 的 pending/continuation | 有的 PDF 金额先于项目名，项目名也可能跨行 | 只在有限 y 距离归并，专属列不能挤进金额列 | 业务版式分类成本测试 |
| `_cost_validation` | 有行不等于可信；票头除税和税额要分别验证 | 两项各自容差 `0.02`，差异显式进入校验 | 候选评分/校验测试 |
| `_select_cost_analysis` | 结构化格式优先只用于同分决胜，校验可靠性更重要 | 先 score/有行/可用，再 XML>OFD>PDF | 同票候选评分和并列优先测试 |
| `stock_average_unit_price*` | 库存成本按数量加权；不能替换成行单价算术平均 | 缺少任一必需值时返回空，不把坏行作零 | 均价双口径/缺失行测试 |
| `purchase_reference_average_unit_price_with_tax` | 采购参考刻画每次采购单价，行权重相同 | 不参与库存金额和开票参考基数 | 双口径测试 |
| `_reference_key` 与 `costs.py::_reference_aliases` | SHA1 分隔键兼容旧系统，旧明文/规范化键仍需读取 | 新保存归一到 SHA1；四字段不能加入销售方/票号 | 旧 SHA1/兼容状态测试 |
| `_invoice_reference_summary/_build_reference_rows` | 开票参考按成本单价（不含税 + 不可抵扣税金）、行级加价和本公司销项税率计算 | 8% 仅 fallback；每行独立；公式在工作簿、API、保存与 page-costs 四处一致；无 `tax_profile` 时等同旧的一般纳税人 13% | 行级加价与统计测试、税务设置测试 |
| `input_tax_deductibility/reference_cost_basis` | 一般纳税人只有专票与旅客运输普票可抵扣，其他普票税金计入成本；小规模全部计入 | 类型未确认时按不含税并标注，避免识别缺口抬高参考价；通行费普票未单独识别，会按不可抵扣计 | `test_cost_reference_general_taxpayer_adds_ordinary_invoice_tax_to_cost`、`..._unconfirmed_invoice_type_...` |
| `_write_reference_status`（两处） | 改写状态 JSON 时保留顶层 `tax_profile` | 重新汇总合并工作簿状态、只保存行状态都不能清掉公司税务设置 | `test_rebuild_status_writer_preserves_tax_profile`、`test_cost_tax_profile_change_keeps_locked_snapshot_and_survives_row_saves` |
| `read_outbound_summary/outbound_reference_fields` | 销项只在手动重新汇总时读取并缓存到工作区；只采用销售方为本目录进项购买方的票；比对不改保存的已开数量 | 开具目录是全局设置，切换公司后可能指向别家；手填可能早于销项归档，自动覆盖会改动已开快照 | `test_outbound_summary_dedupes_formats_and_ignores_other_companies`、`test_outbound_compare_states_follow_hand_entered_quantity`、`test_bridge_rebuild_reads_outbound_invoices_into_cost_reference` |
| `canonical_reference_rows/merged_status_item/_migrate_statuses_to_catalog` | 品目表改名即合并；已开状态在保存品目表时一次性迁移（合并相加、拆分按数量分摊）；规格不改大小写、不去 E 后缀 | 合并 / 拆分不能丢已开快照；18E 与 18 是不同牌号；无品目表时分组键不变，旧状态无需迁移 | `test_item_catalog_merges_names_and_keeps_saved_invoiced_snapshots`、`test_item_catalog_split_shares_merged_status_by_quantity`、`test_item_catalog_spec_normalisation_finds_status_saved_under_old_key` |
| `reference_invoice_id/reference_exclusions` | 开票参考“移除”只是排除，不删文件、不改明细与已开状态；来源发票整张移除 | 用户要求可恢复且不动发票目录；按发票号整张排除，避免同票在不同品目里一半计入一半不计 | `test_reference_exclusions_remove_and_restore_rows_without_losing_status`、`test_reference_exclusions_remove_source_invoice_from_row` |
| `referenceColumnIndex` / 底部操作条 | 草稿联动按列 key 定位；批量操作只在勾选 / 有草稿时出现 | 新增列（来源）与重排不会让联动写错格；减少常驻按钮 | 前端契约测试 `test_cost_page_keeps_required_controls` |
| `finishCostViewSwap` / `renderCostChrome` / `setText` | 切换 sheet 只渲染目标表；空表先保高度、渲染后先测量再释放；未变数据的自动刷新只更新状态文字 | 空表测得约 620px 的高度上限会让页面瞬间变短、滚动被拉回顶部；整页重绘与重复写 DOM 是“突兀”的来源 | 前端契约测试 `test_cost_page_keeps_required_controls` 与浏览器 A/B 验收 |
| `CostProjectionService.save_reference_status::locked_part` | 已开金额代表保存当时的业务快照，新增明细只能增加未开 | 数量变化才按比例重锁；只改加价不重价已开部分 | 快照锁定/新增汇总/改加价测试 |
| `_read_reference_status_from_workbook` | 旧目录可能只有工作簿状态，没有完整 JSON | 只作兼容兜底，恢复后写结构化 JSON | 工作簿恢复测试 |

## 7. P0：Monitor 与进程真值

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `monitoring/state.py::is_pid_alive` Windows 分支 | 本地化 `tasklist` 文本和 PATH 不可靠，系统句柄才是进程真值 | access denied 表示进程可能存活；STILL_ACTIVE=259 | PID 当前进程测试；Windows 真机验收 |
| `MonitorState.acquire_lock/cleanup_stale_lock` | lock 文件存在不等于 daemon 存活；O_EXCL 防并发抢锁 | 活 PID 的 lock 不清；stale lock 先隔离再建新 lock | live duplicate/stale lock 测试 |
| `file_signature/detect_source_changes` | 周期扫描要轻量，事件只是提示，最终以路径+mtime_ns+size 确认 | 无变化不重解析；增删改集合明确 | monitor rebuild/periodic 测试 |
| `sync_excel_manual_edits` | Excel 可能被占用，且只允许三字段成为覆盖 | 不可读时 GUARD_BLOCK；不接受其它列手改 | schema/手改同步测试 |
| `MonitorSynchronizer.run_sync` 决策矩阵 | 缺产物、schema 旧、源变化、手改和 force 的处理不同 | schema-only 可只刷新；无变化只 heartbeat；全重建后保存 processed | monitoring 同步与 schema 测试 |
| `MonitorState.sync_write_lock`、`MonitorSynchronizer.run_sync` 与 `MonitorControlService.bridge_rebuild` | daemon、startup child 与手动重建可同时命中同一 TargetProfile，单进程 `AppState._lock` 不能保护跨进程投影写入且会阻塞 API | 以 TargetProfile `state_dir` 为键取得可重入线程锁和 OS 文件锁，覆盖整段读取、决策、投影与 monitor 状态写入；不同 profile 不互相串行 | monitor overlap 与手动重建相邻测试 |
| `BackgroundSyncService._retire_background_process_async/_wait_for_background_sync_result` | 切换目录或新的 startup sync 不能让旧子进程无限扫描/写入；等待它退出也不能卡住请求入口 | superseded worker 独立有界 terminate/join；等待结果有总 deadline；仍未退出只记录 `server.background_worker_retire_timeout` 诊断，不覆盖活动 TargetProfile 真值 | startup child EOF、超时、retire 测试 |
| `daemon.run_monitor` 两次 startup_sync | 第一轮扫描与 Watchdog ready 之间存在漏事件窗口 | observer/兜底初始化后必须再补漏，再写 ready=true | bridge ready 和新文件事件测试 |
| daemon 的 `queue.Queue` 合并 | Watchdog 会产生连续 create/modify/move 事件 | 取得首事件后 1 秒归并，最终仍走签名判断 | daemon event 测试 |
| `MonitorBridge.status/_wait_for_ready/start` | 仅见 PID/lock 不能向用户报告启动成功 | lock PID、status PID、running、ready 必须一致 | bridge start/stop 测试 |
| `MonitorBridge.stop` | stop flag 是协作停止，超时才强制杀进程 | 停止后清 flag/stale lock 并返回真实复核状态 | bridge 生命周期测试 |

## 8. P0：皮肤、单据与文件安全

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `services/skins.py::_safe_package_path` | ZIP 路径可能使用 `/`、`\`、盘符或编码绕过 | 拒绝绝对、盘符/协议、`.`/`..`/空段 | unsafe ZIP 测试 |
| `validate_skin_zip` | 解压即写盘会造成 zip slip 或放入可执行内容 | 先完整校验路径、类型、大小、重复、symlink、加密，再写 runtime | 皮肤导入/拒绝测试 |
| `_validate_css` | CSS 可通过 import/url 加载远程或可执行内容 | 只允许包内存在的相对静态资源 | CSS 安全测试 |
| `SkinService.import_skin` | 导入替换应以临时目录完成，内置皮肤只读 | imported 仅在 runtime；同 id 内置不覆盖 | 导入、替换、存储隔离测试 |
| `ink-pulse/skin.css::ink-pulse-page-in` | Chromium 可在 transform 动画终止帧为 `none` 时仍保留 identity matrix，让 `body` 成为 fixed containing block | `body` 入场 keyframes 只允许 opacity，不得使用 transform/filter/perspective/will-change 等可建立 containing block 的属性 | Ink Pulse CSS 完整 keyframes 属性契约；滚动后真实浏览器验收 |
| `documents.py::_ensure_detail_rows/_finish_document_layout/document_layout` | 插行不会自动移动行高和打印范围；合并单元格不能按 nth-child 分配列宽 | 移动合并与行高、复制行样式、扩展打印范围；预览消费模板真实列宽 | 5/15 行双单据布局测试 |
| `documents.py::_inbound_detail_rows` | 同票副本不能重复增加入库数量；相同来源内重复行仍是真实明细 | 仅折叠完整明细一致的不同来源，冲突阻断且不重写 CSV | 重复来源与冲突导出测试 |
| `DocumentService.document_inbound_selection/export_inbound_document`（勾选身份由 `DocumentService._validated_inbound_selection` 经 `InvoiceSelectionService` 校验） | 页面草稿可能跨目录或列表身份已变化 | 同一锁内验证 target、key/path、真实源文件到逐票写出；已有文件跳过/副本 | 批量身份、缺明细、已有文件保护测试 |
| `page-documents.js::exportBatchInbound/loadPreview` | 写请求结果不确定时重试可能重复生成；旧预览可能迟到 | 不确定结果停止剩余且保留；请求序号拒绝迟到预览 | Node 停止、断网与预览竞态检查 |
| `documents.py::rmb_uppercase` | “零”的跨四位组规则非直觉，普通数字格式化不能替代 | HALF_UP 到分；万/亿跨组零正确 | RMB 零位测试 |
| `documents.py::_save_workbook` | 直接保存目标可能留下半写工作簿 | 同目录临时文件后 replace；占用错误上抛给用例层 | 单据导出/占用测试 |
| `targets.paths.path_is_under_root`（预览/打印服务与 DocumentService open/export 共用）| 客户端不能提交任意本机路径让服务打开/覆盖 | 路径由服务端计算且必须位于入/出库受控根 | 任意路径拒绝、出库范围测试 |
| `storage/files.py::atomic_write_json/write_csv_rows` | 状态和投影被并发读取，半写正文会造成错误恢复 | 同目录临时文件 + `os.replace`；保持 CSV BOM | monitoring/cost/API 相邻测试 |

## 9. P0：Windows 启停和发布

`local_http.rs::read_framed`：服务端成功状态不等于完整响应，完整响应也不要求 TCP 正常关闭；204 在响应头完成，Content-Length 在足量字节完成，chunked 在合法终止块完成。只在无明确 framing 时依赖正常 EOF，不能把 reset 普遍当成功。共同总预算防止慢分片拖延，重复身份头/长度冲突/截断继续阻断；守护为同文件的分片、reset、截断、真实保持连接和超时测试。

`backend.rs` 在失败清理前记录 Python PID、尝试次数、耗时和存活状态，避免用户把清理后的无监听误解为端口从未可用。错误不含 proof、challenge 或业务正文；守护为 HTTP error redaction 与 child 提前退出回归。`main.rs::start_surface` 的浏览器兜底只在已握手后的窗口错误上触发；用户等待时 child 可能退出，故确认后必须 fresh 重验，不能降级为只看 health.ok。守护为 accepted/declined/ownership_lost/browser_failure 的纯编排测试。

`main.rs` 的 setup 错误必须在 setup 闭包内部消费并提示：Tauri 将该闭包推迟到事件循环，直接返回 `Err` 会触发 panic，无法被 `Builder::build` 的错误分支捕获。清理 owned backend 后记录失败标记、展示诊断并请求退出；`--no-startup-dialog` 仅用于自动化且不能吞掉日志/退出码。守护为 `test_gui_setup_failure_is_presented_before_requesting_exit` 和实际冲突成品运行。

单实例路径必须在 runtime 尚不存在时解析最近的现存父目录，并统一 Windows extended path 前缀；否则首次启动与目录建好后的第二次启动会派生不同锁标识。守护为 `first_launch_and_existing_runtime_have_the_same_instance_key` 及全新隔离状态的重复启动验收。

启动冲突诊断：GUI host 没有可见 stderr，BAT 退出也会带走控制台，失败必须进入独立日志与原生提示；BAT 弹窗前释放 startup mutex，避免用户未关弹窗而阻挡重试。`startup_diagnostics.rs` 的监听查询不依赖 CIM；进程快照/health 自报只作线索，不能授予 ownership。官方单实例锁按 EXE/runtime 区分，防止测试包静默唤回另一个目录的正式包。`api/main.py` 在 app import 前检查端口，避免已知失败仍构造 AppState 并安排同步。守护为 Windows 真实监听与 PS7/PS5.1 冲突测试、Rust 路径锁隔离/监听 PID/字段白名单测试及 CLI 零业务初始化回归。

`InvoiceHub.Windows.psm1::Test-IHProcessIdentity`：Windows venv 转发到基础 executable 后会保留 venv 的 argv 首项。两者分别属于启动上下文的可信 Python 集合才允许继续匹配精确模块/root/config；不能以二者字符串相同作为前提，也不能省略任一匹配。守护为 `test_process_identity_accepts_venv_redirect_without_loosening_scope`（PS7/PS5.1、直接 Python、venv、release 单候选与外来 executable/命令/模块/目录/配置/额外参数负向）和正式根 BAT 启停。

| 文件与位置 | 应说明的原因 | 不能破坏的不变量 | 守护验收 |
|---|---|---|---|
| 根启动/停止/迁移 BAT | 名称是用户第一视图，两个停止入口语义固定，迁移必须是显式旁路动作 | stop 只停 WebUI；stop-all 才停 monitor；迁移只复制白名单设置 | 正式 BAT 与迁移矩阵 |
| 四个正式 BAT 的 PowerShell 选择 | PowerShell 7 可能来自固定 Program Files，也可能只由 Microsoft Store App Execution Alias 暴露在 `PATH`；固定路径缺失不能直接推导为只有 5.1 | 保留 `INVOICE_HUB_FORCE_PS51=1`；先验证固定 PS7，再安全解析并验证 PATH `pwsh.exe`，无可运行 7.x 才回退 5.1；参数原样转发 | 中文空格目录中的 PATH PS7/强制 PS5.1 动态 BAT 回归与成品真机验收 |
| `InvoiceHub.Windows.psm1::Get-IHHealth` | PS5.1 在 JSON 未声明 charset 时会用旧代码页解释 `Invoke-WebRequest.Content`，使真实 UTF-8 中文路径在 JSON 仍可解析时悄然损坏 | 从 `RawContentStream` 原始字节显式按 UTF-8 解码后再 `ConvertFrom-Json`；不放宽 PID、配置、runtime、build/package 身份 | 无 charset 本地 HTTP health 在 PS7/PS5.1 的中文空格路径动态回归、正式 BAT 身份闭环 |
| `InvoiceHub.Windows.psm1::Ensure-IHDirectory/Ensure-IHFileSlot` | runtime 目标可能被同名文件/目录占位 | 冲突先隔离且后缀不覆盖，父目录存在后再写日志/PID/state | 冲突路径、正式启动测试 |
| `Get-IHOwnedServer/Wait-IHReady` 及启动判重 | stale state/PID、同命令不同 root/config 和外部端口占用不能冒充本服务 | 首页、端口、PID、Python、模块、root、config、package/build identity 全部匹配 | 连点/并发/stale/占端口验收 |
| `Open-IHBrowser` | 系统壳成功派发已是本次打开成功；注册表只用于壳失败后备 | 同一 URL 最多派发一次，不因前台判断重复打开 | 正式默认浏览器验收 |
| `release/build_core.py` 的 Git snapshot/allowlist | 仓库含本机配置、运行态、发票和开发资产，工作树还可能有未跟踪文件 | 精确 clean commit + 明确白名单；本机 config 永远跳过；两次 ZIP SHA 相同 | release/source snapshot、ZIP 清单检查 |
| `release/verify_portable.py::_verify_windows_member` | 单仓库中的 `scripts/docs/requirements` 同时存在开发和另一平台内容，Python 完整 runtime 也携带非产品文档与机器绑定 launcher；只有顶层 allowlist 会允许这些文件伪装进已重写内容清单 | Windows ZIP 只接受精确文件/子树；macOS 路径、Swift/bundle、Mac 锁、Unix Python runtime 和大小写变体的 `python/Doc`、`python/Scripts` 先于内容清单校验 fail closed | release 反向注入参数化测试、Windows 成品验包 |
| `release/verify_portable.py::_verify_archive_structure` 的 `tests` 作用域 | 哈希锁定的上游 wheel 可以合法携带测试资料；全局按路径段拒绝会阻断未被裁剪的真实依赖，但全局放开又会让项目测试和基础 runtime 测试混入成品 | 仅大小写不敏感地允许 `python/Lib/site-packages/**/tests/**`；其它 `tests` 及全局禁用成员仍拒绝，获准文件继续执行依赖内容扫描并进入 runtime tree、逐文件 manifest、SBOM/锁身份和 ZIP SHA；不得按包名硬编码、裁剪 wheel/改 RECORD 或排除哈希 | 完整 ZIP 正向依赖测试、项目/基础 runtime/缓存/秘密反向注入、Task 4 wheel 来源证据和成品验包 |
| `WINDOWS_REPACKAGE_CONFIG.json` / `windows_release_config.ps1` | 版本、Python、包名、锁和证据目录散落在脚本/手册会让 Agent 拼出不同构建；把当前 commit 写入同一提交又会形成自引用 | 固定参数进入可哈希 JSON，并在任何 effectful 构建步骤前与 `version.py` 和派生路径核对；RC_SHA 始终由交接消息单独提供 | Windows release contract、source snapshot、构建收据与真机初始化 |
| `initialize_windows_repackage.ps1` / `verify_release_source.ps1` 的原生命令输出 | `Select-Object -First 1` 会提前终止 native 上游；全新严格模式进程可能因此没有当前作用域的 `$LASTEXITCODE`，预设为零又会掩盖真实失败 | 先完整捕获输出并立即保存退出码，检查成功后再取第一行；实时日志只使用完整消费上游的管道 | 全新 `pwsh -NoProfile` 成功/缺失远端引用动态回归、Windows release contract |
| `test_windows_release_contract.py` 的初始化器动态夹具 | pytest 临时目录可能位于小容量系统卷；直接读取该卷余量会让“fresh PowerShell 身份/receipt”测试在真实 RC 磁盘充足时仍偶发触发生产 10 GiB 门禁 | 只在测试子进程内覆盖文件系统余量：固定 20 GiB 验证成功与 receipt，低于配置阈值 1 字节验证 fail closed；生产配置和初始化器不增加测试开关、不降低阈值 | fresh `pwsh -NoProfile` 成功、缺远端、低磁盘三条动态回归；Windows release source gate |
| `prepare_windows_test_environment.ps1` | 源码门禁需要精确 3.14.6 和 pytest，测试子进程又可能覆盖父进程 `PYTHONPATH`；把测试依赖或源码绑定装入正式 runtime 会破坏 runtime tree 与成品最小依赖 | 独立 test Python/wheelhouse 同时安装 Windows runtime 锁与 test-tools 锁，并在其自身 site-packages 写受边界校验的 `.pth` 绑定当前 RC `src`；正式 runtime 只安装产品锁且不携带 `.pth` | Windows release contract、测试环境收据、monitor/API 子进程导入、Windows 真机完整回归 |
| `prepare_windows_runtime.ps1` 的产品 `Doc` 裁剪 | Python Manager x64 完整 runtime 没有 no-doc 变体，官方 SSL 文档含私钥示例，会被成品严格扫描正确阻断；放宽 scanner 会扩大真正凭据泄漏风险 | 保留只读 `base-python/Doc`；每次复制后只删除产品 `python/Doc`，并在依赖安装、smoke 和 runtime manifest 前完成 | Windows release contract、真实 runtime 双重建、portable 反向注入与 SHA parity |
| `prepare_windows_runtime.ps1` / `runtime_manifest.normalize_windows_runtime` | pip 26.1.2 vendored distlib 会把安装时刻和当前 staging 绝对解释器路径写进 console launcher；RECORD 哈希随 EXE 漂移，复用同一 runtime 的双组装无法发现 | 安装期间强制 `SOURCE_DATE_EPOCH=315532800` 并在 `finally` 恢复；随后删除产品不使用的顶层 `Scripts`，用 CSV 规则删除对应 RECORD 行，再生成 runtime manifest；不得从 tree/ZIP hash 排除这些差异 | 环境恢复/顺序契约、规范化幂等测试、不同目录真实 runtime 连续重建、在线/离线 ZIP parity |
| `scripts/dev/run_tests.ps1::Invoke-IHPythonCheck` | PowerShell 的 `$LASTEXITCODE` 会被下一个外部命令覆盖，延迟统一检查会把 pytest 红灯伪装成整体通过 | 每个 pytest/compileall 命令返回后立即 fail closed；后续检查不能掩盖失败 | Windows source runner 静态契约、GitHub Windows CI |
| `.gitattributes` / `build_windows_portable.ps1` 的源码归档 | `git archive` 会应用主机 Git 的文本转换；Windows `core.autocrlf=true` 可在相同 commit 下改变普通文本字节，而 Core Build ID 按字节计算；反过来用 `* text` 固定换行又会把既有 PNG/WebP/字体 blob 强制归类为文本并污染 checkout | 只用 `text=auto eol=lf` 固定自动识别的普通文本，二进制保持 `-text`，BAT/PS1 继续 CRLF；Windows archive 显式使用 `core.autocrlf=false`，不得以调整构建主机配置或强制全部文件为文本取代 fix-forward | 临时 Git 仓库保留历史二进制 blob，以 autocrlf=true 全新 checkout 验证 clean tree 和二进制字节，再以 true/false 实际 archive 验证二进制字节与 Core Build ID 均相同 |
| Windows handoff 文档中的 lock SHA | 已有 Windows 工作树可在属性变化后继续保留 CRLF 物理字节；从该工作树计算并固化 SHA 会让全新 LF RC 的 receipt 被错误阻断 | 期望 SHA 只取精确 RC 的 LF Git blob、禁用 autocrlf 的 archive 或全新 LF checkout；true/false fresh checkout 与 archive 必须都得到和 blob 相同的两份 lock，三份 handoff 文档引用同一固定 SHA，旧 CRLF SHA 必须消失 | Windows release lock checkout/archive 动态契约、Task 2 receipt 审计、三份 handoff 文档契约 |
| 发布契约中的隔离 Git checkout | GitHub `actions/checkout` 默认提供浅仓库；临时仓库从该源 fetch `HEAD` 时若不允许更新浅边界，会在真正校验换行与 archive 前因没有 `FETCH_HEAD` 停止，本地完整仓库则无法暴露该缺陷 | 保持 CI 浅历史；测试临时 fetch 显式使用 `--update-shallow` 继承已知边界，并在 `--depth 1 --no-local` 源仓库中动态回归，不以全局 `fetch-depth: 0` 掩盖夹具假设 | Windows release lock checkout/archive 契约、Windows/macOS GitHub Actions |
| `scripts/dev/generate_synthetic_release_fixture.py::main` | Windows CI 捕获 stdout 时子进程可能使用不能编码中文路径的本地代码页 | 机器可读 JSON stdout 必须保持 ASCII-safe；解析后还原 Unicode，磁盘上的 XML/OFD/README/manifest 仍为 UTF-8 | 强制 `PYTHONIOENCODING=ascii` 的中文路径发布回归 |
| `release/content_scan.py::scan_release_text/scan_release_tree` | 第三方 wheel 和 Framework 可能保留上游 runner 构建路径，按自有源码策略扫描会稳定误报；完全跳过又会放过高置信凭据 | 自有源码/core 拒绝凭据赋值与具体用户路径；仅哈希锁定依赖前缀允许 provenance 路径，GitHub token/私钥仍阻断 | release、source snapshot、Mac/Windows 发布契约与成品验包 |
| `_packaged_default_config` | 发布包必须可重建空目录且不能泄露本机业务路径 | 相对 `./发票文件`、`./运行状态`，recent 为空，OCR 禁用 | release 测试、真实包验收 |
| `settings_migration.import_settings` | 覆盖安装会混淆旧进程/缓存与新代码，整目录复制可能带入业务数据；迁移时重写有效显式启动方式会违背偏好可恢复性 | 新目录安装；只导入配置/偏好白名单；备份目标；保留有效导入的 `desktop` 或 `browser`，Windows portable 对新 desktop 选择的拒绝由运行时策略处理 | settings migration 单测与双合成包演练 |

## 9.1 P0：macOS 进程、桥接与构建握手

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `LocalBackendController.start/handleExistingBackend` | 一次控制请求失败不改变后端来源；匹配的存活 Process/PID 仍属于当前壳 | owned 不能被误降级 external；未知服务不能被提升 owned | Swift ownership 状态机测试 |
| `terminateOwnedBackendForAppQuit/finalizeOwnedBackendExit` | SIGTERM 已发送不等于进程已退出，提前清真值会留下无人管理写入者 | 仅确认 `isRunning=false` 后清 process/PID/ownership；删除 PID 做内容 CAS | Swift cleanup 与 Python 静态契约 |
| `WebOriginPolicy` 与 WK delegates | script message handler 注册在 WebView 配置级，外部页面/子框架不能继承原生能力 | 只允许预期 `127.0.0.1:<port>` 主框架；外部导航、message、open panel 拒绝 | Swift origin/navigation 测试 |
| `BuildHandshake.evaluate` | health 可能来自旧后端或源码 fallback，单向必需能力检查不能发现 manifest/health 漂移 | manifest_present=true；build/API/W9/能力/路径三方一致；health PID 必须为正整数 | Swift handshake、`test_build_manifest.py` |
| `BackendPaths` / `PythonCommandResolver` release 分支 | 当前目录或系统 Python fallback 会让正式 App 接入 checkout/本机环境且不可复现 | `InvoiceHubReleaseMode` 只接受 `Contents/Resources/invoice-hub-core` 与内嵌可执行 Python；core/marker 无效立即拒绝 | Swift release resolver 与 Mac 发布契约 |
| `verify_macos_release.sh::verify_macos_platform_boundary` | Mac 构建器当前复制列表虽精确，但真实分发资产仍需独立验证，不能只相信构建脚本或收据 | staging、Sparkle ZIP 和 DMG 内 App 都拒绝 Windows 脚本、锁与 `.exe/.dll/.pyd` runtime | macOS release 静态契约、真实三份 App 布局验收 |
| `prepare_release_runtime.sh` 的上游平台裁剪 | 固定 python-build-standalone runtime 自带三个 Windows shell helper，pip/distlib 还带六个 Windows console launcher；把整个 runtime 列为例外会让真实平台污染逃过分发门禁 | manifest 前只删除精确九项；随后全树扫描，任何其它 BAT/CMD/PS1/PSM1 或 EXE/DLL/PYD/MSI/MSIX 仍 fail closed；验包器不放宽 | macOS release contract、离线 runtime 复验、真实三份 App 平台边界 |
| `build_release.sh` / `verify_macos_release.sh` 的签名模式 | App 做 ad-hoc 不会自动让新建 DMG 容器带签名；无模式验签又无法区分 developer-local 与正式发行 | internal 在验证前对 DMG `codesign --force --sign -`，并要求三份 App 加 DMG 都是 ad-hoc、无 Authority/Team ID；formal 继续要求 Developer ID/Team ID/notary；两个 expect flag 精确互斥 | macOS release contract、内部实际 DMG artifact-only 验收 |
| `verify_macos_release.sh` 的内嵌 Python 检查 | 已签名 staging App 在首次验证后若被 `pip check`、import smoke 或 `content_scan` 新增 `.pyc`，首次可通过但普通复验会因 seal 漂移失败；`-I` 还会忽略 `PYTHON*` 环境变量 | 对所有目标 App 的 Python 命令同时设置 `PYTHONDONTWRITEBYTECODE=1` 与 `-B`；普通验证必须可连续重跑，artifact-only 通过不能替代 staging 幂等门禁 | macOS release contract、普通验证连续复跑、pyc 数量和 codesign seal 前后检查 |
| `InvoiceHubSparkleUpdater` 与 `LocalBackendController` 更新恢复 | Sparkle 替换 App 时旧 monitor 仍可独立运行，直接 relaunch 会留下旧 core 写入者；而 startup gate 尚未释放时更新 token 会故意拒绝恢复；外部兼容服务也不能被当前壳擅自停止 | 仅 current owned token 可安装、写标记、停/恢复 monitor；新启动先严格握手并转为 verified owned running、释放 startup gate，再可读取 marker 恢复；取消/失败恢复，external/失败启动不触碰 monitor | Swift marker/gate 生命周期回归、updater/bridge contract、真实取消/失败/成功升级 |
| `BackendLifecycleToken/BackendLifecyclePolicy` | shutdown、monitor、rebuild 和 termination handler 会在 await 期间交错；启动失败清理会自行 finalize 并推进一代 | 完成时 generation/phase/ownership/health/Process PID 仍匹配才可写状态；更新代次不可被覆盖，external 不可升级或停其 monitor；仅预期尝试的下一代 stopped 可恢复原始启动错误 | Swift 交错状态机测试 |
| `InvoiceHubAPIClient.verifyRequiredRoutes` | 数据型状态接口可能扫描阻塞的业务目录，不能作为构建兼容探针 | 实取静态页面；API 只通过有界 `/openapi.json` 校验注册 | Swift URLProtocol 测试、shell 静态契约 |
| 未签名开发 `.app` 的 TCC 目录授权 | 重建可能改变 macOS 识别的代码身份；严格握手按设计不扫描业务目录，因而可以在 `watch_dir` 不可读时仍通过 | 不把 `health.ok` 当目录权限真值；先用日志诊断，用户明确允许后经真实 `NSOpenPanel` 重选保存，并复验 `background_status=ready`、手动重建和源文件预览 | 真实开发 `.app` 与受保护包外目录验收 |
| `build_and_run.sh` stale PID 清理 | 探测期间新实例可能改写 PID 文件，读首行也可能错误接受混合内容 | 读取整个纯数字文件；旧/当前快照相同且旧 PID 已死才删除 | shell 静态契约、`bash -n` |
| `build_and_run.sh::server_argv_matches_expected_identity` | argparse 长选项缩写可以让额外 `--conf/--confi` 改变实际 config，但表面仍保留预期 `--config` | 只接受真实 `python -m invoice_hub.api.main`、唯一分离且精确的 `--config <path>`；TERM/KILL 前复用同一谓词 | Darwin argv 动态测试、shell 静态契约 |
| `api.__init__/api.main` | 包初始化发生在 `-m ...main` 执行前，急切导出会额外创建默认 AppState；argparse 默认接受长选项缩写 | 包级工厂惰性；CLI 禁用 `allow_abbrev`，root/config 生效后只实例化一次 | CLI 子进程守护测试 |
| `file_preview.py` 与 `page-index.js` 的预览闲置续租 | 票面渲染数据敏感且可能很大，但页面用 blob 展示时不会继续访问后端；固定创建时起算的 TTL 会在弹窗仍打开时过期 | 15 分钟改为闲置超时；成功内容访问和轻量 keep-alive 滑动续租；关闭弹窗停止续租；`404/410` 自动用原勾选快照重建并保留文件/页码；不放宽 watch_dir、源签名、作业数/页面/像素/缓存上限或持久化边界 | preview 服务/API/前端契约，macOS OpenAPI 严格握手测试 |
| `invoice_printing.py` 的短期 job | 打印票面数据同样敏感且可能很大，用户选择又可能在重建后指向不同文件 | 复核 `invoice_key + source_path` 和 watch_dir；TTL/数量/页面/像素/缓存上限；不写 SQLite 或投影 | print 服务与 API 测试 |
| `WebPopupConfigurationPolicy.installRestrictedPrintBridge/createWebViewWith` | WebKit 把新窗口的内部状态交给 delegate 回调提供的 `WKWebViewConfiguration`；另造配置会破坏该生命周期，直接继承又会泄露主窗口 bridge | 必须复用 callback 提供的 configuration，只替换其 user-content controller，并且仅注册 `invoiceHubMacPrint` | Swift popup configuration / origin / print policy 测试 |
| `WebPopupPolicy/WebPrintPolicy` 与 `WebView` 打印子窗口 | WebKit child window 默认会继承配置级消息能力，普通 popup 不能成为原生能力逃逸路径 | 仅 trusted main frame 的 exact about:blank；只允许同端口、无 query/fragment 的同一登记 print job 路径（可重载），子窗口只注册 print handler | Swift popup/origin/print policy 测试 |
| `PrintPopupRegistry/PrintPopupQuarantine/windowWillClose` | AppKit/WebKit 没有在关闭窗口后可安全释放整张 WKWebView 对象图的完成回调；在 close callback 或猜测的定时回合释放会触发 teardown 崩溃 | 关闭时先撤销消息接收并从 active registry 移除，再把 window、WebView 与 handler 强引用到进程生命周期 quarantine；SwiftUI 重建也不得手动清 delegate/config 或提前释放它们 | Swift popup quarantine 与 close-during-print 测试；2026-07-31 真实开发 `.app` 的系统面板取消和子窗口关闭无新增 IPS |

## 10. P1：兼容与跨层契约

| 文件与符号 | 建议解释 | 关联测试 |
|---|---|---|
| `common.js::api/beginActivity/setBusy` | 并发读取必须等最后一个响应 JSON 完成才收回提示；失败必须清理；轻量续租不能周期闪动；按钮原节点/尺寸/禁用态需要完整恢复 | frontend_interactions 的并发、JSON 失败、续租静默、重复 busy 与按钮恢复 |
| `common.js::bindNavigationTransitions/bindStickyControls` 与 app.css | 原生导航不额外延时或先清空页面；浏览器返回/取消要清理状态；皮肤 overflow-x:hidden 可能制造错误的 sticky 滚动容器，必须由 clip 和实测顶栏高度保护；预览、合计与关闭弹窗的 html/body 滚动锁必须高于这些全局 overflow 规则 | Node 导航恢复、预览/前端静态契约；真实桌面/窄屏、内置皮肤和 no-skin 滚动与弹窗 |
| `system-controls.js` 与 `common.js::connectEvents` | 全局电源总要确认，设置入口保留记住偏好；后端必须明确接受同一行为才结束 SSE，避免把正常关闭报告成断线；失败保留 WebUI 与选择 | Node 确认/取消/重试/归属/SSE、shutdown API、共享模板 HTTP 契约 |
| `api/app.py::_template` | 关闭片段只读取固定本地文件并在普通模板标记处注入，不能从 URL 接受模板路径；保持每页唯一弹窗与同一控制器 | business_pages_share_power_dialog_and_versioned_controls |
| `api/app.py::_resolve_event_stream_cursor` | 显式 `after`、`Last-Event-ID`、默认最新游标的优先级用于避免历史回放请求风暴 | SSE cursor 两项测试 |
| `api/app.py::cache_versioned_assets` | 只有带 `?v=` 的成功静态/皮肤资源才能 immutable；无版本资源不能长缓存 | 前端/API 静态契约 |
| `api/app.py::active_skin_link` | 服务端在 body 首次绘制前写入校验后的皮肤身份并加载 CSS，防止暗色换页闪白；backend/no_skin 必须跳过 | 皮肤页面注入、持久化与恢复 API 测试 |
| `appearance.js::prepareStylesheet` 与切换处理 | CSS 必须先成功加载才写入 skin 状态，失败不能持久化坏外观；切换已加载 link 保留业务 DOM 与未保存草稿；保存响应未确认不自动重试 | frontend_interactions 的加载顺序、双击、失败恢复和草稿测试；真实默认/深色/恢复入口 |
| `generate_desktop_icon.py` | 本地 OFL 字体和固定坐标避免主机字体造成图标漂移；纸白母版、Windows 多尺寸和 macOS 容器必须来自同一设计，tray 保持 8-bit RGBA | test_desktop_icon 的生成一致性、容器、透明度和小尺寸对比；Tauri IHDR 契约 |
| `web/static/css/app.css` 的设置移动端规则、做账和勾选合计基础规则 | 缺失媒体查询结束大括号不会删除选择器，却会让桌面端完全丢失基础布局并被皮肤通用规则覆盖 | 共享基础规则必须位于顶层；透明金额卡点击层、三列金额卡和弹窗网格不能只在窄屏生效 | 前端 CSS 大括号层级契约；Ink Pulse、无皮肤和真实桌面浏览器验收 |
| `page-costs.js::positionCostFormulaTooltip` 与 `app.css::.cost-formula-tooltip` | 按钮移到切换栏左侧后，固定 `right:0` 的 460px 浮层越过视口左缘；皮肤 `:is()` 无法匹配 `::after`，深色下箭头保持白色 | 每次 hover/focus 实测并夹在视口 12px 内、避开 `.topbar`，上方不足翻到下方，仍不足则限高由 `__body` 滚动（不裁箭头、不用 `overscroll-behavior: contain`）；浮层内部滚动不触发重算以免 `scrollTop` 归零，`::before` 悬停桥覆盖按钮间隙，`max-width` 按 `clientWidth` 写入；箭头 `background: inherit` | 前端静态契约；无头 Chrome 多宽度/翻转/矮视口与默认、no_skin、Animal Island、website-dark 实测 |
| `web/static/css/app.css::.detail-cost-body` | 有界 Grid 会把多个隐式 `auto` 行压到容器高度内；项目卡又用 `overflow:hidden` 收圆角，结果是汇总卡占满项目、规格表被静默裁掉且外层没有可滚动溢出 | 隐式项目行使用 `max-content` 并从顶部排布；单项目表格保留自身有界滚动，多项目高度交给外层 `overflow-y:auto`，纵向滚动链仍为 `auto` | 前端静态契约；Ink Pulse、Animal Island、`?no_skin=1` 多项目真实浏览器尺寸与滚动验收 |
| `invoice_print.html::waitForImage/waitForPrintableFrame/requestBrowserPrint` | `load` 早于图片解码/首次绘制时会让首次打印预览抓到空票面；固定 A4 会覆盖 A5，打印态 `100vw/100vh` 又会随预览页框重算形成反馈，表现为持续加载/跳动或额外空白页；浏览器仍只暴露打印对话框近似生命周期 | 首印等待 `decode()` 与两次渲染帧；命名页只声明方向；票面使用页框百分比且只在后续票面前分页；文案不得把对话框打开写成打印成功 | 打印前端契约 + Chrome/Edge A4/A5 真实验收 |
| `targets/paths.py::target_id_for` | casefold 的目录身份是 Windows 语义，16 位只作档案目录 | paths 测试 |
| `targets/paths.py::serialize_config_path` | 项目内相对保存用于便携，包外绝对保存用于用户目录 | settings/documents 路径测试 |
| `summary.py::summary_schema_needs_refresh` | CSV 与 XLSX 必须一起检查，旧表头会触发后台自愈 | summary schema 测试 |
| `CostProjectionService.needs_schema_refresh/refresh_schema_from_current_detail` | 仅表头升级时不应重解析全部源票，且必须保留状态 | cost schema refresh 测试 |
| `_sync_status` | 成本同步按同票来源组而非文件数统计 | same-invoice format count 测试 |
| `InvoiceListService._summary_rows` | `mtime_ns+size` 只做进程内 CSV 读取缓存，不是源发票变化真值 | API 列表/后台同步测试 |
| `platform/windows.py::run_native_dialog` | 子进程 cwd 必须是项目根，避免 config 目录破坏模块导入 | picker mock + Windows 真机 |
| `release/build_manifest.py::deterministic_build_id/load_build_manifest` | 构建身份必须覆盖实际共享输入，字段缺失不能伪装成兼容包 | 排除本机缓存；无效清单返回 manifest_present=false；capabilities 不丢失 | build manifest 测试 |
| `release/package_manifest.py` 与 `runtime_manifest.py` | 仅 core build 相同不能证明平台包、Python 或依赖相同 | package ID/平台/架构/类型/source/lock/core 闭环；runtime tree SHA 与 import probe 对应 | identity/dependency/release/Mac/Windows contract |
| 退休包的 embedded `source_commit` 与公开历史净化 | 重写公开 ref 会生成不同 commit SHA；若仍把退休包挂到新 Tag，会让 Release 表示的源码与包内身份不一致 | 退休包只留在私有备份；公开二进制必须从新版本重新构建，并在获授权的 all-ref 验证后发布 | 历史净化执行记录、release identity/provenance tests |
| `UpdateService.fetch_update_feed/check` | 更新检查发生在本地业务进程内，任意 URL、DNS/代理卡死、慢重定向正文、实例检查锁排队或坏缓存都可能扩大攻击面或阻塞使用；调用方 wall deadline 与操作系统何时调度 daemon worker 是两个独立时序，短预算测试不能把后者误作前者的前置条件 | 固定 HTTPS 白名单和重定向复核；3s/5s/256KB；总时限覆盖 DNS/代理、headers、redirect 和逐块 read，redirect body 直接关闭；不可取消 transport 至多保留一个 worker；deadline 测试先测调用方返回耗时，再独立等待 worker/gate 收尾；实例锁 nonblocking，忙碌调用只返回非持久化 offline，不覆写 checking/cache；失败保留最后有效 ETag/feed 且不享受成功 TTL | update service host/timeout/cache/error/worker-gate/并发 service-check 测试 |
| `parsers._is_synthetic_release_fixture` | Windows/macOS 发布主机可共同使用的 PDF fixture 需要内置 Latin 字体，但泛化英文标签会把普通业务 PDF 误投影为发票 | 只有固定双 synthetic marker 同时存在时才启用其英文别名；普通英文 invoice-like 文本必须留空 | synthetic fixture 与 ordinary-English negative release tests |
| `update_metadata.generate_release_metadata` | 手工构造的 provenance 或分别调用格式化/写盘函数会绕过发行前身份门禁 | 唯一公开生成入口先 finalizer 再格式化/写盘；私有 helper 不是授权机制，公开权限由受保护的 Release/Pages 凭据控制 | update metadata orchestration/parity 测试 |
| `source_snapshot.inspect_tagged_source_tree` / `release/provenance.py::_verify_sparkle_embedded_core` | 归档 manifest 可以自称任意 tag，checkout 工作树也可能有未跟踪内容，ZIP 同名条目或盘符路径会让“读取到的 core”与用户预期不一致 | 公开 Feed 只能接受固定 Tag commit `git archive` 重建后与归档在 commit/tree SHA/文件数/core build 全部相等；Sparkle ZIP 必须无重复、加密、链接和不安全路径 | source snapshot 与 release provenance 回归 |
| `scripts/dev/tauri_version_sync.py::synchronize` | Tauri 的 Cargo、JSON 和 npm 都有版本字段，手动并行维护会让 shell、installer 和 Feed 获得不同产品身份 | `version.py` 是唯一产品版本来源；`--check` 发现任一派生字段漂移必须失败，`--write` 是唯一写派生字段入口 | `tests/test_tauri_foundation.py` 的同步/单点 drift 回归 |
| `scripts/dev/tauri_doctor.py::evaluate` / `tauri_bootstrap.py` | 开发机缺少 Rust、pnpm、证书或平台 SDK 时，自动安装会改变开发机信任和签名状态，且会把环境偶然性伪装为项目准备完成；rustup 与 Corepack shim 甚至可能在普通 `--version` 探测时下载缺失工具，而两者也会按子进程 cwd 选择 toolchain/package manager | 默认只报告版本、锁、固定 origin 和 SDK；全部 probe 与版本同步从请求的项目根启动，Rust/Cargo probe 强制 `RUSTUP_AUTO_INSTALL=0`，pnpm probe 强制 `COREPACK_ENABLE_NETWORK=0`，`--require-ready` 缺 Rust/Cargo/Cargo.lock 必须非零，只有显式 `--install-js` 能消费已有 pnpm lock | Tauri doctor fail-closed、root cwd、rustup 与 Corepack 环境传递回归；受控工具链到位后才运行 Rust 聚焦测试 |
| `tauri_doctor.py::_find_executable/_windows_sdk_check` | 普通 Visual Studio/Build Tools 会把 `vswhere.exe` 安装到固定 Installer 目录而非 PATH；`vswhere -latest` 的零退出也可能只是没有匹配实例，或匹配实例没有 C++ workload；没有 `ProgramFiles(x86)` 时把 SDK 路径相对化会把调用目录误作系统 SDK | Windows 只在固定 Installer 路径或 PATH 找到 `vswhere` 后，要求 `Microsoft.VisualStudio.Component.VC.Tools.x86.x64`、非空安装目录、`ProgramFiles(x86)` 和实际 Windows Kits Include 版本目录；否则 `--require-ready` 必须继续失败 | Tauri foundation 的 bundled-vswhere、MSVC/SDK 和缺 Program Files 诊断回归；Windows 真机仍需验证真实 toolchain |
| `tauri-doctor.ps1` / `tauri-bootstrap.ps1` | PowerShell 找不到外部 `python` 时不会可靠设置新的 `$LASTEXITCODE`，直接转发或退出旧值会把未运行的诊断误报成功 | 先解析 `py`，再解析 `python`；两者均缺失显式 `exit 2`，外部命令后空的退出码也归一为失败 | Tauri foundation PowerShell fail-closed 静态契约；Windows 真机验证包装器 |
| `.cargo/config.toml` | 直接 Tauri crate 的声明 MSRV 不会自动限制 Cargo 默认选择较新的传递依赖，首次解析已选择 Rust 1.88 依赖而违背项目的 Rust 1.85 约束 | 保持 `incompatible-rust-versions = "fallback"` 并提交审查过的 lock；不得手工篡改传递依赖或因刷新 lock 随意升级工具链 | Tauri foundation lock contract、受控 `cargo check --locked` |
| `src-tauri/src/main.rs` checkout guard、`BackendHost::launch`、`startup_surface` 与退出收束 | 精确 crate/lock 不能把源码 checkout 变成可连接的 host；child/watch/handshake/setup 任一步漂移都可能授权未知服务；Tauri/AppHandle 引用环使 `Drop` 不能承担退出；predefined Quit 可绕过 `ExitRequested`；更新重启若重复关闭已停止 backend 会把正确 relaunch 当普通失败，而普通 Quit 若穿过 active commit 又会中断不可逆事务 | manifest 缺失状态 `78`；fresh HMAC/identity 后 arm watcher；surface 失败先 structured shutdown/kill+wait，全部成功才 release gate/manage，updater activation 再晚于 manage。普通 ExitRequested 在 commit reserved/executing 时 prevent，其他普通退出 structured keep-monitor；只有 `relaunch_prepared` 跳过重复 shutdown。禁止 predefined Quit，外部终止不作承诺 | lifecycle 静态 guard/order/menu/setup/update-exit contracts、locked binary check 与既有 Cmd-Q smoke |
| `src-tauri/src/monitor_recovery.rs` | updater/relaunch 期间若只凭 PID/路径停止 monitor，child exit、路径替换或 stale marker 会触碰外部 monitor，失败后也可能丢失原运行义务 | 每个 marker/bridge 操作前后复核 released lease；只暂停 ready monitor，已有/损坏/跨 scope marker 不覆盖。Store 固定从 strict identity `runtime_dir` 打开；Unix descriptor/no-follow/flock/directory-sync 与 Windows handle-relative/no-reparse 不变量不变。startup restore 只有 later `running && ready` 才清 marker，失败保留 marker、WebUI/backend 诊断和 updater failed 状态 | recovery contract 加 startup activation/order lifecycle contract；L10-E macOS arm64 marker/runtime 样本已通过，Windows 与真实更新事务仍待验收 |
| `src-tauri/src/monitor_bridge.rs` 与 `api/app.py::_monitor_recovery_response` | 固定 endpoint 不是 ownership proof；把 bearer secret 发给候选端口、只验请求不验响应、允许 body/replay 或宽松解析都会让错误进程伪造恢复结果 | 固定 enum/loopback/空 body/有界超时；backend-private secret 不发送，fresh challenge 对 request domain+method+path+empty-body hash 做 HMAC，response 再绑定 exact status/body hash；Python 拒绝 incomplete/tampered/non-empty/replayed 请求，Rust 拒绝 missing/duplicate/tampered proof 并常量时间验证。普通 bridge 调用保持原语义 | Rust bridge 10 项与 Python auth valid/tamper/replay/body contracts；L10-E 已调用隔离 owned monitor 的 authenticated start/status 与普通 stop，未调用真实更新事务 |
| `src-tauri/src/update_coordinator.rs` | 将未验签 bytes 交给 installer，或吞掉 pause/install/relaunch 的恢复错误，会把不可逆动作放在证据边界外并留下停机状态 | `VerifiedUpdate` 只能由 Tauri `Update::download` 内置验签后的 promotion 产生；严格 download+verify -> pause -> install -> relaunch，并同时保留 primary/restore。Coordinator 仍纯 trait，Host adapter 才持有真实 `Update`/bridge/platform relaunch | coordinator unit/contract 与 Host RPC wiring static contract；真实 updater/install/relaunch 仍待授权 |
| `src-tauri/src/backend.rs::BackendLifecycleAuthority` | 为 recovery seam 复制 child/ownership/lifecycle 状态会让 lease 与 host 真值漂移，clone 也可能只复制句柄而漏掉代次验证 | authority 只 clone `BackendHost` 已有 `Arc` 和 child PID；capture/revalidate 继续检查 generation、phase、startup gate、health/owned/process PID 和 state scope | backend lifecycle unit tests、`test_tauri_lifecycle_contract.py` |
| `backend.rs::load_bundle_manifest/compiled_bundle_manifest_hash_matches` | 只检查 manifest 是否存在会让源码 checkout、替换过的 bundle manifest 或错误 bundle root 获得同一 host 启动路径 | 必须对原始 manifest bytes 做 SHA-256，并与只在 staged-manifest 签名 host 编译时注入的 `INVOICE_HUB_BUNDLE_MANIFEST_SHA256` 完全相等；缺值、缺文件或任一字节差异均在连接/窗口前 exit `78` | lifecycle Rust manifest-hash contract 与 locked offline desktop check |
| `tauri_dev_app.py`、development schema-3 manifest 与 `INVOICE_HUB_DEV_STATE_ROOT` | 裸 checkout 不应因为测试方便而读取用户 Application Support 或可连接任意 localhost；把工作站路径写入 manifest 又会让同一构建在另一用户下失真，state root 落入 bundle、macOS `.app/Contents` sibling 或包住 bundle 又会污染资源 | development assembler 只 stage allowlisted core、绝对 venv launcher 及其 SHA，host 只接受显式、已存在、绝对、canonicalize 后与 bundle/core 和完整 `.app` 容器双向不包含的 development state root，且在启动 Python child 前清除；release/缺失/相对路径 fail closed | L8-S `.app/Contents` sibling path/child-environment contracts 与一次隔离 L9 smoke |
| `backend.rs::updater_from_json`、`tauri.dev.conf.json`、`tauri_dev_app.py` recovery 变体与 `tauri_recovery_smoke.py` | 为验证 startup restore 而打开通用 development updater 会把任意 Feed/key 误带进脏工作树，也可能让 runner 自己触发 check/install 后把恢复样本误写成更新证据；插件配置缺省为 `null` 又会在 runtime manifest 覆盖前退出 | ordinary development/internal-alpha 始终 disabled；development enabled 只接受固定不可达 HTTPS loopback endpoint、无验签能力 sentinel 和精确三字段对象。overlay 空 `pubkey` 只提供可反序列化对象，不含 endpoint/权限；hash-bound manifest 和 Rust parser 再提供精确 sentinel。runner 预写 `auto_check_updates=false`，只允许 health/status/stop，按 plist/manifest/health/path 身份确认后才 stop，并仅清理自己创建的进程组 | Rust exact-tuple/extra-field test、development staging/plugin-placeholder tests、recovery runner plist/allowlist/path/identity contracts，以及 L10-E macOS arm64 startup-recovery 样本；真实 Feed/download/install/restart 不在样本内 |
| `platform/host_rpc.py::_send` | 默认 `urllib` opener 会读取 `HTTP_PROXY/http_proxy`；即便 Host RPC URL 已被校验为 loopback，bearer token 仍可能被交给环境代理 | 为每个 private Host RPC 请求创建 `ProxyHandler({})` 的 opener，强制直连已验证的 private loopback listener；保留固定 enum、origin、超时与脱敏错误，不把 token 带入任何代理或日志 | `test_tauri_host_rpc.py` direct no-proxy transport contract |
| `src-tauri/icons/icon.png` | Tauri 的编译期 context 可以接受 PNG，但 macOS tray 在实际初始化时要求可用的 8-bit RGBA 数据；16-bit RGBA 只在首个真实 app launch 暴露问题 | 图标保持 8-bit RGBA，并用 IHDR 回归锁定位深/颜色类型，避免把 tray 初始化异常误归因为生命周期或端口错误 | Tauri icon IHDR contract 与 L9 development app smoke |
| `host_rpc.rs::HostUpdater` 与 `AboutService.check_for_updates/install_update`（`services/about.py`） | 普通 cache 检查不能授权安装；无时限网络、caller metadata、响应前副作用、并发 commit 或平台退出差异都会造成越权、悬挂或半更新 | Hosted API 保持 strict fresh-200/version approval 和非阻塞锁；HTTP install 只接 `{}`/脱敏 503。Host metadata/download 5 秒，完整 `Update` 和域分隔 artifact ID 不公开。Enabled runtime 只在 gate release/manage 后 startup restore；install 原子 consume/reserve，spawn latch worker，flush exact success 后 execute。writer/spawn/latch loss `CommitLost` 无副作用；coordinator 执行 verified download -> pause -> install -> relaunch，Windows callback 与 macOS prepared restart 分开；active commit 拒绝并发与普通 Quit | Host RPC deferred commit/disabled/concurrency/artifact tests、lifecycle/static/API contracts；真实 Feed/update 仍待平台验证 |
| `AboutService.check_for_updates` 的 hosted lock-contended 分支 | 只读 busy 结果若仍穿过统一的 `append_event`，会等待 SQLite 写入，破坏“立即/非持久化”并使锁竞争成为可被存储压力放大的路径 | 竞争分支在 `busy_result()` 后直接返回，不调用 metadata/candidate、不清 approval、也不写 `updates.checked`；成功与非竞争检查保持既有事件语义 | Host RPC Python blocked-append-event 并发样本 |
| `platform/host_rpc.py` 的 picker 预算与 `api/app.py` 的四条 picker route | Rust dialog 可以合法等待 120 秒，较短 Python timeout 会在原生面板仍有效时伪造失败；未经映射的 private channel 错误会使外部响应语义漂移或泄露连接细节 | Python 等待 125 秒，保留 5 秒响应余量且不无限等待；四条 route 只将 `HostRpcError` 固定映射为脱敏 503，未配置 Tauri 时仍走既有 Tk | `test_tauri_host_rpc.py` timeout/route 静态契约与 FastAPI picker runtime contract |
| `release/provenance.py::_verify_macos_distribution_artifacts` / `verify_macos_release.sh` / `verify_sparkle_update.swift` | macOS 收据可记录构建期结果，却无法证明发布时的 DMG、ZIP 或 Ed25519 sidecar 尚未被替换；checkout 工作树脚本也不是 Tag 版本发行物的信任根 | finalizer 只接受 schema 4、`developer-id-notarized`、`com.invoicehub.release` 与 v4 verifier，从已解析固定 Tag 取验证器并用 `--artifact-only --expect-notarized` 验证实际 DMG/ZIP；已签名 App 的 `SUPublicEDKey` 必须匹配后才验 ZIP 原始字节，内部收据与布尔值仅审计 | release provenance、metadata CLI、macOS release contract；真实 Developer ID/公证/DMG/Sparkle 成品验收 |
| `bookkeeping.status/mapping_migration` preview/apply | 预览与执行之间资源可能变化，迁移又不可静默丢历史状态 | 同锁重验所有 SHA/revision/binding/backup；启动时不自动迁移 | bookkeeping migration 测试 |
| `bookkeeping.batches.finalize` | 页面未看到结果不能证明未入账，重复观察必须幂等 | success/failed/unknown 证据互斥；同 observation hash 重放原 receipt | bookkeeping export/finalize 测试 |

## 11. P2：大型文件导航注释

这些注释适合在未来拆分模块时增加短区块标题，不应单独制造批量 diff：

- `services/app_state.py`：组装根；只保留锁/活动目标/config、health，以及切换 watch_dir 与删除所选两条跨域编排，领域服务以公开属性暴露、路由直接调用（ENG-08）。各用例区见 `services/` 下的领域服务（文件地图逐一列出）。
- `projections/cost_analysis.py`：格式清洗、均价/详情拆分、加价/快照、PDF 坐标、XML/OFD 明细、状态兼容、分组/工作簿七个算法区。
- `web/static/js/page-settings.js`：只在真实拆分模块时为目录、运行、皮肤、偏好、关闭、诊断区保留导航标题。
- Windows 启动器：预检、判重、进程启动、就绪探测、状态写入、浏览器派发的阶段标题。
- `bookkeeping/`：状态仓储、提案/决定、映射、迁移、导出和批次观察区；只在真实拆分时补导航标题。
- `LocalBackendController.swift`：探测/启动、严格握手、owned 控制、显式关闭和 App 退出收束阶段。

区块标题必须稳定描述用例，不写“下面做某某”的流水账。

## 12. 推荐注释形态

一个高价值注释通常只需一到三行：

```python
# invoice_key is a row position, so source_path must be revalidated after rebuilds.
# Otherwise a stale browser selection could target a different invoice.
```

兼容原因可以这样写：

```python
# Read both SHA1 and legacy plain keys; existing watch directories may predate
# the hashed status format. New writes always collapse aliases to the SHA1 key.
```

跨功能流程可以这样写：

```python
# 先提交成本投影，再发送 `costs.updated`：页面收到事件后会立即重读该文件。
# 若先发事件，页面可能读到半写入状态并将其显示为同步成功。
```

不要把 `Why/Invariant/Compatibility` 模板机械复制到每处。能用更清楚的函数名、数据模型或拆分消除困惑时，优先改结构；注释只保留无法从局部代码推出的原因。

## 13. 后续逐点补注释流程

1. 在本页找到被修改符号和优先级。
2. 回看对应测试与 `CHANGELOG.md` 历史，确认原因有证据。
3. 先确认上游输入、下游消费者、顺序/不变量和失败后果；在最靠近交接或保护分支的位置写简短注释，不要在文件头重复整篇架构文档。
4. 若代码行为已改变，先更新本页的原因和不变量，再写源码注释。
5. 跑表中守护测试及任务导航要求的相邻回归。
6. 在 CHANGELOG 说明补了哪个设计原因、验证了什么，而不是只写“增加注释”。

## 14. 注释审查问题

- 删除这条注释后，熟悉语言但不了解业务的人会误删哪个保护？
- 注释描述的是当前代码和测试能证明的事实吗？
- 它是否解释了为什么，而不是逐字翻译代码？
- 跨功能流程中，开发者能否从注释立刻识别输入来自哪里、结果由谁消费，以及为何不能改写当前顺序？
- 交接失败、乱序或绕过校验时，注释是否说明会破坏的状态、用户可见结果或安全边界？
- 是否包含会很快漂移的数字、路径、分支状态或样本规模？
- 行为变化时，关联测试会失败并提醒更新注释吗？
- 它是否意外承诺了未启用能力，例如正式 OCR、云部署或 SQLite 发票主存储？

## 14.1 独立官网交接约束

`version.py` 将 `LOCAL_WEBSITE_PATH` 与远端 `WEBSITE_URL` 分开，防止官网本地化把更新 Feed 一起改成本机地址；设置 JS 仅为官网放行固定相对路径，下载仍要求 HTTPS。`website.py` 的资源清单被 HTTP 与各组装器共同消费，防止漏带离线字体/图标或公开维护目录；路由跟随选定 Web bundle，返回脱敏缺失提示。导航同窗口进入官网，只在 localhost 的 `/website/` 下提供返回设置，避免依赖桌面壳弹窗，也不影响未来公网导航。守护包括 Node 导航脚本、官网资源 unittest、API 与 build manifest 契约。

`website/demo-data.js` 的入口注释限定合成数据与业务 API 隔离；`website/app.js` 在筛选、合计和 CSV 导出交接处解释可见选择重验与合成来源边界，并在 dialog 打开处说明双滚动根锁定。`website/paper-scene.js` 在动画调度处说明 30 fps、屏外和后台停止，以免官网占用持续业务处理资源。`website/scripts/preview.cjs` 只服务官网目录，不能把仓库或发票目录当静态根。对应守护为 Node 演示/资源契约，真实滚动、焦点与画布验收需浏览器；本轮未获访问许可，不声称已覆盖。

内容补充在 `summarizeDetails` 说明票头与明细独立口径，在 `printPlan` 说明缺 PDF 整批阻断且官网仅动画；五层 Canvas 缓存处说明独立移动与文字清晰度，命中区/键盘/触屏交接注释说明不影响标题操作且减少动态效果直接切换。相邻守护为明细多维分组、PDF 回退/阻断、税额分位守恒和动画收敛测试。做账和 OCR 状态文案依据当前源码；独立税率计算器只称概念预览。

触屏 `pointerleave` 先于 click，不得像鼠标离开那样提前清除 pinned 状态，否则第二次轻点无法归拢；最近分支注释与 Node VM 连续轻点断言共同守护。

## 15. 相关入口

- [开发架构总入口](../DEVELOPMENT_ARCHITECTURE.md)
- [平台架构](PLATFORM_ARCHITECTURE.md)
- [完整文件地图](FILE_MAP.md)
- [接口与运行流程](INTERFACES_AND_FLOWS.md)
- [数据结构与算法](DATA_AND_ALGORITHMS.md)
- [Agent 任务导航](AGENT_TASK_MAP.md)
