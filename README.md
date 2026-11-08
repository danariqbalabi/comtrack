# Lomba Radar

Radar pribadi untuk hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) di Indonesia. Sasaran awal mahasiswa. Pencarian manual tetap tersedia; website/RSS terdaftar juga dapat diperiksa berkala saat otomatisasi diaktifkan.

## Discovery dan pantauan website otomatis - tahap 4

Tahap 3 menambahkan discovery di luar daftar website pantauan. Scheduler membentuk maksimal tiga query per job dari kategori dan jenjang pada preferensi, dengan variasi Indonesia/Inggris, tahun, pencarian info lomba, dan situs kampus. Posisi rotasi dan rencana query disimpan di SQLite; restart tidak mengembalikannya ke query pertama.

**Artikel website yang lolos kualifikasi otomatis menjadi sumber pantauan mulai job berikutnya**, dengan adapter `discovered_article`. Yang didaftarkan adalah URL artikel yang sudah dibaca, bukan seluruh domain atau homepage. Penemuan artikel lain tetap melalui discovery. Tidak mengikuti link artikel (0 hop tautan); satu pengambilan artikel per sumber, dibatasi kuota halaman dan pengamanan redirect/robots yang sama. Hasil pencarian disimpan dengan URL, domain, query asal, waktu, dan status. Tracking umum di URL diabaikan untuk deduplikasi. Kandidat sosial media belum dibaca; akun Instagram tetap menunggu tahap 6.

Untuk memakai discovery terjadwal:

1. Siapkan key Brave sendiri dan aktifkan `DISCOVERY_PROVIDER_ENABLED=true` pada environment server. Isi `BRAVE_API_KEY` tanpa awalan `VITE_`.
2. Isi `BRAVE_COST_PER_REQUEST_USD` dengan estimasi tarif per request pada paket akun sendiri. Nilai wajib positif, maksimal enam angka desimal. Nilai kosong berarti belum dikonfigurasi; aplikasi tidak mengasumsikan tarif/kuota gratis.
3. Di preferensi, aktifkan **Sertakan discovery pada pencarian**, lalu simpan. Di otomatisasi, aktifkan scheduler, izin provider berbayar, dan batas request serta anggaran harian positif.
4. Restart backend/worker/scheduler setelah mengubah environment, lalu tunggu jadwal. Tambahan Discovery web ikut batas sumber per job dan pemilihan bergiliran. Jika daftar 30 sumber sudah penuh, kosongkan satu slot untuk sumber sistem tersebut. Sumber Discovery web yang dinonaktifkan tidak diaktifkan ulang diam-diam.

Tidak ada layanan berbayar yang diaktifkan atau key yang dipasang selama implementasi. Tanpa key, tarif, izin, atau kuota, pencarian provider ditahan dan alasan ditampilkan. Website lain tetap diproses. Konfigurasi provider mengikuti [Brave Web Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get); tarif dan kuota perlu diperiksa pada paket akun sendiri, bukan dianggap tetap oleh aplikasi.

Sebelum request, worker mereservasi satu request dan biaya **estimasi** dalam transaksi SQLite. Batas yang dipakai adalah yang lebih ketat dari snapshot job dan pengaturan terkini. Hari dihitung menurut UTC. Reservasi mencakup request sukses, gagal, dan yang statusnya tidak pasti sesudah crash; tidak ada refund otomatis. Batas harian berhenti digunakan pada pergantian hari UTC tanpa menghapus catatan lama. Permintaan untuk query yang sama pada job yang sama tidak dikirim ulang: respons sukses tersimpan dapat dipakai kembali, sedangkan reservasi yang terputus/gagal membuat job berhenti pada query tersebut. Job jadwal berikutnya dapat melakukan request baru selama kuota tersedia.

Angka reservasi **bukan tagihan aktual** dan tidak menjamin batas tagihan eksternal jika estimasi tarif diisi terlalu rendah atau akun dipakai aplikasi lain. Tidak ada retry langsung saat provider gagal/menolak request. Instagram dan model AI belum masuk ledger biaya ini. Mode **Cari sekarang** masih memakai discovery manual versi sebelumnya: tiga query tetap dan konfigurasi provider lama, tanpa penerapan kuota terjadwal. Gunakan discovery terjadwal untuk batas baru ini.

