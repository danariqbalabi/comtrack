# Lomba Radar

Tool pribadi untuk menemukan hackathon, Business Case Competition (BCC), dan Business Plan Competition (BPC) yang diselenggarakan di Indonesia, termasuk lomba online, dengan sasaran awal mahasiswa.

Pengambilan data direncanakan hanya saat pengguna menekan **Cari sekarang**. Tidak ada pencarian berkala.

## Status: tahap 1 — fondasi proyek

Yang sudah tersedia:

- Frontend React + Vite + TypeScript, dengan Tailwind CSS.
- Backend FastAPI dan pengaturan environment server.
- Endpoint `GET /api/health` serta dokumentasi API di `/docs`.
- Halaman awal yang mengecek koneksi backend sebenarnya, dengan status loading, berhasil, gagal, dan tombol coba lagi.
- Proxy Vite agar frontend lokal mengakses backend melalui `/api` tanpa konfigurasi CORS tambahan.

Belum tersedia pada tahap ini: database, feed lomba, scraping, worker, discovery, integrasi Instagram, OCR, dan instalasi PWA. Tidak ada data lomba dummy.

Tahap selanjutnya: database persisten dan model penyimpanan lomba, sumber, serta bukti pengambilan.

## Prasyarat

- Node.js **22.12+**; pengembangan awal diverifikasi menggunakan Node.js 24.
- Python **3.11+**; pengembangan awal diverifikasi menggunakan Python 3.13.
- npm, tersedia bersama Node.js.

Tidak perlu API key atau layanan berbayar untuk menjalankan tahap 1.

## Struktur proyek

```text
comtrack/
├── backend/
│   ├── app/
│   │   ├── config.py       # Environment server
│   │   └── main.py         # FastAPI dan endpoint kesehatan
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
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | Tujuan proxy `/api` pada dev server Vite |
| `VITE_API_BASE_URL` | `/api` | Base URL API yang digunakan frontend |

Variabel berawalan `VITE_` bersifat **publik** dan masuk ke kode frontend. Credential provider nantinya hanya boleh berada di environment backend, tanpa awalan tersebut.

Restart backend dan Vite setelah mengganti `.env`. Variabel frontend juga perlu di-build ulang jika menggunakan hasil build.

Jika port backend diganti melalui opsi `--port`, sesuaikan `API_PROXY_TARGET`. Port frontend dikunci ke 5173; Vite akan memberi error jika port tersebut sedang digunakan.

## Pemeriksaan

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
  "environment": "development"
}
```

### Periksa koneksi frontend ke backend

Saat kedua server berjalan:

```powershell
Invoke-RestMethod http://127.0.0.1:5173/api/health
```

Respons harus sama dengan endpoint backend langsung. Ini memastikan proxy `/api` berfungsi. Memuat ulang halaman atau menekan **Cek koneksi lagi** hanya mengecek kesehatan API; tidak mengambil informasi lomba.

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
