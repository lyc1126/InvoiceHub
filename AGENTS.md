# AGENTS.md

本文件作用于整个重构版仓库。不要创建 `AGENT.md`、`agent.md` 或其他旧命名变体。

## 项目边界

- 当前产品边界：`v1 localhost`
- 当前运行模型：`单活动监控目录 + TargetProfile 独立档案`
- 公开基线：本仓库以一个脱敏根提交建立新的 `main`。旧私有提交图、Tag、构建包、receipt 和验证叙述不属于公开图或 Release 输入；详情见 `docs/release/HISTORY_SANITIZATION_EXECUTION.md`。
- 下一开发主线：公开验证完成后，`v0.3.0-alpha.1` 使用 Tauri 2 统一桌面壳，继续复用 Python/FastAPI/Web/独立 monitor；Tauri 不得重写发票、成本、做账或投影核心。
- 当前不做：多用户、权限、授权、云部署、MSI、Windows ARM64、macOS Intel/Universal、App Store、本地 OCR 正式打包版、SQLite 发票主存储。
- 本文件已整合旧项目仓库根 `AGENTS.md` 与 `发票处理脚本/AGENTS.md` 中仍适配重构版的约束。旧项目特有的目录名、版本号、旧 `web_localhost` 布局和旧包名只作为历史基线，不作为新项目结构要求。

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

## 开发架构阅读与同步规则

- `docs/DEVELOPMENT_ARCHITECTURE.md` 是当前开发实现的权威架构入口；`docs/architecture/AGENT_TASK_MAP.md` 是按任务定位修改入口、联动范围和最低验收的导航表。
- 跨模块、架构、数据链、启动、监控和发布任务，必须先读架构总入口，再按任务导航阅读对应专题：接口与时序读 `docs/architecture/INTERFACES_AND_FLOWS.md`，数据、数据库与算法读 `docs/architecture/DATA_AND_ALGORITHMS.md`，文件关系读 `docs/architecture/FILE_MAP.md`，设计原因与注释债读 `docs/architecture/COMMENT_RATIONALE_MAP.md`。
- 窄范围修改也必须先在任务导航中定位该任务；只需阅读与修改面直接相关的专题，不要求无差别重读全部附录。
- 新增、删除、移动或重命名工程文件时，必须在同一任务内同步 `docs/architecture/FILE_MAP.md`；不得只改目录树而留下失真的 Agent 导航。
- 修改 API、页面消费、SSE、错误码、状态语义、生成产物或运行流程时，必须同步 `docs/architecture/INTERFACES_AND_FLOWS.md`；修改模型、SQLite schema、投影字段、公式或算法时，必须同步 `docs/architecture/DATA_AND_ALGORITHMS.md`。
- 修改跨模块影响范围、最低测试或验收入口时，同步 `docs/architecture/AGENT_TASK_MAP.md`；产生新的非直觉约束、兼容原因或失败保护时，同步 `docs/architecture/COMMENT_RATIONALE_MAP.md`，必要时再把长期不变量写回本文件。
- 整合开发分支完成验收并合并 `main` 后，必须在同一任务内把架构文档的开发实现基线和稳定发布基线切换到新的 `main` commit，不保留两套相互漂移的架构说明。

## 第一性原则

- 源发票是事实；CSV/XLSX/JSON 是可重建投影。
- 字段策略保持：宁可空，不要脏值。
- 开票金额、除税价、税金等金额字段必须命中合法金额格式；不得接受 8-20 位纯数字、发票号片段或文件名编号作为金额。PDF 页必须保留页边界；文本顺序异常时，优先在同页 `价税合计/小写` 锚点后的有限窗口内寻找带 `¥/￥` 的唯一有序三元组，且必须满足 `abs(除税额 + 税额 - 价税合计) <= 0.02`。多个可行三元组、跨页、缺少可靠锚点或算术不一致时不得采用；普通标签 fallback 只能读取同行或紧邻独立货币值，合计统计只累计合法金额。
- 用户可见路径必须明确区分：
  - `watch_dir`：当前发票业务来源目录
  - `workspace`：普通汇总与运行状态工作区
  - `watch_dir/成本发票明细.csv`
  - `watch_dir/成本发票汇总.xlsx`
  - `watch_dir/成本开票状态.json`
- SQLite 只允许存任务、事件、缓存和设置，不作为发票主存储。
- Docker 只作为开发与 Mac 验证工具，不作为 Windows 正式离线运行依赖。
- 源码、默认配置和文档示例不得写死本机绝对路径；项目根目录内路径写回配置时必须保存为相对路径，包外用户目录才允许保存绝对路径。
- 启动必须快，但不能牺牲旧项目默认能力：localhost 首页先返回 200，首轮发票汇总、成本同步状态、OCR 探测和重诊断必须在后台自动开始；不能要求用户每次启动后手动点击“重新汇总”才看到当前目录发票。
- 所有用户可见状态必须可诊断：状态文件、日志、事件、API 返回和页面提示不能互相矛盾。

## 目录规则

- `src/invoice_hub/domain`：领域模型与契约
- `src/invoice_hub/extraction`：PDF/OFD/XML/OCR 轻量提取
- `src/invoice_hub/projections`：CSV/XLSX/JSON 投影
- `src/invoice_hub/targets`：路径解析与运行态自愈
- `src/invoice_hub/api`：FastAPI 路由与错误模型
- `src/invoice_hub/services`：业务服务
- `src/invoice_hub/platform`：Windows 启停、进程、通知、原生选择器、打开文件
- `src/invoice_hub/storage`：文件真值读写与 SQLite 任务/事件
- `src/invoice_hub/release`：发布构建与验收辅助
- `web`：模板与静态资源
- `scripts/windows`：正式 Windows 用户入口
- `macos/InvoiceHubMac`：macOS SwiftUI/WKWebView 本地壳与 SwiftPM 工程，负责 macOS 窗口、菜单、目录选择和本地后端进程控制；不得承载发票解析主逻辑
- `scripts/dev`：开发、Docker、门禁脚本
- `tests`：自动化测试与黄金样本
- `runtime`、`运行状态`、`dist`：本地运行态和发布产物，必须 ignored
- 根目录允许保留 `启动一站式发票汇总系统.bat`、`停止一站式发票汇总系统.bat`、`停止一站式发票汇总系统并停止监控.bat` 和本机生成的 `启动一站式发票汇总系统.lnk`，作为用户第一视图入口；`.lnk` 不纳入 Git。

## 持续监听规则

