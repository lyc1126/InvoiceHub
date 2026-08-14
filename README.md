# 一站式发票汇总系统 重构版

English project name: `InvoiceHub`.

这是现有发票汇总工具的平行重构版。目标是保持现有 `v1 localhost` 用户体验与 `/api/v1` 兼容接口，同时把核心能力拆成可维护、可测试、可发布的商业化工程结构。

公开仓库从经过审计的脱敏源码快照开始。旧私有提交图、验证材料、Tag 和二进制包均不属于公开历史，也不会作为公开 Release 上传。历史净化范围和发布门槛见[执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。

首个公开开发版本为 `0.3.0-alpha.1`。它将以 Tauri 2 实现统一桌面壳，复用既有 Python/FastAPI/Web/独立 monitor 和全部业务核心。Tauri 只处理窗口、托盘、单实例、原生面板、打印、后端生命周期、Host RPC 与 updater；安装包仅放 GitHub Releases，更新 Feed 从 `v0.3` 起由同仓库 GitHub Pages 托管。

## 单仓库与双平台成品

本项目采用 monorepo：无论在 Windows 还是 macOS 执行 `git clone`，源码目录都会同时包含共享的 `src/`、`web/`、Windows 入口 `scripts/windows/` 和 macOS 壳 `macos/InvoiceHubMac/`。看到另一平台源码不代表最终包体混合，也不应在 Windows checkout 中手工删除 `macos/`。

- Windows 源码开发只通过根 BAT 的 `-Development` 模式调用当前 checkout；正式发布只运行 Windows 构建脚本，产出 `windows-x64-portable.zip`。验包器使用精确路径白名单，并拒绝 macOS 壳、Swift/bundle、Mac 依赖锁和 Unix Python runtime。
- macOS 开发和发布只通过 `macos/InvoiceHubMac/` 下的脚本；正式 `.app`、DMG 和 Sparkle ZIP 只嵌入共享核心、Mac 锁和 arm64 Python。验包器扫描整个 `Resources`，拒绝 Windows BAT/PowerShell、Windows 锁与 `.exe/.dll/.pyd/.msi/.msix`。
- 两个平台共享同一 `RC_SHA` 和 core build ID，但 package ID、运行时、启动器、可写目录和成品文件互不复用。源码共存用于避免业务算法分叉，成品互斥用于避免平台文件混包。

## 快速启动

Windows 开发环境：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\启动一站式发票汇总系统.bat -Development
```

默认地址：

```text
http://127.0.0.1:8766/
```

如果启动日志出现 `WinError 10013`，先用 `netsh interface ipv4 show excludedportrange protocol=tcp` 检查 Windows 排除端口范围；当 `8766` 落在排除范围内时，将 `config/app.local.json` 的 `port` 改为未被占用且未被排除的本机端口后重启。端口绑定失败属于 Windows 运行环境问题，不代表发票识别失败。

首页“选择文件夹”只负责调用系统原生选择器并把结果放入输入框，页面会显示“待保存目录”，输入框会滚到路径末尾便于确认目录名；确认无误后点击“保存目录”才会切换当前活动发票目录，并把该路径加入最近保存的文件夹记录。目录按钮下方会用分割线展示“当前使用”和“过去保存”的路径选项，点击历史路径只会填入待保存草稿，不会直接切换活动目录；过去保存路径右上角的 `-` 可从记忆中删除该路径，路径较多时会在该区域内纵向滚动。路径卡保持固定宽度，长路径不撑宽、不换行，鼠标覆盖或键盘聚焦时会在卡片内部横向滚动查看完整路径。项目根目录内的发票目录会按相对路径写入 `config/app.local.json`，包外目录才保存为绝对路径。

首页发票列表会按源文件扩展名显示 `PDF/OFD/XML` 浅色格式徽标，销售方列固定宽度并单行省略，便于把发票号、票种、金额等参数前移展示。列表所有表头、文字、金额、排序控件、按钮、徽标和勾选框均水平/垂直居中；发票大类不再显示“大类：”前缀，增值税专用发票和普通发票使用不同的高对比度徽标，空大类仍显示 `--`。分类徽标与识别状态徽标固定在同一主行，下方业务类型文案继续显示“业务：具体类型”并缩小 30%。每行状态只显示一枚徽标：分类缺失、未知或冲突优先显示对应类型错误，其次显示普通“识别失败”或“重复发票”，没有显式异常时显示“已识别”；完整类型识别说明保留在徽标的悬停标题和无障碍标签中。开票时间列旁边提供上下三角排序按钮，可在正序和倒序之间切换，排序只调整当前筛选后的可见列表。列表右侧可逐张勾选发票，标题区会实时显示勾选发票的价税合计金额和张数，并提供“一键全选”和“清除勾选”按钮；两个按钮位于合计块左侧，勾选合计保持标题区最右侧。批量全选只作用于当前筛选后的可见列表，筛选或刷新后只保留当前可见列表中的勾选金额。发票详情页的核心字段区域提供“打开文件”和“打开文件所在位置”两个动作，分别用于打开源发票本体和打开其所在文件夹；右侧将“手工修订”和“本票成本明细”作为同级面板上下展示，不再内嵌详情页一致性板块。本票成本明细按当前发票自己的成本明细行汇总同项目数量、除税总计和价税合计，并在项目下列出同项目同规格的数量、算术平均单价和加权平均单价；每个项目按真实内容高度排布，外层成本区负责有界纵向滚动，不会再把项目压扁并裁掉规格表。

“勾选价税合计金额”整块是语义化按钮，无勾选时禁用；有勾选时点击可打开“已勾选发票合计详情”，hover/active 不改变合计块颜色，键盘焦点仍有可见焦点环，不另设“查看合计”按钮。合计详情在桌面端保持三张醒目金额卡、项目与税率标题、项目统计和真实规格表格；该共享基础样式必须位于顶层，因此 macOS WKWebView 与 Windows 浏览器使用相同的信息层级。2026-07-30 曾因设置页窄屏媒体查询遗漏结束大括号而将这些桌面规则错误包入 `@media`；前端契约现解析规则层级，防止选择器文本仍存在却只在窄屏生效。合计先按同票家族去重：优先当前发票号码，其次文件名中的 20 位号码，仍无法识别时按源文件路径区分；票头与文件名取得的同一号码视为同一张票。弹窗顶部三项金额分别只累计票头 `除税价 / 税金 / 开票金额` 的合法值，同一家族同字段出现多个不同合法金额时该字段不计入并提示冲突。明细只读当前 `watch_dir/成本发票明细.csv`，不会触发重建或重新解析；按发票号匹配，手改号码无结果时回退源文件，按 `内部项目名称 + 明细税率` 拆分项目块，再按 `规格型号 + 单位` 汇总。税率 `0.13` 与 `13%` 统一显示为 `13%`，缺失税率明确显示“税率未识别”；规格数量与四项均价继续沿用详情页公式，不改变成本 CSV/XLSX/JSON 或 `/api/v1/cost-analysis` 契约。合计请求的同步文件读取与聚合在服务线程池中执行，弹窗生成期间 localhost 的 health 和其它请求仍可继续响应。内置 Ink Pulse `1.3.0` 的 `body` 入场动画全程只做 opacity 淡入，不在任何动画帧设置 transform；因此页面已滚动时打开勾选合计或设置关闭等固定弹窗，顶部操作仍保持在视口内可达；在不超过 `420px` 的窄屏上，合计项目内三项金额卡改为单列，长金额不再被三列窄卡逐字拆行，规格表横向滚动和弹窗内部纵向滚动保持不变。

首页已勾选发票可直接生成源文件预览或批量打印。预览 job 保留每条已选源文件及顺序，支持 PDF/OFD/图片分页、XML 受限文本、分页切换、缩放、适合宽度和受控的“打开文件/打开所在位置”；预览只接受仍属于当前 `watch_dir` 的作业内路径，并受 15 分钟闲置超时、页数、像素和缓存上限保护。预览弹窗打开期间会轻量续租，分页/文本/打开操作也会刷新闲置时间；回到前台时如发现后端重启或旧作业已回收，页面会自动重建原勾选预览并尽量保留当前文件和页码，不再因固定 15 分钟截止要求人工点“重试”。弹窗关闭后停止续租，目录切换或源文件变化仍会按安全边界拒绝旧作业。批量打印按同票家族收敛为可打印 PDF 页面，普通浏览器打开受控打印页；macOS 壳则只允许受信主 WebView 创建的打印子窗口调用系统打印面板。预览和打印均不改变源发票、普通汇总或成本产物。

详情页规格明细始终保留真实 `<table>`，宽列由“本票成本明细”内部横向滚动容器承接，不把整个页面撑宽；窄屏下的长源文件名会在“源文件与状态”卡内安全断行，同样适用于 `?no_skin=1` 恢复入口。

勾选一张或多张发票后，标题区 `>>` 会启用“打印已勾选发票”。系统先用 `invoice_key + source_path` 复核列表身份，再按同票家族去重并准备当前目录内的 PDF 票面；勾选 OFD/XML 时，如果同票家族存在 PDF，会自动使用该 PDF，只有 OFD/XML 而没有 PDF 时整批不开始并明确列出原因。每个原 PDF 页面独占一张打印纸，多张或多页发票可在一次 Chrome/Edge 默认打印对话框中打印；横向、纵向页面只声明对应方向，纸型沿用打印机或用户在对话框中的当前选择。打印快照只在 localhost 进程内短期保存，不写入源发票目录、普通/成本投影或 SQLite 发票主数据；单次最多接收 100 条勾选记录、200 个 PDF 页面，超限、加密、损坏、移动、弹窗被拦截、票面加载失败或浏览器不支持打印都会给出可恢复提示。

打印页会等全部 PNG 票面真正解码并完成浏览器绘制后才首次打开打印对话框，避免第一次预览为空；命名页只声明横/纵方向、不强制 A4，打印盒使用实际页框的 `100% × 100%`，不再使用会随 Chrome 预览重算的 `100vw/100vh`。分页只发生在下一张真实票面之前，因此 A4/A5 单页不会附带空白纸，预览也不会因纸型与动态视口互相反馈而持续跳动。

普通导航面向日常操作，保留首页、成本分析、单据、做账、OCR、一致性和设置。`/settings` 按概览、目录与产物、运行与监控、单据、外观、偏好、OCR 和诊断分类展示当前系统状态；当前已开放安全配置、日常运行控制和低风险展示偏好：发票目录选择/检查/保存/最近目录删除、出库发票目录选择/保存/最近目录删除、入库单/出库单默认信息编辑、皮肤启用和恢复默认外观，刷新运行状态、启动/停止独立监控 daemon、手动重新汇总、打开监控日志、打开运行状态目录和关闭本系统，以及成本页默认显示行数、长路径显示方式、已导出单据处理策略、OCR 候选目录与系统关闭方式偏好。关闭方式默认“每次询问”，弹窗可选择“保留监控，仅关闭 WebUI”或“关闭 WebUI，并停止监控”，底部“记住本次选择”会保存所选方式；偏好分类可随时改回询问或切换固定行为。macOS 壳连接 `externalCompatible` 后端时会禁用 Web 设置页关闭及 monitor 启动/停止入口，原生菜单和侧栏也不会改变该未知服务；这限制当前壳的所有权动作，不把 localhost API 误当作多客户端权限系统。owned 壳的原生停止固定保留 monitor。目录选择仍保持“待保存目录”草稿，自动刷新和 SSE 重连不会覆盖未保存输入；偏好不改变发票源文件、普通汇总、成本 CSV/XLSX/JSON 或开票参考行级加价率口径；高级诊断中可复制摘要、运行配置健康检查并导出不含源发票和投影正文的支持包，备份恢复仍未开放。皮肤 ZIP 导入和替换继续保留在 `/skins`，从设置中心“外观”分类进入；皮肤异常时可用 `/settings?no_skin=1` 临时绕过当前皮肤。

设置现另有“关于”分类：显示版本、更新通道、平台/架构、包类型、package ID、core build ID 和公开链接；`GET /api/v1/about` 只读本地信息，不会联网。用户点击“检查更新”或开启“启动后自动检查”后，系统才访问固定 HTTPS 白名单 Feed；发现更高 beta 时在关于标签和版本卡显示绿色上箭头，并列出版本、发布时间、包大小、SHA-256 和发行说明，由用户决定是否升级。Windows 首版只支持系统默认浏览器，桌面窗口选项明确禁用；macOS 可在“桌面窗口/系统默认浏览器”之间选择，下次启动生效。Windows 使用新目录解压与白名单设置迁移，macOS 安装交给 Sparkle，任何更新检查失败都不影响本地发票功能。

目录检查会递归统计当前目录下的 PDF/OFD/XML 发票源文件；如果目录能读取但只包含 `.zip/.rar/.7z` 压缩包、成本产物或其它文件，页面会显示 warning，并提示先解压或改选解压后的发票文件夹。点击“重新汇总”后若结果为 0 条，页面会直接显示这个原因，而不是只显示笼统完成。

macOS 未签名开发 `.app` 重建后，系统可能因应用代码身份变化重新要求“下载”等受保护目录的访问权限。若 localhost 严格握手成功，但页面出现 `Load failed` 或 health 的 `background_status=failed`，应在用户明确允许后通过首页原生 `NSOpenPanel` 重新选择并保存当前目录，再确认 `background_status=ready`、手动重新汇总成功且源文件预览可打开；仅有 `health.ok=true` 不能证明业务目录已经获权。

首页双栏概览下方、筛选栏上方会显示独立全宽的“业务资料夹”横条，避免资料夹内容把右侧“当前档案”卡拉高并在左侧留下空白。该入口不会改变 `watch_dir` 的发票扫描语义，只用于连通当前公司完整资料夹：当当前扫描目录是 `公司资料夹/成本发票` 这类子目录时，系统会自动识别上一层公司资料夹，并通过 `/api/v1/business-dossier` 暴露公司资料夹、发票扫描目录、成本发票、银行流水、进项抵扣、开具发票和成本产物等快速链接；资料夹元数据只做一次有界扫描（4,000 个目录项或 1.25 秒，不跟随符号链接），若返回 `scan.complete=false`，页面显示的文件数是已读取部分的下界，并会保留已加载的发票列表；`/api/v1/business-dossier/open` 只允许打开当前业务资料夹或当前 `watch_dir` 内的文件/文件夹。

普通导航“单据”入口对应 `/documents`。入库单按当前活动发票目录里的 `成本发票明细.csv` 选择 `发票号码` 后生成页面预览；出库单按单独保存的“开具发票目录”扫描目录内 `PDF/OFD/XML` 发票，选择 `发票号码` 后生成页面预览。两类单据都不会在启动时自动生成，也不进入监控循环；只有点击“导出入库单/导出出库单”才复制当前 Excel 模板并填充生成文件。手填字段可为空，可点击“保存默认信息”复用；默认值保存到 `runtime/local_state/documents/defaults.json`，不是发票主存储。重复导出已存在的单据时，页面会提示已导出文件所在文件夹，可选择导出副本、取消或打开该文件；如果原文件被占用会提示先关闭，如果原文件已删除则不再提示已存在。

单据预览表随页面纵向自然展开，不生成页面内第二根纵向滚动条；表格宽度不足时，预览容器只负责横向滚动。单据页和设置中心“单据默认信息”共用按实际容器宽度响应的表单口径：空间充足时保持四列，中等宽度自动收为两列，窄容器改为单列，不会用固定输入宽度撑出卡片或页面。OCR 页面同样采用页面级纵向滚动，候选文件表只保留必要的横向表格滚动。

单据导出路径固定为：

- 入库单：`watch_dir/入库单/入库单-<发票号码>-<开票日期>.xlsx`
- 出库单：`outbound_invoice_dir/出库单/出库单-<发票号码>-<开票日期>.xlsx`

普通导航“做账”入口对应 `/bookkeeping`。W8 已把该页接入安全执行契约：凭证使用稳定 `posting_key` 和 `proposal_revision_hash`，页面展示服务端结构化 `blockers[]`，只有当前 revision 通过统一 validator 后才允许审批；导出必须携带 store revision、精确 proposal revision 和显式 item 清单，并生成不可变的 `凭证/批次/<batch_id>/manifest.json + 凭证导入.xlsx`，绑定单一账套、单一期间、行号、计划凭证号、signature 和文件 SHA256。旧逐张 `PATCH /api/v1/bookkeeping/import-result` 已停用并固定返回 HTTP 410，导入观察只允许通过批次 finalize API 整批、幂等回写。`confirmed_success` 只有在回传完整批次逐项观察、每项 `observed_state=imported` 且存在 `readback_hash` 时才成立；同时携带 `commit_not_attempted=true` 或 `ledger_absence_confirmed=true` 会作为矛盾证据被拒绝。明确失败则必须证明未点击提交，或由 `reconcile_only` 完整回读证明整批未落账。

W9 已在同一页面补齐“凭证人审 / 映射规则 / 账套设置”三个视图。账套 profile 与账套环境、稳定身份、科目表及辅助核算档案 SHA 绑定；会计决定可确认业务类别、付款状态、税务处理及证据、入库覆盖、项目分配、科目和辅助核算。映射规则保存前必须预览影响，`manual/ai_confirmed` 规则不得静默覆盖，保存后只定向重算 resolver 结果发生语义变化的草稿；“重算当前”也不会在提案无变化时重置 `blocked/rejected`。映射和凭证状态迁移都是 preview/apply 两阶段，apply 复核源 SHA、preview hash、revision、绑定和备份 SHA，禁止启动时自动迁移。

runner 必须显式传入 `--batch-manifest`，不会再猜测“最新 XLSX”；`--import-file` 只用于复核 manifest 已绑定的同一文件。W8 仅开放 batch-bound dry-run，真实 Safari `apply`、读回和 `reconcile-only` driver 留待 W10：

```bash
python -m invoice_hub.runners.jierui_voucher_import \
  --company-dir "<公司资料夹>" \
  --batch-manifest "<公司资料夹>/凭证/批次/<batch_id>/manifest.json" \
  --mode dry-run
```

W8/W9 技术与产品能力已完成，但当前真实公司资料夹中的 7 张历史草稿仍是未迁移的 version 1 `draft`，未审批、未导出、未生成业务批次。下一个业务步骤不是自动迁移：必须先在用户明确授权下从正式目标账套重新采集并确认 profile、完整科目/辅助核算档案，再逐票确认业务、税务、付款、入库和项目分配。事实齐备且用户再次授权后，才可执行源文件 SHA256、preview hash 和 revision 绑定的 migration apply。

停止：

```powershell
.\停止一站式发票汇总系统.bat
```

该停止入口只停止 localhost 页面服务，不停止持续监听。需要同时停止监听时使用：

```powershell
.\停止一站式发票汇总系统并停止监控.bat
```

设置中心“运行与监控”也提供“关闭本系统”：默认先弹窗询问是否保留独立监控，勾选“记住本次选择”后可按已保存方式直接关闭；“偏好”可随时修改。该页面入口不会改变上述两个正式 BAT 的固定语义。

启动独立监控时，接口会等待 daemon 完成首轮同步、文件事件观察器或周期兜底初始化和一次补漏同步后才返回成功；设置页与首页会区分“启动中”“运行中”和“运行中（周期兜底）”。这样即使 PID 检测很快，启动返回后立即放入发票也不会掉进观察器尚未就绪的空窗。

根目录还会保留 `启动一站式发票汇总系统.lnk`，指向同名启动 BAT；如丢失可重新运行 `.\scripts\windows\创建根目录快捷方式.ps1`。

## 持续监听

首页“启动监控”会启动独立监控进程。关闭浏览器不会停止 localhost，也不会停止监控；`/api/v1/bridge/status` 会返回真实 `running/pid/lock/log_path/last_sync_at`。

启动 localhost 后，系统会在后台自动执行一次首轮汇总同步；如果当前活动档案缺失或发票目录有新增/更新/删除，会自动生成 `发票汇总.csv/.xlsx` 和成本产物，首页随后通过事件流刷新。首页先可打开，后台汇总不阻塞 `/` 和 `/api/v1/health`。

监控默认策略：

- 启动时校验一次。
- `.pdf/.ofd/.xml` 文件变化后 1 秒合并处理。
- 每 60 秒只比较路径、mtime、size 做兜底校验。
- 普通汇总写入 `workspace/发票汇总.csv/.xlsx`。
- 成本产物写入当前 `watch_dir/成本发票明细.csv`、`watch_dir/成本发票汇总.xlsx`、`watch_dir/成本开票状态.json`。
- 业务日志写入 `workspace/文件变化监控日志.txt`。
- 正式配置的运行状态根目录是 `运行状态/`。

## 开发者与 Agent 阅读路线

开发实现的权威入口是 [`docs/DEVELOPMENT_ARCHITECTURE.md`](docs/DEVELOPMENT_ARCHITECTURE.md)。公开 `main` 已从单一脱敏根提交开始，不继承旧的私有提交、Tag 或 Release 身份；旧图仅保留在私有归档。当前没有公开 Release、更新 Feed 或 Tauri 开发分支。后续从 `main` 创建 `codex/tauri2-unified-desktop` 时，以 `0.3.0-alpha.1` 开始用 Tauri 2 统一桌面壳，但仍复用 Python/FastAPI/Web/monitor 业务核心。共享核心与平台边界见[平台架构](docs/architecture/PLATFORM_ARCHITECTURE.md)，公开净化记录见[执行记录](docs/release/HISTORY_SANITIZATION_EXECUTION.md)。

接手工程或定位任务时按以下顺序阅读：

1. 先读 [`AGENTS.md`](AGENTS.md)，确认产品边界、数据准确性和验收不变量。
2. 再读[开发架构总入口](docs/DEVELOPMENT_ARCHITECTURE.md)，建立端到端系统模型。
3. 使用 [Agent 任务导航](docs/architecture/AGENT_TASK_MAP.md)按发票提取、成本、监控、前端、Windows、发布或文档任务定位首要文件。
4. 按任务进入[完整文件地图](docs/architecture/FILE_MAP.md)、[接口与运行流程](docs/architecture/INTERFACES_AND_FLOWS.md)、[数据结构与算法](docs/architecture/DATA_AND_ALGORITHMS.md)或[注释与设计原因地图](docs/architecture/COMMENT_RATIONALE_MAP.md)。

文件地图记录逐文件职责、上下游、产物和测试；新增、删除或重命名工程文件时必须同步更新。架构文档不记录 `config/app.local.json` 的本机值，也不把运行态、真实发票或本机验收资产当作源码。

## 开发验证

Windows：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src tests
```

Mac / Docker：

```bash
docker compose run --rm test
```

如果 Docker Hub 直连不可用，可以先配置 Docker Desktop 代理/镜像源，或临时指定已拉取的 Python 镜像：

```bash
INVOICE_HUB_TEST_IMAGE=<local-or-mirror-python-image> docker compose run --rm test
```

Docker 只作为开发验证，不作为正式 Windows 离线包运行依赖。

Mac 本地壳开发：

```bash
cd macos/InvoiceHubMac
./script/build_and_run.sh
```

只构建或刷新本地 `.app`、不打开 App 且不停止当前 localhost/监控时，可执行 `./script/build_and_run.sh --build-only`。该模式仍会把当前仓库的 `src`、`web`、内置皮肤字体与纹理复制到 `dist/InvoiceHubMac.app/Contents/Resources/invoice-hub-core` 并重建 build ID。

当前 macOS 第一版采用 SwiftUI + WKWebView 本地壳：Swift 负责 `.app` 窗口、菜单、目录/文件选择、Sparkle 更新和后端进程生命周期，业务核心继续复用现有 Python/FastAPI、`/api/v1`、持续监听、成本分析、单据生成和做账人审能力。开发脚本会生成本地 `macos/InvoiceHubMac/dist/InvoiceHubMac.app`；正式脚本则从精确 Git commit 复制只读 core、嵌入 Python 3.14.6 arm64 运行时和锁定依赖，生成签名 `.app`、Sparkle ZIP 与 DMG。正式模式只接受 `Contents/Resources/invoice-hub-core`，该 core 缺失或无效即拒绝启动，绝不回退 checkout。运行态配置、日志和 SQLite 写入 `~/Library/Application Support/InvoiceHub`，不写入 `.app`。WKWebView 页面里的目录选择通过 Swift bridge 调用 `NSOpenPanel`，皮肤页文件输入由 `WKUIDelegate` 提供单 ZIP 面板；bridge、导航和原生面板只对预期 localhost 主框架开放。正式工程路径已经建立，最终放行仍需真实 Developer ID、Apple 公证、staple、quarantine 干净机和 Sparkle 升级证据。详见 [更新体系开发说明](docs/release/UPDATE_SYSTEM.md)。

目录切换统一使用页面里的“选择草稿 -> 后端校验 -> 保存生效”流程；工具栏和菜单不再直接保存目录。重新汇总、监控启停等原生命令仍复用同一套 `/api/v1` 后端，并在完成后刷新 WKWebView。异步控制结果绑定发起时的后端代次、阶段、health 与 Process/PID，旧请求不能覆盖后来发生的停止或重启。开发脚本重新运行 `.app` 前只会收束命令行为 `invoice_hub.api.main` 且配置路径精确匹配当前 Application Support 的旧服务；TERM 超时后也必须再次核验同一 PID、命令和配置才允许强制收束，未知端口占用会明确失败，不终止、不自动换端口。

每次构建会对 App 内共享核心生成确定性 SHA-256 清单，并记录精确 `source_commit`；正式包还具有严格的 package/runtime manifest 和 CycloneDX SBOM。build/package manifest 的 source commit 必须相同，壳只有在 manifest 与 `/api/v1/health` 的 build ID、`2026-08-02-release-update-v1` API 契约、`w9-ledger-review-v1` 做账协议、完整能力集合、配置路径、运行目录、PID 和发行身份全部匹配时才接入 localhost。macOS 固定 runtime 在 manifest 前剔除 python-build-standalone 自带的三个已知 Windows shell helper 与 pip/distlib 六个 Windows launcher，并继续扫描拒绝任何其它 BAT/CMD/PS1/PSM1 或 EXE/DLL/PYD/MSI/MSIX；分发验包器的全 Resources 平台禁令不放宽。macOS 构建固定使用 Sparkle Keychain account `com.invoicehub.release`，并把 artifact SHA/大小、分发 package ID、`signature_mode`、account 和验包状态写入 schema 4 收据。内部模式要求 staging App、update ZIP App、DMG App 与 DMG 容器全为 ad-hoc；公开 Feed 只接受 `developer-id-notarized` 与 v4 验证器，并从固定 Tag 对实际 DMG/update ZIP 再次检查 Developer ID、Team ID、公证与 ZIP 字节 Ed25519，收据不能单独放行。握手不会读取可能扫描真实业务目录的数据接口，且每次请求都有时限。停止、重启和 monitor 启停只对 Process/PID/health 精确匹配的 `owned` 服务开放；外部兼容服务标为 `externalCompatible`，其原生与壳内页面控件均禁用这些动作。Sparkle 安装、更新 monitor 停止与恢复同样只接受当前 exact owned lifecycle；外部服务没有安装 bridge 且不会被改变 monitor。已验证 owned 的更新先写入升级标记并停止 monitor，取消或失败后恢复原 monitor；新版本只有在严格握手已完成、当前启动已验证为 owned running 且 startup gate 已释放后才尝试 marker 恢复，monitor ready 后才清理标记。批量打印子窗口仍只拥有受限打印 bridge。

2026-07-31 的开发版 `.app` 验收已实际打开源文件预览和 7 页批量打印系统面板；取消后页面收到 `afterprint`，关闭打印子窗口后主窗口与 health 仍存活，且没有新增 InvoiceHubMac 崩溃报告。该结果仅覆盖开发 `.app`，不代表 Windows 正式入口、core 包、DMG、签名或公证已通过。

首次运行 macOS 开发脚本时，如果 `macos/InvoiceHubMac/.backend-venv` 不存在或缺少后端依赖，脚本会建立开发虚拟环境并写入 `dev-python-path.txt`。该标记只允许存在于开发 `.app`；正式构建和验证脚本会拒绝它，并只接受嵌入的锁定运行时。

## 构建 Windows 便携包

以下流程只适用于新的 Windows RC；不复用退休预公开包的构建输入、收据或 Tag。固定打包参数由 [`docs/release/WINDOWS_REPACKAGE_CONFIG.json`](docs/release/WINDOWS_REPACKAGE_CONFIG.json) 提供，最终 `RC_SHA` 由发布协调方单独交付。Windows 真机先运行初始化门禁并建立与成品 runtime 隔离的锁定测试环境：

```powershell
pwsh -NoProfile -File .\scripts\dev\initialize_windows_repackage.ps1 `
  -SourceCommit <40位小写RC_SHA>
pwsh -NoProfile -File .\scripts\dev\prepare_windows_test_environment.ps1 -Clean
```

初始化器要求指定的 release ref、detached `HEAD` 与交付 SHA 完全相同，并写入会话证据；测试环境同时消费 Windows runtime 锁和 test-tools 锁，并以环境内受边界校验的 `.pth` 精确绑定当前 RC `src`，保证测试子进程导入相同源码。正式 runtime 不安装该绑定或 pytest 等测试包。

```powershell
.\scripts\dev\build_windows_portable.ps1 `
  -Version <new-release-version> `
  -PythonVersion 3.14.6 `
  -Architecture x64 `
  -SourceCommit <40位小写RC_SHA> `
  -Clean
```

脚本先校验机器配置，再准备哈希锁定的 Python 3.14.6 x64 运行时和 wheelhouse，以离线安装结果组装两次确定性 ZIP 并比较 SHA-256。`base-python` 保留 Python Manager 的原始文档用于证明在线/离线基线相同；每次复制出产品 `python` 后先删除产品副本的 `Doc`，锁定安装期间强制固定 `SOURCE_DATE_EPOCH`，再删除内嵌 staging 绝对路径的产品 `Scripts` 并规范对应 RECORD，最后执行 `pip check`、import smoke 和 runtime manifest。正式源码预门禁、隔离测试环境与实际组包链都拒绝非精确 `3.14.6` patch。Windows package manifest 的 source commit 必须与 build manifest 一致；构建收据记录 ZIP 的文件名、大小、SHA、source/core/package/lock identity、机器配置 SHA、联网/离线模式和 `reproducibility_checked=true`，否则最终 Feed 门禁拒绝。正式流程还要求断网后从既有 wheelhouse 重装 runtime、再次双组装，并与联网 ZIP SHA 完全相同。默认包清单包含共享核心、web、正式 Windows 入口、结构性 facts/runner、LICENSE/第三方声明、构建/包/runtime manifest、SBOM、脱敏默认配置和空 `发票文件/运行状态`。验包器只允许这些精确文件和子树，大小写不敏感地拒绝 `python/Doc` 与 `python/Scripts`，并反向拒绝 macOS 壳、Mac 锁、Swift/bundle 与 Mac runtime；`macos/`、`scripts/dev`、测试、普通项目文档、运行态、缓存、真实业务数据和本机 `config/app.local.json` 均不进入包。旧版本只能通过 `导入旧版设置.bat` 白名单迁移设置和偏好；具体版本由 `version.py` 和该 RC 的发布记录决定。

上段“测试不进入包”专指项目自身测试和 Python 基础 runtime 测试。哈希锁定 wheel 在 `python/Lib/site-packages` 内自带的 `tests` 可以原样保留，不按当前包名维护白名单，也不为缩小包体修改 wheel/RECORD；这些文件仍使用依赖范围扫描，并完整计入 runtime tree、逐文件 manifest 和 ZIP SHA。任何其它位置或缓存目录中的大小写变体仍由验包器拒绝。

正式 Windows BAT 会优先验证 `%ProgramFiles%\PowerShell\7\pwsh.exe`；该固定位置不存在时，再通过 `where.exe pwsh.exe` 使用当前 `PATH`，因此 Microsoft Store 的 App Execution Alias 也是有效 PS7 来源。只有没有可运行的 7.x 时才回退 Windows PowerShell 5.1，`INVOICE_HUB_FORCE_PS51=1` 仍用于兼容验收。共享启动模块从 localhost health 的原始响应字节显式按 UTF-8 解码，避免 PS5.1 在响应未声明 charset 时损坏中文配置和运行目录；解码后仍执行完整 PID、路径、build/package 身份校验。

## 数据口径

- 当前发票目录：`watch_dir`
- 普通汇总：当前活动档案 `运行状态/targets/<target_id>/workspace/发票汇总.csv` 与 `发票汇总.xlsx`
- 成本分析：当前 `watch_dir/成本发票明细.csv`、`watch_dir/成本发票汇总.xlsx`、`watch_dir/成本开票状态.json`
- 单据默认信息：`runtime/local_state/documents/defaults.json`
- 设置偏好：`runtime/local_state/preferences.json`，保存成本页显示行数、长路径显示、单据重复导出策略、OCR 候选目录和系统关闭方式（每次询问/保留监控/同时停止监控）
- 诊断支持包：`runtime/local_state/support_packages/*.zip`，只包含 manifest、诊断摘要、健康检查、事件尾部和日志尾部，不包含源发票或可重建投影正文
- SQLite 只存任务、事件、设置和缓存，不作为发票主存储。

发票分类使用两个独立字段：`invoice_type` 只允许“增值税专用发票 / 增值税普通发票 / 空”；`business_type` 允许“标准电子发票”，以及稀土、建筑服务、旅客运输、货物运输、不动产销售、不动产经营租赁、农产品收购、光伏收购、代收车船税、自产农产品销售、差额征税差额开票、差额征税全额开票 12 种特定业务样式。识别结果同时返回 `classification_status=ok/needs_review/conflict` 和 `classification_issue`；缺少可靠证据、遇到未知标签或同票多格式非空分类冲突时不猜值。

PDF 分类只使用发票标题和左上业务标签坐标；无坐标文本只接受带“特定业务类型 / 业务标签”等明确前缀的值。OFD 优先使用 `CustomTag.xml` 的类型字段与带坐标文本对象，XML 只读取明确的类型/业务字段。公司名、项目名中的“建筑服务 / 货物运输”等词不会触发业务分类，`XT` 只有在业务标签位置精确匹配时才表示“稀土”。同一 20 位发票号家族只补齐空分类，已有非空结果不互相覆盖；冲突会进入一致性报告和待核对状态。

成本分析重建会扫描当前 `watch_dir` 下的 `PDF/OFD/XML` 发票并按同一个发票号码家族去重；同一张发票同时存在多种格式时，优先选择除税金额和税额都校验通过的结构化候选，不会重复计入库存。PDF 明细使用“表头识别 + 行基线分组”动态还原列，不再依赖一套固定横坐标；建筑服务、旅客运输、货物运输和不动产版式中的专属列只用于分隔，金额、税率和税额按实际表头定位。XML 使用结构化 `IssuItemInformation` 明细节点，OFD 使用 `CustomTag.xml -> ObjectRef -> TextObject` 中的项目、规格、单位、数量、单价、金额、税率和税额字段；无法识别可靠表头或结构化明细时会进入“发票校验”待核对，不用文件名或纯文本顺序猜测明细。

详情页“本票成本明细”与“手工修订”为同级标题面板，只读取当前 `watch_dir/成本发票明细.csv` 中匹配当前发票的明细行；优先按详情页当前发票号码匹配 `发票号码`，若发票号已手工修订导致无匹配，则回退到源文件路径或文件名匹配 `源文件`。项目汇总按 `内部项目名称` 分组，展示 `数量合计 / 金额(除税)合计 / 价税合计`；规格汇总按 `内部项目名称 + 规格型号 + 单位` 分组。算术平均单价按明细行原始单价平均：除税为 `avg(金额(除税) / 数量)`，含税为 `avg((金额(除税) + 税金) / 数量)`；加权平均单价按库存口径：除税为 `sum(金额(除税)) / sum(数量)`，含税为 `sum(价税合计) / sum(数量)`。数量显示 3 位小数，金额和单价显示 2 位小数，无法计算时页面显示 `--`。

成本分析“开票参考”按 `发票代码(**内文字) / 内部项目名称 / 规格型号 / 单位` 生成与旧系统兼容的 SHA1 `reference_key`。沿用旧目录时，系统会读取既有 `成本开票状态.json` 中的已开数量、已开参考金额快照和状态更新时间；如果旧 JSON 缺少快照字段，也会从同目录 `成本发票汇总.xlsx` 的“开票参考”sheet 兜底恢复，避免重建后丢失用户已锁定状态。

`/costs` 的“开票参考”支持逐行或批量填写已开数量，也支持按行填写、锁定、解锁加价率；勾选后的批量加价率操作只作用于已选行。已开数量和加价率输入框只接受数字，已开数量不能超过本行数量合计。点击行内或批量“锁定/解锁”只修改页面草稿，并会立即重算当前页面里的本行含税平均单价、参考价税合计、已开/未开数量和金额以及顶部已开/未开库存合计；点击“保存状态”后会写入当前 `watch_dir/成本开票状态.json`，并自动重新读取后端快照刷新页面，无需手动点“刷新”或“重新汇总”。保存已开数量时会锁定当次已开参考金额/税金/价税合计快照，后续新增同一 `reference_key` 的成本明细只会增加未开部分，不会放大已保存的已开金额；只修改某行加价率不会重写已有已开金额快照。

成本分析页在显示汇总和下方列表之间提供列表控制行：左侧放刷新、重新汇总、打开成本分析表、复制当前表格、批量已开数量、批量加价率和保存状态按钮，右侧放成本四标签切换；四标签左侧的圆形 `!` 可通过鼠标悬停或键盘聚焦查看三张成本表中平均单价算法说明；系统服务连接状态使用彩色提示区分初始化、已连接和重连；页面也会展示最近保存的文件夹路径。成本四张 sheet 使用固定列宽，子表框内部提供竖向滚动，并在左下角提供 `30 / 60 / 100` 三档可视行数，默认档位可在设置中心“偏好”分类调整；档位只控制表格窗口高度，不裁剪真实 `<table>` 行，数据量小于等于档位时按实际条目数量自然收缩，数据量大于档位时在子表框内滚动查看，横向滚动仍由表格容器承担；子表滚动到上/下边界后继续滚轮或触控板滚动会交给主页面滚动条。过长源文件、项目、规格、发票号等文本默认单行裁切，鼠标覆盖或键盘聚焦时会在单元格内从头到尾单向滑动查看完整内容，不显示单元格内滚动条。成本发票明细的 `平均单价(含税)` 按该行发票识别出的 `(金额(除税) + 税金) / 数量` 计算。项目规格汇总采用双口径：`平均单价(除税)`、`平均单价(含税)` 与新增的 `库存平均单价(除税)`、`库存平均单价(含税)` 均按库存成本加权平均，即 `sum(金额或价税合计) / sum(数量)`；`采购参考平均单价(含税)` 按同组明细行原始含税单价做算术平均，只作为采购价格参考，不参与库存金额和开票参考金额计算。开票参考工作簿、API 和前端可见列表展示的 `平均单价(含税)` 为开票预估口径，其中 `average_unit_price` 是库存加权除税成本，`reference_average_unit_price` 为库存加权除税成本叠加行级加价率，`reference_average_unit_price_with_tax` 按该参考单价乘 `1.13`；参考金额、参考税金、参考价税合计和已开/未开参考金额按 `库存加权除税单价 × 数量 × 行级加价率 × 13%销项税` 联动。读取成本页或启动同步时，如果既有成本 CSV/XLSX 仍是旧表头，系统会基于当前成本明细自动刷新这三处字段结构，并保留既有开票参考状态快照。统计区中的“入库总量合计”来自项目规格汇总的 `价税合计` 总额；“已开库存合计金额”和“未开库存合计金额”使用开票参考口径，按每行自己的加价率和 `13%` 销项税汇总价税合计；行未设置时默认使用 `8%` fallback，不再有页面顶部全局加价率设置。

金额识别遵守“宁可空，不要脏值”：8-20 位纯数字不会被当成开票金额，首页合计只累计合法金额。电子发票 PDF 会保留页边界，并在同页 `价税合计/小写` 锚点后的有限窗口内只收集带 `¥/￥` 的合法值；仅当唯一有序候选满足 `除税金额 + 税额 = 价税合计`（容差 `0.02`）时才采用三项金额。多个可行组合、跨页、不一致或无货币符号时放弃该证据；明确标签 fallback 只读取同行或紧邻独立货币行。20 位发票号、日期和主体序列只恢复购买方、销售方，不再把主体后的两个明细小数当票头金额。OFD 优先读取 `CustomTag.xml` 的 `ObjectRef -> TextObject` 结构化字段恢复发票号码、日期、购销方、税率和金额三件套；已保存人工修改仍在投影阶段最后覆盖自动结果。

普通导航面向日常操作，只保留首页、成本分析、单据、做账、OCR、一致性和设置；后端诊断页仍保留在 `/backend`，用于排障时直达。

普通页面仍采用轻量多页 localhost 架构，页面切换使用主内容区域快速淡入/退出动效并尊重系统“减少动态效果”设置，避免整页大面积动画造成滚动卡顿。页面自己的初始接口负责读取首屏数据；SSE 默认从当前最新事件之后开始监听，不回放历史事件，断线重连时按浏览器 `Last-Event-ID` 续接并刷新关键数据，避免初次进入页面时重复拉取。成本分析页会把连续自动事件合并为一次成本快照刷新；手动刷新、重新汇总和保存状态仍立即执行。带版本参数的静态资源和皮肤 CSS 会使用长期缓存；成本分析页首屏只渲染当前 sheet 的真实表格，切换到其它标签时再按需渲染，同时继续保留互斥标签、真实 `<table>` 和 TSV 复制口径。

设置中心“外观”分类会读取 `/api/v1/skins` 展示皮肤列表，并可启用选中皮肤或恢复默认外观；导入和替换 ZIP 仍保留在 `/skins`，从“皮肤管理与导入”进入。默认不启用皮肤；`/skins` 页面可导入 CSS/资源 ZIP 皮肤包、启用已有皮肤、重置回默认界面，或用新 ZIP 替换已导入皮肤并立即启用。皮肤 ZIP 上传使用原始 `application/zip` 请求体，不经过前端 JSON 转码；后端只接受 `skin.json + CSS + 静态资源`，拒绝任意 JS/HTML/脚本、路径穿越、外链资源和超限文件。导入器会自动忽略 `__MACOSX`、`._*`、`.DS_Store`、`Thumbs.db` 等常见打包垃圾条目；当所有有效文件都包在同一个顶层目录下时会自动剥离这一层目录；同时允许 `asset-sources.json`、`LICENSE*`、`COPYING*`、`COPYRIGHT*` 和 `OFL-*.txt/.md` 这类只读来源/许可元数据随皮肤一起保存。内置 `animal-island` 样式位于 `web/static/skins/animal-island/skin.css`，当前为 `2.0.8`：使用本地 OFL 字体子集、原创纸纹/叶片纹理、圆润 3D 按钮、NookPhone 风格配色，并补齐设置中心的纸质面板、分类选中态、表单和诊断块，同时针对成本四张 sheet 和详情页本票成本明细同级面板优化表头贴合、滚动槽、子表内部纵向滚动、滚动链边界传递、显示行数 footer、长文本单向滑动、表格文字、数字、已开数量输入框和开票参考状态徽标；当前皮肤下首页路径分组标签与成本页开票加价率 `%` 使用白字以贴合深色背景；`已开具 / 部分开具 / 未开具` 会使用清淡但不同的状态色区分；不包含第三方脚本、外链资源、任天堂官方素材、角色、Logo、截图或字体。资源来源记录在同目录 `asset-sources.json`。皮肤异常时可用任意普通页面的 `?no_skin=1` 临时绕过当前皮肤。

内置 `ink-pulse 1.3.0` 在详情页把“本票成本明细”显示为深色项目分组：项目名与规格数量位于独立标题栏，下方保留数量合计、除税总计和价税合计三张卡，规格明细继续使用真实 `<table>`、青色表头、荧光数字和紫色横向滚动槽；首页与单据页的目录分组标签、目录选项和删除符号，分类/识别徽标、勾选合计详情、成本页的加价率与明细、关闭确认弹窗，以及一致性页差异列表均使用适合深色背景的高对比文字，禁用按钮仍保留独立灰态。表内未当前显示的加权均价列仍可滚动查看，`?no_skin=1` 仍保留同一份语义结构、数据和亮色基础样式。

一致性页 `/consistency` 会按同票发票号或文件名中的 20 位号码聚合 PDF/OFD/XML，展示同票组格式、文件和核心字段差异；详情页不再内嵌一致性板块，避免挤占手工修订和本票成本明细区域。

## Invoice Filename Organization

Settings > Directories and outputs now includes a batch invoice-file rename action for the saved watch directory.
It accepts only PDF, OFD, and XML invoices whose extracted date, seller, buyer, and legal amount are all valid.
Files are named YY-MM-DD_seller&buyer_amountYuan.ext because slash characters are not valid in Windows file names.
The action never derives core fields from the existing filename, skips unsafe collisions, keeps source files on any skip, and preserves manual field corrections across the rebuild.
The same closeable feedback pattern is used for rename completion and monitor actions: monitor start is green and monitor stop is red.

The one-click rename action uses a warm-gold surface with deep ink text; red remains reserved for stop, error, and danger feedback.
Shared operation notices mount outside the animated page shell, calculate their offset from the live sticky topbar, and therefore remain at the visible viewport top after scrolling.
Their close action is a compact round X matching the saved-path removal control and retains Escape and timed dismissal.
