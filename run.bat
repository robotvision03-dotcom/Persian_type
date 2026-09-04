@echo off
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
  if exist ".venv" rmdir /s /q .venv
  py -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment with "py -m venv".
    echo Install Python from https://www.python.org/downloads/ and enable "Add python.exe to PATH",
    echo or keep the "py" launcher.
    exit /b 1
  )
)

"%VENV_PY%" -m pip install --upgrade pip
"%VENV_PY%" -m pip install -r requirements.txt

if exist "C:\Users\omid\Documents\appointment\models" (
  set "MODELS_DIR=C:\Users\omid\Documents\appointment\models"
)

"%VENV_PY%" -m app --host 127.0.0.1 --port 8000
endlocal
