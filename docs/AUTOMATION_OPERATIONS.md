# Operasi Lomba Radar

Implementasi tahap 1-9, 8 November 2026. Gunakan README untuk menjalankan aplikasi. Semua provider bersifat opt-in; konfigurasi default tidak mengaktifkan layanan berbayar atau otomatisasi.

## Proses dan data

API melayani UI/pengaturan, scheduler membuat job yang jatuh tempo, worker mengambil sumber. Ketiganya memakai file SQLite lokal yang sama. API/browser tidak harus terbuka untuk scheduler/worker yang sudah hidup. Tidak ada catch-up massal sesudah downtime dan hanya satu job aktif. Jangan menjalankan database pada network share.

Job menyimpan snapshot sumber dan batas saat antre. Penambahan sumber tidak memperluas job berjalan. Klaim atomik, heartbeat dan token lease menolak penulis lama. Sumber yang dinonaktifkan/dihapus dilewati. Jeda otomatisasi memblokir penulisan hasil terjadwal sesudah jeda; request jaringan yang sudah terkirim tidak selalu bisa dibatalkan. Mode manual tetap dapat dipakai saat otomatisasi dijeda, dengan izin/kuota provider yang sama.

Scheduler memilih sumber yang jatuh tempo, mendahulukan yang belum dicoba/paling lama dicoba, skor sebagai pemecah seri, kemudian rotasi ID. Sumber relevan baru/perubahan tetap memakai interval dasar; sumber tanpa hasil baru 2-4 kali interval; kegagalan memakai backoff eksponensial maksimum 7 hari. HTTP 429 minimal 4 kali interval. Interval global masih membatasi seberapa cepat job dibuat. Perubahan interval menghapus penundaan sumber sehat, mempertahankan backoff kegagalan. Refresh manual mengabaikan backoff untuk percobaan eksplisit.

## Batas tersimpan

| Pengaturan | Rentang | Perilaku |
| --- | --- | --- |
| Interval | 30-10080 menit | Jadwal persisten; bukan tab browser |
| Sumber per job otomatis | 1-30 | Snapshot sumber; tidak bertambah saat berjalan |
| Sumber baru per job | 0-30, tidak melebihi sumber/job | Website dan Instagram berbagi ledger; 0 menahan onboarding |
| Halaman per sumber | 1-10 | Reservasi sebelum get; OCR ikut menghabiskan jatah |
| Gambar per post/dokumen | 0-5 | OCR memakai nilai lebih ketat dari snapshot dan pengaturan terkini |
| Request provider per hari | 0-10000 | Brave dan Apify berbagi ledger UTC |
| Anggaran provider per hari | USD 0-1000, dua desimal | Estimasi Brave + seluruh cap Actor Apify |
| Total sumber | 30 | Termasuk sumber sistem dan nonaktif |
| Generasi AI lokal per job | 0-20, default 3 | Environment server, cache tidak memerlukan generasi baru |

Reservasi tidak dikembalikan sesudah error/crash. Request provider yang sama pada job yang sama menggunakan respons sukses tersimpan, atau ditahan bila gagal/tidak pasti. Job baru boleh mencoba jika kuota masih cukup. Ledger sumber baru tetap menghitung sumber yang dihapus pada job tersebut. Menaikkan batas sesudah job antre tidak menaikkan jatahnya; menurunkannya dapat menghentikan bagian berikutnya.

Apify profil dan postingan memakai run berbeda. `maxTotalChargeUsd`, timeout 60, `restartOnError=false`, dan batas hasil dikirim ke endpoint Actor. Respons API dibatasi 4 MiB. Biaya internal adalah reservasi estimasi/cap, bukan laporan tagihan aktual. Tidak menghitung pemakaian provider oleh aplikasi lain. Kredensial tidak ada di URL, frontend, atau log aplikasi.

## Bukti dan kualitas

