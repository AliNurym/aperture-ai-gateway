@echo off
title Aperture AI - Autonomous DePIN Grid Orchestrator
cd /d "%~dp0"

echo =========================================================================
echo    ⚡ APERTURE AI: AUTONOMOUS DePIN GRID (SOLANA DEVNET + NVIDIA SILICON)
echo =========================================================================
echo.
echo Launching 3 Grid services in separate console windows:
echo   [1/3] AI-Sentinel Oracle Gateway (Port 8000)
echo   [2/3] Physical Hardware Worker (NVIDIA GeForce RTX 3050)
echo   [3/3] Institutional Command Center UI (Port 3000)
echo.

start "Aperture Oracle Gateway (8000)" cmd /c "call start_backend.bat"
timeout /t 2 /nobreak >nul

start "Aperture Silicon Worker (RTX 3050)" cmd /c "call start_worker.bat"
timeout /t 2 /nobreak >nul

start "Aperture Command Center UI (3000)" cmd /c "call start_frontend.bat"

echo =========================================================================
echo  All 3 services successfully dispatched!
echo  Open your browser at: http://127.0.0.1:3000
echo =========================================================================
timeout /t 5
