<div align="center">

<img src="src-tauri/icons/icon.png" alt="InvoiceHub hi. 图标" width="96" />

# InvoiceHub

### 多公司发票、成本、勾稽与凭证，一处整理。

把散落的 PDF、OFD、XML、银行流水与公司资料夹，变成看得清、找得到、对得上的账前与做账资料。

[![当前版本](https://img.shields.io/badge/version-v1.0.0-d5ff5f?style=flat-square&labelColor=252820)](https://github.com/lyc1126/InvoiceHub/releases)
[![平台](https://img.shields.io/badge/platform-Windows_x64_%7C_macOS_ARM64-f8f9f5?style=flat-square&labelColor=252820)](https://github.com/lyc1126/InvoiceHub/releases)
[![Tauri](https://img.shields.io/badge/built_with-Tauri_2-ff8b70?style=flat-square&labelColor=252820)](src-tauri/README.md)
[![许可](https://img.shields.io/badge/license-AGPL--3.0--or--later-d5ff5f?style=flat-square&labelColor=252820)](LICENSE)

**[查看 Releases 下载](https://github.com/lyc1126/InvoiceHub/releases) · [使用指南](docs/USER_GUIDE.md) · [产品介绍](website/README.md) · [更新记录](CHANGELOG.md)**

</div>

---

月底对票、算成本、理流水、做凭证，不该从一张张打开文件、来回抄数字开始。

InvoiceHub 是一个开源的本地优先多公司发票与账前工作台。登记公司资料夹或选定监控目录后，发票识别、同票去重汇总、四维勾稽核对、成本分析 V2、自适应出入库单、通用凭证草稿导出以及按需 PaddleOCR 识别都可以在同一个工作台内完成；开启独立监控后，新放进来的发票会持续后台增量同步。

**源文件始终留在自己的电脑里，整理出来的结果随时拿得走。**

<p align="center">
  <img src="docs/screenshots/invoicehub-home.png" alt="InvoiceHub 当前运行版本的发票汇总首页" width="100%" />
  <br />
  <sub>运行版本实拍：默认空目录；本机路径仅在截图会话中脱敏，未添加演示发票。</sub>
</p>

## 从收票，到核对与出表

| 这一步 | InvoiceHub 能帮你做什么 |
|---|---|
| **把多公司资料理顺** | Vue 3 多公司工作区支持登记已有资料夹或新建标准六类文件夹；按公司独立保存档案、发票标签与项目归属，并支持只读挂载服务器目录（SMB / SFTP 试验版，不写入远端）。 |
| **把票收齐、找准** | 读取 PDF、OFD、XML，同票多格式按 20 位发票号码家族核对与去重合计；内置 Java 21 / OFD 原票预览与 PDF 批量打印；扫描件与社保截图可在「OCR」页按需接入 PaddleOCR 官方 API 或自建服务。 |
| **把成本与勾稽算清** | 成本工作台 V2 区分货物与服务双路径、支持公司纳税人身份时间线、开票参考与已开快照；提供进销存、往来、抵扣与跨目录同号检查四维勾稽。 |
| **把单据与凭证交出去** | 导出汇总表、自适应扩行出入库单；基于发票、银行流水与工资社保生成凭证草稿，人工审核后默认导出软件无关的「通用凭证表（标准）」（支持无损读回，同时兼容品牌与自定义模板）。 |
| **把重复活交给后台** | 独立监控 daemon 增量同步新增/修改/删除记录，不删除源发票并保护手改字段；完整代际与缓存自动容量治理，固定端口冲突提供引导式优雅恢复。 |

<details>
<summary><b>再看看成本分析和外观设置</b></summary>

### 成本有明细，开票有参考

<img src="docs/screenshots/invoicehub-costs.png" alt="成本分析页面：明细、项目规格汇总、开票参考与发票校验" width="100%" />

### 常用的工具，也可以有喜欢的样子

四款内置图标，浅色、深色与可切换皮肤。外观可以换，表格、复制和导出照常用。

<img src="docs/screenshots/invoicehub-appearance.png" alt="当前版本的应用图标与皮肤管理页面" width="100%" />

以上截图均来自同一运行版本；数据状态保持原样，目录与日志路径已隐藏。拍摄说明见[截图来源](docs/screenshots/README.md)。

</details>

## 下载后，从一个文件夹开始

| 平台 | 下载 | 开始使用 |
|---|---|---|
| Windows 10/11 x64 | **[便携工具包 ZIP](https://github.com/lyc1126/InvoiceHub/releases/download/v0.3.0-alpha.2-opt.1/InvoiceHub-v0.3.0-alpha.2-windows-x64-portable.zip)** | 解压到新目录，运行其中的 InvoiceHub 程序。 |
| macOS 13+ · Apple Silicon | **[预览版 DMG](https://github.com/lyc1126/InvoiceHub/releases/download/v0.3.0-alpha.2-opt.1/InvoiceHub-v0.3.0-alpha.2-macos-arm64-preview.dmg)** | 打开 DMG，将 App 拖到 Applications 后启动。 |

1. **添加公司或选目录。** 首次打开工作区按三步引导登记已有公司资料夹（或新建标准六类文件夹），也可直接为经典首页选定监控目录。
2. **自动同步与汇总。** 设为监控目录后后台自动增量解析与汇总；需要立即刷新时点击“重新汇总”。
3. **核对、分析与导出。** 在工作区完成筛选、原票预览、成本分析 V2、四维勾稽、出入库单与通用凭证草稿导出。
4. **按需扩展。** 如需扫描发票或社保截图识别，可在「OCR」页配置 PaddleOCR 官方 API（需显式同意与按公司授权）或自建服务；如需只读查看共享目录，可连接 SMB / SFTP 服务器来源。

桌面窗口和系统浏览器都能使用，在设置中选择启动方式，完整退出后下次生效。关掉桌面窗口只是隐藏；关闭系统时，可以选择是否保留监控。[完整操作说明 →](docs/USER_GUIDE.md)

> 已包含启动响应完整性检查、固定端口冲突引导恢复、分阶段诊断和 Windows 浏览器兜底。遇到启动问题时，可查看[启动排障说明](docs/STARTUP_TROUBLESHOOTING.md)。

> 当前源码主线与发布候选版本为 **`1.0.0`（`UPDATE_CHANNEL = "stable"`）**，历史公开预览包 `v0.3.0-alpha.2-opt.1` 保留在 Releases。Windows 包未签名；Mac 预览包使用 ad-hoc 签名，未经 Apple 公证，首次打开可能需要系统确认。校验和、构建收据及具体已测/未测范围均以 [Releases](https://github.com/lyc1126/InvoiceHub/releases) 为准。

## 表格可以重建，原票始终保留

- **本地优先。** 核心发票识别、汇总、勾稽、成本与凭证生成均在本机完成；更新检查、另行配置的 PaddleOCR API 是显式授权的独立联网行为。
- **不猜金额。** 缺少可靠证据就留空，发现冲突就提示核对。手工修订的字段会受到保护。
- **结果可带走。** 普通汇总、成本资料与通用凭证导出使用标准 CSV、XLSX、JSON；SQLite 只保存任务、事件、设置和缓存，不作为发票主存储。
- **删除与缓存有边界。** 自动同步只调整投影与状态，不删除源发票；勾选删除走系统回收站；历史代际、解析缓存与服务器只读副本均有界自动回收。

## 一起把它做得更顺手

遇到某种票面识别不对，或一条操作总要多点几次，可在软件内「设置 › 关于 › 建议与反馈」一键复制脱敏版本环境后[前往 GitHub 提交 Issue](https://github.com/lyc1126/InvoiceHub/issues/new)。描述复现步骤即可；请不要公开真实发票、公司资料或凭据。

项目采用 **[AGPL-3.0-or-later](LICENSE)** 许可证。[贡献指南](CONTRIBUTING.md) · [行为准则](CODE_OF_CONDUCT.md) · [安全问题](SECURITY.md)

<details>
<summary><b>开发者文档与源码运行</b></summary>

**首页维护约定：** 仅在大型产品内容更新后，定点修改与更新直接相关的部分。日常修复、性能优化和构建验收记录写入 [CHANGELOG](CHANGELOG.md) 与 [Releases](https://github.com/lyc1126/InvoiceHub/releases)，不反复改写首页整体布局、文案和截图。

alpha.2 优化版 1 已内置对应平台的 Java 21/OFD 原票预览组件，按真实页面树输出 PNG，并在组件未变化时复用校验结果。源码开发首次构建运行 `python scripts/dev/build_ofd_preview.py --fetch`；构建、体积及验收范围见 [OFD 预览说明](docs/OFD_PREVIEW.md)。

- [开发架构总入口](docs/DEVELOPMENT_ARCHITECTURE.md) · [Agent 任务导航](docs/architecture/AGENT_TASK_MAP.md)
- [文件地图](docs/architecture/FILE_MAP.md) · [接口与流程](docs/architecture/INTERFACES_AND_FLOWS.md) · [数据与算法](docs/architecture/DATA_AND_ALGORITHMS.md)
- [实现状态](IMPLEMENTATION_STATUS.md) · [迁移清单](docs/MIGRATION_GAP_CHECKLIST.md) · [平台工作流](docs/MAC_WINDOWS_WORKFLOW.md)
- [监控与日志](docs/MONITORING_AND_LOGGING.md) · [项目约束](AGENTS.md)

Windows 源码开发：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\启动一站式发票汇总系统.bat -Development
```

默认服务地址为 `http://127.0.0.1:8766/`。Tauri 工具链诊断：

```powershell
.\scripts\dev\tauri-doctor.ps1 --require-ready
.\scripts\dev\tauri-bootstrap.ps1
```

桌面壳开发说明见 [src-tauri](src-tauri/README.md)。

更新协议的工程状态：L10-D 已把这些边界接入 Host RPC/updater/startup restore，响应 flush 后才进入私有 commit，失败保持 `CommitLost` 诊断。L10-E 是不安装更新的隔离恢复样本，记录 `update_requests=0`；`internal-alpha` 也不代表正式更新验收。本预览禁用宿主自动安装更新，未发布更新 Feed。

</details>

## 接下来（`v1.1+` 路线）

当前核心工作区、成本 V2、通用凭证导出与按需 PaddleOCR 接入已就绪，下一阶段重点推进：

- **税务政策引擎（D0—D5）。** 当前工作区已支持公司税费记录与显式假设的手工测算；完整法规与多税种申报口径将在后续版本逐步复核接入。
- **只读服务器来源深化。** 当前支持 SMB 与 SFTP（SSH Agent 试验版）独立只读浏览与汇总；后续按需评估密码/钥匙串凭据及跨模块接入。
- **外部 Agent / MCP 扩展与更多账套模板。** 在严格脱敏与人工确认边界下，按真实样本补充更多记账软件官方导入模板，并规划 `v1.2+` 的只读外部协议接口。
