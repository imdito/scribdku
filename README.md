# Scribd Downloader — Web UI + API

UI web dari desain **Scribd Downloader — Exaggerated Minimalism** yang terhubung
langsung ke backend Python `scribd-downloader` (Selenium + headless Chrome).
Semua progres di UI nyata: jumlah halaman, fase converting, error, file hasil,
cancel, dan history dari server. Akses dilindungi login; setiap user bisa
menambah user lain.

## Quick start (Docker)

```bash
cd "/home/Imdito/scribd downloader"
docker compose up -d --build
```

Buka <http://localhost:8080>. Port host bisa diganti:

```bash
SCRIBD_PORT=9000 docker compose up -d --build
```

Cek status:

```bash
docker compose ps
curl -s http://localhost:8080/api/health
docker compose logs -f
```

Hentikan:

```bash
docker compose down          # data unduhan tetap di volume
docker compose down -v       # hapus juga semua file & history
```

## Login

Saat volume `/data` masih kosong, akun awal dibuat otomatis:

| | |
|---|---|
| Username | `ditok` |
| Password | `tokditok` |

Setiap user yang login bisa menambah user lain lewat menu **USERS** di UI atau
`POST /api/auth/users`. Tidak ada role: semua user punya hak yang sama.
Username 3–32 karakter (huruf/angka/`.`/`-`/`_`), password 6–128 karakter.

Ganti kredensial awal **sebelum start pertama**:

```bash
SCRIBD_DEFAULT_USERNAME=admin \
SCRIBD_DEFAULT_PASSWORD='password-yang-lebih-panjang' \
docker compose up -d --build
```

Jika `users.json` sudah ada, env tersebut tidak mengubah apa pun. Menghapus
`/data/users.json` akan membuat ulang akun awal dan **menghapus semua user lain**.
Sesi login berlaku 7 hari (`SCRIBD_SESSION_DAYS`).

## Arsitektur

```
Browser
  │  UI statis (index.html, app.js, styles.css)
  ▼
FastAPI  ──►  antrean job (1 worker)  ──►  runner.py (subprocess)
  │                                          │
  │                                          ├─ import scribd-downloader.py apa adanya
  │                                          ├─ headless Chromium + chromedriver
  │                                          └─ parse stdout → progress per halaman
  ▼
/data/jobs/<id>/<nama>.<pdf|docx|txt> + /data/jobs.json
```

- Backend asli tidak diubah. `server/backend_bridge.py` meng-import
  `scribd-downloader/scribd-downloader.py` lewat path.
- Satu job = satu subprocess. Cancel = terminate seluruh process group
  (termasuk Chrome), sehingga tidak ada browser menggantung.
- Job disimpan sebagai JSON dan file di volume `/data`; retensi **7 hari**
  (bisa diubah lewat `SCRIBD_JOB_TTL_DAYS`).
- Default hanya **1 job** berjalan sekaligus karena satu Chrome bisa memakai
  1–2,5 GB RAM. Job lain masuk antrean dan UI menampilkan posisinya.

## Format

| Format | Didukung | Catatan |
|---|---|---|
| PDF | ✅ | Paling setia ke tampilan Scribd |
| DOCX | ✅ | Editable, mempertahankan font/warna/gambar |
| TXT | ✅ | Teks + penanda `===== Page N =====` |
| PPTX | ❌ | Dihapus dari UI karena backend tidak mendukung |

## API

Semua endpoint di bawah `/api/` membutuhkan cookie sesi, kecuali
`/api/health` dan `/api/auth/login`. Login mengembalikan cookie
`HttpOnly` + `SameSite=Lax`.

