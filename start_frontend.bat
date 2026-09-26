@echo off
setlocal
title Aperture - Frontend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Frontend
set "APERTURE_EXIT=%ERRORLEVEL%"
if not "%APERTURE_EXIT%"=="0" pause
exit /b %APERTURE_EXIT%