- 关闭浏览器不停止 localhost，也不停止监控。
- `停止一站式发票汇总系统.bat` 只停止 localhost；`停止一站式发票汇总系统并停止监控.bat` 才允许同时停止监控。
- 设置页“关闭本系统”必须默认每次询问“保留监控，仅关闭 WebUI / 关闭 WebUI，并停止监控”，允许勾选“记住本次选择”并在偏好中随时改回询问或切换固定行为；该页面能力不得改变两个正式停止 BAT 的固定语义。
- 页面选择同时停止监控时，必须先停止 monitor 并复核真实 `running=false`，失败时保留 WebUI 供用户重试；关闭响应必须先返回浏览器，再延迟终止 localhost，并让 `server_state.json` 的 `stopping/stopped` 与 monitor 状态一致。
- 监控必须使用独立 daemon，不能退回到 FastAPI 进程内线程作为正式用户入口。
- 监控状态真值优先级：PID 存活 + `state_dir/.invoice_monitor.lock`，`server_state.json` 只诊断 localhost。
- 监控启动接口只有在 daemon 完成首轮同步、文件事件观察器或周期兜底初始化、补漏同步并写入 `ready=true` 后才允许返回成功；不得只凭 PID/lock 报启动成功，避免文件落入“启动同步已结束、观察器尚未就绪”的空窗。
- 监控日志必须写入 `workspace/文件变化监控日志.txt`，至少保留 `STARTUP_SYNC/EVENT_SYNC/PERIODIC_SYNC/MANUAL_EDIT_* / NOTIFY_*` 动作。
- 监控默认同步策略为启动校验一次、文件事件 1 秒合并、60 秒轻量兜底；无变化周期不得重解析全目录。
- Excel 手改自动同步只允许 `销售方/开票金额/发票号码` 三字段，必须记录 `MANUAL_EDIT_DETECTED`、`MANUAL_SYNC_GUARD_PASS/BLOCK`、`MANUAL_EDIT_AUTO_SYNC`。
- localhost 服务启动后，即使用户没有点击“启动监控”，也必须后台执行一次 `STARTUP_SYNC`：比较当前 `watch_dir` 与 `processed_files.json`、缺失汇总或成本产物时自动重建普通汇总和成本三件套。该动作不能阻塞 `/` 和 `/api/v1/health`。
- 删除同步只允许删除投影记录和状态，不得删除源发票文件。
- `server_state.json`、`browser_launch.log`、`startup_preflight.log`、`monitor_status.json` 等只作为诊断文件，不是唯一运行真值。

## 数据准确性规则

- 不允许用文件名乱回填正文提取不到的核心字段。文件名只能用于同票 20 位号码家族判断、重复识别辅助和路径展示。
- 电子发票 PDF 常见“标签在前、值集中在后”文本顺序。处理这类版式时，20 位发票号、开票日期和两个可靠主体只用于恢复购方/销方；票头金额必须独立使用同页唯一算术三元组或明确标签证据。不得把购销方后的两个普通小数直接映射为除税金额和税额，也不得恢复“全文抓最大金额”这类会污染字段的策略。
- 遇到 `购买方 / 销售方` 识别异常时，先检查同票多格式家族。本项目“同票”按同一个 20 位发票号码家族定义，不按完全相同文件名定义。
- 若同票家族存在 XML，优先用 XML 的 `销售方 / 购买方` 纠偏同票 PDF/OFD 的空字段；不得用 XML 覆盖用户手改字段。
- `销售方 / 购买方` 的非空值如果是中文大写金额、纯数字对象号、发票标签、地址电话、项目/运输描述等明显脏值，不能视为有效识别结果；允许被同票 XML/OFD/PDF 中更可靠的结构化字段纠正，但不得覆盖用户手改字段。
- OFD 识别必须优先使用 `CustomTag.xml` 中的 `ObjectRef -> TextObject` 结构化字段读取发票号、日期、购销方、税率、除税金额、税金和价税合计；只有结构化字段不可用时才允许回退纯文本解析。
- 发票分类必须保持两个独立维度：`invoice_type` 只允许“增值税专用发票 / 增值税普通发票 / 空”；`business_type` 只允许“标准电子发票”及已登记的特定业务样式。缺失、未知或冲突证据必须留空并使用 `classification_status/classification_issue` 进入待核对，不得把 PDF/OFD/XML 文件格式写入发票大类。
- 业务样式只能按上下文取证：PDF 使用发票标题和左上业务标签坐标，无坐标文本只接受明确业务标签前缀；OFD 优先 `CustomTag.xml` 类型字段并结合坐标文本对象；XML 只接受明确类型/业务字段。公司名、项目名、商品名中的相同词不得触发分类，`XT` 只允许在业务标签或结构化业务字段中精确匹配。
- 同一 20 位发票号家族只允许用更可靠格式补齐空分类；非空大类或业务样式冲突时不得强行覆盖，必须保留各来源结果、标记 `conflict` 并进入一致性报告。
- PDF/OFD/XML 提取链变更后，不能只看页面；必须至少覆盖汇总 CSV/XLSX、`/api/v1/invoices`、详情页、成本同步状态和一致性页。
- 为跨平台发布主机生成的合成 PDF 可以使用受控标记和内置 Latin 字体，但解析器只能对同时具备该固定双标记的资料启用专用别名；不得把 `Invoice number/Buyer/Seller/Total amount` 等通用英文业务文档文本提升为可计入发票字段。扩大任何提取证据面时必须同时增加普通业务文档的负向回归。
- 成本发票明细解析必须优先使用结构化或坐标来源：PDF 使用坐标/表格结构还原，XML 使用结构化明细节点，OFD 优先使用 `CustomTag.xml` 的明细字段引用，必要时才使用 `Content.xml` 文本对象坐标；不能只靠纯文本行号、抽取顺序或文件名硬拆。商品名跨行、OFD `item` 多段拆分、金额/税额先于数量/单价出现等情况必须在结构层或坐标层归位。
- PDF 业务版式成本明细必须先识别可靠表头，再按行基线映射列；建筑服务发生地/项目名称、旅客/货运专属列、不动产权证号等只能用于版式定位，不得挤入金额、税率或税额。无可靠表头时不得猜明细；同票候选优先选择除税金额和税额均校验通过的来源。
- 成本发票校验差异必须显式进入结果和页面，不得只写日志或在解析阶段吞掉。
- 首页勾选发票合计必须按同票家族去重：优先使用当前发票号码，其次使用文件名中的 20 位号码，最后按源文件路径区分；票头与文件名取得的同一号码必须落入同一号码命名空间。三项金额必须分别从票头 `除税价 / 税金 / 开票金额` 累计合法金额；同一家族同字段存在多个不同合法金额时，该字段整张票不计入并明确提示冲突。
- 首页勾选合计请求必须同时携带并校验 `invoice_key + source_path`，位置键已对应其它源文件时必须返回过期选择，不得误汇总。合计成本明细只能只读当前 `watch_dir/成本发票明细.csv`，不得触发重建或反推票头金额；匹配优先发票号、无结果再回退源文件，并按 `内部项目名称 + 明细税率` 拆组、按 `规格型号 + 单位` 汇总，缺失税率必须显示未识别，不得用票头税率猜测。

