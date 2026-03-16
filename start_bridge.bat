@echo off
title ReaStream Bridge
echo.
echo  ReaStream Bridge — WASAPI to FL Studio
echo  =======================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Python not found. Install from https://python.org
    echo      Make sure "Add to PATH" is checked during install.
    pause
    exit /b 1
)

:: Install dependencies if needed
pip show sounddevice >nul 2>&1
if errorlevel 1 (
    echo  Installing dependencies...
    pip install sounddevice numpy
    echo.
)

:: Run bridge with auto-detect
python "%~dp0reastream_bridge.py" -d auto -b 2.0 --block 512

pause
