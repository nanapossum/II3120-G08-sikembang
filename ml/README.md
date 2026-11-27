# Dataset sintetis AIForecastService

Generator ini membangun histori order, snapshot BOM, rekonsiliasi stok, dan contoh prediksi mingguan dalam WIB. Satuan asli adalah kg, liter, atau butir sesuai bahan. Semua order, resep, kalender perencanaan dan pergerakan stok merupakan simulasi berversi. Hasil ini disiapkan untuk Sprint 3.

## Reproduksi dari root repo

Gunakan Python 3.13 pada Windows. Dependensi paket dideklarasikan di `ml/pyproject.toml`. Lockfile merekam versi yang digunakan saat verifikasi. Contoh berikut memakai venv baru di bawah `ml/`.

```powershell
rtk proxy py -3.13 -m venv ml/.venv
rtk proxy ml\.venv\Scripts\python.exe -m pip install -r ml/requirements-dev.lock
rtk proxy ml\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e ml
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.dataset --seed 3120 --output ml/generated/synthetic-v1
rtk proxy ml\.venv\Scripts\python.exe -m pytest ml/tests -q
```

Ekspor menggunakan staging sebelum publikasi. Pengulangan dengan output identik memverifikasi kesamaan berkas. Untuk seed, konfigurasi atau versi pipeline lain, gunakan direktori output baru. Dari checkout, default konfigurasi berada di `ml/config/`. Wheel juga membawa ketiga fixture. Parameter `--config-dir` dapat menunjuk salinan konfigurasi berversi.

## Membaca bundle

| Berkas | Isi |
|---|---|
| `metadata.json` | Sumber sintetis, versi lingkungan dan fixture, checksum SHA-256, tanggal cakupan, jumlah observasi, batas split, urutan dan definisi fitur. |
| `order_versions.jsonl` | Kronologi draft, konfirmasi, revisi, pembatalan, pemenuhan, dan porsi dengan versi BOM. |
| `weekly_demand.jsonl` | Total BOM terpenuhi tiap bahan/minggu dan waktu lengkapnya diketahui. |
| `weekly_feedback.jsonl` | Prediksi referensi Senin, bukti ledger/sensor, rekonsiliasi, residual, alasan netral serta waktu tersedia. |
| `train.csv`, `validation.csv`, `test.csv` | Satu baris per bahan, minggu ISO target dan cutoff. Kolom input persis mengikuti `metadata.model_features`. |
| `purged.csv` | Dua kelompok minggu yang disisihkan pada perbatasan split. |
| `insufficient_history.json` | Origin/bahan yang dikeluarkan bila salah satu dari empat minggu lag belum tersedia. |
| `summary.md` | Tabel distribusi train dalam satuan asli, pola musiman sintetis, dan ukuran partisi. |

Untuk training selanjutnya gunakan hanya 18 kolom pada `model_features` sebagai X, dalam urutan manifest. Label model adalah `target_scaled`. Untuk evaluasi per bahan, kembalikan prediksi ke satuan asli dengan `scale` dan bandingkan dengan `target_native`. Kolom audit mencakup `order_snapshot_id`, kuantitas native, `fulfilled_remaining`, dan `label_available_at`. Memasukkan kolom pemenuhan akhir akan membocorkan jawaban.

`build_features()` adalah jalur bersama replay dan inferensi. Empat lag berasal dari minggu lengkap sebelum minggu cutoff. Minggu yang terbukti nol sah. Minggu yang belum lengkap memicu `InsufficientHistory`. Feedback dipakai setelah rekonsiliasi minggu sebelumnya tersedia secara ketat sebelum cutoff, dengan batas ±25% dari skala bahan. Fitur netral memakai nilai 0 disertai flag ketersediaan. Ringkasan eksplorasi hanya mengakses distribusi train. Test dipertahankan untuk evaluasi akhir.

## Training dan evaluasi Sprint 3

