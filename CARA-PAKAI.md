# Scribdku — app lokal

Pengunduh dokumen Scribd (PDF/DOCX/TXT) untuk dokumen yang berhak kamu akses.
Jalan 100% lokal di komputermu — tidak ada login, tidak ada server publik.

## Syarat
- Docker + Docker Compose (Linux: Docker Engine; Windows: Docker Desktop, mode Linux containers)

## Jalan
- Linux/macOS: `./run.sh`
- Windows: klik dua kali `run.bat`

App terbuka di http://localhost:8080 (ganti lewat env `SCRIBD_PORT`).

## Berhenti
- Linux/macOS: `./stop.sh`
- Windows: `stop.bat`

Data job tersimpan di volume Docker `scribd-data` (retensi file 7 hari).
Matikan total + hapus data: `docker compose down -v`.

## Catatan
- Tanpa login: jangan expose port ini ke internet; app ini untuk jaringan lokal saja.
- Job mengunduh lewat Chrome headless di dalam container; beberapa dokumen bisa
  diblokir Scribd (Client Challenge) tergantung reputasi IP.
- Mode headful: set `SCRIBD_HEADLESS=0`. Proxy: set `SCRIBD_PROXY` (http://user:pass@host:port).
