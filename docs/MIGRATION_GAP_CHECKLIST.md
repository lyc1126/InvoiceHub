# 迁移与公开缺口清单

## 2026-11-17 P3 本地阶段

- B7.2：无账号列时可在映射弹窗手填本方账号，保留前导零，与预览哈希/revision 绑定。文件出现账号列时须完整唯一且一致，未映射也不能隐藏冲突；档案含私有账号，不可直接分享。保存计划保留根身份，避免并发列目录淘汰文件引用后写错位置。
- B7.1：银行目录逐文件显示内置/确认/未识别版式、交易行数、余额链断点和简单整表页脚；仅未识别文件提供映射按钮。共用受限无链接字节读取，目录 2000 文件/2 秒；每请求最多 32 冷文件/5 秒，可终止解析子进程。缓存绑定公司/目录/文件签名/档案哈希，待处理项不缓存，来源变化返回 409。


## 2026-11-17 工作区 P2 接口缺口

B3 标签使用计数、B5 凭证墙对流水/项目字段、B7 公司版式映射已在本地接入；B8 已接入独立申报/缴纳记录与明确假设的手工测算，自动政策测算仍待规则复核。B7 仅公司账簿/往来消费已确认的表格档案；OFD、扫描件、复杂表格、原生文件/Windows 语义和 CLI/凭证生成接线仍待 BANK-01。B8 未提供已复核政策自动计算或申报表导入，不修改旧草稿 `申报数据.json`。全部 WS 真实/平台验收项保持待执行，自动化通过不改变稳定 main/发行资格。未覆盖真实默认配置/业务资料、正式 Windows BAT、正式入口前台拉起、原生选择器、Tauri 宿主及打包成品；未执行真实申报、缴纳、账套操作。

## 2026-11-17 工作区 P1 接口缺口补齐

B1/B2/B4/B6 的本地源码与工作区消费已接入；目录统计包含标签，检测不写资料夹，勾选补建带计划身份，导出预览不写文件/历史，未知写响应走查询。公司成本身份只读显示、同公司开具目录和来源缓存校验已接通。历史月身份查询不重算历史成本。P2、WS 37 项真实/平台验收及成品资格保持原状态，不因合成回归自动勾选。


## 2026-11-16 工作区原型复刻（进行中）

外框与公司总览已向原型对齐，明暗外观与经典对话框遮罩协调完成；成本分析、目录筛选 / 选择、临时识别与新建公司弹窗、设置标签区等仍与原型存在差异，复刻未完成，不改变既有真实验收项状态。

## 2026-11-16 WS-03 / WS-04 开发范围补齐

经典首页项目列、比较汇总 / 流水明细、凭证缩略图墙与银行回单对应页大图已接入。回单匹配只取既有确定性算法，预览只接受后端签发的公司 / 目录 / 文件版本凭据，不开放任意路径或非监控发票。合成与自动化验证见 CHANGELOG；以下 37 项真实资料 / 平台验收保持未勾选，需另核对真实银行版式、来源变化、窄屏与原生宿主。

## 2026-11-16 新设计边界（WS-08 / WS-09）

