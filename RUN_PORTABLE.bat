@echo off
title FastPOS Quick Launcher
echo Starting FastPOS...
python -m pip install -r requirements.txt >nul 2>&1
start "" pythonw main.py
