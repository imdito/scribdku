@echo off
REM Pasang Scribdku ke Start Menu Windows - biar muncul di pencarian Start.
cd /d "%~dp0"
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $lnk = $ws.CreateShortcut([IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Scribdku.lnk')); $lnk.TargetPath = [IO.Path]::Combine($PWD.Path, 'run-window.bat'); $lnk.WorkingDirectory = $PWD.Path; $lnk.IconLocation = [IO.Path]::Combine($PWD.Path, 'scribdku.ico'); $lnk.Description = 'Pengunduh dokumen Scribd (lokal)'; $lnk.Save()"
echo Terpasang. Tekan tombol Windows lalu ketik "Scribdku".
echo Jangan pindahkan folder app ini setelah memasang; kalau pindah, jalankan install-windows.bat lagi.
pause