Search title/snippet hanya menghasilkan kandidat. Artikel asli diproses oleh parser, lalu fallback AI/OCR opsional bila struktur/konten belum lengkap. AI hanya memilih kutipan exact-match; JSON dengan field tambahan atau kutipan tidak terdapat pada teks ditolak. Tanggal tanpa tahun tidak ditebak. Angka/tanggal diparsing dari kutipan sumber. Perbedaan dengan parser mempertahankan fakta lama dan menandai review; OCR selalu perlu dicocokkan terhadap gambar.

Ollama hanya di `127.0.0.1:11434`; `/api/show` harus menunjukkan metadata model lokal tanpa remote host/model sebelum generasi. Jalankan runtime dengan `OLLAMA_NO_CLOUD=1`. Tidak ada auto-pull model, tool, shell atau akses credential untuk model. Nama model, revision dan versi prompt ikut kunci cache. Ubah `AI_MODEL_REVISION` setelah mengganti bobot model dengan tag yang sama. Cache AI tersimpan di SQLite, OCR memakai hash gambar dan bahasa.

Onboarding artikel memerlukan observasi asli dan hasil gabungan yang relevan, bukti tersimpan, syarat peserta/cakupan Indonesia yang cukup, dan deadline pendaftaran belum lewat. Parser ini konservatif, bukan penjamin legalitas penyelenggara. URL artikel dipantau ulang; tidak otomatis merayapi seluruh domain/menyimpulkan RSS. Kandidat tertahan dapat dinilai ulang ketika ditemukan lagi. Akun Instagram diperiksa publik + bio media lomba/penyelenggara sebelum postingan; perubahan ke private/ambigu menahan pengambilan berikutnya. Tidak ada bypass akun private/login.

Kategori, edisi, nama dan bukti identitas tambahan diperlukan untuk deduplikasi lintas sumber. Link pendaftaran yang tertulis eksplisit dapat menjadi bukti tambahan; root domain dan nama mirip saja tidak cukup. Perbedaan narasi ringkasan artikel tidak dianggap konflik fakta. Data yang hilang tidak menghapus fakta terdahulu. Perubahan material menyimpan nilai sebelum/sesudah, versi dan sumber; bukti/kutipan/hash dan riwayat dapat dibuka pada detail.

## API pembacaan

- `/api/automation`: pengaturan, heartbeat, jadwal, kesiapan konfigurasi.
- `/api/automation/activity`: hasil terakhir dan kuota bersama hari UTC.
- `/api/automation/sources`: kesehatan dan jadwal sumber, maksimal 30.
- `/api/automation/runs?offset=0&limit=10`: riwayat, maksimal 30 per halaman.
- `/api/automation/changes?offset=0&limit=20`: perubahan, maksimal 100 per halaman.
- `/api/automation/deadlines?days=7&limit=30`: deadline terverifikasi mendatang, rentang 1-30 hari.
- `/api/discovery/candidates`: kandidat artikel, filter status/domain, pagination.
- `/api/instagram/candidates`: kandidat akun dan alasan, filter status, pagination.

Membaca endpoint/panel tidak melakukan pencarian atau menulis observasi. Di production, akses baca/tulis memakai login pribadi. Mutasi API memerlukan header `X-Lomba-Radar: 1` dan origin yang diizinkan. Status configured tidak membuktikan credential valid atau model terpasang.

## Diagnostik dan pemulihan

