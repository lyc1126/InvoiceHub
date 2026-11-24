# Windows 正式入口与启动规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：BAT/PS1、PowerShell 5.1、中文路径、端口冲突、PID、浏览器与原生选择器。
- 代码与验收定位：scripts/windows/、platform/windows.py；平台架构与任务导航第 12 节。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-windows) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

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

## 正式入口验收

- Windows 用户入口变更必须至少覆盖：
  - 正式 BAT 启动
  - 停止 localhost 后监控仍运行
  - stop-all 入口停止监控
  - 根目录快捷入口
  - 首页 `/`
  - `GET /api/v1/health`
  - runtime 基础日志与 `server_state.json`
  - 正式停止

监控启停同时遵守 [监控规则](MONITORING.md)，成品输入和发布同时遵守 [发行规则](RELEASE.md)。

## 显式源文件回收

- Windows 源文件删除只用 IFileOperation 回收站能力，并用 PreDeleteItem veto 阻止永久删除；保留取消/失败/aborted诊断，不回退SHFileOperation永久删除或unlink。COM契约测试不替代 Windows BAT/桌面成品对本地盘、回收不可用磁盘和中文路径的真实验收。

- PostDeleteItem必须同时给出成功结果与非空回收站目标，且操作未aborted；不能只用队列提交成功或HRESULT报告可恢复。
