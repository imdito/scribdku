@echo off
REM Lepas Scribdku dari Start Menu Windows.
powershell -NoProfile -Command "Remove-Item ([IO.Path]::Combine($env:APPDATA, 'Microsoft\Windows\Start Menu\Programs\Scribdku.lnk')) -ErrorAction SilentlyContinue"
echo Scribdku dilepas dari Start Menu. Folder app tidak dihapus.
pause
