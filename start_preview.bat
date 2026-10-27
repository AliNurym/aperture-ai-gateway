@echo off
setlocal
cd /d "%~dp0"
echo Aperture unified workspace: console, gateway and reviewed CPU worker.
echo Models: add GEMINI_API_KEY or DEEPSEEK_API_KEY to backend\.env, then restart.
echo DeepSeek checks source with AI Sentinel. Worker owners set execution rates.
echo Off-chain execution. No Docker isolation or Solana payment.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Preview
if errorlevel 1 pause
