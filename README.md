# Lomba Radar

Tool pribadi untuk menemukan hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) yang diselenggarakan di Indonesia, termasuk lomba online, dengan sasaran awal mahasiswa.

Pengambilan data direncanakan hanya saat pengguna menekan **Cari sekarang**. Tidak ada pencarian berkala.

## Status: tahap 4 — kualitas data dan relevansi

Yang sudah tersedia:

- Frontend React + Vite + TypeScript, dengan Tailwind CSS.
- Backend FastAPI dan pengaturan environment server.
- Endpoint `GET /api/health` serta dokumentasi API di `/docs`.
- Halaman awal yang mengecek koneksi backend sebenarnya, dengan status loading, berhasil, gagal, dan tombol coba lagi.
- Proxy Vite agar frontend lokal mengakses backend melalui `/api` tanpa konfigurasi CORS tambahan.
- SQLite persisten dengan migrasi SQL berversi, checksum, transaksi, dan foreign key aktif.
- Model penyimpanan lomba, sumber, bukti per halaman, riwayat perubahan, job manual, log, dan preferensi.
- Repository untuk membaca/menyimpan data secara atomik, termasuk pemeriksaan versi agar penulis lama tidak menimpa pembaruan terbaru.
- Migrasi otomatis saat backend mulai; endpoint kesehatan juga membaca database.
- Adapter khusus berkas EPIC pada website OU Festival, dengan pengambilan manual melalui CLI.
- Penyimpanan hasil nyata, bukti/kutipan per field, status sumber, log, dan hasil job.
- Pembacaan ulang sumber yang sama tidak membuat lomba baru; perubahan hasil ekstraksi disimpan sebagai versi berikutnya.
- Parsing tanggal Indonesia/Inggris/ISO, periode registrasi, waktu dengan zona eksplisit, dan beberapa gelombang.
- Evaluasi kategori, cakupan Indonesia, jenjang mahasiswa, status pendaftaran, serta alasan hasil disembunyikan/perlu dicek.
- Pencocokan lintas sumber secara konservatif, bukti multisumber, asal nilai per field, dan konflik yang tidak menimpa data pasti secara diam-diam.

Belum tersedia pada tahap ini: feed lomba, worker/antrean asinkron, discovery, integrasi Instagram, OCR, dan instalasi PWA. API pengelolaan sumber dan feed belum dibuat; halaman frontend masih berupa pemeriksaan koneksi. Sumber OU Festival baru didaftarkan saat perintah pengambilan dijalankan, dan lomba hanya disimpan setelah halaman nyata berhasil dibaca. Tidak ada seed lomba atau sumber contoh saat startup.

Tahap selanjutnya: worker terpisah dan antrean job manual yang dapat dipicu frontend, termasuk pemulihan setelah crash. Pengambilan website aktif saat ini masih satu adapter OU Festival; pencocokan lintas sumber tahap 4 diuji menggunakan observasi fixture, belum mengaktifkan scraper website tambahan.

## Prasyarat

- Node.js **22.12+**; pengembangan awal diverifikasi menggunakan Node.js 24.
- Python **3.11+**; pengembangan awal diverifikasi menggunakan Python 3.13.
- npm, tersedia bersama Node.js.

Tidak perlu server database terpisah, API key, atau layanan berbayar untuk menjalankan tahap 4. SQLite dan transport HTTP memakai modul bawaan Python; parsing HTML memakai Beautiful Soup. Tahap 4 tidak menambah dependency.

## Struktur proyek

