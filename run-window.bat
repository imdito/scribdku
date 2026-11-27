@echo off
REM Scribdku - mode JENDELA SENDIRI (Windows): server lokal + jendela app
REM tanpa address bar/tab browser (Chrome app mode).
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python belum ada. Pasang Python 3.10+ dari python.org dulu. & pause & exit /b 1)

set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe
if "%CHROME%"=="" (echo Google Chrome tidak ditemukan - mode jendela butuh Chrome. & pause & exit /b 1)

if not exist ".venv\Scripts\python.exe" (
  echo Menyiapkan environment Python (.venv)...
  %PY% -m venv .venv || (echo Gagal membuat .venv & pause & exit /b 1)
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r server\requirements.txt

if "%SCRIBD_DATA_DIR%"=="" set SCRIBD_DATA_DIR=%CD%\data
if "%SCRIBD_PORT%"=="" set SCRIBD_PORT=8080
if not exist "%SCRIBD_DATA_DIR%" mkdir "%SCRIBD_DATA_DIR%"

curl -s -m 2 http://localhost:%SCRIBD_PORT%/api/health >nul 2>nul
if errorlevel 1 (
  start "Scribdku Server" /min .venv\Scripts\python.exe -m uvicorn app:app --app-dir server --host 127.0.0.1 --port %SCRIBD_PORT%
)
powershell -NoProfile -Command "$u='http://localhost:%SCRIBD_PORT%/api/health'; for($i=0;$i -lt 60;$i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $u | Out-Null; exit 0 } catch { Start-Sleep -Seconds 1 } }; exit 1"
if errorlevel 1 (echo Server tidak siap. & pause & exit /b 1)

"%CHROME%" --app=http://localhost:%SCRIBD_PORT% --user-data-dir="%SCRIBD_DATA_DIR%\browser-profile" --window-size=1280,860 --no-first-run --no-default-browser-check
echo.
echo Jendela Scribdku dibuka. Kalau sudah selesai, tekan Enter di sini untuk mematikan servernya.
pause >nul
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %SCRIBD_PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
