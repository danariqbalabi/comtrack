# Lomba Radar

Radar pribadi untuk hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) di Indonesia. Sasaran awal mahasiswa. Implementasi tahap 1-9 tersedia, dengan commit bertahap; [roadmap](docs/AUTOMATION_ROADMAP.md) menjelaskan cakupannya.

Aplikasi dapat mencari kandidat di luar daftar sumber, membuka artikel asli, menyimpan bukti, lalu otomatis memantau artikel dan akun Instagram yang memenuhi syarat. Website tetap bisa dipakai tanpa API model atau Instagram. Tidak ada seed lomba/dummy di database produksi.

## Mulai dari sini

Kalau aplikasi sudah terpasang: restart backend, worker, dan scheduler dengan kode terbaru, lalu buka **Pengaturan**. Gunakan **Aktivitas radar** untuk melihat hasil, kegagalan, kuota, dan kesehatan sumber. Konfigurasi provider tidak otomatis berarti credential valid.

| Kebutuhan | Yang perlu disiapkan |
| --- | --- |
| Pantau website/RSS terdaftar, termasuk OU Festival | Backend + worker; tanpa key provider |
| Pemeriksaan otomatis saat browser ditutup | Scheduler + worker tetap hidup, otomatisasi diaktifkan |
| Cari website/akun baru tanpa menyusun banyak sumber | Brave API, estimasi tarif, preferensi discovery, izin dan kuota provider |
| Baca postingan akun lomba Instagram | Apify token; akun harus lolos pemeriksaan publik dan bio |
| Bantuan AI pada artikel yang sulit/tidak lengkap | Ollama dengan model lokal; opsional |
| Baca teks poster/carousel | Tesseract dan language pack; opsional |

Website/parser lokal tidak memerlukan API berbayar. Brave dan Apify mengikuti paket/kuota akun masing-masing; aplikasi tidak menjamin seluruh integrasi gratis. AI lokal memakai RAM/storage/komputasi mesin sendiri. Provider berbayar dan otomatisasi default nonaktif; tidak ada deployment atau model yang dipasang otomatis.

## Setup Windows / PowerShell

