param(
    [string]$ShortcutName = "启动一站式发票汇总系统.lnk"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$target = Join-Path $root "启动一站式发票汇总系统.bat"
$shortcutPath = Join-Path $root $ShortcutName

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,167"
$shortcut.Description = "启动一站式发票汇总系统 localhost 服务"
$shortcut.Save()
Write-Host "Shortcut created: $shortcutPath"
