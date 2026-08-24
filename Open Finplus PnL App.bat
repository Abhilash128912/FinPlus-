@echo off
title Finplus PnL Journal - Starting...
echo.
echo  ============================================================
echo   FINPLUS PnL JOURNAL  -  MOBILE ^& CLOUD SYNC
echo   Cloud Backend: https://finplus.onrender.com
echo  ============================================================
echo.

cd /d "%~dp0"

echo  [1/3] Clearing stale processes on port 3000 ^& clearing build cache...

:: Kill any stale process on port 3000
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    echo    - Killing stale PID %%P on port 3000
    taskkill /F /PID %%P >nul 2>&1
)

:: Clear Vite cache to force fresh app render
if exist node_modules\.vite rmdir /s /q node_modules\.vite 2>nul
if exist __pycache__ rmdir /s /q __pycache__ 2>nul

echo  Done clearing cache.
echo.

echo  [2/3] Fetching latest trades ^& portfolio entered on Mobile App (Render Cloud)...
python sync_from_cloud.py

echo.
echo  [3/3] Starting Finplus PnL Journal Web Server on http://localhost:3000 ...
echo.
echo  ============================================================
echo   App will open on http://localhost:3000 automatically.
echo   Keep this window open while using the app.
echo   To stop the app, close this window.
echo  ============================================================
echo.

call npm.cmd run dev
