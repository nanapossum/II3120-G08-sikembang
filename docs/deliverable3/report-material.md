# Materi laporan Deliverable 3 SiKembang

Masukkan bagian ini ke laporan gabungan D1–D3. Gunakan urutan bab dan nomor tabel atau gambar yang ditetapkan kelompok. Pada bagian awal laporan, cantumkan penugasan tiap anggota. Entri kontribusi yang dicakup naskah ini adalah modul AI prediktif, backend FastAPI dan SQLite, integrasi API frontend, serta integrasi telemetri ESP32. Sumber ketentuan adalah *Tugas Besar II3120*, bagian Deliverable 3 dan Dokumen Laporan. Sumber rancangan adalah laporan kelompok Deliverable 2, bagian BPMN To-Be, desain SoaML, spesifikasi REST API, dan rencana prototipe.

Deliverable 3 mencakup pembangunan prototipe berdasarkan D1 dan D2, peran dua teknologi terpilih pada solusi, pengujian yang mendokumentasikan skenario, langkah atau input, hasil harapan, hasil aktual, status dan bukti, demonstrasi alur utama beserta interaksi API, serta keterbatasan dan rencana pengembangan. Kelompok mengumpulkan satu laporan PDF dan satu dokumen presentasi yang masing-masing memuat D1, D2, dan D3. [Matriks rancangan ke pengujian](traceability.md) · [Skenario dan bukti verifikasi](verification.md)

## Tujuan dan lingkup implementasi

