# 官网素材来源

所有资源均本地加载，不使用远程字体、图片、追踪或分析服务。

| 文件 | 来源 | 许可 |
|---|---|---|
| `assets/mark.svg` | 为 InvoiceHub 原创的 `h / i` 字母组合 | 随仓库 AGPL-3.0-or-later |
| `paper-scene.js` 的 Canvas 纸票 | 确定性原创印刷构图，两张票纸与三个标签独立动画，内容为品牌文字，不含真实票据 | 随仓库 AGPL-3.0-or-later |
| `index.html` / `style.css` 功能场景 | 原创 CSS 纸票、放大镜、打印机、明细归集、扫描与单据排版；数字均为合成数据 | 随仓库 AGPL-3.0-or-later |
| `assets/display.woff` | 复用仓库已许可的 Dela Gothic One Latin 字体 | SIL Open Font License 1.1，见 `assets/OFL-DelaGothicOne.txt` |
| `assets/icons.js` | 从本机已安装的 Lucide 1.8.0 提取 48 个图标节点，未复制整套运行库；源码链接使用 GitFork 通用仓库图标 | ISC，见 `assets/LICENSE-lucide` |

正文优先使用系统字体，Dela Gothic One 只用于英文品牌展示。未复制商业网站、游戏、公司或用户的图片、截图、源码样式与业务资料。

图标可从已安装的 Lucide 包机械重建：

```powershell
node website/scripts/vendor-icons.cjs <lucide-package-directory>
```

生成器只更新精选图标及其许可证文件；不会联网安装依赖。
