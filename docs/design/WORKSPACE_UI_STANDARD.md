# 工作区前端设计标准（硬性要求）

2026-11-16 用户确认：工作区前端的设计、风格以 [工作区原型](workspace-sidebar-prototype.html) 为唯一视觉真值；**此后所有新增 / 修改的前端（`frontend/` Vue 与嵌入经典页的 `workspace-embed.css`）必须按本标准开发**。本标准是 [页面规则](../architecture/rules/WEB_UI.md) 的强制附件；与原型冲突时以原型为准并同步修订本文，与业务规则冲突时先停下请用户确认，不得自行取舍。

实现基线：`frontend/src/prototype.css`（工作区组件与变量）、`frontend/src/styles.css`（基础层）、`web/static/css/workspace-embed.css`（嵌入经典页）、`frontend/src/components/WsModal.vue`（对话框）、`frontend/src/toast.ts`（提示条）。新组件优先复用这些类与组件，不另起一套。

## 1. 设计令牌

| 令牌 | 浅色（原型值） | 深色 `website-dark` | 用途 |
|---|---|---|---|
| `--bg` | `#f8f9f5` | 皮肤值 | 内容区底色 |
| `--surface` | `#fff` | 皮肤值 | 卡片、表格、输入、对话框 |
| `--surface-2` | `#f3f5ef` | 皮肤值 | 侧栏、表头、提示条、空态 |
| `--line` / `--line-strong` | `#dfe2d7` / `#b9bfb1` | 皮肤值 / `#4b4f43` | 分隔线 / 控件边框 |
| `--text` / `--muted` | `#242520` / `#686b60` | 皮肤值 | 正文 / 次要文字 |
| `--primary`（lime） | `#d9fb5c` | 皮肤值 | 选中态底色、计数、强调 |
| `--ws-lime-deep` | `#9bb52a` | `--primary` | 关键指标左线、选中竖条 |
| `--ws-selected` / `--ws-active-line` | lime 16% / `#becba7` | `#353c25` / `#586a33` | 选中行底色 / 边线 |
| `--green` / `--amber` / `--red` | `#15803d` / `#b7791f` / `#b42318` | 皮肤值 | 成功 / 警示 / 危险 |
| `--ws-primary-bg` / `--ws-primary-ink` | 墨 `#242520` / lime | lime / 墨 | 主按钮 |
| `--ws-inverse-bg` / `--ws-inverse-ink` | 墨 / 纸色 | `#30352a` / 正文 | 底部操作条、提示条 |
| `--ws-modal-scrim` | `#1b211d66` | `--ws-scrim` | 对话框遮罩 |

- 禁止写死白底、黑字或任何新色值；需要新语义色时先在 `prototype.css` 增加变量并给出浅 / 深两值。
- 深色**不反色**：浅色的墨色填充（主按钮、操作条）在深色改用 lime / 抬升面，不能变成近白块；源票面、单据图像永不反色。

## 2. 字体与排版

- 字体：`"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif`，基准 14px / 1.5；品牌 `hi.` 用 `HubDisplay`。
- 页标题 h2 24px/700；区块标题 h3 16px/700；区块说明 13px 次要色；对话框标题 16px。
- 路径、发票号、凭证号等标识用等宽 `Consolas,"SFMono-Regular",monospace` 12.5px。
- 表格 13px；表头 13px/600 正文色、`--surface-2` 底、`8px 12px` 内距；数字列右对齐 `tabular-nums`。
- 指标（KPI）数值 21px/700，标签与注释 12.5px 次要色；≥1 万显示“xx.xx 万”（仅显示格式，悬停给精确值）。
- 圆角：控件 / 卡片 4px，菜单 / 弹层 / 操作条 6–8px，胶囊 999px；不得使用更大圆角。

## 3. 布局

- 外壳：72px 模块列 + 侧栏（默认 292px，可拖 220–460px）+ 内容区；内容区内距 `20px 24px 48px`，窄屏 16px。
- 模块列：选中项 lime 底 + 700；“临时识别”是工具按钮，打开对话框，**永不显示选中态**；成本分析、设置前有 32×1px 分隔线。
- 页头（`.detail-header--split` / `.module-context--tools`）：左侧面包屑 13px → h2 → 等宽路径；右侧工具（期间、状态、主操作）与页头**底边对齐**。
- 区块：上边线 + `16px 0` 内距（`.overview-section` / `.panel`），区块头左标题说明、右操作。
- 侧栏树行：1px 透明边 + 6px 内距 + 18px 箭头列 + 7px 间距；⋯ 按钮仅悬停 / 聚焦时出现并让出角色标签位置；“置顶”分组常驻，空时显示提示。

## 4. 组件规范（类名为现行实现）

