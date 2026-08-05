@echo off
title Quality Stock Screener — Phase 1
echo ============================================
echo   Quality Stock Screener  ^|  Phase 1
echo   Source: D:\Nifty 500 stocks.xlsx
echo ============================================
echo.
echo Step 1: Installing required packages...
pip install yfinance pandas openpyxl requests curl_cffi --quiet
echo.
echo Step 2: Running screener (first run takes 8-15 min)...
echo         Subsequent runs use cache and complete in under 1 min.
echo.
python "%~dp0fetch_and_build.py"
echo.
echo Server active! The web app should have opened in your browser at:
echo http://localhost:5000
echo.
echo Use the "Scan Now" button inside the web app for 1-click scans anytime.
echo Keep this window open while using the app.
echo.
pause
