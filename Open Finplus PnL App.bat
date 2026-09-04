@echo off
title Finplus PnL Journal - Cache Cleanup & Server Start...
echo.
echo  ============================================================
echo   FINPLUS PnL JOURNAL  -  CACHE PURGE ^& AUTO SYNC
echo   Cloud Backend: https://finplus.onrender.com
echo  ============================================================
echo.

cd /d "%~dp0"

echo  [1/4] Terminating stale background processes on ports 3000 ^& 8000...

:: Kill any stale process on port 3000 (Vite)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo    - Killing process PID %%P on port 3000
    taskkill /F /PID %%P >nul 2>&1
)

:: Kill any stale process on port 8000 (FastAPI backend if running locally)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo    - Killing process PID %%P on port 8000
    taskkill /F /PID %%P >nul 2>&1
)

echo.
echo  [2/4] Purging all local build ^& browser bundle caches...
if exist node_modules\.vite (
    echo    - Deleting node_modules\.vite ...
    rmdir /s /q node_modules\.vite 2>nul
)
if exist dist (
    echo    - Deleting dist build folder ...
    rmdir /s /q dist 2>nul
)
if exist __pycache__ (
    echo    - Deleting __pycache__ ...
    rmdir /s /q __pycache__ 2>nul
)
if exist .cache (
    echo    - Deleting .cache ...
    rmdir /s /q .cache 2>nul
)

echo  Done purging local cache.
echo.

echo  [3/4] Fetching latest live portfolio dataset from Render Cloud...
python sync_from_cloud.py 2>nul || py sync_from_cloud.py 2>nul

echo.
echo  [4/4] Launching fresh web server with --force flag (bypasses all browser cache)...
echo.
echo  ============================================================
echo   App will open on http://localhost:3000 automatically.
echo   Keep this window open while using the app.
echo   If you still see old cached UI, press Ctrl + Shift + R on your browser.
echo  ============================================================
echo.

:: Open browser explicitly after launching Vite server
start "" "http://localhost:3000"

call npm.cmd run dev -- --force
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Failed to start application server.
    pause
)


