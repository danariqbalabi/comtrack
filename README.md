# Lomba Radar

Radar pribadi untuk hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) di Indonesia. Sasaran awal mahasiswa. Pencarian manual tetap tersedia; website/RSS terdaftar juga dapat diperiksa berkala saat otomatisasi diaktifkan.

## Otomatisasi · tahap 2

Tahap 2 tersedia di **Pengaturan → Otomatisasi · Tahap 2**: kontrol aktif/jeda, interval (30 menit–7 hari), jadwal berikutnya, heartbeat scheduler, dan ID job otomatis terakhir. Pengaturan tahap 1 tetap tersimpan. Batas jumlah sumber (1–30) dan halaman per sumber (1–10) sekarang diterapkan pada job otomatis. Sumber baru, gambar, dan anggaran disiapkan untuk tahap selanjutnya. Instagram tetap dibatasi ke akun publik media lomba dan penyelenggara.

Izin provider berbayar default **nonaktif**, batas request harian **0**, dan anggaran harian **USD 0.00**. Mengizinkan provider berbayar memerlukan batas request dan anggaran positif; anggaran disimpan sebagai desimal maksimal dua angka di belakang titik. Status kesiapan integrasi memeriksa konfigurasi server tanpa memanggil layanan atau menampilkan credential. Status dikonfigurasi tidak menjamin key valid atau kuota tersedia.

**Scheduler tahap 2 hanya memproses website/RSS yang sudah terdaftar** dengan adapter OU Festival, HTML publik, atau RSS. Discovery, penemuan sumber baru, Instagram, OCR, AI, dan provider berbayar belum masuk job otomatis, termasuk bila izin berbayar dicentang. Tidak ada panggilan berbayar dari scheduler. Pencarian manual tetap memakai alur/konfigurasi provider sebelumnya dan belum dibatasi kuota otomatisasi.

Konfigurasi tersimpan di `automation_settings`, jadwal di `automation_schedule`, dan snapshot konfigurasi setiap job otomatis di `automation_job_runs`, schema **005**. API `GET /api/automation` membaca konfigurasi beserta status runtime; `PUT /api/automation` menerima `{"settings":{...},"expected_version":1}`. Header mutasi, validasi origin, dan login pribadi mengikuti API lainnya. Penyimpanan dari versi lama menghasilkan HTTP 409 agar perubahan tab/proses lain tidak tertimpa. Pengaturan tidak mengubah preferensi relevansi atau sumber pantauan.

Untuk mulai: **restart backend dan worker dengan kode terbaru**, jalankan scheduler di terminal tambahan, lalu centang **Aktifkan otomatisasi website/RSS → Simpan otomatisasi**. Aktivasi pertama jatuh tempo segera. Membiarkan kotak tersebut kosong mempertahankan mode manual.

```powershell
.\.venv\Scripts\python.exe -m backend.app.scheduler
```

Jalankan backend, worker, dan scheduler sebagai tiga proses server. Scheduler hanya memasukkan job ke SQLite; worker mengambil web. Setelah konfigurasi disimpan, tab browser maupun API boleh ditutup, selama scheduler/worker/mesin tetap hidup. `SCHEDULER_POLL_SECONDS` default 5 detik mengatur pemeriksaan jadwal, bukan interval scraping. Status scheduler memakai heartbeat dengan toleransi minimal 30 detik dan UI diperbarui setiap 10 detik; penghentian proses tidak langsung terlihat pada saat yang sama.

Scheduler dan pencarian manual berbagi batas satu job aktif. Saat antrean sibuk, jadwal yang jatuh tempo menunggu tanpa menambah job; setelah antrean bebas, satu job dapat dibuat. Setelah downtime panjang, hanya satu job dibuat, lalu jadwal berikutnya dihitung dari waktu dispatch terbaru—tidak mengejar semua interval yang terlewat. Jika sumber melebihi batas per pencarian, pemilihan berputar menurut ID agar seluruh sumber mendapat giliran. Tanpa sumber yang sesuai, UI menampilkan alasan dan scheduler menunggu interval berikutnya. Menambahkan sumber tidak memaksa jadwal maju; gunakan Cari sekarang atau jeda/aktifkan kembali jika perlu.

