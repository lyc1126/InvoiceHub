# 变更日志

## 未发布

### 2026-09-08 发布 alpha.2 双平台预览并整理产品首页

- 所有者明确确认既有验收范围后，将注释 Tag `v0.3.0-alpha.2` 从 `eb425bc2690b374a61be67172e4acdbdc1e35c6e` 改指两端共同源码 `55a59870630198b7b8b055b85decfaa5bb360db6`；使用旧 Tag 对象身份的 force-with-lease，只更新该引用，不改写 main 或独立功能历史。
- GitHub Pre-release 已公开，Release ID `384542627`，8 项资源包括 Windows portable ZIP、Mac preview DMG、各自 SHA-256/receipt 及平台 Python SBOM；服务器报告的所有大小、SHA-256 与本地清单逐项一致。未重打程序、未开启安装 updater，也未发布 Feed；公开资源重新下载并逐项校验，8 项文件大小与 SHA-256 全部一致；网络中断后使用断点续传完成两个大文件复验。
- 发布说明保留 Windows 为用户验证后交付、本机静态验包的证据界限；Mac 25 项离线核验、实际默认空目录的启动/页面/monitor 验收，以及 62 项聚焦契约和 15 项文档契约均分别说明。隔离 HOME 自动烟测未通过、原生 picker/打印/完整浏览器与托盘交互/公证/updater 未覆盖，源归档器合成负向夹具误报仍存在；所有者确认只按这一预览范围发布，不将其改写成全量通过。
- 用户要求将 GitHub README 改为官网 hi. 风格的产品首页。新增居中标识/标题、真实版本和平台徽章、直接下载入口、简短场景介绍与官网已有 OCR/做账/税额换算后续方向；许可证保持 AGPL-3.0-or-later，不采用参考图中的 MIT、排名或下载量。使用指南移至 `docs/USER_GUIDE.md`，开发状态放入折叠区并保留架构导航。
- GitHub 实际 Markdown 渲染已检查，标题、徽章、截图和下载地址正常。首轮 Windows/macOS CI 仅因 README 工具链命令被缩写而失败，已在折叠开发区恢复两条完整入口，保留现有契约不放宽；产品代码不变。
- 三张截图来自当时运行的 alpha.2 默认空目录页面：汇总、成本分析、图标与皮肤。仅在独立截图浏览器内将本机路径替换为明确隐藏标记；未增加演示发票、修改金额、保存皮肤或改变当前 App 配置，原始 DOM 快照不进入仓库。截图来源、文件地图与发布真值在本轮同步。

### 2026-09-08 main 同步、Mac 候选与过期引用清理

- 本轮从 `codex/tauri2-alpha2-main-baseline@8d1c904` 收束到公开 `main`，本地 `main`、`origin/main` 和文档分支同步到 `55a59870630198b7b8b055b85decfaa5bb360db6`。税费计算器与 Mac 工作区的脏改动完整保存在 stash `df6451e0018c0de4db9734efecdae09da89a0eb0`，不作为公开源码、候选构建或 Release 输入；独立功能不因本轮同步改变。
- 已普通 `git branch -d` 删除六个只指向已合并历史的本地分支：`codex/tauri2-alpha2-main-baseline`、`codex/tauri2-alpha2-packaging`、`codex/tauri2-alpha2-postmerge-baseline`、`codex/tauri2-alpha2-public-preview-fix`、`codex/tauri2-alpha2-receipt-gate` 和 `codex/tauri2-unified-desktop`。唯一旧 Mac alpha baseline 的远端引用也已删除，并用 `git ls-remote --heads origin` 复核；`codex/desktop-latest`、`codex/desktop-main-docs`、图标/搜索/税费/更新恢复和 Dependabot 引用继续保留。旧的 dirty `codex/alpha2-dual-platform-release-prep` worktree 保留，本轮不执行 `git worktree prune`。
- 从精确 `main@55a59870630198b7b8b055b85decfaa5bb360db6` 构建 macOS arm64 alpha.2 preview：目录为 `dist/candidates/20260908-macos-main-55a5987/`，产物为 `InvoiceHub-v0.3.0-alpha.2-macos-arm64-preview.app`、`.dmg` 和 `build-receipt.json`；core build ID 为 `c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`，DMG 为 `109535179` bytes，SHA-256 为 `21715661a3bffa48e8afd0034a81eb975758280f3a6ed6d2356d982ec5607298`。该候选为 ad-hoc、未公证、host updater disabled，finalized receipt verifier 已通过。
- Mac 包内源码、官网、运行时、锁和签名的离线核验通过；隔离 HOME smoke 尚未通过；Mac smoke 未得到属于隔离 HOME 的 health；其后观察到构建身份正确且后台 ready 的实例，却使用真实 Application Support，不能计入隔离烟测通过，因此不能把候选描述为 public-preview 成品验收、签名/公证结果或 Release 资产。已收到与 Mac 同源的 Windows x64 portable 候选、SHA sidecar 和 build receipt：`source_commit=55a59870630198b7b8b055b85decfaa5bb360db6`、`core_build_id=c081eb0348cc3f1d8192b5e243b65877ca7650147dad86bd480468838716c2bf`、ZIP 大小 `58040173` bytes、SHA-256 `f7c03a502d06d19faa61ee5f9ed859c4da3f57c6789f52014dec3fd4005a6ff3`，unsigned portable 且 `updater_enabled=false`。Windows 完整包由用户说明已验证后交付；本机独立静态验包和收据/实际 ZIP SHA-256 核对通过，不能把本机检查描述为 Windows 真机运行验收。
- 远端 `v0.3.0-alpha.2` Tag 仍为 `eb425bc`，不能与本轮 `55a5987` Mac 候选或其它 source snapshot 配对；本轮没有修改 Tag、GitHub Release、资产或更新 Feed。源码快照导出曾因 `tests/test_tauri_windows_portable.py` 中既有的合成负向 secret 值命中扫描而失败，没有绕过或放宽该扫描。后续双平台候选仍需以同一 source/core 身份闭合 ZIP、SHA-256、receipt 和 SBOM；构建入口使用现有 `scripts/dev/tauri_windows_portable.py` 的精确参数 `--root`、`--python`、`--runtime-dir`（指向含 `python/python.exe` 的父目录）、`--pnpm`、`--output-dir` 和 `--source-commit`，不把脚本部署或环境自动准备描述为已完成，也不复用旧 release-prep 输入。
- Mac 离线深验 25 项通过，源码/web/website 与构建提交逐字节一致，运行时及 App/DMG/receipt 签名与哈希闭合；未生成新包。检查器初次中文 Git 路径解析、构建后文档状态和上游既有 bytecode 分类误报已纠正；本轮检查生成的缓存已通过从只读 DMG 恢复 App 消除，并重新校验原 receipt 的 App SHA 与签名。旁置运行时哈希表 2621 条验证通过，报告不包含本机绝对路径。
- 用户确认已允许并打开软件后，主代理核实先前只剩临时宿主、8766 无监听，按精确身份收束该宿主并从保留的候选 App 正常重启。新包在实际 Application Support 默认空目录达到 health/background ready，原生首页实际渲染；普通首页和 `?no_skin=1` 各 8 项静态资源与当前源码字节一致，首页脚本为 `20260907-large-list-1`。monitor 从原 false 启动到 running/ready，再停止并恢复 false，后端保持 ready，新 App 保留供用户使用。原生 picker 因控制工具返回 noWindowsAvailable 未完成，不冒充通过。该当前配置证据不能替代失败的隔离 HOME smoke，先前仅据 spctl 拒绝断言无法启动的归因撤回。
- 本轮聚焦测试通过 62 项，覆盖 Mac 发布/烟测契约、Tauri foundation、图标、release identity 和 build manifest；另有 15 项文档契约通过，版本派生与 diff 检查通过。没有重复全仓 CI、Windows BAT、原生选择器、实体打印或真实 updater。最小无业务 App 证实同样的 LaunchServices `--env HOME=...` 传参能正确隔离；正式候选的 quarantine/Gatekeeper 首次打开与隔离运行仍须闭合，不能删除 quarantine 来制造通过。

### 2026-09-08 Desktop 主线合并检查

- 结果：最终功能提交 `f9eebca` 的 Windows/macOS push 与 PR CI、DCO 全部通过，审查意见修复并解决后，以普通 merge 合入 PR #20，主线产品基线为 `53544e3c96ba01906520637fae60cbc215b7808b`。本地主线同步，随后用纯文档分支同步 README、实现状态、分支记录及全部架构附录的统一基线；保留完整提交历史，不创建 Release/Feed。
- 文档收尾 PR #21 将当前状态表改为 main/PR 身份与实时 Git 查询，精确当次合并 SHA 仅作本节历史记录，避免下次主线演进后把固定值误当当前 HEAD；产品代码不变。
- 本地聚焦检查分别为 40 项前端契约、59 项缓存/单据相关回归和 38 项监控/索引/文档回归，源码 compileall 通过。CI 覆盖完整双平台 Python 回归、Windows 发布契约/PowerShell 解析和 macOS Swift 测试；本轮没有新增 BAT、原生选择器、实体打印或平台成品验收。审计脚本、远端 CI 日志和合成测试文件保留在 ignored 的 `runtime/desktop-merge-check/` 供回溯，无需复现后可清理；业务数据与本机配置未提交。
- 用户授权将 `codex/desktop-latest` 合入 `main`，从已推送的 `482dff6` 开始复核。首次远端 CI 在 Windows/macOS 各有两项失败，均为预览/打印前端契约仍引用旧首页脚本版本；分别已有 661/652 项 Python 测试通过。
- 将两处测试版本预期同步为页面已使用的 `20260907-large-list-1`，保留现有产品源码、缓存参数及已验 Desktop 包；继续运行聚焦回归与远端 CI，合并结果以本节后续记录为准。
- PR #20 的首轮 CI/DCO 已通过，但同提交 push 场景出现索引 phase=complete 后状态写入失败。为单据缓存发布增加仅针对 Windows 5/32/33 的有界重试，最多 20 次、累计等待 0.95 秒；持续拒绝仍抛错。新增最终 ready 写入共享冲突和持续/非 Windows 错误的确定性测试。该源码修复尚未进入此前的本地 ZIP，不将旧包宣称为本次精确成品。
- PR 自动审查发现 `MonitorBridge.stop()` 的前置状态读取被完整汇总锁阻塞，停止请求和 20 秒超时可能数分钟后才开始。核对后将状态读写放入独立短锁，写入仍按 sync -> status 顺序串行；回归覆盖长汇总锁未释放时读取与停止/超时可达。该修复同样仅在源码，不重打旧包。

### 2026-09-08 Desktop 推送重试与分支整理完成

