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
