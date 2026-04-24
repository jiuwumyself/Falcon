@echo off
REM Falcon 一键启动：后端 (Django @ 8000) + 前端 (Vite @ 5173)
REM 两个新 CMD 窗口运行，关掉这个 launcher 不影响服务。

setlocal

set ROOT=%~dp0
REM 去掉末尾反斜杠，路径拼接更干净
if "%ROOT:~-1%"=="\" set ROOT=%ROOT:~0,-1%

REM 基本存在性检查，防止双击后一闪而过
if not exist "%ROOT%\backend\venv\Scripts\python.exe" (
  echo [!] backend\venv\Scripts\python.exe 不存在 — 请先建虚拟环境：
  echo     cd backend
  echo     python -m venv venv
  echo     venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist "%ROOT%\frontend\package.json" (
  echo [!] frontend\package.json not found
  pause
  exit /b 1
)

REM 用 /d 设置新窗口的初始目录；cmd /k 后面跟纯命令，不要再叠 && 链（start
REM 对 && 的处理不稳定，某些机器上会把第二条命令当成 start 自己的参数）。
start "Falcon Backend" /d "%ROOT%\backend" cmd /k venv\Scripts\python.exe manage.py runserver
start "Falcon Frontend" /d "%ROOT%\frontend" cmd /k npm run dev

echo.
echo [ok] backend  -^> http://localhost:8000
echo [ok] frontend -^> http://localhost:5173
echo.
echo 关闭服务：双击 stop.bat 或直接关掉上面两个窗口。

REM ping 充当 sleep，timeout /t 在某些 Windows 上被 stdin 重定向时会崩
ping -n 4 127.0.0.1 >nul 2>&1
endlocal
exit /b 0
