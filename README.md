# SiKembang

**SiKembang** adalah sistem perencanaan kebutuhan bahan baku dan pemantauan stok gudang berbasis **IoT (ESP32 + Load Cell 20kg)** dan **AI Forecasting (XGBoost)** untuk operasional katering (Kelompok 08 — II3120).

Alur end-to-end: **Marketing** mencatat pesanan terkonfirmasi → sistem memecah resep (BOM), **AI XGBoost** memprediksi kebutuhan tambahan musiman & volume order, **timbangan IoT ESP32** memperbarui stok gudang secara real-time → **PPIC** meninjau rekomendasi (Terima / Ubah / Tolak AI) → **PFA** menerima dokumen permintaan bahan siap pengadaan.

> **Dokumentasi lengkap:** [Paket Handoff Deliverable 3](docs/deliverable3/README.md) · [Panduan Hardware ESP32](firmware/README.md) · [Arsitektur Frontend](docs/architecture.md) · [Bukti Pengujian](docs/deliverable3/EVIDENCE_INDEX.md)

---

## Coba Cepat untuk Dosen / Penguji

Tersedia **dua cara** mencoba aplikasi langsung setelah `git clone`:

### Opsi A — Paling Cepat (30 detik, Tanpa Python / Mode Mock)

Cocok untuk langsung mengeksplorasi seluruh antarmuka **Marketing → PPIC → PFA** beserta **Simulator IoT** di browser tanpa instalasi backend Python:

```bash
npm install
npm run dev
```

Buka **`http://localhost:5173`**. Gunakan pemilih peran (`MARKETING`, `PPIC`, `PFA`) di kanan atas navbar serta menu **Simulator IoT** untuk mencoba seluruh alur.

---

### Opsi B — Mode Live Full-Stack dalam 1 Perintah (FastAPI + XGBoost + SQLite + React)

Artefak model XGBoost siap pakai (`ml/artifacts/default/`) sudah disertakan di repositori sehingga **tidak perlu menjalankan training ulang**. Jalankan satu perintah berikut dari root repo:

- **Windows (PowerShell):**
  ```powershell
  .\scripts\start-demo.ps1
  ```
  *(Gunakan `.\scripts\start-demo.ps1 -ResetDb` jika ingin mengulang demo dengan database bersih.)*

- **macOS / Linux / Git Bash:**
  ```bash
  bash scripts/start-demo.sh
  ```
  *(Gunakan `bash scripts/start-demo.sh --reset-db` untuk mereset database demo.)*

Script otomatis menyiapkan `ml/.venv`, menginstal dependensi, menginisialisasi & mengisi SQLite minggu berjalan, mendaftarkan sensor ESP32, lalu menyalakan:

- **Frontend Dashboard:** `http://localhost:5173`
- **Swagger / OpenAPI Docs:** `http://127.0.0.1:8000/docs`
- **Health Check (cek versi model XGBoost):** `http://127.0.0.1:8000/api/health`

#### Akun Demo Mode Live

| Peran | Username | Password | Fungsi Utama |
|---|---|---|---|
| **Marketing** | `marketing` | `demo-marketing-123` | Catat pesanan terkonfirmasi (gunakan tanggal acara minggu ini agar langsung masuk ke PPIC) |
| **PPIC** | `ppic` | `demo-ppic-123456` | Pantau stok IoT real-time, hitung kebutuhan (AI XGBoost), tinjau draf, setujui & kirim ke PFA |
| **PFA** | `pfa` | `demo-pfa-1234567` | Terima dan cetak/simpan PDF dokumen permintaan bahan yang sudah disetujui PPIC |

#### Uji Live Update Sensor IoT Tanpa Perangkat Fisik (Opsional)

Saat membuka halaman **PPIC** (`/ppic`), jalankan perintah berikut di terminal lain untuk mensimulasikan timbangan ESP32 mengirim berat Beras **`170,4 g`** (otomatis dikonversi menjadi **`0,17 kg`** dengan status **Segar** dalam 2,5 detik):

**PowerShell (Windows):**
```powershell
$ts = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
curl.exe -i -X POST "http://127.0.0.1:8000/api/iot/telemetry" `
  -H "Content-Type: application/json" `
  -H "X-Device-Key: demo-esp32-physical-rice-key-0000001" `
  -d "{`"sensor_id`":`"SNS-GDG-ESP32-01`",`"ingredient_id`":`"ING-001`",`"measured_weight`":170.4,`"unit`":`"g`",`"recorded_at`":`"$ts`"}"
```

**Bash (macOS / Linux):**
```bash
TS=$(date -u +"%Y-%m-%dT%H:%M:%S.000000Z")
curl -i -X POST "http://127.0.0.1:8000/api/iot/telemetry" \
  -H "Content-Type: application/json" \
  -H "X-Device-Key: demo-esp32-physical-rice-key-0000001" \
  -d "{\"sensor_id\":\"SNS-GDG-ESP32-01\",\"ingredient_id\":\"ING-001\",\"measured_weight\":170.4,\"unit\":\"g\",\"recorded_at\":\"${TS}\"}"