Perubahan interval saat aktif menjadwalkan ulang ke waktu simpan + interval baru. Perubahan batas lainnya berlaku untuk job berikutnya; snapshot batas job yang sudah antre tidak berubah. **Jeda otomatisasi** menghentikan dispatch baru dan membuat worker melewati sumber otomatis berikutnya. Request yang sudah berjalan boleh selesai di jaringan, tetapi transaksi ingest memeriksa ulang status jeda sebelum menulis hasil. Data yang sudah disimpan sebelumnya dipertahankan; job manual tidak dibatalkan. `Ctrl+C` pada scheduler hanya menghentikan proses penjadwal; worker yang masih berjalan dapat menyelesaikan job antrean. Gunakan tombol jeda untuk menghentikan pekerjaan otomatis.

Halaman daftar/RSS ikut memakai batas halaman per sumber. Misalnya batas 1 hanya cukup membaca daftar, sehingga artikel detail belum dapat diverifikasi. Reservasi halaman disimpan di SQLite sebelum pengambilan, sehingga crash/pemulihan tidak mereset batas dan worker lama/jeda diperiksa sebelum request berikutnya. Reservasi yang sudah dibuat tidak dikembalikan bila request gagal atau proses mati. Robots, redirect dan retry HTTP internal tetap mengikuti pembatasan transport yang sudah ada; batas halaman ini menghitung panggilan pengambilan halaman, bukan jumlah paket/request HTTP. Jika batas tercapai, sumber bisa dilaporkan gagal/sebagian berhasil dengan hasil yang sudah tersimpan tetap utuh.

Periksa satu kali tanpa daemon menggunakan `python -m backend.app.scheduler --once`; perintah ini hanya memeriksa/dispatch, tidak mengambil sumber. Untuk mengulang uji live terhadap database sementara tanpa API/frontend:

```powershell
.\.venv\Scripts\python.exe -m scripts.scheduler_smoke
```

Uji langsung berhasil membuat satu job `scheduled`, memproses OU Festival nyata, menyimpan satu lomba dan bukti, membuktikan restart tidak membuat job duplikat, serta membuktikan jeda menghentikan dispatch. Batas satu halaman tercatat `used=1, limit=1`. Tidak ada provider berbayar yang digunakan. Roadmap lengkap ada di [docs/AUTOMATION_ROADMAP.md](docs/AUTOMATION_ROADMAP.md).

Verifikasi tahap 2: **159 tes backend lulus** pada salinan persis file commit, termasuk 21 tes scheduler/batas halaman, build TypeScript/Vite berhasil, dan `pip check` bersih. Migrasi mempertahankan data/job/log lama. Pemeriksaan visual UI melalui browser belum dijalankan pada tahap ini; UI divalidasi melalui build dan API/storage, sedangkan scheduler/worker diuji sebagai proses terpisah dengan sumber nyata.

## Yang sudah bekerja

- Feed dari SQLite asli: kategori, pencarian nama/penyelenggara, urutan baru ditemukan/deadline, pagination.
- Detail: timeline, biaya per tahap, eligibility, tautan sumber/pendaftaran/guidebook, semua bukti dan riwayat versi.
- Pengaturan: tambah website/RSS/Instagram, aktif/nonaktif/hapus pantauan, preferensi relevansi, dan katalog **38 kandidat sumber**.
- Worker dan scheduler terpisah, antrean/jadwal persisten, klaim atomik, heartbeat, pemulihan crash, log per sumber, penolakan penulis lama.
- Collector khusus OU Festival EPIC, RSS/Atom yang memverifikasi artikel asli, HTML artikel/daftar dengan selector CSS.
- Adapter discovery Brave Search dan Instagram Apify yang **opt-in**, serta OCR poster/carousel memakai Tesseract dan cache hash.
- PWA dengan ikon, manifest, pemasangan pada browser yang mendukung, dan shell offline. API/data lomba tidak disimpan oleh service worker.
- Frontend produksi disajikan FastAPI pada origin yang sama. Basic Authentication pribadi diwajibkan untuk `APP_ENV=production`.
- Dockerfile, Compose dengan volume persisten dan worker terpisah, serta perintah backup SQLite konsisten.

Tidak ada seed lomba atau feed dummy. Data baru disimpan setelah sumber nyata dibaca. Katalog tidak otomatis mengaktifkan 38 sumber; sebagian akun/website masih kandidat, bukan integrasi teruji. Sumber berubah struktur, memerlukan login, melarang robots, atau gagal akses akan ditampilkan sebagai gagal/belum terhubung.

