@echo off
title FastPOS Windows Builder
color 0B
echo ====================================================================
echo        FastPOS Premium - Automated Windows .EXE Builder
echo ====================================================================
echo.

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found on your system!
    echo Please install Python 3.10 or higher from https://python.org
    echo IMPORTANT: Make sure to check "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

echo [Step 1/3] Installing required Python libraries & PyInstaller...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo [Step 2/3] Compiling FastPOS.exe (Optimized GUI Build)...
pyinstaller --clean -y FastPOS.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller compilation failed.
    pause
    exit /b 1
)

if exist "pos_default.db" (
    copy /y pos_default.db dist\FastPOS\pos_local.db >nul
)

echo.
echo ====================================================================
echo [Step 3/3] SUCCESS! FastPOS Windows App is Ready!
echo.
echo Executable Location:
echo    dist\FastPOS\FastPOS.exe
echo.
echo To distribute to your cashiers / clients:
echo   1. Simply zip the "dist\FastPOS" folder.
echo   2. Send it to the Windows PC.
echo   3. Extract and double-click "FastPOS.exe" to launch!
echo ====================================================================
pause