```text
comtrack/
├── backend/
│   ├── app/
│   │   ├── config.py       # Environment server
│   │   ├── main.py         # FastAPI, startup database, dan endpoint kesehatan
│   │   ├── database.py     # Koneksi, transaksi, migrasi, dan CLI
│   │   ├── models.py       # Kontrak data penyimpanan
│   │   ├── repository.py   # Operasi penyimpanan
│   │   ├── collect.py      # CLI pengambilan manual dan inspeksi hasil
│   │   ├── collectors/     # HTTP publik dan adapter OU Festival EPIC
│   │   ├── quality/        # Tanggal, relevansi, identitas, penggabungan, dan ingest atomik
│   │   └── migrations/     # Migrasi SQL berurutan
│   ├── tests/              # Tes database sementara, tanpa seed aplikasi
│   ├── requirements.in    # Dependency langsung dan rentang versi
│   └── requirements.txt   # Versi dependency yang dikunci
├── frontend/
│   ├── src/
│   │   ├── api.ts         # Pemanggilan API
│   │   ├── App.tsx        # Halaman awal dan status koneksi
│   │   ├── main.tsx       # Entry point React
│   │   └── styles.css     # Tailwind dan gaya dasar
│   ├── package-lock.json
│   └── vite.config.ts
├── .env.example
└── README.md
```

## Menjalankan di Windows / PowerShell

Semua perintah dimulai dari root repository, misalnya `C:\Coding\comtrack`.

### 1. Instalasi backend

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 2. Jalankan backend di terminal pertama

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

- Kesehatan API: <http://127.0.0.1:8000/api/health>
- Dokumentasi API: <http://127.0.0.1:8000/docs>

### 3. Instalasi dan jalankan frontend di terminal kedua

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Buka <http://127.0.0.1:5173>. Halaman menampilkan **Backend terhubung — Lomba Radar** jika FastAPI tersedia.

`npm.cmd` digunakan agar perintah tetap bekerja pada PowerShell yang membatasi eksekusi `npm.ps1`. Pengguna Command Prompt atau shell lain dapat memakai `npm`.

Hentikan masing-masing server dengan `Ctrl+C` di terminalnya.

### macOS / Linux

Gunakan `python3 -m venv .venv`, lalu ganti `.\.venv\Scripts\python.exe` dengan `.venv/bin/python` dan `npm.cmd` dengan `npm`. Jalankan Uvicorn dari root repository dan Vite dari folder `frontend` seperti alur di atas.

## Konfigurasi environment

Nilai bawaan sudah cukup untuk pengembangan lokal. Jika perlu mengganti konfigurasi:

```powershell
Copy-Item .env.example .env
```

File `.env` berada di **root repository** dan diabaikan Git. Backend dan Vite sama-sama membaca file tersebut.

| Variabel | Bawaan | Kegunaan |
| --- | --- | --- |
| `APP_NAME` | `Lomba Radar` | Nama layanan pada respons kesehatan backend |
| `APP_ENV` | `development` | Label environment backend |
| `DATABASE_PATH` | `data/lomba-radar.db` | File SQLite; path relatif dihitung dari root repository |
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | Tujuan proxy `/api` pada dev server Vite |
| `VITE_API_BASE_URL` | `/api` | Base URL API yang digunakan frontend |

Variabel berawalan `VITE_` bersifat **publik** dan masuk ke kode frontend. Credential provider nantinya hanya boleh berada di environment backend, tanpa awalan tersebut.

Restart backend dan Vite setelah mengganti `.env`. Variabel frontend juga perlu di-build ulang jika menggunakan hasil build.

Jika port backend diganti melalui opsi `--port`, sesuaikan `API_PROXY_TARGET`. Port frontend dikunci ke 5173; Vite akan memberi error jika port tersebut sedang digunakan.

## Pemeriksaan

### Mengambil lomba nyata dari website pertama

Jika virtual environment sudah tersedia dari tahap sebelumnya, perbarui dependency dahulu:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Jalankan dari root repository:

```powershell
.\.venv\Scripts\python.exe -m backend.app.collect --source ou-festival
```

Perintah ini tidak memerlukan frontend atau server FastAPI yang sedang berjalan. Prosesnya sinkron di terminal: periksa `robots.txt`, ambil HTML publik, ekstrak berkas EPIC, simpan lomba dan bukti ke SQLite, lalu cetak ringkasan JSON. `outcome` berupa `created`, `updated`, atau `unchanged`; `competition_id` menunjuk data yang tersimpan. Kegagalan menghasilkan exit code bukan nol dan dicatat sebagai kegagalan sumber/job.

