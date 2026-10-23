@echo off
setlocal
cd /d "%~dp0"
echo Aperture unified workspace: console, gateway and reviewed CPU worker.
echo Gemini and AI Sentinel: copy backend\.env.example to backend\.env, add GEMINI_API_KEY, then restart.
echo Off-chain execution. No Docker isolation or Solana payment.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Preview
if errorlevel 1 pause
