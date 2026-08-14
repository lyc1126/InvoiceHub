@echo off
setlocal EnableExtensions
chcp 65001 >nul
call "%~dp0scripts\windows\导入旧版设置.bat" %*
exit /b %ERRORLEVEL%
