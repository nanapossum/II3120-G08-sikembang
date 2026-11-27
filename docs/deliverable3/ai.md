# Prediksi kebutuhan bahan tambahan

## Persoalan regresi

AIForecastService memperkirakan kebutuhan tambahan setiap bahan untuk sisa minggu ISO berjalan atau untuk sepekan berikutnya. Satu contoh regresi adalah kombinasi bahan `i`, minggu target `w`, dan cutoff `c`. Minggu dimulai Senin pukul 00.00 WIB (`Asia/Jakarta`). Cutoff membekukan informasi yang diketahui ketika forecast dibuat. Untuk minggu berjalan, cakupan dimulai pada tanggal lokal cutoff, termasuk acara hari itu yang belum dilayani. Untuk target minggu depan, cakupan dimulai pada Senin depan. Kedua jendela berakhir sebelum Senin berikutnya. [Rekonstruksi order](../../ml/src/ai_forecast/orders.py), [inferensi](../../ml/src/ai_forecast/predictor.py)

| Komponen | Formulasi per bahan |
|---|---|
| Kebutuhan pesanan terkonfirmasi, `C(i,w,c)` | Jumlah `porsi × kuantitas BOM per porsi` untuk revisi terakhir dari tiap order yang efektif dan tersedia paling lambat pada cutoff, berstatus `CONFIRMED`, dan bertanggal acara dalam cakupan. |
| Kebutuhan terpenuhi, `F(i,w,c)` | Jumlah BOM dari versi final `FULFILLED` dalam cakupan setelah cutoff, termasuk pesanan yang baru dikonfirmasi setelah cutoff. Waktu pemenuhan eksplisit dipakai bila tersedia, dengan waktu ketersediaan rekaman sebagai alternatif untuk acara berbasis tanggal. |
| Target tambahan, `y(i,w,c)` | `max(0, F(i,w,c) − C(i,w,c))`. Selisih dihitung setelah agregasi per bahan sehingga perubahan porsi, pembatalan, dan pesanan masuk ikut memengaruhi hasil netto. |
| Skala per baris, `s` | `max(1, (lag_1_native + lag_2_native + lag_3_native + lag_4_native) / 4)` dalam satuan bahan. Model dilatih pada `y/s`. |
| Prediksi tambahan, `A(i,w,c)` | `max(0, prediksi_model) × s`, dibulatkan half-up ke 0,001 kg/liter atau satu butir. |
| Rekomendasi beli | `max(0, C + A + safety_stock − usable_IoT_stock)`. Pengadaan memakai stok kini dan stok pengaman dalam satuan yang sama dengan BOM. Mode tanpa AI menetapkan `A = 0`. |

Versi baru mengganti versi yang lebih lama pada snapshot sejak versi itu efektif dan tersedia. Perpindahan tanggal mengeluarkan pesanan dari periode asal setelah perubahan diketahui. `DRAFT`, `CANCELLED` dan `FULFILLED` tidak masuk BOM terkonfirmasi. Pembatalan setelah cutoff tetap membiarkan BOM lama terlihat pada snapshot dan mengurangi kebutuhan akhir. Pengurangan BOM cutoff pada label membuat pesanan yang sudah diketahui dihitung sekali saat pengadaan menambahkan `C` ke keluaran model `A`. Pembatalan dan pemenuhan final muncul di histori sintetis, sedangkan endpoint order demo melayani pembuatan dan revisi pesanan terkonfirmasi. [Indeks order](../../ml/src/ai_forecast/orders.py), [order backend](../../ml/src/sikembang_backend/orders.py), [kalkulasi pengadaan](../../ml/src/sikembang_backend/procurement.py)

## Data, asumsi, dan skema

Dataset `synthetic-weekly-v1` dibangkitkan dengan NumPy PCG64 dan seed 3120. Stream order, revisi, dan inventaris terpisah. Jumlah order harian mengikuti Poisson dengan intensitas dasar 0,3 untuk prasmanan pernikahan, 0,8 untuk prasmanan nonpernikahan, dan 1,5 untuk nasi kotak. Generator menyesuaikan intensitas dengan hari kerja atau akhir pekan, flag kalender, dan noise harian. Rentang porsi masing-masing 120–600, 45–260, dan 15–160. Probabilitas simulasi pembatalan, pindah hari, dan perubahan porsi masing-masing 5,5%, 8,5%, dan 28%. Rentang dan probabilitas ini adalah asumsi generator. [Konfigurasi](../../ml/config/synthetic-v1.json), [generator order](../../ml/src/ai_forecast/orders.py)

