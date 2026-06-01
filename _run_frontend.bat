@echo off
REM ============================================================
REM Falcon 前端启动脚本 — 由 start.bat 调用，也可单独双击。
REM 启动 Vite 开发服务器在 http://localhost:5173
REM 添加 chcp 65001 切换到 UTF-8 编码，解决 Windows CMD 中文乱码问题
REM ============================================================
chcp 65001 >nul

title Falcon Frontend
cd /d "%~dp0frontend"

echo.
echo [Falcon Frontend] 当前目录: %CD%
echo [Falcon Frontend] 启动 Vite @ 5173 ...
echo.

call npm run dev

echo.
echo [Falcon Frontend] 进程已退出。按任意键关闭窗口。
pause >nul
