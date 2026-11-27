# Implementasi sistem SiKembang

SiKembang mendukung perencanaan pengadaan bahan baku SonoKembang Catering Malang. Temuan F3 pada Deliverable 1 berkaitan dengan perubahan pesanan yang diteruskan melalui chat dan berisiko tidak sinkron dengan PPIC. F4 berkaitan dengan pencatatan stok manual dan estimasi kebutuhan bahan yang meleset. Rancangan To-Be D2 menggabungkan pencatatan pesanan terkonfirmasi, timbangan IoT, prediksi tambahan, kalkulasi belanja, validasi PPIC, dan penerusan permintaan ke PFA. Prototipe berakhir saat PFA menerima daftar tervalidasi. Pembelian ke pemasok, pembayaran, eksekusi produksi, pengiriman, serta sinkronisasi langsung dengan Sunnyday atau Ecount berada di luar implementasi ini.

[Diagram arsitektur keseluruhan](diagrams/01-system.svg) · [Sumber Mermaid](diagrams/01-system.mmd) · [Sequence diagram](diagrams/06-sequence.svg) · [Sumber Mermaid](diagrams/06-sequence.mmd).

## Arsitektur dan layanan SoaML

Backend adalah **modular monolith**. Satu proses Uvicorn melayani router FastAPI. Kode dipisah menurut tanggung jawab SoaML, memakai dependensi Python internal dan satu berkas SQLite. Pemisahan modul memetakan operasi D2 ke sumber yang jelas. Satu proses dan database cocok untuk demo lokal dengan tiga peran, artefak inferensi lokal, dan alur kalkulasi yang perlu konsistensi data lintas modul. Batas integrasi eksternal adalah REST antara browser/perangkat dan FastAPI.

| Layanan SoaML | Operasi D2 | Sumber implementasi | Perilaku aktual |
| --- | --- | --- | --- |
| OrderService | `catatPesanan`, `revisiPesanan`, `ambilPesananTerkonfirmasi` | `sikembang_backend/orders.py` | Mencatat order terkonfirmasi, menyimpan setiap revisi, menyaring order berdasarkan minggu dan visibilitas, serta memecah BOM terkonfirmasi untuk kalkulasi. |
| InventoryIoTService | `kirimTelemetri`, `ambilStokTerkini` | `sikembang_backend/inventory.py` | Memvalidasi paket dan mapping sensor, mengonversi satuan, mengaudit penerimaan/penolakan, serta mengembalikan stok dan kesegaran. |
| AIForecastService | `buatPrediksi` | `ai_forecast/api.py`, `ai_forecast/predictor.py`, `sikembang_backend/forecast.py`, `sikembang_backend/forecast_feedback.py` | `ForecastService` membuat prediksi tambahan dari snapshot pada cutoff. Adapter database menyediakan riwayat demand, BOM, bukti feedback dan run. `Predictor` memuat artefak XGBoost dan metadata. |
| ProcurementCalcService | `hitungKebutuhan` | `sikembang_backend/procurement.py`, `sikembang_backend/drafts.py` | Menerima minggu ISO dan pilihan AI. Menggabungkan BOM terkonfirmasi, prediksi opsional, stok dan safety stock, lalu membuat satu draf. |
| ShoppingListService | `simpanDraf`, `validasiDaftar`, `teruskanKePFA`, `ambilDaftarBelanja` | `sikembang_backend/drafts.py`, `sikembang_backend/shopping_lists.py` | `DraftService` mereservasi periode dan menyimpan rincian. `ShoppingListService` memvalidasi keputusan, menjalankan handoff, serta membuat proyeksi PPIC dan PFA. |

[Diagram komponen backend](diagrams/02-backend.svg) · [Sumber Mermaid](diagrams/02-backend.mmd) · [Kontrak 11 endpoint](api.md) · [ERD dan kamus data](database.md).

### Komponen pendukung dan alur panggilan

