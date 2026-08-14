@echo off
setlocal EnableExtensions
chcp 65001 >nul
call "%~dp0scripts\windows\停止localhost服务.bat" %*
exit /b %ERRORLEVEL%
