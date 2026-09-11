@echo off
title Aperture AI - AI Sentinel Oracle (Port 8000)
cd /d "%~dp0backend"
echo ========================================================
echo  Aperture AI Oracle: AST Guard ^& Pyth Hermes Oracle
echo ========================================================
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
) else (
    echo [!] Virtual environment not detected. Initializing venv...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
    python -m uvicorn main:app --host 127.0.0.1 --port 8000
)
pause
