@echo off
title Backtest (research.py)
cd /d "%~dp0"
set PY=python
where python >NUL 2>NUL || (
  if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
  if exist "%USERPROFILE%\anaconda3\python.exe" set PY="%USERPROFILE%\anaconda3\python.exe"
)
echo === 1/3 Crypto breakouts, 20 coins (now also tests widening tight stops to 1%%) ===
%PY% research.py crypto
echo.
echo === 2/3 Crypto breakouts, ~47 coins (more coins = more chances) ===
%PY% research.py crypto --universe trader\universe_crypto_wide.txt
echo.
echo === 3/3 Crypto oversold bounce (for sideways days), 20 coins ===
%PY% research.py crypto-mr
echo.
echo Reports: trader\research\report_crypto.txt, report_crypto-crypto_wide.txt, report_crypto-mr.txt
echo (For NSE / F^&O / short tests: python research.py nse ^| fno ^| crypto-short)
pause
