# Roadmap otomatisasi Lomba Radar

Disepakati 8 November 2026. Dokumen ini adalah rencana; fitur yang tercantum belum otomatis dianggap tersedia.

Status: tahap 1–3 sudah diimplementasikan. Scheduler menjadwalkan website/RSS dan discovery dengan query sesuai preferensi, rotasi, verifikasi artikel asli, kandidat domain/URL, dan reservasi kuota/estimasi biaya sebelum request. Tanpa key/estimasi tarif/izin/kuota, discovery ditahan dan website lain tetap berjalan. Pengujian Brave memakai respons mock karena key belum tersedia; fallback website diuji live. Aktivasi domain kandidat otomatis, Instagram dan OCR/AI belum masuk alur otomatis; tahap 4 dan seterusnya belum dikerjakan. Kuota discovery terjadwal belum membatasi mode manual versi sebelumnya.

## Tujuan dan batas cakupan

Pengguna cukup menentukan kategori, profil peserta, dan anggaran. Sistem menemukan kandidat sumber sendiri, membaca informasi lomba, memverifikasi bukti, menggabungkan duplikat, dan memantau perubahan tanpa daftar sumber panjang yang harus dirawat pengguna.

- Fokus: hackathon, BCC, BPC di Indonesia; mahasiswa sebagai profil awal.
- Pencarian dan monitoring berkala di server menggantikan keputusan lama manual-only. Tombol Cari sekarang tetap tersedia.
- Instagram hanya akun publik media/info lomba dan penyelenggara yang relevan. Akun pribadi tidak dipantau otomatis. Akun ambigu menunggu peninjauan; publik saja bukan bukti akun merupakan media lomba.
- Akun publik tetap dapat mengalami batas API, login, rate limit, atau tidak dapat diambil provider. Tidak ada bypass kontrol akses.
- Tidak mengaktifkan layanan berbayar atau deployment eksternal tanpa instruksi pengguna. Provider yang belum siap tampil belum terhubung; bagian lain tetap berfungsi.
- Semua data penting dapat ditelusuri ke URL, kutipan, hash, dan waktu pengambilan. Ketidakpastian tetap terlihat.
- Gunakan model yang sudah tersedia terlebih dahulu. Training/fine-tuning bukan prasyarat; evaluasi berdasarkan data yang dikoreksi sebelum mempertimbangkannya.

## Cara kerja yang dituju

Preferensi → scheduler persisten → discovery web/akun → validasi sumber → pengambilan konten → parsing/OCR/AI → verifikasi fakta dan relevansi → deduplikasi → penyimpanan bukti → feed dan pemantauan perubahan.

Collector yang sudah ada tetap dipakai. Parsing deterministik didahulukan; OCR/AI digunakan ketika diperlukan. Hasil pencarian dan keluaran AI bukan bukti kebenaran dengan sendirinya. Konten sumber tidak boleh menentukan tool call, mengakses credential, atau mengeksekusi kode.

## Tahapan commit dan push

Setiap tahap dikerjakan satu per satu. Setelah tes sesuai tahap selesai: jelaskan hasil, keterbatasan dan konfigurasi yang dibutuhkan, commit, lalu push ke GitHub. Berhenti sesudah laporan tahap dan tunggu arahan pengguna untuk tahap selanjutnya. Tahap kompleks boleh memiliki beberapa commit yang masing-masing dapat ditinjau; jangan mencampur fitur tahap lain.