## Setup lokal (Windows / PowerShell)

Prasyarat: Python 3.11+ dan Node.js 22.12+ (pengembangan memakai Python 3.13 dan Node.js 24). Jalankan dari root repository.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

Terminal pertama:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Terminal kedua:

```powershell
.\.venv\Scripts\python.exe -m backend.app.worker
```

Buka **http://127.0.0.1:8000**. Di Pengaturan, klik **Pakai sumber OU Festival yang sudah teruji**, kembali ke feed, lalu **Cari sekarang**. Tidak perlu credential untuk sumber ini. Worker bisa menyelesaikan permintaan setelah tab ditutup, selama proses worker dan server/mesin tetap hidup. API tidak perlu terus berjalan untuk worker memproses antrean yang sudah tersimpan. Untuk pencarian berkala, jalankan scheduler di terminal tambahan dan aktifkan otomatisasi seperti panduan di atas.

Untuk pengembangan frontend dengan hot reload, jalankan terminal ketiga:

```powershell
cd frontend
npm.cmd run dev
```

Buka http://127.0.0.1:5173. Proxy Vite meneruskan `/api` ke backend. Backend bisa memakai `--reload` untuk development. PWA didaftarkan hanya pada build produksi. `npm.cmd` menghindari pembatasan `npm.ps1` PowerShell. macOS/Linux: gunakan `.venv/bin/python` dan `npm`.

## Menambahkan sumber

Gunakan Pengaturan. Menyimpan sumber **tidak** langsung mengakses jaringan.

| Jenis | Perilaku |
| --- | --- |
| OU Festival | URL `https://ou-festival.com/` memakai adapter khusus berkas EPIC |
| Website artikel | Membaca `h1` dan `article`, `.entry-content`, `.post-body`, atau `main` |
| Website daftar | Isi selector **Link di daftar**, misalnya `.post-title a`; maksimal 10 artikel per job |
| Website khusus | Isi selector CSS judul/isi/link; selector yang tidak cocok menghasilkan error |
| RSS / Atom | Membaca maksimal 10 entri lalu membuka artikel asli; snippet tidak dianggap bukti terverifikasi |
| Instagram | Username atau URL profil; memerlukan konfigurasi Apify; maksimal 5 postingan secara bawaan |

Tidak ada scraper universal. Halaman JS-only, PDF, login, CAPTCHA, dan situs dengan struktur berbeda mungkin belum didukung. Tidak ada bypass kontrol akses. Adapter publik menghormati robots, timeout, batas body 2 MiB, maksimal satu retry sementara, DNS publik yang dipin ke IP tervalidasi, dan redirect hanya dalam hostname sumber/alias www. URL private/internal, credential di URL, port khusus, dan redirect ke host lain ditolak. Sumber dapat menyertakan tautan luar untuk dibuka pengguna tanpa otomatis di-crawl.