Pasang dependensi dari lockfile CPython 3.13 Windows di atas. Untuk pemasangan dengan resolusi versi sendiri, pasang paket dengan extra `[train,test]`. Jalankan perintah ini dari root repo setelah bundle dataset tersedia.

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.train --dataset ml/generated/synthetic-v1 --output ml/artifacts --seed 3120
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.evaluate --dataset ml/generated/synthetic-v1 --artifact ml/artifacts/xgb-v1-f9a770b940f71fc8
```

Perintah training mencetak direktori run. Gunakan direktori tersebut pada `--artifact`. ID contoh di atas berasal dari bundle dan versi dependensi yang digunakan pada Sprint 3. Untuk mengulang eksperimen sambil mempertahankan run lama, berikan direktori `--output` berbeda.

| Keluaran run | Isi |
|---|---|
| `model.ubj` dan `manifest.json` | Model XGBoost native, checksum, versi aktual, urutan fitur, satuan, konfigurasi, rentang fit, dan metrik. |
| `evaluation.json` | Seleksi validation, ablation, rincian MAE/RMSE/bias per bahan dan kelompok test, serta waktu fit dan inferensi. |
| `predictions.csv` | Aktual, prediksi model sebelum dan sesudah pembulatan, nol, median historis, replay feedback, dan residual pada origin yang sama. |
| `charts/` | Enam grafik evaluasi dalam SVG dan PNG. |

XGBoost dipilih dari empat konfigurasi menggunakan MAE ternormalisasi validation. Model terpilih di-fit ulang pada baris train dan validation dengan label yang sudah tersedia saat origin test pertama. Perintah `evaluate` memuat artefak dalam proses Python baru dan memverifikasi ulang skor serta prediksi test melalui model tersimpan. Keluaran model dan evaluasi berada di `ml/artifacts/` yang dikecualikan dari Git. Seluruh skor berasal dari data sintetis.

## Inferensi Sprint 4

Jalankan harness setelah bundle Sprint 2 dan model Sprint 3 tersedia. Lockfile memiliki dependensi API dan tes. Untuk instalasi dengan resolusi versi sendiri, gunakan extra `[api,train,test]`.

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m pip install -r ml/requirements-dev.lock
rtk proxy ml\.venv\Scripts\python.exe -m pytest ml/tests -q
$env:SIKEMBANG_REPLAY_TOKEN = [System.Net.NetworkCredential]::new('', (Read-Host 'Token bearer harness lokal' -AsSecureString)).Password
rtk proxy ml\.venv\Scripts\python.exe -m uvicorn ai_forecast.harness:create_app --factory --host 127.0.0.1 --port 8010
```

Jalankan klien di terminal kedua dengan token lokal yang sama. Default cutoff harness adalah 5 Maret 2025 pukul 12.00 WIB, sehingga minggu yang dapat diminta adalah `2025-W10` dan `2025-W11`.

```powershell
$replayToken = [System.Net.NetworkCredential]::new('', (Read-Host 'Token bearer harness lokal' -AsSecureString)).Password
$request = @{target_period='2025-W10'; ingredient_ids=@('ING-001','ING-007','ING-012')} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8010/api/ai/predict' -Headers @{Authorization="Bearer $replayToken"} -ContentType 'application/json' -Body $request
```

`SIKEMBANG_ARTIFACT` dan `SIKEMBANG_REPLAY_DATASET` dapat menunjuk artefak serta bundle yang cocok. Untuk mereproduksi 422 riwayat kurang, mulai ulang harness dengan `SIKEMBANG_REPLAY_CUTOFF=2020-12-21T12:00:00+07:00` dan minta `2020-W52`. Harness ini memakai order dan feedback sintetis, bearer token lokal, dan penyimpanan run dalam memori satu proses.