- `app.py:create_app` mengikat instance service, router, session factory, auth, jam, dan handler galat. Startup memeriksa skema database dan mencoba memuat artefak. Jika model tidak tersedia, health mengembalikan `model_version=null` dan kalkulasi tanpa AI tetap tersedia. `settings.py` membaca `SIKEMBANG_DB_PATH`, `SIKEMBANG_JWT_SECRET`, `SIKEMBANG_SYSTEM_KEY`, `SIKEMBANG_ARTIFACT`, dan `SIKEMBANG_DEMO_CUTOFF`. Cutoff override berlaku pada rute prediksi langsung, sedangkan kalkulasi memakai jam aplikasi. [Factory](../../ml/src/sikembang_backend/app.py) · [Konfigurasi](../../ml/src/sikembang_backend/settings.py).
- Router dan skema Pydantic berlokasi di modul domain, termasuk adapter rute AI. Validasi struktur dilakukan sebelum service. `errors.py` memasang envelope JSON standar. Pencarian dan mutasi memakai SQLAlchemy di service atau adapter data, dengan tabel dideklarasikan di `models.py`. [Handler galat](../../ml/src/sikembang_backend/errors.py) · [ORM](../../ml/src/sikembang_backend/models.py).
- `db.py` menyiapkan engine, FK SQLite dan sesi. CLI `python -m sikembang_backend.manage init-db` membuat atau melengkapi skema. Perintah `seed` mengisi fixture demo secara idempoten terhadap baris yang kompatibel. File database yang sama mempertahankan perubahan setelah restart. [Database](../../ml/src/sikembang_backend/db.py) · [Seed](../../ml/src/sikembang_backend/seed.py) · [CLI](../../ml/src/sikembang_backend/manage.py).
- Saat PPIC memanggil kalkulasi, `ProcurementCalcService` memanggil `DraftService.reserve`, `OrderService.explode_bom`, `InventoryIoTService.stock`, dan `ForecastService.build_run` jika dipilih. `DatabaseSnapshots.read` menggunakan sesi yang sama. Setelah semua input dan satuan lolos validasi, `DatabaseRuns.record` menyimpan run opsional dan `DraftService.populate` mengisi draf di transaksi tersebut. [Kalkulasi](../../ml/src/sikembang_backend/procurement.py) · [Adapter forecast](../../ml/src/sikembang_backend/forecast.py).
- `auth.py` memverifikasi password PBKDF2-HMAC-SHA256 dengan salt dan menerbitkan JWT bertanda tangan HS256 berumur satu jam. Peran dan status aktif tetap diperiksa di SQLite. DEVICE menggunakan digest SHA-256 kunci perangkat dan mapping sensor-bahan. SYSTEM menggunakan otoritas internal untuk kalkulasi serta header `X-System-Key` untuk rute HTTP tertentu bila dikonfigurasi. [Autentikasi dan otorisasi](../../ml/src/sikembang_backend/auth.py).
- Tes Python mencakup unit domain/ML, akses role, persistensi, inferensi, dan alur pengadaan. Frontend menggunakan Vitest dan MSW untuk kontrak serta kondisi antarmuka. Script verifikasi tambahan menjalankan HTTP nyata dan browser terhadap backend, dengan basis data uji terisolasi. [Tes Python](../../ml/tests) · [Bukti Sprint 7](../testing).

### Struktur repositori

```text
II3120-G08-sikembang/
├── ml/
│   ├── pyproject.toml
│   ├── requirements-dev.lock
│   ├── config/
│   ├── artifacts/xgb-v1-f9a770b940f71fc8/
│   ├── src/
│   │   ├── sikembang_backend/
│   │   │   ├── app.py, settings.py, db.py, models.py
│   │   │   ├── auth.py, errors.py, manage.py, seed.py
│   │   │   ├── orders.py, inventory.py, forecast.py, forecast_feedback.py
│   │   │   └── procurement.py, drafts.py, shopping_lists.py
│   │   └── ai_forecast/
│   │       ├── api.py, predictor.py, feedback_provider.py
│   │       └── dataset.py, features.py, splits.py, train.py, evaluate.py
│   ├── tests/
│   └── testing/verify_sprint7_browser.mjs
├── src/
│   ├── main.tsx
│   ├── app/                   # router, provider, sesi
│   ├── api/                   # fetch, kontrak Zod, kueri, adapter MSW
│   └── features/              # tampilan per peran dan simulator
├── firmware/esp32_scale/
│   ├── esp32_scale.ino
│   ├── scale_telemetry.h
│   └── README.md
└── docs/
    ├── architecture.md
    ├── backend-data.md
    ├── testing/
    └── deliverable3/
```

