# InvoiceHub 注释与设计原因地图

> 本轮状态：只登记注释债，不批量修改生产源码。
> 公共权威基线：单一脱敏根提交；旧私有提交、Tag、包和验证材料不在公开图中。
> 当前边界：`v0.3` Tauri 需要新增 Host RPC/updater 的专门原因说明，但不能借机重写共享业务核心。
> 原则：注释解释“为什么必须这样做”和“破坏后会发生什么”，不复述 Python/JavaScript/PowerShell 语法。

## 1. 为什么先做地图而不是批量加注释

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

不应当注释：

- `x += 1`、`return payload`、遍历列表等语法复述。
- 只重复函数名或类型标注的 docstring。
- 没有代码/测试证据的历史猜测。
- 易漂移的行数、测试总数、当前样本数量或本机路径。
- 用 TODO 代替明确任务和验收条件。
- 对每个字段逐行生成相同句式的“保存某某值”。

## 3. 注释优先级

| 优先级 | 含义 | 处理时机 |
|---|---|---|
| P0 | 数据污染、文件破坏、进程竞态或安全边界 | 下一次触碰该符号时必须补，并跑守护测试 |
| P1 | 兼容、跨层契约或非直觉算法 | 下一次行为变更或重构时补 |
| P2 | 导航性解释，可降低大型文件理解成本 | 拆分/重排模块时补，不单独制造大 diff |

## 4. P0：AppState 编排与事务

| 文件与符号 | 应说明的原因 | 不能破坏的不变量 | 守护测试 |
|---|---|---|---|
| `services/app_state.py::_run_background_sync_process` 与 `AppState.run_background_diagnostics` | PyMuPDF 等原生解析可能长时间占用 GIL；首轮同步必须在 `spawn` 子进程，而不是把重解析留在 API 进程线程中。retire 和 worker 清理可以并发，`Process.close()` 后读取 `pid/exitcode` 会抛错 | `/` 和 health 不被重解析阻塞；子进程以 `emit_events=false/notify=false` 返回结果，父进程只有在 generation 与完整 TargetProfile 身份仍匹配时才清缓存、更新状态并补发普通同步事件；过期结果只能记 `server.background_stale`；超时事件使用关闭前安全捕获的进程诊断值 | startup child、慢 worker、过期 TargetProfile、关闭后 PID 快照与失败路径 API 测试 |
| `api/app.py::invoice_selection_summary` 与 `AppState.invoice_selection_summary` | `invoice_key` 是行位置，会在重建后复用，所以请求必须带并复核 `source_path`；业务方法还会做同步文件 I/O 和聚合，必须由异步路由卸载到线程池 | 旧选择不能落到新文件；过期返回 409；selection-summary 进行中 health 仍可调度 | selection-summary 过期/非法/并发 health 测试 |
| `api/app.py::manual_fields/cost_analysis/reference_status` 与 `AppState.update_manual_fields/cost_snapshot/save_cost_reference_status` | 手改、schema 自愈和状态/工作簿写入都会等待文件锁；留在事件循环会让 health 与其他轻请求饥饿，脱离 profile 锁又会与 monitor 竞争 | JSON 解析后在线程池运行；所有会写投影的路径使用捕获 profile 的写锁；profile 已切换时旧目录可完成自身真值，但不得清当前缓存或发出当前目录事件 | manual fields、cost snapshot、reference status 的 lock/health/stale-profile API 测试 |
| `_selection_family_key/_selection_metric_total` | 票头号码和文件名号码必须进入同一命名空间；每个金额字段独立判断冲突 | 同票多格式只计一次；同字段多值整票不计 | selection-summary 去重/冲突/回退测试 |
| `AppState.rename_invoice_files` 第一阶段 | 临时名先释放所有源名称，避免 A/B 目标互占和顺序覆盖 | 任何 staging 失败都逆序回滚；不覆盖已有非计划文件 | 重命名保持手改与重复目标测试 |
| `rename_invoice_files` 第二阶段 | 全部临时名再提交为最终名，失败时需要同时回滚已提交与未提交项 | 结果必须区分文件已改名但投影重建失败 | 同上；真实目录验收另行执行 |
| `_migrate_renamed_manual_overrides` | 手改状态用源路径作身份，文件改名必须迁移 key | 不丢三项手改，不把旧 invoice_key 当长期身份 | 手改迁移/重建测试 |
| `request_server_shutdown` | stop-monitor 模式必须先停止并复核，失败时保留 WebUI | 响应前不终止服务；monitor 仍 running 时不调度退出 | shutdown API 两种行为测试 |
| `finalize_server_shutdown` | 正式启动器 PID 可能不是 Uvicorn `os.getpid()`，且关闭期间可能启动新实例 | 仅当 PID 文件内容仍等于请求快照时删除 | shutdown finalize 测试 |
| `AppState._scan_business_dossier/business_dossier/open_business_dossier` | 公司资料夹是导航边界，不是新的扫描根；完整递归和每链接重复扫描会拖住页面，即使前端超时服务端仍会继续工作 | 单次 `os.scandir` 有目录项/时间上限、跳过符号链接；迭代途中 `OSError` 保留已累计项并以 `unreadable_entries` 标为下界；只打开业务资料夹或当前 watch_dir 内路径，open 同步路径经线程池 | business dossier API/有界扫描/iterator-OSError/线程池与首页刷新容错测试 |
| `AppState.bookkeeping_*` 与 bookkeeping repository | 做账状态写入跨进程且必须绑定当前资源 revision | 只经严格仓储/写锁/CAS；坏 schema 保留原文件并 fail closed | 全部 bookkeeping 状态/API 测试 |

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
| `_invoice_reference_summary/_build_reference_rows` | 开票参考按库存除税均价、行级加价和 13% 销项税计算 | 8% 仅 fallback；每行独立；公式两文件一致 | 行级加价与统计测试 |
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
| `MonitorState.sync_write_lock`、`MonitorSynchronizer.run_sync` 与 `AppState.bridge_rebuild` | daemon、startup child 与手动重建可同时命中同一 TargetProfile，单进程 `AppState._lock` 不能保护跨进程投影写入且会阻塞 API | 以 TargetProfile `state_dir` 为键取得可重入线程锁和 OS 文件锁，覆盖整段读取、决策、投影与 monitor 状态写入；不同 profile 不互相串行 | monitor overlap 与手动重建相邻测试 |
| `AppState._retire_background_process_async/_wait_for_background_sync_result` | 切换目录或新的 startup sync 不能让旧子进程无限扫描/写入；等待它退出也不能卡住请求入口 | superseded worker 独立有界 terminate/join；等待结果有总 deadline；仍未退出只记录 `server.background_worker_retire_timeout` 诊断，不覆盖活动 TargetProfile 真值 | startup child EOF、超时、retire 测试 |
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
| `documents.py::_ensure_detail_rows` | 插行会打乱模板合并区域和 footer 样式 | 先移动后续合并区域，再插行并复制模板行样式 | 超模板行数导出测试 |
| `documents.py::rmb_uppercase` | “零”的跨四位组规则非直觉，普通数字格式化不能替代 | HALF_UP 到分；万/亿跨组零正确 | RMB 零位测试 |
| `documents.py::_save_workbook` | 直接保存目标可能留下半写工作簿 | 同目录临时文件后 replace；占用错误上抛给用例层 | 单据导出/占用测试 |
| `AppState._path_is_under_root` 与 open/export 方法 | 客户端不能提交任意本机路径让服务打开/覆盖 | 路径由服务端计算且必须位于入/出库受控根 | 任意路径拒绝、出库范围测试 |
| `storage/files.py::atomic_write_json/write_csv_rows` | 状态和投影被并发读取，半写正文会造成错误恢复 | 同目录临时文件 + `os.replace`；保持 CSV BOM | monitoring/cost/API 相邻测试 |

