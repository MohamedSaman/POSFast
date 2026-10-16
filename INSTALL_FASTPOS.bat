@echo off
setlocal enabledelayedexpansion
title FastPOS Premium - 1-Click Windows Auto-Installer
color 0B

echo ===============================================================================
echo                ⚡ FASTPOS PREMIUM - 1-CLICK WINDOWS INSTALLER ⚡
echo ===============================================================================
echo.
echo  Welcome to the FastPOS Automated Setup!
echo  This installer will configure everything and create a Desktop shortcut for you.
echo.
echo ===============================================================================
echo.

:: Step 1: Detect Python
echo [1/4] Checking Python installation...
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
    echo [!] Python is not detected on your Windows system.
    echo [*] Downloading official Python 3.11 for Windows (64-bit)...
    
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', 'python_setup.exe')"
    
    if not exist python_setup.exe (
        echo [ERROR] Failed to download Python automatically.
        echo Please download and install Python from https://www.python.org/downloads/
        echo Make sure to tick: "Add python.exe to PATH"
        pause
        exit /b 1
    )
    
    echo [*] Installing Python silently into system... Please wait 30-60 seconds...
    python_setup.exe /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_test=0
    del /f /q python_setup.exe >nul 2>&1
    
    :: Refresh PATH for current cmd session
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;C:\Program Files\Python311;C:\Program Files\Python311\Scripts;%PATH%"
    set "PY_CMD=python"
)

echo [*] Python detected:
%PY_CMD% --version
if errorlevel 1 (
    echo [WARNING] Please restart this installer or your PC if Python was just installed.
    pause
    exit /b 1
)

echo.
:: Step 2: Install dependencies
echo [2/4] Installing necessary libraries & PyInstaller...
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies. Please check your internet connection.
    pause
    exit /b 1
)

echo.
:: Step 3: Build Windows Native Executable
echo [3/4] Compiling Windows Native FastPOS.exe...
%PY_CMD% -m PyInstaller --clean -y FastPOS.spec
if errorlevel 1 (
    echo [!] Standard spec build failed, compiling directly...
    %PY_CMD% -m PyInstaller --clean -y --windowed --icon=icon.ico --add-data="icon.png;." --hidden-import=PyQt6 --hidden-import=PyQt6.QtCore --hidden-import=PyQt6.QtGui --hidden-import=PyQt6.QtWidgets --hidden-import=PyQt6.QtPrintSupport --hidden-import=jinja2 --hidden-import=requests --hidden-import=barcode --hidden-import=barcode.codex --hidden-import=sqlite3 --name="FastPOS" main.py
)

if not exist "dist\FastPOS\FastPOS.exe" (
    echo [ERROR] Could not find dist\FastPOS\FastPOS.exe after compilation.
    pause
    exit /b 1
)

echo.
:: Step 4: Create Desktop & Start Menu Shortcut
echo [4/4] Finalizing setup & creating Desktop Shortcut...
set "EXE_PATH=%~dp0dist\FastPOS\FastPOS.exe"
set "WORKING_DIR=%~dp0dist\FastPOS"
set "ICON_PATH=%~dp0icon.ico"

if exist "%~dp0pos_default.db" (
    echo [*] Pre-loading offline product catalog (4,600+ items)...
    copy /y "%~dp0pos_default.db" "%WORKING_DIR%\pos_local.db" >nul
) else if exist "%~dp0pos_local.db" (
    echo [*] Pre-loading offline product catalog...
    copy /y "%~dp0pos_local.db" "%WORKING_DIR%\pos_local.db" >nul
)

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'FastPOS Premium.lnk')); $s.TargetPath = '%EXE_PATH%'; $s.WorkingDirectory = '%WORKING_DIR%'; $s.IconLocation = '%ICON_PATH%'; $s.Description = 'FastPOS Premium Terminal'; $s.Save()"

:: Also check if Inno Setup compiler is present to compile the installer wizard
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    echo [*] Found Inno Setup Compiler! Building FastPOS_Setup_v1.0.exe...
    "%ISCC%" installer.iss >nul 2>&1
    if exist "dist\FastPOS_Setup_v1.0.exe" (
        echo [OK] Full Windows Setup Wizard created at: dist\FastPOS_Setup_v1.0.exe
    )
)

echo.
echo ===============================================================================
echo  🎉 INSTALLATION COMPLETE! FastPOS IS READY TO USE!
echo ===============================================================================
echo.
echo  1. A shortcut named "FastPOS Premium" has been created on your Windows Desktop!
echo  2. The standalone application is located at:
echo     %EXE_PATH%
echo.
echo ===============================================================================
set /p LAUNCH="Would you like to launch FastPOS right now? (Y/N): "
if /i "%LAUNCH%"=="Y" (
    start "" "%EXE_PATH%"
)
echo.
echo Thank you for installing FastPOS Premium!
pause
