@echo off
setlocal
cd /d "%~dp0"
echo Starting the Aperture workspace and local gateway.
echo Execution requires a configured gateway and an authenticated worker.
start "Aperture Frontend" cmd /c call "%~dp0start_frontend.bat"
start "Aperture Backend" cmd /c call "%~dp0start_backend.bat"
echo Open http://127.0.0.1:3000 after the frontend reports ready.
echo For isolated execution, configure backend/.env and backend/.worker.env, then run start_worker.bat with Docker available.
echo For the complete reviewed local preview, use start_preview.bat instead.
