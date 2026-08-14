# 持续监听与日志规范

## 运行语义

- 关闭浏览器不停止 localhost 服务，也不停止发票监控。
- `停止一站式发票汇总系统.bat` 只停止 localhost。
- `停止一站式发票汇总系统并停止监控.bat` 先停止监控，再停止 localhost。
- 监控由独立 daemon 负责，FastAPI 只通过 `/api/v1/bridge/*` 控制生命周期。

## 路径真值

- 源发票目录：`watch_dir`
- 普通汇总：`workspace/发票汇总.csv`、`workspace/发票汇总.xlsx`
- 业务日志：`workspace/文件变化监控日志.txt`
- 停止标记：`workspace/.invoice_stop`
- 监控状态：`state_dir/.invoice_monitor.lock`、`state_dir/monitor_status.json`、`state_dir/processed_files.json`
- 手改状态：`state_dir/manual_overrides.json`
- 成本产物：`watch_dir/成本发票明细.csv`、`watch_dir/成本发票汇总.xlsx`、`watch_dir/成本开票状态.json`

## 同步策略

- `STARTUP_SYNC`：监控启动后校验一次。
- `EVENT_SYNC`：`.pdf/.ofd/.xml` 新增、修改、移动或删除后，1 秒 debounce 合并处理。
- `PERIODIC_SYNC`：默认每 60 秒只比较路径、mtime、size；无变化不重建。
- `MANUAL_EDIT_SYNC`：监听 `发票汇总.xlsx`，只接受 `销售方/开票金额/发票号码` 三字段手改。

## 日志动作

- 监控生命周期：`MONITOR_STARTED`、`WATCHDOG_STARTED`、`MONITOR_STOPPING`、`MONITOR_STOPPED`
- 同步：`STARTUP_SYNC`、`EVENT_SYNC`、`PERIODIC_SYNC`、`SYNC_FAILED`
- 手改：`MANUAL_EDIT_DETECTED`、`MANUAL_SYNC_GUARD_PASS`、`MANUAL_SYNC_GUARD_BLOCK`、`MANUAL_EDIT_AUTO_SYNC`、`MANUAL_EDIT_APPLIED`
- 状态：`STALE_LOCK_CLEANED`、`PROCESSED_REBUILT`
- 通知：`NOTIFY_ATTEMPT`、`NOTIFY_SENT`、`NOTIFY_FALLBACK`、`NOTIFY_FAIL`、`NOTIFY_SKIP`

## 排障顺序

1. `/api/v1/bridge/status`
2. `state_dir/.invoice_monitor.lock`
3. `state_dir/monitor_status.json`
4. `workspace/文件变化监控日志.txt`
5. `state_dir/bridge_stdout.log`
6. `state_dir/bridge_stderr.log`
