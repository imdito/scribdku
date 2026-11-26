@echo off
REM Scribdku - jalankan app lokal (Windows). Butuh Docker Desktop.
cd /d "%~dp0"
where docker >nul 2>nul || (echo Docker belum terpasang. Pasang Docker Desktop dulu, lalu jalankan lagi. & pause & exit /b 1)
if "%SCRIBD_PORT%"=="" set SCRIBD_PORT=8080
echo Menyiapkan Scribdku (build + start)...
docker compose up -d --build || (echo Gagal start. Pastikan Docker Desktop sedang jalan. & pause & exit /b 1)
echo Menunggu server siap di http://localhost:%SCRIBD_PORT% ...
powershell -NoProfile -Command "$u='http://localhost:%SCRIBD_PORT%/api/health'; for($i=0;$i -lt 60;$i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 $u | Out-Null; exit 0 } catch { Start-Sleep -Seconds 2 } }; exit 1"
if errorlevel 1 (echo Server belum siap. Cek log: docker compose logs & pause & exit /b 1)
echo Scribdku jalan: http://localhost:%SCRIBD_PORT%
start "" "http://localhost:%SCRIBD_PORT%"