Situs SonoKembang Malang mendukung konteks layanan pernikahan, syukuran, dan nasi kotak. Situs menyebut minimum publik 20 pax untuk nasi kotak dan 50 pax untuk prasmanan. Katalog penjual memberi contoh kategori produk. Angka fixture di atas mengikuti konfigurasi eksperimen. [Situs SonoKembang Malang](https://sonokembangmalang.com/), [katalog penjual SonoKembang](https://www.mbizmarket.co.id/p/sonokembang-catering-malang-p6eN/catalog)

Rujukan institusional mendukung cara mendokumentasikan porsi dan resep baku. Kuantitas pada BOM, frekuensi pesanan, stok, stok pengaman, dan rekonsiliasi historis prototipe berasal dari fixture sintetis. Rekaman telemetri saat demo mempunyai provenance simulasi atau fisik sesuai perangkat terdaftar. Pesanan dan keputusan pengguna ketika demo dicatat terpisah dari data pembangkitan. [Lampiran penilaian porsi Poltekkes Kemenkes Malang](https://perpus-utama.poltekkes-malang.ac.id/assets/file/kti/P17110214127/17._LAMPIRAN_.pdf), [Bakhri, Intiyati, dan Widartika, *Sistem Penyelenggaraan Makanan Institusi*](https://repo.upertis.ac.id/1113/), [fixture katalog](../../ml/config/catalog-and-bom-v1.json)

**Tabel 1. Katalog dan BOM kuantitas per porsi** (`synthetic-bom-v1`, berlaku mulai 1 Januari 2020). Tanda — berarti bahan absen pada resep.

| Menu | `ING-001` Beras (kg) | `ING-003` Ayam (kg) | `ING-007` Telur (butir) | `ING-009` Santan (liter) | `ING-012` Minyak goreng (liter) |
|---|---:|---:|---:|---:|---:|
| `MNU-N01` Nasi putih | 0,075 | — | — | — | — |
| `MNU-A01` Ayam bakar | — | 0,12 | — | 0,01 | 0,005 |
| `MNU-S01` Sayur asem | — | — | — | — | 0,002 |
| `MNU-W01` Paket prasmanan | 0,15 | 0,10 | 1 | 0,02 | 0,01 |
| `MNU-K02` Nasi kotak ayam | 0,09 | 0,08 | 1 | — | 0,006 |

Satu order memakai baris paket atau komponen tanpa mencampur keduanya. Satuan kanonis bahan adalah kg, liter, atau butir. Katalog, resep, dan satuan yang dimuat backend harus sesuai dengan kontrak artefak.

| Berkas bundle di `ml/generated/synthetic-v1/` | Skema dan kegunaan |
|---|---|
| `order_versions.jsonl` | Satu objek per revisi. `source`, `order_id`, `category`, `status` berupa string. `version` integer positif. `event_date` tanggal lokal ISO. `created_at`, `effective_at`, `available_at` timestamp berzona. `confirmed_at` dan `fulfilled_at` timestamp berzona atau null. `items[]` berisi `menu_id` dan `bom_version` string serta `portions` integer positif. |
| `weekly_demand.jsonl` | `source` dan `ingredient_id` string, `monday` tanggal Senin, `quantity` numerik dalam satuan bahan, `complete` boolean, `available_at` timestamp berzona. Kuantitas adalah BOM terpenuhi final satu bahan satu minggu. |
| `weekly_feedback.jsonl` | Bukti per bahan-minggu. Objek `sources` menyimpan identitas minggu/bahan/lokasi/satuan, run referensi, pembacaan awal-akhir, mutasi bertimestamp, approval, dan provenance. Rekonsiliasi menyimpan saldo batas, pemakaian teratribusi, tambahan, residual, `reason`, dan `available_at`. Angka pemakaian dan saldo menggunakan satuan bahan. |
| `train.csv`, `validation.csv`, `test.csv`, `purged.csv` | Identitas split, bahan, satuan, periode dan cutoff. Kolom audit mencakup `order_snapshot_id`, `bom_version`, `label_available_at`, `feedback_week`, `feedback_reason`, `scale`, BOM cutoff, pemenuhan sisa, lag dan koreksi native. Label `target_native` dan `target_scaled` terpisah dari 18 input model. |
| `metadata.json`, `summary.md`, `insufficient_history.json` | Metadata dan checksum, ringkasan distribusi train, serta daftar contoh yang tidak memenuhi empat lag. |

Rentang tanggal acara pada sumber 30 November 2020 hingga 4 Januari 2026. Draft paling awal tercatat 16 Oktober 2020. Cakupan utama generator 4 Januari 2021 hingga 28 Desember 2025, dengan minggu tambahan untuk kebutuhan histori dan batas simulasi. Bundle berisi **5.155** ID order, **17.251** versi (5.155 draft, 6.941 konfirmasi/revisi, 4.852 pemenuhan, 303 pembatalan), **1.325** catatan kebutuhan mingguan dan **1.325** bukti feedback. Evaluasi membentuk **17.920** baris eligible dari 256 minggu target, 14 cutoff harian per target dan lima bahan. Sebanyak 5.320 label bernilai nol, termasuk baris purge. [Pembentuk dataset](../../ml/src/ai_forecast/dataset.py), [bukti Sprint 7](../testing/sprint7_ml_evidence.json)

**Tabel 2. Split kronologis, dikelompokkan berdasarkan minggu target.** Tanggal pada kolom cutoff paling awal memakai WIB.

| Split | Minggu target | Minggu | Baris | Cutoff paling awal | Label terakhir tersedia |
|---|---|---:|---:|---|---|
| Train | 2021-W05–2023-W51 | 151 | 10.570 | 25 Jan 2021 00.00 | 25 Des 2023 00.00 |
| Validation | 2024-W01–2024-W51 | 51 | 3.570 | 25 Des 2023 00.00 | 23 Des 2024 00.00 |
| Test | 2025-W01–2025-W52 | 52 | 3.640 | 23 Des 2024 00.00 | 29 Des 2025 00.00 |
| Purge | 2023-W52 dan 2024-W52 | 2 | 140 | 18 Des 2023 00.00 | 30 Des 2024 00.00 |

Dua minggu batas dikeluarkan dari fit dan penilaian split agar origin target berikutnya tidak bertumpang tindih dengan minggu target sebelumnya. Baseline rolling boleh mengambil label historis yang sudah tersedia pada cutoff, termasuk saat test berjalan. Fitur tersedia as-of cutoff, versi order masa depan diabaikan, dan `fulfilled_remaining` hanya dipakai membangun label. Audit memeriksa ulang 17.920 baris dan menghasilkan 10 berkas bundle identik byte demi byte. [Split](../../ml/src/ai_forecast/splits.py), [audit Sprint 7](../testing/sprint7_verify_ml.py)

## Kamus fitur dan inferensi

**Tabel 3. Urutan 18 kolom model sesuai manifest.** Kuantitas lag, koreksi, dan BOM disimpan juga dalam satuan bahan di kolom audit. Fitur kuantitas yang masuk model dibagi `s`. Matriks masukan XGBoost dikonversi ke NumPy `float32`.

| Fitur | Definisi dan tipe | Satuan model | Sumber dan ketersediaan pada cutoff |
|---|---|---|---|
| `lag_1` | Float, total BOM terpenuhi satu minggu sebelum minggu cutoff, dibagi `s` | Rasio | Histori mingguan, lengkap dan `available_at ≤ cutoff` |
| `lag_2` | Float, total BOM terpenuhi dua minggu sebelum minggu cutoff, dibagi `s` | Rasio | Histori mingguan, lengkap dan `available_at ≤ cutoff` |
| `lag_3` | Float, total BOM terpenuhi tiga minggu sebelum minggu cutoff, dibagi `s` | Rasio | Histori mingguan, lengkap dan `available_at ≤ cutoff` |
| `lag_4` | Float, total BOM terpenuhi empat minggu sebelum minggu cutoff, dibagi `s` | Rasio | Histori mingguan, lengkap dan `available_at ≤ cutoff` |
| `is_ramadan_season` | Boolean, ≥4 dari 7 tanggal target berada dalam interval Ramadan tabular | 0/1 | Kalender fixture berversi tersedia sebelum inferensi |
| `is_wedding_season` | Boolean, ≥4 tanggal target berada pada Juni, Juli, atau November | 0/1 | Asumsi kalender fixture tersedia sebelum inferensi |
| `is_year_end` | Boolean, ≥4 tanggal target berada pada 15–31 Desember | 0/1 | Asumsi kalender fixture tersedia sebelum inferensi |
| `prev_error_adj` | Float, residual historis yang dibatasi lalu dibagi `s` | Rasio | Rekonsiliasi minggu sebelum minggu cutoff yang lolos dan disahkan ketat sebelum cutoff, atau 0 |
| `feedback_available` | Integer, 1 bila rekonsiliasi eligible, termasuk residual valid nol | 0/1 | Pemeriksaan feedback pada cutoff, 0 bila fallback |
| `confirmed_bom` | Float, `C(i,w,c)/s` | Rasio | Pesanan terkonfirmasi terakhir yang efektif dan tersedia pada cutoff dan BOM berversi |
| `days_remaining` | Integer, dari awal jendela sampai batas akhir target, 7 untuk target berikutnya | Hari | Tanggal lokal cutoff dan Senin target |
| `days_to_start` | Integer, jarak tanggal cutoff ke Senin target, minimal 0 | Hari | Tanggal lokal cutoff dan Senin target |
| `cutoff_day_fraction` | Float, detik terlewati sejak tengah malam WIB dibagi 86.400 | Fraksi hari | Timestamp cutoff |
| `ingredient_ING-001` | Integer one-hot Beras | 0/1 | ID bahan pada permintaan, divalidasi terhadap katalog |
| `ingredient_ING-003` | Integer one-hot Ayam | 0/1 | ID bahan pada permintaan, divalidasi terhadap katalog |
| `ingredient_ING-007` | Integer one-hot Telur | 0/1 | ID bahan pada permintaan, divalidasi terhadap katalog |
| `ingredient_ING-009` | Integer one-hot Santan | 0/1 | ID bahan pada permintaan, divalidasi terhadap katalog |
| `ingredient_ING-012` | Integer one-hot Minyak goreng | 0/1 | ID bahan pada permintaan, divalidasi terhadap katalog |

Empat lag selalu relatif terhadap awal minggu cutoff, termasuk untuk target minggu berikutnya. Lag yang hilang, belum lengkap, atau terlambat menghasilkan HTTP 422 `INSUFFICIENT_HISTORY`. Bahan di luar katalog menghasilkan 422 `UNKNOWN_INGREDIENT`. Periode di luar horizon menghasilkan 422 `UNSUPPORTED_FORECAST_HORIZON`. Artefak yang hilang atau inkompatibel membuat prediksi mengembalikan 500 `MODEL_UNAVAILABLE`. Nilai atau satuan stok kini masuk ke kalkulasi pengadaan. [Fitur](../../ml/src/ai_forecast/features.py), [snapshot backend](../../ml/src/sikembang_backend/forecast.py), [diagram inferensi](diagrams/04-inference.mmd)

Kalender fixture mencakup 2020–2026 dan harus mencakup ketujuh hari pada minggu target. Target `2026-W53` sudah melintasi 1 Januari 2027 dan menghasilkan 500 `INTERNAL_ERROR` karena kalender tidak tersedia. Penggunaan setelah cakupan itu memerlukan bundle kalender dan artefak yang kompatibel dengan pemeriksaan checksum kalender. [Kalender](../../ml/config/calendar-id-synth-v1.json), [validasi kalender](../../ml/src/ai_forecast/fixtures.py), [validasi artefak](../../ml/src/ai_forecast/predictor.py)

## Pelatihan dan hasil evaluasi

Model memakai satu `XGBRegressor` untuk lima bahan. Skala per baris menyetarakan besaran target dan pengkodean one-hot memberi identitas bahan pada model. Pohon boosting sesuai untuk interaksi kalender, horizon, dan kebutuhan historis pada tabel fitur kecil. Objective `reg:squarederror` meminimalkan galat kuadrat pada target berskala. Pelatihan memakai `tree_method=hist`, CPU, satu thread, seed 3120. [Kode pelatihan](../../ml/src/ai_forecast/train.py), [parameter XGBoost 3.1](https://xgboost.readthedocs.io/en/release_3.1.0/parameter.html), [diagram pelatihan](diagrams/03-training.mmd)

Grid melatih empat kombinasi `max_depth ∈ {2,4}` dan `n_estimators ∈ {100,250}` pada train. Seleksi memakai MAE ternormalisasi validation keseluruhan, dengan rincian blok 13 minggu. Skor konfigurasi `(depth, trees)` adalah `(2,100)` 0,080872, `(2,250)` 0,082564, `(4,100)` 0,082517, dan `(4,250)` 0,085012. Parameter lain tetap `learning_rate=0.05`, `subsample=1.0`, `colsample_bytree=1.0`, `min_child_weight=1`, `reg_alpha=0.0`, `reg_lambda=1.0`. Model terpilih di-fit ulang pada 14.140 baris train + validation yang labelnya tersedia saat cutoff test pertama. Parameter dibekukan sebelum test. [Bukti evaluasi](../testing/sprint7_ml_evidence.json)

Baseline nol selalu memprediksi 0. Baseline median mengambil hingga empat target mingguan lampau pada bahan dan offset cutoff yang sama, dengan `label_available_at ≤ cutoff`. Jika tidak ada label eligible, median memakai 0. Fallback ini terjadi nol kali pada validation dan test. Audit menemukan empat median test berbeda dari median desimal eksak hingga 0,001 satuan dasar dan delapan perbedaan pembulatan referensi feedback. Tabel dan grafik memakai protokol evaluasi yang dipublikasikan. [Evaluator](../../ml/src/ai_forecast/evaluate.py), [audit numerik](../testing/sprint7_ml_evidence.json)

Residual evaluasi `e = prediksi − aktual`. MAE adalah rerata `|e|`, RMSE adalah akar rerata `e²`, dan bias adalah rerata `e`. Ketiganya disajikan dalam satuan masing-masing bahan. MAE ternormalisasi menghitung `|e|/s` pada tiap baris, merata-ratakannya per bahan, lalu merata-ratakan lima skor dengan bobot sama. Metrik tersebut tanpa satuan.

**Tabel 4. Hasil test sintetis per bahan**, 728 baris per bahan. Tiap sel berisi MAE / RMSE / bias dalam satuan pada baris.

| Bahan (satuan) | XGBoost | Median historis | Nol |
|---|---:|---:|---:|
| Beras (kg) | 19,803 / 29,199 / +4,987 | 20,322 / 32,289 / −2,589 | 42,907 / 63,985 / −42,907 |
| Ayam (kg) | 17,943 / 26,640 / +3,746 | 19,134 / 30,022 / −2,400 | 40,742 / 60,653 / −40,742 |
| Telur (butir) | 172,014 / 256,075 / +7,838 | 178,354 / 278,182 / −22,231 | 378,374 / 550,936 / −378,374 |
| Santan (liter) | 1,786 / 2,717 / +0,671 | 1,691 / 2,973 / −0,351 | 1,931 / 3,790 / −1,931 |
| Minyak goreng (liter) | 1,416 / 2,068 / +0,443 | 1,450 / 2,287 / −0,175 | 3,019 / 4,519 / −3,019 |

MAE ternormalisasi test XGBoost **0,073093**, median historis **0,074741**, dan nol **0,145075**. Keunggulan relatif terhadap median sebesar **2,20%**. XGBoost memperbaiki RMSE untuk lima bahan dan MAE untuk empat bahan. Median mempunyai MAE santan lebih rendah. Bias model positif pada kelima bahan. Replay test dengan prediksi model sebagai referensi feedback menghasilkan 0,073097 pada 3.640 baris, dengan 2.500 baris memakai referensi model dan 265 referensi yang diterbitkan lewat simulasi. Referensi memakai model beku setelah label fit tersedia. [Bukti evaluasi lengkap](../testing/sprint7_ml_evidence.json)

Ablation validation menghapus `prev_error_adj` dan `feedback_available` bersama-sama dan melatih ulang konfigurasi terpilih. MAE ternormalisasi adalah 0,080872 dengan fitur feedback dan 0,080740 tanpa pasangan fitur. Hasil ini belum menunjukkan manfaat akurasi dari feedback. Fitur dipertahankan untuk kontrak integrasi D2. Gain tertinggi pada pohon ada pada `days_to_start`, diikuti indikator santan dan `days_remaining`. Gain adalah statistik split model, sehingga nilainya tidak mengukur pengaruh sebab-akibat. [Ablation](evidence/evaluation/06-feedback-ablation.png), [feature importance](evidence/evaluation/05-feature-importance.png)

### Grafik yang siap dipakai

| Gambar | Keterangan |
|---|---|
| [1. Aktual dan prediksi](evidence/evaluation/01-actual-vs-predicted.png) | Seri test per bahan, satu cutoff Senin 00.00 WIB per minggu target berjalan, dengan aktual sintetis, XGBoost, dan median. |
| [2. Perbandingan MAE](evidence/evaluation/02-mae.png) | Tiga metode pada seluruh cutoff test, panel per bahan dalam satuan dasar. |
| [3. Perbandingan RMSE](evidence/evaluation/03-rmse.png) | Tiga metode pada seluruh cutoff test, panel per bahan dalam satuan dasar. |
| [4. Distribusi residual](evidence/evaluation/04-residuals.png) | Prediksi XGBoost dikurangi aktual pada test. Massa di kanan nol berarti prediksi lebih besar dari aktual. |
| [5. Feature importance](evidence/evaluation/05-feature-importance.png) | Gain rata-rata dari split pohon model terlatih. |
| [6. Ablation feedback](evidence/evaluation/06-feedback-ablation.png) | MAE ternormalisasi pada validation secara keseluruhan dan per blok kronologis. |
| [7. Distribusi target sintetis](evidence/evaluation/07-synthetic-distributions.png) | Lima histogram target positif dalam satuan dasar dan proporsi label nol dari 2.114 baris train per bahan. Label nol mencapai 53,8% pada santan dan 23,7–25,4% pada bahan lain. |

Gambar 1–6 adalah salinan PNG identik dari grafik Sprint 7. Gambar 7 membaca `target_native` dari `train.csv` dengan verifikasi checksum dataset dan katalog. Semua hasil mengukur kecocokan model terhadap pola generator sintetis. Evaluasi operasional memerlukan histori SonoKembang yang telah diverifikasi, termasuk versi order, pemenuhan, serta bukti persediaan dan produksi. [Kode grafik eksperimen](../../ml/src/ai_forecast/plots.py), [kode grafik distribusi](evidence/evaluation/plot_synthetic_distributions.py)

### Artefak dan reproduksi

Run **`xgb-v1-f9a770b940f71fc8`** disimpan di `ml/artifacts/xgb-v1-f9a770b940f71fc8/`. `model.ubj` berukuran 90.820 byte dengan SHA-256 `f9a770b940f71fc80329298ee3aec21cb692b48c0b1e5fa35891fe950b06c11e`. Format UBJSON menyimpan model XGBoost, sementara `manifest.json` menyimpan versi, checksum, urutan fitur, kategori dan satuan bahan, kontrak target/cutoff dan pembulatan, fingerprint fixture, cakupan fit, parameter, kebijakan feedback, dan metrik. `evaluation.json` menyimpan rincian seleksi dan skor subkelompok. `predictions.csv` menyimpan prediksi dan target test per baris. Versi asli Python 3.13.2, XGBoost 3.1.3, NumPy 2.2.6, scikit-learn 1.6.1, SciPy 1.15.3, tzdata 2025.2, dan Matplotlib 3.10.3. [Bukti model](../testing/sprint7_ml_evidence.json), [I/O model XGBoost](https://xgboost.readthedocs.io/en/release_3.1.0/tutorials/saving_model.html)

Reload pada proses baru memverifikasi fingerprint dataset dan kunci baris test. Seluruh 3.640 prediksi berskala cocok dengan delta maksimum 0,0. Semua prediksi dalam satuan dasar cocok persis, bernilai hingga dan nonnegatif. Runtime memeriksa kompatibilitas checksum, urutan fitur, katalog, kalender, dan kontrak sebelum melayani inferensi. Bobot model tetap saat request. [Pemuatan model](../../ml/src/ai_forecast/model.py), [evaluator](../../ml/src/ai_forecast/evaluate.py), [bukti reload](../testing/sprint7_ml_evidence.json)

Gunakan [panduan ML](../../ml/README.md#reproduksi-dari-root-repo) untuk menyiapkan venv dan memasang paket. Dari root repo PowerShell, jalankan pemeriksaan berikut bila bundle dan model tersedia. Salinan bundle dan artefak asli diabaikan Git. Gunakan versi yang sudah disediakan untuk demo, atau bangkitkan sekali pada checkout yang belum memilikinya. Perintah pelatihan opsional dan evaluasi ulang dijelaskan pada [panduan training](../../ml/README.md#training-dan-evaluasi-sprint-3).

```powershell
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.evaluate --dataset ml/generated/synthetic-v1 --artifact ml/artifacts/xgb-v1-f9a770b940f71fc8
rtk proxy ml\.venv\Scripts\python.exe docs/deliverable3/evidence/evaluation/plot_synthetic_distributions.py
rtk proxy ml\.venv\Scripts\python.exe -m ai_forecast.feedback_demo
```

Inferensi standalone tersedia melalui [harness replay](../../ml/README.md#inferensi-sprint-4). API live memakai repository SQLite untuk menyimpan run dan audit feedback. Panggilan dari ProcurementCalcService menempatkan penyimpanan run serta draf dalam transaksi kalkulasi yang sama. [Repository run](../../ml/src/sikembang_backend/forecast.py), [kode pengadaan](../../ml/src/sikembang_backend/procurement.py)

## Feedback historis AI–IoT

Stok IoT kini diambil dari persediaan saat kalkulasi pengadaan. Riwayat feedback memakai persediaan minggu ISO tertutup sebelum minggu cutoff, dengan pembacaan awal-akhir, saldo dipulihkan pada batas minggu, buku mutasi lengkap, atribut batch produksi, dan forecast pembanding. Pembacaan harus cocok dengan bahan, lokasi, satuan, dan sisi ledger dalam jendela 60 menit dari batas minggu. Jeda ukur–terima dibatasi 0–5 menit. Neraca pemakaian harus cocok dengan pemakaian yang dapat diatribusikan pada produksi. [Diagram feedback](diagrams/05-feedback.mmd), [rekonsiliasi](../../ml/src/ai_forecast/feedback.py)

Provider mengambil approval terbaru yang tersedia ketat sebelum cutoff dan setelah atau tepat saat minggu sumber ditutup. Forecast pembanding harus memiliki cutoff Senin pukul 00.00 WIB dan telah terbit dalam minggu sumber paling lambat pada approval serta sebelum pemenuhan pertama bila tercatat. Untuk replay sintetis dengan produksi tanpa waktu pemenuhan pertama, publikasi harus tepat pada origin Senin. Kandidat eligible dipilih berdasarkan waktu publikasi paling awal, lalu ID. Referensi model replay juga memerlukan bukti ketersediaan label fit saat origin referensi. [Pemilihan bukti dan referensi](../../ml/src/ai_forecast/feedback_provider.py)

```text
pemakaian_ledger = stok_awal + restock + transfer_masuk − transfer_keluar
                   − retur_keluar − waste + koreksi_bertanda − stok_akhir
tambahan_terekonsiliasi = max(0, pemakaian_teratribusi − BOM_run_referensi)
residual_feedback = tambahan_terekonsiliasi − prediksi_tambahan_run_referensi
prev_error_adj_native = clip(residual_feedback, −0,25 × s, +0,25 × s)
fitur_prev_error_adj = prev_error_adj_native / s
```

Residual feedback positif berarti permintaan tambahan terobservasi melampaui prediksi referensi, konvensi yang berlawanan dengan residual evaluasi pada Tabel 4. Nilai koreksi masuk ke model satu kali sebagai fitur. Rumus pengadaan mengambil `predicted_demand` dari model. Jika bukti gagal, sistem memakai koreksi 0 dan `feedback_available=0` serta menyimpan alasan audit. Residual valid nol tetap berflag 1. Audit bundle menemukan 12.432 baris dengan feedback valid, termasuk 300 residual nol, dan 5.488 baris netral. [Audit dataset](../testing/sprint7_ml_evidence.json)

Generator sintetis membentuk stok awal 100 satuan bahan, pemakaian produksi dari BOM mingguan dikali faktor acak 0,95–1,05, serta target stok akhir 20–60 satuan. Mutasi transfer, retur, dan waste 0–4 satuan serta koreksi bertanda −2 hingga +2 satuan disimulasikan terpisah. Restock menyeimbangkan saldo dan diselesaikan bersama pemakaian produksi saat laporan pemenuhan mingguan lengkap. Peluang pembacaan hilang dan ditolak masing-masing 5% per pembacaan, dengan lag approval simulasi 2–30 jam setelah penutupan. Run referensi utama memakai median historis yang kausal. [Generator feedback](../../ml/src/ai_forecast/feedback.py)

Snapshot seluruhnya sintetis memakai bukti simulasi yang disegel. Snapshot live memerlukan pembacaan batas minggu yang cocok dengan log `ACCEPTED` perangkat fisik, binding lokasi, ledger/produksi yang lengkap, serta run `live` di basis data. Snapshot campuran pesanan demo dan lag sintetis memakai feedback netral. Log telemetri ESP32 tunggal dapat memperbarui stok kini. Bukti feedback fisik mencakup prasyarat tambahan di atas, dan jalur lengkapnya diuji dengan fixture terkontrol. Histori rekonsiliasi fisik operasional masih perlu dikumpulkan. [Adapter backend](../../ml/src/sikembang_backend/forecast_feedback.py), [tes feedback](../../ml/tests/test_backend_forecast_feedback.py)

### Contoh rekonsiliasi terverifikasi

Replay beras `ING-001` pada cutoff 5 Maret 2025 pukul 12.00 WIB dengan target `2025-W10` memilih bukti `2025-W09`. Run median sintetis terbit Senin 24 Februari 2025 pukul 00.00 WIB. Approval tercatat 3 Maret 2025 pukul 06.00 WIB, dan permintaan tepat pada waktu approval masih menerima fallback.

| Tahap | Nilai dari replay |
|---|---:|
| Pemakaian teratribusi dari ledger | `27 + 278,877 + 3 − 0 − 0 − 1 − 1 − 49 = 257,877 kg` |
| Tambahan terekonsiliasi | `257,877 − 221,640 = 36,237 kg` |
| Residual feedback | `36,237 − 26,445 = +9,792 kg` |
| Skala dan clipping | `s = 250,85625 kg`, batas `±62,7140625 kg` |
| Koreksi yang masuk model | `+9,792 kg / 250,85625 kg ≈ 0,0390343` |
| Respons ASGI dengan feedback | HTTP 201, `prev_error_adj = +9,792 kg`, kebutuhan tambahan **14,638 kg** |
| Respons ASGI dengan fallback | HTTP 201, `prev_error_adj = 0 kg`, kebutuhan tambahan **14,638 kg** |

Replay kedua pada 18 Maret 2025 pukul 12.00 WIB (`2025-W12`) membatasi residual +88,813 kg menjadi +87,564375 kg. Prediksi tambahan adalah 22,923 kg dengan fitur valid dan 23,043 kg dengan fallback. Keluaran kedua replay berasal dari model tersimpan dan bukti sintetis. ID run respons berubah pada setiap eksekusi. [Bukti replay yang dijalankan ulang](evidence/evaluation/feedback-replay.json), [kode demo](../../ml/src/ai_forecast/feedback_demo.py)