| Method | Path | Keterangan |
|---|---|---|
| `POST` | `/api/auth/login` | Body `{"username","password"}` → set cookie sesi |
| `GET` | `/api/auth/me` | User yang sedang login (401 bila belum) |
| `POST` | `/api/auth/logout` | Hapus cookie sesi |
| `GET` | `/api/auth/users` | Daftar user (tanpa hash password) |
| `POST` | `/api/auth/users` | Body `{"username","password"}` → user baru (`201`) |
| `POST` | `/api/jobs` | Body `{"url": "...", "format": "pdf\|docx\|txt"}` → `202` + job |
| `GET` | `/api/jobs` | Semua job, terbaru dulu (termasuk yang sedang berjalan) |
| `GET` | `/api/jobs/{id}` | Status live: `status`, `phase`, `progress`, `pages_done`, `pages_total`, `message`, `error`, `size_bytes` |
| `POST` | `/api/jobs/{id}/cancel` | Batalkan job queued/running |
| `GET` | `/api/jobs/{id}/file` | Unduh file hasil (attachment, nama asli) |
| `DELETE` | `/api/jobs/{id}` | Hapus satu job selesai + filenya |
| `DELETE` | `/api/jobs` | Bersihkan semua history yang tidak aktif |
| `GET` | `/api/health` | Healthcheck Docker (publik) |
| `GET` | `/api/config` | Format yang didukung + retensi |
| `GET` | `/api/docs` | Dokumentasi OpenAPI interaktif |

Contoh:

```bash
# login (simpan cookie)
curl -c cookies.txt -s -X POST http://localhost:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"ditok","password":"tokditok"}'

# buat user baru
curl -b cookies.txt -s -X POST http://localhost:8080/api/auth/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"budi","password":"rahasia123"}'

# mulai download
curl -b cookies.txt -s -X POST http://localhost:8080/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.scribd.com/document/123456789/Judul","format":"pdf"}'

curl -b cookies.txt -s http://localhost:8080/api/jobs/<id>
curl -b cookies.txt -OJ http://localhost:8080/api/jobs/<id>/file
```

Status job: `queued → running → completed | failed | cancelled`.
Error memakai kode stabil (`invalid_url`, `not_found`, `blocked`, `private`,
`bad_password`, `timeout`, `browser_error`, `server_restart`, …) dan pesan
berbahasa Indonesia.

## Environment variables

| Variable | Default | Fungsi |
|---|---|---|
| `SCRIBD_PORT` | `8080` | Port host (compose) |
| `SCRIBD_MAX_CONCURRENT` | `1` | Job paralel; naikkan hanya jika RAM cukup |
| `SCRIBD_JOB_TTL_DAYS` | `7` | Umur file & history sebelum dihapus otomatis |
| `SCRIBD_JOB_TIMEOUT` | `3600` | Batas waktu satu job (detik) |
| `SCRIBD_EXPORT_BATCH_SIZE` | `8` | Halaman yang dimuat sekaligus oleh Chrome |
| `SCRIBD_CDP_TIMEOUT` | `600` | Timeout `Page.printToPDF` (detik) |
| `SCRIBD_PAGE_LOAD_TIMEOUT` | `120` | Timeout memuat satu batch halaman |
| `SCRIBD_DATA_DIR` | `/data` | Lokasi history, file, user & session key |
| `SCRIBD_WEB_DIR` | `/app/web` | Lokasi UI statis |
| `SCRIBD_BACKEND_SCRIPT` | `/app/backend/scribd-downloader.py` | Script backend asli |
| `SCRIBD_DEFAULT_USERNAME` | `ditok` | Akun awal, hanya saat `users.json` belum ada |
| `SCRIBD_DEFAULT_PASSWORD` | `tokditok` | Password akun awal, hanya saat init pertama |
| `SCRIBD_SESSION_DAYS` | `7` | Umur cookie sesi login |
| `SCRIBD_COOKIE_SECURE` | `0` | Set `1` bila diakses lewat HTTPS |
| `SCRIBD_LOG_LEVEL` | `INFO` | Level log server |

Semua variabel `SCRIBD_*` milik backend (mis. `SCRIBD_HEADLESS`,
`SCRIBD_DOCUMENT_READY_TIMEOUT`) juga bisa diteruskan lewat compose.

## Data & retensi

- History job: `/data/jobs.json`
- File: `/data/jobs/<job-id>/`
- User: `/data/users.json` (hash scrypt, tanpa password plaintext)
- Session key: `/data/session.key` (HMAC untuk cookie login)
- File dan entri history dihapus otomatis setelah 7 hari (dicek saat startup
  dan setiap jam). User tidak ikut dihapus.
- Job yang sedang berjalan saat container mati akan ditandai `failed`
  (`server_restart`) — aman, tidak menggantung.
- Antrean berjalan **di dalam satu proses**. Jalankan satu replika container
  (atau satu proses uvicorn); jangan scale-out tanpa menambahkan queue eksternal.

