@echo off
title Trader dashboard (port 3000)
cd /d "%~dp0"
set PY=python
where python >NUL 2>NUL || (
  if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
  if exist "%USERPROFILE%\anaconda3\python.exe" set PY="%USERPROFILE%\anaconda3\python.exe"
)
where npm >NUL 2>NUL || (
  echo Node.js is not installed. Install the LTS version from https://nodejs.org and run this again.
  pause
  exit /b 1
)
%PY% -c "import fastapi, uvicorn, psutil" 2>NUL || (
  echo Installing fastapi + uvicorn + psutil, one time...
  %PY% -m pip install fastapi uvicorn psutil
)
if not exist node_modules (
  echo Installing the dashboard packages, one time, takes a minute or two...
  call npm install
)

rem ---- password: the dashboard is reachable from your phone on the same WiFi, so it asks for one
set PWFILE=trader\dashboard_password.txt
if exist "%PWFILE%" goto havepw
if not exist trader mkdir trader
echo.
echo The dashboard will also open on your phone (same WiFi), so it needs a password.
echo Login: any username + this password. It is saved in %PWFILE% (change or delete it any time).
rem letters and digits only: cmd mangles symbols (ampersand, pipe, caret, percent, exclamation mark) when it saves the password
set NEWPW=
set /p NEWPW=Choose a password (letters and digits only; press Enter and one is made for you): 
if "%NEWPW%"=="" for /f %%p in ('%PY% -c "import secrets; print(secrets.token_urlsafe(12))"') do set NEWPW=%%p
echo Your dashboard password: %NEWPW%
>"%PWFILE%" echo %NEWPW%
:havepw
set /p DASHBOARD_PASSWORD=<"%PWFILE%"

echo Starting the dashboard API on 127.0.0.1:8000 (PC only) in a second window...
start "Trader dashboard API" %PY% -m uvicorn api.index:app --host 127.0.0.1 --port 8000
echo Building the dashboard (about a minute)...
call npx next build
if errorlevel 1 (
  echo Build failed, see above.
  pause
  exit /b 1
)
echo.
echo ======================================================================
echo  On this PC:  http://localhost:3000
echo  On your phone (same WiFi), open one of these:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do for /f "tokens=*" %%b in ("%%a") do echo     http://%%b:3000
echo  Login: any username + the password from %PWFILE%
echo  If Windows Firewall asks about Node.js: allow it on PRIVATE networks.
echo  Keep this window open; close it to stop the dashboard.
echo ======================================================================
start "" cmd /c "timeout /t 5 >NUL & start http://localhost:3000"
call npx next start -H 0.0.0.0 -p 3000
pause