Backend bersama dapat memanggil `create_router(service, identity_role)`. Dependensi `identity_role` harus memperoleh peran dari principal yang sudah terautentikasi. Isi `ForecastService` dengan satu `Predictor.load(...)` per proses, implementasi `SnapshotProvider` dan `RunRepository` backend. ProcurementCalcService bisa memanggil `service.forecast(planning_period, ingredient_ids, cutoff=cutoff, snapshot=snapshot)` secara langsung. Gunakan snapshot order/BOM dan cutoff yang sama dengan kalkulasi. Komponen AI yang dikonsumsi adalah `run.items[].predicted_demand`.

## Feedback AI–IoT Sprint 5

`HistoricalFeedbackProvider(reader).load(cutoff, ingredient_units)` menghasilkan mapping untuk `ForecastSnapshot.feedback`. Provider meminta satu minggu ISO tertutup sebelum minggu cutoff WIB, termasuk saat targetnya minggu depan. Reader mengembalikan bukti minggu tersegel terbaru yang tersedia **sebelum** cutoff tersebut. Run referensi harus berasal dari cutoff Senin 00.00 WIB dan diterbitkan dalam minggu itu sebelum pemenuhan pertama, bila ada. Jika beberapa kandidat memenuhi syarat, provider memakai waktu publikasi paling awal lalu ID untuk seri.

Untuk sumber fisik, reader backend perlu memasok status InventoryIoTService `ACCEPTED`, pemetaan sensor–bahan–lokasi yang berlaku pada saat pembacaan, nilai yang sudah dikonversi ke satuan dasar, status penutupan ledger, dan atribusi produksi beserta waktu pemenuhan pertama. Gunakan `PHYSICAL` hanya untuk bukti tersebut dengan run operasional `live`. Replay dari bundle Sprint 2 memakai `SIMULATED` dengan run baseline sintetis. Detail sumber dan alasan fallback disimpan pada run secara internal tanpa menambah field respons D2.

Reader operasional perlu mengambil waktu publikasi aktual dan BOM dari snapshot asal run. Jika memakai run `model_replay`, cantumkan batas ketersediaan label fit model per ID run pada `replay_fit_available_at`. Batas itu harus berada pada atau sebelum cutoff referensinya. Predictor mencegah koreksi sintetis dipakai pada snapshot operasional. Audit run menyimpan sumber, ID referensi, residual mentah, batas koreksi, dan ketersediaan bukti. Koreksi terpakai tersimpan pada item forecast.

Rekonsiliasi mengembalikan stok batas minggu lalu menghitung pemakaian dari stok awal, penerimaan, transfer, retur, waste, dan koreksi inventaris bertanda. Nilainya harus cocok dengan produksi yang dapat diatribusikan. Residual adalah `max(0, pemakaian teratribusi − BOM pada run referensi) − prediksi tambahan run referensi`. Batasi residual ke ±25% skala hasil empat lag dan masukkan ke XGBoost satu kali. Feedback yang belum layak menghasilkan nilai netral 0 serta alasan audit. Galat nol dengan bukti sah tetap memiliki flag ketersediaan 1.

Jalankan demo dari root repo setelah bundle dan artefak terlatih tersedia.

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.feedback_demo --output .ai-context/SPRINT_5_FEEDBACK_EVIDENCE.json
rtk proxy ml\.venv\Scripts\python.exe -m pytest ml/tests -q -p no:cacheprovider
```

Demo mencatat neraca stok sintetis dan respons ASGI dari model yang sama pada dua cutoff, termasuk contoh ketika koreksi mencapai batas clipping. Setiap cutoff membandingkan snapshot dengan rekonsiliasi valid dan snapshot pembanding dengan fallback netral. Data fisik dan backend InventoryIoTService belum tersedia di checkout.

## Backend dan SQLite Sprint 6A

Jalankan dari root repo pada PowerShell. Gunakan venv Python 3.13 yang sama dengan Sprint 2–5. Pasang kebutuhan backend dari lockfile lalu pasang paket editable bila belum tersedia.

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m pip install -r ml/requirements-dev.lock
rtk proxy ml\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e ml
New-Item -ItemType Directory -Force ml/runtime
Copy-Item ml/backend.env.example.ps1 ml/runtime/backend.env.ps1
```

