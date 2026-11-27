# SIkembang (frontend)

Antarmuka web untuk **SIkembang**, sistem rekomendasi kebutuhan bahan: Marketing mencatat pesanan,
sistem memecahnya lewat resep, AI menambah prediksi dari riwayat dan tren musiman, stok gudang
dikurangkan, PPIC meninjau (boleh menerima, mengubah, atau menolak rekomendasi AI), lalu PFA menerima
dokumen permintaan bahan.

Repo ini memuat frontend React serta backend FastAPI dan SQLite di direktori `ml/`. Keduanya
berkomunikasi melalui REST API sesuai Laporan Kelompok 08 Deliverable 2 II3120, Bab 9.

## Tech stack

| Kebutuhan            | Pilihan                                                       | Alasan singkat                                                            |
| -------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Build dan dev server | Vite + React 19 + TypeScript (strict)                         | Cepat, hasil build statis, bisa di-host di mana saja                      |
| Routing              | React Router                                                  | Rute per peran (Marketing, PPIC, PFA)                                     |
| Data dari API        | TanStack Query                                                | Cache, loading, error, dan invalidasi tanpa state global manual           |
| Validasi data        | Zod                                                           | Skema kontrak API dan skema form satu bahasa, response divalidasi runtime |
| Form                 | React Hook Form + Zod resolver                                | Form pesanan dengan baris menu dinamis                                    |
| Styling              | Tailwind CSS v4 + design tokens (CSS variables)               | Token warna, font, radius terpusat di `tokens.css`                        |
| Font                 | Figtree (judul) + Open Sans (isi), self-hosted via Fontsource | Tanpa dependensi CDN                                                      |
| Backend palsu        | MSW (Mock Service Worker)                                     | Frontend jalan penuh tanpa backend                                        |
| Tes                  | Vitest                                                        | Logika keputusan PPIC dan util murni                                      |
| Kualitas             | ESLint, Prettier, GitHub Actions CI                           | Lint, tes, dan build di setiap push                                       |

Frontend sengaja **agnostik terhadap stack backend**: semua pengetahuan tentang bentuk API terkumpul di
`src/api/`. Backend boleh FastAPI, Express, Spring, Laravel, dan lain-lain, selama kontraknya sama.
Cara menyesuaikan: lihat [docs/architecture.md](docs/architecture.md).

## Mulai cepat

```bash
npm install
cp .env.example .env      # default: VITE_API_MODE=mock
npm run dev               # http://localhost:5173
```

Pada mode `mock`, pemilih peran di header (MARKETING, PPIC, PFA) tersedia, dan data awal mengikuti contoh
payload di laporan. Untuk memakai backend sungguhan:

```bash
# .env
VITE_API_MODE=live
VITE_API_BASE_URL=/api
VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000
```

### Menjalankan mode live di Windows

