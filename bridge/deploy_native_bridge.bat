@echo off
REM The default deployment for this fork is explicitly Vectorworks 2027.
powershell -NoProfile -File "%~dp0deploy_2027.ps1"
exit /b %errorlevel%
