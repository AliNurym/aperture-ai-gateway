@echo off
setlocal
cd /d "%~dp0"
echo Aperture local workspace: console, gateway and reviewed CPU worker.
echo Off-chain execution. No Docker isolation or Solana payment.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Preview
if errorlevel 1 pause
