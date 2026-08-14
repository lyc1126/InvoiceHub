# 更新体系开发说明

## 当前状态

公开仓库尚未发布二进制或更新 Feed。退休的预公开更新地址、包和 Tag 不兼容新的脱敏 Git 图，不能被迁移、重定向或作为升级来源。

`v0.3` 才引入公开更新体系：安装包只放 GitHub Releases，同仓库 GitHub Pages 提供 Feed。实现前不得把现有检查接口或 Swift/Sparkle 参考代码描述为已完成的 Tauri 更新器。

## 固定边界

- `GET /api/v1/about` 只读本地身份，不联网。
- 只有用户触发的 `POST /api/v1/update/check` 或显式启用的延迟检查可以访问固定 HTTPS Feed。
- Feed URL 和允许主机不能由用户配置覆盖。检查必须限制 DNS、连接、重定向、头、正文和总时限，并保留最后一次有效缓存。
- Host RPC token 只留在 Tauri 进程内，不返回网页；网页只能请求固定 localhost origin 的枚举命令。
- `POST /api/v1/update/install` 由 host 实现。先写可恢复标记、停止并验证 monitor，随后验签、下载、安装和重启。停止失败、下载失败或用户取消均不改变运行状态。

## 发布元数据门槛

`latest.json` 和平台元数据必须由同一工具从实际资产生成。每次发布都校验版本、URL、长度、SHA-256、签名、source tag、package ID、core build、源码归档、SBOM 和收据的一致性。

公开 Feed finalizer 必须从实际安装器、签名证据、收据和由固定 release Tag 导出的源码归档重新计算身份。任一平台资产、Tag、源码归档、收据、版本、source commit、core build、package ID、长度、SHA 或签名发生冲突时，阻断 Feed。

## 验证范围

每个平台最终 RC 只执行一次真实更新烟测，覆盖合法更新、篡改签名、用户取消、monitor 停止失败和成功重启。此前先运行命中 API、前端、Rust 和元数据代码的聚焦测试；完整回归每个 RC 最多一次。
