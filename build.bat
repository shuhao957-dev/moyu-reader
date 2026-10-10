@echo off
echo ================================
echo Moyu Reader - Build Script
echo ================================
echo.

echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found
    pause
    exit /b 1
)

echo [2/4] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies
    pause
    exit /b 1
)

echo [3/4] Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 (
    echo Error: Failed to install PyInstaller
    pause
    exit /b 1
)

echo [4/4] Building exe...
pyinstaller --onefile --windowed --name "MoyuReader" --icon NONE --clean reader.py

if errorlevel 1 (
    echo Error: Build failed
    pause
    exit /b 1
)

echo.
echo ================================
echo Build complete!
echo Executable: dist\MoyuReader.exe
echo ================================
pause
