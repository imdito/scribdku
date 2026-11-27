# Scribdku — app lokal

Pengunduh dokumen Scribd (PDF/DOCX/TXT) untuk dokumen yang berhak kamu akses.
Jalan langsung di komputermu seperti app biasa — tanpa Docker, tanpa login,
tanpa server publik.

## Syarat
- Python 3.10+ (Windows: dari python.org, centang "Add python.exe to PATH")
- Google Chrome / Chromium terpasang (kalau tidak ada, Selenium mencoba
  mengunduh Chrome sendiri saat job pertama)

## Jalan
- Linux/macOS: `./run.sh`
- Windows: klik dua kali `run.bat`

Pertama kali, script menyiapkan `.venv` dan memasang dependency (butuh internet
sebentar). Setelah itu browser otomatis membuka http://localhost:8080
(port bisa diganti lewat env `SCRIBD_PORT`).

## Berhenti
- Di jendela terminal tempat app jalan: Ctrl+C / tutup jendelanya.
- Atau jalankan `stop.sh` / `stop.bat`.

## Data
- Hasil dan riwayat job tersimpan di folder `data/` di folder app ini
  (file job retensi 7 hari). Hapus folder `data/` untuk mulai dari nol.

## Catatan
- App hanya mendengarkan di 127.0.0.1 (komputer ini saja) dan tanpa login —
  jangan diubah jadi publik.
- Sebagian dokumen bisa diblokir Scribd (Client Challenge) tergantung
  reputasi IP jaringanmu.
- Mode headful: set env `SCRIBD_HEADLESS=0`. Proxy: set `SCRIBD_PROXY`
  (format http://user:pass@host:port).

## Alternatif (Docker)
`Dockerfile` dan `docker-compose.yml` tetap tersedia kalau suatu saat ingin
jalan via container: `docker compose up -d --build`.