- 从 `codex/desktop-latest@f35d314` 继续用户已授权的推送；GitHub 成功接收完整整合提交，分支已跟踪同名远端，`git ls-remote` 核对一致。稳定 `main` 仍为 `eb425bc`，未创建 PR、Release 或 Feed，也未上传本机配置、业务数据与 ZIP。
- 远端接收后，重新核对七个冗余本地引用均只指向稳定基线、没有独立提交或工作树绑定，使用 `git branch -d` 删除；有独立历史的开发线和构建快照继续保留，完成状态见 `docs/BRANCH_STATUS.md`。
- 本轮只涉及 Git 操作及文档同步，复核远端 SHA、提交范围、工作区分类和文档 diff，不重复已通过的产品测试、BAT 或成品验收；`runtime/desktop-push-check/` 保留供源码整合审计回溯，无需复现时可按精确目录清理。

### 2026-09-07 最新 Desktop 源码整合与分支整理

- 用户授权整理分支，并提交、推送最新版 Desktop 的全部更新。实时 fetch 后稳定 `origin/main` 仍为 `eb425bc`；从该基线建立 `codex/desktop-latest`，保留当前所有已验源码、资源、测试与文档，恢复同基线的本地 main 跟踪分支。
- 本次以最新 Desktop 构建快照核对内容，不重写其它功能分支或构建快照的历史。七个仅指向稳定基线、无独立提交的本地分支在整合推送成功后删除；其余来源线/构建快照保留并由 `docs/BRANCH_STATUS.md` 说明用途。
- 提交使用精确文件清单，排除本机配置、业务源文件/投影、缓存/日志、用户压缩档与发行 ZIP；代码/资源沿用最近已验 Desktop，文档与分支状态另行同步。验证结果和最终远端提交身份以本次实际 Git 检查及任务结果为准；不合并 main、不发布 Release/Feed、不创建 PR。
- 提交前发现文件地图未逐项列出图标及深色皮肤资源，官网测试的旧脚本分界标记已删除，导致误执行诊断控制器；补齐路径并给测试添加有效分界断言，不改变产品代码。敏感内容扫描命中两项验包负向测试的固定合成字符串，人工确认后按精确值记录例外。
- 整合提交 `5331187` 已完成，15 项文档契约、31 项前端/官网交互、compileall 和 diff 检查通过；产品代码/资源仍与已验 Desktop 快照一致。三次 GitHub HTTPS 推送遇到连接超时或连接重置，尚未推送成功，七个冗余本地引用依约保留至远端核对成功。本机审计与测试目录 `runtime/desktop-push-check/` 保留供后续推送复核，完成后可清理；没有新增全仓、BAT、原生选择器、macOS 或成品验收。

### 2026-09-07 大列表响应与单据断点缓存

- 从公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 转入 `codex/fix-large-list-responsiveness`，保留全部前序修复，未推送/合并。用户要求解决大目录持续处理中及模块卡顿，并支持保留进度和终止加载。
- 定位到保存目录在事件循环全目录解析、出库预览重复扫描、首页及单据选项全量 DOM。改为轻量目录校验、spawn 子进程索引、快速状态与独立进度轮询；保存/打开/导出同步工作卸载到线程池。预览只重新解析所选来源，仍检查目录/号码身份。
- 每个 TargetProfile/开具目录在 runtime `local_state/documents/index/<scope>/` 保留逐文件缓存。按路径、大小、mtime/ctime 和版本复用，停止/重启后可继续。SQLite WAL/NORMAL 避免逐文件 FULL 同步慢，断电可能丢失少量近期进度；不写源发票或业务投影。暂停不被普通刷新重启，旧 job_id 不得停止新任务；Windows 进度替换瞬时读失败保留最后有效状态。
- 首页每页 100 条，入/出库候选每页 100 项并可搜索号码/销售方，全选仍针对完整筛选结果，批量上限保留。单据新增进度、失败数、停止及继续。脚本和新增样式版本 `20260907-large-list-1`。
- 最小实验为 7,003 条合成记录和 7,003 个合成 XML，用于决定是否保留分页及独立进程。真实 Chromium 搜索/重置/翻页、加载中导航、停止/继续通过；测得首页 276ms、单据 233ms、停止 58ms、切设置 106ms，暖缓存复用 7,003 文件。仅代表本机合成样本。初轮发现同步写盘慢和进度读问题，修正后复测通过。
- 聚焦单据/缓存/HTTP/Node/文档契约及最终 Desktop 产物见本节后续补充；不作为全仓、macOS、正式 BAT、原生选择器或实体打印的新验收。
- 最终验证：63 项单据/索引/前端静态/文档测试、7 项搜索与 health API 测试、16 项 Node 交互、compileall 与 diff 检查通过。两款皮肤/默认无皮肤及恢复入口在 1440/390 宽度通过；窄屏加载工具和分页单独修正尺寸约束。
- 最终包为 `dist/candidates/20260907-large-list-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，SHA256 `e62a437deeff4b79e9565a2ec8ab1dfa1e443fe8e1436d3b8692e9d9f50bab07`；源码快照 `8e723cfd8fd1124a67de6648308c9f5f5f399ae4`，core build `1177db99a7f6dfdd3aab7e7a79a7027b8aa32f2eda5efcdb87b265285c243acf`。独立 verifier、Python runtime smoke/pip check、148 份包内源码/资源比对通过。
- 真实默认配置已切换新 EXE，health/build 身份及资源版本匹配；当前无皮肤及 `no_skin=1` 的真实 DOM 生效。实际保存目录 6,688 文件完成，errors=0；加载中停止约 69ms、切设置约 101ms，恢复复用 2,261 文件，后续重新核对复用全部 6,688。就绪页面最多 100 个业务选项，处理中指示已消失；监控保持原 false。仅输出聚合计数，未保存业务响应/DOM/截图。
- 旧 search-scope ZIP/hash/receipt 已撤下，旧解包保留回退。合成测试服务及浏览器均关闭；`runtime/large-list-check/` 保留合成复现、验证脚本与截图，`runtime/desktop-integrated-source/` 保留可追溯构建快照及既有依赖连接，可在无需复现/重打后另行清理。工作区 modified 95、deleted 0、untracked 33、ignored 27，73 条既有不可访问/缺失缓存目录警告；本机配置未暂存或上传。

### 2026-09-07 首页搜索范围与文件名误命中

- 用户反馈搜索供应商混入空销售方记录；在公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 的工作区保留全部前序修改，转入 `codex/fix-invoice-search-scope`。只读统计当前 API 命中字段，不保存业务响应，不修改真实发票、配置或投影，不推送。
- 当前搜索同时匹配文件名，而表格隐藏文件名，导致用户无法解释命中；没有发现不满足旧规则的记录。用户确认默认搜索销售方/发票号码，文件名单独选。首页增加搜索范围，保留显式全部范围；文件名参与搜索时展示转义文件名，无匹配显示筛选专用空态。
- API 新增 `search_scope=invoice|filename|all`，缺省 all 兼容旧调用者，非法枚举返回 422。关键字逐字段、不区分大小写匹配，不跨字段拼接。首页默认与重置为 invoice，刷新沿用已提交范围，迟到响应保留 generation 保护。脚本版本为 `20260907-search-scope-1`。
- 验证计划与阶段结果：7,003 条合成 API 记录覆盖范围、旧调用兼容、组合筛选、空结果、非法范围、统计与字段边界；Node 的 7,000 条迟到响应检查通过。pytest 默认临时目录权限错误与新基目录缺父目录在独立测试目录准备后解决，没有改系统权限。浏览器和最终包只使用合成数据进行界面验收，实际配置仅只读核对命中统计；最终结果后补。
- 最终检查：2 项搜索 API、17 项前端静态、15 项架构文档检查及 15 项 Node 交互通过，compileall/diff whitespace 通过；没有完整 pytest 或新增 Rust 行为回归。浏览器 101 条合成记录完成默认范围、文件名 60 条、文件名可见、无结果、重置 101 条，以及 1440×1000/390×844、两款皮肤和 `no_skin=1`。首次 7,001 行全量 DOM 的 Playwright 操作/快照超时，未宣称大列表渲染性能通过；大量数据搜索正确性由 API 和迟到响应回归覆盖，不能把本轮范围修复表述为完整性能优化。
- 新成品：`dist/candidates/20260907-search-scope-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，快照 `29395af61632d13ca573f0565f4ab94a122df2a7`，58,032,891 字节，SHA256 `bfa4cca521687276c58635295227287cbe5575cdad28b4be3f593f922181fd79`。独立 verifier、runtime smoke、pip check 通过，146 份包内源码/前端资源与快照及当前工作区逐字节核对；保留既有皮肤、图标、启动与监控修复。release 编译保留 3 项既有 updater dead-code warning，仍为 unsigned/updater-disabled。
- 当前运行：接替前旧 Desktop 已自行退出，未停止外来进程；新 EXE 使用原用户配置启动，health/build/package manifest 均有效，后台 ready、monitor 保持关闭。实际页面在移除初次加载的限定查询路由后提交原关键词，当前 1 条结果均满足 invoice 范围，新 JS 版本、控件计算尺寸、默认无皮肤与恢复入口已复核；本次当前数据与最初截图时不同，不将记录数变化全部归因于搜索修复。没有将真实业务响应、DOM 或截图保存到仓库。
- 清理与边界：源码烟测 8881 与两个 Playwright 专用会话已关闭，新 Desktop 保留供使用；旧 startup-diagnostics ZIP/hash/receipt 已删除，旧解包目录保留短期回退。`runtime/search-scope-check/` 保留合成夹具、脚本、截图和诊断，`runtime/desktop-integrated-source/` 复用既有目录绑定 `codex/search-scope-snapshot` 供复现；确认新包稳定后可按精确目录清理验收材料，构建目录继续遵守既有 junction 边界。没有推送、修改用户配置或手工重写业务投影，未覆盖本轮 BAT 启停、原生目录选择器、macOS、签名安装器或 updater。

### 2026-09-07 旧 ZIP 与中间候选授权清理盘点

