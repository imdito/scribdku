#!/usr/bin/env bash
# Pasang Scribdku ke menu aplikasi Linux — biar muncul di pencarian (GNOME/COSMIC/dll).
set -euo pipefail
cd "$(dirname "$0")"
APP_DIR="$PWD"
APPS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"
mkdir -p "$APPS_DIR" "$ICONS_DIR"
cp scribdku.png "$ICONS_DIR/scribdku.png"
cat > "$APPS_DIR/scribdku.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Scribdku
Comment=Pengunduh dokumen Scribd (lokal)
Exec=bash "$APP_DIR/run.sh"
Path=$APP_DIR
Icon=scribdku
Terminal=true
Categories=Network;Utility;
Keywords=scribd;download;unduh;pdf;dokumen;
StartupNotify=true
DESKTOP
chmod +x "$APPS_DIR/scribdku.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true
echo "Terpasang. Cari 'Scribdku' di pencarian aplikasi (mungkin perlu beberapa detik / login ulang)."
echo "Jangan pindahkan folder app ini setelah memasang; kalau pindah, jalankan install-linux.sh lagi."