## Stack yang digunakan

| Lapisan | Teknologi dan versi |
| --- | --- |
| Backend lokal | CPython 3.13.2 pada verifikasi Sprint 7, SQLite 3.45.3 dari runtime tersebut, FastAPI 0.165.0, Uvicorn 0.54.0, SQLAlchemy 2.0.53, Pydantic 2.14.4, PyJWT 2.15.1. |
| Dataset, model, evaluasi | NumPy 2.2.6, XGBoost 3.1.3, scikit-learn 1.6.1, Matplotlib 3.10.3. Pemrosesan dataset menggunakan NumPy serta modul standar Python untuk JSON/CSV. Pandas tidak tercantum sebagai dependensi pipeline. |
| Web | React dan React DOM 19.3.1, TypeScript 6.0.3, Vite 8.3.8, Tailwind CSS 4.3.5, React Router DOM 7.18.6, TanStack Query 5.108.4, React Hook Form 7.92.0, Zod 4.6.7, dan Fetch API. Verifikasi memakai Node 24.19.0 dan npm 11.17.0. |
| Firmware | ESP32 Dev Module klasik, ADC HX711, load cell, OLED SSD1306 128 × 64 dan tombol tare. Arduino CLI 1.5.1, ESP32 core 2.0.17, HX711 Arduino Library 0.7.5, Adafruit GFX 1.12.4, SSD1306 2.5.16, dan BusIO 1.17.4. Sketch memakai WiFi, HTTPClient, Preferences, Wire, SNTP dan FreeRTOS dari core. |
| Verifikasi | Pytest 9.1.1 dan httpx 0.28.1, Vitest 5.1.1, MSW 3.0.7, kompilasi firmware dan uji host C++. |

[Python project](../../ml/pyproject.toml) · [Lockfile Python](../../ml/requirements-dev.lock) · [Lockfile web](../../package-lock.json) · [Verifikasi Sprint 7](../testing/sprint7_test_results.txt) · [Firmware](../../firmware/esp32_scale/README.md).

## Kalkulasi pengadaan

Untuk setiap bahan, sistem menjumlahkan porsi pada revisi pesanan terkonfirmasi yang terlihat pada cutoff, dikali takaran resep per porsi dari versi BOM pada baris menu. Revisi terbaru dapat mengubah kuantitas dan minggu acara. Model memprediksi **tambahan di luar kebutuhan terkonfirmasi**. Fitur historis `prev_error_adj` sudah masuk inferensi, sehingga kalkulasi memakai hanya hasil `predicted_demand`. Stok terkini dari IoT masuk sebagai pengurang kebutuhan pembelian. Safety stock ditambahkan sebagai buffer.

```text
bom_confirmed_need = Σ (confirmed_portions × quantity_per_portion)
recommended_purchase = max(0, bom_confirmed_need + ai_additional_forecast
                              + safety_stock − iot_available_stock)
```

