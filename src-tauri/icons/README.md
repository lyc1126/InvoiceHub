# InvoiceHub 桌面图标 04

第四款为当前 desktop 默认图标：官网纸白 `#f8f9f5` 圆角方形、墨黑粗体 `hi.`、荧光黄绿票纸折角。保持足够留白，适配 Dock、任务栏和托盘小尺寸。

| 文件 | 用途 |
| --- | --- |
| `desktop-04.png` | 1024×1024 RGBA 设计母版 |
| `icon.png` | 512×512、8-bit RGBA，Tauri 窗口和托盘 |
| `icon.ico` | Windows 16/20/24/32/40/48/64/128/256 像素多尺寸 |
| `icon.icns` | macOS 多尺寸图标，最大 1024 像素 |

`../tauri.conf.json` 显式绑定三个平台资源，development、alpha、public-preview 和 Windows preview 配置继承它。修改资源不会改变已安装程序的图标；新桌面构建才包含本设计。

生成：`python scripts/dev/generate_desktop_icon.py`。依赖项目已有 Pillow，使用包内 `website/assets/display.woff` 的 Dela Gothic One 字形，许可见 `website/assets/OFL-DelaGothicOne.txt`。构图为 InvoiceHub 原创，随仓库 AGPL-3.0-or-later；不依赖系统字体、远程图片或商业素材。