Snippet dan judul pencarian tidak dipakai sebagai fakta lomba. Worker membuka artikel asli dengan pembatasan robots, DNS/IP publik, redirect, ukuran dan waktu yang sudah ada. Hasil baru di-ingest lewat alur kualitas setelah ekstraksi artikel berhasil. `verified` pada kandidat hanya berarti artikel berhasil diekstrak; kelayakan dan status pendaftaran dinilai terpisah. Artikel yang gagal diakses/strukturnya belum didukung tetap kandidat. Setelah batas halaman discovery tercapai, URL lain disimpan tanpa dibuka. Hasil verifikasi lama dipertahankan jika batas membuat pemeriksaan ulang belum dapat dijalankan, dengan waktu pemeriksaan sebelumnya tetap terlihat.

Panel **Discovery · Tahap 4** di Pengaturan menampilkan status konfigurasi, request/anggaran estimasi harian, query job terakhir, kandidat per domain, serta filter status dan pagination. Panel menampilkan keputusan pantauan beserta alasan dan ID sumber: menunggu penilaian, perlu diperiksa, ditolak, aktif, sudah terdaftar, atau batas tercapai. Tombol **Isi formulir sumber** tetap tersedia untuk penambahan manual. API read-only: `GET /api/discovery` dan `GET /api/discovery/candidates?status=verified&domain=example.com&offset=0&limit=30`. Membaca API/panel tidak menjalankan pencarian. Schema **006** menambahkan rencana query, rotasi, metadata kandidat, dan ledger reservasi tanpa menghapus data lama.

Pemeriksaan tahap 3: pengujian kontrak/provider memakai respons mock eksplisit; belum ada key Brave sehingga pencarian Brave live belum diuji. Uji website live membuktikan fallback saat provider belum terhubung tetap menyimpan OU Festival nyata. Untuk mengulang fallback tanpa provider berbayar dan tanpa mengubah database utama:

```powershell
.\.venv\Scripts\python.exe -m scripts.discovery_smoke
```

Hasil pemeriksaan tahap 3 sebelumnya: **183 tes backend lulus**, termasuk 24 tes discovery, juga pada salinan persis file commit. Build TypeScript/Vite dan `pip check` berhasil. UI diperiksa lewat build dan pengujian API; verifikasi visual browser tidak dilakukan pada tahap ini. Database lokal sudah dibackup dan dimigrasikan tanpa mengaktifkan layanan berbayar.

## Kualifikasi website - tahap 4

Aktivasi otomatis hanya berlangsung pada discovery **terjadwal**, setelah observasi berhasil masuk database beserta URL/hash/kutipan bukti. Observasi asli dan hasil gabungan dinilai ulang terhadap preferensi terkini. Harus berupa lomba kategori pilihan, cakupan Indonesia dan syarat peserta yang jelas, tanpa tanggal ambigu/konflik aktif, serta memiliki tanggal akhir pendaftaran yang belum lewat. Ini penyaringan konservatif berbasis teks, bukan jaminan validitas penyelenggara. Informasi yang belum cukup tetap kandidat; hasil di luar preferensi ditolak. Artikel gagal diekstrak atau yang hanya muncul di snippet tidak diaktifkan. Kandidat lama dinilai ketika ditemukan dan diverifikasi ulang, bukan lewat migrasi massal.

Batas sumber baru menggunakan nilai lebih ketat dari snapshot job dan pengaturan terkini. Nilai 0 menahan semua penambahan. Maksimal 30 sumber keseluruhan, termasuk sumber nonaktif dan sumber sistem. Ledger `website_onboardings` menyimpan pemakaian jatah per job, tetap dihitung sesudah penghapusan sumber atau restart. Transaksi dan pemeriksaan lease/jeda melindungi proses paralel. URL dengan www/tracking yang sama tidak ditambahkan ulang, konfigurasi dan status sumber yang sudah ada dipertahankan. Kandidat yang tertahan batas dapat dinilai ulang jika ditemukan pada job berikutnya.