## 接口与前端同步

- 修改后端接口、服务返回结构、生成产物字段或业务状态语义时，必须同步更新：
  - 前端页面
  - 前端 JS 消费
  - 页面文案
  - HTTP/静态契约测试
- 修改 `web/static` 下的 CSS/JS 后，必须同步更新引用该资源的模板版本参数（例如 `?v=...`），并在前端静态契约测试中锁定新版本号；不得只改静态文件而不刷新版本，避免浏览器缓存导致用户端看不到改动。
- 修改 `web/static`、前端模板或皮肤 CSS 后，收尾前必须验证当前正在运行的 localhost 已实际应用本轮前端资源：至少检查目标页面 HTML 中的新 `?v=` 参数、对应静态文件内容、`GET /api/v1/health` 指向当前仓库运行态，并用浏览器或等价 DOM 检查确认关键样式/脚本计算结果已生效。若当前 localhost 未加载新版本、端口指向旧进程或浏览器仍展示旧资源，必须先用正式启停入口重启并复验，最终回复需明确说明是否覆盖当前启用皮肤与 `?no_skin=1` 恢复入口。
- `/api/v1/cost-analysis` 必须持续返回：
  - `watch_dir/source_dir/target_id`
  - `output_detail_csv_path`
  - `output_summary_xlsx_path`
  - `reference_status_path`
  - `invoice_reference`
  - `reference_status_stats`
  - `reference_markup_rate`
  - `sync`
- 首页原生目录选择器返回的路径是待保存草稿，页面必须明确显示“待保存目录”；自动刷新、SSE 重连或列表刷新不得覆盖用户尚未保存的输入框路径。
- 所有使用 `EventSource` 的页面都必须同时处理 `onerror` 和重连后的 `onopen`：断线给出用户可见状态，重连后刷新关键数据。
- 源文件预览的 15 分钟有效期必须是闲置超时，不得在预览弹窗仍打开时按创建时间硬切断；弹窗打开期间必须轻量续租，内容访问必须刷新闲置期限，定时器被节流、后端重启或 job 回收后的 `404/410` 必须先尝试自动重建原勾选会话并保留当前文件/页码。关闭弹窗必须停止续租；不得因续租放宽源文件变更、目录切换、作业数或缓存上限。
- 用户可见按钮必须区分“普通禁用”和“异步处理中”：只有真实请求、选择器、重建、打开文件等进行中状态可以显示等待光标；无待保存草稿、未选中行、功能不可用这类普通禁用态不得使用加载光标。
- 首页源文件预览只能接收当前发票列表已勾选的 `invoice_key + source_path`，服务端必须用当前列表重新校验身份并确认解析后的真实文件仍位于当前 `watch_dir`；不得增加任意本机路径参数、目录浏览器或把绝对路径返回浏览器，多选预览保留每条源文件且不按同票家族去重。
- 源文件预览是原生内容镜像，不是发票字段解析：PDF/OFD/受控图片只返回 PNG 页，XML 只以安全纯文本返回，其它格式只展示元信息和系统打开入口；SVG 必须拒绝 DTD、实体、脚本、事件、主动元素和外链资源，XML/HTML/SVG 等本地内容不得进入前端 `innerHTML`。
- 预览作业必须短期、仅内存、按需渲染并受记录数、页数、像素、单作业/全局字节和过期时间约束；切换 `watch_dir` 时与打印缓存一起清空，不得把预览内容写入源目录、普通/成本投影、runtime 文件或 SQLite 发票主数据。
- 首页勾选汇总或源文件预览弹窗打开时，必须同时锁定 `html` 与 `body` 的背景滚动；不能只锁 `body`，因为皮肤对根元素设置 `overflow-x` 后会阻断滚动锁向视口传播，导致窄屏保留根滚动条并可滚动弹窗后的页面。
- 首页批量打印必须使用 `invoice_key + source_path` 重新校验勾选身份，并按同一 20 位发票号码家族只打印一次；只能读取当前 `watch_dir` 内仍存在的 PDF 票面，选中 OFD/XML 时允许回退同票家族 PDF，没有可用 PDF 必须整批失败并明确提示，不能静默漏票或把文件名/汇总表重建成票面。
- 浏览器打印准备只能生成有时限、有页数和内存上限的进程内票面快照，不得写入 `watch_dir`、普通/成本投影或 SQLite 发票主数据；原 PDF 每一页都必须保留并独占一张打印纸，不能为了“一票一页”丢弃多页发票的后续页。
- `window.print()` 只能请求浏览器打开系统打印对话框；页面必须覆盖弹窗被拦截、浏览器无打印 API、PDF 渲染失败、票面加载失败和作业过期等可诊断错误，但不得把“对话框已打开”表述为“实体打印成功”，因为浏览器不会向页面可靠暴露用户取消、打印机离线或纸张输出结果。
- 打印页首次自动调用 `window.print()` 前必须等待全部票面图片完成 `load + decode` 并至少经过两次浏览器渲染帧；命名 `@page` 只允许声明横/纵方向，纸型必须沿用打印机或用户选择，打印盒必须使用页框百分比尺寸跟随实际页框，不得用固定 A4 毫米尺寸或打印态 `100vw/100vh` 形成纸型覆盖与预览重排反馈；只允许在第二张及后续真实票面前强制分页，避免首次预览空白、持续跳动和末尾空白页。
- `/costs` 页面中与工作簿 sheet 对应的标签必须互斥显示；新增或调整标签时必须检查 `hidden/aria-selected/aria-hidden`、`.cost-view[hidden]` 和复制 TSV 口径。
- 表格必须保持真实 `<table>` 结构和可选择文本；调整表格渲染时必须保留可粘贴到 Excel/WPS 的 TSV 复制路径。
- 首页、成本页等内部可纵向滚动的子表容器不得用纵向 `overscroll-behavior: contain` 阻断滚动链；当子表滚动到上/下边界且主页面仍可滚动时，继续滚轮或触控板滚动必须交给主页面滚动条。
- 普通导航面向日常用户；`/backend` 可保留直达诊断，但不得重新暴露到用户第一视图导航，除非用户明确要求。
- 皮肤系统默认必须是“无皮肤”且可恢复；普通页面可加载当前皮肤，`/backend` 不加载皮肤，必须保留 `?no_skin=1` 作为皮肤损坏时的恢复入口。
- 皮肤 ZIP 只允许 `skin.json`、CSS 和静态资源；`skin.json` 必须声明 `id/name/version/entry`，`id` 只允许小写字母、数字和短横线。不得导入或执行任意 JS、HTML、脚本、可执行文件或远程资源。
- 皮肤导入必须校验 zip slip、绝对路径、Windows 盘符路径、`..`、重复文件、符号链接、加密 ZIP、文件数和大小上限；CSS 必须拒绝 `@import`、外链 URL、`data:`、`javascript:` 和包内不存在的资源引用。
- 导入皮肤只能写入 `runtime/local_state/skins` 这类运行态位置，不得写入 `watch_dir`，不得污染源发票、成本产物或默认配置；内置皮肤只读，同 ID 导入不得覆盖内置皮肤。
- 新增内置皮肤必须只覆盖 CSS 变量和既有选择器，不能改变业务 DOM、表格结构、TSV 复制链路、SSE 重连、目录草稿或成本输入行为；引用第三方项目时只能作为视觉参考，除非许可和来源已明确记录，否则不得复制素材、字体包、组件代码或源码样式。
- 内置皮肤允许打包本地字体子集和原创图片纹理，但必须使用包内相对 `url()`、记录来源/许可、禁止远程字体和外链图片；不得复制官方游戏素材、角色、Logo、截图或商业字体。

