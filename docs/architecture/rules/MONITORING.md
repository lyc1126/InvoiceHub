# 后台同步、监控与关闭规则

本页是 [AGENTS.md](../../../AGENTS.md) 按任务引用的强制功能规则；命中本专题时须在修改前完整读取。规则维护在本页，入口摘要不能替代正文。

- 适用问题：STARTUP_SYNC、monitor ready、漏同步、手改同步与关闭行为。
- 代码与验收定位：monitoring/、services/monitor_bridge.py；接口流程第 6.1—6.3、6.10 节、任务导航第 7—8 节。Python 模块目录（extraction/projections/monitoring/services/bookkeeping/runners/platform/release）相对 `src/invoice_hub/`，其余路径相对仓库根。
- 导航：[任务入口](../AGENT_TASK_MAP.md#task-monitor) · [架构总入口](../../DEVELOPMENT_ARCHITECTURE.md) · [文件地图](../FILE_MAP.md) · [接口与流程](../INTERFACES_AND_FLOWS.md) · [数据与算法](../DATA_AND_ALGORITHMS.md) · [设计原因](../COMMENT_RATIONALE_MAP.md)。

## 首次后台同步

- 启动必须快，但不能牺牲旧项目默认能力：localhost 首页先返回 200，首轮发票汇总、成本同步状态、OCR 探测和重诊断必须在后台自动开始；不能要求用户每次启动后手动点击“重新汇总”才看到当前目录发票。

## 持续监听规则

- 关闭浏览器不停止 localhost，也不停止监控。
- `停止一站式发票汇总系统.bat` 只停止 localhost；`停止一站式发票汇总系统并停止监控.bat` 才允许同时停止监控。
- 设置页“关闭本系统”必须默认每次询问“保留监控，仅关闭 WebUI / 关闭 WebUI，并停止监控”，允许勾选“记住本次选择”并在偏好中随时改回询问或切换固定行为；该页面能力不得改变两个正式停止 BAT 的固定语义。
- 普通页面顶栏的电源入口始终先显示确认弹窗，以已保存关闭偏好作为选项默认值；必须与设置共用控制器、归属保护和关闭协议。设置内已记住行为的直接执行语义保留，只有后端明确接受关闭后才停止 SSE 并显示关闭状态。
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

## 关闭响应核对

- 页面只在返回 `ok=true`、`scheduled || idempotent` 且返回关闭行为与请求一致后接受关闭；不能仅凭请求已发出改变页面和 SSE 状态。