Kuantitas disetarakan ke kg, liter, atau butir sesuai master. Perhitungan memakai pembulatan desimal half-up ke 0,001 untuk kg/liter atau bilangan bulat untuk butir. Angka stok yang telah tersimpan tetap dipakai saat usang dengan peringatan `STALE_STOCK`. PPIC wajib mencatat verifikasi sebelum menyetujui. Stok kosong atau pengukuran yang belum tersedia pada cutoff menghasilkan `INVENTORY_UNAVAILABLE`. Tanpa resep valid, kalkulasi gagal dengan `MISSING_BOM`. Jika AI dipilih, histori kurang dari empat minggu yang memenuhi syarat menghasilkan `INSUFFICIENT_HISTORY` dan artefak yang gagal dimuat menghasilkan `MODEL_UNAVAILABLE`. Pilihan eksplisit tanpa AI menggunakan tambahan 0 dan menyimpan draf tanpa run. [Rumus dan pembulatan](../../ml/src/sikembang_backend/drafts.py) · [Alur kalkulasi](../../ml/src/sikembang_backend/procurement.py).

| Contoh beras | BOM, kg | Tambahan, kg | Safety, kg | Stok, kg | Bersih, kg |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixture deterministik D2, dengan nilai AI contoh | 45 | 8 | 5 | 20,5 | 37,5 |
| Fixture D2 dengan komponen AI disetel nol pada tes rumus | 45 | 0 | 5 | 20,5 | 29,5 |
| Sprint 7 dengan forecast, sebelum telemetri | 69 | 4,498 | 5 | 20,5 | 57,998 |
| Sprint 7 dengan forecast, setelah paket simulator 17.500 g | 69 | 4,498 | 5 | 17,5 | 60,998 |
| Sprint 7 tanpa forecast pada basis data alternatif | 60 | 0 | 5 | 20,5 | 44,5 |

Kedua run pembanding stok memiliki order, model, dan komponen lain yang sama. Penurunan stok 3 kg menaikkan rekomendasi 3 kg. Skenario Sprint 7 tanpa forecast memiliki order berbeda. Pada skenario tersebut, permintaan dengan AI dan artefak absen menghasilkan HTTP 500, kemudian permintaan eksplisit tanpa AI menghasilkan HTTP 201 dengan `forecast_run_id=null`, `model_version=null`, dan semua tambahan nol. Perbandingan satu variabel AI pada fixture D2 memverifikasi aritmetika, sedangkan nilai 4,498 kg pada run Sprint 7 berasal dari artefak asli. [Tes aritmetika D2](../../ml/tests/test_backend_procurement.py) · [Bukti HTTP Sprint 7](../testing/sprint7_http_evidence.json).

## Frontend dan alur peran

| Peran | Layar | Perilaku |
| --- | --- | --- |
| Marketing | `/marketing/orders/new` | Mencatat pesanan terkonfirmasi melalui formulir dan menampilkan hasil simpan. Revisi tersedia melalui `PUT /api/orders/{order_id}` dan adapter `ordersApi.update`. Layar tersedia untuk order baru, sehingga demonstrasi revisi memakai API. |
| PPIC | `/ppic` dan `/ppic/review/:period` | Melihat pesanan terkonfirmasi dan stok pada minggu berjalan, menghitung dengan atau tanpa prediksi, lalu meninjau draf. Keputusan per item dapat menerima rekomendasi, mengubah angka, atau menolak komponen AI dengan alasan. PPIC menyetujui kemudian mengirim bila ada kuantitas final positif. |
| PFA | `/pfa/requests` | Melihat daftar terkirim dengan item kuantitas final positif, nama, satuan, dan catatan yang diteruskan. |
| Simulator | `/demo/simulator` | Layar tersedia setelah memilih peran di mode mock dan simulasinya ditangani MSW. Pada mode live, gunakan klien HTTP atau skrip dengan kunci DEVICE terdaftar untuk mengirim paket sintetis. |

Di mode live, frontend login melalui `/api/auth/login`, menyimpan JWT di `sessionStorage` per tab, lalu membaca identitas server melalui `/api/auth/me`. Router menyesuaikan tampilan berdasarkan peran. Akses API tetap ditegakkan backend. Reload memulihkan sesi melalui server, sementara logout atau kedaluwarsa mengosongkan token dan cache kueri. `src/api/http.ts` menangani fetch, JWT, timeout, dan galat. `src/api/case.ts` mengonversi casing dan `src/api/contracts` memvalidasi respons dengan Zod. Dalam mode live, bootstrap membersihkan worker mock sebelum UI dimuat. Vite dapat mem-proxy `/api` ke FastAPI. Mode mock memakai pemilih peran dan data MSW untuk demonstrasi UI lokal.

