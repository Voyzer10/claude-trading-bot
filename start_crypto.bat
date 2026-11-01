@echo off
title Live crypto scanner + AUTO PAPER trading
cd /d "%~dp0"
set PY=python
where python >NUL 2>NUL || (
  if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
  if exist "%USERPROFILE%\anaconda3\python.exe" set PY="%USERPROFILE%\anaconda3\python.exe"
)
echo Starting live scanner. Keep this window open; close it or press Ctrl+C to stop.
%PY% live.py --markets CRYPTO --auto-paper %*
pause
