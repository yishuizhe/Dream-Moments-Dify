@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title My Dream Moments
cd /d "%~dp0"

set "PYTHON_CMD="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON_CMD (
  where py >nul 2>&1 && for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_CMD=%%I"
)
if not defined PYTHON_CMD set "PYTHON_CMD=python"

"%PYTHON_CMD%" --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed. Please install Python 3.12.
  pause
  exit /b 1
)

for /f "tokens=2" %%I in ('"%PYTHON_CMD%" -V 2^>^&1') do set PYTHON_VERSION=%%I
for /f "tokens=1,2 delims=." %%A in ("!PYTHON_VERSION!") do (
  set MAJOR_VERSION=%%A
  set MINOR_VERSION=%%B
)
if not "!MAJOR_VERSION!"=="3" (
  echo Need Python 3.10-3.12, current: !PYTHON_VERSION!
  pause
  exit /b 1
)
if !MINOR_VERSION! LSS 10 (
  echo Need Python 3.10-3.12, current: !PYTHON_VERSION!
  pause
  exit /b 1
)
if !MINOR_VERSION! GEQ 13 (
  echo Python 3.13+ is not supported. Current: !PYTHON_VERSION!
  echo Please use Python 3.12.
  pause
  exit /b 1
)

set VENV_DIR=.venv
if not exist %VENV_DIR% (
  echo Creating virtual environment...
  "%PYTHON_CMD%" -m venv %VENV_DIR%
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

call %VENV_DIR%\Scripts\activate.bat

if exist requirements.txt (
  echo Installing dependencies...
  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
  if errorlevel 1 (
    echo Dependency install failed.
    pause
    exit /b 1
  )
)

echo Starting program...
python run_config_web.py
if errorlevel 1 (
  echo Program error.
  pause
)
deactivate