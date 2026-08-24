@echo off
title Finplus PnL Journal - Starting...
echo.
echo  ============================================================
echo   FINPLUS PnL JOURNAL  -  Starting up...
echo   Cloud Sync & Backup: Render Cloud Backend
echo  ============================================================
echo.

cd /d "%~dp0"

REM ============================================================
REM  Clear any existing processes holding port 3000
REM ============================================================
echo  [1/2] Clearing any stale process on port 3000...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo    - Killing PID %%P on port 3000
    taskkill /F /PID %%P >nul 2>&1
)

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
echo   App will open in your browser automatically (http://localhost:3000).
echo   Keep this window open while using the app.
echo   To stop the app, close this window.
echo  ============================================================
echo.

call npm.cmd run dev