| Tahap | Commit yang direncanakan | Hasil yang dapat diperiksa | Syarat selesai |
| --- | --- | --- | --- |
| 1 | `feat: add automation controls and collection budgets` | Kontrol aktif/nonaktif otomatisasi, interval, batas sumber/halaman, anggaran provider, status kesiapan integrasi; migrasi konfigurasi dan API/UI sederhana | Batas divalidasi dan tersimpan; otomatisasi default nonaktif sampai diaktifkan; mode manual tetap bekerja; tanpa credential tidak ada panggilan provider berbayar |
| 2 | `feat: schedule durable collection jobs` | Scheduler server dengan jadwal persisten, menyatu dengan worker, pemulihan restart, dan tombol jeda | Jadwal jatuh tempo memicu satu job; tidak tumpang tindih; restart tidak membanjiri antrean; jeda menghentikan job baru; frontend boleh ditutup |
| 3 | `feat: discover competition sources automatically` | Query Indonesia/Inggris yang dibentuk dari preferensi, rotasi query, kandidat URL dan domain yang tersimpan, deduplikasi dan status verifikasi | Pengujian kontrak provider; jika credential tersedia, uji pencarian live; snippet tidak langsung masuk feed sebagai lomba; sumber lama tetap berjalan jika discovery gagal |
| 4 | `feat: qualify and onboard discovered websites` | Penilaian relevansi/keamanan sumber, onboarding website secara otomatis dalam batas yang dipilih pengguna, laporan alasan diterima/ditolak | Sumber relevan baru dapat dipantau tanpa entry manual; private IP/redirect berbahaya ditolak; sumber ambigu tetap kandidat; batas sumber/hops/halaman dipatuhi |
| 5 | `feat: extract verified competition facts with AI` | Adapter model terpisah, keluaran terstruktur, kutipan wajib, validasi tanggal/biaya, cache hash dan versi model/prompt, OCR jika dibutuhkan | Kasus fakta hilang, poster ambigu, konflik dan prompt injection diuji; nilai tanpa bukti ditolak atau perlu dicek; tanpa model collector deterministik tetap berfungsi |
| 6 | `feat: discover and monitor public competition Instagram accounts` | Penemuan akun dari sumber web/akun awal, klasifikasi media lomba/penyelenggara, caption/carousel/OCR, asal penemuan akun | Akun pribadi ditolak, ambigu ditahan, akun publik kategori lomba dapat dipantau; provider tak siap dilaporkan; kontrak diuji dan live diuji jika credential tersedia |
| 7 | `feat: prioritize productive sources and track changes` | Skor produktivitas sumber, jadwal adaptif terbatas, backoff error/rate limit, pemantauan deadline, duplikat lintas sumber | Sumber gagal tidak dicoba terus; sumber produktif mendapat prioritas; edisi/kategori berbeda tidak digabung; perubahan tetap memiliki bukti dan riwayat |
| 8 | `feat: show automation activity and source health` | Ringkasan pencarian otomatis, kandidat/sumber baru, hasil diterima/ditolak, kegagalan, penggunaan kuota dan status berhenti | Pengguna dapat mengetahui hasil terakhir, penyebab error, kebutuhan credential, dan batas yang tercapai tanpa membuka log terminal |
| 9 | `test: verify autonomous collection end to end` | Uji terintegrasi, panduan menjalankan proses server, restart/recovery, backup dan persiapan deployment | Temuan baru berasal dari discovery sampai feed, pengambilan ulang idempoten, frontend tidak wajib terbuka, batas biaya dipatuhi; hasil live dan mock dibedakan jelas |

## Kebijakan anggaran

Sebelum pemanggilan provider, sistem harus mengecek kuota yang tersisa. Simpan reservasi agar worker paralel/retry tidak melampaui batas internal. Catat penggunaan aktual jika provider menyediakannya; jika tidak, tampilkan estimasi sebagai estimasi. Batasi panggilan, halaman, gambar, token, waktu, percobaan ulang, dan pengeluaran sesuai dukungan provider. Saat kuota habis, hentikan bagian berbayar dan tampilkan alasannya.

Batas internal tidak menjamin kesamaan persis dengan tagihan provider, terutama saat koneksi putus sesudah request diterima. Kemampuan pembatasan dan harga provider perlu diverifikasi dari dokumentasi terbaru saat tahap integrasi dikerjakan.

## Kondisi awal repo

Fondasi yang sudah ada: feed/detail/pengaturan, SQLite, job manual persisten, worker, collector OU Festival/RSS/HTML, adapter opsional Brave/Apify/OCR, PWA, dan persiapan produksi.

Ada perubahan lokal pekerjaan perluasan website sebelumnya pada collector, pengaturan, katalog, serta file profil/CLI website yang belum di-commit saat roadmap ditulis. Perubahan itu tidak ikut commit roadmap. Audit dan penyelesaiannya dilakukan terpisah sebelum bergantung padanya; hasil probe lama perlu diverifikasi ulang dan tidak dianggap bukti akses terkini.

## Ukuran keberhasilan

Utamakan jumlah lomba relevan yang terbukti, ketepatan tanggal/biaya, duplikasi rendah, cakupan sumber, dan waktu informasi ditemukan. Jumlah halaman yang diambil bukan satu-satunya ukuran. Jangan menjanjikan seluruh web/sosmed dapat dibaca, seluruh temuan selalu benar, atau skala besar sepenuhnya gratis.
