@echo off
REM Scribdku - jalan langsung tanpa Docker (Windows).
REM Butuh: Python 3.10+ (dari python.org, centang "Add to PATH") dan Google Chrome.
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python belum ada. Pasang Python 3.10+ dari python.org dulu. & pause & exit /b 1)

if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan environment Python (.venv)...
  %PY% -m venv .venv || (echo Gagal membuat .venv & pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r server\requirements.txt

if "%SCRIBD_DATA_DIR%"=="" set SCRIBD_DATA_DIR=%CD%\data
if "%SCRIBD_PORT%"=="" set SCRIBD_PORT=8080
start /b powershell -NoProfile -WindowStyle Hidden -Command "$u='http://localhost:%SCRIBD_PORT%/api/health'; for($i=0;$i -lt 60;$i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $u | Out-Null; Start-Process 'http://localhost:%SCRIBD_PORT%'; break } catch { Start-Sleep -Seconds 2 } }"
echo Scribdku jalan di http://localhost:%SCRIBD_PORT% - tutup jendela ini untuk berhenti.
.venv\Scripts\python.exe -m uvicorn app:app --app-dir server --host 127.0.0.1 --port %SCRIBD_PORT%
pause
