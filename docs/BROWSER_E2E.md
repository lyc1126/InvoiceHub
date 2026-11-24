# 合成浏览器回归（ENG-05）

本入口用真实 FastAPI、真实 Chromium 和仓库页面验证交互。每次运行新建合成发票、公司、配置与工作区，不读取本机默认配置、不启动 monitor daemon、不操作真实账套。Linux 仅为 CI 环境，不增加产品发行平台。业务、Windows BAT、正式入口前台拉起、原生选择器和 Tauri/成品验收仍按[迁移清单](MIGRATION_GAP_CHECKLIST.md#cost-v2-delivery)分别执行。

导航：[任务入口](architecture/AGENT_TASK_MAP.md#task-browser-e2e) · [页面规则](architecture/rules/WEB_UI.md) · [文件地图](architecture/FILE_MAP.md) · [架构入口](DEVELOPMENT_ARCHITECTURE.md)。

## 安装与运行

后端使用项目 Python 3.14 虚拟环境，或通过 `PYTHON` 指定已安装运行依赖的解释器。Node 24、pnpm 版本与前端依赖分别由工作流、`frontend/package.json` 和 `frontend/pnpm-lock.yaml` 固定；Playwright 为精确开发依赖，默认启动它配套的 Chromium。

在仓库根目录执行：

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend run build
pnpm --dir frontend run test:e2e --repeat 3 --verify-refresh-guard
```

macOS 默认 Python 为 `.venv/bin/python`，Windows 为 `.venv/Scripts/python.exe`。使用系统 Python 的 CI 设置 `PYTHON=python`。Linux CI 安装 `requirements/browser-linux-x64-py314.lock`（仅 CI；相同运行依赖版本、对应 Linux x64 二进制哈希），并运行 `playwright install --with-deps chromium`；不复用 Mac/Windows 轮子哈希，也不将这份锁用于发行包。[Playwright 官方 CI 说明](https://playwright.dev/docs/ci)

`--suite workspace|costs|classic` 可单独运行，逗号可组合，缺省 all；`--repeat` 为 1—5 次，每次重新创建资料与浏览器上下文。任何一次失败立即阻断，重复运行不充当失败重试。`--output` 相对仓库根解析，默认 `output/playwright/`（ignored）。

## 覆盖范围

| 场景 | 实际验证 |
|---|---|
| workspace | P3 银行映射确认、余额断链禁存、凭证结构保存后重读、未签署税费保持待复核、浅深/390px/no_skin。 |
| costs | 服务归类与成本、服务毛利及证据、报价→真实归档后丢响应→按原 ID 查询→下载冻结 XLSX；只有一次归档 PUT，核对实际构建资源。 |
| classic | 104 条记录/103 张同票家族、100 行分页与跨页全选、三项合计、SSE 后行对象/焦点/内部滚动/未保存目录草稿、单次读取失败与恢复、迟到筛选不覆盖新结果、空态与重置、默认/深色/两款经典皮肤/390px/no_skin。 |
| refresh-mutation | 仅在开发夹具返回的 JS 中恢复整表重绘；必须到达 `CLASSIC_LOCAL_REFRESH_LOST` 浏览器断言并失败。依赖缺失、启动失败或其它断言失败均不能算检出。生产资源不修改。 |

故障在开发夹具中注入，业务请求不使用 HTTP mock。夹具控制路由仅在这些脚本创建的临时 app 注册，生产 API 没有控制或故障入口。经典首页回归允许恰好一次列表 503，成本允许恰好一次归档 503；其余页面错误/HTTP 错误阻断。

## 浏览器选择与诊断

`BROWSER_E2E_BROWSER=chrome` 可使用已安装 Chrome。`BROWSER_E2E_CDP` 连接已有 Chrome；仅关闭本次上下文，保留其它标签。原脚本的 `P3_E2E_*`、`COST_V2_E2E_*` 和首页的 `CLASSIC_E2E_*` 可分别覆盖 `BROWSER/CDP/HEADED/OUTPUT`。`PLAYWRIGHT_MODULE` 可指向其它已安装模块，覆盖运行必须注明版本，不能冒充锁定 Chromium 的验收。

每个场景保存 `result.json`、截图、`trace.zip`、`backend.log` 和启动日志；失败另存 `failure.png` 与 `failure.txt`，总入口写 `summary.json`。CI 保存这些合成诊断 7 天。查看 trace：

```bash
pnpm --dir frontend exec playwright show-trace ../output/playwright/run-1/classic/trace.zip
```

关闭上下文先释放 SSE，再停止夹具并有界等待，必要时结束本次子进程；合成资料根由父进程持有并清理，强制结束夹具不遗留发票投影。输出目录供诊断，开发任务收尾须清理；不得把真实资料放入该目录或上传为 CI artifact。浏览器配套关系见[官方浏览器说明](https://playwright.dev/docs/browsers)。

## 验收边界

本机连续运行与故障检出只证明本机代码和该浏览器。工作流接线不等于 GitHub Linux 作业已经运行；必须在获准推送后查实际 CI 结果，连续通过才能关闭 ENG-05 的远端稳定性验收。合成数据不增加三轮真实资料清单的勾选数，真实默认配置的源码资源核对也不替代正式平台成品验收。