[增量缓存与服务器链接设计](SERVER_CONNECTION_AND_CACHE_DESIGN.md)及现有原型隔离演示已登记到[未来工作](PRODUCT_BACKLOG.md#ws-08)，生产实现仍待开发。最新原型恢复右侧文件列表入口，在目录标签下拉选择子目录并汇总；空内容提示、边界内放大还原及同来源重连复用仅覆盖离线 DOM。全屏及独立服务器公司树已移除；真实浏览器布局与侧栏边界仍待实测。跨模块 SourceBinding、可靠游标续接/失效回退及人工状态保护另按设计 §11—12 验收。现有37项真实验收不因此勾选；原型离线DOM/文档检查不代表真实SMB/SFTP、默认配置、Windows BAT、前台拉起、原生弹窗或成品通过。远程来源/输出路径例外、只读预览权限及故障矩阵须按设计分期验收，不沿用旧本地能力结论。

<a id="ws-real-acceptance"></a>

## 多公司工作区（WS 线）待真实验收（2026-11-13 登记）

WS-01—07 到目前为止只用合成资料验证（pytest、Vitest、专用 Chrome 1280 / 390，临时根目录与合成公司），逐项范围见 CHANGELOG 2026-11-10 起各 WS 小节的“未覆盖”。以下按测试轮次排列，逐步实测；测完把 `[ ]` 改为 `[x]`，并在 CHANGELOG 记录日期、样本范围（脱敏描述）与结论。真实资料只在公司资料夹内操作，结果与截图不进入仓库；写入类操作先用资料夹副本，每次真实写入、导出或账套操作仍需用户当回合明确授权。

2026-11-13 核对补齐：原 32 项增加非活动目录保护、跨页筛选勾选、冲突 / 损坏保护、界面缓存与外观、默认配置与入口五项，共 37 项，均未勾选。分轮计数为 12 / 18 / 7；历史章节的已勾选项不转算为当前 WS 验收。仍待开发的能力见 [WS 当前汇总](../IMPLEMENTATION_STATUS.md)，本清单只验收已经实现的范围。

2026-11-14 开发推进：WS-01 的 Vue 明暗 / 皮肤衔接已实现，共用皮肤首屏、加载后保存切换与恢复参数传播已纳入自动化；合成浏览器检查单独记录于 CHANGELOG。以下真实资料 / 平台清单仍为 37 待验、0 已验。

2026-11-14 第五阶段补齐六模块独立缓存与 Vue 临时识别，已有工作区 / Tauri 验收项包含模块缓存、局部刷新、临时来源失效、复制与原生多选 / OS 拖入；本轮只登记合成与源码证据，不勾选真实 / 平台项。

### 第一轮：真实公司资料夹，业务资料只读

2026-11-14 后续：WS-02 增补目录身份与损坏状态保护；工作区的 Ink Pulse / Animal Island 按用户确认暂停应用，单独经典页面保留，浅色 / 深色 / no_skin 继续验收。本任务仅做合成与源码检查，37 项仍待真实验收，不能把暂停的皮肤标记为视觉已通过。

公司登记会写本机公司清单；本轮“只读”指不改公司资料夹、源文件和投影，不执行补建或切换监控。

- [ ] 登记一家真实公司：六类子目录自动识别、纳税人身份生效期；子目录补建只看预览、不执行。
- [ ] 非活动目录保护：读取上次投影并提示缺失 / 过期，查看目录、账簿和比较前后源文件与投影不变，不创建该目录的 TargetProfile、不启动额外监控；无公司 / 缺子目录 / 金额未识别时照实提示。
- [ ] 发票账簿：进项 / 销项按月合计与经典首页、成本页一致；同票多格式只计一次；守恒校验成立；金额问题单列。
- [ ] 银行流水：真实中国银行对账单的期初、收支、期末与对账单逐月一致；缺月显示“缺 X 月对账单”、余额为“—”。
- [ ] 抵扣核对：真实“用途确认信息”导出的已勾选、当期 / 前期开票、清单有目录无、目录有清单无与税额差异。
- [ ] 进销存：真实序时账读回期初与账套库存商品明细一致；卖超、进项中没有的品类照实列出。
- [ ] 往来核对：真实流水的户名归属与逐笔对应，未对应流水不分摊。
- [ ] 项目汇总：真实 PDF / OFD 备注的项目名识别，合计与发票账簿一致。
- [ ] 同号检查：真实的成本发票 ⇄ 费用报销、两家关联公司的开具 ⇄ 成本发票；核对疑似重复是否属实、双方同一张票是否判断正确、大目录响应时间。
- [ ] 目录勾选与比较记录的原票：真实 PDF 与 OFD 票面在面板内的缩略图与大图；同票多格式与超过 100 个源文件的翻组 / 序号跳转不漏文件；面板打开超过 15 分钟后的续租与过期重建；切换监控目录后旧面板的提示。
- [ ] 目录筛选、排序与跨页勾选：日期正倒序在全量结果上生效，标签筛选与全选范围一致，跨页张数 / 三项合计 / 同票去重与经典首页一致；临时结果和非监控目录无勾选操作，切换监控后旧选择与迟到响应失效。
- [ ] 比较明细抽屉与原始记录并排：在真实数据上点类目，只留相关记录，计算过程与结果数一致。

### 第二轮：写入类操作（先用资料夹副本）

- [ ] 设为监控目录：切换后旧目录停止监控、SSE 与经典首页同步；切回原目录后投影不变。
- [ ] 子目录补建：按预览确认执行，只新建空目录；同名替换必须使计划失效，根内链接 / junction 与父路径同名文件不能穿透，嵌套映射共用上级目录仍可补建。
- [ ] 从零新建工作区：已有父目录内创建新公司根与六类空子目录，核对计划、取消、重复确认与失联后只读查询；同名文件、父路径变化与部分失败的保留结果（先用合成目录 / 副本）。
- [ ] 子目录映射编辑：只改变资料类型指向，原文件与 watch_dir 不变；已打开目录 / 账簿 / 比较 / 项目树更新，项目人工草稿与工资手工草稿不被清空。
- [ ] 发票标签：单张与多行批量打标签；重新汇总、切换目录后标记仍在；删除标签同时清除标记；源发票、CSV 与金额不变。
- [ ] 项目人工归属：保存后重新汇总仍保留；版本冲突提示。
- [ ] 写入冲突与损坏保护（只用副本 / 合成文件）：公司清单、标签、项目归属、凭证审核表、记入期调整和申报数据的旧 revision 保存被拒绝，不自动重放；损坏原文件保留，不能按空数据覆盖；草稿未保存改动的保留 / 显式放弃提示正确。
- [ ] 勾选删除：真实点击“确认移入废纸篓”（副本文件），系统废纸篓可恢复，逐文件结果与日志一致。
- [ ] 打印：打印窗口弹出、系统打印预览分页正确（多页 PDF 每页独占一张）。
- [ ] 批量入库单：跳转单据页后导出，Excel / WPS 打开核对。
- [ ] 凭证草稿：命令行生成的真实审核表在页面修改、审核并保存 → Excel / WPS 打开核对超链接、格式与其他工作表 → 页面“导出已审核…”与 `voucher_cli export` 各导出一次，导入文件逐单元格一致（含真实 `模板原件.xlsx` 列顺序）→ 在测试或正式账套只导入一张核对（账套操作需当回合授权）。
- [ ] 页面生成草稿：真实公司资料夹用页面与命令行各生成一次同期草稿，逐表核对一致；审核部分凭证后重新生成，核对备份文件、沿用与需重审清单是否符合实际改动。
- [ ] 改记入期：真实资料把一张跨月到票的进项改记到下月，核对增值税（进项 / 待认证）、库存加权成本与月度核对随之变化且与人工计算一致；已入账读回月份的票改记入期后的结果。
- [ ] 属期文件夹核对与移动（先在资料夹副本上）：真实进项抵扣 `5月/6月/10月份属期抵扣项` 与银行对账单的核对结果是否正确，确认后移动、文件内容不变、抵扣核对与银行账簿结果不受影响；网络盘 / Windows 上的改名。
- [ ] 凭证草稿改所属期：真实审核表把凭证移到另一个月后，`voucher_cli export` 的该月编号、`--after` 接号与整月拦截是否符合预期；Excel / WPS 打开核对月份、凭证号与日期列。
- [ ] 工资社保：从电子税务局导出真实的社保费应缴明细（Excel 与 PDF 各一份）放进工资社保目录，核对版式识别、五险金额与截图一致；确认后重新生成草稿，8、9 月社保计提与账套一致；人员信息默认脱敏。
- [ ] 其他记账软件导出：从目标软件下载空白导入模板放进 `做账草稿/导出模板/`，核对对列结果；在柠檬云 / 用友等真实账套（测试账套）只导入一张，核对凭证字号、科目、借贷、辅助核算后再把配置标为已验证。
- [ ] 凭证草稿与导出 `--ledger` 读回快照的校验差异：账套新建科目后，页面（只读 `凭证/科目表.json`）与导出结论是否一致。

### 第三轮：平台、入口与产物

- [ ] 工作区界面与缓存：置顶 / 展开 / 侧栏宽度持久化，拖动限位与键盘可用；切换首页标签与六个模块分别保留对象 / 草稿 / 筛选 / 勾选 / 滚动，双击 `hi.` 仅刷新当前标签或模块；临时识别的排序 / 历史 / 复制 / 原票预览与来源失效保护保持原行为；1280 / 390 布局与控制台正常。当前工作区保留默认 / 深色 / no_skin，Ink Pulse / Animal Island 按用户确认隔离，须核对工作区不应用、单独经典页面沿用保存偏好；草稿与勾选保留、切换失败恢复、原票面原色及 `?no_skin=1` 不写设置 / 导航保留继续验收；合成检查不代替本项平台实测。
- [ ] Tauri 桌面窗口内的 `/workspace`（WebView 布局、右键菜单、拖动调宽、打印窗口、临时页原生多选 / OS 拖入与其它模块拒绝）。
- [ ] 真实默认配置与入口一致性：源码正式入口及待验收成品解析到预期的 watch_dir / workspace / runtime，健康信息与实际资源一致；浏览器模式确实前台拉起且可进入 `/workspace`，desktop 模式打开预期窗口，跨入口不误用旧端口或另一份资源。
- [ ] macOS 已安装应用替换为新构建后的 `/workspace` 资源版本（`?v=` 内容哈希）。
- [ ] Windows：正式 BAT 启动、盘符与大小写不敏感路径、网络盘上的公司资料夹、原生回收站。
- [ ] 公司原生目录选择器已接入，仍须在 Windows / macOS 的 desktop 与 browser 下实测选择、取消、失败 / 超时、重复点击、迟到返回与待登记隔离（合成 mock 不替代系统弹窗）。
- [ ] 打包产物包含当前 `web/static/app/` 构建并通过 CI 逐字节重建比对（需推送后由 CI 执行）。

## 2026-10-09 双平台集成验收

- [x] Windows原生回收结果确认、Tauri带参数首页拖入及新增API握手门禁。
- [x] 图标跨平台字形布局固定、editable安装元数据与核心构建身份分离。
- [x] Mac首轮候选release编译、ad-hoc签名和DMG/receipt核对；最终源码与包身份由随包receipt绑定。
- [ ] 原生启动：现有8766服务占用，隔离启动门禁在拉起前停止；系统选择器、前台及默认业务配置未覆盖。
- [ ] Windows实机回收站、正式BAT/原生选择器与用户自行构建的成品验收；共享源码检查不替代。

## 2026-10-09 勾选操作增强

开发分支 `codex/selection-workflow` 基于 本轮开工时核验的稳定 `main`（起点提交记录在 CHANGELOG 与私有检查点），保留此前未提交工作。本轮实现确认移入原生废纸篓、按项目搜索/税率筛选、汇总来源链接与详情返回恢复、超过100份选择的逐文件预览与序号跳转。删除使用当前目标/源签名及monitor互斥锁，日志仅作操作状态，不是发票主存储；自动删除同步不改变原票。

相关实现/接口/算法/最低验收见[勾选工作流任务导航](architecture/AGENT_TASK_MAP.md#task-selection-workflow)。原有临时识别及渐进读取继续保留；后续双平台集成已修正图标像素及egg-info身份差异，提交、构建与最终验收范围统一见本页双平台集成记录及CHANGELOG。正式Windows BAT、默认业务配置、前台拉起和系统选择器仍需独立验收。


## 2026-10-09 临时原文件预览

队列与历史识别结果新增“预览”：PDF/OFD按需票面、XML安全原文，支持翻页/放大/返回、源失效清空与缓存恢复。独立于活动目录和正式投影；源码与合成测试范围见 CHANGELOG，原生选择器、真实默认配置和新成品未验收。

## 2026-10-09 临时识别

- [x] 独立临时批次、源关联历史、排序与设置；不改变旧普通汇总/成本或监控语义。
- [x] 原路径失效后禁止读取缓存；历史删除只影响缓存，原票不删除。
- [x] Tauri 固定多选 RPC 和首页拖放桥源码；普通浏览器源路径确认回退。
- [ ] Windows/macOS 成品原生选择与 OS 拖放、真实默认业务配置及正式 BAT 验收；本轮合成回归不代替真实用户验收。


## 2026-10-09 大目录渐进读取

- [x] 首页服务端分页，完整筛选统计和全选范围不缩小；成本四标签独立分页，跨页草稿和完整 TSV 复制保留。
- [x] 无完整结果时分批显示只读明细；后台更新有旧结果时继续读上次完整代际，避免等待同步锁。临时数据不能用于正式导出或开票状态保存。
- [x] 入库候选提前就绪、首页所选发票优先准备，出库候选增量发布；导出状态复用签名有效的文件名元数据。
- [x] 隔离合成数据的自动化与浏览器验证；具体命令、范围与计量见本轮 CHANGELOG。
- [ ] 真实默认业务配置、正式 Windows BAT、宿主前台拉起、系统原生选择器和新打包产物验收；本轮不扩大发布覆盖声明。

## 开发任务接力（2026-09-12）

- [x] [通用协议与小工具](AGENT_HANDOFF.md)：仓库外私有状态、线程别名/交接码定位、revision 防覆盖、未知结果复核与紧凑 Markdown/JSON 接手；v2 增量日志兼容旧记录，按需读取且无后台轮询。
- [x] 明确公开输入和固定运行时的便携打包及合成回归。
- [ ] Windows 原生解压/命令执行验收；本机静态验证不能替代。
- [x] Claude Code 从通用检查点实际接手补充并交回；Mac 最终便携包在新解压目录、内嵌 Python 下通过普通文件/通用 actor/漂移及未知操作验收。结果不推导为所有 Agent 或网络盘自动互通。

## Agent 阅读与定位入口（2026-09-11）

- [x] 全局必读规则与功能细则分层，按问题索引覆盖提取、成本、监控、页面/单据、做账、税务、Windows、macOS、Tauri 与发行；规则迁移不降低既有验收门槛。
- [x] [任务索引](architecture/AGENT_TASK_MAP.md#quick-lookup)、文件地图与 CLAUDE 入口指向同一套规则。此项只表示文档导航，跨 Agent 检查点与自动接力仍未实施。

## 税务计算器与资料读取（设计阶段）

- [x] [交互与架构规格](TAX_WORKBENCH_DESIGN.md)、[公式/政策核对](TAX_ALGORITHMS_AND_POLICY.md)及[合成原型](design/tax-calculator-prototype.html)。仅设计完成，不代表旧 MVP 已迁入 main。
- [ ] D0—D1：审查并迁入可复用计算器，修正旧税务规则，接入后端解释与首页交互；包含 20px 小入口、悬浮/首页置顶栏偏好、位置持久化/失败恢复与拖动边界验收。
- [ ] D1 补充：紧凑 20 键无需下划、长解释与结果独立滚动、同一行自定义税率、后端百分数归一化及假设标记/输入边界；原型静态设计不替代真实视口验收。
- [ ] D2—D4：独立公司绑定、原生单目录选择与待保存流程、证据适配、逐月/季度计算、缺项阻断和有界自动归集；覆盖双平台 desktop/browser 的选择成功/取消/失败/超时与迟到返回。
- [ ] D3 补充：申报表映射（绑定表式版本，改版后 stale）、征期与申报期限（记录来源与核对日期）、留存备查清单、税会差异调整项台账，以及跨期例与政策变更例两类独立预期。
- [ ] 投入决策：按[价值评估与就绪度](TAX_WORKBENCH_VALUE_AND_READINESS.md)先写假设、会改变决策的结果、最小样本与停止条件；未确认固定复核人力前不扩张政策中心覆盖范围。
- [ ] D0 前置：定位旧 MVP 草稿并只读核对可复用范围；当前工作树、stash 与 Git 历史均无其源码，不可得时按规格重新实现并用独立预期验收。
- [ ] D5：规则包治理、官方政策中心与影响提示；按[政策来源与核验](TAX_POLICY_SOURCES_AND_REVIEW.md)的 A/B/C/D 分级，只有官方原文可进规则包，其余只产生提示或线索。各税种申报舍入、实际公司资格、地方口径及真实账簿/申报对照仍需独立核验。

2026-09-10：alpha.2 优化版 1 已完成同源 Mac 构建并发布，内置平台 Python/Java/OFD 组件；离线、包内两页 OFD 和实际正常配置的 ready/页面/monitor 验收通过。隔离 HOME 自动样本未通过，其他平台原生与签名限制仍保留。精确身份、发布状态与来源见[分支记录](BRANCH_STATUS.md)；后续开发以 main 为准，制品身份由优化批次 Tag 固定。

2026-09-09 Windows alpha.2 加固候选继承 main PR #24 的响应分帧和浏览器兜底，补充 PYTHONHOME 隔离、spawn 系统错误诊断及真实 Winsock 回归。公测原机与 macOS 新包仍需独立验证；本轮 Windows 成品范围见 CHANGELOG。

2026-09-08：[`v0.3.0-alpha.2` 双平台预览](https://github.com/lyc1126/InvoiceHub/releases/tag/v0.3.0-alpha.2) 已按所有者确认的验收范围发布。Windows x64 portable ZIP 与 macOS arm64 preview DMG 同源，包含校验和、收据和平台 Python SBOM；Mac 离线核验与实际默认配置验收通过，隔离 HOME 自动烟测仍未通过，未启用安装 updater 或更新 Feed。精确发布身份和限制见[分支与发布记录](BRANCH_STATUS.md)。



2026-09-07 Desktop 整合补齐前端工作区未包含的既有桌面功能：四款内置图标选择（白底 hi. 默认）、打印弹窗许可、固定 WebView 数据目录、picker 调度、串行 monitor 状态与同步进度、Windows 启动恢复。最新官网/批量单据/全局外观和关闭控制器继续保留；旧候选及中间试包撤下，成品验证范围以当日 Changelog 为准。

更新时间：2026-09-08

## OFD 原票预览

- [x] 真实浏览器内的 InvoiceHub 单票勾选、预览弹窗、API 与新组件交接；源码 development health/background ready，使用临时副本及独立运行态。

- [x] 一份真实单页 OFD 的直接渲染与系统 Preview 展示，用户已确认该样本可见效果；原文件只读，真实票面不进入公开工作树。

- [x] 源码分支独立 OFDRW 图片渲染、真实页面树、中文/金额/矢量/图片、多页横纵方向、缺组件逐文件诊断与 PNG 内存交接；构建输入和 Java 21 锁定，详见 [OFD 预览说明](OFD_PREVIEW.md)。
- [ ] 更多问题 OFD、完整签章版式及更多嵌入字体样式的视觉核对；合成红色印记不冒充真实数字签章验证。
- [ ] Windows 真机、正式 BAT、Mac/Windows 成品与分发许可检查；alpha.2 已发布包不含本功能。

## 大目录单据与列表性能

- [x] 监控状态读取不再等待整轮汇总长锁；独立短状态锁保持 Windows 读写互斥，回归覆盖长汇总中停止请求和超时路径可达。
- [x] 单据缓存发布对 Windows 短暂共享/访问拒绝有界重试，最终 ready 仍晚于目录快照，持续错误不隐藏；仅源码及回归补齐，不宣称旧 ZIP 包含该修复。
- [x] 保存目录不在事件循环全量解析，独立进程可停止/恢复，runtime 缓存按目标及目录隔离，瞬时读失败保留进度。
- [x] 出库预览仅核对所选来源，缓存不替代当前身份；首页/单据分页，完整结果搜索与全选保留。
- [x] 7,003 条合成浏览器交互及后台加载中导航、停止/继续；文件变化/删除、跨目录与旧任务回归。成品及未覆盖项见变更日志。

## 首页搜索可解释性

- [x] 用户选择默认销售方/发票号码搜索，文件名单独选择；保留显式全部范围和旧 API 缺省兼容。文件名参与搜索时显示文件名，空结果不再提示重新汇总。
- [x] 大量合成记录的范围、组合筛选、统计、字段边界及迟到响应回归；首页新脚本版本由静态契约锁定。真实浏览器和新包结果以本次变更日志为准。

## 启动环境冲突可诊断性

- [x] 2026-09-09 源码修复增加 Content-Length/无正文/chunked 完成判定、截断与大小上限、分阶段诊断、清理前 child 状态；浏览器兜底仅作用于成功握手后的桌面窗口创建失败。
- [ ] 含上述修复的 Windows 新 ZIP、真实默认配置、正式 BAT、原生兜底确认、系统浏览器前台拉起及外部公测回访；原机不可访问，不将合成复现视为原机根因证明。

- [x] BAT 默认失败弹窗、独立只读检查与 `-NoDialog`；真实监听 PID、程序权限不足提示和服务自报环境。
- [x] Desktop 原生失败提示、托盘诊断、按程序/运行目录区分单实例；不同环境冲突不授予 ownership、不自动杀进程或换端口。
- [x] Python CLI 在 AppState 初始化前拒绝已占用端口，避免失败启动提前安排业务同步。
- [x] 最终 Windows portable 实测原生诊断窗口与失败退出 1、同实例复用/异环境拒绝、desktop/browser 切换及监控保留/停止；146 份包内源码/资源与最新快照一致。真实用户配置已恢复到新 EXE。
- [ ] 本机 computer-use 截图兼容性：Windows 10 19045 返回 `SetIsBorderRequired` / `0x80004002`，窗口枚举与激活可用，截图不可用；不将缺失的视觉证据计为通过。

## 源码 BAT 握手跟进

- [x] Windows venv 转发器保留原命令行时的身份误判已修复；PS7/PS5.1 根 BAT、重复启动、普通停止保留监控与 stop-all 在隔离配置通过。
- [x] 当前真实默认 8766 的源码根 BAT 在完整退出 Desktop 后成功启动、重复复用同一 backend PID 并正式停止；占用时拒绝接管也已覆盖。前文历史 BAT 未通过记录由本节补齐，不等同于原生选择器验收。

## 最新工作区 Desktop 与皮肤

- [x] 保留 owned backend 结束联动 host 退出，修正 Windows 启动方式文案；一个 Desktop 包可选择浏览器或桌面，下次完整启动生效。
- [x] Ink Pulse `1.4.0` 与 Animal Island `2.1.0` 适配新顶栏工具、批量单据和全局关闭弹窗；Ink Pulse 保留深色单据预览。
- [x] 复用 Windows portable builder/verifier，将官网精确白名单接入组包与验包；旧基线候选撤下，禁止作为当前工作区产物交付。
- [ ] 签名 NSIS、macOS 新成品、真实 updater 与纸张实打；本轮 Mac 候选仍待 smoke/runtime，Windows 同源 portable 候选虽已由用户交付且本机仅做静态验包，仍不替代签名、安装、真实 updater 与双平台成品验收。

## 默认前端与关闭入口

- [x] 官网浅色/深色切换、太阳/月亮动效、首屏持久状态、设置标记与恢复入口；失败保持当前界面且可重试。
- [x] 白底 desktop 图标 04 与 Tauri 默认 PNG/ICO/ICNS 绑定，确定性生成及小尺寸图像检查。
- [ ] 含新图标的 Windows/macOS 原生桌面构建、任务栏/Dock/托盘实机显示；当前 main 已有 Mac arm64 ad-hoc 候选但尚未完成 smoke/runtime，Windows 同源 portable 候选已由用户交付且本机仅做静态验包，现有安装包不因源文件更新而改变。

- [x] `hi.` 粗体官网标记、首页勾选到单据批量入库交接、目标/源文件重验、已有文件保护及逐票结果。
- [x] 双单据预览/导出列宽、合并、最低行数、超行数打印范围与无“人民币”前缀大写金额；明细副本与冲突守护。
- [ ] Excel/WPS 原生打开与纸张实打的字体/分页验收；程序化 XLSX 渲染不替代原生客户端结果。

- [x] 官网品牌语言进入默认前端，保留页面结构、皮肤与 `?no_skin=1`。
- [x] 页面切换取消人为等待，慢请求/真实操作转圈，顶栏与列表操作固定，窄屏功能栏可横向滚动。
- [x] 全局电源复用设置关闭协议；确认、取消、记住选择、失败重试、外部服务禁用和 SSE 有序结束有静态/API/交互守护。
- [x] 源码浏览器验收覆盖当前默认配置、120 张合成发票、慢请求、内置皮肤和恢复入口。
- [ ] 正式 Windows BAT 开发身份握手、系统原生选择器、桌面壳与包含本次样式的新安装包验收；源码 UI 通过不替代这些结论。

## 独立产品官网

- [x] 新增 `website/` 静态产品官网和合成数据交互演示；不改变旧能力迁移、业务 API 或公开应用发行资格。
- [x] 本地字体、图标与许可、静态资源和演示数据的 Node 契约。
- [x] 软件「官方网站」链接到随包 `/website/`，同窗口返回工作台；资源白名单同步后端、构建身份、源码快照与双平台组包器，公开更新 Feed 保持原地址。
- [ ] 含官网入口的新安装包与 Windows/macOS 桌面壳交互验收：本轮已产生 Mac 候选但尚未完成壳交互 smoke，Windows 同源候选由用户交付、本机仅做静态验包；不能把候选构建替代双平台成品验收。
- [x] 官网内容补充：预览/打印/项目明细、自适应单据、OCR/做账状态与概念税率换算；五层票据展开和功能动效，仅使用合成数据。13 项 Node 检查通过。
- [ ] 浏览器实际 DOM 交互、桌面/手机截图和画布像素验收：本轮浏览器访问未获许可，未执行。
- [ ] 官网部署：本轮未请求上线，不修改 GitHub Pages、Release 或 `updates/` Feed。

## 公开历史净化

- [x] 仓库所有者已授权替换公开历史、删除旧远端分支和 Tag，并保留 owner-only 私有备份。
- [x] 选择单一脱敏根提交，而非逐提交文本替换，避免保留可关联的验证叙述和身份元数据。
- [x] 规定移除真实本机路径、私有主体/项目/人员标识、真实业务验证材料、容器元数据、历史 Git 身份与真实凭据。
- [x] 将所有测试夹具确认或替换为明确的合成数据。
- [x] 对候选源树完成一次文本、二进制容器和工作簿属性审计。
- [x] 创建中性身份的根提交，并对所有保留对象完成一次 gitleaks 与业务数据分类审计。
- [x] 用托管 API 核对 heads、tags、PR refs、Release/asset、LFS 与可见 fork/cache 状态；新公开仓库只包含脱敏根及其后代，原始图保留在 private archive。
- [x] 提供旧工作区功能与故障的脱敏回溯索引；索引只记录公开可验证的类别和当前查询入口，原始 Changelog 继续留在私有归档外部，不复制进公开工作树或发布输入。

执行约束见 [历史净化执行记录](release/HISTORY_SANITIZATION_EXECUTION.md)。旧私有包和旧 Tag 绝不进入新的公开图或 Release。

## 已保留的共享核心

- [x] `v1 localhost`、单活动 `TargetProfile`、文件真值与 SQLite 运行态边界。
- [x] PDF/OFD/XML 提取、金额防污染、两维分类、同票纠偏、普通汇总与成本投影。
- [x] 独立 monitor、后台 startup sync、事件合并、周期兜底、手改保护与诊断日志。
- [x] 目录草稿、SSE 断线恢复、真实表格/TSV、预览、批量打印、皮肤安全边界和结构化关闭。
- [x] 做账 W8/W9 的严格本地状态、预览/apply、服务端执行校验、批次 manifest 和 dry-run 边界。
- [x] 银行流水底稿（2026-10-02，新能力，非旧功能迁移）：中国银行对账单/回单解析、余额勾稽、回单匹配、建议分录与脱敏底稿，命令行入口。
- [x] 参考凭证草稿与捷锐导入文件（2026-10-10，命令行）：审核表、按月导出、整月拦截、重复导出保护与做账习惯学习。
- [ ] 开票参考优化 COST-01—05 已登记到[产品待办清单](PRODUCT_BACKLOG.md)，待排期。
- [x] 凭证与对账单比对（2026-10-20，命令行）：银行对账、月度核对、已入账月份读回补记、原件速查与默认短摘要。
- [ ] 银行流水底稿与凭证草稿接入页面/API、其他银行或 Excel/CSV 适配器、销售成本结转与工资计提、捷锐导入格式实测，以及与 W9 凭证链（posting key、validator 与人审）合流。
- [x] 现有 macOS SwiftUI/WKWebView 壳仅作为共享后端与原生桥接的参考实现。

## `v0.3.0-alpha.1` Tauri 2 缺口

- [x] 建立 `src-tauri/` foundation、固定 `127.0.0.1:8766` 合同和由 `version.py` 派生的 Cargo/Tauri/npm 产品身份；host 已具备托盘、browser 启动路径、单实例恢复、close-to-hide 和 L6 host 委托 updater 边界。裸源码 checkout 继续在缺少编译绑定 manifest 时以状态 `78` 退出；development assembler 已生成并构建一个本地 arm64 `.app`，但不构成原生面板、打印、发布或平台验收声明。
- [x] 锁定 pnpm 与 Tauri JavaScript 依赖，并提供不会自动安装 Rust、证书、Xcode 或 Visual Studio 的 Windows/macOS `doctor/bootstrap`。
- [x] 在受控 Rust/Cargo `1.85.0` 环境中解析精确直接 Tauri crate、生成并审查 MSRV-compatible `src-tauri/Cargo.lock`，并通过最小 Rust compile/test；这只允许开始后续 host 生命周期实现，不等于已实现或发布。
- [x] 实现 `127.0.0.1:8766` 严格启动/握手：未知占用失败、child PID/build/package identity/OpenAPI 方法复核、HMAC challenge-response 归属证明，以及 manifest 原始字节 SHA-256 必须匹配编译期注入值的状态 `78` fail-closed。schema-3 development manifest 与显式 venv launcher 已被组装并编译绑定；一次隔离启动验证了 owned backend、health/background ready 与首页，退出机制由下方独立 P1-Q 样本限定，不扩大为 release bundle 或平台发布证据。
- [x] 保持 `startup_surface=desktop|browser` 语义：Tauri child 的缺省偏好为 desktop，既有有效显式偏好保持原值；严格 handshake 后 Rust 才选择 WebView 或固定 origin 的 host-only browser opener，托盘/第二实例重开同一 surface。L9 已验证 development `.app` 的 `desktop_available=true` 与默认 desktop；Windows 便携版仍拒绝新增 desktop 选择，真实 browser、tray、单实例和原生面板仍未验收。
- [x] 以不返回网页的随机 token 限制 Host RPC，picker 面只开放四种 picker 枚举与精确 localhost origin，更新面独立地只开放 `update_check/update_install`；host 只把 token/secret 传给其直接启动的 backend，backend 启动时捕获并从 descendant 环境清除，Python bearer 请求显式禁用环境代理，WebView capability 为空，token 不进入 Tauri command/event、API 响应或日志；授权先 arm 再由有界 liveness watcher 在 child exit 后撤销；尚未实测原生面板。
- [x] 保持 `POST /api/v1/update/check` 兼容：同一进程具备 Tauri host marker 和 private RPC 时，API、设置页和后台检查都进入 strict host preflight；只有非 Tauri/非 host 检查不获取 host lifecycle 锁并保留 cache/ETag/busy 语义。host approval 只以非阻塞方式获取该锁，竞争时返回不持久化 busy 结果且不触发 metadata/candidate 或清除既有 approval；install 锁竞争立即失败且不消费 approval 或发起第二次 private RPC。获得锁后，AppState 只在同一 session 内取得显式携带 `Cache-Control: no-cache`、不带 ETag 的 fresh allowlisted Feed `200` body、并与 host candidate version 完全一致时授予一次性内存 approval，缓存、ETag、`304`、离线或错误不可授权。host candidate 最多 300 秒，由 listener 主动清除；L10-D 后 `update_install` 可把 fresh candidate 交给响应后私有 commit，但 Web 仍不能提供版本/URL/签名/artifact ID，错误继续脱敏。隔离 Rust/FastAPI TestClient 合同覆盖此源码边界；真实下载、更新、bundle、签名、重启和平台烟测仍未执行。
- [x] hosted host-lock 竞争的 busy 返回不写 `updates.checked`：该路径不调用 `append_event`，因此不会把“立即/非持久化”响应重新变成 SQLite 写入等待；成功和非竞争检查的事件语义不变。
- [x] L8-S/L9：development profile 仅接受显式、已存在、绝对且 canonicalize 后与 bundle/core 及完整 macOS `.app` 容器双向不包含的 `INVOICE_HUB_DEV_STATE_ROOT`，`Contents` sibling 同样 fail-closed，release、缺失或相对覆盖 fail-closed，变量不传给 Python child；在隔离 state root 构建并启动一次 unsigned/ad-hoc macOS arm64 development `.app`。固定端口、health/background、首页/静态资源和 desktop 默认值通过；真实 Application Support 未被触碰。16-bit RGBA 图标导致的 tray 初始化失败已改为 8-bit RGBA，并有 IHDR 回归。
- [x] P1-Q：clean-commit 外部 AppleScript quit 绕过 shutdown POST 并留下 `server_state=ready`，因此该外部路径仍不作有序退出承诺。修复后的自定义 macOS 应用菜单 Quit/Cmd-Q 与 tray 共用 `app.exit(0)` 且禁止 predefined Quit；隔离的 clean-commit 真实 Cmd-Q 样本已确认 shutdown POST 200、stopped state、monitor 未启动、host/backend/PID/端口清理，SSE 未及时退出时由显式 `kill + wait` 兜底。该结果允许推送开发分支并创建 Draft PR，但不覆盖 tray 点击、Force Quit、SIGKILL 或平台发布。
- [x] P1 setup cleanup：BackendHost 启动后若 tray、desktop window 或 browser surface 初始化失败，host 在返回原始 setup error 前调用既有 keep-monitor shutdown，并在失败/超时时 kill+wait owned child；如果终止尚不可确认则 setup 保持阻塞并重试，child mutex 或 `try_wait` 错误也不算退出，绝不返回后依赖 Drop。只有成功初始化后才把 backend/surface 注册到 app state。该路径不依赖 `ExitRequested`，且不改变 updater fail-closed 语义。
- [x] L10-R source foundation：future coordinator 可使用 released owned lifecycle lease（generation/phase/health/owned/process PID/state scope）围住每次 marker/bridge 操作；暂停只接受 `running && ready` 的 owned monitor，已有/损坏/跨 scope marker、ownership loss 和任一 failure 都 fail closed。Unix marker store 用 opened-directory + `O_NOFOLLOW` 的 `openat`/atomic no-clobber `linkat`/`unlinkat` 固定最终操作；在该 L10-R 阶段其它非 Unix 平台返回 unavailable。下方 L10-C source-level slices 后续补充 Windows handle-relative/no-reparse marker store 与 Unix whole-operation protocol hardening。它未接入 Host RPC、真实 monitor、下载、安装或 restart，`update_install` 仍清除 candidate 后返回 unavailable。
- [x] L10-C foundation slices：新增 fixed-loopback `PythonMonitorRecoveryBridge`、只接收已验证 artifact 的 pure `UpdateCoordinator`、共享既有 child/ownership/lifecycle `Arc` 的 cloneable `BackendLifecycleAuthority`，并补充 Windows handle-relative marker 的 source/static contract。它们在 L10-C 阶段只形成可注入 source-level seams；当时的 56 项 Rust、42 项 Python 和最小 Windows 临时 crate 结果保留为历史证据，当前运行行为由 L10-D 接线取代。
- [x] L10-D authenticated runtime coordinator：Backend 私有 ownership secret 对每个固定 recovery 请求/精确响应使用 fresh challenge/HMAC-SHA256，Python 拒绝不完整、篡改、非空 body 和有界进程内 replay，普通 bridge 调用不变。Updater-disabled profile 不激活；enabled profile 只在 startup gate 释放和 `BackendHost` manage 后从 `runtime_dir` 打开 marker store并先恢复，失败保留 marker 和诊断 WebUI。完整 host-owned candidate 以域分隔 artifact identity 固定且不公开；`update_install` 先 reserve/spawn blocked worker，再 flush `{"ok":true}`，最后才执行 Tauri `download` 内置验签 -> pause -> `install` -> relaunch。writer/spawn/latch loss 进入 `CommitLost` 且无副作用；Windows `on_before_exit` 与 macOS `request_restart` 分别执行平台终止协议。该项只有源码/contract 证据，真实 Feed、monitor、合法/篡改下载、安装和重启仍在发布缺口中。
- [x] L10-E non-installing recovery smoke：普通 development/internal-alpha 继续 updater-disabled；显式 development smoke 只接受固定不可达 loopback endpoint、无验签能力 key sentinel 和精确三字段 updater 对象。隔离 runner 使用临时 HOME/state/watch、关闭自动更新检查、预置 scope marker，且 HTTP allowlist 只有 health/status/stop。锁定工具链离线构建后，macOS arm64 `.app` 已恢复 owned monitor 到 `running && ready`、删除 marker、显式停止 monitor，并清理本次 backend/monitor PID、进程组、固定端口和临时目录；runner 报告 `update_requests=0`。该项仍不覆盖 Feed、候选、下载、验签、安装或重启。

## 发布缺口

- [ ] 从包含 receipt finalization 门禁的最终干净 `v0.3.0-alpha.2` Tag 构建并挂载 macOS public-preview DMG，验证默认 finalized ad-hoc receipt、隔离 Application Support 状态、quarantine、LaunchServices 启动、monitor 与结构化退出；该包未公证。receipt gate 已合入 `main`，Tag 已按所有者确认绑定本轮同源制品；此项因隔离 HOME 自动烟测未通过仍不勾选，预览发布不改变这一结果。
- [ ] 在 GitHub-hosted Windows runner 执行 WebView2 hash gate、两层 SignPath、NSIS 安装/卸载与 receipt 烟测；本 alpha 接受卸载器未签名。

- [ ] Windows 10/11 x64 NSIS 安装器与新的公开构建/签名证据。
- [ ] macOS 13+ arm64 DMG、更新归档、Developer ID、Hardened Runtime、公证、staple、quarantine 与升级证据。
- [ ] 同仓库 GitHub Pages 更新 Feed、真实资产签名、源码归档、SBOM、收据与最终 provenance 闭环。
- [ ] 每个平台最终 RC 一次安装、启动、目录选择、托盘、合法/篡改更新与 monitor 停止烟测。

## 不在当前范围

- [ ] Windows ARM64、MSI、Intel/Universal macOS、App Store、云端、多用户、增量更新与正式本地 OCR 包。
- [ ] 真实业务做账迁移、审批、导出、账套或外部系统写入。它们需要独立事实、真实环境和当回合用户授权。
