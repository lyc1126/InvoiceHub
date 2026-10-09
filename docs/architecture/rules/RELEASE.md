# 公开基线、构建与发行规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：版本、RC、依赖锁、源码快照、平台成品、签名、SBOM、receipt、Feed 与发布验收。
- 代码与验收定位：release/、scripts/dev/；任务导航第 13—13.1 节、docs/release/UPDATE_SYSTEM.md。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-release) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

## 发行身份、平台输入与复现

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

## 更新与 Feed 放行

- Windows 更新不得覆盖运行中的旧目录；使用“新 ZIP 解压到新目录 + 白名单导入设置 + 保留旧目录回滚”。迁移不得复制日志、PID、SQLite、cache、皮肤、源发票或成本产物。
- `v0.3` 发布 Feed 是最后切换点。适用平台真机、对应源码、SBOM、签名/公证、updater 实际升级、重下载复验和人工许可检查任一缺失时，不得让公开 Feed 指向候选。
- 安装包只放 GitHub Releases；从 `v0.3` 起同仓库 GitHub Pages 提供更新 Feed。不使用 GitHub Packages 或 App Store。Rust/Cargo/pnpm/Tauri 依赖必须锁定，Windows/macOS `doctor` 与 `bootstrap` 只能诊断环境，不得自动安装证书、Xcode 或 Visual Studio。

## 公开历史、重打与验证预算

- 退休的预公开包只保留在 owner-only 私有备份中，不能作为新的公开 Tag、Release、Feed 或构建证据。不得为补 receipt、刷新数字或补表格重打或复用它们。
- 开源治理、许可证、文档、仓库 public 设置、Release 说明和 Feed 元数据变化不触发新应用重打。只有新包的包内输入变化、包损坏、签名失效或嵌入身份不一致时才重打；仅影响单平台时只处理该平台。
- 公开前已对全部保留 refs 执行一次 gitleaks 和一次真实业务文件扫描，并以通过结果建立新的公开根。文档、许可证、仓库设置和 Feed 元数据变化不刷新该审计；发现新的真实秘密或业务数据时，先轮换/隔离并只复核受影响机制。旧历史包和资产不得上传。
- 2026-08-14 的远端可达历史扫描确认存在真实目录及私有标识；用户已批准并完成历史净化。新公开仓库独立于原始私有归档；不得上传退休 Release、Tag、receipt 或包，也不得为其建立兼容 Feed。Tauri 开发分支、Release 与 Feed 仍须按各自门槛另行创建。
- 每项实验开始前必须记录假设、结果会改变的决策、最小样本和停止条件；无法改变决策的实验不得执行。相同失败机制只用一个代表样本，结果矛盾、修改面扩大或机制不同才追加样本。
- 每个 RC 最多一次完整回归；先运行命中变更面的聚焦验证。Tauri `v0.3` 的决策场景固定为两种启动方式、单实例与错误端口、Host RPC 授权边界、合法/篡改更新、安装前 monitor 停止；修复后只重跑受影响类别。

## 发布验收

- 发布变更必须分别覆盖 Windows 真机手册与 macOS 正式发布手册；共享单测、静态契约、模拟 runtime、开发 `.app`、ad-hoc 签名和替代端口都不能冒充对应成品证据。
- 发布包不得把本机 `config/app.local.json` 原样打入或递归复制整个 `config/`；必须只生成脱敏默认配置，并扫描本机业务路径、真实发票/投影、运行态、日志、PID、SQLite、cache、秘密和开发工具。构建 provenance 必须覆盖全部实际包输入。
