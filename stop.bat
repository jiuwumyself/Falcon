@echo off
REM Falcon 一键关闭：按端口 8000 / 5173 杀进程。

setlocal enabledelayedexpansion

call :kill_port 8000 Backend
call :kill_port 5173 Frontend
REM Vite 被占用会自动挪到 5174 / 5175，一并清掉
call :kill_port 5174 Frontend-alt1
call :kill_port 5175 Frontend-alt2

echo.
echo [ok] done
timeout /t 2 >nul
exit /b 0


:kill_port
set PORT=%~1
set LABEL=%~2
set FOUND=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
  if not "%%P"=="0" (
    echo [kill] %LABEL% pid=%%P port=%PORT%
    taskkill /PID %%P /F >nul 2>&1
    set FOUND=1
  )
)
if !FOUND! EQU 0 echo [skip] %LABEL% port=%PORT% not listening
exit /b 0
