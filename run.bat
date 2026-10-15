@echo off
chcp 65001 >nul
title GeoHide DNS Switcher Launcher
cd /d "%~dp0"

echo ====================================================
echo Starting GeoHide DNS Manager...
echo Requesting administrator privileges if needed...
echo ====================================================

python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
