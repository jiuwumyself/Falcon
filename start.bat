# Windows 启动脚本
@echo off
REM Falcon one-click startup (Windows)
REM Backend :8000 + Frontend :5173

cd /d "%~dp0"

echo.
echo   Falcon Startup
echo   ==============
echo.

if not exist "backend\venv\Scripts\python.exe" (
    echo [!] backend\venv not found. Run:
    echo     cd backend ^&^& python -m venv venv
    echo     venv\Scripts\pip.exe install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [!] frontend\node_modules not found. Run:
    echo     cd frontend ^&^& npm install
    echo.
    pause
    exit /b 1
)

echo [Backend] Django @ 8000 ...
start "Falcon Backend" "%~dp0_run_backend.bat"

echo [Frontend] Vite @ 5173 ...
start "Falcon Frontend" "%~dp0_run_frontend.bat"

echo.
echo   Backend  - http://localhost:8000
echo   Frontend - http://localhost:5173
echo.
echo   Stop: run stop.bat or close windows manually
echo.