Penolakan AI per item memakai rumus tanpa tambahan dengan pembulatan yang selaras di sisi browser. PPIC dapat menyesuaikan kuantitas akhir dan alasan dikirim pada `ppic_notes`. Rekomendasi awal tetap tersedia untuk audit. Setelah approval semua kuantitas nol, daftar tetap tervalidasi dengan status pengadaan tidak diperlukan. PPIC dapat membuka kembali daftar tervalidasi untuk mencoba pengiriman setelah gangguan, selama daftar belum berstatus terkirim. Bukti Sprint 7 mencatat browser mode live mengikuti API nyata tanpa intersepsi MSW, serta mode mock melalui worker secara terpisah.

[Alur pengguna](diagrams/10-user-flow.svg) · [Sumber Mermaid](diagrams/10-user-flow.mmd) · [Lifecycle](diagrams/07-lifecycle.svg) · [Sumber Mermaid](diagrams/07-lifecycle.mmd) · [Arsitektur frontend](../architecture.md) · [Bukti browser](../testing/sprint7_browser_evidence.json).

## Perangkat, firmware, dan simulasi

Load cell mengirim sinyal ke HX711. Pin HX711 DOUT/SCK terhubung ke GPIO 32/33. OLED SSD1306 128 × 64 beralamat I²C `0x3C` dengan SDA GPIO 25 dan SCL GPIO 26. Tombol tare aktif LOW pada GPIO 27 dengan pull-up internal. Serial Monitor memakai 115200 baud. Faktor kalibrasi sementara untuk perangkat tim adalah −120,0 dan perlu dikonfirmasi dengan massa referensi.

Firmware membaca satu konversi HX711 ketika data siap dan memeriksa stabilitas lima sampel dengan spread maksimal 3 g. Tahan tare satu detik saat platform kosong untuk menyimpan offset di Preferences. Boot memulihkan offset tersebut apabila tersedia. Toleransi nol awal adalah 0 g dan pembacaan negatif ditahan. Fitur ini menjaga offset yang telah ditentukan operator. Pengaturan nol otomatis dari sketch lama tidak dijalankan pada firmware integrasi.

Papan memakai Wi-Fi LAN dan menunggu sinkronisasi SNTP sebelum membuat `recorded_at` UTC. Firmware mengirim JSON dengan `sensor_id`, `ingredient_id`, `measured_weight`, `unit="g"`, dan `recorded_at` ke `POST /api/iot/telemetry` menggunakan `X-Device-Key`. Firmware mengirim pembacaan pertama, perubahan minimum 10 g atau heartbeat 60 detik saat stabil, dengan jarak minimum 2 detik. Tugas jaringan terpisah memakai timeout HTTP 3 detik, percobaan koneksi Wi-Fi 12 detik, dan backoff 2–30 detik. Dalam mode demo, gunakan paket sintetis ketika alat fisik belum siap.

Panduan firmware memuat tabel wiring lengkap, instalasi core dan library, pengisian konfigurasi lokal, kompilasi, upload, kalibrasi, koneksi LAN, log serial, pemeriksaan API/database dan dashboard. Uji host dan build target lulus pada Sprint 7. Verifikasi rangkaian, kalibrasi bermassa dan penerimaan paket fisik masih memerlukan papan yang terdeteksi melalui port serial. Bukti yang ada untuk perubahan stok dan efek pengadaan menggunakan paket simulator.

[Diagram perangkat dan REST](diagrams/08-iot.svg) · [Sumber Mermaid](diagrams/08-iot.mmd) · [Panduan wiring, Arduino, dan fallback](../../firmware/esp32_scale/README.md) · [Hasil uji Sprint 7](../testing/sprint7_test_results.txt).
