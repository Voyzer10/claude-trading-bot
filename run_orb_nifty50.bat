@echo off
cd /d "%~dp0"
echo NSE opening-range scan (Nifty 50)...
python scan_nse.py orb --nifty50
echo.
pause