Isi `ml/runtime/backend.env.ps1` dengan signing secret acak sedikitnya 32 byte, tiga password berbeda (12–128 karakter), dan dua device key acak berbeda (32–256 karakter ASCII tanpa spasi). Contoh sumber random adalah `secrets.token_urlsafe(32)` dari Python. Pertahankan rahasia lokal di environment atau berkas runtime yang diabaikan Git.

```powershell
. .\ml\runtime\backend.env.ps1
rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage init-db
rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage seed
rtk proxy ml\.venv\Scripts\python.exe -m uvicorn sikembang_backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

Server menyediakan `GET /api/health`, `/docs`, `POST /api/auth/login`, `GET /api/auth/me`, dan router D2 `POST /api/ai/predict`. Login menerima JSON `username` dan `password`, lalu menyediakan `access_token` untuk header Authorization Bearer. MARKETING, PPIC, dan PFA adalah peran dashboard. SYSTEM dipakai untuk pemanggilan internal.

Default seed mengikuti minggu berjalan WIB. Untuk replay yang dibekukan, isi `SIKEMBANG_DEMO_CUTOFF` dengan timestamp WIB yang sesuai, misalnya `2025-03-05T12:00:00+07:00`, dan jalankan `seed --period 2025-W10`. Gunakan path SQLite tersendiri untuk replay bila ingin mempertahankan demo berjalan. Seeder memasukkan baris yang belum ada dan memeriksa konflik kredensial serta kelayakan histori pada seed ulang. Perubahan kredensial yang sudah tersimpan memerlukan alur administrasi terpisah.

Artefak dan bundle Sprint 2–3 dapat dibangkitkan melalui perintah di bagian sebelumnya bila belum tersedia. Beri `SIKEMBANG_ARTIFACT` path direktori artefak untuk mengaktifkan inferensi. Dengan konfigurasi model kosong, health dan login tetap dapat dipakai dan endpoint AI memberi `500 MODEL_UNAVAILABLE`. Konfigurasi path model yang invalid menghentikan startup. Init database adalah langkah eksplisit.

Vite dapat meneruskan `/api` melalui `VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000`. Klien frontend live sudah membaca `sessionStorage.access_token`, sedangkan layar login dan workflow bisnis menyusul pada sprint berikutnya. Uji backend 6A melalui OpenAPI atau HTTP client. Skema dan provenance dirinci di [dokumentasi data backend](../docs/backend-data.md).

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m pytest ml/tests -q -p no:cacheprovider
```

## Order dan inventaris Sprint 6B

Untuk database Sprint 6A yang sudah ada, jalankan kembali `rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage init-db` dengan path database yang sama. Inisialisasi menambahkan kolom provenance revisi dan telemetry serta tabel audit request rusak. Data yang sudah tersimpan tetap ada.

Dengan aplikasi dan database dari langkah 6A, akun Marketing dapat membuat order melalui `POST /api/orders` dan mengirim revisi lengkap melalui `PUT /api/orders/{order_id}` dengan versi yang terakhir dibaca. Akun PPIC dapat membaca order melalui `GET /api/orders?planning_period=2026-W48` dan stok melalui `GET /api/inventory/stock?ingredient_ids=ING-001,ING-012`. Gunakan minggu ISO sesuai tanggal acara.

`POST /api/iot/telemetry` memerlukan `X-Device-Key` dan pasangan sensor–bahan yang terdaftar. Untuk beras, registry demo memakai `SNS-GDG-01` dan `ING-001`. Kirim timestamp berzona yang berusia maksimal 300 detik. Stok tanpa waktu sinkronisasi atau dengan sinkronisasi lebih dari 60 menit berstatus `STALE`. Nilai `null` berarti kuantitas stok belum diketahui.
