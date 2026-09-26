@echo off
setlocal
title Aperture - Backend
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Backend
set "APERTURE_EXIT=%ERRORLEVEL%"
if not "%APERTURE_EXIT%"=="0" pause
exit /b %APERTURE_EXIT%
