@echo off
title Quality Stock Screener — Phase 1
cd /d "%~dp0"
echo ===================================================
echo   Quality Stock Screener  ^|  Phase 1 Server
echo   Source: Nifty 500 Universe (2400+ Stocks)
echo ===================================================
echo.

set "SCREENER_PORT=%PORT%"
if "%SCREENER_PORT%"=="" set "SCREENER_PORT=5050"
echo [1/3] Terminating any existing Stock Screener server (Port %SCREENER_PORT%)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr :%SCREENER_PORT% ^| findstr LISTENING 2^>nul') do taskkill /F /PID %%a >nul 2>&1
ping 127.0.0.1 -n 2 >nul

echo [2/3] Cleaning Python bytecode ^& temporary system cache...
if exist __pycache__ rmdir /s /q __pycache__ 2>nul
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
if exist .pytest_cache rmdir /s /q .pytest_cache 2>nul
echo.

echo [3/3] Launching Stock Screener Server ^& Web UI...
echo         Starting server on http://localhost:%SCREENER_PORT% ...
echo.
python fetch_and_build.py
echo.
if %ERRORLEVEL% NEQ 0 (
  echo ❌ Server exited with code %ERRORLEVEL%.
  pause
  exit /b
)

echo Server active! Press any key to stop server...
pause
