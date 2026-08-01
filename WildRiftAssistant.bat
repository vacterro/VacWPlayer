@echo off
setlocal
cd /d "%~dp0"
title WildRiftAssistant

rem --- find a usable Python ---------------------------------------------------
set "PYW="
if exist "..\venv\Scripts\pythonw.exe" set "PYW=..\venv\Scripts\pythonw.exe"
if not defined PYW if exist "venv\Scripts\pythonw.exe" set "PYW=venv\Scripts\pythonw.exe"
if not defined PYW if exist "..\venv\Scripts\python.exe" set "PYW=..\venv\Scripts\python.exe"
if not defined PYW if exist "venv\Scripts\python.exe" set "PYW=venv\Scripts\python.exe"

if not defined PYW (
    echo.
    echo [ERROR] Python not found.
    echo Expected one of:
    echo   ..\venv\Scripts\pythonw.exe
    echo   venv\Scripts\pythonw.exe
    echo   ..\venv\Scripts\python.exe
    echo   venv\Scripts\python.exe
    echo.
    echo Install deps with:  ..\venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "main.pyw" (
    echo.
    echo [ERROR] main.pyw not found in "%~dp0"
    echo.
    pause
    exit /b 1
)

rem --- diagnostic check: WildRiftAssistant.bat --check ------------------------
if "%~1"=="--check" (
    echo OK: %PYW%
    exit /b 0
)

echo Starting WildRiftAssistant...
start "" "%PYW%" main.pyw
endlocal