> **Keamanan:** Seluruh endpoint `/api/` (kecuali health & login) dilindungi
> cookie sesi HttpOnly + SameSite=Lax; password di-hash dengan scrypt. Namun
> aplikasi ini tidak menyediakan TLS sendiri — jalankan di belakang reverse
> proxy HTTPS, set `SCRIBD_COOKIE_SECURE=1`, dan jangan ekspos lewat HTTP polos
> karena password dikirim saat login. `jobs.json` berisi URL asli (termasuk
> `secret_password` bila dipakai); `users.json` berisi hash password. Batasi
> akses ke volume `/data`.

Backup volume:

```bash
docker run --rm -v scribd-downloader_scribd-data:/data -v "$PWD":/backup \
  alpine tar czf /backup/scribd-data.tgz -C /data .
```

Bind mount (mis. `./data:/data`) perlu di-`chown` ke UID container (`10001`):

```bash
mkdir -p data && sudo chown -R 10001:10001 data
```

## Menjalankan tanpa Docker (development)

Butuh Python 3.10+, Google Chrome/Chromium, dan ChromeDriver.

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

export SCRIBD_DATA_DIR="$PWD/data"
export SCRIBD_BACKEND_SCRIPT="$PWD/scribd-downloader/scribd-downloader.py"
export SCRIBD_WEB_DIR="$PWD/scribd-downloader-web/scribd-downloader-web"
export CHROME_BIN="$(command -v chromium || command -v google-chrome)"
export CHROMEDRIVER="$(command -v chromedriver)"

.venv/bin/uvicorn app:app --app-dir server --host 127.0.0.1 --port 8080
```

Buka <http://127.0.0.1:8080>. UI **tidak** bisa dibuka lewat `file://` karena
butuh API yang sama-origin.

Testing parser (tanpa Chrome):

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest server/tests -q
```

## Troubleshooting

| Gejala | Penyebab / solusi |
|---|---|
| `address already in use` saat compose up | Port 8080/8000 dipakai proses lain. Set `SCRIBD_PORT` lain. |
| Error `blocked` / Cloudflare | IP datacenter/VPS sering ditolak Scribd. Coba jaringan rumahan atau tunggu. |
| `browser_error` | Chromium/chromedriver gagal start. Cek `docker compose logs`; pastikan `shm_size` cukup. |
| Dokumen besar lambat | Wajar: Chrome mencetak tiap halaman. Naikkan `SCRIBD_CDP_TIMEOUT`, turunkan `SCRIBD_EXPORT_BATCH_SIZE` bila RAM terbatas. |
| File hilang setelah 7 hari | Retensi default. Unduh sebelum kedaluwarsa atau naikkan `SCRIBD_JOB_TTL_DAYS`. |
| Lupa password / ingin reset akun | Hapus `/data/users.json` lalu restart — akun awal dibuat ulang, **semua user lain ikut terhapus**. |
| Login berhasil tapi kembali ke halaman login | `SCRIBD_COOKIE_SECURE=1` dipakai diakses lewat HTTP. Set `0` untuk HTTP lokal, atau akses lewat HTTPS. |
| Tidak bisa menambah user | Username harus 3–32 karakter dan belum dipakai; password 6–128 karakter. |

## Struktur

```
.
├── Dockerfile
├── docker-compose.yml
├── server/                     # API + worker (baru)
│   ├── app.py
│   ├── auth.py
│   ├── jobs.py
│   ├── runner.py
│   ├── backend_bridge.py
│   ├── protocol.py
│   ├── requirements.txt
│   └── tests/
├── scribd-downloader/          # backend asli (tidak diubah)
└── scribd-downloader-web/      # UI (login, download, history, users)

## Batasan & disclaimer

- Login memakai akun lokal. Semua user punya hak sama (termasuk menambah user);
  belum ada role admin, hapus user, atau ganti password mandiri.
- History dan file unduhan **dibagi antar semua user** (belum ada isolasi data
  per user). Siapa pun yang login bisa melihat dan mengunduh hasil job user lain.
- Tidak ada TLS bawaan — gunakan reverse proxy HTTPS bila diakses dari jaringan.
- Tidak ada OCR: dokumen scan hanya menghasilkan gambar (DOCX) atau teks kosong (TXT).
- Gunakan hanya untuk dokumen yang memang berhak kamu akses. Patuhi hak cipta
  dan Terms of Service Scribd.