Katalog mencakup OU Festival, Sorota, Pusbisnas, Info Lomba, SIM UNS, INFEST, UGP GBIC, Unifest, INSPACE, arsip Info-lomba.com, serta kandidat Instagram termasuk `@csrelatedcompetitions` dan `@lombabisnis`. Bentuk plural CS-related Competitions dirujuk oleh [Untitled Training Camp](https://www.untitledtc.com/persiapan/daftar-akun-daging). Nama singular dari permintaan awal tetap diberi label kandidat. Username dan aktivitas akun dapat berubah; daftar tersebut tidak menjanjikan semua akun masih aktif atau dapat diambil.

## Integrasi opsional dan biaya

Monitoring website/RSS, SQLite, PWA, dan Tesseract berjalan lokal tanpa API berbayar. Hosting/mesin tetap harus tersedia. **Tidak ada pembelian atau aktivasi layanan berbayar otomatis.**

| Fitur | Konfigurasi server | Batasan |
| --- | --- | --- |
| Discovery | `BRAVE_API_KEY`, `DISCOVERY_PROVIDER_ENABLED=true`, lalu aktifkan preferensi discovery | Tiga query Indonesia/Inggris setiap permintaan manual; maksimal 10 URL kandidat diverifikasi. Tarif/kuota mengikuti provider |
| Instagram | `APIFY_TOKEN`, `INSTAGRAM_PROVIDER_ENABLED=true` | Actor `apify/instagram-scraper`, feed/carousel dari akun pilihan. Bisa dikenakan biaya; tidak ada jaminan akses semua akun |
| OCR | Pasang Tesseract; `OCR_ENABLED=true` | PNG/JPEG/WebP, maksimal 5 gambar per postingan; language pack harus tersedia. OCR dapat salah dan bukan sumber fakta pasti |

Tanpa credential/flag, sumber provider diberi **Belum terhubung** dan monitoring website lain tetap berjalan. Status **Dikonfigurasi** di UI hanya memeriksa konfigurasi, bukan jaminan key valid/kuota tersedia. Credential tidak dikirim ke frontend, source config, bukti, atau log.

Apify dibatasi `INSTAGRAM_POSTS_LIMIT` (1–20, default 5), timeout actor 60 detik, `APIFY_MAX_CHARGE_USD` (default **0.05 USD per run/per sumber**, bukan per bulan), dan tanpa retry request berbayar otomatis. Pemulihan job setelah crash dapat mengulang request provider: bukan jaminan exactly-once atau batas biaya seluruh job. Timeout koneksi provider juga bisa terjadi sesudah actor mulai; periksa dashboard provider. [Dokumentasi API Apify](https://docs.apify.com/api/v2/actor-run-sync-get-dataset-items-post), [input actor Instagram](https://apify.com/apify/instagram-scraper/input-schema), [Brave Web Search](https://api-dashboard.search.brave.com/api-reference/web/search/get).

Discovery menyimpan kandidat terpisah dari pantauan. Snippet tidak di-ingest; halaman asli perlu dibuka dan diekstrak. Label kandidat `verified` berarti ekstraksi artikel berhasil; relevansi/kelayakan tetap dinilai terpisah. Tidak ada domain baru yang otomatis dipantau. Aktifkan sumber baru secara sadar melalui formulir.

Di Windows, pasang Tesseract sendiri dan arahkan `TESSERACT_COMMAND` ke executable jika tidak ada di PATH. `OCR_LANGUAGE=eng` bawaan; gunakan `ind+eng` jika kedua language pack terpasang. Image Docker menyertakan Tesseract dan language pack Indonesia. Hash gambar+bahasa dipakai untuk cache hasil OCR di samping database; gambar boleh diunduh ulang untuk memeriksa hash, tetapi OCR tidak diulang untuk konten sama. Caption tetap dibaca jika OCR nonaktif, dengan peringatan poster belum dibaca.

## Kualitas data

- Negara/cakupan Indonesia dan jenjang mahasiswa disaring; event luar negeri/internasional eksplisit, seminar, webinar, lowongan, lomba kategori lain, dan event selesai disembunyikan.
- Fakta yang belum diketahui tetap kosong. Eligibility/tanggal/kategori belum pasti diberi alasan perlu dicek.
- Tahun/jam tidak ditebak; zona disimpan jika disebutkan. Registrasi, submission, pelaksanaan, final, dan gelombang dipisahkan. Tanggal tanpa jam tidak dianggap tutup pada awal hari deadline.
- Ekstraksi HTML/RSS/Instagram konservatif; bukan pengganti adapter khusus. Biaya yang tidak terbaca pasti disimpan sebagai kutipan tanpa mengarang angka. Dokumen/poster yang belum terbaca ditandai.
- Bukti menyimpan URL asli, teks, hash, waktu, kutipan, dan snapshot observasi. UI menampilkan seluruh bukti/versi, termasuk data yang disembunyikan dari feed.
- Identitas kategori dan edisi dijaga. Pencocokan lintas sumber memerlukan identitas konservatif; tidak ada fuzzy matching spekulatif. Konflik tidak diam-diam menimpa fakta pasti.
- Pengambilan ulang idempoten. Perubahan deadline tetap menyimpan bukti dan riwayat lama. Preferensi dan waktu dinilai ulang saat feed dibaca tanpa perlu scraping lagi.
- Konten web/poster diperlakukan sebagai data; tidak ada eksekusi instruksi sumber atau LLM dengan akses secret.

Adapter OU Festival memakai [berkas EPIC halaman utama](https://ou-festival.com/#berkas-epic), karena halaman detail pernah mengembalikan tanggal `NaN`. Pendaftaran/juknis ditautkan tanpa login. BMC gratis tidak membuat seluruh lomba dilabeli gratis: biaya tahap proposal dan syarat kelulusan tetap disimpan. Verifikasi sumber nyata 26 Oktober 2026 menghasilkan EPIC 2026/2027 dengan deadline registrasi 22 November 2026; hasil lokal bukan data bawaan aplikasi.

## Antrean dan perintah operator

```powershell
.\.venv\Scripts\python.exe -m backend.app.jobs enqueue --source ou-festival
.\.venv\Scripts\python.exe -m backend.app.jobs latest
.\.venv\Scripts\python.exe -m backend.app.worker --once
.\.venv\Scripts\python.exe -m backend.app.jobs show 1
.\.venv\Scripts\python.exe -m backend.app.jobs recover
.\.venv\Scripts\python.exe -m backend.app.collect --inspect-id 1
.\.venv\Scripts\python.exe -m backend.app.collect --list-visible
```

Ganti ID sesuai output. `collect --source ou-festival` tetap tersedia sebagai CLI sinkron. Tanpa antrean, worker tidak membuat job atau mengakses sumber. Hanya satu job aktif; refresh berulang mengembalikan ID yang sama, termasuk jika pilihan sumber berbeda. Maksimal 30 sumber/job. Job aktif menggunakan snapshot sumber saat diminta; sumber yang kemudian dihapus/nonaktif dilewati sebelum hasil disimpan.

Worker memperbarui heartbeat paling lambat 10 detik. Lease default 90 detik; pemulihan saat polling antrean/enqueue/recover/scheduler melanjutkan sumber belum selesai, maksimal tiga klaim job. Worker lama ditolak di transaksi penyimpanan. Crash sesudah ingest sebelum status sumber selesai bisa membaca sumber ulang, tetapi tidak menggandakan lomba/bukti. Setelah batas pemulihan habis, job gagal dan antrean bebas. `Ctrl+C` pada worker membatalkan job. Sumber gagal tidak membatalkan sumber lain; artikel yang sudah tersimpan tetap dipertahankan bila artikel lain gagal. API/CLI membedakan `trigger=manual` dan `trigger=scheduled`; metadata terjadwal disimpan terpisah agar tabel job lama beserta semua relasi tetap utuh.

API tersedia di `/docs`: `GET /api/competitions`, `GET /api/competitions/{id}`, sumber/preferensi, `POST /api/refresh`, serta status `/api/jobs/latest` dan `/api/jobs/{id}`. Mutasi memerlukan JSON dan header `X-Lomba-Radar: 1`; origin browser harus ada di `API_ALLOWED_ORIGINS`. Tanpa sumber aktif, refresh mengembalikan 409.

## PWA dan akses dari HP

Build produksi menyertakan manifest, ikon PNG 192/512, dan service worker untuk shell aplikasi. Browser yang mendukung menampilkan tombol Pasang. iOS: Safari → Share → Add to Home Screen. Instalasi memerlukan **HTTPS atau localhost**. Akses dari HP ke server lain memerlukan hostname HTTPS; `127.0.0.1` di HP menunjuk HP sendiri.

Offline hanya menyediakan shell aplikasi dan pesan koneksi; pencarian dan isi feed/detail memerlukan API. Service worker tidak menyimpan respons API atau credential, tidak menjalankan pencarian background, dan tidak menjanjikan seluruh data tersedia offline.

## Produksi lokal / persiapan deployment

Isi `.env` dengan `ACCESS_USERNAME` dan `ACCESS_PASSWORD` unik minimal 16 karakter. Tidak ada username/password bawaan. Tanpa pasangan credential, production menolak startup. Basic Auth memakai prompt login browser; gunakan HTTPS jika diakses melalui jaringan/internet. Ubah `API_ALLOWED_ORIGINS` menjadi origin HTTPS milik sendiri.

Dengan Docker Compose terpasang:

```powershell
docker compose up --build -d
docker compose logs -f api worker
```

Buka http://127.0.0.1:8000. Port Compose hanya terikat ke loopback. API dan worker berbagi volume `radar-data`; `docker compose down` mempertahankan volume. **Jangan pakai `down -v` jika ingin mempertahankan data.** Untuk HTTPS, letakkan reverse proxy pribadi seperti Caddy/Nginx di depan port lokal ini, dengan domain/sertifikat sendiri. Tidak ada deployment ke akun luar yang dilakukan.

Docker tidak tersedia pada mesin verifikasi saat implementasi: Dockerfile/Compose disiapkan, tetapi image/container belum diuji lewat build Docker. Compose kini juga memiliki service `scheduler` yang berbagi volume data dengan API dan worker. Untuk production tanpa Docker, set `APP_ENV=production`, build frontend, jalankan Uvicorn, worker dan scheduler memakai process manager OS. Scheduler tetap tidak mengambil apa pun selama otomatisasi nonaktif.

## Konfigurasi dan penyimpanan

Seluruh nilai/flag ada di [.env.example](.env.example). `DATABASE_PATH` default `data/lomba-radar.db`; path relatif dihitung dari root repo. `WORKER_LEASE_SECONDS` 30–3600, `WORKER_POLL_SECONDS` 0.1–30 (poll antrean, bukan jadwal scraping). `API_PROXY_TARGET` untuk Vite development. Jangan menyimpan secret di variabel `VITE_` karena bersifat publik.

Schema terbaru **005**: data lomba, sumber, bukti, riwayat, job/log, snapshot sumber, preferensi, kandidat discovery, konfigurasi/jadwal otomatisasi, dan metadata job otomatis. Startup menerapkan migrasi SQL berurutan dengan checksum tanpa menghapus data lama. Jangan mengubah file migrasi yang sudah diterapkan. SQLite memakai WAL, foreign key, transaksi dan disk lokal; bukan network share.

```powershell
.\.venv\Scripts\python.exe -m backend.app.database migrate
.\.venv\Scripts\python.exe -m backend.app.database status
.\.venv\Scripts\python.exe -m scripts.backup data/backups/radar-backup.db
```

Backup memakai SQLite online backup sehingga data WAL yang committed ikut tersalin. Pilih nama file baru. Untuk restore: hentikan API/worker, simpan salinan kondisi lama, lalu gunakan file backup sebagai `DATABASE_PATH`. OCR cache dapat dibuat ulang. `.env`, database, cache, artefak QA, dependency terpasang dan build tidak di-commit ke Git.

## Pemeriksaan

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -q
.\.venv\Scripts\python.exe -m pip check
cd frontend
npm.cmd run build
```

Tes memakai database sementara dan fixture eksplisit, mencakup kualitas data, deduplikasi, riwayat, migrasi/rollback, privasi jaringan, antrean/klaim paralel, heartbeat/crash, penulis lama, API feed/detail/pengaturan, provider opt-in, OCR cache, dan akses pribadi. Provider berbayar tidak dipanggil oleh tes. Integrasi live Apify/Brave tetap memerlukan credential milik pengguna; tes kontrak memakai mock respons, bukan bukti layanan live sudah terhubung.

**Verifikasi browser langsung 26 Oktober 2026:** Chrome desktop 1440 px dan mobile 390 px berhasil menjalankan setup sumber → pencarian OU Festival nyata → worker → feed → detail/bukti. Pencarian nama dan filter kategori bekerja, preferensi bertahan setelah reload, shell offline terbuka, tidak ada overflow horizontal mobile atau error JavaScript, dan cache service worker tidak berisi URL API. Screenshot/log tersimpan hanya di folder lokal `data/` yang diabaikan Git. Collector tambahan Sorota juga berhasil membaca satu kompetisi dari jaringan; teks petunjuk tanpa tanggal tidak dipakai sebagai fase deadline.

Pemeriksaan akhir: **128 tes backend lulus**, build TypeScript/Vite berhasil, `pip check` bersih. Backup database lokal berhasil dibaca dengan `PRAGMA integrity_check = ok`, satu lomba nyata dan schema `003` tetap utuh. Build Docker dan koneksi live provider berbayar belum diverifikasi.

Untuk mengulang uji browser opsional (mengakses OU Festival nyata, bukan provider berbayar):

```powershell
.\.venv\Scripts\python.exe -m pip install --target data/qa-tools -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m scripts.browser_smoke
```

Gunakan Chrome yang terpasang; `BROWSER_EXECUTABLE` bisa menunjuk executable browser lain. Pada OS tanpa Chrome/Chromium sistem, instal browser Playwright sendiri terlebih dahulu. Skrip membuat database sementara, credential acak khusus pengujian, API lokal dan worker; semua proses miliknya dihentikan sesudah tes, tanpa mengubah database/preferensi utama.

Stack: React, Vite, TypeScript, Tailwind CSS, FastAPI, SQLite, Beautiful Soup. Dependency runtime backend tetap pada `backend/requirements.txt`; tidak ada Redis/Celery atau layanan database terpisah yang wajib dipasang.
