@echo off
setlocal
cd /d "%~dp0"
title WildRiftAssistant

rem --- find a usable Python ---------------------------------------------------
rem Priority: real system pythonw (the local venv's pythonw.exe on this machine
rem is a wrapper stub that spawns a second pythonw for the same script - every
rem launch then runs main.pyw / engines TWICE, doubling clicks and lag). The
rem system install has all deps (cv2, pywin32, tkinterdnd2) and runs the same
rem code; venv pythonw stays only as last-resort fallback.
set "PYW="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
if not defined PYW if exist "%ProgramFiles%\Python311\pythonw.exe" set "PYW=%ProgramFiles%\Python311\pythonw.exe"
if not defined PYW if exist "%ProgramFiles(x86)%\Python311\pythonw.exe" set "PYW=%ProgramFiles(x86)%\Python311\pythonw.exe"
if not defined PYW if exist "..\venv\Scripts\pythonw.exe" set "PYW=..\venv\Scripts\pythonw.exe"
if not defined PYW if exist "venv\Scripts\pythonw.exe" set "PYW=venv\Scripts\pythonw.exe"
if not defined PYW if exist "..\venv\Scripts\python.exe" set "PYW=..\venv\Scripts\python.exe"
if not defined PYW if exist "venv\Scripts\python.exe" set "PYW=venv\Scripts\python.exe"

if not defined PYW (
    echo.
    echo [ERROR] Python not found.
    echo Expected one of:
    echo   %LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe
    echo   ..\venv\Scripts\pythonw.exe
    echo   ..\venv\Scripts\python.exe
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