## 成本分析规则

- 成本分析 v1 产物固定写入当前选择器 `watch_dir`：
  - `watch_dir/成本发票明细.csv`
  - `watch_dir/成本发票汇总.xlsx`
  - `watch_dir/成本开票状态.json`
- `workspace` 只保留普通汇总与运行状态工作区；成本页面和 API 不得让用户误以为成本汇总表在 `workspace`。
- “刷新”和“重新汇总”语义必须分开：刷新只重新读取当前状态，不生成文件；重新汇总才扫描当前发票目录并重建普通汇总与成本分析。
- 成本分析表“开票参考”sheet 与 `/costs` 页面“开票参考”标签必须以当前成本明细为来源，按 `发票代码(**内文字) / 内部项目名称 / 规格型号 / 单位` 汇总；不能输出销售方和涉及发票号码；开票加价率不再固定，默认 `8%` 只作为行级 fallback，每条开票参考行可在 `watch_dir/成本开票状态.json` 中单独保存 `reference_markup_rate/reference_markup_rate_percent/reference_markup_locked`，勾选后的批量加价率操作只作用于已选行。API 必须持续暴露兼容字段 `reference_markup_rate`，但页面不得再提供顶部全局加价率设置。
- 开票参考状态保存时必须按同一汇总键持久化到当前 `watch_dir/成本开票状态.json`，并锁定当次 `已开数量` 与已开参考金额/税金/价税合计快照。后续新增同键发票只能增加未开部分，不能让已开金额随新汇总漂移。
- 底层 `成本发票明细.csv` 必须保持一条明细一行、票面字段不留空；工作簿和页面可以合并展示同票票面字段，但不能改变 CSV 逐行口径。
- 调整成本字段时必须同步更新工作簿 sheet、`GET /api/v1/cost-analysis`、`POST /api/v1/cost-analysis/reference-status`、`/costs` 前端和契约测试。

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

## Windows 与启动规则

- Windows 下默认优先 PowerShell 7 (`pwsh`)，允许回退 `powershell.exe` 5.1；任何会打进 core 包、且可能被 5.1 执行的 `.ps1`，如果包含非 ASCII 文本，必须保存为 UTF-8 BOM。
- 正式 BAT 选择 PowerShell 时必须保留 `INVOICE_HUB_FORCE_PS51=1` 强制门；普通路径先验证固定 `Program Files` 的 PowerShell 7，再安全解析 `PATH`/App Execution Alias 中的 `pwsh.exe`，只有没有可运行的 7.x 时才允许回退 Windows PowerShell 5.1。不得把“固定安装目录不存在”直接等同于“机器没有 PowerShell 7”。
- Windows PowerShell 5.1 的 `Invoke-WebRequest` 会在 `application/json` 未声明 charset 时按旧代码页解释 `.Content`；启动器读取 localhost health 必须从原始响应流按 UTF-8 解码后再解析 JSON，并在中文空格 `config_path/runtime_dir` 上执行同一严格身份校验。不得通过放宽路径身份或只测 ASCII 路径绕过。
- 修改正式 BAT/PS1 后，至少验收正式 BAT，不得只跑 Python 模块或临时脚本。
- 启动判重不能只依赖 `server_state.json`、`server.pid` 或命令行匹配；必须以首页 `/` 可访问、端口可达、PID 存活作为运行真值，并清理 stale ready 状态。
- 连续点击、并发启动、旧 state 残留、端口被外部占用属于启动脚本相邻回归；涉及启动链时不能只测单次启动成功。
- 启动器写 `server.pid`、`server_state.json`、`browser_launch.log`、`server_stdout.log`、`server_stderr.log`、`startup_preflight.log` 时必须确保父目录存在，并区分“目录缺失 / 同名文件占位 / 文件位被目录占位”，冲突先隔离成 `.conflict-<timestamp>[-N].bak`。
- Windows monitor PID 存活判断必须使用不依赖 PATH、命令输出编码和本地化文本的系统进程真值；不得只解析 `tasklist` 文本就把活进程当 stale lock。
- 发行测试驱动不得只在一串外部命令结束后读取一次 `$LASTEXITCODE`；`pytest`、`compileall`、脚本/语法检查等每一条外部命令返回后都必须立即 fail closed，避免后续成功覆盖前序失败。
- localhost 进程内关闭时不能假设 `server.pid == os.getpid()`；必须快照请求时 PID 文件，并只在收尾时删除内容仍与快照一致的文件，避免包装进程/子进程 PID 不同造成 stale PID，也不得误删关闭期间新实例写入的 PID。
- 浏览器拉起标准是系统壳优先，注册表模板后备；系统壳派发 URL 返回成功后应接受本次打开结果，前台窗口 nudge 只作为 best-effort 诊断，不能重复打开同一个 URL。
- 原生目录/文件选择器子进程必须从项目根作为 `cwd` 启动，不能把 `config/` 当模块导入根目录。
- `OFD` 临时解压目录绝不能回落到 `watch_dir`；即使输出目录缺省，也必须使用 runtime/temp 类目录。
- core 包正式 BAT 烟测前必须检查配置端口是否落入 Windows TCP 排除范围。默认端口被排除时要记录原样启动失败及系统错误，只允许用另一个不含业务路径的脱敏验收配置继续相邻链路；不得因此宣称包内默认配置原样启动通过。

## macOS 本地壳规则

