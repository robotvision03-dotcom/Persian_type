@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if exist "C:\Users\omid\Documents\appointment\models" (
  set "MODELS_DIR=C:\Users\omid\Documents\appointment\models"
)
python -m app --host 127.0.0.1 --port 8000
endlocal
