# 迁移与公开缺口清单

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