1. Jalankan `python -m scripts.doctor` menggunakan venv. Periksa schema **012**, integritas DB, build frontend, enabled/paid allowance, dan heartbeat. Perintah ini tidak memanggil layanan atau menampilkan secret.
2. Job tetap antre: pastikan worker menggunakan `DATABASE_PATH` yang sama. Jadwal tidak bergerak: pastikan scheduler hidup dan otomatisasi aktif. Browser tidak menjalankan scheduler.
3. Provider belum terhubung: isi flag/key, tarif Brave atau cap Apify, restart proses, lalu periksa izin/kuota pada Pengaturan. Untuk percobaan ulang eksplisit gunakan Cari sekarang; request gagal/tidak pasti pada job lama tidak dikirim ulang.
4. Halaman tidak terbaca: cek error sumber dan selector, robots/login/JS/PDF. Menambah batas halaman tidak menyelesaikan struktur yang belum didukung. AI/OCR dapat membantu konten, bukan melewati kontrol akses.
5. Daftar penuh: hapus sumber yang tidak diperlukan. Menonaktifkan saja tidak mengosongkan batas 30 sumber; data lomba/bukti lama tetap tersimpan ketika sumber dihapus.
6. Sebelum migrasi/update: backup dengan `python -m scripts.backup data/backups/nama-baru.db`. Gunakan file baru. Untuk restore hentikan semua tiga proses, simpan salinan kondisi lama, lalu set `DATABASE_PATH` ke backup. Jangan menggabungkan file DB/WAL dari backup berbeda.

## Deployment dan verifikasi

Compose menyediakan API, worker, scheduler, volume SQLite dan OCR. AI lokal tidak dibundel; endpoint loopback membutuhkan Ollama dalam lingkungan jaringan worker yang sama. Konfigurasi default Compose belum membuat runtime/model Ollama. Jangan menganggap Ollama di host Windows otomatis terjangkau dari loopback container.

Hasil akhir: 282 tes backend, build frontend dan pip check lulus. Pengujian menggunakan database sementara, tanpa seeding produksi: pipeline discovery sampai feed lintas sumber, recovery setelah ingest, permission/budget manual/otomatis, source disable/pause, cache dan quote validation, migrasi, API autentikasi serta guard mutasi. `scripts.system_smoke` menjalankan API production HTTP nyata dan frontend build dengan credential fixture, lalu menghentikan proses miliknya. `scripts.scheduler_smoke` dan `scripts.discovery_smoke` menguji website OU Festival nyata dengan provider berbayar dipaksa nonaktif. Hasil lokal ada di `data/` dan tidak ikut Git.

Tavily/Brave/Apify live, model/OCR live, visual browser terbaru dan Docker build belum diuji karena credential/runtime/tool tidak tersedia. Jangan menganggap mock provider sebagai bukti koneksi live. Otomatisasi lokal/provider tetap tidak diaktifkan oleh tes.

## Tavily Free sebagai default

Discovery default sekarang Tavily Basic Search: env `DISCOVERY_PROVIDER=tavily`, `TAVILY_API_KEY`, flag discovery aktif. Tidak memerlukan izin berbayar/anggaran USD. Kontrol `tavily_free_enabled` default true, `tavily_daily_credit_limit` default 20, `tavily_monthly_credit_limit` default 600; batas 0 menghentikan request baru, maksimal 1000/bulan. Kuota tersendiri di luar ledger USD Brave/Apify. UI Discovery/aktivitas menampilkan reservasi kredit lokal, bukan saldo akun provider.

Schema 012 mempertahankan ledger lama dan menambahkan reservasi satu kredit/query Basic. Hari/bulan UTC, guard lease/jeda, batas lebih ketat dari snapshot/terkini, tanpa refund saat gagal/crash, cache sukses per query/job. Pin provider mencegah pemulihan job berganti provider dan mengirim ulang pencarian ke layanan lain. Basic dipaksa, auto_parameters dan answer/raw/images dimatikan; respons usage selain 1/tidak tersedia menahan integrasi melalui tavily_safety.blocked. Periksa kontrak/tarif dan perbaiki adapter sebelum mereset flag tersebut; jangan menghapus ledger untuk melewati jatah. Brave tetap opt-in eksplisit; adapter internal brave_discovery dan URL sumber sistem lama dipertahankan demi kompatibilitas data, bukan penanda tujuan request HTTP (Tavily memakai api.tavily.com/search).

Free plan akun harus tetap Researcher, PAYG nonaktif; tidak ada kontrol billing akun melalui aplikasi ini. Kredit yang digunakan aplikasi lain tidak tercatat. Instagram masih memerlukan provider terpisah. Panduan langkah demi langkah terbaru ada pada README.
