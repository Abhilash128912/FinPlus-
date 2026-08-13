@echo off
title Quality Stock Screener — Phase 1
cd /d "%~dp0"
echo ============================================
echo   Quality Stock Screener  ^|  Phase 1
echo   Source: D:\Nifty 500 stocks.xlsx
echo ============================================
echo.
echo Step 1: Cleaning up any old background server instances...
taskkill /F /IM python.exe 2>nul
timeout /t 1 /nobreak >nul

echo Step 2: Checking required packages...
pip install yfinance pandas openpyxl requests curl_cffi --quiet
echo.
echo Step 3: Running screener & launching web server...
echo         Scanning 2400+ stocks in background...
echo.
python fetch_and_build.py
echo.
echo Server active! The web app should have opened in your browser at:
echo http://localhost:5000
echo.
echo Use the "Scan Now" button inside the web app for 1-click scans anytime.
echo Keep this window open while using the app.
echo.
pause
