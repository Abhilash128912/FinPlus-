@echo off
TITLE INDmoney / MCX Pair Trading Signal
cd /d "%~dp0"

echo ===================================================
echo  INDmoney / MCX Pair Trading Signal
echo ===================================================
echo.

netstat -ano | findstr ":5850" | findstr "LISTENING" >nul
IF %ERRORLEVEL% EQU 0 (
    echo Server already running on port 5850 - opening browser only.
    start http://127.0.0.1:5850
    goto :eof
)

echo Starting server on port 5850...
start /b python app.py

echo Waiting for server to come up...
timeout /t 5 /nobreak > nul

start http://127.0.0.1:5850

echo.
echo Server is running in this window. Close this window to stop it.
echo.
pause >nul