SiKembang merupakan prototipe perencanaan pengadaan bahan baku untuk studi kasus SonoKembang Catering Malang, penyedia layanan antara lain prasmanan pernikahan, acara syukuran, dan nasi kotak. Lingkup diturunkan dari dua titik kegagalan D1. Pada F3, perubahan pesanan melalui pesan terpisah dapat membuat data yang digunakan PPIC berbeda dari data Marketing. Pada F4, pencatatan stok dan taksiran kebutuhan secara manual dapat menimbulkan kekurangan atau kelebihan bahan. [Profil layanan SonoKembang Catering Malang](https://sonokembangmalang.com/) · [Pemetaan F3 dan F4](traceability.md)

Alur yang dibangun dimulai dari pencatatan pesanan terkonfirmasi, pemantauan persediaan, prediksi kebutuhan tambahan, dan perhitungan kebutuhan bersih. Sistem menyimpan hasil kalkulasi sebagai draf yang ditinjau PPIC. PFA menerima daftar yang telah disetujui dan diteruskan PPIC. Modul pesanan terpusat menggantikan integrasi langsung Sunnyday/Ecount dalam prototipe. Pembelian pemasok, pembayaran, pelaksanaan produksi, dan pengiriman berada di luar lingkup tersebut. [Peta alur peran](diagrams/10-user-flow.svg)

## Arsitektur, teknologi, dan backend

React mengirim permintaan REST JSON ke satu aplikasi FastAPI yang menjalankan lima layanan logis SoaML. Pendekatan *modular monolith* memungkinkan pemisahan kontrak tiap layanan, pemanggilan internal melalui objek Python, dan transaksi tunggal untuk prediksi pengadaan dan draf. SQLite menyimpan data operasional, sementara XGBoost membaca artefak terlatih dari sistem berkas. Firmware ESP32 atau simulator mengirim telemetri melalui API yang sama dengan identitas perangkat berbeda. [Arsitektur sistem](diagrams/01-system.svg) · [Komponen backend](diagrams/02-backend.svg) · [Dokumentasi sistem](system.md)

*Gambar — Arsitektur implementasi SiKembang dengan tiga peran pengguna, lima layanan logis, SQLite, model XGBoost, dan sumber telemetri.* [Diagram](diagrams/01-system.svg)

*Tabel — Teknologi utama yang digunakan pada prototipe dan verifikasi.*

| Lapisan | Teknologi dan versi yang diperiksa | Peran |
| --- | --- | --- |
| Backend | Python 3.13.2, FastAPI 0.165.0, Uvicorn 0.54.0, Pydantic 2.14.4, SQLAlchemy 2.0.53, SQLite | API, validasi kontrak, transaksi, penyimpanan |
| Akses | PyJWT 2.15.1, JWT HS256, PBKDF2 dengan salt, `X-Device-Key` | Login dashboard, otorisasi peran, identitas sensor |
| AI | XGBoost 3.1.3, NumPy 2.2.6, scikit-learn 1.6.1, Matplotlib 3.10.3 | Pelatihan, evaluasi, inferensi, visualisasi |
| Frontend | React 19.3.1, TypeScript 6.0.3, Vite 8.3.8, Tailwind CSS 4.3.5, React Router 7.18.6, TanStack React Query 5.108.4, Zod 4.6.7 | Dashboard, routing, penanganan data API dan validasi runtime |
| IoT | ESP32 dan Arduino-ESP32 2.0.17, load cell, HX711 0.7.5, OLED SSD1306 128 × 64, Adafruit SSD1306 2.5.16 dan GFX 1.12.4 | Pencuplikan massa, tampilan lokal, telemetri LAN |
| Uji | Pytest 9.1.1, Vitest 5.1.1, ESLint, MSW, Chrome, Arduino CLI 1.5.1 | Regresi, pengujian browser, mock, kompilasi firmware |

[Lockfile Python](../../ml/requirements-dev.lock) · [Lockfile frontend](../../package-lock.json) · [Firmware](../../firmware/esp32_scale/README.md)

Factory `sikembang_backend.app:create_app` merangkai konfigurasi, sesi database, autentikasi, skema Pydantic, dan router di satu aplikasi. Autentikasi manusia menggunakan Bearer JWT yang diperiksa bersama status pengguna pada database. Kunci perangkat hanya mengotorisasi sensor dan bahan yang terdaftar. Otoritas SYSTEM internal menjalankan penyimpanan draf dari kalkulasi. Akses SYSTEM lewat HTTP dapat diaktifkan dengan kunci terpisah. [Factory aplikasi](../../ml/src/sikembang_backend/app.py) · [Dokumentasi API](api.md)

*Tabel — Implementasi layanan logis pada aplikasi FastAPI.*

| Layanan | Tanggung jawab dan modul |
| --- | --- |
| OrderService | Membuat pesanan terkonfirmasi, menyimpan revisi berversi, menyajikan snapshot mingguan dan menghitung kebutuhan pesanan melalui resep pada versi yang sesuai. [`orders.py`](../../ml/src/sikembang_backend/orders.py) |
| InventoryIoTService | Memvalidasi paket, mengonversi unit, memperbarui stok dan menyimpan jejak penerimaan atau penolakan. [`inventory.py`](../../ml/src/sikembang_backend/inventory.py) |
| AIForecastService | Mengambil snapshot histori, membentuk fitur, memanggil model dan menyimpan hasil serta provenance feedback. [`forecast.py`](../../ml/src/sikembang_backend/forecast.py) · [Adapter API prediksi](../../ml/src/ai_forecast/api.py) |
| ProcurementCalcService | Mengorkestrasi kebutuhan BOM, forecast opsional, stok pengaman, stok yang tersedia dan pembuatan draf. [`procurement.py`](../../ml/src/sikembang_backend/procurement.py) |
| ShoppingListService | Menyimpan draf melalui `DraftService`, memvalidasi keputusan PPIC, meneruskan dan menyajikan proyeksi untuk PFA. [`drafts.py`](../../ml/src/sikembang_backend/drafts.py) · [`shopping_lists.py`](../../ml/src/sikembang_backend/shopping_lists.py) |

## Database dan antarmuka REST

SQLite menghubungkan `orders`, `order_revisions` dan `order_items` dengan katalog `menus`, `ingredients`, dan `bom_recipes`. Revisi menyimpan snapshot sehingga pembacaan histori dapat memakai versi yang sudah tersedia pada cutoff. `iot_telemetry_logs` mencatat pembacaan dan provenance. `weekly_demand` dan `feedback_evidence` mendukung prediksi, `forecast_runs` dan `forecast_run_items` menyimpan hasil prediksi, sementara `shopping_lists` dan `shopping_list_items` menyimpan status dan keputusan akhir. Foreign key diaktifkan per koneksi aplikasi. Periode daftar dibatasi unik dan transaksi mencegah run tersimpan sendiri apabila pembuatan draf gagal. Basis data yang sama mempertahankan order, stok, dan daftar setelah restart. [Model ORM](../../ml/src/sikembang_backend/models.py) · [Kamus data](database.md) · [Bukti integritas dan restart](../testing/sprint7_http_evidence.json)

*Gambar — ERD SQLite untuk katalog, revisi, audit stok, run prediksi, dan siklus daftar belanja.* [ERD](diagrams/09-erd.svg)

*Tabel — Ringkasan sebelas endpoint bisnis dan otorisasi yang diterapkan.*

| Layanan | Metode dan endpoint | Otorisasi | Respons sukses |
| --- | --- | --- | --- |
| Order | `POST /api/orders` | MARKETING | `201` pesanan terkonfirmasi versi pertama |
| Order | `PUT /api/orders/{order_id}` | MARKETING | `200` revisi berversi |
| Order | `GET /api/orders` | PPIC/SYSTEM | `200` snapshot pesanan |
| InventoryIoT | `POST /api/iot/telemetry` | DEVICE | `201` penerimaan telemetri |
| InventoryIoT | `GET /api/inventory/stock` | PPIC/SYSTEM | `200` stok dan freshness |
| AIForecast | `POST /api/ai/predict` | PPIC/SYSTEM | `201` run prediksi |
| ProcurementCalc | `POST /api/procurement/calculate` | PPIC | `201` komponen per bahan dan draf |
| ShoppingList | `POST /api/shopping-lists` | SYSTEM | `201` draf |
| ShoppingList | `PATCH /api/shopping-lists/{list_id}/approve` | PPIC | `200` `VALIDATED_BY_PPIC` |
| ShoppingList | `POST /api/shopping-lists/{list_id}/send` | PPIC | `200` `SENT_TO_PFA` |
| ShoppingList | `GET /api/shopping-lists` | PPIC/PFA | `200` proyeksi sesuai peran |

Galat API disajikan melalui `error.code`, `error.message`, dan `error.details`. Kode HTTP membedakan antara lain kegagalan otorisasi, konflik revisi, dan pelanggaran aturan bisnis. Swagger UI pada `/docs` menyediakan spesifikasi dan formulir pemanggilan API. [Kontrak dan contoh respons](api.md) · [Bukti HTTP](../testing/sprint7_http_evidence.json)

## AI prediktif, dataset, dan fitur

Model regresi memprediksi kebutuhan tambahan per bahan untuk minggu ISO berdasarkan informasi yang tersedia pada waktu prediksi (*cutoff*, zona WIB). Label dibentuk sebagai `max(0, kebutuhan BOM akhir dari pesanan yang terpenuhi − kebutuhan BOM terkonfirmasi yang terlihat saat cutoff)`, untuk bagian periode yang masih relevan saat cutoff. Snapshot pesanan mengikuti waktu ketersediaan versi, dengan pembatalan dan acara yang telah berlalu diperlakukan menurut aturan target. Kalkulasi dapat menjumlahkan kebutuhan terkonfirmasi dan prediksi tambahan tanpa memasukkan rencana terkonfirmasi dua kali. [Definisi target dan unit](ai.md) · [Implementasi snapshot dan target](../../ml/src/ai_forecast/orders.py)

Riwayat sintetis yang dapat diregenerasi dengan seed 3120 memuat 5.155 pesanan, 17.251 versi, 1.325 observasi kebutuhan mingguan, dan 1.325 rekaman feedback. Tanggal acara sumber mencakup 30 November 2020 hingga 4 Januari 2026. Katalog uji berisi lima bahan dengan satuan kg, liter, atau butir, lima menu, dan resep representatif. Sumber publik mendukung konteks kategori layanan. Nilai resep, pesanan, persediaan, dan histori feedback disusun sebagai data sintetis. [Profil layanan publik](https://sonokembangmalang.com/) · [Katalog fixture](../../ml/config/catalog-and-bom-v1.json) · [Audit dataset](../testing/sprint7_ml_evidence.json)

Model memakai 18 fitur. Empat lag kebutuhan berasal dari empat minggu sebelumnya yang sudah tertutup dan tersedia. Fitur lainnya mencakup penanda Ramadan, musim pernikahan, akhir tahun, koreksi galat historis `prev_error_adj`, indikator ketersediaan feedback, BOM terkonfirmasi, tiga fitur jarak waktu atau posisi cutoff, dan lima kolom penanda bahan. Kalender fixture mendefinisikan musim sebelum prediksi. Partisi kronologis membagi 17.920 baris menjadi 10.570 train (2021-W05–2023-W51), 3.570 validation (2024-W01–2024-W51), 3.640 test (2025-W01–2025-W52), dan 140 baris *purge* pada batas partisi. Pemeriksaan ulang 17.920 baris menelusuri kapan lag, versi pesanan, label dan feedback tersedia. [Kamus fitur dan metode split](ai.md) · [Audit kausal](../testing/sprint7_ml_evidence.json)

*Gambar — Pembentukan dataset sintetis, pemisahan kronologis, evaluasi baseline, dan pelatihan model.* [Diagram pipeline pelatihan](diagrams/03-training.svg)

*Gambar — Distribusi target positif dan proporsi target nol per bahan pada partisi train sintetis.* [Distribusi data](evidence/evaluation/07-synthetic-distributions.png)

## Pelatihan dan evaluasi XGBoost

Satu model gabungan (*pooled model*) XGBoost memakai penanda identitas bahan dan skala per baris berdasarkan rerata empat lag dengan batas minimum satu satuan kanonis. Model menggunakan `reg:squarederror`, kedalaman maksimum 2, 100 pohon, dan laju belajar 0,05. Konfigurasi dipilih berdasarkan validation, kemudian dilatih kembali menggunakan gabungan train dan validation sebelum evaluasi test. Model native `xgb-v1-f9a770b940f71fc8` dilengkapi manifest urutan fitur dan metadata. Pemuatan ulang menghasilkan prediksi skala model yang persis sama pada 3.640 baris test. [Bukti pemilihan dan muat ulang model](../testing/sprint7_ml_evidence.json)

MAE ternormalisasi test sebesar 0,073093 untuk XGBoost, 0,074741 untuk median historis, dan 0,145075 untuk baseline nol. Perbaikan relatif terhadap median sebesar 2,20% berlaku untuk fixture sintetis ini. RMSE XGBoost lebih rendah untuk kelima bahan. MAE santan naik dari 1,691 menjadi 1,786 liter. Ablation pada validation menghasilkan 0,080872 dengan fitur feedback dan 0,080740 tanpa `prev_error_adj` serta indikator ketersediaannya, sehingga eksperimen tersebut belum menunjukkan manfaat penambahan fitur. Ringkasan lintas bahan menghitung galat absolut dibagi skala per baris, lalu mengambil rerata dengan bobot setara antar bahan. Galat mentah dilaporkan per satuan. [Bukti evaluasi](../testing/sprint7_ml_evidence.json)

*Tabel — MAE, RMSE, dan bias pada test sintetis untuk tiap bahan. Bias dihitung sebagai prediksi dikurangi aktual.*

| Bahan | Satuan | MAE XGBoost | RMSE XGBoost | MAE median | RMSE median | Bias XGBoost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Beras | kg | 19,803 | 29,199 | 20,322 | 32,289 | +4,987 |
| Ayam | kg | 17,943 | 26,640 | 19,134 | 30,022 | +3,746 |
| Telur | butir | 172,014 | 256,075 | 178,354 | 278,182 | +7,838 |
| Santan | liter | 1,786 | 2,717 | 1,691 | 2,973 | +0,671 |
| Minyak goreng | liter | 1,416 | 2,068 | 1,450 | 2,287 | +0,443 |

*Gambar — MAE baseline dan XGBoost menurut bahan dalam satuan kanonis masing-masing.* [MAE](evidence/evaluation/02-mae.png)

*Gambar — RMSE baseline dan XGBoost menurut bahan pada test sintetis.* [RMSE](evidence/evaluation/03-rmse.png)

*Gambar — Prediksi XGBoost dan nilai aktual pada test sintetis.* [Aktual dan prediksi](evidence/evaluation/01-actual-vs-predicted.png)

*Gambar — Distribusi residual pada test sintetis menurut bahan.* [Residual](evidence/evaluation/04-residuals.png)

*Gambar — Kepentingan fitur berdasarkan gain pada pohon XGBoost.* [Kepentingan fitur](evidence/evaluation/05-feature-importance.png)

*Gambar — Perbandingan MAE ternormalisasi pada validation dengan dan tanpa pasangan fitur feedback.* [Ablation](evidence/evaluation/06-feedback-ablation.png)

## Integrasi AI–IoT dan firmware

Stok terkini dari InventoryIoTService digunakan pada kalkulasi pengadaan. Feedback model mengambil bukti minggu sebelumnya yang sudah tertutup, memverifikasi stok pembuka dan penutup, mutasi seperti penerimaan dan transfer, serta konsumsi untuk produksi yang dapat diatribusikan. Setelah kebutuhan terkonfirmasi dikurangkan dari konsumsi produksi, selisih kebutuhan tambahan teramati dan prediksi referensi menjadi koreksi bertanda. Koreksi dibatasi ±25% dari skala per baris, digunakan satu kali sebagai fitur, dan beralih ke nol dengan status ketersediaan jika bukti belum memenuhi syarat. Pada replay sintetis `ING-001`, kebutuhan tambahan 36,237 kg dan referensi 26,445 kg menghasilkan `prev_error_adj` +9,792 kg. Model menghasilkan 14,638 kg pada contoh tersebut, baik saat koreksi tersedia maupun saat fitur memakai fallback netral. Uji itu membuktikan integrasi fitur dan menunjukkan keluaran dapat tetap sama pada kedua kondisi. [Contoh rekonsiliasi dan provenance](ai.md) · [Alur feedback](diagrams/05-feedback.svg) · [Bukti replay](evidence/evaluation/feedback-replay.json)

Load cell terhubung ke HX711, lalu ESP32 membaca data pada GPIO 32/33 dan menampilkan massa melalui OLED SSD1306 di I²C GPIO 25/26. Tare menggunakan GPIO 27 dan faktor awal kalibrasi perangkat adalah −120,0. Setelah waktu sinkron melalui SNTP, ESP32 mengirim JSON bercap waktu melalui Wi-Fi LAN dengan `X-Device-Key`. Firmware mengirim perubahan stabil minimum 10 g dan heartbeat setelah 60 detik saat stabil. Backend mengubah gram menjadi kg serta menolak telemetri yang terlalu lama, berada di masa depan, di luar urutan, salah dimensi, atau invalid. Stok yang telah diterima dinilai FRESH hingga 60 menit dan STALE setelahnya. [Firmware dan wiring](../../firmware/esp32_scale/README.md) · [Bukti validasi paket](../testing/sprint7_http_evidence.json)

*Gambar — Rangkaian dan komunikasi ESP32, dari pembacaan massa hingga audit telemetri dan pembaruan stok.* [Diagram perangkat](diagrams/08-iot.svg)

Build firmware lulus pada target `esp32:esp32:esp32`. Upload, kalibrasi, pengukuran rujukan, dan pengiriman melalui Wi-Fi dari perangkat fisik berstatus BLOCKED pada audit karena nol port COM terdeteksi. Alur software diverifikasi dengan sumber telemetri `synthetic`. Bukti feedback historis fisik memerlukan ledger produksi dan pembacaan batas minggu. [Verifikasi firmware dan perangkat](verification.md)

## Integrasi frontend dan alur daftar belanja

Marketing memasukkan pesanan terkonfirmasi melalui React. Revisi berversi tersedia dan teruji melalui API. PPIC membaca pesanan dan stok, memicu kalkulasi, lalu meninjau draf, menyunting kuantitas, atau menolak kontribusi AI untuk item tertentu di layar review. Backend menyimpan rekomendasi sistem beserta kuantitas final, catatan, dan waktu persetujuan. Daftar mengikuti urutan `DRAFT → VALIDATED_BY_PPIC → SENT_TO_PFA`. Daftar dengan seluruh kuantitas akhir bernilai nol berhenti setelah validasi. PFA membaca daftar terkirim dan menerima hanya baris dengan kuantitas akhir positif. Mode live memakai FastAPI dan JWT, sementara mode mock memakai MSW. [Arsitektur frontend](../architecture.md) · [Diagram lifecycle](diagrams/07-lifecycle.svg) · [Bukti browser live](../testing/sprint7_browser_evidence.json)

Kebutuhan BOM diperoleh dengan mengalikan jumlah porsi dan kuantitas bahan per porsi, lalu menjumlahkannya per bahan. Rekomendasi dihitung sebagai `max(0, BOM terkonfirmasi + prediksi tambahan + stok pengaman − stok tersedia)` setelah konversi ke satuan kanonis. Stok STALE yang diketahui memunculkan peringatan dan harus disertai catatan sebelum approval. Stok yang belum diketahui menyebabkan kalkulasi gagal. Jika salah satu dari empat lag wajib belum tersedia, jalur forecast mengembalikan galat. PPIC dapat memilih jalur tanpa forecast yang memakai tambahan AI nol dan menyimpan draf tanpa run prediksi. [Aturan dan contoh API](api.md) · [Alur layanan](diagrams/06-sequence.svg)

*Tabel — Contoh penghitungan beras dari fixture D2 dan eksekusi HTTP Sprint 7.*

| Bukti | BOM | Tambahan | Stok pengaman | Stok tersedia | Rekomendasi |
| --- | ---: | ---: | ---: | ---: | ---: |
| Contoh deterministik D2, tambahan merupakan nilai fixture | 45 kg | 8 kg | 5 kg | 20,5 kg | 37,5 kg |
| Uji model aktual, stok STALE | 69 kg | 4,498 kg | 5 kg | 20,5 kg | 57,998 kg |
| Uji model aktual, sesudah telemetri FRESH | 69 kg | 4,498 kg | 5 kg | 17,5 kg | 60,998 kg |
| Uji terpisah mode tanpa AI, pesanan berbeda | 60 kg | 0 kg | 5 kg | 20,5 kg | 44,5 kg |

Perbandingan stok memakai dua database terisolasi dengan pesanan, cutoff, dan model yang sama. Penurunan stok 3 kg meningkatkan rekomendasi 3 kg. Baris tanpa AI berasal dari skenario HTTP terpisah. [Fixture deterministik](../../ml/tests/test_backend_procurement.py) · [Bukti perbandingan stok dan mode kalkulasi](../testing/sprint7_http_evidence.json)

*Gambar — Layar perencanaan PPIC pada mode live dengan stok hasil telemetri simulasi.* [Capture planning](evidence/screenshots/01-ppic-planning.png)

*Gambar — Tinjauan draf PPIC dengan komponen prediksi, perubahan kuantitas, dan catatan stok.* [Capture review](evidence/screenshots/02-ppic-review.png)

*Gambar — Daftar terkirim yang dibaca PFA setelah approval dan pengiriman oleh PPIC.* [Capture handoff](evidence/screenshots/03-pfa-handoff.png)

## Pengujian dan hasil implementasi

Sprint 7 mencatat 405 tes Pytest lulus, 34 tes Vitest lulus, serta lint dan build frontend lulus. Uji integrasi menjalankan ketiga peran melalui Uvicorn dan SQLite dengan artefak XGBoost aktual. Bukti mencakup 38 transaksi HTTP di tiga database terisolasi, kesebelas operasi bisnis, pemeriksaan integritas dan restart. Uji Chrome mode live mencatat 20 respons API dari backend, alur PPIC/PFA, serta nol respons dari service worker pada jalur live. Uji firmware mencakup sembilan kelompok pengujian host C++ dan satu build target yang lulus. [Rincian pengujian dan status](verification.md) · [Log ringkas](../testing/sprint7_test_results.txt)

*Tabel — Contoh pengujian fungsi dan bukti aktual.*

| Skenario | Langkah atau input | Hasil harapan | Hasil aktual | Status dan bukti |
| --- | --- | --- | --- | --- |
| Revisi pesanan | Memperbarui porsi 40 menjadi 60 dengan versi aktif, lalu mengulang versi lama | Versi naik dan permintaan lama ditolak | Versi 2 tersimpan, `409 VERSION_CONFLICT`, dan dua revisi tetap tersedia setelah restart | PASS [HTTP](../testing/sprint7_http_evidence.json) |
| Integrasi stok | Mengirim 17.500 g dari perangkat simulasi | Stok beras 17,5 kg FRESH dan audit tercatat | `201`, nilai dan provenance tersimpan | PASS [HTTP](../testing/sprint7_http_evidence.json) |
| Inferensi dan kalkulasi | Prediksi dan kalkulasi untuk 2026-W48 | Prediksi berunit dipakai untuk membuat draf | Tambahan 4,498 kg beras, rekomendasi 60,998 kg, draf tersimpan | PASS [HTTP](../testing/sprint7_http_evidence.json) |
| Persetujuan dan handoff | PPIC mengirim 42.250 g pada approval, menyetujui, lalu meneruskan | Daftar memuat 42,25 kg dalam satuan kanonis dan terbaca PFA | PFA melihat 42,25 kg, status akhir bertahan setelah restart | PASS [HTTP](../testing/sprint7_http_evidence.json) · [Browser](../testing/sprint7_browser_evidence.json) |
| Timbangan ESP32 fisik | Deteksi port untuk upload dan verifikasi pengukuran | Perangkat dapat diunggah, mengukur dan mengirim pembacaan | Build lulus, nol port COM terdeteksi | BLOCKED untuk upload dan pengukuran [Verifikasi](verification.md) |

Kelompok TC-08 dan TC-09 pada PPT D2 berhubungan dengan prediksi dan kalkulasi. Bukti independen menunjukkan kedua fungsi berjalan, termasuk histori kurang, perubahan stok, serta mode tanpa AI. Definisi individual pada Tabel 11.1 dirujuk oleh PPT namun belum tersedia dalam laporan yang diperiksa. [Matriks keterlacakan](traceability.md)

## Keterbatasan dan pengembangan lanjutan

Hasil evaluasi mengukur perilaku pada data sintetis. Pengembangan lanjutan perlu memvalidasi baseline dan model pada histori transaksi serta konsumsi yang direkonsiliasi dan disetujui mitra. Fixture kalender berakhir pada 2026. Perluasan periode memerlukan pemeriksaan kalender dan histori yang kompatibel. Katalog serta resep terbatas pada sampel. Revisi order di layar Marketing dan peninjauan item audit lengkap pascapengiriman dapat dikembangkan pada frontend. Verifikasi timbangan memerlukan perangkat terhubung, kalibrasi massa referensi, dan pengujian telemetri LAN. Untuk penggunaan produksi, evaluasi beban dan pemulihan, data induk, komunikasi perangkat terenkripsi, dan pengelolaan kredensial perlu ditetapkan. [Status dan batas verifikasi](verification.md) · [Pemeriksaan manual](demo.md)

## Kesimpulan

SiKembang mewujudkan alur perencanaan bahan dari pesanan terkonfirmasi sampai handoff PFA dalam satu aplikasi web. XGBoost memperkirakan kebutuhan tambahan, dan telemetri menyediakan stok untuk kalkulasi bersih. PPIC mempertahankan kewenangan atas kuantitas akhir. Pengujian membuktikan alur perangkat lunak dengan telemetri simulasi berlabel, termasuk penyimpanan revisi, inferensi, persetujuan, dan persistensi setelah restart. Kompilasi firmware terverifikasi. Validasi pengukuran perangkat fisik dan kinerja forecast pada transaksi perusahaan merupakan pekerjaan lanjutan. [Paket bukti](EVIDENCE_INDEX.md)
