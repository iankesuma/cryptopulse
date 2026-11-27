@echo off
REM ============================================
REM  CryptoPulse - live signal & price predictor
REM  http://127.0.0.1:8099
REM ============================================
cd /d "%~dp0"
if not exist data mkdir data
python app.py --open
pause