- macOS 第一版为 SwiftUI/WKWebView 本地壳，业务核心继续复用 Python/FastAPI、`/api/v1`、CSV/XLSX/JSON 投影和独立监控 daemon；不得为 macOS 单独重写发票识别、成本分析或状态口径。
- `.app` bundle 只允许放只读核心资源和内置运行时；用户配置、SQLite、日志、pid、皮肤导入和运行态必须写入 `~/Library/Application Support/InvoiceHub` 或等价用户可写目录，不得写入 `.app/Contents`。
- macOS 用户运行不得依赖 Docker；Docker 只作为开发、测试和未来云端依赖验证工具。
- macOS 目录选择优先使用系统原生 `NSOpenPanel`；选择结果必须仍通过后端设置接口保存，并保留“待保存目录/保存后切换活动目录”的产品语义。
- macOS WKWebView 内的页面“选择文件夹”不得调用 Python/Tk picker；必须通过 Swift bridge 调用 `NSOpenPanel`，只把选择结果和后端校验结果返回给页面，避免弹出 Python Launcher 或选择器闪退。
- 重建未签名 macOS 开发 `.app` 可能改变 TCC 代码身份并重新触发“下载”等受保护目录授权；严格握手或 `health.ok=true` 不代表 `watch_dir` 可读。出现后台同步超时、`background_status=failed` 或页面 `Load failed` 时，必须先用系统日志区分目录权限与预览/API 故障；只有用户明确允许后才可通过真实 `NSOpenPanel` 重新授权，随后必须复验 `background_status=ready`、手动重建和源文件预览。
- macOS WKWebView 内的 HTML 文件输入必须由 `WKUIDelegate` 实现 `runOpenPanelWith`，使用系统 `NSOpenPanel` 并在选择或取消后始终完成 WebKit 回调；皮肤页只允许选择单个 ZIP，修改后必须在真实 `.app` 中点击验收原生面板。
- macOS 批量打印只允许受信主 WebView 以精确 `about:blank` 创建子窗口；登记后的子 WebView 只能导航到同端口、无查询和 fragment 的 `/invoices/print/{job_id}`。外部域名、错误端口、子框架和普通页面不得继承任何原生能力。
- 打印子窗口只能注入受限 `window.print()` bridge，并在已登记的打印路由、主框架和预期 origin 全部匹配时调用 `WKWebView.printOperation(with:)`；目录选择、后端控制和通用 `window.invoiceHubMac` bridge 只允许主 WebView，取消打印按正常完成处理并派发 `afterprint`。
- macOS 工具栏、菜单或 Swift bridge 触发的保存目录、重新汇总、监控启停等原生命令，必须复用 `/api/v1` 后端返回值，并在成功或失败后刷新/诊断 WKWebView 可见状态；不得只在 Swift 状态栏写“操作已发送”而让页面保持旧汇总。
- macOS 开发 `.app` 重跑脚本必须先收束旧 app 和旧 InvoiceHub 后端，再打开新版 app；不得让新壳连接到即将被旧壳退出钩子终止的 localhost。SwiftUI 壳运行中应禁用 AppKit 自动终止，避免系统在窗口/恢复状态短暂为空时结束 app 并带掉后端。
- macOS 开发 `.app` 脚本必须明确准备或绑定可用 Python 后端环境；写入 `dev-python-path.txt` 后，Swift 端必须校验该路径可执行，失效时直接诊断，不得静默回退到缺少依赖的系统 Python。
- macOS 壳不得只凭 `/api/v1/health` 的 `ok=true` 接入 localhost；必须同时核对打包 build ID、API 契约版本、必需能力、配置路径、运行目录和关键页面/API，任一不匹配都要拒绝连接并显示预期值、实际值、端口和日志路径。
- macOS 严格握手必须同时校验构建 manifest、health 和 Swift required 三方的 API 契约、`w9-ledger-review-v1` 与完整 capabilities；manifest 缺失/无效、`build_manifest_present=false` 或任一能力集合漂移都必须拒绝连接。
- macOS 严格握手只能实际读取 health 和无业务扫描的静态页面；必需 API 通过 `/openapi.json` 校验注册，不得为探测兼容性读取会扫描真实 `watch_dir` 的 documents/bookkeeping 等数据接口。Swift 与开发脚本的每次 HTTP 探测都必须设置连接和总时限。
- macOS 壳与开发脚本不得为规避端口冲突自动换端口；同一 Application Support 运行态只能有一套 localhost 写入者，固定端口被未知程序占用时必须明确失败。
- macOS 开发脚本只能终止命令行为 `invoice_hub.api.main` 且 `--config` 精确指向当前 Application Support 配置的旧服务；无法验证归属的 PID 或监听进程不得终止。
- `python -m invoice_hub.api.main` 启动只能构造一份 FastAPI/AppState 和一条后台 startup sync；包级 API 导出不得在 CLI 参数解析前抢先实例化默认应用。
- 关闭 macOS 主窗口不等于停止监控；停止 localhost 与停止监控必须保持分离，只有明确 stop-all/停止监控动作才允许停止监控 daemon。
- macOS 壳只能把当前壳启动且 Process/PID/health 精确匹配的服务标为 `owned`；一次 API 控制失败不得把 owned 服务降级为 external。发送终止信号后只有确认进程退出才允许清理 PID 和 ownership；超时必须保留真值和诊断。
- macOS 壳跨 `await` 的启动、停止、monitor 和重建结果必须绑定发起时的 lifecycle generation、phase、ownership、health PID 与 Process PID；完成时身份或代次已变化就丢弃旧结果，不得复活已停止服务或覆盖新的 starting/stopping 真值。
- WKWebView 的 `window.invoiceHubMac`、导航和原生 open panel 只对预期 `http://127.0.0.1:<固定端口>` 主框架开放；外部页面、子框架和不匹配 security origin 不得调用原生能力。
- SwiftPM GUI app 必须通过项目脚本生成 `.app` bundle 后运行，不把 SwiftUI GUI 当普通命令行可执行直接作为正式入口。
- macOS 正式包只能使用 `Contents/Resources/invoice-hub-core` 内嵌且清单匹配的核心与 Python，不得包含 `dev-python-path.txt`、`.backend-venv` 或系统 Python fallback；内嵌 core 缺失或结构无效时必须直接失败，绝不能回退当前目录或 checkout；monitor 使用项目内 polling observer，不为 macOS 强行引入缺少目标 wheel 的 watchdog。
- Sparkle 更新安装、升级标记写入、为更新停止/恢复 monitor 都必须由当前 App 已验证的 `owned` lifecycle（generation/phase/health PID/owned PID/Process PID）发起；`externalCompatible` 不得拥有 Web bridge、原生菜单或恢复路径来安装更新或改变其 monitor。安装前必须先写 Application Support 恢复标记，再停止 monitor 并确认真实 `running=false`；取消、下载/安装失败或停止失败时，仍由当前有效 owned lifecycle 恢复此前运行的 monitor。新版本只有在 build/package/health/OpenAPI 严格握手完成、启动已切换到经验证的 owned running 身份并释放 startup gate 后，才可尝试 marker 恢复；monitor 恢复 `ready=true` 后才删除标记。启动失败或 `externalCompatible` 路径仍必须保留既有收尾释放，不能以提前释放 gate 绕过身份验证。
- `externalCompatible` 的 Swift 菜单、侧栏和由壳注入的首页/设置页控件都必须禁用 monitor 的启动与停止；这是壳的所有权保护，不应把无认证 localhost HTTP API 误描述为跨客户端权限边界。
- macOS 正式脚本计算 SHA-256 时必须以 `LC_ALL=C LANG=C /usr/bin/shasum` 执行；构建机的 `C.UTF-8` locale 可能使系统 `shasum` 失败，不能把它当成产物哈希不匹配。
- macOS 内部候选的 staging App、Sparkle ZIP App、DMG App 与 DMG 容器必须全部为 ad-hoc 签名，并拒绝 Developer ID Authority 或 Team ID；验证器必须显式且互斥地使用 `--expect-internal-adhoc` 或 `--expect-notarized`，不得用自动猜测或无模式验证混淆内部候选与正式产物。
- Sparkle 发布私钥只允许使用 Keychain account `com.invoicehub.release`，`sign_update` 必须显式传递该 account。macOS 构建收据固定为 schema 4 并记录 `signature_mode`、`sparkle_keychain_account` 与 v4 验证器；公开 provenance/finalizer 只接受 `developer-id-notarized` 正式收据，仍须对实际制品独立执行 `--artifact-only --expect-notarized`，内部 ad-hoc 收据永远不能放行 Feed。
- macOS 发布验收必须额外覆盖：`.app/.dmg`、Developer ID、Hardened Runtime、公证/staple、quarantine、无 Docker/开发 `.venv`、包外发票目录、Application Support、原生面板、关闭窗口/monitor，以及一次真实 Sparkle 旧版到新版升级。
- macOS 发布验证器对已签名 App 执行内嵌 Python、`pip check`、import smoke 或内容扫描时必须同时设置 `PYTHONDONTWRITEBYTECODE=1` 和解释器参数 `-B`；`-I` 会忽略 `PYTHON*` 环境变量，不能只靠前者。普通验证必须可重复执行且不得在 staging App 内新增 `.pyc` 或破坏 codesign seal，artifact-only 通过不能替代该幂等检查。