Baca hasil lengkap tanpa permintaan web tambahan, dengan ID dari ringkasan sebelumnya:

```powershell
.\.venv\Scripts\python.exe -m backend.app.collect --inspect-id 1
```

Output memuat informasi lomba, bukti asli beserta hash/waktu pengambilan, dan riwayat perubahan. Ulangi perintah `--source ou-festival` untuk mengecek ulang sumber; ID lomba tetap sama untuk cabang dan edisi yang sama. Fixture pengujian tidak pernah dimasukkan oleh perintah ini.

**Sumber yang didukung:** [berkas EPIC di halaman utama OU Festival](https://ou-festival.com/#berkas-epic). Adapter mengikuti struktur khusus situs tersebut, bukan scraper universal. Cabang olimpiade, sastra, poster, trading, dan rencana BCC yang belum dirilis tidak dibuat sebagai lomba tambahan.

Informasi yang diambil mencakup nama/edisi, penyelenggara, jenjang, syarat tim, deadline registrasi, pengumpulan BMC/proposal, tanggal final mahasiswa, biaya per tahap, serta tautan halaman pendaftaran/juknis. Kutipan biaya mempertahankan syarat kelulusan BMC; lomba tidak dilabeli gratis secara keseluruhan. Basis biaya per orang/per tim tetap `unknown` karena tidak disebutkan jelas pada berkas.

Tanggal tanpa tahun eksplisit tetap kosong dengan teks asli dan penanda `needs_review`. WIB hanya disimpan jika tertulis dalam halaman; jam tidak ditambahkan tanpa bukti. Negara, venue, dan hadiah yang belum diketahui tidak diisi dengan dugaan. Status pendaftaran dihitung dari periode yang cukup jelas, dengan asal status dicatat sebagai `timeline`; pernyataan eksplisit sumber dibedakan dengan asal `source`. Final mahasiswa dipisahkan dari final SMA menggunakan keterangan dalam berkas. Adapter menandai cakupan nasional Indonesia dari berkas penyelenggara, tanpa mengarang persyaratan kewarganegaraan.

**Batasan sumber saat verifikasi:** halaman detail `/competition/53` mengembalikan HTML dengan tanggal `NaN` dan memerlukan login untuk mendaftar. Adapter memakai berkas publik pada halaman utama sebagai bukti. Tautan pendaftaran/juknis disimpan dari anchor asli, tetapi login tidak dilakukan dan isi juknis belum diambil. Label relevansi adalah hasil aturan pada informasi yang tersedia, bukan jaminan memenuhi seluruh ketentuan juknis.

Pengambilan menghormati `robots.txt` dan crawl-delay, memakai satu koneksi pada satu waktu, timeout koneksi 15 detik, batas body 2 MiB, dan maksimal satu retry untuk error sementara. `Retry-After` yang panjang membuat proses berhenti; akses tidak dicoba ulang lebih awal. Redirect diperiksa ulang dan hanya diizinkan ke hostname OU Festival yang terdaftar. DNS divalidasi sebagai alamat publik dan koneksi memakai IP hasil validasi tersebut; TLS tetap memverifikasi hostname sumber. Tidak ada bypass login, CAPTCHA, atau rendering browser.

CLI mencatat job manual langsung sebagai `running` dan menyelesaikannya sebagai `succeeded`, `failed`, atau `cancelled`. Permintaan tumpang tindih ditolak. `Ctrl+C` dicatat sebagai pembatalan; penghentian paksa proses/mesin dapat meninggalkan job aktif. Pemulihan otomatis job setelah crash akan ditambahkan bersama worker di tahap 5. Tidak ada pencarian otomatis saat aplikasi dibuka.

**Verifikasi langsung 26 Oktober 2026:** halaman nyata berhasil diproses menjadi `EPIC — OU Festival 12 (2026/2027)`, dengan deadline registrasi 22 November 2026. Pengambilan ulang terakhir menghasilkan `unchanged` pada ID yang sama. Hasil berada di database lokal yang diabaikan Git, bukan data bawaan aplikasi.

### Aturan kualitas tahap 4

Perintah pengambilan kini menjalankan alur pencocokan, penggabungan, evaluasi, dan penyimpanan dalam satu transaksi. Data dari tahap 3 tetap bisa dibaca; field kualitas baru berada dalam JSON dengan nilai bawaan, sehingga schema SQLite tetap `001` dan tidak perlu mengubah migrasi lama.

Untuk membaca daftar yang saat ini lolos preferensi, tanpa mengakses web:

```powershell
.\.venv\Scripts\python.exe -m backend.app.collect --list-visible
```

Daftar ini mengevaluasi ulang waktu dan preferensi saat dibaca. Status tersimpan bisa berubah ketika waktu berlalu; tidak perlu menghapus data atau menunggu scraping ulang. `--inspect-id` tetap menampilkan hasil lengkap, termasuk observasi yang disembunyikan, konflik, asal field, dan riwayat bukti. Feed frontend belum dibuat.

**Relevansi:** hanya kategori hackathon/BCC/BPC yang dipilih, cakupan Indonesia, dan jenjang sesuai preferensi. Lomba dengan negara asing atau scope internasional eksplisit disembunyikan. Seminar, webinar, kelas, lowongan, lomba khusus pelajar, pengumuman pemenang tanpa bukti pendaftaran baru, serta event yang jelas selesai juga disembunyikan. Informasi kategori, negara, eligibility, jurusan/institusi, atau tanggal yang belum pasti menghasilkan `needs_review` beserta alasan. Preferensi `include_unknown_eligibility=false` menyembunyikan ketidakjelasan kelayakan; `hide_closed=false` mengizinkan pendaftaran tutup, tetapi tidak menghidupkan kembali event yang sudah selesai.

**Tanggal:** tahun harus tertulis. Nama bulan Indonesia/Inggris dan ISO didukung; format numerik ambigu seperti `01/02/2030`, dua alternatif tanggal, atau kalender tidak valid tetap perlu dicek. Rentang dengan bulan/tahun bersama dapat menghasilkan awal dan akhir, tetapi `20 Desember–5 Januari 2031` tidak dipakai untuk menebak tahun awal. Teks asli selalu tersimpan. Jam hanya menjadi datetime jika zona waktunya eksplisit atau diberikan adapter dari keterangan sumber. Rentang dengan jam yang belum terpisah jelas tetap ditandai ambigu.

Tanggal tanpa jam tidak dianggap tutup pada awal hari deadline. Dengan zona diketahui, penutupan dihitung setelah hari itu berakhir di zona tersebut. Tanpa zona, penutupan baru dianggap pasti setelah tanggal tersebut berakhir di seluruh zona waktu; aturan ini tidak menambahkan jam ke data sumber. Waktu yang hanya menyebut menit diberi `time_precision=minute` dan menit tersebut tidak ditutup lebih awal dengan mengasumsikan detik nol. Beberapa gelombang dihitung bersama: gelombang berikutnya yang masih terbuka menjaga lomba tetap tersedia, dan deadline tidak diketahui tidak dianggap sudah tutup. `phase_id` atau label tahap digunakan untuk membedakan gelombang; fase tanpa identitas jelas tidak digabung dengan tebakan.

**Deduplikasi:** kategori dan edisi harus sama. Pencocokan lintas sumber juga membutuhkan nama yang sama setelah normalisasi dasar, beserta kecocokan tautan resmi, penyelenggara, atau halaman sumber. Nama kategori panjang/BCC/BPC, tanda baca, dan parameter tracking URL dinormalisasi. Fragment URL tetap disimpan karena dapat menunjuk cabang festival yang berbeda. Tidak ada fuzzy matching, penggabungan edisi berbeda, atau penggabungan BCC dan BPC dalam satu festival. Jika ada lebih dari satu record yang cocok, ingest ditolak agar tidak menggabungkan data secara keliru. Adapter masih dapat memberikan identitas deterministik untuk pengambilan ulang sumbernya sendiri.

**Konflik dan bukti:** observasi baru disimpan sebagai `_observation` di bukti, terpisah dari nilai gabungan yang dipilih. `field_provenance` mencatat URL, hash, dan kutipan asal nilai. Nilai kosong tidak menghapus fakta lama. Tanggal ambigu dan biaya yang tidak jelas tidak menimpa informasi pasti. Perbedaan antarsumber mempertahankan nilai sebelumnya dan membuat konflik berisi kedua nilai, URL, serta hash bukti. Sumber utama boleh memperbarui informasi pastinya sendiri; riwayat lama tetap tersimpan. Persetujuan baru dari sumber yang semula berbeda dapat menandai konflik `resolved`, tanpa menghapus catatannya. Konflik deadline yang belum selesai membuat status tutup perlu dicek, bukan diam-diam menyembunyikan lomba.

Pengujian lintas sumber menggunakan fixture; hanya sumber OU Festival yang benar-benar diambil dari jaringan pada tahap ini. Pemeriksaan aturan belum mencakup semua kemungkinan redaksi eligibility atau format tanggal. Konten halaman, poster, dan dokumen tetap diperlakukan sebagai data, bukan instruksi untuk mengubah preferensi atau menjalankan tindakan.

### Database dan migrasi

Backend otomatis menerapkan migrasi yang belum dijalankan saat startup. Untuk menjalankannya secara manual dari root repository:

```powershell
.\.venv\Scripts\python.exe -m backend.app.database migrate
.\.venv\Scripts\python.exe -m backend.app.database status
```

Perintah `migrate` dapat dijalankan berulang tanpa menghapus data atau mengembalikan preferensi ke nilai bawaan. Versi pertama adalah `001`. File migrasi yang sudah diterapkan tidak boleh diedit: tambahkan file bernomor berikutnya untuk perubahan schema. Checksum yang berbeda atau database dari versi aplikasi yang lebih baru akan menggagalkan startup dengan pesan kesalahan.

Migrasi baru dijalankan dalam transaksi. Jika satu perintah SQL gagal, perubahan migrasi tersebut dibatalkan. Mode WAL dan batas tunggu penguncian 15 detik dipakai untuk akses lokal antarproses. Database harus berada di disk lokal yang mendukung penguncian SQLite; jangan menaruh file aktif di network share.

| Tabel | Isi |
| --- | --- |
| `sources` | URL, adapter, konfigurasi ekstraksi, status aktif, waktu cek/berhasil, dan error terakhir |
| `competitions` | Informasi lomba terbaru, kategori, identitas deduplikasi opsional, versi, dan waktu ditemukan/dicek |
| `evidence` | URL asli, teks/kutipan, hash konten, bukti per field, serta waktu pertama/terakhir bukti diamati |
| `competition_history` | Snapshot setiap versi dan perubahan sebelum/sesudah, dengan referensi bukti |
| `collection_jobs` | Permintaan manual, status, waktu proses, heartbeat, dan ringkasan |
| `collection_logs` | Log per job/sumber; nama sumber dipertahankan jika sumber dihapus |
| `preferences` | Kategori, cakupan Indonesia, jenjang, filter pendaftaran, dan opsi discovery |
| `schema_migrations` | Versi, nama file, checksum, dan waktu penerapan migrasi |

Tanggal disimpan bersama teks asli. Tanggal, jam, zona waktu, biaya, dan hadiah yang belum diketahui tetap kosong; biaya memakai desimal agar tidak kehilangan presisi. Beberapa gelombang registrasi dapat disimpan sebagai entri timeline terpisah.

Penghapusan sumber pantauan tidak menghapus bukti lomba atau log yang sudah tersimpan. Pembaruan lomba menyimpan riwayat dan bukti dalam satu transaksi; pembacaan ulang data identik tidak menambah versi. Identitas lintas sumber dan evaluasi relevansi kini dijalankan oleh modul `quality`.

Tabel job memiliki batas satu job aktif untuk mencegah tumpang tindih. CLI tahap 3 menggunakan penyimpanan ini secara sinkron; worker, penanganan antrean, dan pemulihan otomatis setelah crash belum tersedia. Tidak ada timer atau pencarian yang dipicu oleh startup.

Credential tetap disimpan di environment backend; jangan menaruh token di konfigurasi sumber atau log.

### Tes penyimpanan

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -t . -v
```

Tes menggunakan database dalam folder sementara. Cakupannya termasuk persistensi lintas proses Python, migrasi berulang/paralel, rollback migrasi dan penyimpanan, checksum, foreign key, bukti multisumber, riwayat perubahan, konflik versi penulis, persistensi preferensi/sumber/job, dan endpoint kesehatan saat database belum siap. Tes pengambilan juga memeriksa pemisahan deadline festival/EPIC, biaya bersyarat, tanggal ambigu, idempotensi, pembaruan deadline, kegagalan jaringan/struktur, pembatalan, robots, redirect, DNS private, koneksi ke IP tervalidasi, dan retry terbatas. Semua data lomba contoh hanya digunakan di tes; HTML fixture ditulis khusus untuk pengujian, bukan snapshot live yang disamarkan.

Untuk backup lokal, hentikan backend dan proses lain yang memakai database sebelum menyalin file dari `DATABASE_PATH`. Jangan commit database atau backup-nya ke Git.

### Build frontend dan periksa TypeScript

```powershell
cd frontend
npm.cmd run build
```

Perintah ini menjalankan pemeriksaan TypeScript dan menghasilkan aset di `frontend/dist/`. Untuk hanya memeriksa tipe, jalankan `npm.cmd run typecheck`.

### Periksa backend langsung

Saat server berjalan:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Respons bawaan:

```json
{
  "status": "ok",
  "service": "Lomba Radar",
  "environment": "development",
  "database": "ok",
  "schema_version": "001"
}
```

### Periksa koneksi frontend ke backend

Saat kedua server berjalan:

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/health
```

Respons harus sama dengan endpoint backend langsung. Ini memastikan proxy `/api` berfungsi. Memuat ulang halaman atau menekan **Cek koneksi lagi** hanya mengecek kesehatan API dan database; tidak mengambil informasi lomba. Database yang belum siap menghasilkan HTTP 503 dan tidak dilaporkan sehat.

Untuk mengecek keadaan gagal, hentikan backend lalu tekan **Cek koneksi lagi**. Halaman harus menampilkan kegagalan koneksi, bukan keberhasilan. Jalankan backend kembali untuk mencoba pemulihan.

## Dependency dan batas penggunaan

- Gunakan `npm ci` agar versi frontend mengikuti `package-lock.json`.
- Gunakan `backend/requirements.txt` untuk instalasi backend yang mengikuti versi terkunci. `requirements.in` mencatat dependency langsung untuk pembaruan yang disengaja.
- `.venv`, `node_modules`, hasil build, `.env`, dan database lokal diabaikan Git.
- Kedua server terikat ke `127.0.0.1` untuk pengembangan lokal. Autentikasi dan hosting internet belum disiapkan pada tahap ini.
- `--reload` dan Vite dev server digunakan untuk pengembangan. Deployment produksi akan memerlukan konfigurasi tersendiri, termasuk routing `/api`.
- Tidak ada layanan eksternal yang diaktifkan atau deployment yang dilakukan oleh setup ini.

## Rujukan stack

- [Vite: getting started](https://vite.dev/guide/)
- [Tailwind CSS: integrasi Vite](https://tailwindcss.com/docs/installation/using-vite)
- [FastAPI: virtual environments](https://fastapi.tiangolo.com/virtual-environments/)
