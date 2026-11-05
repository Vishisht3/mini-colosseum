@echo off
setlocal enabledelayedexpansion
title Mini-Colosseum Research Workbench

echo =================================================================
echo  MINI-COLOSSEUM: Research-Harness Workbench on Meta Muse Models
echo  Implementing Stellar Colosseum (arXiv:2609.15983)
echo =================================================================

cd /d "%~dp0"

:: 1. Locate Python
set "PYTHON_CMD="
for %%c in ("py" "python" "python3" "%LOCALAPPDATA%\Python\bin\python.exe") do (
    if not defined PYTHON_CMD (
        %%~c --version >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON_CMD=%%~c"
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3 was not found on your system.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Using Python: !PYTHON_CMD!

:: 2. Release port 8765 if already in use by a stale process
powershell -NoProfile -Command "try { Get-Process -Id (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop).OwningProcess -ErrorAction Stop | Stop-Process -Force } catch {}" >nul 2>&1

:: 3. Launch background browser opener once the server /health responds
set "PORT=8765"
set "URL=http://127.0.0.1:!PORT!"
echo Starting Python backend on !URL!...

start /b "" powershell -NoProfile -Command "for ($i=0; $i -lt 30; $i++) { Start-Sleep -Milliseconds 400; try { if ((Invoke-WebRequest -Uri '!URL!/health' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200) { Start-Process '!URL!'; break } } catch {} }"

:: 4. Run backend in foreground so logs are visible and Ctrl+C cleanly terminates
echo Mini-Colosseum is starting. Your browser will open automatically once ready.
echo Press Ctrl+C in this window to stop the server.
echo.

!PYTHON_CMD! -m backend.main !PORT!

if %ERRORLEVEL% neq 0 (
    echo.
    echo [INFO] Mini-Colosseum stopped.
    pause
)
