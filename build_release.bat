@echo off
chcp 65001 >nul
title Building GeoHideManager Release EXE
cd /d "%~dp0"

echo ====================================================
echo Starting PyInstaller build for GeoHideManager.exe...
echo Mode: OneFile, NoConsole, Icon embedded, Domains JSON embedded
echo ====================================================

taskkill /F /IM GeoHideManager.exe >nul 2>&1
timeout /t 1 >nul

python -m PyInstaller --noconsole --onefile --clean --noconfirm --icon=icon.ico --add-data "icon.ico;." --add-data "icon.png;." --add-data "geohide_domains.json;." --name="GeoHideManager" app.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ====================================================
    echo BUILD SUCCESSFUL!
    echo Output binary: dist\GeoHideManager.exe
    echo ====================================================
) else (
    echo.
    echo ====================================================
    echo BUILD FAILED with error code %ERRORLEVEL%.
    echo ====================================================
)

echo.
echo Build process finished.
timeout /t 5