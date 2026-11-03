@echo off
setlocal
cd /d "%~dp0"

rem ---- OpenDroidEmu (ODE) - builds dist\OpenDroidEmu\OpenDroidEmu.exe
rem ---- folder build (not onefile), no console window, icon = assets\icon.ico

if exist build rmdir /s /q build
if exist dist\OpenDroidEmu rmdir /s /q dist\OpenDroidEmu

pyinstaller --noconfirm --clean --onedir --noconsole --name OpenDroidEmu --icon "assets\icon.ico" --add-data "assets;assets" --paths "." OpenDroidEmu.py

if errorlevel 1 (
    echo.
    echo Build failed. Make sure PyInstaller and PyQt5 are installed:  pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo Done: dist\OpenDroidEmu\OpenDroidEmu.exe
echo The core\ and data\ folders are created next to the exe on first run.
pause
