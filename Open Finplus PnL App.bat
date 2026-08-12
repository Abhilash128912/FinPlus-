@echo off
title Finplus PnL Journal - Starting...
echo.
echo  ============================================================
echo   FINPLUS PnL JOURNAL  -  Starting up...
echo  ============================================================
echo.

cd /d "%~dp0"

REM ============================================================
REM  Kill any stale processes already holding ports 8000 / 3000
REM ============================================================
echo  [0/3] Clearing any existing processes on ports 8000 and 3000...

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo    - Killing PID %%P on port 8000
    taskkill /F /PID %%P >nul 2>&1
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo    - Killing PID %%P on port 3000
    taskkill /F /PID %%P >nul 2>&1
)

REM Also clean up any orphaned uvicorn/node processes tied to this app
taskkill /F /IM uvicorn.exe >nul 2>&1

echo  Done clearing old processes.
echo.

REM --- Start FastAPI Backend Server on port 8000 ---
echo  [1/3] Launching Backend Price Server on port 8000...
start /b python -m uvicorn backend:app --host 0.0.0.0 --port 8000 >nul 2>&1

REM --- Install node_modules if missing ---
if not exist "node_modules" (
    echo  [2/2] Installing npm dependencies...
    call npm.cmd install
    if errorlevel 1 (
        echo.
        echo  ERROR: npm install failed. Make sure Node.js is installed.
        pause
        exit /b 1
    )
)

REM --- Launch Vite dev server (auto-opens browser) ---
echo  [2/2] Starting Finplus PnL Journal on http://localhost:3000
echo.
echo  ============================================================
echo   App will open in your browser automatically.
echo   Keep this window open while using the app.
echo   To stop the app, close this window.
echo  ============================================================
echo.

call npm.cmd run dev
