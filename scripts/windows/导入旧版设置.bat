@echo off
setlocal EnableExtensions
chcp 65001 >nul
if "%~1"=="" (
  echo Usage: %~nx0 "C:\example\old-invoicehub"
  exit /b 2
)
set "SCRIPT=%~dp0import_previous_settings.ps1"
set "PS7_FIXED=%ProgramFiles%\PowerShell\7\pwsh.exe"
set "PS7="
if "%INVOICE_HUB_FORCE_PS51%"=="1" goto :powershell51
if exist "%PS7_FIXED%" set "PS7=%PS7_FIXED%"
if defined PS7 "%PS7%" -NoLogo -NoProfile -NonInteractive -Command "if ($PSVersionTable.PSVersion.Major -ge 7) { exit 0 } else { exit 1 }" >nul 2>&1
if defined PS7 if not errorlevel 1 goto :powershell7
set "PS7="
for /f "delims=" %%P in ('where.exe pwsh.exe 2^>nul') do if not defined PS7 set "PS7=%%~fP"
if not defined PS7 goto :powershell51
"%PS7%" -NoLogo -NoProfile -NonInteractive -Command "if ($PSVersionTable.PSVersion.Major -ge 7) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto :powershell51
:powershell7
"%PS7%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -OldRoot "%~1"
exit /b %ERRORLEVEL%
:powershell51
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -OldRoot "%~1"
exit /b %ERRORLEVEL%