## 发行与更新规则

- `src/invoice_hub/version.py` 是版本、API 契约、通道、公开链接、更新白名单和双平台 package ID 的单一真值；Python、Swift、脚本、manifest、Feed 和文档不得各自维护漂移常量。
- 新建的双平台发行必须从同一 40 位 clean `RC_SHA` 构建并具有相同 core build ID；build/package/runtime manifest、依赖锁、SBOM、文件 SHA 和构建收据必须互相闭环。带 `+dirty` 的开发清单不能进入正式候选。旧私有包不能作为公开发行基线或证据来源。
- 仓库采用单仓库共享核心，Windows checkout 可以包含 `macos/` 源码，macOS checkout 也可以包含 Windows 脚本；这不授权成品混包。Windows portable 必须只接受精确 Windows 包路径并拒绝 macOS 壳、锁和 runtime，macOS `.app/DMG/Sparkle ZIP` 必须拒绝 Windows BAT/PowerShell、锁和二进制 runtime；任一反向平台文件出现即 fail closed。
- 固定的 python-build-standalone macOS runtime 自带 `fetch_macholib.bat`、`idle.bat` 和 `venv/scripts/common/Activate.ps1` 三个跨平台辅助文件，内置 pip/distlib 还携带 `t32/t64/t64-arm/w32/w64/w64-arm.exe` 六个 Windows console launcher；`prepare_release_runtime.sh` 必须在 runtime manifest 前精确删除这九个已知文件，并再次扫描整个 runtime，任何其它 BAT/CMD/PS1/PSM1 或 EXE/DLL/PYD/MSI/MSIX 仍须 fail closed。不得通过放宽 macOS 成品验包器或把上游 runtime 整体列为例外来绕过平台边界。
- 正式源码快照必须从精确 Git commit 导出，不读取工作树未跟踪/ignored 文件；新建发行的对应源码、LICENSE、第三方声明和适用平台 SBOM 缺失时不得发布二进制。
- `.gitattributes` 必须以 `text=auto eol=lf` 固定自动识别的普通文本，不能用 `* text` 强制二进制为文本；BAT/PS1 继续 CRLF，二进制必须保持 `-text` 与原始 blob 字节。Windows 源码归档还必须显式使用 `git -c core.autocrlf=false archive`，并以 `autocrlf=true` 全新 clean checkout、二进制逐字节一致和 true/false archive Core Build ID parity 共同守护。
- 发布手册、缓存复用门禁和收据审计中锁文件的期望 SHA-256 必须以精确 RC 的 LF Git blob、`git -c core.autocrlf=false archive` 或全新 LF checkout 为真值，并由 `core.autocrlf=true/false` archive parity 契约锁定；不得从可能保留旧 CRLF 物理字节的持久化 Windows 工作树计算并固化期望值。工作树文件哈希与 LF Git 真值不符时必须停止，不得把主机换行产物写回手册。
- 发布契约如果创建临时 Git 仓库并从当前 checkout 获取 `HEAD`，必须兼容 GitHub `actions/checkout` 的浅源仓库；需要 fetch 时应显式接受已知浅边界，并至少在 `--depth 1 --no-local` 源仓库中跑一次动态回归。不得通过把 CI 全局改成完整历史来掩盖测试夹具对完整仓库的隐式依赖。
- Windows 初始化器的动态契约不得依赖 pytest 临时目录所在卷的实时剩余空间；测试必须在 fresh `pwsh -NoProfile` 进程内以确定性文件系统余量分别覆盖高于阈值成功和低于阈值失败，同时保持生产 `minimum_free_disk_gib` 配置与初始化器门禁不变。不得通过清理测试主机、改用大盘临时目录或降低生产阈值掩盖夹具对宿主状态的隐式依赖。
- Windows `verify_release_source.ps1`、`prepare_windows_runtime.ps1` 与 `build_windows_portable.ps1` 都必须在解析或选择解释器前以相同的 `^3\.14\.6$` 参数门禁拒绝其它 Python patch；不得让源码预门禁比实际组包链更宽松。
- Windows 正式产品 runtime 每次从只读 `base-python` 重建后，必须在依赖安装和 runtime manifest 生成前删除产品副本的 `python/Doc`，但保留 `base-python/Doc` 作为在线/离线同源基线；验包器必须大小写不敏感地拒绝任何 `python/Doc` 成员。不得通过放宽秘密扫描、修改依赖锁或直接删除基线文档绕过上游文档中的私钥示例命中。
- Windows 哈希锁安装必须在进程内强制 `SOURCE_DATE_EPOCH=315532800`，并在 `finally` 恢复调用者原环境；安装后必须删除产品不使用且内嵌 staging 绝对解释器路径的 `python/Scripts`，使用 CSV 规则同步删除各 `*.dist-info/RECORD` 中指向该顶层目录的条目，再执行 `pip check`、import smoke 和 runtime manifest。验包器必须大小写不敏感地拒绝任何 `python/Scripts` 成员；不得通过排除 launcher/RECORD 哈希、复用已安装 runtime 或固定构建目录伪造可复现。
- Windows portable 的 `tests` 路径禁令必须区分项目内容和锁定依赖：只有 `python/Lib/site-packages/**/tests/**` 可保留上游 wheel 自带测试文件；项目源码、web、脚本、Python 基础 runtime 或其它位置的大小写变体 `tests` 仍须 fail closed。获准的依赖测试文件必须继续接受依赖范围的秘密/绝对路径扫描，并纳入 runtime tree、逐文件 manifest 和 ZIP SHA；不得全局删除禁令、按当前包名硬编码例外、裁剪 wheel/改写其 RECORD 或从哈希排除这些文件。
- `GET /api/v1/about` 不得联网；更新网络访问只允许显式 `POST /api/v1/update/check` 或用户启用的启动后延迟检查。Feed URL/主机不可由用户或客户端覆盖，必须复核 HTTPS、每次重定向、总时限和响应大小。总时限必须覆盖 DNS/代理、连接、响应头、重定向和逐块读取；遇到不可取消的系统解析调用时，只能保留一个未退出的后台 fetch worker，新的检查必须快速诊断为 offline/busy，不能积累线程。实例级检查锁不得把第二个 API 请求排队；忙碌响应只能是非持久化结果，不得覆写首个检查的缓存或 `checking` 状态。
- `v0.3` 起的 `latest.json` 与平台更新元数据必须由同一工具从真实产物生成，并校验版本、URL、长度、SHA、签名、source tag、package ID 和 core build；公开 Feed finalizer 必须从实际资产、收据和源码归档重算身份。Tauri updater 的签名验证、下载、停止 monitor、安装和重启必须由 host 管理；停止失败或用户取消时不得改变运行状态。不得为退休的预公开版本建立兼容 Feed。
- `v0.3` Tauri 新安装默认 `desktop`，已导入的显式偏好保持原值并在下次启动生效；browser 模式隐藏主窗口、只打开一次默认浏览器并常驻托盘。关闭浏览器或桌面窗口均不得停止独立 monitor。
- Windows 更新不得覆盖运行中的旧目录；使用“新 ZIP 解压到新目录 + 白名单导入设置 + 保留旧目录回滚”。迁移不得复制日志、PID、SQLite、cache、皮肤、源发票或成本产物。
- `v0.3` 发布 Feed 是最后切换点。适用平台真机、对应源码、SBOM、签名/公证、updater 实际升级、重下载复验和人工许可检查任一缺失时，不得让公开 Feed 指向候选。

