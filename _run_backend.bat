@echo off
REM Falcon 后端启动脚本 — 由 start.bat 调用，也可单独双击。
REM 使用 waitress 生产级 WSGI 服务器（多线程），替代 Django runserver（单线程易502）

title Falcon Backend
cd /d "%~dp0backend"

echo.
echo [Falcon Backend] 当前目录: %CD%
echo [Falcon Backend] 启动 waitress (8 threads) @ 8000 ...
echo.

venv\Scripts\python.exe -m waitress --host=0.0.0.0 --port=8000 --threads=8 config.wsgi:application

echo.
echo [Falcon Backend] 进程已退出。按任意键关闭窗口。
pause >nul