```

> Untuk pengujian menggunakan **perangkat keras ESP32 + Load Cell 20kg + OLED SSD1306 fisik**, lihat panduan lengkap pinout, kalibrasi, `secrets.h`, dan upload Arduino di [firmware/README.md](firmware/README.md).

---

## Teknologi Utama

| Lapisan | Teknologi | Peran |
|---|---|---|
| **Frontend** | React 19 + TypeScript (strict) + Vite 8 + Tailwind CSS v4 | Dashboard responsif dengan tipografi Inter / Plus Jakarta Sans (`tabular-nums`) |
| **State & Validasi** | TanStack Query + React Hook Form + Zod + MSW | Polling stok real-time (2,5 dtk), kontrak API runtime, dan mode mock standalone |
| **Backend API** | FastAPI + SQLAlchemy + SQLite + PyJWT | REST API 5 layanan (Orders, Inventory IoT, AI Forecast, Procurement, Shopping Lists) |
| **AI Forecasting** | XGBoost (`model.ubj`) + fitur musiman & feedback IoT | Prediksi kebutuhan tambahan mingguan (Ramadan, musim nikahan, akhir tahun, tren 4 minggu) |
| **IoT Hardware** | ESP32 DevKit + HX711 (Load Cell 20kg) + OLED SSD1306 | Pembacaan berat stabil real-time, auto-zero, SNTP UTC, HTTP POST dengan `X-Device-Key` |

---

## Skrip Pengembangan & Pengujian

| Perintah | Fungsi |
|---|---|
| `npm run dev` | Menjalankan dev server frontend (`http://localhost:5173`) |
| `npm run build` | Typecheck (`tsc --noEmit`) + build produksi ke `dist/` |
| `npm run lint` / `npm run format` | ESLint / Prettier |
| `npm test` | Menjalankan seluruh unit test frontend (Vitest) |
| `ml\.venv\Scripts\python.exe -m pytest ml/tests -q` | Menjalankan seluruh unit & integration test backend + AI *(pasang `[test]` jika perlu)* |

---

## Struktur Repositori

```text
II3120-G08-sikembang/
├── src/                        # Frontend React 19 + TypeScript
│   ├── api/                    # Kontrak Zod, HTTP client, TanStack Query, MSW mock
│   ├── app/                    # Providers, router, manajemen sesi JWT & mock
│   ├── components/             # AppShell (navbar) dan primitif UI modern
│   ├── features/               # Fitur per peran: auth, orders, planning, review, requests, simulator
│   ├── lib/                    # Formatter angka/presisi stok & util periode ISO
│   └── styles/                 # Tailwind CSS v4 & design tokens
├── ml/                         # Backend FastAPI, SQLite, dan Modul AI XGBoost
│   ├── artifacts/default/      # Artefak model XGBoost siap pakai (model.ubj + manifest.json)
│   ├── config/                 # Katalog BOM, kalender musiman, konfigurasi sintetis
│   ├── src/ai_forecast/        # Pipeline fitur, training, evaluasi, dan predictor XGBoost
│   ├── src/sikembang_backend/  # FastAPI app, auth JWT/Device-Key, IoT, procurement, shopping lists
│   └── tests/                  # Suite pengujian backend & AI
├── firmware/                   # Firmware perangkat keras IoT ESP32
│   ├── README.md               # Panduan lengkap wiring, upload Arduino, dan uji curl
│   ├── esp32_sikembang/        # Firmware utama (HX711 + OLED SSD1306 + NTP + secrets.example.h)
│   └── esp32_scale/            # Referensi firmware FreeRTOS & host unit test C++
├── scripts/                    # Script 1-perintah untuk menjalankan demo live (Windows & Unix)
└── docs/                       # Arsitektur, spesifikasi data, dan paket handoff Deliverable 3
```

---

## Daftar Layar Aplikasi

| Rute | Peran | Fungsi |
|---|---|---|
| `/login` | Live | Autentikasi JWT akun dashboard (`marketing`, `ppic`, `pfa`) |
| `/marketing/orders/new` | Marketing | Catat pesanan terkonfirmasi beserta detail menu dan porsi |
| `/ppic` | PPIC | Ringkasan pesanan minggu ini, stok gudang live IoT, dan tombol hitung kebutuhan |
| `/ppic/review/:period` | PPIC | Tinjau rekomendasi belanja (rincian AI, Terima / Ubah / Tolak AI), setujui & kirim ke PFA |
| `/pfa/requests` | PFA | Dokumen permintaan bahan yang telah disetujui PPIC (siap cetak / simpan PDF) |
| `/demo/simulator` | Mock | Simulator timbangan IoT untuk demonstrasi tanpa backend |
