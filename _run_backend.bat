@echo off
REM Falcon 后端启动脚本 — 由 start.bat 调用，也可单独双击。
REM 启动 Django 开发服务器在 http://localhost:8000

title Falcon Backend
cd /d "%~dp0backend"

echo.
echo [Falcon Backend] 当前目录: %CD%
echo [Falcon Backend] 启动 Django @ 8000 ...
echo.

venv\Scripts\python.exe manage.py runserver

echo.
echo [Falcon Backend] 进程已退出。按任意键关闭窗口。
pause >nul