Adapter artikel hanya membaca ulang artikel dengan parser HTML yang sudah berhasil dipakai saat discovery. Jika struktur berubah, kegagalan dicatat dan bukti lama dipertahankan. Tidak menyimpulkan halaman daftar/RSS secara spekulatif. Domain tujuan berbeda ditahan; akses produksi memakai pemeriksaan DNS/IP publik dan redirect dari collector, termasuk saat pengambilan ulang. URL sosial media tetap menunggu tahap 6.

Schema onboarding **007** menambahkan keputusan onboarding dan ledger penambahan sumber tanpa menghapus data sebelumnya. Pemeriksaan tahap 4: 202 tes backend, termasuk 19 tes onboarding (alur worker hingga job berikutnya, jatah bersama, konkurensi, restart, sumber nonaktif, jeda, dan bukti wajib); build TypeScript/Vite dan `pip check`. Integrasi discovery memakai respons fixture, belum ada key untuk uji Brave live. Tidak mengaktifkan provider berbayar atau otomatisasi lokal. UI diverifikasi melalui build/API, tanpa pemeriksaan visual browser.

## Ekstraksi AI lokal dan OCR - tahap 5

Parser deterministik selalu didahulukan. Untuk artikel website/discovery terjadwal yang belum lengkap, AI lokal dapat memilih nama dan kutipan fakta dari teks sumber. Skema JSON menolak field tambahan; kutipan yang tidak persis ada dalam teks ditolak. Angka biaya/tanggal tidak diterima langsung dari model, melainkan diparsing ulang dari kutipan. Tahun yang hilang tidak ditebak; perbedaan dengan parser biasa ditandai perlu diperiksa dan fakta lama dipertahankan. Konten halaman tidak mendapat akses tool, shell, credential, atau konfigurasi model.

Integrasi memakai API generate terstruktur Ollama di alamat tetap `127.0.0.1:11434`, tanpa SDK tambahan. Jalankan Ollama dan pasang model lokal sendiri, lalu isi `AI_MODEL`, `AI_ENABLED=true`, dan restart worker. Tidak ada download model atau panggilan cloud otomatis. Model bertanda cloud ditolak. Ollama harus berjalan di lingkungan jaringan yang sama dengan worker; adapter ini tidak memakai endpoint remote. Instalasi model membutuhkan storage/RAM sesuai model. Tesseract tetap opsional melalui `OCR_ENABLED`; bahasa OCR harus sudah terpasang.

Batas input 16.000 karakter, output 2.048 token, timeout default 45 detik, maksimal `AI_MAX_REQUESTS_PER_JOB=3` per job. Reservasi request AI bertahan saat crash; request gagal tidak diulang dalam job yang sama. Cache disimpan dengan hash konten/URL, model, `AI_MODEL_REVISION`, dan versi prompt. Naikkan revision jika bobot model lokal berubah. OCR mengikuti batas gambar terkecil antara snapshot dan pengaturan terkini, juga menghabiskan jatah halaman sumber. Kutipan hasil OCR tetap perlu dicek terhadap gambar. Fitur gagal/tidak terpasang tidak mematikan parser sumber lain. Mode manual lama tidak memakai fallback ini.

Schema ekstraksi **008** menyimpan cache dan reservasi ekstraksi. Kontrak Ollama mengikuti dokumentasi resminya: https://docs.ollama.com/api/generate dan https://docs.ollama.com/capabilities/structured-outputs . Integrasi dites dengan fixture; belum ada Ollama/Tesseract terkonfigurasi untuk uji model/OCR live di mesin ini.

## Instagram publik - tahap 6

Discovery merotasi query `site:instagram.com` bersama query website. URL profil dari hasil pencarian dan maksimal tiga tautan akun per artikel disimpan dengan asal penemuan; URL postingan/hashtag tidak dianggap username. Sistem tidak memakai daftar akun pribadi. Profil dicek melalui Actor resmi `apify/instagram-profile-scraper`: username harus cocok, flag `private`/`isPrivate` harus eksplisit false, bio harus jelas berupa media info lomba atau penyelenggara. Bio akun pribadi ditolak; akun ambigu, status publik tidak tersedia, perubahan skema, atau provider gagal tetap ditahan. Ini klasifikasi konservatif berbasis bio, bukan verifikasi identitas penyelenggara. Data kontak/follower tidak disimpan.

