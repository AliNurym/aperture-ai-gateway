@echo off
setlocal
cd /d "%~dp0"
echo Starting the Aperture workspace and local gateway.
echo The browser demo works even if the gateway needs configuration.
start "Aperture Frontend" cmd /c call "%~dp0start_frontend.bat"
start "Aperture Backend" cmd /c call "%~dp0start_backend.bat"
echo Open http://127.0.0.1:3000 after the frontend reports ready.
echo To execute trusted local workloads, configure backend/.env and run start_worker.bat separately.