Dari root repo, siapkan venv, model Sprint 3, dan berkas environment lokal sesuai
[panduan backend](ml/README.md#backend-dan-sqlite-sprint-6a). Jalankan backend di terminal pertama.

```powershell
. .\ml\runtime\backend.env.ps1
rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage init-db
rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage seed
rtk proxy ml\.venv\Scripts\python.exe -m uvicorn sikembang_backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

Jalankan frontend dari terminal kedua.

```powershell
rtk proxy npm.cmd ci
$env:VITE_API_MODE = 'live'
$env:VITE_API_BASE_URL = '/api'
$env:VITE_DEV_PROXY_TARGET = 'http://127.0.0.1:8000'
rtk proxy npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Buka `http://127.0.0.1:5173`. Masuk menggunakan akun seed `marketing`, `ppic`, atau `pfa`
dan password masing-masing dari konfigurasi backend. Sesi browser memakai JWT dan membaca peran
melalui `/api/auth/me`. Token tersimpan per tab. Gunakan **Keluar** untuk mengganti akun.

Untuk menjalankan mock, mulai ulang Vite dengan `$env:VITE_API_MODE = 'mock'` dan kosongkan
`VITE_DEV_PROXY_TARGET`. Mock menjalankan MSW dan menampilkan pemilih peran serta simulator.
Mode live mengirim telemetry demo ke FastAPI melalui API perangkat yang sudah diregistrasi.
Pada build live, host frontend perlu menyediakan route `/api` atau konfigurasi base URL yang sesuai.

| Skrip                             | Fungsi                                   |
| --------------------------------- | ---------------------------------------- |
| `npm run dev`                     | Dev server                               |
| `npm run build`                   | Typecheck lalu build produksi ke `dist/` |
| `npm run lint` / `npm run format` | ESLint / Prettier                        |
| `npm test`                        | Vitest                                   |

## Struktur folder

```text
sikembang/
├── .github/  # CI GitHub Actions
│   └── workflows/
│       └── ci.yml
├── docs/  # dokumentasi teknis
│   └── architecture.md  # arsitektur dan cara ganti backend
├── public/  # aset statis (+ service worker MSW)
│   ├── favicon.svg
│   └── mockServiceWorker.js
├── src/  # kode aplikasi
│   ├── api/  # satu-satunya pintu ke backend
│   │   ├── contracts/  # skema Zod bentuk data backend
│   │   │   └── index.ts
│   │   ├── mocks/  # MSW: backend palsu untuk mode mock
│   │   │   ├── browser.ts
│   │   │   ├── db.ts  # data awal mock
│   │   │   └── handlers.ts  # handler MSW
│   │   ├── services/  # satu fungsi per endpoint
│   │   │   └── index.ts
│   │   ├── case.test.ts
│   │   ├── case.ts  # konversi snake_case <-> camelCase
│   │   ├── config.ts  # baca env
│   │   ├── errors.ts  # ApiError dan pesan ramah
│   │   ├── http.ts  # klien HTTP, token, galat
│   │   └── queries.ts  # hook React Query + kunci cache
│   ├── app/  # provider, router, sesi
│   │   ├── providers.tsx
│   │   ├── router.tsx
│   │   └── session.tsx  # sesi JWT live dan peran demo mock
│   ├── components/  # komponen bersama
│   │   ├── layout/  # AppShell dan navigasi per peran
│   │   │   └── AppShell.tsx
│   │   └── ui/  # primitif UI (Button, Tag, Field, Modal, dst.)
│   │       └── index.tsx
│   ├── features/  # satu folder per peran/layar
│   │   ├── orders/  # Marketing: catat pesanan
│   │   │   └── OrderFormPage.tsx
│   │   ├── planning/  # PPIC: perencanaan dan hitung kebutuhan
│   │   │   └── PlanningPage.tsx
│   │   ├── requests/  # PFA: dokumen permintaan bahan
│   │   │   └── RequestsPage.tsx
│   │   ├── review/  # PPIC: tinjau, ubah, tolak AI, setujui
│   │   │   ├── decisions.test.ts
│   │   │   ├── decisions.ts  # logika keputusan PPIC (murni, dites)
│   │   │   └── ReviewPage.tsx
│   │   └── simulator/  # demo timbangan IoT
│   │       └── SimulatorPage.tsx
│   ├── lib/  # util murni (format, periode, cn)
│   │   ├── cn.ts
│   │   ├── format.ts
│   │   └── period.ts
│   ├── styles/  # Tailwind + design tokens
│   │   ├── index.css
│   │   └── tokens.css  # warna, font, radius
│   ├── test/  # (disiapkan untuk setup tes bersama)
│   └── main.tsx
├── .env.example  # contoh variabel lingkungan
├── .gitignore
├── .prettierrc  # format kode
├── eslint.config.js  # lint
├── index.html  # titik masuk HTML
├── package.json  # dependensi dan skrip
├── README.md  # dokumen ini
├── tsconfig.json  # TypeScript strict
└── vite.config.ts  # Vite, alias @, proxy dev, Vitest
```

Prinsipnya: **satu folder fitur per peran/layar** di `features/`, **satu pintu ke backend** di `api/`,
**satu sumber desain** di `styles/tokens.css`. Komponen tidak memanggil `fetch` langsung.

## Layar

| Rute                    | Peran     | Isi                                                                        |
| ----------------------- | --------- | -------------------------------------------------------------------------- |
| `/login`                | Live      | Autentikasi akun dashboard                                                |
| `/marketing/orders/new` | Marketing | Catat pesanan terkonfirmasi                                                |
| `/ppic`                 | PPIC      | Ringkasan minggu ini, stok, tombol hitung kebutuhan                        |
| `/ppic/review/:period`  | PPIC      | Tinjau draf: Terima, Ubah, atau Tolak AI per bahan, lalu setujui dan kirim |
| `/pfa/requests`         | PFA       | Dokumen permintaan bahan yang sudah dikirim                                |
| `/demo/simulator`       | Mock      | Simulator timbangan IoT untuk demo                                         |

## Aturan desain

- Ukuran teks hanya 12/14/16 px, radius hanya 8/12/16 px, warna dominan netral dari palet proyek.
- Tombol dan highlight memakai fill kontras tinggi, bukan stroke. Outline hanya untuk fokus keyboard.
- Status selalu punya label teks (Segar, Usang, Ditolak), tidak mengandalkan warna saja.
- Detail dan catatan aksesibilitas: [docs/architecture.md](docs/architecture.md).

## Yang belum ada (TODO)

- Layar revisi pesanan (`PUT /api/orders/{id}` dengan penanganan 409 `VERSION_CONFLICT`). Service sudah ada di `ordersApi.update`.
- Daftar menu: `MENU_OPTIONS` di `features/orders/OrderFormPage.tsx` masih statis. Perlu endpoint menu atau `GET /api/menus`.
- Konfirmasi "Terima permintaan" di sisi PFA belum ada endpoint-nya.
- Tampilan indikator musim (Ramadan, pernikahan, akhir tahun) dari `season_flags` AI belum ditampilkan karena `POST /api/ai/predict` hanya dipanggil backend.