## 开源冻结与 Tauri 2 规则

- 退休的预公开包只保留在 owner-only 私有备份中，不能作为新的公开 Tag、Release、Feed 或构建证据。不得为补 receipt、刷新数字或补表格重打或复用它们。
- 开源治理、许可证、文档、仓库 public 设置、Release 说明和 Feed 元数据变化不触发新应用重打。只有新包的包内输入变化、包损坏、签名失效或嵌入身份不一致时才重打；仅影响单平台时只处理该平台。
- 公开前对全部保留 refs 只执行一次 gitleaks 和一次真实业务文件扫描。发现真实秘密或真实业务数据时，先轮换/隔离并暂停公开；只有真实命中才增加净化工作。旧历史包和资产不得上传。
- 2026-08-14 的远端可达历史扫描确认存在真实目录及私有标识；用户已批准历史净化。完成候选树、Git 对象和托管面验证前，禁止将仓库设 public、上传 Release、上线 Feed 或创建公开后的 Tauri 分支。
- 每项实验开始前必须记录假设、结果会改变的决策、最小样本和停止条件；无法改变决策的实验不得执行。相同失败机制只用一个代表样本，结果矛盾、修改面扩大或机制不同才追加样本。
- 每个 RC 最多一次完整回归；先运行命中变更面的聚焦验证。Tauri `v0.3` 的决策场景固定为两种启动方式、单实例与错误端口、Host RPC 授权边界、合法/篡改更新、安装前 monitor 停止；修复后只重跑受影响类别。
- Tauri `src-tauri/` 只承担窗口、托盘、单实例、原生面板、打印、后端生命周期、随机令牌 Host RPC 与 updater。它只绑定 `127.0.0.1:8766`；未知占用必须明确失败，不能换端口或连接旧实例。Host RPC token 不得返回网页，只接受固定 localhost origin 的枚举命令。
- 安装包只放 GitHub Releases；从 `v0.3` 起同仓库 GitHub Pages 提供更新 Feed。不使用 GitHub Packages 或 App Store。Rust/Cargo/pnpm/Tauri 依赖必须锁定，Windows/macOS `doctor` 与 `bootstrap` 只能诊断环境，不得自动安装证书、Xcode 或 Visual Studio。

## 验收规则

- 自动化回归不是最终用户验收。
- 对外宣称“已验证”时必须写清：
  - 测了什么
  - 没测什么
  - 是否覆盖真实默认配置
  - 是否覆盖正式 Windows BAT
  - 是否覆盖打包产物
- Windows 用户入口变更必须至少覆盖：
  - 正式 BAT 启动
  - 停止 localhost 后监控仍运行
  - stop-all 入口停止监控
  - 根目录快捷入口
  - 首页 `/`
  - `GET /api/v1/health`
  - runtime 基础日志与 `server_state.json`
  - 正式停止
- 发布变更必须分别覆盖 Windows 真机手册与 macOS 正式发布手册；共享单测、静态契约、模拟 runtime、开发 `.app`、ad-hoc 签名和替代端口都不能冒充对应成品证据。
- 发布包不得把本机 `config/app.local.json` 原样打入或递归复制整个 `config/`；必须只生成脱敏默认配置，并扫描本机业务路径、真实发票/投影、运行态、日志、PID、SQLite、cache、秘密和开发工具。构建 provenance 必须覆盖全部实际包输入。
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

## Git 分支开发与回溯规则

