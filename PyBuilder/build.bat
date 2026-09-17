@echo off
setlocal
cd /d "%~dp0"

echo === Create virtual environment ===
if not exist .venv (
  py -3 -m venv .venv
)

echo === Activate venv ===
call .venv\Scripts\activate.bat

echo === Upgrade pip ===
python -m pip install --upgrade pip

echo === Install requirements ===
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  pause
  exit /b 1
)

echo === Kill running EncBuilder.exe if any (prevents PermissionError) ===
taskkill /IM EncBuilder.exe /F >nul 2>nul
timeout /T 1 >nul 2>nul

echo === Build single-file EXE with PyInstaller ===
if exist "%~dp0dist\EncBuilder.exe" del /f /q "%~dp0dist\EncBuilder.exe" >nul 2>nul

set ADDDATA=
if exist assets (
  set ADDDATA=--add-data "assets;assets"
)

echo Running: python -m PyInstaller --noconfirm --clean --noconsole --onefile --name EncBuilder %ADDDATA% app.py
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --noconsole ^
  --onefile ^
  --name EncBuilder ^
  %ADDDATA% ^
  app.py
if errorlevel 1 (
  echo [ERROR] PyInstaller failed
  pause
  exit /b 1
)

echo.
echo Done. Find EXE here:
echo   %~dp0dist\EncBuilder.exe
pause