Akun lolos didaftarkan dalam jatah sumber baru yang sama dengan website, maksimal 30 sumber total, mulai dipantau job berikutnya. Sumber nonaktif tidak diaktifkan ulang. Setiap pengambilan postingan memeriksa ulang profil; akun yang berubah private/pribadi tidak diproses. Caption hanya diterima untuk URL post/reel asli dan owner yang cocok. Carousel OCR dibatasi gambar per post serta halaman per sumber; fakta OCR ditandai perlu dicek. Tidak ada bypass login atau akun private. Bio dan hasil search bukan fakta lomba untuk feed.

Isi `INSTAGRAM_PROVIDER_ENABLED=true`, `APIFY_TOKEN`, `INSTAGRAM_POSTS_LIMIT` dan batas `APIFY_MAX_CHARGE_USD` pada server; restart worker. Izin provider berbayar dan kuota harian positif tetap wajib. Sebelum tiap Actor run, aplikasi mereservasi satu request dan **seluruh cap biaya run**, bukan perkiraan harga per post. Cap dikirim sebagai `maxTotalChargeUsd`, `restartOnError=false`, timeout 60 detik, output dibatasi. Profil dan postingan adalah dua run terpisah. Kuota harian request/biaya sekarang **bersama Brave + Apify**, UTC, mencakup gagal dan status tidak pasti. Nilai cap default USD 0.05 bisa membuat jatah harian cepat habis; reservasi bukan tagihan aktual. Request yang sama pada job yang sama tidak diulang setelah gagal/crash. Belum ada token sehingga uji Instagram menggunakan fixture, bukan live.

Worker menggunakan alur pemeriksaan ini juga untuk akun Instagram yang ditambahkan manual. Panel Akun Instagram dan `GET /api/instagram/candidates` menampilkan keputusan serta alasan tanpa menjalankan provider. Schema **009** menyimpan kandidat akun dan ledger Apify. Dokumentasi kontrak: https://apify.com/apify/instagram-profile-scraper dan https://docs.apify.com/api/v2/actor-run-sync-get-dataset-items-post .

## Prioritas sumber dan perubahan - tahap 7

Setiap penyelesaian sumber mencatat produktivitas secara idempoten: lomba relevan baru, perubahan, keberhasilan/kegagalan, skor, dan waktu pemeriksaan berikutnya. Sumber menghasilkan lomba/perubahan tetap memakai interval normal. Sumber tanpa hasil baru diperjarang 2-4 kali interval; sumber gagal memakai jeda eksponensial, maksimum tujuh hari. HTTP 429 mendapat jeda minimal empat kali interval. Scheduler melewati sumber yang belum jatuh tempo, mendahulukan sumber belum dicoba/paling lama dicoba, lalu skor pada waktu yang sama, dengan rotasi untuk seri. Sumber produktif lebih sering memenuhi syarat jadwal, tetapi sumber lain tidak dibuang. `Cari sekarang` dapat mencoba sumber di luar jeda dan memulihkan status. Mengubah interval menghapus penundaan sumber sehat; backoff kegagalan dipertahankan.

Link pendaftaran/website resmi/guidebook yang tertulis eksplisit di artikel disimpan sebagai bukti tanpa diikuti. Link pendaftaran yang sama dapat membantu deduplikasi lintas website/Instagram jika nama, kategori, dan edisi juga sama. Nama samar atau edisi/kategori berbeda tetap terpisah. Konflik fakta lintas sumber tetap terlihat, tidak ditimpa diam-diam. Perubahan material timeline, biaya, status pendaftaran, dan syarat peserta dicatat dengan nilai sebelum/sesudah serta versi riwayat di `competition_change_events`. Deadline/status feed tetap dinilai ulang terhadap waktu saat dibaca; tidak perlu mencari web hanya untuk mengetahui tanggal sudah lewat. Schema **010** menyimpan kesehatan sumber dan peristiwa perubahan.

## Aktivitas radar - tahap 8

