# Lomba Radar

Radar pribadi untuk hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) di Indonesia. Sasaran awal mahasiswa. Implementasi tahap 1-9 tersedia, dengan commit bertahap; [roadmap](docs/AUTOMATION_ROADMAP.md) menjelaskan cakupannya.

Aplikasi dapat mencari kandidat di luar daftar sumber, membuka artikel asli, menyimpan bukti, lalu otomatis memantau artikel dan akun Instagram yang memenuhi syarat. Website tetap bisa dipakai tanpa API model atau Instagram. Tidak ada seed lomba/dummy di database produksi.

## Mulai dari sini

Kalau aplikasi sudah terpasang: restart backend, worker, dan scheduler dengan kode terbaru, lalu buka **Pengaturan**. Gunakan **Aktivitas radar** untuk melihat hasil, kegagalan, kuota, dan kesehatan sumber. Konfigurasi provider tidak otomatis berarti credential valid.

| Kebutuhan | Yang perlu disiapkan |
| --- | --- |
| Pantau website/RSS terdaftar, termasuk OU Festival | Backend + worker; tanpa key provider |
| Pemeriksaan otomatis saat browser ditutup | Scheduler + worker tetap hidup, otomatisasi diaktifkan |
| Cari website/akun baru tanpa menyusun banyak sumber | Tavily Free API key, preferensi discovery, batas kredit gratis |
| Baca postingan akun lomba Instagram | Apify token; akun harus lolos pemeriksaan publik dan bio |
| Bantuan AI pada artikel yang sulit/tidak lengkap | Ollama dengan model lokal; opsional |
| Baca teks poster/carousel | Tesseract dan language pack; opsional |

Website/parser lokal tidak memerlukan API berbayar. Tavily memiliki paket gratis terbatas kredit; Brave dan Apify tetap mengikuti paket akun masing-masing. Aplikasi tidak menjamin semua integrasi gratis tanpa batas. AI lokal memakai RAM/storage/komputasi mesin sendiri. Provider berbayar dan otomatisasi default nonaktif; tidak ada deployment atau model yang dipasang otomatis.

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

## Aktifkan pencarian otomatis dengan Tavily Free

Lu tidak perlu mengumpulkan daftar website. Discovery mencari kandidat sendiri, membuka artikel asli, memeriksa kualitas, lalu mendaftarkan artikel yang lolos untuk dipantau pada job berikutnya.

