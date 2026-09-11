@echo off
title Aperture AI - Physical Silicon Worker (NVIDIA RTX 3050)
cd /d "%~dp0backend"
echo ========================================================
echo  Aperture DePIN Worker Node: Physical Hardware Daemon
echo ========================================================
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -u worker.py --node-id NODE-HOST-GPU-01 --wallet 7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ
) else (
    python -u worker.py --node-id NODE-HOST-GPU-01 --wallet 7wFo7q4EHfKrBNpL4XLXXWAi9TcE6BD27ZoQoBqtFcNQ
)
pause
