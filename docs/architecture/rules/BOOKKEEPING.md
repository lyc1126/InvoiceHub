# 业务资料夹与做账规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：W8/W9/W10、凭证、映射、审批、导出、迁移、批次观察与捷锐。
- 代码与验收定位：bookkeeping/、runners/；接口流程第 3.5 节、数据算法第 3.2、4.5 节、任务导航第 10.2 节。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-bookkeeping) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

## 做账（bookkeeping）规则

- 做账数据真值全部在公司资料夹 `凭证/` 下，包括 `账套配置.json`、`科目表.json`、`辅助核算档案.json`、`科目映射.json`、`凭证生成状态.json`、`批次/` 和 `日志/`；真实业务数据不得进入仓库。仓库只保存结构性 `docs/jierui` facts/selector、确定性生成代码和随包 runner。
- `凭证生成状态.json` 只允许 InvoiceHub 后端通过严格仓储、跨进程写锁和单调 revision/CAS 写入；合法 JSON 但 schema 错误、未来版本或结构损坏时必须保留原文件、写诊断并停止后续写入，不得把异常状态当空对象覆盖。
- v1 状态必须先 preview，再以源文件 SHA256 和 `confirm=true` 显式迁移到 schema v2；禁止启动时自动迁移。迁移不得静默丢弃已审批、已导出、已入账或存在冲突的历史项。
- 业务身份使用稳定 `posting_key = SHA256(company_id + event_type + anchor_business_key)`，不得包含全局规则版本、科目、日期或生成时间；可变证据、规则、科目/辅助档案和完整分录必须进入 `proposal_revision_hash`。规则变化只能产生同一业务事件的新 revision，不能产生第二个可执行事件。
- 审批和导出必须复用 `VoucherExecutabilityValidator`，客户端状态、`review_tier`、历史 `approved` 或页面按钮均不能绕过服务端复核。至少校验账套/期间、来源文件 hash、proposal revision、Decimal 到分、借贷平衡、科目存在/启用/末级、必要辅助核算、税务证据、重复业务键和未完成批次；阻断项必须以结构化 `blockers[]` 返回并在前端持续展示。
- 导出必须携带 store revision、精确 proposal revision 和显式 item 清单，只允许单一账套、单一期间；先生成不可变 `凭证/批次/<batch_id>/manifest.json + 凭证导入.xlsx`，绑定 facts/科目/辅助档案指纹、行号、计划凭证号、signature 和文件 SHA256，再以一次状态写入关联整批凭证。XLSX 或任一绑定事实变化后原授权立即失效。
- 凭证执行状态必须覆盖 `exported -> importing -> imported | import_failed_confirmed | import_unknown`；批次观察只允许通过幂等 finalize API 整批回写。同一 `batch_id + observation_hash` 重放返回原 receipt；`import_unknown/partial` 只允许后续 `reconcile-only` 只读查账推进，禁止再次导入或把已确认终态降级。确认成功必须覆盖 manifest 全部项目、每项 `observed_state=imported`、凭证号/signature 匹配并携带 `readback_hash`；同时声称 `commit_not_attempted=true` 或 `ledger_absence_confirmed=true` 必须按证据矛盾拒绝。确认 `import_failed_confirmed` 必须证明未点击提交，或携带完整逐项未落账观察、`readback_hash` 和 `ledger_absence_confirmed=true`，不能把“没有看到结果”当成“确认失败”。
- 旧 `PATCH /api/v1/bookkeeping/import-result` 固定返回 HTTP 410 `BATCH_FINALIZE_REQUIRED`。runner 只接受显式 `--batch-manifest`，不得猜测最新 XLSX，也不得直接写状态 JSON；W8 只开放 batch-bound dry-run，真实 Safari `apply`、读回和 `reconcile-only` driver 属于 W10，且每次真实 apply 仍需用户在当回合明确授权。
- 捷锐 facts 使用 `template/grouping/voucher_type/numbering/decimal/aux` 六项独立 readiness；只有 `ready` 能放行所需能力，`not_tested/unsupported/failed` 都必须阻断。未实测的「记」类别、自动编号、小数、分组和辅助核算不得写成既定事实。
- W8 是安全协议与状态底座，不等于 W9 的正式账套 profile、科目/辅助核算和映射人审闭环，也不等于 W10 的真实测试账套导入。代码验收不得自动获得真实状态迁移、审批、导出或账套操作授权。
- W9 的账套 profile、科目表、辅助核算档案和科目映射必须绑定同一 `company_id + ledger_environment + ledger_identity_sha256`；profile 还必须绑定当前科目/辅助目录文件 SHA。测试账套与正式账套、旧采集批次与新采集批次不得混用；绑定不一致时必须停止审批、导出和迁移。
- 映射保存前必须基于当前 CSV 投影和当前/候选 resolver 结果生成零写影响预览；保存时必须重验来源投影、rules/profile/catalog/store 的资源级 CAS，且不得静默覆盖 `manual` 或 `ai_confirmed` 规则。规则变化只能重算 resolver 胜者、胜者指纹、歧义或未命中结果发生语义变化的凭证；无关全局映射版本不得进入 proposal hash。
- 显式 recompute 和映射保存如果得到相同 proposal，不得改写凭证文件或重置 `blocked/rejected`；如果 proposal 变化，只能在同一 `posting_key` 下生成新 revision 并使旧审批失效。
- 映射 v1→v2 与凭证状态 v1→v2 迁移都必须提供确定性 preview hash，apply 必须在同一写锁内重验源 SHA、preview hash、source revision、profile/目录/映射绑定、待重确认数和命令身份；必须保留并校验精确备份 SHA，迁移 revision 只能单调增加。
- 捷锐外部页面自动化不在公开源树保留真实选择器、页面地址、坐标、账套或实测记录。W10 driver 只能在用户当回合明确授权后，于受控测试环境重新采集私有事实；公开源码不得据此自动写入外部系统。
