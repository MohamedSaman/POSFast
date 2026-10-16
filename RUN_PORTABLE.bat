@echo off
setlocal enabledelayedexpansion
title FastPOS Quick Launcher
color 0B

set "PY_CMD="
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=py"
    )
)

if "%PY_CMD%"=="" (
    echo.
    echo ====================================================================
    echo [!] Python is not found on your PC.
    echo Please run "INSTALL_FASTPOS.bat" first - it will install everything!
    echo ====================================================================
    echo.
    pause
    exit /b 1
)

:: Preload default database if pos_local.db doesn't exist yet
if not exist "pos_local.db" (
    if exist "pos_default.db" (
        copy /y "pos_default.db" "pos_local.db" >nul 2>&1
    )
)

:: Quick check for PyQt6
%PY_CMD% -c "import PyQt6" >nul 2>&1
if errorlevel 1 (
    echo Installing required libraries (one-time setup, please wait)...
    %PY_CMD% -m pip install -r requirements.txt
)

echo Starting FastPOS Premium Terminal...
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw main.py
) else (
    start "" %PY_CMD% main.py
)
exit /b 0