- `main` 只保留已验收、可回退的稳定版本；代码、接口、前端、解析、启动、成本、发布类功能改动不得直接在 `main` 上施工。
- 大功能、用户可见功能、跨模块改动和高风险修复必须从当前稳定 `main` 新建 `codex/<task-name>` 分支开发；分支名用英文短横线描述任务，例如 `codex/voucher-draft`。
- 创建分支前必须执行 `git status --short --branch --ignored`，并确认当前分支、未提交修改、ignored 运行态和当前 `main` 基线 commit；最终回复或任务记录中必须写清本轮从哪个 commit/分支开工。
- 创建分支前若存在非本轮代码修改，必须先分类说明并决定是否暂存、提交、保留或停止；`config/app.local.json` 这类本机运行配置允许留在工作区，但不得纳入功能提交。
- 默认使用同一个工作目录切换分支；只有并行维护两条开发线、需要长期对照旧实现或用户明确要求时，才使用 `git worktree`。使用 worktree 时必须说明新目录路径、绑定分支和清理方式。
- `push` 不是默认收尾动作；只有用户明确要求“推送 / 上传到 GitHub / 更新 PR / 创建 PR”时，才允许执行 `git push`。不得因为本地提交完成就自动推送。
- 用户明确要求推送功能分支时，使用 `git push -u origin codex/<task-name>`；不得把未验收功能直接推到 `origin/main`。
- 用户明确要求创建或更新 PR 时，才允许推送分支并创建/更新 GitHub Draft PR。PR 描述必须列出变更范围、测试结果、未覆盖项、敏感路径/本机配置检查结论和回退方式。用户明确满意后，才允许合并进 `main`。
- PR 合并前必须复核 PR diff、测试结果、未覆盖项、`config/app.local.json`、真实发票路径、运行态、发布产物和本机业务路径；发现风险时先修复或停止，不得带风险合并。
- 未合并的功能如果不满意：切回 `main`，删除本地分支和远端分支即可；不得为丢弃未合并功能去重写 `main` 历史。
- 已合并的功能如果不满意：优先使用 `git revert <merge-commit>` 或 `git revert <commit>` 生成反向提交；禁止默认使用 `git reset --hard`、强推或重写共享历史，除非用户明确要求并确认风险。
- 本地未提交试验只能在功能分支内丢弃；不得在 `main` 上做“试试看”的高风险改动。
- 未经用户明确要求，不做 force push，不改写已推送历史，不做 rebase/squash 来隐藏或重排既有提交。

## Git 提交与推送速查

- 开始提交前必须先执行 `git status --short --branch --ignored`，确认当前分支、领先/落后关系、未提交修改和 ignored 运行态；不得沿用旧状态判断。
- 提交范围必须用显式文件清单暂存，优先 `git add <file...>`，不得用 `git add .`、`git add -A` 这类会把本机运行态、配置或产物一并扫进去的命令。
- `config/app.local.json` 默认不提交本机运行配置；只有确认内容已脱敏、`watch_dir` 等路径符合“项目内相对路径、包外用户目录不写入默认示例”的规则时才允许暂存。含业务绝对路径、最近目录、真实发票路径的本机配置必须留在本地。
- 暂存后必须检查：
  - `git diff --cached --name-status`
  - `git diff --cached --check`
  - 对 staged diff 搜索本机业务路径、`.lnk`、`.venv`、`runtime`、`dist`、`运行状态`、`__pycache__`、真实发票和成本产物关键词。
- 代码、接口、前端、解析、启动、成本或发布相关提交，必须先跑与风险匹配的测试；常规提交优先执行 `.venv\Scripts\python.exe -m pytest` 和 `.venv\Scripts\python.exe -m compileall src tests`。纯文档提交可不跑完整测试，但最终回复必须说明未运行原因。
- 提交信息使用清晰英文祈使句，例如 `Add recent watch directory removal controls`；不要改写用户已有历史，不做 rebase/squash，除非用户明确要求。
- 推送必须由用户明确指定；没有明确“推送/上传/更新 PR/创建 PR”要求时，不得执行 `git push`。用户要求推送时，推送目标必须匹配当前任务分支：功能分支使用 `git push -u origin codex/<task-name>`；只有已在 `main` 上完成验收合并或用户明确要求直推稳定主线时，才使用 `git push origin main`。
- 如果 GitHub HTTPS 短暂超时，先重试并用 `git status --short --branch`、`git branch -vv` 判断本地是否仍领先；如果远端有冲突或不可访问，不擅自改分支名、不强推，停止并报告。
- 推送后必须复核：
  - `git branch -vv`
  - `git log --oneline --decorate --graph --all -8`
  - `git ls-remote --heads origin <当前分支名>`；涉及主线合并或推送时同时检查 `git ls-remote --heads origin main`
  - `git status --short --ignored`
- 最终回复必须按 `modified/deleted/untracked/ignored/warning` 分类说明工作区状态；如果 `config/app.local.json` 仍修改，必须说明它是本机运行配置并未上传。

## 收尾规则

- 任何项目变更都必须更新 `CHANGELOG.md` 的 `Unreleased`。
- 后续变更记录必须按时间写入，优先使用 `YYYY-MM-DD 任务标题` 小节；记录内容必须实事求是写清任务需求、执行过程、采用方案、任务结果、验证范围和未覆盖项，不得只写“优化/修复/已完成”这类无法复盘的空泛描述。
- 行为、结构、入口、验收口径变化时必须同步更新 `README.md` 与 `IMPLEMENTATION_STATUS.md`。
- 涉及旧功能迁移、缺口修复或验收口径变化时必须同步更新 `docs/MIGRATION_GAP_CHECKLIST.md`。
- 如果本轮修复触发新模式或新风险，必须回写本文件，形成长期规则。
- 开发、调试、测试、烟测、解压验收、打包验收产生的临时文件和临时目录，收尾前必须清理；确需保留时必须在回复中写明保留路径、原因和后续清理动作。
- 收尾前必须运行 `git status --short --ignored` 并分类说明：
  - `modified`
  - `deleted`
  - `untracked`
  - `ignored`
  - `warning`

## 当前 Git 快照

- 更新时间：`2026-08-14`。公开 `main` 的提交 ID 只在候选树扫描和根提交完成后记录；不继承旧提交、Tag 或 Release 身份。
- 原工作区、stash、本机配置、未跟踪资产、ignored 运行态和真实业务文件都不属于公开根提交或发行输入，不得清理或混入。
- 私有历史备份的存在不构成公开发布资格；恢复旧图只能在仓库保持 private 时由所有者执行。
- 每次任务开工、提交、推送和收尾前仍必须重新执行 `git status --short --branch --ignored`，不得沿用本节快照数字。
