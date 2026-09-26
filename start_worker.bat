@echo off
setlocal
title Aperture - Worker
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" -Service Worker
set "APERTURE_EXIT=%ERRORLEVEL%"
if not "%APERTURE_EXIT%"=="0" pause
exit /b %APERTURE_EXIT%