Pengaturan memiliki panel Aktivitas radar dengan hasil job terakhir (baru/berubah/tetap, relevan/perlu dicek/di luar preferensi), ledger harian UTC per provider, percobaan AI/OCR, kesehatan/score sumber, alasan jeda, waktu keberhasilan terakhir, riwayat job beserta error tiap sumber, perubahan fakta sebelum/sesudah, dan deadline terverifikasi tujuh hari ke depan. Riwayat job dan perubahan memakai pagination. Ringkasan diperbarui tiap 10 detik; semua endpoint bersifat read-only dan tidak memicu pencarian atau biaya provider. Status siap konfigurasi bukan bukti credential valid; error integrasi terlihat pada hasil job.

API: `GET /api/automation/activity`, `/api/automation/sources`, `/api/automation/runs?offset=0&limit=10`, `/api/automation/changes?offset=0&limit=20`, dan `/api/automation/deadlines?days=7&limit=30`. Deadline ambigu/di luar preferensi/sudah lewat tidak dimasukkan sebagai deadline aktif. Model data dan bukti lama tetap tersimpan di detail. Panel tidak mengirim notifikasi ke luar aplikasi. Tidak diperlukan migrasi tambahan pada tahap ini; schema tetap **010**. Pengujian API memastikan membuka panel tidak mengakses provider, batas pagination tervalidasi, dan tidak membocorkan worker token/config sumber.

## Scheduler dan kontrol otomatisasi

Kontrol tersedia di **Pengaturan → Otomatisasi · Tahap 4**: aktif/jeda, interval (30 menit–7 hari), jadwal berikutnya, heartbeat scheduler, dan ID job otomatis terakhir. Batas jumlah sumber (1–30) dan halaman per sumber (1–10) diterapkan pada job otomatis, ditambah kuota request/estimasi biaya discovery pada tahap 3. Batas sumber baru diterapkan pada tahap 4; batas gambar disiapkan untuk tahap selanjutnya. Instagram tetap dibatasi ke akun publik media lomba dan penyelenggara.

Izin provider berbayar default **nonaktif**, batas request harian **0**, dan anggaran harian **USD 0.00**. Mengizinkan provider berbayar memerlukan batas request dan anggaran positif; anggaran disimpan sebagai desimal maksimal dua angka di belakang titik. Status kesiapan integrasi memeriksa konfigurasi server tanpa memanggil layanan atau menampilkan credential. Status dikonfigurasi tidak menjamin key valid atau kuota tersedia.

Scheduler memproses website/RSS terdaftar dengan adapter OU Festival, HTML publik, atau RSS. Tahap 3 menambahkan discovery Brave jika preferensi mengizinkannya dan seluruh syarat provider/biaya terpenuhi. Tahap 4 menambahkan pantauan artikel website yang lolos kualifikasi. AI lokal/OCR opsional masuk alur website terjadwal; Instagram masuk alur otomatis pada tahap 6. Pencarian manual tetap memakai alur/konfigurasi provider sebelumnya dan belum dibatasi kuota otomatisasi.

Konfigurasi tersimpan di `automation_settings`, jadwal di `automation_schedule`, dan snapshot konfigurasi setiap job otomatis di `automation_job_runs`. API `GET /api/automation` membaca konfigurasi beserta status runtime; `PUT /api/automation` menerima `{"settings":{...},"expected_version":1}`. Header mutasi, validasi origin, dan login pribadi mengikuti API lainnya. Penyimpanan dari versi lama menghasilkan HTTP 409 agar perubahan tab/proses lain tidak tertimpa. Pengaturan tidak mengubah preferensi relevansi atau sumber pantauan.

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
| Discovery | `BRAVE_API_KEY`, `DISCOVERY_PROVIDER_ENABLED=true`, lalu aktifkan preferensi discovery | Otomatis: juga perlu `BRAVE_COST_PER_REQUEST_USD`, izin dan kuota; query dirotasi, artikel dibatasi anggaran halaman. Manual: alur tiga query tetap sebelumnya |
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

Schema **006**: data lomba, sumber, bukti, riwayat, job/log, snapshot sumber, preferensi, kandidat discovery, konfigurasi/jadwal otomatisasi, metadata job otomatis, rencana query dan reservasi request provider. Startup menerapkan migrasi SQL berurutan dengan checksum tanpa menghapus data lama. Jangan mengubah file migrasi yang sudah diterapkan. SQLite memakai WAL, foreign key, transaksi dan disk lokal; bukan network share.

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
