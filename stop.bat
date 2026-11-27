@echo off
REM Scribdku - matikan server native (kalau jalan di background).
if "%SCRIBD_PORT%"=="" set SCRIBD_PORT=8080
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %SCRIBD_PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo Scribdku berhenti (kalau jalan di jendela terminal, tutup saja jendelanya).
pause
