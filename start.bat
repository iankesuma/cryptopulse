@echo off
REM ============================================
REM  CryptoPulse - live signal & price predictor
REM  http://127.0.0.1:8099
REM ============================================
cd /d "%~dp0"
if not exist data mkdir data

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app.py --open
) else (
  echo [info] .venv belum ada, bikin + install dependensi...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  ".venv\Scripts\python.exe" app.py --open
)
pause