## 9. P0：Windows 启停和发布

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
| `settings_migration.import_settings` | 覆盖安装会混淆旧进程/缓存与新代码，整目录复制可能带入业务数据 | 新目录安装；只导入配置/偏好白名单；备份目标；Windows desktop 归一 browser | settings migration 单测与双合成包演练 |

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
| `api/app.py::_resolve_event_stream_cursor` | 显式 `after`、`Last-Event-ID`、默认最新游标的优先级用于避免历史回放请求风暴 | SSE cursor 两项测试 |
| `api/app.py::cache_versioned_assets` | 只有带 `?v=` 的成功静态/皮肤资源才能 immutable；无版本资源不能长缓存 | 前端/API 静态契约 |
| `api/app.py::active_skin_link` | 服务端首屏注入避免每页额外皮肤列表请求；backend/no_skin 必须跳过 | 皮肤页面注入测试 |
| `web/static/css/app.css` 的设置移动端规则、做账和勾选合计基础规则 | 缺失媒体查询结束大括号不会删除选择器，却会让桌面端完全丢失基础布局并被皮肤通用规则覆盖 | 共享基础规则必须位于顶层；透明金额卡点击层、三列金额卡和弹窗网格不能只在窄屏生效 | 前端 CSS 大括号层级契约；Ink Pulse、无皮肤和真实桌面浏览器验收 |
| `web/static/css/app.css::.detail-cost-body` | 有界 Grid 会把多个隐式 `auto` 行压到容器高度内；项目卡又用 `overflow:hidden` 收圆角，结果是汇总卡占满项目、规格表被静默裁掉且外层没有可滚动溢出 | 隐式项目行使用 `max-content` 并从顶部排布；单项目表格保留自身有界滚动，多项目高度交给外层 `overflow-y:auto`，纵向滚动链仍为 `auto` | 前端静态契约；Ink Pulse、Animal Island、`?no_skin=1` 多项目真实浏览器尺寸与滚动验收 |
| `invoice_print.html::waitForImage/waitForPrintableFrame/requestBrowserPrint` | `load` 早于图片解码/首次绘制时会让首次打印预览抓到空票面；固定 A4 会覆盖 A5，打印态 `100vw/100vh` 又会随预览页框重算形成反馈，表现为持续加载/跳动或额外空白页；浏览器仍只暴露打印对话框近似生命周期 | 首印等待 `decode()` 与两次渲染帧；命名页只声明方向；票面使用页框百分比且只在后续票面前分页；文案不得把对话框打开写成打印成功 | 打印前端契约 + Chrome/Edge A4/A5 真实验收 |
| `targets/paths.py::target_id_for` | casefold 的目录身份是 Windows 语义，16 位只作档案目录 | paths 测试 |
| `targets/paths.py::serialize_config_path` | 项目内相对保存用于便携，包外绝对保存用于用户目录 | settings/documents 路径测试 |
| `summary.py::summary_schema_needs_refresh` | CSV 与 XLSX 必须一起检查，旧表头会触发后台自愈 | summary schema 测试 |
| `CostProjectionService.needs_schema_refresh/refresh_schema_from_current_detail` | 仅表头升级时不应重解析全部源票，且必须保留状态 | cost schema refresh 测试 |
| `_sync_status` | 成本同步按同票来源组而非文件数统计 | same-invoice format count 测试 |
| `AppState._summary_rows` | `mtime_ns+size` 只做进程内 CSV 读取缓存，不是源发票变化真值 | API 列表/后台同步测试 |
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
| `src-tauri/src/main.rs` foundation guard | 即使已有精确 crate 版本和 Cargo lock，也不等于有可运行的 Rust host；无 runtime 类型上下文的 `generate_context!` 也不能验证配置是否可编译 | 显式使用 `tauri::Context<tauri::Wry>` 生成上下文后固定非零退出；不得换端口、接入未知实例或伪造桌面能力 | `tests/test_tauri_foundation.py` 静态固定-origin/guard 回归、受控 Rust unit test |
| `release/provenance.py::_verify_macos_distribution_artifacts` / `verify_macos_release.sh` / `verify_sparkle_update.swift` | macOS 收据可记录构建期结果，却无法证明发布时的 DMG、ZIP 或 Ed25519 sidecar 尚未被替换；checkout 工作树脚本也不是 Tag 版本发行物的信任根 | finalizer 只接受 schema 4、`developer-id-notarized`、`com.invoicehub.release` 与 v4 verifier，从已解析固定 Tag 取验证器并用 `--artifact-only --expect-notarized` 验证实际 DMG/ZIP；已签名 App 的 `SUPublicEDKey` 必须匹配后才验 ZIP 原始字节，内部收据与布尔值仅审计 | release provenance、metadata CLI、macOS release contract；真实 Developer ID/公证/DMG/Sparkle 成品验收 |
| `bookkeeping.status/mapping_migration` preview/apply | 预览与执行之间资源可能变化，迁移又不可静默丢历史状态 | 同锁重验所有 SHA/revision/binding/backup；启动时不自动迁移 | bookkeeping migration 测试 |
| `bookkeeping.batches.finalize` | 页面未看到结果不能证明未入账，重复观察必须幂等 | success/failed/unknown 证据互斥；同 observation hash 重放原 receipt | bookkeeping export/finalize 测试 |

