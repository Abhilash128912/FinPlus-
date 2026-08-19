@echo off
title Quality Stock Screener — Phase 1
cd /d "%~dp0"
echo ===================================================
echo   Quality Stock Screener  ^|  Phase 1 Server
echo   Source: Nifty 500 Universe (2400+ Stocks)
echo ===================================================
echo.

echo [1/3] Terminating any existing server instances (Port 5000 ^& Python)...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr :5000 ^| findstr LISTENING 2^>nul') do taskkill /F /PID %%a 2>nul
taskkill /F /IM python.exe 2>nul
timeout /t 1 /nobreak >nul

echo [2/3] Cleaning Python bytecode ^& temporary system cache...
if exist __pycache__ rmdir /s /q __pycache__ 2>nul
for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d" 2>nul
if exist .pytest_cache rmdir /s /q .pytest_cache 2>nul
echo.

echo [3/3] Launching Stock Screener Server ^& Web UI...
echo         Starting server on http://localhost:5000 ...
echo.
python fetch_and_build.py
echo.
if %ERRORLEVEL% NEQ 0 (
  echo ❌ Error starting Python server. Please check python installation.
  pause
  exit /b
)

echo Server active! Open in your browser at:
echo http://localhost:5000
echo.
pause
