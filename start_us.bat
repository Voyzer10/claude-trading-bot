@echo off
title US day-trader flow (11 agents, PAPER)
cd /d "%~dp0us"
set PY=python
where python >NUL 2>NUL || (
  if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
  if exist "%USERPROFILE%\anaconda3\python.exe" set PY="%USERPROFILE%\anaconda3\python.exe"
)
echo ======================================================================
echo  US flow: scanner first (about 4 minutes for ~5,900 stocks)
echo ======================================================================
%PY% us_flow.py scan
:pick
echo.
set TK=
set /p TK=Ticker to run through agents 2-9 (blank to quit): 
if "%TK%"=="" goto end
%PY% us_flow.py trade %TK%
goto pick
:end
echo.
echo Pelosi tracker (agent 11):
%PY% us_flow.py pelosi
pause
