# 应用内建议与反馈

## 1. 范围与当前状态

2026-11-19 用户确认：在设置 › 关于的“更新日志”右侧加“建议与反馈”，软件内填写，经独立中转创建 GitHub Issue；沿现有工作区开发线实现，**本轮只做代码与本机验收，不部署**。同页包类型、Package ID、核心 Build ID、API 契约收进默认关闭的“技术详情”，平台与架构继续直接显示。

这是独立、可选的产品反馈渠道，不把发票应用改成云服务，不增加多用户/云端票据能力。源码开发不代表稳定 main 或已发布成品具备本功能。中转服务部署说明见 [独立服务](../integrations/feedback-relay/README.md)。

## 2. 交互

“建议与反馈”打开 Vue `FeedbackDialog` / `WsModal`，保留所在设置页和草稿。独立经典页进入 `/workspace/settings?feedback=1#about`；嵌入设置页通过已有同源、frame、view token 校验的 navigate 通道请求外壳对话框。恢复参数继续传递，不向 iframe 嵌套新的工作区。

表单有类型（问题 / 建议 / 其他）、标题（1—120 字）、描述（1—6000 字）。不增加上传或联系方式字段。软件版本、平台、架构、包类型由本机 About 的严格白名单生成，默认不附带，勾选后预览。提交人必须明确勾选不含敏感信息并同意公开；按钮写“确认公开并提交”。公开确认不能替代维护者对用户误填敏感内容的处理。

正文及环境只在显式提交时发送；打开关于页、打开反馈弹窗、GET 本地反馈配置均不联网。任意用户文字以文本渲染。草稿只保存在该窗口内存；关闭再开保留，退出/完整刷新会丢失未发送文字。可以主动复制；复制失败保留可选中的预览文本。未配置中转或配置无效时明确提示尚未开通，禁用在线提交，仍可填写和复制。

提交成功必须有中转确认的 GitHub 正整数 Issue 编号。显示反馈编号和可选 GitHub 链接，国内用户可以只看软件内的确认结果。打开 Issue 链接仍需用户能访问 GitHub，不把“已打开网页”当“已提交”。

## 3. 本机接口与状态

| 接口 | 行为 |
| --- | --- |
| `GET /api/v1/feedback` | 本地返回 enabled/message/environment/pending；无远程 I/O |
| `POST /api/v1/feedback` | 同源校验、有界 JSON、类型/长度/公开确认校验；先持久化意图再单次 POST 中转 |
| `GET /api/v1/feedback/{request_id}` | 已知终态直接读本地；未知时只 GET 原中转回执，绝不重发 |

POST 字段为 `request_id/kind/title/description/include_environment/public_consent`，多余字段拒绝。客户端不能指定中转地址、仓库、GitHub 令牌或任意环境对象。中转地址仅由后端 `INVOICE_HUB_FEEDBACK_URL` 提供，必须为无凭据、无 query/fragment 的公网 HTTPS；该环境变量属于部署者受信配置，不是用户可提交的通用代理。禁止重定向，限制响应大小和等待时间；DNS 卡住时每服务实例最多一个后台网络线程，已有线程未结束不增开。

`runtime/local_state/feedback.sqlite3` 的 `feedback_jobs` 只存 id、提交 fingerprint、查询 receipt、state、number、created、原 relay；不存正文、标题、发票、配置或日志。该数据库是任务/回执，不是发票主存储。首次真正提交才创建。receipt 只在本机后端与原中转之间传递，不返回浏览器，不写日志或公开源码。

状态为 `sending → submitted|rejected|unknown`；sending 对 UI 等同 unknown。提交指纹相同且已成功时返回原结果；存在未知任务时返回该任务而不新发；相同 ID 不同内容拒绝。数据库 `BEGIN IMMEDIATE` 序列化跨线程/进程的意图预留。退出/重启后 GET 配置能找回未确认任务并锁定新写入。不可确认的结果不默认当成未发送。

只有 submitted/rejected 为确定终态；网络中断、超时、坏响应、5xx、查不到中转回执保留 unknown。用户只能查询原编号，不能自动重放。查询绑定原服务地址，即使配置换地址也不把旧 receipt 发送给新地址。更换/停用旧服务前需处理未确认回执。

## 4. 独立中转

服务位于 `integrations/feedback-relay/`，可放在能由目标用户访问且能连接 GitHub 的独立服务器。产品不绑定国内外某家平台，不承诺平台或域名的中国大陆连通性；上线前需实网验证。没有创建平台账号、发布服务、配置真实域名或真实 Issue。

中转 `POST /feedback` / `GET /feedback/{request_id}` 使用 256 位随机查询 receipt；DB 只存其 SHA-256。仓库固定 `lyc1126/InvoiceHub`，GitHub 写令牌仅在服务器 secret，调用固定 GitHub API，不跟随重定向。未配置令牌/限流 secret/私有绝对 DB 路径时 fail closed。服务无浏览器 CORS；本机后端负责 HTTPS 请求。

SQLite `submissions` 在任何 GitHub 写入前预留 ID、payload hash、回执 hash、状态、时间与来源 HMAC。重复 ID 相同内容与回执返回已有状态；冲突 409，未知不自动重发。数据库必须持久化和私有备份，禁止按“启动临时数据”清空。

首版默认每来源每小时 5 条（来源 HMAC 每 UTC 日换代，跨日重新计数）、全局 UTC 每日最多 50 条；SQLite 事务保护多进程配额。来源用受信反向代理解析后的 client IP 做 HMAC，不存原 IP，不直接读任意转发头。GitHub 标题/正文的 @ 提及加零宽分隔，避免匿名反馈直接通知任意用户。限流不是完整反滥用机制；上线规模增加时加验证码、审核或队列，见待办。

GitHub 并发请求有界，成功/确定拒绝持久化；原调用超时后后台收到的成功仍保存，可用同一 receipt 查询。进程在写 GitHub 后、写确认前崩溃则结果未知，维护者按 Issue 正文 UUID 标记人工核对，未确认前不能重发。没有自动重试后台队列，也没有自动恢复未知外部写入。

## 5. 验收与后续

`tests/test_feedback.py` 覆盖应用—中转协议、隐私白名单、缺配置、正文限制、同源、公开确认、重复/并发、断线/重启回执、限流、未知不重发；`frontend/tests/feedback.spec.ts` 覆盖表单、草稿、预览、未知只查询和失败恢复。真实浏览器用隔离合成配置及模拟 GitHub 上游，检查关于位置/折叠/弹窗、浅深/390/no_skin、控制台和相邻入口。正式 Windows BAT、原生前台/浏览器/选择器、Tauri 成品、真实默认配置、真实 GitHub 与公网中转另验。

后续部署、实网/真实 Issue 验收、令牌轮换、滥用防护和状态保留治理见 [FEEDBACK-01](PRODUCT_BACKLOG.md#feedback-01)。正式上线前应补充隐私说明和维护者撤稿/敏感信息处理流程，不能把本机合成验收当作服务已开通。