1. Daftar di [Tavily](https://app.tavily.com/), pilih paket **Researcher / Free**, dan salin API key dari dashboard. Paket gratis saat dicek memberikan 1.000 kredit/bulan tanpa kartu kredit; **jangan aktifkan pay-as-you-go**. Lihat [kredit resmi](https://docs.tavily.com/documentation/api-credits) dan [ketentuan paket gratis](https://help.tavily.com/articles/8298987937-billing-credits-usage-limits).
2. Buka `C:\Coding\comtrack\.env` (bukan `.env.example`). Kalau belum ada, salin `.env.example` tanpa menimpa konfigurasi lama. Isi:

```dotenv
DISCOVERY_PROVIDER=tavily
DISCOVERY_PROVIDER_ENABLED=true
TAVILY_API_KEY=isi_key_tavily_lu
INSTAGRAM_PROVIDER_ENABLED=false
AI_ENABLED=false
OCR_ENABLED=false
```

3. Simpan file, lalu restart backend, worker, dan scheduler dengan perintah pada bagian setup di atas. Buka **http://127.0.0.1:8000**. Tidak perlu key Brave atau `BRAVE_COST_PER_REQUEST_USD` untuk Tavily. Key hanya disimpan di `.env`, tidak dikirim melalui chat/Git atau variabel `VITE_`.
4. Buka Pengaturan, pilih kategori dan jenjang pada Preferensi relevansi, centang **Sertakan discovery pada pencarian**, lalu simpan.
5. Pada Otomatisasi, gunakan pengaturan berikut dan klik **Simpan otomatisasi**:

| Pengaturan | Nilai awal untuk pribadi |
| --- | --- |
| Aktifkan otomatisasi website/RSS/Instagram | Centang |
| Izinkan Tavily Free | Centang |
| Interval pencarian | 360 menit (6 jam) |
| Maksimal sumber per pencarian | 10 |
| Maksimal sumber baru per pencarian | 3 |
| Maksimal halaman per sumber | 5 |
| Kredit Tavily Free per hari | 20 |
| Kredit Tavily Free per bulan | 600 |
| Izinkan provider berbayar (Brave/Apify saja) | **Tidak dicentang** |
| Batas request provider berbayar / anggaran USD | **0 / 0.00** |

6. Tunggu job otomatis berjalan, lalu buka **Aktivitas radar** dan panel **Discovery**. Provider harus tampil `tavily`, kredit lokal mulai terpakai, query/kandidat muncul, dan artikel yang lolos masuk pantauan/feed. Proses bisa memerlukan beberapa menit. `verified` hanya berarti artikel dapat diekstrak; kelayakan tetap dinilai terpisah. Tombol Cari sekarang juga memakai kredit Tavily, tetapi tidak mendaftarkan sumber baru otomatis; uji onboarding lewat job otomatis.

Basic Search dipatok `search_depth=basic`, `auto_parameters=false`, maksimal lima hasil/query, tanpa fitur answer/raw-content/images. Satu request mereservasi satu kredit. Maksimal tiga query/job; empat job/hari berarti sekitar **360 kredit per 30 hari** jika semuanya menjalankan tiga query, sebelum pencarian manual. Sumber yang belum jatuh tempo/backoff bisa membuat pemakaian lebih rendah. Query mencakup Indonesia dan variasi akun Instagram; snippet tidak dijadikan fakta lomba.

Batas harian dan bulanan memakai kalender **UTC**, berlaku bersama untuk manual/otomatis, dan disimpan sebelum request. Crash/error tetap memakai reservasi; respons sukses dapat digunakan ulang pada job yang sama. Snapshot job dan pengaturan terkini memakai batas lebih ketat. Batas bulanan maksimal 1.000; default 600 memberi ruang terhadap kredit gratis. Ledger hanya menghitung aplikasi ini, bukan aplikasi lain yang memakai akun Tavily lu. Pastikan paket akun tetap gratis dan PAYG nonaktif; aplikasi tidak mengubah billing akun.

Saat kuota habis, berhenti sampai periode berganti atau batas dinaikkan; tidak ada fallback otomatis ke Brave/provider berbayar. Provider terkunci setelah job mulai melakukan pencarian; jika mengganti provider, jalankan job baru. Jika respons Tavily melaporkan kredit selain 1/tidak menyertakan usage, integrasi ditahan persisten dan perlu diperiksa. Schema **012** menambahkan ledger Tavily dan penjagaan provider, tanpa menghapus data/ledger Brave lama.

## Instagram dan alternatif Brave (opsional)

Tavily mencari kandidat URL akun, sedangkan mengambil profil/postingan Instagram tetap memakai **Apify**. Instagram tidak otomatis menjadi gratis karena mengganti mesin discovery. Jika nanti ingin mengaktifkannya, isi `APIFY_TOKEN`, `INSTAGRAM_PROVIDER_ENABLED=true`, `INSTAGRAM_POSTS_LIMIT=5`, `APIFY_MAX_CHARGE_USD=0.05`, restart proses, kemudian aktifkan izin provider berbayar dan anggaran USD di UI. Profil dan postingan memakai run terpisah, tiap run mereservasi seluruh cap biaya. Akun harus lolos pemeriksaan publik/bio; tidak ada bypass akun private.

Brave tetap dapat dipilih eksplisit melalui `DISCOVERY_PROVIDER=brave`, `BRAVE_API_KEY`, dan `BRAVE_COST_PER_REQUEST_USD`. Brave/Apify berbagi request dan budget USD harian terpisah dari kredit Tavily Free. Tidak ada perpindahan otomatis ke Brave ketika Tavily gagal/habis kuota.

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

Doctor tidak memanggil provider/model atau menampilkan secret. Backup SQLite online mencakup WAL yang committed. Gunakan nama file baru; untuk restore hentikan API, worker, dan scheduler, simpan kondisi lama, lalu gunakan backup sebagai `DATABASE_PATH`. Schema terbaru **012**; migrasi berurutan memakai checksum dan tidak menghapus data lama. Jangan edit migrasi yang sudah diterapkan. `.env`, database/cache, build, dan hasil QA diabaikan Git.

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

Pemeriksaan akhir: **282 tes backend lulus**, build TypeScript/Vite dan `pip check` berhasil. Pemeriksaan memakai database sementara dan fixture provider eksplisit: discovery -> bukti -> onboarding web/akun -> job berikutnya -> deduplikasi feed, recovery sesudah ingest tanpa request search ganda, budget manual/otomatis, migrasi, API dan kontrol akses. Smoke HTTP produksi memeriksa frontend hasil build, Basic Auth, API aktivitas, dan guard refresh. Smoke website live berhasil mengambil EPIC OU Festival dan membuktikan fallback saat discovery belum terhubung. Laporan lokal tersimpan di `data/*-smoke-result.json`.

**Tavily/Brave/Apify live, model Ollama/OCR live, tampilan browser baru, dan build Docker belum diverifikasi.** Credential/runtime belum tersedia; tidak ada layanan berbayar, model, otomatisasi lokal atau deployment yang diaktifkan selama implementasi. Fixture pengujian tidak dimasukkan ke feed produksi.

Stack: React, TypeScript, Vite, Tailwind CSS, FastAPI, SQLite, Beautiful Soup. Tidak wajib Redis/Celery atau layanan database terpisah.