- 用户明确授权盘点和清理；继续在 `codex/startup-conflict-diagnostics@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 工作，保留既有 modified/untracked/ignored 内容，主工作区 index 不变。当前仓库没有本地 `main` 引用，未创建或更改引用。
- 可读产物区找到 17 个产品 ZIP，其中 1 个为当前最终包，16 个为旧包。清理白名单共 18 个精确文件/目录目标，包含旧 ZIP、对应收据/哈希、两份旧解包目录和三个空候选目录，共 7,485 个文件、1,197,160,480 字节。完整本机清单位于 `runtime/startup-diagnostics-check/old-candidate-inventory.md`，保留供执行清理与核对，完成清理后可连同既有验收记录处理。
- 删除前核验目标均在 `dist` 内、无 reparse point、无已观察到的运行程序、不含当前最终包；当前 Desktop/backend 均运行于 startup-diagnostics-desktop-final，health 正常，最终 ZIP SHA256 与上轮收据一致。构建源码、依赖、用户配置、业务数据和专用 evidence 目录保留。
- 结果：自动审批仍在创建命令进程前拒绝删除，只有 `blocked by policy`，无具体原因；实际删除 0 项，未修改权限或改工具绕过。构建源码区内 `.windows-portable-staging` 另有文件系统拒绝枚举，未纳入候选数量或清理范围。上轮旧包磁盘残留限制仍有效。
- 验证边界：本轮为只读盘点与文档记录，没有产品代码变更、重打包、启停或推送，因此不重复运行产品回归；复核文件存在性、新包哈希、实际运行身份及 Git 状态。
- 后续执行：用户再次要求清理后，明确文件路径的非递归删除成功，已清理全部 16 个旧 ZIP 和 30 个配套哈希/收据，共 46 个文件、897,616,059 字节。批量递归目录删除与后续空目录删除仍被自动审批以 `blocked by policy` 拒绝，故旧解包和空目录暂留；没有改权限或删除解包内部文件。已复核可读候选区仅剩 startup-diagnostics-desktop-final 的产品 ZIP，新包 SHA256 不变，原 backend PID 仍 health ok。清单已同步实际状态，源码、配置、业务数据、构建源码和 evidence 保留；本轮不运行产品回归、不重打包、不推送。

### 2026-09-07 启动冲突诊断与桌面进程可见性

- 需求与开工：开发、测试与 Desktop 启动冲突必须向用户展示原因和占用者，不能只把错误写入隐藏终端；正式 Desktop 应能在任务管理器按产品名称定位。由 `codex/fix-source-bat-handshake@eb425bc` 转入同一公开 main 基线的 `codex/startup-conflict-diagnostics`，保留全部既有代码、皮肤、图标、握手修复和本机运行态，不推送。
- 假设与最小验证：GUI subsystem 下的 stderr 和跨目录单实例唤回会造成静默失败或打开错误环境。先追踪两个入口的失败/重复启动分支，再用一个隔离监听器验证冲突提示、PID/路径、日志和未知占用保护；正常启动、相同实例唤回及 monitor 保留/停止为相邻验证。新包必须来自包含本轮修改的当前工作区快照，不能复用旧 EXE。以可见提示、可定位进程、受影响自动检查与 Windows 成品验证通过为停止条件。
- 成品发现与修正：首个本轮候选在端口冲突时仍退出 101；实际 stderr 表明 Tauri 将 setup 推迟至事件循环并对返回的 `Err` panic，外层 build 错误分支无法捕获。改为 setup 内清理后直接提示并请求有序失败退出，新增守护测试和仅供自动化的 `--no-startup-dialog`。该首次候选不交付，最终 ZIP 必须重新编译并复验实际失败退出码。
- 实现结果：BAT 失败释放启动锁后保存独立诊断并显示原生前台弹窗，根 `检查启动环境.bat` 支持坏配置和无 Python 的只读检查；PS7/PS5.1 共用真实监听 PID 查询。Desktop 使用 Windows 原生监听表、进程路径和父进程线索，新增托盘诊断、按 EXE/runtime 隔离单实例，并通过 `run_return` 保留失败退出码。直接 CLI 在 AppState 初始化前检查端口，诊断子进程沿用 Host RPC 环境清理；服务自报字段仅作诊断，不授予 ownership，不杀未知进程或自动换端口。
- 最终包：`dist/candidates/20260907-startup-diagnostics-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，来源快照 `96d149b373926be1b354ce0913a22c767de6d9e1`，大小 `58032592` 字节，SHA256 `26ae9d64b3f05cb1fb1f27ff9af9a0f790e27312959941b0a1b81ec4d4bdf3a3`。独立 verifier、locked runtime 导入与 pip check 通过；146 份包内源码/资源与快照及当前工作区逐一核对，其中前端 62 份、官网 10 份，另核对 host 修改与图标输入。图标选择、最新前端和两款皮肤继续保留。最终验收记录属于构建后的文档更新，不改变包内输入。
- 自动检查：启动/Windows/Tauri/API 的首组 49 项通过；最终 CLI 凭据清理等 2 项、Tauri 生命周期 17 项和文档 15 项定点通过。Rust 原整组 79 项通过，新增诊断检查后 4 项诊断测试通过，最终 release 编译成功；既有 3 项 updater dead-code warning 保留。没有把重跑累计为新增用例，没有执行完整 pytest。
- 真机入口：PS7/强制 PS5.1 根 BAT 在隔离配置完成启动、重复启动、普通停止保留相同 ready monitor PID、stop-all 停止两者。真实默认配置根 BAT 在释放 Desktop 端口后成功启动，重复启动复用相同 backend PID，health/config/state 一致，再通过正式停止入口退出；此前“默认 BAT 尚未成功”缺口已补齐。
- 精确成品验收：固定 8766 上与源码冲突返回 1，诊断指出原 PID/config 且原服务继续存活，无 panic；默认弹窗的真实窗口标题为“InvoiceHub 启动与运行诊断”。隔离用户目录完成 desktop→browser→desktop、两模式重复启动、另一环境明确拒绝、keep_monitor 保留同一 ready PID、stop_monitor 停止并重启确认。验收脚本先修正 bridge start/status 字段口径，并等待后端 health 之后的桌面窗口初始化，正常用户操作时序下完整流程通过。立即在窗口构造期间通过外部 API 关闭会中断 setup 并返回诊断，不记为正常完成启动。
- 当前运行与未覆盖：最终 EXE 已恢复真实用户目录配置，health 为 ok、background_status=ready，窗口与进程名均为 InvoiceHub，PE ProductName/FileDescription 均为 InvoiceHub，原启动偏好为 desktop、monitor 保持关闭。前端本轮未再修改，以资源字节核对衔接前轮当前皮肤与 `no_skin=1` 的 DOM 验收。本轮没有任务管理器 GUI/窗口像素截图，没有重做浏览器前台与原生选择器操作；前轮相同前端资源的操作证据保留。未覆盖 macOS 新成品、签名安装器、updater、实际纸张打印和真实业务目录压力测试。
- 清理限制与保留：最终只交付 startup-diagnostics-desktop-final 新包；删除失败首候选目录及上一轮 ZIP/hash/receipt 的精确命令被自动审批以 `blocked by policy` 拒绝，未执行、未绕过，旧文件仍在磁盘且不再作为当前候选。`runtime/startup-diagnostics-check/` 保留诊断与验收脚本/日志，`runtime/desktop-integrated-source/` 的最终 snapshot-release 分支保留构建复现。后续具备清理条件时删除确切的旧候选和验收目录；构建目录须先按既有 junction 边界移除链接。前轮被拒绝的清理不重试。本机配置和 ignored 运行态不入提交，主工作区 index 未动，没有推送。

### 2026-09-07 源码 BAT 虚拟环境握手修复

- 需求与开工：继续处理源码 BAT 开发启动的独立握手故障；从公开 `origin/main@eb425bc` 的 `codex/desktop-current-package` 转入 `codex/fix-source-bat-handshake`，保留全部已有 modified/untracked/ignored 内容及 index，不推送。
- 实验计划：假设 Windows venv 转发器的真实 executable 为基础 Python，而命令行首项仍为 venv Python，导致严格进程校验误拒绝。使用一个隔离空目录配置通过根 BAT 启动，对照 CIM executable、命令行和 health；若仅该差异成立则修正可信解释器集合的匹配，仍严格绑定模块/root/config，错误路径和未知 Python 必须拒绝。停止条件为 PS7/PS5.1 正式启停、重复启动和相邻身份负向回归通过；不重打未包含 BAT 的 Tauri ZIP。
- 结果：隔离配置的旧实现复现 20 秒握手失败；修复后根 BAT 约 5 秒返回 ready。实际 CIM 确认 executable 为 venv 声明的基础 Python，argv 首项为 venv Python。`Test-IHProcessIdentity` 分别核验这两项均属于当前启动上下文，再保留原有精确模块/root/config 检查，启动复用与 PID 停止共用该修复。release 单候选和完整 CIM 矛盾拒绝语义保留。
- 验证：23 项 Windows 契约及 15 项架构文档检查通过，compileall 与 diff whitespace 检查通过；新增 PS7/PS5.1 的 venv 转发、直接 Python、release 单候选和外来执行文件/命令/模块/root/config/额外参数负向回归。真实根 BAT 在隔离配置完成显式 Development、自动源码识别、PS7/强制 PS5.1 启动及重复启动；首页与 health 成功、PID/state 与实际进程一致。普通停止保留相同 running/ready monitor PID，stop-all 后复核两个进程退出、monitor ready=false、server state=stopped；日志无启动异常。
- 当前运行与未覆盖：先前手动启动的源码实例已通过 keep_monitor API 退出；随后默认 8766 被用户目录配置的 Desktop 实例占用，根 BAT 正确报身份不匹配，未接管或结束该实例。真实默认配置的源码 BAT 成功启动仍未覆盖；没有单独的根 `.lnk` 可测，根 BAT 已覆盖。未复验浏览器前台、原生选择器、成品离线 BAT 或 macOS；没有修改前端或 Tauri 包内输入，因此保留上一轮最终 ZIP、皮肤和图标修复，不重打。
- 清理与限制：后台组合诊断命令被自动审批拒绝，仅返回 `blocked by policy`，改用直接根 BAT 与独立只读检查完成验证。本轮 `runtime/source-bat-handshake-check/` 已确认无存活测试进程、无 reparse point，但精确目录清理同样被自动审批拒绝，未绕过；配置、空目录产物与 pytest 临时目录暂留本地作故障复核，后续获允许后删除该精确目录即可，前序保留目录不在清理范围。本机配置保持本地、index 未动，没有提交或推送。

### 2026-09-07 最新工作区桌面包与内置皮肤适配

