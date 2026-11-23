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
- localhost 服务启动后，即使用户没有点击“启动监控”，也必须后台执行一次 `STARTUP_SYNC`：比较当前 `watch_dir` 与 `processed_files.json`、缺失汇总或成本产物、或 `projection-manifest.json` 缺失 / `parser_versions` 落后当前解析器版本时自动增量重建普通汇总和成本三件套（保留手改覆盖；重建后稳态无变化周期仍不得重解析全目录）。该动作不能阻塞 `/` 和 `/api/v1/health`。
- 删除同步只允许删除投影记录和状态，不得删除源发票文件。
- `server_state.json`、`browser_launch.log`、`startup_preflight.log`、`monitor_status.json` 等只作为诊断文件，不是唯一运行真值。

## 关闭响应核对

- 页面只在返回 `ok=true`、`scheduled || idempotent` 且返回关闭行为与请求一致后接受关闭；不能仅凭请求已发出改变页面和 SSE 状态。

## 增量与远程来源约束（2026-11-19）

[WS-08/09 当前实现](../../SERVER_CONNECTION_AND_CACHE_DESIGN.md)采用原始解析缓存、完整清单核对及完整代际发布。完整枚举成功才允许将删除退出投影；掉线、权限失败和挂载消失均为未知，保留上次完整快照。缓存只存原始解析，纠偏和手改在副本上执行；普通/成本候选在来源及人工版本复核后一次切换 manifest，固定导出失败按回执恢复，不覆盖未知手改。

daemon 与手动 incremental/full/verify 共用发布流程，目录身份变化或迟到候选拒绝；无源变化仍检查公司身份依赖，到期刷新成本工作簿但不重提取原票。所有读取消费者须绑定完整代际，不得各读一个固定文件拼成快照；显式旧 CLI CSV 与资料夹索引仍是兼容文件契约。

SourceProfile 的任务与 TargetProfile/monitor 独立，每源一个、全局最多两个；网络操作在可终止 worker，不持有 API 状态锁。取消/断连使迟到提交失效，重启中断明确未知，提交先落盘再更新内存指针。来源缓存只在本机，不写服务器、不切换活动监控，也不创建第二个 daemon。标准 SFTP v3 只提供弱版本，不能声称远端原子快照；真实 SMB/SFTP/SSH Agent 仍须单独验收。

后续“不遍历重连”必须依据服务端可续接日志及 scope/journal 连续性；SMB 通知与标准 SFTP 不默认具备该保证。游标随完整代际共同提交，失效/断档显式回退核对，不以最后连接时间跳过变化；各模块共享一次来源同步，不各自再扫描。详见设计 §11。

## 公司销项缓存来源（2026-11-17）

所有 daemon、后台 spawn 与手动重建入口须与 API 传递相同公司开具映射。monitor 继续只沿用可匹配当前来源的缓存，不扫描开具目录；映射变化不允许继续使用旧全局/旧公司结果。手动重新汇总才重新读取同公司开具目录，链接/缺失不回退全局。
