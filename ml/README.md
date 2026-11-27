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
