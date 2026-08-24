@echo off
title Finplus PnL Journal - Starting...
echo.
echo  ============================================================
echo   FINPLUS PnL JOURNAL  -  3-PILLAR SYSTEM
echo   Unified App Server on http://localhost:8080
echo  ============================================================
echo.

cd /d "%~dp0"

echo  [1/3] Clearing any stale process on port 8080...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8080" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%P >nul 2>&1
)

echo  [2/3] Fetching latest portfolio and syncing with Render Cloud...
python sync_from_cloud.py

echo  [3/3] Launching Finplus PnL Journal on http://localhost:8080 ...
start http://localhost:8080

echo.
echo  ============================================================
echo   App running on http://localhost:8080
echo   Keep this console window open while using the app.
echo  ============================================================
echo.

python -m uvicorn backend:app --host 0.0.0.0 --port 8080
