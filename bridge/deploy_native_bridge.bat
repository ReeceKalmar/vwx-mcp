@echo off
REM The default deployment for this fork is explicitly Vectorworks 2027.
REM Permit this local checkout script for this child process only. Domain policy still applies.
powershell -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0deploy_2027.ps1"
exit /b %errorlevel%
