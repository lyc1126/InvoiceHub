# Windows `v0.3.0-alpha.2` NSIS public-preview 操作手册

本手册只覆盖 Windows 10/11 x64 的 current-user NSIS public-preview。它不创建 MSI、公开 Feed、自动更新、GitHub Release 或发布资产；这些操作仍须在各自阶段取得明确授权。

## 开始条件

1. `v0.3.0-alpha.2` 必须已被重新指向包含所有 macOS/Windows release 修复的最终干净 `main`；不得从中间 Tag、分支 tip 或 dirty checkout 构建。
2. GitHub Repository Secret 已配置 `SIGNPATH_API_TOKEN`。
3. GitHub Repository Variables 已配置 `SIGNPATH_ORGANIZATION_ID`、`SIGNPATH_PROJECT_SLUG`、`SIGNPATH_SIGNING_POLICY_SLUG`、`SIGNPATH_APPLICATION_ARTIFACT_CONFIGURATION_SLUG` 与 `SIGNPATH_INSTALLER_ARTIFACT_CONFIGURATION_SLUG`。
4. 两个 SignPath artifact configuration 已分别绑定应用 EXE 和外层 NSIS 安装器，且其签名策略已获 SignPath 审核。

## 触发构建

1. 在 GitHub 的 Actions 页面选择 `Windows public-preview NSIS`。
2. 选择 `Run workflow`，将 `tag` 精确填写为 `v0.3.0-alpha.2`。
3. 只接受 GitHub-hosted `windows-2025` runner；不得在本机以临时下载、改写锁文件或替换 Tag 的方式绕过 workflow。
4. 等待 SignPath 的两次签名请求完成。工作流只上传 Actions artifact，不会创建、修改或上传 GitHub Release。

## 工作流必须通过的顺序

1. checkout 精确 Tag，并固定 Python `3.14.6` x64 与 Node `24`。
2. 以受控 runtime/staging 生成 Windows preview host/package/SBOM 身份。
3. 下载 WebView2 `offlineInstaller`，先校验 [配置锁](WINDOWS_PUBLIC_PREVIEW_CONFIG.json)中的大小和 SHA-256，才允许预填 Tauri cache。
4. 执行 `tauri build --no-bundle`，并只写入一次确定性 NSIS marker。
5. 将应用 `invoicehub-desktop.exe` 交给第一个 SignPath artifact configuration 签名。
6. 执行 `tauri bundle --bundles nsis --no-sign`，复核 NSIS 内主 EXE 与已签应用 EXE 的字节 SHA-256 完全一致。
7. 将外层安装器交给第二个 SignPath artifact configuration 签名。
8. 复核应用和安装器的 Authenticode 均为 `Valid`，然后写入 SHA-256 sidecar 与 receipt。

任一 WebView2 哈希、Tag 身份、marker 次数、包内 EXE 哈希或签名状态失败时，停止该运行；不得手工补写 receipt 或上传部分产物。

## 下载与审计产物

从同一个成功的 Actions run 下载且只保留以下三项：

- `InvoiceHub-v0.3.0-alpha.2-windows-x64-setup.exe`
- `InvoiceHub-v0.3.0-alpha.2-windows-x64-setup.exe.sha256`
- `InvoiceHub-v0.3.0-alpha.2-windows-x64-setup.build-receipt.json`

在 PowerShell 中先核验：

```powershell
$artifact = '.\InvoiceHub-v0.3.0-alpha.2-windows-x64-setup.exe'
$checksum = "$($artifact).sha256"
$expected = (Get-Content $checksum -Raw).Split()[0].ToLowerInvariant()
$actual = (Get-FileHash $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Installer SHA-256 mismatch.' }
Get-AuthenticodeSignature -FilePath $artifact | Format-List Status,StatusMessage,SignerCertificate
Get-Content '.\InvoiceHub-v0.3.0-alpha.2-windows-x64-setup.build-receipt.json' -Raw
```

receipt 必须保持 `product_version=0.3.0-alpha.2`、`package_id=com.invoicehub.windows.x86_64.nsis-preview`、`updater_enabled=false`、`uninstall_signed=false`，并记录该安装器哈希、已签应用 EXE 哈希、WebView2 锁哈希与 40 位 `source_commit`。

## 真机烟测

在隔离的 Windows 10/11 x64 测试用户或 VM 中执行。不要使用真实发票目录、真实业务配置或管理员范围安装。

1. 双击安装器，保持 current-user 安装；安装后从实际安装目录定位主 EXE，不假设固定绝对路径。
2. 对安装后的主 EXE 运行 `Get-AuthenticodeSignature`，要求 `Status` 为 `Valid`；其 SHA-256 应与 receipt 的 `signed_application_sha256` 一致。
3. 启动应用，在隔离的空目录配置下确认 health 到达 ready。
4. 启动 monitor，确认 `running && ready`；停止 monitor 并复核真实 stopped 状态。
5. 使用应用的结构化退出路径关闭，确认主程序退出且不残留本次测试进程。
6. 通过 Windows 的卸载入口卸载一次，并复核主程序不再可启动。该 alpha 的 Tauri 生成卸载器预期未签名，必须如实记录，不能将其列为签名失败。

Windows 真机通过后，保留安装器、SHA-256、receipt、Actions run URL、签名状态和烟测记录，等待单独授权后再追加到同一 GitHub Prerelease。