Lingkungan pengembangan menggunakan Python 3.13 dan Node.js 24. Jalankan dari root repo:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m backend.app.database migrate
```

Jalankan tiap proses berikut pada terminal terpisah:

```powershell
# Terminal 1: API dan frontend hasil build
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2: pengambilan data
.\.venv\Scripts\python.exe -m backend.app.worker
```

```powershell
# Terminal 3: diperlukan untuk jadwal otomatis
.\.venv\Scripts\python.exe -m backend.app.scheduler
```

Buka **http://127.0.0.1:8000**. Untuk mencoba tanpa provider: di Pengaturan klik **Pakai sumber OU Festival yang sudah teruji**, lalu **Cari sekarang** di feed. Data berasal dari website asli. Tanpa worker, job tetap antre; tanpa scheduler, pencarian manual tetap bekerja. `Ctrl+C` menghentikan proses di terminalnya.

Untuk hot reload frontend: `npm.cmd --prefix frontend run dev`, lalu buka http://127.0.0.1:5173. Backend boleh memakai `--reload` untuk development. PWA/shell offline aktif pada build produksi; data/API tidak dicache service worker. macOS/Linux memakai `.venv/bin/python` dan `npm`.

## Aktifkan discovery dan Instagram

1. Isi environment server pada `.env`, sesuai [.env.example](.env.example). Credential tidak boleh memakai awalan `VITE_`.
2. Untuk discovery, isi `BRAVE_API_KEY`, `DISCOVERY_PROVIDER_ENABLED=true`, serta `BRAVE_COST_PER_REQUEST_USD` berdasarkan paket akun sendiri. Estimasi wajib positif, maksimal enam desimal.
3. Untuk Instagram, isi `APIFY_TOKEN` dan `INSTAGRAM_PROVIDER_ENABLED=true`. `APIFY_MAX_CHARGE_USD` adalah cap per Actor run, default USD 0.05; profil dan postingan memakai run terpisah.
4. Restart proses setelah environment berubah. Di Pengaturan, simpan preferensi **Sertakan discovery pada pencarian**. Aktifkan otomatisasi, izin provider berbayar, dan batas request/anggaran harian positif. Isi batas sumber baru di atas 0 agar onboarding berjalan.
5. Periksa **Aktivitas radar**, kandidat website, dan kandidat Instagram. Tanpa key/izin/kuota, bagian itu ditahan dengan alasan; sumber website lain tetap diproses.

Kuota request/biaya harian UTC sekarang dipakai bersama oleh Brave dan Apify, termasuk **Cari sekarang**. Reservasi dibuat sebelum request dan tetap dihitung jika gagal/crash; request yang sama tidak dikirim ulang dalam job yang sama. Brave mereservasi estimasi tarif; Apify mereservasi seluruh cap run. Angka ini bukan tagihan aktual dan tidak mencakup pemakaian akun provider oleh aplikasi lain.

Jeda otomatisasi menghentikan pekerjaan terjadwal; pencarian manual masih dapat dipakai dengan kuota yang sama. Pencarian manual tidak mendaftarkan sumber baru otomatis. Snapshot job dan pengaturan terkini memakai batas yang lebih ketat. Schema **011** menambahkan snapshot batas job manual tanpa mengubah trigger manual.

## AI lokal dan OCR

AI opsional menggunakan Ollama di alamat tetap `127.0.0.1:11434`. Pasang model lokal sendiri, isi `AI_MODEL` sesuai model yang tersedia, lalu `AI_ENABLED=true`. Jalankan Ollama dalam mode lokal saja (`OLLAMA_NO_CLOUD=1` pada proses Ollama), sesuai [dokumentasi resmi](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features). Model cloud/metadata remote ditolak sebelum generasi. Tidak ada tool call atau eksekusi perintah dari teks sumber. Dalam Docker, loopback mengarah ke container worker sendiri; konfigurasi Compose bawaan belum menyertakan runtime Ollama.

Model hanya memilih kutipan persis dari teks asli dalam skema JSON. Kutipan yang tidak ada ditolak; tanggal/biaya diparsing kembali, bukan menerima angka buatan model. Tanggal tanpa tahun dan perbedaan dengan parser tetap perlu diperiksa. Parser biasa tetap diprioritaskan dan tetap berjalan tanpa AI. Batas default: 16.000 karakter input, 2.048 token output, timeout 45 detik per request lokal, tiga generasi per job. Cache memasukkan hash konten/URL, model, `AI_MODEL_REVISION`, dan versi prompt; naikkan revision bila bobot model berubah.

Untuk OCR isi `OCR_ENABLED=true`, `TESSERACT_COMMAND`, dan `OCR_LANGUAGE` sesuai language pack terpasang. OCR dibatasi gambar per post dan halaman per sumber; hasilnya ditandai perlu dicek terhadap gambar. Tidak ada training model wajib.

## Apa yang dipantau dan batasnya

- Website/RSS dapat ditambahkan manual dengan selector CSS opsional; RSS membuka artikel asli, tidak menjadikan snippet sebagai fakta.
- Discovery merotasi maksimal tiga query per job, maksimal lima hit per query. Kandidat di-dedup berdasarkan URL tanpa tracking, lalu dibuka dalam jatah halaman.
- Onboarding website mendaftarkan **URL artikel yang sudah terbaca dan lolos kualitas**, mulai job berikutnya. Belum merayapi seluruh domain, halaman JS-only, PDF, login, atau CAPTCHA secara universal. Tidak mengikuti link artikel untuk crawling (0 hop tautan).
- Kandidat harus sesuai kategori/Indonesia/syarat peserta, tanpa konflik/tanggal ambigu, dan memiliki deadline pendaftaran yang belum lewat. Ini penyaringan bukti, bukan jaminan validitas penyelenggara.
- Akun Instagram ditemukan dari URL profil hasil search dan maksimal tiga link akun per artikel. Username harus cocok, flag publik eksplisit, bio jelas media lomba/penyelenggara. Akun pribadi/private ditolak; akun ambigu ditahan. Profil diperiksa lagi sebelum membaca postingan. Caption harus berasal dari owner dan URL post/reel yang cocok.
- Maksimal 30 sumber total, termasuk nonaktif dan sumber sistem. Jatah sumber baru dibagi website + Instagram, tahan restart dan penghapusan sumber. Sumber yang dinonaktifkan tidak diaktifkan ulang.
- Sumber produktif tetap interval normal; sumber tanpa perubahan diperjarang, kegagalan memakai backoff maksimal tujuh hari. Cari sekarang dapat mencoba di luar backoff.
- Deduplikasi lintas sumber memerlukan kategori/edisi/nama yang cocok dan bukti identitas tambahan. Konflik fakta, perubahan, URL/kutipan/hash, dan riwayat tetap tersimpan.

Pengamanan transport: robots, IP/DNS publik yang dipin, redirect terbatas ke hostname/alias www, timeout, ukuran maksimum 2 MiB, dan retry terbatas. URL internal/private, credential URL dan port khusus ditolak. Batas halaman menghitung pengambilan logis, bukan setiap request transport/robots/redirect. Batas terperinci dan perilaku restart ada di [panduan operasi](docs/AUTOMATION_OPERATIONS.md).

## Diagnostik, backup, produksi

```powershell
.\.venv\Scripts\python.exe -m scripts.doctor
.\.venv\Scripts\python.exe -m scripts.backup data/backups/radar-backup-baru.db
.\.venv\Scripts\python.exe -m backend.app.database status
```

Doctor tidak memanggil provider/model atau menampilkan secret. Backup SQLite online mencakup WAL yang committed. Gunakan nama file baru; untuk restore hentikan API, worker, dan scheduler, simpan kondisi lama, lalu gunakan backup sebagai `DATABASE_PATH`. Schema terbaru **011**; migrasi berurutan memakai checksum dan tidak menghapus data lama. Jangan edit migrasi yang sudah diterapkan. `.env`, database/cache, build, dan hasil QA diabaikan Git.

Produksi pribadi membutuhkan `APP_ENV=production`, `ACCESS_USERNAME`, dan password minimal 16 karakter. Build frontend dahulu. `compose.yaml` menyiapkan API/worker/scheduler dan volume database persisten; jalankan `docker compose up --build -d` setelah konfigurasi siap. Build Docker belum diuji di mesin ini karena Docker tidak tersedia. Jangan memakai mode development untuk akses publik. Hosting/mesin harus tetap hidup agar jadwal berjalan; menutup browser tidak menghentikan worker/scheduler.

## Verifikasi tahap 9

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
.\.venv\Scripts\python.exe -m pip check
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m scripts.system_smoke
# Opsional: akses website OU Festival asli, tanpa provider berbayar
.\.venv\Scripts\python.exe -m scripts.scheduler_smoke
.\.venv\Scripts\python.exe -m scripts.discovery_smoke
```

Pemeriksaan akhir: **264 tes backend lulus**, build TypeScript/Vite dan `pip check` berhasil. Pemeriksaan memakai database sementara dan fixture provider eksplisit: discovery -> bukti -> onboarding web/akun -> job berikutnya -> deduplikasi feed, recovery sesudah ingest tanpa request search ganda, budget manual/otomatis, migrasi, API dan kontrol akses. Smoke HTTP produksi memeriksa frontend hasil build, Basic Auth, API aktivitas, dan guard refresh. Smoke website live berhasil mengambil EPIC OU Festival dan membuktikan fallback saat discovery belum terhubung. Laporan lokal tersimpan di `data/*-smoke-result.json`.

**Brave/Apify live, model Ollama/OCR live, tampilan browser baru, dan build Docker belum diverifikasi.** Credential/runtime belum tersedia; tidak ada layanan berbayar, model, otomatisasi lokal atau deployment yang diaktifkan selama implementasi. Fixture pengujian tidak dimasukkan ke feed produksi.

Stack: React, TypeScript, Vite, Tailwind CSS, FastAPI, SQLite, Beautiful Soup. Tidak wajib Redis/Celery atau layanan database terpisah.
