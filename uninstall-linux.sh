#!/usr/bin/env bash
rm -f "$HOME/.local/share/applications/scribdku.desktop" "$HOME/.local/share/icons/scribdku.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" || true
echo "Scribdku dilepas dari menu aplikasi. Folder app tidak dihapus."