## 11. P2：大型文件导航注释

这些注释适合在未来拆分模块时增加短区块标题，不应单独制造批量 diff：

- `services/app_state.py`：配置与诊断、单据、普通汇总/重命名、列表/一致性/选择合计、monitor/关闭、成本/皮肤、OCR/平台七个用例区。
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

不要把 `Why/Invariant/Compatibility` 模板机械复制到每处。能用更清楚的函数名、数据模型或拆分消除困惑时，优先改结构；注释只保留无法从局部代码推出的原因。

## 13. 后续逐点补注释流程

1. 在本页找到被修改符号和优先级。
2. 回看对应测试与 `CHANGELOG.md` 历史，确认原因有证据。
3. 在最靠近保护分支的位置写简短注释；不要在文件头重复整篇架构文档。
4. 若代码行为已改变，先更新本页的原因和不变量，再写源码注释。
5. 跑表中守护测试及任务导航要求的相邻回归。
6. 在 CHANGELOG 说明补了哪个设计原因、验证了什么，而不是只写“增加注释”。

## 14. 注释审查问题

- 删除这条注释后，熟悉语言但不了解业务的人会误删哪个保护？
- 注释描述的是当前代码和测试能证明的事实吗？
- 它是否解释了为什么，而不是逐字翻译代码？
- 是否包含会很快漂移的数字、路径、分支状态或样本规模？
- 行为变化时，关联测试会失败并提醒更新注释吗？
- 它是否意外承诺了未启用能力，例如正式 OCR、云部署或 SQLite 发票主存储？

## 15. 相关入口

- [开发架构总入口](../DEVELOPMENT_ARCHITECTURE.md)
- [平台架构](PLATFORM_ARCHITECTURE.md)
- [完整文件地图](FILE_MAP.md)
- [接口与运行流程](INTERFACES_AND_FLOWS.md)
- [数据结构与算法](DATA_AND_ALGORITHMS.md)
- [Agent 任务导航](AGENT_TASK_MAP.md)
