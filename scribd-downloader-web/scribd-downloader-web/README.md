# Scribd Downloader — Web UI

Implementasi web dari desain Figma "Scribd Downloader — Exaggerated Minimalism"
(https://www.figma.com/design/bM2fcJMGEFHJVRTOqMb0S6), sekarang **terhubung ke
backend sungguhan** lewat FastAPI dan dilindungi login.

## Isi

- `index.html` — Login, Home, Loading/Converting, Error, History, Users.
  Format: PDF, DOCX, TXT.
- `styles.css` — Exaggerated Minimalism: #000 / #FFF / #FF0000, Inter Black,
  teks outline, responsive ≤760px.
- `app.js` — memanggil API:
  - `POST /api/auth/login` + `GET /api/auth/me` + `POST /api/auth/logout`;
  - `GET/POST /api/auth/users` untuk daftar & tambah user (semua user bisa);
  - `POST /api/jobs` saat submit (URL + format pilihan user);
  - polling status nyata: persen, `halaman / total halaman`, fase, ETA;
  - `POST /api/jobs/{id}/cancel` untuk tombol CANCEL;
  - `GET /api/jobs/{id}/file` untuk tombol GET FILE / RE-DOWNLOAD;
  - `GET /api/jobs` untuk HISTORY (termasuk retry job gagal);
  - error backend ditampilkan apa adanya (invalid link, dokumen hilang,
    Cloudflare, timeout, dll).

UI tidak menyimpan history di `localStorage`; semuanya dari server. Cookie sesi
disimpan sebagai HttpOnly cookie oleh browser.

## Login

Akun awal saat server pertama kali dijalankan: **`ditok` / `tokditok`**.
Setiap user yang login bisa menambah user lain lewat menu **USERS**. Ganti
kredensial awal dengan env `SCRIBD_DEFAULT_USERNAME` / `SCRIBD_DEFAULT_PASSWORD`
sebelum start pertama.

## Jalankan

Cara termudah — lewat Docker (UI + API di satu port):

```bash
cd "/home/Imdito/scribd downloader"
docker compose up -d --build
# buka http://localhost:8080
```

Atau tanpa Docker (butuh Chrome + chromedriver):

```bash
.venv/bin/uvicorn app:app --app-dir server --host 127.0.0.1 --port 8080
```

Detail lengkap, API, env, dan troubleshooting ada di [README utama](../../README.md).
Jangan buka `index.html` langsung (`file://`) karena UI membutuhkan API
same-origin.