| 组件 | 规范 | 实现 |
|---|---|---|
| 按钮 | 36px 高、`0 14px`、1px `--line-strong`、4px；悬停边框变墨色；按下下移 1px；主按钮墨底 lime 字；危险确认红底白字；ghost 次要色；小号 30px/13px | `button` / `.primary` / `.ghost` / `.danger-fill` |
| 分段切换 | 外框 1px，选中 lime 底 700；用于期间、视图、来源切换 | `.period-segment` |
| 标签页 | 下划线式：透明底、次要色，选中正文色 700 + 2px 墨色下划线；**不得做成填充方块** | `.tabs` |
| 首页标签 | 顶部文件夹式标签，只属于首页，可全部关闭 | `.ws-tab` |
| 提示条 | 左 3px 边 + `--surface-2` 底 + 12.5px；警示用琥珀；不要用 flex 拆开行内粗体 | `.overview-notice(--warn)` |
| 状态 | 胶囊：成功绿、警示琥珀、危险红、中性灰；监控状态用 `.status-chip`，只能说“当前监控目录”，不得暗示 daemon 运行 | `.tag.pill-ok/.pill-warn/.tag--danger` |
| 指标 | 左 2px 线（关键项 lime-deep）、标签 / 数值 / 注释三行 | `.overview-kpi` |
| 表格 | 真实 `<table>`、1px 外框 4px、表头见上、行悬停浅 lime；单元格不折行时外层横向滚动；保留 TSV 复制 | `.grid` |
| 空态 | 虚线卡片：标题 15px/700 + 说明 + 可选小号主按钮；整页空态用居中大图标 46px | `.empty-state` / `.module-empty` |
| 对话框 | 640px（宽 1100px）、6px、阴影 `0 24px 70px #0004`、标题栏 + ×、正文 18px 内距最高 70vh；Esc / × 关闭；锁 html+body 滚动；返回焦点 | `WsModal` |
| 抽屉 | 右侧 560px（宽 780px）、左边线 + 阴影，用于预览与明细 | `.compare-drawer` / `.source-preview` |
| 底部操作条 | 墨色条（深色抬升面）、8px 圆角、lime 计数、合计框可点开明细、无框图标按钮、右端“全选筛选结果”与 × | `.selection-bar` / 成本 `.cost-action-bar` |
| 提示条（toast） | 底部居中墨底白字 13px，2.4 秒自动消失；只用于成功 / 中性反馈，需要用户处理的错误留在页内横幅 | `toast()` |
| 年月选择 | 264px 弹层、4 列、当前月 lime 700、有数据的月份右上 5px 绿点、底部“本月” | `MonthPicker` |
| 信息提示 | 17px 圆形 `i`，悬停 / 聚焦显示说明；浮层须按视口测量夹取 | `.info` |
| 筛选栏 | 标签 12.5px 在上、控件 36px 高、最小 150px，底边对齐 | `.filters .field` |

## 5. 交互与状态

- 悬停、聚焦（3px `#e96c51` 外框）、按下、禁用（45% 透明，无等待光标）、处理中（`aria-busy` + 文案“…中”）五态必须齐全；普通禁用不得显示加载光标。
- 动效：进入 0.16s 上浮淡入；尊重 `prefers-reduced-motion`。
- 新增“打开一件事来做”的流程（向导、确认、导出、识别）一律用 `WsModal`，不得新开首页标签或整页；确认响应未知时只查询结果、不自动重放。
- 反馈分层：成功 → toast；可恢复错误 → 页内横幅 + 显式重试；危险操作 → 对话框二次确认。
- 所有金额、合计、统计只显示后端返回值；页面只做格式化（分组、万、百分比），不得自算。

## 6. 深色、窄屏与无障碍

- 每个新界面必须同时验收浅色、`website-dark` 与 `?no_skin=1`；深色下不得出现裸按钮方框、近白块或不可辨的选中态。
- 390px：模块列变横排（分隔线改竖线）、侧栏为抽屉、指标 2 列、表格横向滚动、对话框 92vw。
- 对话框 `role=dialog aria-modal`，菜单 `role=menu`，状态区 `role=status`；所有图标按钮带 `aria-label`。

## 7. 验收清单（每个前端改动）

1. 与原型同页面在 1440×900 截图并排比对，关键元素用计算样式核对字号、字重、内距、颜色。
2. 浅色 / 深色 / 390px 截图；控制台无错误。
3. `pnpm run typecheck`、`pnpm test`、`pnpm run build`、`tests/test_workspace_frontend.py`；改嵌入样式时递增 `workspace-embed.css?v=` 并更新契约测试。
4. 新组件或新令牌回写本文。

## P2 组件接入（2026-11-17）

成本V2（2026-11-21 后续）：`CostItemTypes.vue` 复用宽 WsModal/field/grid/actions 展示类型变更预览；`CostAnalysis.vue` 的服务项目毛利和价格证据复用现有 grid、details 与警告/待核对状态。没有新增视觉令牌；390px只在表格容器内横向滚动，数据来源与未知值完全由后端给出。

`BankLayouts.vue` 复用宽 WsModal，按原型 `openMapping` 布局：一张表内每列表头上方一个下拉 + 来源小签（`.chip--ok` 表头词典命中 / 已确认版式 / 手动指定，`.chip--warn` 方向由余额链确认 / 未使用），下方原始列名与至多五行样例；方向判定用 `.checkline`（成立绿、不成立红），`save_blockers` 逐条红色 checkline 并禁存。三类样式在组件内以共享令牌重建，不写原型硬编码色值。2026-11-17 起：`WsModal` 传送到 `<body>`，凡 `#app` 前缀的按钮规则须同时写 `.ws-modal` 选择器，否则弹窗主按钮退化为普通按钮。`CompanyTax.vue` 复用总览指标、表格与宽编辑弹窗，null 显示“未测算 / 未录入”、零显示 0.00，显式标明手工假设和覆盖期间；做账“税费”表按原型 `bkTax` 一行一税种、点击行展开“怎么算的”，状态胶囊只按后端字段是否为空命名（已缴 / 已申报待缴 / 待申报 / 规则待复核 / 缺资料），不推算金额。`InvoiceTagsEditor.vue` 增右对齐“使用中”列与资料不可用提示，原型令牌继续共用。
