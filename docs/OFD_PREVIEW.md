# OFD 原票预览组件

## 范围与实现

本功能只渲染用户已选择的 OFD 原文件，不参与票头识别、成本明细、同票纠偏或打印来源选择。PDF 继续使用 PyMuPDF；OFD 由 OFDRW 2.4.0 的 `ImageMaker` 输出 150 DPI PNG，复用既有分页、缩放、闲置续租和内存缓存。

旧测试将两个 PNG 放入 ZIP 后改名 OFD，未包含真实 OFD 页面树，不能证明原票面兼容性。新测试使用 `OFD.xml → Document.xml → Page/Content.xml`、文字、矢量图形和图片资源。

## 实验记录与判定

2026-09-08，从 `main@fda171dbb7deb4e01731c5a72ec8102f11d3c03d` 创建 `codex/ofd-preview-renderer`。

1. 假设：OFDRW 图片链可正确显示具有真实页面树的最小 OFD。最小样本是两页横纵混排，含中文/数字文字、线条、图像及不被页面引用的资源；结果用于决定是否采用该引擎。缺页、漏字或仅显示资源图则停止接入，先定位对应机制。
2. 假设：PNG 路径可以去掉 SVG/PDF 导出专用依赖。保留图片链共享的 PDFBox 混合模式、FontBox、iText 字体和签章结构依赖，排除 Batik、iText layout/font-asian；进一步移除 OFD writer 的 layout/graphics2d/font 与 UJMP 未使用的 JSON 导出，显式保留 TIFF 解码。比较相同样本的输出，出现加载失败或像素差异则恢复相关依赖。
3. 假设：Java 21 专用运行时可代替完整 JDK。使用同一个样本在完整 JDK 与 jlink 运行时下比较 PNG，只有字节一致才接受裁剪结果；记录真实体积，不用估算代替测量。

## 数据和进程边界

- 只读原 OFD；受控解包副本仅存在系统临时目录，进程结束后清理。生成的 PNG 通过管道返回，不写到源目录、runtime 或投影。
- 在解包前校验 ZIP 原始成员名 `orig_filename`、重复项、符号链接、加密、成员数及解压大小，避免 Windows 分隔符归一化或 NUL 截断隐藏危险名称；XML 拒绝 DTD/实体声明。多文档 OFD 明确拒绝，不能静默只看第一份。
- 每次只生成一页，进程全局最多一个 OFD worker；忙碌可重试。25 秒超时结束并回收 worker；Java 堆 384 MiB，页数 200、单页 3000 万像素、PNG 32 MiB 上限。
- Java 21 的限制策略只授予临时副本、组件、系统及用户字体目录读取和临时目录写入权限，不授予网络和启动其它进程权限；不继承 Host RPC、Java 参数注入或代理环境。该策略依赖 Java 21，不能直接升级到已移除 Security Manager 的新版 Java。
- 程序缺少或校验失败时，OFD 条目显示组件诊断并保留系统打开。混选的 PDF/XML 仍可查看；不冒充文件损坏，不把同票 PDF 当作 OFD 原文件预览。
- 印章外观渲染不代表数字签名验真。

## 构建与验收

组件源码位于 `tools/ofd-preview/`，构建入口为 `scripts/dev/build_ofd_preview.py`。开发机首次构建：

```bash
python scripts/dev/build_ofd_preview.py --fetch
```

此命令从固定 URL 下载并核对长度/SHA，按本机选择锁定的 macOS arm64 或 Windows x64 JDK 21.0.12.1，仅用于本次编译和 jlink；不安装系统 Java，不需要 Maven。默认下载缓存为 `runtime/ofd-build-cache`，组件输出为 `runtime/components/ofd-preview`。输出已存在时拒绝覆盖；迭代构建使用新的 `--output` 目录，验收后替换自己生成的旧组件。

已有构建输入时可离线执行：

```bash
python scripts/dev/build_ofd_preview.py --jdk-archive <锁定的本平台JDK压缩包> --dependencies <锁定JAR所在目录> --output <新的组件目录>
```

`pom.xml` 仅供维护者解析依赖时对照；正式构建只接受 `dependencies.lock.json` 内的 31 个原始 JAR。`component.json` 记录平台、源码输入、核心绑定指纹与逐文件哈希；组件还携带独立 CycloneDX SBOM、项目/OFDRW 许可证及 JDK legal 文件。修改 Java、构建脚本或锁文件时，必须同步刷新 `COMPONENT_SOURCE_FINGERPRINT` 并通过源码指纹契约。

