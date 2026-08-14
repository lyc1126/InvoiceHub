@echo off
setlocal EnableExtensions
chcp 65001 >nul
call "%~dp0scripts\windows\启动localhost汇总页.bat" %*
exit /b %ERRORLEVEL%
