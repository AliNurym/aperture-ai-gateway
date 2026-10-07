@echo off
setlocal
title Aperture — Presentation Preview
color 0B

echo ===================================================================
echo   APERTURE — Presentation Preview
echo ===================================================================
echo.

if exist "backend\venv\Scripts\python.exe" (
    "backend\venv\Scripts\python.exe" scripts\pitch_demo.py
) else (
    python scripts\pitch_demo.py
)

pause