- 需求与基线：复核上一线程的双启动检查，保留页面关闭后残留 host 的故障修复；用户明确要求撤下不含最新工作区更新的旧候选 ZIP，适配两款原有皮肤后重新打包。由 `codex/default-ui-polish@eb425bc` 保留全部已有工作区修改，转入基于同一公开 `origin/main` 的 `codex/desktop-current-package`。不推送、不部署、不切换公开 Feed。
- 决策与方案：desktop/browser 原本共用一套后端，不新增启动器。保留 watcher 原子撤销 ownership 后退出 host 的修复；host 主动退出先撤销 ownership，避免重入。当前工作区复用既有 portable builder/verifier，补官网精确白名单；只构建 ZIP，不移入旧候选的应用源码或 Feed/handoff 流程。Windows GUI host 隐藏 child 控制台并将日志写到 owned runtime。
- 皮肤：Ink Pulse 升至 `1.4.0`、Animal Island 升至 `2.1.0`；新顶栏图标工具不位移、批量单据沿用皮肤配色、全局关闭弹窗不局限设置页。按用户最新要求保留 Ink Pulse 深色单据预览，Excel 导出和真实票面不受皮肤影响；动态模板内容版本、清单与测试同步。
- 最小验证计划：先验证当前源码两款皮肤的首页/设置/成本/单据、桌面与手机布局、关闭弹窗和恢复入口；仅以当前工作区干净快照组包，最终 ZIP 逐文件核对官网/新图标/JS/皮肤及修复，复验 desktop→browser→desktop、单实例、关闭与监控。若输入字节不一致或修复失效则停止交付。结果与未覆盖项在本节收尾追加。
- 包内实测补充：旧候选曾使用相同的设置脚本版本 URL，浏览器复用旧脚本后与最新全局关闭脚本重复声明变量，导致设置页停在初始化。当前模板及静态/API 契约改为独立的 `20260907-current-desktop-1`，以刷新资源缓存；据此重新生成候选，不能交付首次试打包。
- 用户指出图标选择缺失后的范围纠正：当前前端工作区基于公开 main，但图标选择、打印弹窗偏好、监控状态串行读取、同步进度与 Windows 启动恢复位于 `codex/fix-desktop-search-filter` 的公开后代。此前只搬入 watcher 修复不足以保留既有功能，第二次试打包同样不交付。本轮以共同基线三方合入这些运行代码和守护测试，冲突处保留最新官网、批量单据、全局关闭控制器与外观切换，不回退当前页面。
- 图标恢复：设置外观与皮肤页提供四款内置图标，新增 `website` 为默认白底 hi.，原 `orange/teal/violet` 选择继续有效。Python 与 Rust 共用枚举边界；先请求 owned host 更新窗口/托盘，再保存运行态；浏览器 favicon 同步。第四款从现有母版生成，原三款使用已存在公开分支中的资源。最终公共资源统一为 `20260907-desktop-integrated-2`、图标为 `20260907-app-icon-v3`。
- 最终产物：`dist/candidates/20260907-current-workspace-desktop-final/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip`，来源为当前工作区完整快照 `6c4821dfc817a0888702b2c3eb9e23062f8b6cc5`，大小 `58013606` 字节，SHA256 `fbd260fd789532680b01cf6d8f94e5cf16437812045ed5aa0a56075e9ba88fe3`。旧 desktop-surface 包及两份中间试包的 ZIP/hash/receipt 已删除；最终收据和 SHA 文件与新包同目录。独立 verifier、locked runtime 导入与 pip check 通过，146 份包内源码/资源逐一与快照及当前工作区核对一致，其中官网 10 份；host 的源码与图标输入同样核对。只在本地保留 unsigned、updater-disabled ZIP，没有推送、签名或发布 Feed。
- 自动检查：整合后的 93 项图标/Host RPC/前端/单据/生命周期检查通过；203 项 API/监控/发布/启动相邻回归中 1 项平台跳过，3 项旧基线断言或缺少烟测脚本在修正后定点复验通过；15 项架构文档检查通过。Rust 77 项测试通过（43 单元、6 lifecycle、12 monitor recovery、12 updater coordinator、4 Windows marker），Node 14 项交互检查、compileall、cargo fmt 与 diff whitespace 检查通过。Rust 保留 3 项既有 updater dead-code warning；没有执行完整 pytest 全库回归。
- 最终 ZIP 真机范围：隔离 LocalAppData、固定 8766，完成 desktop→browser→desktop；默认浏览器实际拉起，第二实例退出且 backend PID 不变；页面 keep_monitor 关闭后 host/backend 退出而 monitor 仍 running/ready，关闭浏览器标签不停止两者，stop_monitor 关闭后复核全部退出，随后可再次启动。原生目录选择弹窗打开/取消通过。图标在桌面模式切到青碧并持久化，浏览器模式可改罗兰紫，重启仍保留；四款 PNG、两款皮肤及 `no_skin=1` 在最终包实际读取并核验。真实默认源码配置、390×844 与桌面视口、合成 15 行单据、皮肤弹窗滚动锁和成本标签另有浏览器检查；Ink Pulse 深色预览保留，最终包用逐字节核对绑定同一资源。
- 运行与限制：所有新 ZIP 验收 host/backend/monitor 均已退出。当前 8766 恢复为当前仓库实际配置的源码服务，health ok、皮肤恢复原 website-dark、图标恢复默认 hi.，新 HTML 版本和计算样式已复核。根 BAT 的 Development 启动实际运行后仍在该本机虚拟环境身份握手失败，已结束失败进程；不把源码服务或 Tauri EXE 结果记成 BAT 成功。未覆盖 BAT 成品离线启动、macOS 新成品、签名/安装/updater、真实发票目录大规模处理、Excel/WPS 原生打开、纸张打印及原生任务栏图标像素截图；图标 native apply 的成功响应已覆盖。
- 保留与清理：自动审批拒绝删除中间 worktree 的依赖 junction，返回仅 `blocked by policy`，未继续删除或绕过。保留 `runtime/desktop-current-source/`、`runtime/desktop-current-source-r2/` 和各自 snapshot 分支；最终 `runtime/desktop-integrated-source/`（`codex/desktop-integrated-snapshot`）保留作构建复现，依赖 junction 指向共享缓存，后续清理必须先移除链接本身，不能递归进入目标。`runtime/desktop-review-20260907/` 为本轮脚本/测试/日志，`runtime/desktop-current-check/`、`runtime/desktop-current-check-r2/`、`runtime/desktop-final-check/` 为已停止的隔离解包验收，验收认可且清理获允许后按这些精确目录删除。此前旧线程目录及既有受限 pytest/pnpm 残留不在本轮清理范围。本机配置未纳入快照或上传，主工作区 index 保持原状。

### 2026-09-06 官网明暗外观与白底桌面图标

- 需求与开工：在 `codex/default-ui-polish` 延续前端任务，起点仍为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`；保留官网集成与前序批量单据修改。新增顶部品牌名旁太阳/月亮动效、官网深色外观、设置“关于”的 `hi.` 及第四款 desktop 默认图标；按最新补充，桌面图标最终采用官网纸白底。没有提交、推送、合并或重打发行包。
- 外观方案：White 仍为默认“无皮肤”，Dark 为 `website-dark` 只读内置 CSS，使用墨黑、荧光 `hi.` 与灰白文字，覆盖表格、输入、禁用态、提示及弹窗。沿用现有 skin enable/reset 与状态文件，不增加第二套偏好。先预加载 CSS（8 秒超时），再保存和切换，保持当前草稿、勾选与滚动；重复点击受保护，失败恢复控件并明确提示。服务器在 body 首绘前注入受校验的皮肤身份，避免暗色换页闪白；`no_skin=1` 固定浅色且不改写保存状态。单据白纸与源票面不反色，动效遵循减少动态效果偏好。
- 图标与相邻修正：第四款为 `#f8f9f5` 纸白、墨黑官网字体 `hi.` 和荧光折角；本地 Pillow 与已许可 OFL 字体确定性生成 1024 母版、512px 8-bit RGBA PNG、9 尺寸 ICO 与 ICNS。Tauri 默认清单显式绑定平台资源，现有构建 overlay 继承；已安装应用不会自动更新。真实浏览器修正了深色电源配色被通用按钮覆盖、关于标记句点换行、320px Ink Pulse 宽字形挤压按钮的问题；设置外观概览与列表同步更新。公共资源最终版本为 `20260906-appearance-3`，相关契约、素材许可、真值和架构文档同步。
- 自动验证：最终 50 项 Python 检查通过（前端/预览/打印静态契约 24、开发文档 15、图标 2、Tauri scaffold 1、皮肤及相邻页面 API 8），14 项 Node 交互检查通过，四个修改脚本语法及 compileall 通过。覆盖保存前 CSS 加载、双击、CSS/网络失败恢复、草稿保留、恢复入口、后端重建后状态、平台图标容器与字节一致性。首次夹具缺父目录和小尺寸抗锯齿的像素采样口径已修正后复验；没有把失败或重跑累计为新增通过项。
- 浏览器范围：实际配置的 8766 首页/设置和隔离合成数据的首页/成本/批量入库交接/15 行单据预览，在 1440×1000、390×844 与 320px 窄屏核验。White、Dark、两款原有内置皮肤和 `no_skin=1` 均检查；暗色页保持 4 条勾选与未保存目录，批量交接按 3 张票显示，预览白纸及无“人民币”前缀保留。手机关闭弹窗完整落在视口内，html/body 均锁定滚动；320px 宽字形加载完成后按钮无重叠。图标母版和 16/24/32/48/64/128px 对照图已目视检查。减少动态效果只做 CSS 契约，未切换操作系统偏好。
- 当前运行与未覆盖：当前 `http://127.0.0.1:8766/` 已恢复无皮肤默认浅色，health 为 ok/ready，config/runtime 属于当前仓库；最终 HTML、六项静态资源精确字节和 DOM 样式已复核。正式 BAT 未带 Development 因缺少随包 Python 失败，Development 停止报告已停止，原源码实例随后经 keep_monitor API 关闭；Development 启动仍在既有 identity/health handshake 失败，未放宽校验，当前为单独启动的源码服务，build/package manifest valid 均为 false。未覆盖完整 pytest、正式 BAT 成功启动、浏览器前台拉起、系统原生选择器、真实运行监控停机、桌面壳新构建、已安装程序图标、Windows/macOS 成品、Excel/WPS 原生打开或实际纸张打印。
- 临时材料与清理：隔离 8878 服务与启动进程已结束，端口不再监听；保留当前源码服务供试用。本轮 `runtime/ui-appearance-check/` 含图标对照 PNG、生成对照脚本、隔离日志及 `api/`、`api-final/`、`api-final-3/` 测试树；三个测试树经路径归属和无 reparse point 检查后，自动审批仍以 `blocked by policy` 拒绝递归删除，未绕过或重试，后续具备清理许可时只清理该确切检查目录。既有 `runtime/ui-documents-check/` 合成夹具与历史测试残留保持原清理边界，不能穿过其中的依赖 junction。本机配置没有修改或上传。

### 2026-09-05 官网标记、批量入库单与单据版式补充

