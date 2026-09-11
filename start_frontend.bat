@echo off
title Aperture AI - Institutional Command Center (Port 3000)
cd /d "%~dp0frontend"
echo ========================================================
echo  Aperture Command Center: Frontend UI
echo ========================================================

set "NODE_EXE=node"
if exist "%LOCALAPPDATA%\Programs\cursor\resources\app\resources\helpers\node.exe" (
    set "NODE_EXE=%LOCALAPPDATA%\Programs\cursor\resources\app\resources\helpers\node.exe"
) else if exist "%LOCALAPPDATA%\Programs\Kimi\resources\resources\runtime\node.exe" (
    set "NODE_EXE=%LOCALAPPDATA%\Programs\Kimi\resources\resources\runtime\node.exe"
)

if not exist "node_modules\" (
    echo [!] Dependencies not found. Installing node packages...
    call npm install
)

"%NODE_EXE%" .\node_modules\vite\bin\vite.js --port 3000
pause
