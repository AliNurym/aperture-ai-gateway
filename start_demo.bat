@echo off
setlocal
title Aperture — Live Pitch & Presentation Demo
color 0B

echo ===================================================================
echo   APERTURE — Presentation & Live Pitch Demo
echo ===================================================================
echo.

if exist "backend\venv\Scripts\python.exe" (
    "backend\venv\Scripts\python.exe" scripts\demo.py
) else (
    python scripts\demo.py
)

pause
