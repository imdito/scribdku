# Scribdku

Aplikasi lokal untuk mengunduh dokumen Scribd (PDF / DOCX / TXT) — untuk
dokumen yang memang berhak kamu akses. Jalan 100% di komputermu sendiri:
tanpa server publik, tanpa login.

UI-nya bergaya *exaggerated minimalism*, dengan mode jendela sendiri
(Chrome app mode) dan entri pencarian aplikasi untuk Linux & Windows.

## Cara jalan

Syarat: **Python 3.10+** dan **Google Chrome / Chromium**.

| Mode | Linux/macOS | Windows |
| --- | --- | --- |
| Jendela sendiri (disarankan) | `./run-window.sh` | `run-window.bat` |
| Browser biasa | `./run.sh` | `run.bat` |
| Muncul di pencarian aplikasi | `./install-linux.sh` | `install-windows.bat` |

Detail lengkap ada di [CARA-PAKAI.md](CARA-PAKAI.md). Alternatif via Docker
juga tersedia (`docker compose up -d --build`).

## Kredit & lisensi

Mesin pengunduh di aplikasi ini **bukan karya saya** — Scribdku memakai
script dari repo **[themrsami/scribd-downloader](https://github.com/themrsami/scribd-downloader)**
(lisensi MIT) sebagai backend, yang di sini disertakan sebagai git submodule
di folder `scribd-downloader/`. Yang ditambahkan di repo ini adalah server
FastAPI, UI web, dan kemasan aplikasi lokalnya. Terima kasih untuk author
aslinya.

Hormati hak cipta: unduh hanya dokumen yang berhak kamu akses.

## Catatan teknis

- Server FastAPI + Selenium/Chrome; job mengunduh dirender per halaman lalu
  disusun jadi PDF/DOCX/TXT.
- Scribd memakai bot protection (DataDome): dari IP datacenter biasanya
  muncul `Client Challenge`. Jalankan dari jaringan rumahan, atau set
  `SCRIBD_PROXY` ke proxy residensial. Mode headful: `SCRIBD_HEADLESS=0`.
- App hanya mendengarkan di `127.0.0.1` dan tanpa autentikasi — memang
  dirancang untuk pemakaian pribadi di komputer sendiri.
