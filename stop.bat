@echo off
REM Scribdku - matikan app lokal. Data job tetap tersimpan di volume Docker.
cd /d "%~dp0"
docker compose down
echo Scribdku berhenti.
pause