源码后端会自动读取上述默认组件。正式分发的集成位置是内嵌 Python 的 `components/ofd-preview`（即 `sys.prefix/components/ofd-preview`）；在生成最终 Python runtime manifest、打包/签名之前，将对应平台组件构建至该目录，并重新生成外层 runtime tree、制品文件清单和收据。已有 Windows/macOS staging 会复制整个 Python runtime；不得绕过其平台排除、哈希或签名门禁，也不得直接修改已经签名/发布的旧 App。当前 alpha.2 没有本组件。

本平台原生引擎测试须显式启用，否则相关测试会跳过：

```bash
INVOICE_HUB_TEST_OFD_COMPONENT=runtime/components/ofd-preview python -m pytest tests/test_ofd_rendering.py
```

Windows PowerShell 使用 `$env:INVOICE_HUB_TEST_OFD_COMPONENT = "runtime/components/ofd-preview"` 后执行同一 pytest 命令。

## 本轮结果与限制

| 本机 macOS arm64 测量项 | 结果 |
|---|---|
| 完整 converter 依赖（含适配器） | 32,168,428 bytes |
| 精简预览依赖（含适配器） | 23,643,873 bytes，减少 26.5% |
| 含专用 Java 的完整组件 | 78,334,947 bytes（约 74.7 MiB） |
| 组件测试 ZIP | 56,150,258 bytes（约 53.5 MiB） |


- 两页合成样本在完整 converter 依赖/完整 JDK 与精简依赖/jlink 运行时上输出逐字节一致；中文、金额、线框和图像分区、横纵方向、中文空格临时路径均已检查。初版缺字源于字体目录权限、TTC 默认字体处理和缺字形占位，已补字体映射、cmap glyph 0/null 检查及绘制告警阻断。
- 测试使用本地 Python 3.14.3/PyMuPDF 1.28.0 和锁定 Java 21；原生组件、预览/API/打印/静态契约覆盖 148 个不同测试用例，首轮 2 个失败修正后对受影响的 45 项复验通过，不将重复执行累计为新增用例。另有 16 项 Node 交互和 69 项 Swift 回归通过。修改的 Python 文件编译及 Java 构建通过。
- 最终组件体积、ZIP 哈希与裁剪清单保留在 ignored 的 `runtime/ofd-preview-qa/verification.json`；`page-1.png/page-2.png` 是原创合成样本的可视结果，`ofd-preview-macos-arm64.zip` 是组件测试包，不是完整应用安装包。
- 随后按用户要求，已直接渲染一份单页真实 OFD（1240×945 PNG），在系统 Preview 打开并获得用户对效果的明确确认。原文件只读，真实票面仅保留在系统临时目录供用户当前查看，未进入公开工作树；这是用户要求的独立查看产物，不改变产品预览 API 的内存缓存语义。
- 单样本确认不覆盖更多业务版式、数字签名验真、所有嵌入字体、Windows 原生执行、正式 BAT、真实默认配置、浏览器前台拉起、原生选择器、当前皮肤/`?no_skin=1` 浏览器验收、Tauri/Swift 完整 App 或新 Release。此次没有修改前端静态资源，也没有替换用户当前运行的 alpha.2。

正式分发前仍需 Windows x64 / macOS arm64 对应运行时、打包清单、第三方许可和平台成品验证。合成样本不能代替用户问题 OFD 的视觉核对。


## InvoiceHub 内查看补充

用户随后明确要求在 InvoiceHub 内查看。已通过 keep-monitor 协议关闭经过身份核对的旧 localhost，并从当前源码在固定端口启动开发服务；原 monitor 为未运行。单票副本、配置、普通/成本投影和运行态都隔离在系统临时目录，未修改原发票、用户设置或已发布 App。

已在真实浏览器的发票列表勾选 OFD，经“更多勾选操作 → 预览”显示产品的源文件预览弹窗，截图确认票面加载；health 为 development 且 backend/background ready。此结果补充了默认浅色浏览器的单票 UI → API → renderer 验收，不覆盖原生桌面壳、Windows、其它皮肤或 `?no_skin=1`。开发服务和临时演示目录暂留供查看，关闭后可清理；已安装 alpha.2 的文件不变，当前 localhost 由开发服务提供。