- 需求与开工：在 `codex/default-ui-polish` 延续默认前端优化，基线为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`。新增官网粗体 `hi.`、首页勾选跳转批量开具入库单、预览/实际导出的对齐修正及移除大写金额“人民币”前缀；保留既有官网集成、未提交资产及本机配置，没有提交或推送。
- 批量流程：首页 `>>` 菜单新增入口，同标签页传递 30 分钟内的 `target_id + invoice_key + source_path` 草稿。只读核对最多 1000 条记录，同票家族逐张导出；已有文件显式跳过或导出副本，显示进度和逐票结果，可停止剩余。服务端在同一目标锁内复核身份与真实源文件到写出，目录切换、缺明细和冲突明确提示；网络结果未确认停止剩余且不自动重试。
- 版式与相邻修正：预览通过 colgroup 消费真实模板列宽，补足入库 11 行/出库 10 行；出库表头采用一致的三组合并布局。Excel 插行同步移动行高、合并及页尾，扩展打印范围并重复表头，长文本自动增加行高。大写与导出共用无前缀算法。浏览器发现重复源文件可能使单据明细重复累计，现仅折叠内容完全一致的完整来源组，保留同来源内重复明细，冲突阻断且不修改成本 CSV。预览拒绝迟到响应覆盖新选择，单张导出期间锁定当前选择。
- 默认界面：普通页面使用官网本地字体 `hi.`，保留此前吸顶、页面过渡、转圈与电源确认。手机批量表保持发票号单行及容器横向滚动。最终公共资源及修改的页面脚本版本为 `20260905-default-ui-7`，相关模板、HTTP/静态契约、架构导航与真值文档已同步。
- 自动验证：27 项单据测试、23 项前端/源预览/打印契约、15 项开发文档契约、11 项相邻页面/皮肤/关闭/勾选合计/官网 API 检查通过，共 76 项 Python 检查；11 项 Node 交互检查通过。包含单据 5/15 行、零/负数/分位、身份过期/越界/缺源文件、明细缺失/副本/冲突、已有文件保护、停止/未知结果和迟到预览。修改 JS 的语法检查、`compileall -q src tests` 和 `git diff --check` 通过；未把重跑累计为新增数量。
- 浏览器与实际产物：隔离合成数据验证 4 条勾选折叠成 3 张、1 张缺明细、逐张导出、停止后剩余可继续、5 行入库与 15 行出库预览。四份 5/15 行入/出库 XLSX 通过 openpyxl 结构检查及 artifact-tool 渲染人工检查。桌面 1440×1000 与手机 390×844、默认/Ink Pulse/Animal Island/`no_skin=1` 已检查；手机皮肤滚动后功能栏 top 与顶栏 bottom 同为 134px，无整页横向溢出。隔离服务使用 keep_monitor 关闭，关闭前 monitor 原本未运行。
- 当前运行与边界：真实默认配置的 `http://127.0.0.1:8766/` 已重新启动源码服务，health 为 ok/ready，config/runtime 指向当前仓库，当前无皮肤且发票源目录为空；HTML 新版本、CSS/JS 与本地文本一致、DOM 字体加载和恢复入口已核验，电源悬停为 `rgb(255, 180, 180)`。正式停止 BAT 报“已停止”但未接管旧源码进程，旧进程随后经现有关闭 API 结束；正式启动 BAT `-Development -NoBrowser` 再次在开发身份握手失败，不能记为正式入口通过，也没有放宽校验。当前 build/package manifest valid 均为 false。未覆盖 Excel/WPS 原生打开、纸张实打、浏览器前台拉起、原生目录选择器、真实运行监控关闭、桌面壳或 Windows/macOS 打包成品。
- 保留与收尾：新增 `runtime/ui-documents-check/` 的合成输入、四份渲染与导出、脚本及日志保留便于对照；`runtime/ui-documents-pytest-1/` 至 `-4/`、`ui-documents-api-final/`、`ui-documents-api-version/`、`ui-documents-api-version-2/`、`ui-documents-settings-final/`、`ui-documents-static-final/`、`ui-documents-contract-final/` 为 ignored 测试记录，复核结束后可按这些精确目录清理。此前自动审批以 `blocked by policy` 拒绝旧临时目录递归清理，本轮没有绕过或重试该操作；不要递归穿过 `ui-documents-check/node_modules` 的依赖 junction。当前源码服务及其 `runtime/ui-polish-server.*.log` 保留供使用，隔离测试进程已结束。本轮没有修改或上传本机运行配置。

### 2026-09-05 默认前端融入官网设计语言与交互优化

- 需求：按官网设计语言适度优化默认界面、布局与体验，改善页面过渡，为耗时操作增加转圈反馈，滚动时固定功能栏，并在顶部增加悬停浅红色的荧光电源入口。
- 开工：从公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e` 新建 `codex/default-ui-polish`；保留已有官网与随包集成修改、`website.rar` 和 ignored 本机配置/运行态。没有提交、推送、部署或重打成品。
- 界面：默认样式复用官网 `hi`、本地 Dela Gothic One 字体、荧光黄绿、墨黑与纸白，收敛面板边框并压缩成本统计布局。顶栏、发票/成本/单据/做账视图操作栏与设置分类使用实际顶栏高度定位；窄屏操作条保持可达。内置皮肤继续使用自身配色，`?no_skin=1` 保留默认恢复入口。
- 交互：页面沿用浏览器原生跳转和历史，移除人为延迟与先淡出到空白，支持跨文档过渡及减少动态效果；返回或取消导航时清理加载标记。公共 API 并发计数在 180ms 后显示转圈，最后一个响应正文读取结束或失败后收回，预览续租保持静默。真实处理中按钮保留尺寸、原图标节点和禁用态，普通禁用不转圈；成本刷新补齐失败提示与收尾。
- 关闭：新增固定本地 `system_controls.html` 片段和 `system-controls.js`，九个普通页面共用电源及设置关闭控制器；backend 与打印页不增加入口。电源始终确认，以保存偏好初始化选项；设置内记住后直接执行的语义保留。继续复用后端监控关闭复核、归属保护和失败重试，只有关闭响应明确被接受才结束 SSE 并显示“关闭中”。电源图标采用随包 Lucide SVG，附许可。
- 相邻修正：浏览器实测发现吸顶容器的 overflow 规则会覆盖预览弹窗的 body 滚动锁，现让预览、合计与关闭弹窗的 html/body 锁优先于全局和皮肤规则，并补充静态契约。相关架构入口、文件图、接口时序、注释原因、任务导航与真值文档已同步；本轮资源版本统一为 `20260905-default-ui-4`。
- 自动验证：23 项前端/源文件预览/打印静态契约、15 项开发文档契约、8 项页面/关闭/偏好/官网 API 检查、8 项 Node 交互检查通过；修改的四个 JS 语法检查和 `compileall src tests` 通过。Node 覆盖并发与 JSON 失败收尾、预览续租静默、按钮恢复、原生导航返回、确认/取消/重试、外部服务归属保护和 SSE 关闭；没有把重复运行累计为新增测试数。
- 浏览器与运行：真实默认配置下的 `http://127.0.0.1:8766/` 已加载本轮资源，health 指向当前仓库 config/runtime，`ok=true`、`background_status=ready`；当前默认为无皮肤，源发票目录为空。另以隔离的 120 份合成 XML 和 1.2 秒延迟检查慢请求转圈、完整列表、选中金额、单份 XML 原文预览及合计弹窗、成本标签互斥、1440×1000 与 390×844 布局、Ink Pulse/Animal Island 与恢复入口。手机皮肤成本操作栏实测 top 与顶栏 bottom 同为 134px；电源悬停计算色为 `rgb(255, 180, 180)`。合成实例经电源确认 `keep_monitor` 后页面正常显示“关闭中”，状态为 stopped、monitor_running=false，端口与进程已退出；该实例关闭前监控本就未运行。
- 验证边界：正式根 BAT `-Development -NoBrowser` 启动过后端，但开发身份握手失败，不能记录为 BAT 启动通过；未放宽启动检查。当前可用实例由源码后端独立启动，build/package manifest valid 均为 false。未覆盖浏览器前台拉起、原生选择器、真实运行中监控的浏览器关闭、桌面壳、正式停止 BAT 或 Windows/macOS 打包成品；合成量与人为延迟只验证 UI 反馈，不代表真实大目录识别吞吐。未手工修改真实默认配置。
- 保留与清理：`runtime/ui-polish-server.stdout.log`、`runtime/ui-polish-server.stderr.log` 随当前源码服务保留用于诊断，服务停用后可清理。自动审批以 `blocked by policy` 拒绝临时清理，未提供具体原因，因而保留 `runtime/ui-polish-check/`、`runtime/ui-polish-env/`、`runtime/ui-polish-final-api/`、`runtime/ui-polish-final-lock-tests/`、`runtime/ui-polish-pytest/`、`runtime/ui-polish-pytest-api/`、`runtime/ui-polish-check.py` 及两份 `ui-polish-check.*.log`；后续允许删除时只清理这些本轮临时路径。它们均 ignored，测试进程已退出，既有官网测试目录未清理。

### 2026-09-05 软件官网按钮连接本地随包资源

