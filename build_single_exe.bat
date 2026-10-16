@echo off
title FastPOS Windows Single-File .EXE Builder
color 0A
echo ====================================================================
echo        FastPOS Premium - Standalone Single-File .EXE Builder
echo ====================================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Please install Python 3.10+.
    pause
    exit /b 1
)

echo [Step 1/2] Installing requirements...
pip install -r requirements.txt

echo.
echo [Step 2/2] Packaging into a single standalone FastPOS.exe...
pyinstaller --clean -y --onefile --windowed --icon=icon.ico --add-data="icon.png;." --add-data="icon.ico;." --add-data="pos_default.db;." --hidden-import=PyQt6 --hidden-import=PyQt6.QtCore --hidden-import=PyQt6.QtGui --hidden-import=PyQt6.QtWidgets --hidden-import=PyQt6.QtPrintSupport --hidden-import=jinja2 --hidden-import=requests --hidden-import=barcode --hidden-import=barcode.codex --hidden-import=sqlite3 --name="FastPOS" main.py

if errorlevel 1 (
    echo [ERROR] Compilation failed.
    pause
    exit /b 1
)

echo.
echo ====================================================================
echo SUCCESS! Single-file executable created:
echo    dist\FastPOS.exe
echo.
echo You can send this single "FastPOS.exe" file directly to any Windows PC!
echo ====================================================================
pause
