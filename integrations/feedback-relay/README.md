# 独立反馈中转服务

这不是 InvoiceHub 云端业务服务。它只接收用户明确同意公开的反馈，调用固定仓库 `lyc1126/InvoiceHub` 的 GitHub Issue 接口；不接收源发票、配置、日志、附件或联系方式，不随桌面程序启动。

当前状态：代码与合成验收，**尚未部署**。不要在客户端、前端构建、默认配置或公开仓库放 GitHub 凭据。完整流程、失败恢复与验收见 [反馈设计](../../docs/FEEDBACK_DESIGN.md)。

## 部署

在独立 Python 3.14 环境安装本目录 `requirements.txt`。凭据由服务器的 secret manager 或服务管理器注入，不写进命令历史、仓库 `.env` 或日志。

必需的服务端环境变量：

| 变量 | 含义 |
| --- | --- |
| `FEEDBACK_GITHUB_TOKEN` | 仅目标仓库 Issues 写权限的服务端令牌，维护者负责有效期、轮换和撤销 |
| `FEEDBACK_RATE_SECRET` | 至少 32 字节的随机字符串，用来对限流来源做 HMAC |
| `FEEDBACK_DB_PATH` | 仓库、发布包之外的私有持久目录中 SQLite 文件的绝对路径 |

从本目录运行：

```sh
python -m uvicorn relay:app --host 127.0.0.1 --port 8098 --no-access-log
```

前置 HTTPS 反向代理；代理限制请求体为 32 KiB，禁记正文、`X-Feedback-Receipt`、Authorization 和请求头，设置请求超时。仅信任实际反向代理的转发来源，正确配置 Uvicorn 的受信代理地址，不能直接信任任意 `X-Forwarded-For`。入口不需要 CORS。`GET /health` 仅在服务端必需配置齐全后返回就绪；它不检查 GitHub 令牌是否过期或有权限。

客户端后端运行环境设置 `INVOICE_HUB_FEEDBACK_URL=https://feedback.example.com`（示例地址必须替换）并重新启动；不把该变量指向 GitHub API，不把任何写令牌发给客户端。未配置时按钮可以打开表单与复制内容，但不能在线提交。

上线前要在中国大陆实际网络验证域名、HTTPS、提交、查询和服务器到 GitHub 的连通性；服务器放在哪个平台并不构成可用性保证。首版有每来源小时限额和 UTC 全局日限额，仍须观察滥用；遭攻击时先撤销令牌/停止入口，再评估验证码或审核队列。

中转 SQLite 不存正文，只存反馈 UUID、正文 hash、回执 hash、状态、Issue 编号、时间与来源 HMAC。数据库须持久化、备份、限制文件权限；不能随容器重建清空。`sending/unknown` 记录不能当作未发送而删除重试。未知结果需由维护者按 Issue 正文中的 `invoicehub-feedback:<UUID>` 标记在 GitHub 人工核对；确认前不重发。只在可证明不存在外部副作用后处理失败记录。
