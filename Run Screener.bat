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

set /a RESTART_COUNT=0
:launch
python fetch_and_build.py
set "EXIT_CODE=%ERRORLEVEL%"
echo.

if "%EXIT_CODE%"=="0" (
  echo Server stopped normally.
  goto :end
)

set /a RESTART_COUNT+=1
if %RESTART_COUNT% GEQ 5 (
  echo X Server crashed 5 times in a row ^(last exit code %EXIT_CODE%^). Not retrying further - something is wrong.
  pause
  exit /b
)

echo !! Server exited unexpectedly with code %EXIT_CODE% ^(crash, not a normal stop^). Restarting in 3s... ^(attempt %RESTART_COUNT%/5^)
ping 127.0.0.1 -n 4 >nul
goto :launch

:end
echo Press any key to close this window...
pause