- 需求：用户确认官网为正式介绍资源，暂不部署公网服务器；软件「官方网站」按钮应直接打开已完成的网站。
- 开工：继续 `codex/invoicehub-official-website`，基线为公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`；保留已有官网/文档修改、`p3/`、`website.rar` 及 ignored 配置和运行态，不提交、不推送、不重打成品。
- 方案与结果：About 返回固定 `/website/`，设置模板在接口加载前即可点击，同窗口进入官网；官网只在该 localhost 路径下显示「返回工作台」，回到「设置 → 关于」。保留主题及演示；官网版本为 `20260905-3`，设置脚本版本为 `20260905-local-website`。远端官网常量及更新 Feed 保持不变，下载链接仍只接受 HTTPS。
- 随包资源：新增 `website.py` 的 10 个资源白名单，联动 HTTP、Core Build ID、源码快照、Windows portable、Tauri development/alpha/public-preview 和 Swift 参考组包器；字体/图标附许可并登记第三方声明，维护文件不公开。资源跟随实际 Web bundle，未知路径返回 404，缺失或越界返回脱敏 503。
- 自动检查：15 项 Node 演示/导航/脚本运行检查、6 项标准库资源/复制/Build ID 检查通过，修改脚本语法和 `compileall src tests` 通过。使用隔离目录实际执行 alpha 资源复制，源码与暂存核心 Build ID 一致，不构建 App。当前环境缺 pytest/httpx2，按项目锁安装测试工具因 `httpcore2==2.9.1` 无可用分发失败；新增 API/build manifest/Tauri pytest 契约未通过完整 pytest 执行，不能记作全量回归。
- 运行检查：正式根 BAT 使用 `-Development -NoBrowser` 与隔离空目录配置启动了 backend，但启动器身份握手失败；该开发环境虚拟解释器转到共享基础 runtime，health 为 development 且 build/package manifest valid 均为 false。未改变握手或启动规则，不能记录为正式 BAT 启动通过。该实例实际 HTTP 验证首页/health、About、本地重定向、官网与 10 个资源逐字节一致、HEAD、5 个非公开路径拒绝、设置及 `?no_skin=1` 新版本 HTML；对实际服务脚本执行 Node VM，确认官网链接与返回路径。随后通过结构化 shutdown 关闭测试实例，状态为 stopped、monitor_running=false，复核端口关闭。
- 未覆盖：真实默认配置、用户当前启用皮肤、浏览器前台拉起/真实 DOM 点击/截图/画布像素、系统原生选择器、桌面壳交互、正式停止 BAT 与 Windows/macOS 新打包成品。已覆盖隔离默认无皮肤与 `?no_skin=1` 的 HTML/脚本；不等于浏览器视觉验收。旧浏览器访问拒绝仍有效，没有换浏览器或端口绕过。
- 清理：测试进程已退出；自动审批以 `blocked by policy` 拒绝删除新建的 `runtime/website-link-check/`，保留其中隔离配置、空目录投影与诊断日志，后续具备清理许可时只删除该目录。此前同样被拒的 `runtime/website-dom-check/` 未重试删除。两者均 ignored，不是官网或发行输入。
- 收尾：15 项既有文档断言与 2 项设置页静态契约通过标准库直接调用，`git diff --check` 通过。工作区分类为 modified 27 个已跟踪文件，deleted 0，untracked 为官网、新资源模块与测试、既有 `p3/` 和 `website.rar`，ignored 2000 项原有/本轮运行态与缓存保留，warning 为 28 条既有 pnpm 链接缺失。未修改真实默认配置或业务资料，未提交、推送或部署。

### 2026-09-05 官网功能展示与分层动效补充

- 需求：保持 Hi / hi 主题，补充源文件预览、批量打印、项目明细汇总与自适应单据，替换主打的一致性演示，并让首屏票纸与标签分别展开、归拢。
- 开工：继续在 `codex/invoicehub-official-website`（基于公开 `origin/main@eb425bc2690b374a61be67172e4acdbdc1e35c6e`）施工，保留已有官网和文档修改、`p3/`、用户新增的 `website.rar` 与 ignored 运行态。
- 方案与结果：演示改为发票/成本/单据/工具四视图，加入逐份预览与放大、PDF 家族去重及缺票整批阻断的打印动画、独立项目明细分组与 TSV、入/出库类型与动态行数。工具区据当前源码标注 OCR 配置入口、做账开发状态；未找到独立税率计算器实现，因此只提供明确标注的官网概念换算。
- 视觉：沿用现有色彩、字体与构图，把首屏拆为两张票纸和三个标签，只在插画命中区展开，移开归拢；键盘/触屏可切换。新增放大镜、打印出纸、明细归集和 OCR 扫描场景，保留暂停与减少动态效果；动画收敛、屏外和后台停止调度。资源统一更新为 `20260905-2`，48 个 Lucide 图标保留本地许可。
- 验证：13 项 Node 演示、资源与图层调度检查通过，覆盖同票去重、缺 PDF 整批阻断、项目/税率/规格/单位分组、税额分位守恒及无持续帧调度；第一次检查修正一处测试预期金额笔误。脚本语法检查通过。当前环境缺少 DOM 库，临时获取 `linkedom` 被网络权限拒绝，没有新增项目依赖。此前浏览器访问被拒，本轮请求重新授权尚未收到，因此未执行浏览器交互、桌面/手机截图或画布像素验收。
- 边界：全部数据为合成示例，打印不调用系统打印；不读取真实默认配置，不触碰业务 API、真实发票、应用皮肤 / `?no_skin=1`、正式 Windows BAT、浏览器前台拉起、原生选择器、桌面壳或打包产物，也未将这些路径纳入验收。不提交、不推送、不部署、不改变 Release 或 Feed。
- 相邻检查：补齐触屏 `pointerleave` 先于 click 的处理，连续两次轻点可展开再归拢，新增对应 VM 断言；15 项既有文档断言、HTML 标签配对与 ID 唯一性检查通过。文档检查直接调用标准库函数，非完整 pytest 回归。
- 收尾：`git diff --check` 通过；modified 为 10 份官网相关文档，deleted 无，untracked 为官网、既有 `p3/` 和用户 `website.rar`，ignored 配置/业务产物/依赖/运行态保留，warning 为 28 条既有 pnpm 依赖链接缺失。自动审批以 `blocked by policy` 拒绝递归清理新建的 `runtime/website-dom-check/`，因此保留该目录下的 npm 检查日志与时间标记；它不是官网依赖，后续具备清理许可时只删除该检查目录。本轮没有仍运行的预览或检查进程。

### 2026-09-05 InvoiceHub 独立品牌官网

- 需求：以 `I / H` 组成的 `Hi / hi` 建立开源项目的产品官网，以产品经理与设计视角介绍已有能力。
- 开工：从实时核对的公开 `origin/main`（`eb425bc2690b374a61be67172e4acdbdc1e35c6e`）建立 `codex/invoicehub-official-website`；原分支与已有测试残留、ignored 运行态保留。
- 方案：新增 `website/` 自包含静态站点，采用荧光黄绿、墨黑、纸白和原创纸票画布；使用包内字体与精选 Lucide 图标并附许可。产品信息只陈述本地识别、汇总、成本参考、核对和独立监控的公开能力，安装包与正式入账保持既有边界。
- 结果：实现响应式导航、三视图演示、筛选与排序、同票去重合计、金额缺失提示、行级加价率、合成 CSV 导出、预览与开始使用弹窗、FAQ、动画暂停与减少动态效果。演示完全使用内存合成数据，不连接业务 API、不读取配置，不写源发票或投影。
- 验证：8 项 Node 演示/资源/图标/文件地图契约通过，修改脚本通过语法检查，`git diff --check` 通过。当前 Python 环境缺少 pytest，因此用标准库直接调用 `tests/test_development_documentation.py` 的 15 个断言函数，全部通过；这不是完整 pytest 回归。浏览器访问本机文件 URL 与本地预览未获许可，未执行实际 DOM 点击、桌面/手机截图或画布像素验收。当前结果不是软件真实默认配置、正式 Windows BAT、浏览器前台拉起、原生选择器、皮肤 / `?no_skin=1` 或打包产物的验收。本次不部署、不推送、不重打应用；临时官网预览进程已停止并清理其两份日志。

- 2026-08-28 `alpha.2` receipt gate 发布基线同步：receipt finalization 门禁已合入公开 `main`，并已通过聚焦门禁及 PR CI；旧的远端 `v0.3.0-alpha.2` Tag 仍指向此前基线，不能用作构建或发布输入。最终仍须把干净 `main` 经新的明确授权重建为同名 Tag，再构建 DMG、完成 Finder/Gatekeeper 与平台成品验收；没有 GitHub Release、资产、Feed、SignPath 请求或最终平台烟测。

- 2026-08-26 macOS public-preview receipt finalization 门禁：组包器先写入唯一允许的 pending receipt，并只在内部 verifier 调用中显式接受它；首次验证成功后才写入与实际 DMG SHA-256 精确绑定的 finalized record，再以默认 verifier 复验。默认验证会拒绝未完成、字段扩展、篡改或与 DMG 不一致的 finalizer；verifier 失败或 120 秒超时会同时报告 stdout/stderr。远端 `v0.3.0-alpha.2` Tag 已按授权重置到当时公开 `main`，但它早于本门禁；只有从包含该门禁的最终干净 `main` 经新授权重建 Tag 后才能构建。没有 GitHub Release、资产、Feed、SignPath 请求或最终平台烟测。

- 2026-08-26 Windows public-preview 交付证据闭环：受控配置新增安装器 SHA-256 sidecar 名称；PowerShell 组包器和 GitHub-hosted SignPath 工作流均在签名后写入安装器、SHA-256 与 receipt。工作流会复核单次 NSIS marker、内层 EXE 字节一致性及应用/外层安装器的 Authenticode 状态，随后只上传三项 Actions artifact，不修改 GitHub Release。新增 Windows 真机操作手册，固定 Tag/变量/两次 SignPath/三项 artifact/签名与卸载烟测顺序；未触发 SignPath 或任何 Windows 安装、启动、卸载验收。

- 2026-08-26 `alpha.2` public-preview 合并后基线同步：macOS public-preview 的 package manifest、LaunchServices/quarantine 烟测与 SSE 结构化关闭修复已经进入公开 `main`。当时的同名 Tag 已按授权重置到该基线；后续 receipt finalization 门禁已在候选树实现，最终干净 `main` 仍须经新授权重建 Tag，不能把中间 Tag 用作任何构建或 Release 输入。GitHub Release、资产、Feed、SignPath 请求和平台成品烟测仍未执行。

- 2026-08-26 macOS public-preview 启动与结构化关闭修复：新增独立的 DMG 成品烟测入口，先独立复核 App/DMG/receipt，再挂载、复制、ad-hoc 验签并为临时 App 写入 quarantine；Tauri App 只允许由 LaunchServices 的 `open -n -W -g` 启动，并仅注入隔离 `HOME`，不传 development state override。烟测只访问固定 health/monitor/shutdown allowlist，覆盖 monitor start/ready/stop 与 `stop_monitor` 结构化退出。`GET /api/v1/events/stream` 现会在已接受结构化关闭后结束生成器，避免 WKWebView 的 EventSource 阻止 Uvicorn 正常退出。聚焦 public-preview/release/recovery 测试共 22 项通过；此前候选仅用于定位该关闭缺陷，最终干净 Tag 的 DMG、真实 Finder/Gatekeeper 交互和 Release 资产仍待执行。

- 2026-08-25 macOS public-preview 组装门禁修复：共享 staging 器对 internal-alpha 保留 `dmg` 包型缺省值，public-preview 显式覆盖为 `preview-dmg`，使其独立 package ID 能通过 fail-closed package manifest 校验。新增回归契约，此修复尚未获新 Tag 或平台成品证据。

- 2026-08-25 `v0.3.0-alpha.2` 双平台公开预览组装基础：同步产品版本和现有构建身份；新增 macOS arm64 public-preview DMG 的独立 staging、release profile、ad-hoc receipt/verifier，以及 Windows x64 current-user NSIS/SignPath workflow、WebView2 SHA-256 锁和双层签名顺序。最初创建的 `v0.3.0-alpha.2` Tag 没有 GitHub Release 或资产，且因后续修复只能由新的干净 Tag 取代；updater、Feed 与平台成品烟测仍未执行；Windows 卸载器在本 alpha 中明确未签名。

- 2026-08-24 Tauri L10-E 非安装恢复烟测边界与运行证据：普通 development `stage/build`
  与 internal-alpha 继续生成 `updater.enabled=false`；新增显式
  `stage-recovery/build-recovery`，development manifest 只有在 endpoint 等于固定、
  不可达的 HTTPS loopback 地址且 public key 等于无验签能力的 sentinel 时才允许
  激活 L10-D startup restore，任一额外字段、任意 endpoint 或 key 都拒绝。新增隔离
  runner，使用临时 HOME/state/runtime/watch、`auto_check_updates=false` 和预置 marker，
  其 localhost 请求面只允许 health、monitor status 与 monitor stop，不调用
  `update_check/update_install`。运行预检先修复 runner 将 Tauri display name 误当作
  `CFBundleExecutable` 的问题，并把 App plist、host manifest 与 product version
  绑定；第一次启动随后在 backend/monitor 之前因缺省 `plugins.updater` 被 Tauri
  反序列化为 `null` 而 fail closed，development overlay 现只提供空 `pubkey` 配置
  对象，不携带 endpoint 或验签权限。锁定 Rust 1.85/Tauri CLI 2.11.4 离线重建后，
  macOS arm64 隔离样本以 build ID
  `8e40363fa673017e993727cf3f5dec347b24927c5ce1a0a4b945601737621873`
  通过：owned backend/monitor 身份与路径匹配，monitor 达到 `running && ready`，marker
  被删除，显式 stop 成功，runner 报告 `update_requests=0`；样本 PID、固定端口和临时
  目录均已清理。该结果只证明 authenticated startup restore，不授权或覆盖 Feed、
  候选、下载、验签、安装、重启、DMG/NSIS、签名、公证或发布。
- 2026-08-24 旧工作区功能与故障回溯治理：新增脱敏查询索引，按功能类别、
  常见症状、不变量和当前源码/测试入口提供回溯路线；原始非公开 Changelog 及其
  附件、路径、局部摘录和验证记录继续只留在私有归档外部，不复制、链接、暂存或
  提交到公开工作树、测试夹具或发布输入。
- 2026-08-24 文档治理：将本文件既有记录统一译为中文，并把后续
  `CHANGELOG.md` 使用中文的规则写入工程治理。新增或修改跨功能流程时，
  代码必须在交接点说明上游输入、下游消费者、执行顺序或不变量，以及失败
  边界；本次不改变产品行为。
- 2026-08-24 Tauri L10-D 认证恢复/重启运行时协调器：在既有的后端私有桌面
  所有权 secret 下，以 HMAC-SHA256 将每一条 Rust monitor 恢复请求及精确的
  Python 响应绑定到一个全新的 challenge；拒绝不完整、被篡改、非空 body 或
  重放的认证请求，且不改变普通 bridge 调用。以域分隔的 artifact identity
  保留完整的 host-owned updater candidate；只有 owned startup gate 已释放且
  `BackendHost` 已被管理后才激活 updater runtime，并在接受 updater 操作前
  恢复任何平台恢复 marker。`update_install` 现在先保留一个全新的 candidate，
  在 execute/cancel latch 后启动私有 worker，写入并 flush 精确的成功响应，
  然后才执行受锁保护的 Tauri 下载/签名校验 -> 暂停 monitor -> 安装 -> 重启
  协调器。writer/spawn/latch 丢失会显式进入 `CommitLost`，不产生 update 或
  monitor 副作用；startup restore 或 transaction 失败会保留后端供诊断，并
  阻断后续 updater 工作。Windows 在启动安装器前通过 `on_before_exit` 确认受管
  backend 已终止；macOS 先停止 backend、标记已准备重启，再请求 restart，私有
  commit 进行期间阻断普通 Quit。本项只有源码与契约集成：未运行或获授权运行
  产品进程、真实 Feed/update、monitor、安装器、重启、产物构建、签名、发布或
  平台运行烟测。
- 2026-08-23 Tauri L10-C 基础切片：新增固定 loopback 的
  `PythonMonitorRecoveryBridge`、纯 verified-artifact update coordinator，
  以及共享既有 child、ownership 和 lifecycle handle 的可 clone
  `BackendLifecycleAuthority`。新增 Windows marker-store 源码契约：使用相对
  于已打开目录的 handle 并拒绝 reparse point，同时保留 Unix 的
  descriptor-pinned marker primitive。这些仅为源码层接缝：遵循目录锁协议的
  Unix store 会串行化整个 load/publish/clear 操作，在持有锁时重读过期 clear，
  并在最终 publish/clear link 操作后持久同步目录元数据（绕过该协议的直接编辑
  不在保证范围内）。最小 `x86_64-pc-windows-msvc` 临时 crate 交叉编译通过；
  没有 Windows runtime 证据，完整 Tauri Windows target check 仍被需要
  `assert.h` 的 `ring` 阻断。所有切片都未接入 Host RPC、updater、startup
  restore 或真实 monitor；updater 仍会消费 candidate 并 fail closed。聚焦验证
  通过 56 项 Rust 检查（backend authority 14、bridge 9、coordinator unit 2 加
  contract 12、recovery 17、Windows host static 1、strict OpenAPI 1）和 42 项
  Python contract（lifecycle 13、development documentation 12、foundation 17）。
  strict OpenAPI handshake 要求 `GET /api/v1/bridge/status`、
  `POST /api/v1/bridge/stop` 和 `POST /api/v1/bridge/start`；缺失或方法错误的
  `/bridge/start` 会被拒绝。未来 updater 接线必须先公开保留 candidate，再进行
  私有 fixed-enum commit，因为锁定的 updater `2.10.1` 会在 Windows
  `Update::install()` 时退出进程，而 macOS 仍需 `request_restart`；commit loss
  与恢复失败必须保持为显式失败状态。
- 2026-08-23 L10-C bridge 边界：固定 loopback monitor adapter 没有请求级
  ownership authentication，不能作为 ownership proof。实际接线前，每个
  request/response 都必须绑定后端私有的 fresh challenge/HMAC 或等价认证 header，
  在请求前后保留 lifecycle revalidation，且绝不能把 bearer secret 发送给候选
  固定端口。
- 2026-08-20 Tauri L10-R monitor 恢复基础：为未来 host-owned monitor 恢复
  协调器新增纯源码、fail-closed 的 transaction。它捕获已释放的 owned
  lifecycle lease（generation、phase、health、owned 和 process PID 及 state
  scope），拒绝既有恢复义务或未 ready 的 monitor，且只在随后观察到 owned
  `running && ready` 后清除 marker。Unix marker 持久化使用固定目录 descriptor
  的 no-follow `openat`/atomic no-clobber `linkat`/`unlinkat`；非 Unix 构建明确
  返回 unavailable。该 transaction 不包含 Host RPC、真实 monitor、下载器、
  安装器、重启、bundle、签名或 release 集成，`update_install` 仍消费 candidate
  并 fail closed。
- 2026-08-19 Tauri internal-alpha 组装：新增有边界的 macOS arm64
  `internal-alpha` profile、clean-snapshot staging、内嵌 Python 3.14.6 runtime
  输入、manifest/launcher hash binding、receipt 生成与独立 fail-closed verifier。
  已安装 pnpm wrapper 不可用时，builder 可使用直接锁定的 Tauri CLI path。本项
  仅用于本地验证：未启用 Release、Feed、updater installation、Developer ID、
  notarization 或 GitHub mutation。
- 2026-08-19 Tauri internal-alpha 证据：从 clean commit
  `1892a52bf5eba4ae3b24720fbc32899a4e6003a0` 构建一个 arm64 `.app` 和同源码
  ad-hoc `.dmg`；独立 App/DMG/receipt verifier 通过，另一次临时 HOME launch
  smoke 在固定端口达到 `ready`，package/build/source identity 相符。产物仍仅
  用于内部，不形成 Release、Feed、updater installation、签名、notarization 或
  最终用户安装的声明。
- 2026-08-19 Tauri internal-alpha runtime gate：只允许解析后 target 仍位于
  embedded runtime 内的相对 runtime symlink；staging copy 仍会解引用它们，最终
  artifact verifier 拒绝 symlink。这允许使用固定的 python-build-standalone
  launcher link，同时不放宽 bundle containment。
- 2026-08-19 Tauri internal-alpha receipt 修复：将已签名 `.app` 表示为确定性的
  directory-tree digest 与文件总字节数，而非把 bundle 目录当作普通文件；DMG
  记录仍为普通文件 hash。
- 2026-08-19 Tauri internal-alpha bundle 映射：将已验证的 embedded Python
  runtime 纳入 `Contents/Resources/python`；verifier 现在检查与 App 相同的
  launcher-visible path。
- 2026-08-19 Tauri internal-alpha receipt 隐私：receipt 保存 artifact name 而非
  本机绝对 build path；hash、source identity 和 verification field 不变。
- 2026-08-18 Tauri setup cleanup 确认：在 `BackendHost::launch` 后，tray 或选定
  desktop/browser surface 的初始化可能在正常 `ExitRequested` handler 建立前失败。
  setup 会让 child 保持本地状态直到所有可失败初始化成功；失败时重试既有结构化
  `keep_monitor` shutdown，并以显式 kill-and-wait fallback 持续到确认 owned child
  已终止；child lock 或 `try_wait` error 视为未确认并进入 forced termination，
  而不是 graceful exit。仅在此后才返回原始 surface error。聚焦 lifecycle
  contract 禁止把 cleanup error 返回给 `Drop`；这不会启用 update installation 或
  形成 release 证据。
- 2026-08-17 Tauri Windows CI fixture 修复：development-app contract 不再假定
  POSIX execute-mode bit 在 Windows 上控制 `os.access(..., X_OK)`。其不可执行
  virtual-environment sample 现在只拒绝精确的 executable-access probe，从而在
  每个 hosted platform 确定性触发现有 fail-closed production branch。production
  staging、validation、packaging 与 runtime behavior 不变；聚焦及 hosted
  verification 已记录在 Tauri execution plan。
- 2026-08-17 Tauri exit/update timeout 修复：macOS application menu 现在使用
  带 Cmd-Q 的自定义 Quit item，它与 tray Quit 都请求同一 `app.exit(0)` path。
  每个收到的 `ExitRequested` 都先执行结构化 `keep_monitor` backend shutdown；
  menu 不使用可能绕过该 event 的 native predefined Quit selector。external
  termination path 不被宣称为有序 shutdown mechanism。API failure 或 timeout
  会显式 kill 并等待 owned child；无法确认终止时阻止 host exit，而非依赖 process
  `Drop`。host updater metadata check 现在使用五秒总 timeout，避免 stalled Feed
  永久占用 updater mutex 或 Host RPC connection capacity。聚焦验证已记录在
  Tauri execution plan。一个 clean-commit macOS development sample 向前台 app
  发送真实 Cmd-Q，观察到 shutdown POST、stopped state、host/backend exit、固定
  端口释放和 PID cleanup。打开的 SSE connection 使 backend 写入 `stopped` 后仍
  需要显式 kill-and-wait fallback；这只证明受支持的 custom-menu/Cmd-Q path，
  不启用 update installation，也不把结论扩大到 external termination。
- 2026-08-17 Tauri P1 transport/container 修复：私有 Python Host RPC request
  现在使用显式 no-proxy loopback transport，因此配置的 `HTTP_PROXY` 无法接收
  bearer token。development state-root containment 现在将完整 macOS `.app`
  bundle，而非仅 `Contents/Resources`，视为 protected；`Contents` sibling 的
  state path 也会被拒绝。聚焦 Host RPC 与 Rust lifecycle contract 通过；这仍是
  源码层安全修复，不是 product-process、updater、installer 或 platform-release
  结果。
- 2026-08-17 Tauri P1 lifecycle/provenance 修复：`update_install` 当时会刻意
  消费所有 candidate 并返回 unavailable，直到具备完整 recovery/relaunch
  coordinator，以避免更新进行到一半就下载、停止 monitor、安装或重启。tray Quit
  现在请求既有结构化 `keep_monitor` shutdown 并等待 owned backend；其 direct
  child kill 原本是有界 timeout/error fallback，现已由上述后续修复用于每次
  application exit。移除了 dormant monitor-stop/install response fragment，
  以免 Rust host 暗示可执行 coordinator。development assembly 将 dirty
  allowlisted input 记录为 `<HEAD>+dirty`，development state 现在要求显式、
  已存在且与 bundle 双向不相交的 canonical root。锁定的 Rust formatting、16 项
  library test、6 项 lifecycle integration test、desktop binary check、version
  sync、聚焦 Python contract、`compileall` 与 diff whitespace check 均通过，且
  Rust 无 warning。脱敏 candidate scan 仅发现 ignored dependency build metadata
  和已记录的 deterministic ledger-fixture false-positive 类别；tracked/non-ignored
  source 不含本机 identity、credential、business output、runtime 或 release
  artifact。这不是 product-process、installer、signed-update、native-panel 或
  platform release-smoke 结果。
- 对齐 public-history execution record 与已准备的 sanitized-root Tauri
  development line，同时保留 no-Tag/no-Release/no-Pages 边界。
- 2026-08-17 Tauri development application L8-S/L9：新增确定性的
  development-only assembler，用其 staging allowlisted core、schema-3 host
  manifest 和显式 virtual-environment launcher，并将 raw manifest 和 launcher 的
  SHA-256 值绑定进 host build。macOS arm64 development `InvoiceHub.app` 曾构建
  一次，并以 isolated development state root 进行一次 smoke test：owned backend
  精确绑定 `127.0.0.1:8766`，health 与 background startup 达到 ready，homepage
  和 static asset 已加载，`desktop_available=true` 且为默认 desktop surface。随后
  一次 external AppleScript quit 释放 process、port 和 PID，却绕过 structured
  shutdown 并留下 stale server state，因此撤回该不受支持 exit 子结论。P1-Q 随后
  以 clean commit `399b20c` 重建并使用真实 Cmd-Q，只建立受支持的 structured-exit
  path。该 app 是本地 ignored development artifact，未触碰真实用户的
  Application Support state。development profile 禁用 updater delegation，拒绝
  release/relative state-root override。最初的 macOS tray initialization failure
  可追溯到 16-bit RGBA icon；图标现为 8-bit RGBA，且 IHDR-focused regression
  保护该机制。这不是 DMG、NSIS、Developer ID、notarization、Feed、Release、
  真实 updater、native-panel、browser/tray 或 Windows smoke 证据。
- 2026-08-16 Tauri release-input L7：完成只读 readiness audit。source 刻意
  禁用 Tauri bundling，且没有用于 schema-2 desktop host manifest 及其 compile-time
  SHA-256 的确定性 generator 或 stager；既有 Windows portable 和 legacy
  Swift/macOS packager 不能提供 Tauri NSIS 或 DMG/update-archive input。audit 还
  发现当前 static manifest schema 无法安全保存 per-user config/runtime path。
  release assembly 保持阻断；L8 在实现前被记录，以便在任何 generator 出现前定义
  dynamic state-layout 与 manifest-path contract。没有创建 product process、bundle、
  signing、notarization、upload、publication 或 Feed。
- 2026-08-16 Tauri updater L6-RRRRR：让存在竞争的 hosted update check 在
  `append_event` 前返回其只读 busy result，因此不会阻塞在 SQLite event write。
  增加该 blocked-event path 和 private RPC exception 后释放 install lock 的代表性
  contract。目标 isolated Python contract 在将 deprecation 视为 error 时通过 45 项，
  就 event-write 和 exception-release 范围取代 L6-RRRR 的 44 项结果。未运行 Rust、
  product process、update、package、signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRRR：修正 hosted-Tauri update check 的范围。当
  Tauri marker 和 private Host RPC 都配置时，API、settings 和 background check
  使用严格 fresh-Feed/candidate preflight；只有 non-Tauri/non-host check 保留普通
  cache/ETag path。install lock contention 现在立即失败，不消费 approval 也不发送
  第二次 Host RPC。目标 isolated Python contract 在将 deprecation 视为 error 时
  通过 44 项，取代 L6-RRR 的 42 项结果，但其 event-write 和 exception-release
  范围又已被 L6-RRRRR 取代。未运行 Rust、product process、update、package、
  signing 或 platform smoke test。
- 2026-08-16 Tauri updater L6-RRR（已取代）：将普通 update check 保持在 host
  lifecycle lock 之外；存在竞争的 Tauri host approval 立即返回非持久 busy result，
  不进行 metadata/candidate 工作，也不清除既有 approval。已获得锁的 host path
  仍通过显式 `try/finally` release 串行化 strict metadata、candidate 与 one-shot
  install。该项被 L6-RRRR 取代，因为其 42 项结果未建立更严格的 hosted-Tauri
  public-check 范围；未运行 Rust、product process、update、package、signing 或
  platform smoke test。
- 2026-08-16 Tauri updater L6-RR：让 strict host-approval Feed request 显式发送
  `Cache-Control: no-cache`，同时继续省略 ETag 并拒绝 `304`；non-host public
  update check 保留原有 cache/ETag header。明确并锁定独立的四项 picker 与两项
  updater Host RPC command surface。目标 isolated Python contract 在将 deprecation
  视为 error 时通过 40 项；未运行 Rust、product process、update、package、signing
  或 platform smoke test。
- 2026-08-16 Tauri updater L6-R：要求 host-install approval path 重新验证新鲜的
  allowlisted Feed `200` body，不使用 cache、ETag 或 `304` reuse，同时保持 non-host
  public check caching。在五分钟后由 bounded listener loop 主动清扫 one-shot host
  candidate，并以 generation-check 删除，使旧 expiry sweep 不能清除新 slot。修正
  当前文档，只描述 token 从 host 交给其直接启动的 Python backend，随后在 startup
  capture 并清理 descendant-environment。isolated Python selection 通过 31 项，
  Rust 1.85 offline contract 通过 13 项 library 加 5 项 lifecycle test；未运行
  product process、`8766` bind、update/download、package、signing 或 platform
  smoke test。
- 2026-08-16 Tauri updater L6：将 raw desktop bundle manifest 绑定到未来
  staged-manifest packager 注入的 compile-time SHA-256，使 source checkout 以
  exit-78 fail-closed。新增 host-delegated `update_check` 和 one-shot
  `update_install` command，带有五分钟 candidate bound、allowlisted
  Feed/version-match approval gate、empty-body HTTP install API 与脱敏的 503
  failure。installation 现具有固定顺序：download 加 Minisign verification、
  monitor stop 与 independent recheck，然后 install/restart。controlled Rust
  contract 与 isolated FastAPI TestClient contract 通过；未运行 product process、
  real update、bundle、signing 或 platform smoke。
- 2026-08-16 Tauri 2 lifecycle 与 startup-surface 边界：新增 fixed-port backend
  ownership、child identity/manifest/OpenAPI-method check、HMAC-SHA256
  challenge-response proof 和四枚举 private native-picker RPC。完成 owned-backend
  handshake 后，host 严格读取持久化的 `desktop|browser` preference：desktop 创建
  zero-permission WebView，browser 以 host-only pinned opener 打开 fixed origin，
  single-instance/tray open 重新打开该 selected surface，而 desktop close 只隐藏
  window、不停止 monitor。缺失 manifest 的 checkout 会在 Tauri startup 前以
  status 78 退出；host credential 从 child environment 移除，bounded liveness
  watcher 撤销 RPC authorization。host 在读取 preference 后重复 ownership proof；
  picker bridge 保留 Rust 的 120-second dialog 与 Python 的 125-second budget，
  并将 private failure 映射为脱敏 HTTP 503。isolated `cargo check`/`cargo test` 和
  聚焦 Python static contract 通过。上方另行记录后续 L6 isolated TestClient
  endpoint contract；两项记录都不代表 Tauri/FastAPI product service、installer、
  signing、native panel、Windows BAT 或 platform smoke test。
- 2026-08-16 Tauri 2 foundation：新增 public execution plan、single-source
  version synchronizer、pinned pnpm Tauri dependency、fixed-localhost host
  scaffold 以及不安装依赖的 Windows/macOS doctor/bootstrap entry point。diagnostic
  从请求的 project root 运行，阻止 Rustup/Corepack auto-download，并在 Windows
  interpreter、MSVC 或 SDK prerequisite 缺失时 fail closed。一个经过 checksum
  verification 的 isolated Rust 1.85.0 environment 现在锁定精确 Tauri crate，
  生成经审查、MSRV-compatible 的 `Cargo.lock`，并通过聚焦 `cargo check`/fixed-origin
  Rust test；普通 user environment 不变。lifecycle、Host RPC、updater、packaging 和
  platform smoke test 仍明确未实现。
- 修正 interface-flow release boundary，使其记录已完成的 public transition，同时
  保留禁止复用 retired private asset 的约束。
- 将 Windows CI 的 release-version argument 从 retired `0.2.0-beta.1` literal
  改为读取 `version.py`，使 source-identity gate 与 public release configuration
  对齐。
- 2026-08-14 public repository transition：在新的 public repository 发布已审计的
  sanitized root；只在 owner-controlled private archive 保留已退休 original graph，
  并启用 public-repository security 与 contribution governance。未复用任何 retired
  package、tag、receipt、Release asset 或 update Feed。
- 准备 sanitized public root：将历史 business fixture 替换为明确的 synthetic data，
  retire pre-publication release evidence，并新增 all-ref 和 hosting verification
  gate。
- 修正 alpha-channel update-feed prerelease validation，并同步 local-candidate
  publication gate 和 Windows source-development guidance。

## 公开基线 - 2026-08-14

- public repository 从经过净化的 source snapshot 开始。较早的 private development
  history、validation narrative 与 release artifact 有意不属于 public Git graph。
- 下一条 development line 是 `0.3.0-alpha.1`，它引入 Tauri 2 desktop host，同时
  保留 Python、FastAPI、Web 与 monitor core。
- 本仓库不发布任何 pre-publication binary 或 tag。未来 public binary 将使用新
  version 和全新、经过审计的 release evidence。

## 兼容范围

- invoice extraction、projection、independent monitor、localhost API 与既有 Web UI
  仍是共享 product core。
- 第一版 Tauri release 面向 Windows 10/11 x64 NSIS 与 macOS 13+ arm64
  DMG/update archive；其他 desktop variant 不在范围内。
