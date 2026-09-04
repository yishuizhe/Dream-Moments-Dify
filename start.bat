@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Dream Moments
cd /d "%~dp0"

set "PY312=%LocalAppData%\Programs\Python\Python312\python.exe"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "VENV_PYW=%~dp0.venv\Scripts\pythonw.exe"

if exist "%VENV_PY%" (
  set "PYTHON=%VENV_PY%"
) else if exist "%PY312%" (
  echo Creating virtual environment with Python 3.12...
  "%PY312%" -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
  set "PYTHON=%VENV_PY%"
) else (
  echo Python 3.12 not found. Please install Python 3.12 first.
  echo Current default python:
  python --version 2>&1
  pause
  exit /b 1
)

echo Using:
"%PYTHON%" --version

echo Checking dependencies...
"%PYTHON%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn >nul
if errorlevel 1 (
  echo Dependency install failed. Retrying with proxy...
  set "HTTP_PROXY=http://127.0.0.1:7897"
  set "HTTPS_PROXY=http://127.0.0.1:7897"
  "%PYTHON%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
  if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
  )
)

echo Starting config page / bot...
if exist "%VENV_PYW%" (
  start "" "%VENV_PYW%" run_config_web.py
  exit /b 0
)

"%PYTHON%" run_config_web.py
if errorlevel 1 (
  echo Program exited with error.
  pause
)
