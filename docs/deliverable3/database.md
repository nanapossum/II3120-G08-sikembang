# Basis data dan kamus data

SiKembang menyimpan 16 tabel SQLite melalui SQLAlchemy. Diagram menampilkan kunci dan kardinalitas FK yang tersedia. Relasi dari `orders` ke minimal satu revisi adalah perilaku layanan ketika membuat pesanan. Demikian pula layanan mensyaratkan setidaknya satu item pada draf. SQLite menyimpan status pengadaan di `shopping_lists` dan rincian keputusan per bahan di `shopping_list_items`.

- [ERD SVG](diagrams/09-erd.svg) dan [sumber Mermaid](diagrams/09-erd.mmd)
- [Sumber ORM](../../ml/src/sikembang_backend/models.py) dan [catatan kompatibilitas skema](../backend-data.md)
- [Respons API, tes restart dan pemeriksaan integritas](../testing/sprint7_http_evidence.json)

Kamus berikut menggunakan tipe deklarasi dari SQLite dan nullability skema. PK dan FK dapat menjadi bagian dari kunci komposit. FK yang berpasangan mengacu pada satu baris target yang sama. `DATETIME` disimpan sebagai UTC oleh tipe ORM `UtcTimestamp`, dibaca kembali sebagai instant berzona UTC, dan umumnya ditampilkan oleh API dalam WIB. Bawaan ORM berlaku saat penulisan lewat SQLAlchemy.

## `ingredients`

Master bahan, inventori saat ini, dan buffer PPIC.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `ingredient_id` | `VARCHAR` | PK | Tidak | Kode stabil, misalnya `ING-001` untuk Beras |
| `name` | `VARCHAR` | — | Tidak | Nama tampil |
| `base_unit` | `VARCHAR` | — | Tidak | `kg`, `liter`, atau `butir` |
| `current_stock` | `FLOAT` | — | Ya | Stok terakhir dalam satuan dasar. `NULL` berarti stok belum diketahui |
| `safety_stock` | `FLOAT` | — | Tidak | Buffer dalam satuan dasar. Bawaan ORM `0.0` |
| `last_iot_sync` | `DATETIME` | — | Ya | `recorded_at` pengukuran terakhir yang diterima |
| `source` | `VARCHAR` | — | Tidak | Provenance master. Bawaan ORM `operational` |

Unik `(ingredient_id, base_unit)` sebagai target FK komposit. `current_stock` dan `safety_stock` nonnegatif bila berisi nilai.

## `menus`

Katalog menu pesanan.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `menu_id` | `VARCHAR` | PK | Tidak | Kode stabil, misalnya `MNU-W01` |
| `name` | `VARCHAR` | — | Tidak | Nama tampil |
| `source` | `VARCHAR` | — | Tidak | Provenance katalog. Bawaan ORM `operational` |

## `bom_recipes`

Kuantitas bahan untuk setiap porsi menu pada satu versi resep.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `menu_id` | `VARCHAR` | PK, FK → `menus.menu_id` | Tidak | Menu yang membutuhkan bahan |
| `ingredient_id` | `VARCHAR` | PK, FK → `ingredients.ingredient_id` | Tidak | Bahan menurut satuan dasar |
| `bom_version` | `VARCHAR` | PK | Tidak | Identitas katalog resep |
| `quantity_per_portion` | `FLOAT` | — | Tidak | Kuantitas per porsi dalam satuan dasar. Harus positif |

Indeks `(bom_version, menu_id)` untuk pemilihan resep.

## `orders`

Identitas pesanan yang tetap ketika acara atau porsi direvisi.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `order_id` | `VARCHAR` | PK | Tidak | ID pesanan, misalnya `DEMO-2026-W48-01` |
| `customer_name` | `VARCHAR` | — | Tidak | Nama pelanggan yang diterima dari input atau fixture |
| `category` | `VARCHAR` | — | Tidak | `PRASMANAN_WEDDING`, `PRASMANAN_NON_WEDDING`, atau `NASI_KOTAK` |
| `created_at` | `DATETIME` | — | Tidak | Waktu pencatatan/identitas |
| `source` | `VARCHAR` | — | Tidak | Provenance pesanan. Bawaan ORM `operational` |

## `order_revisions`

Status dan detail acara dari setiap versi pesanan.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `order_id` | `VARCHAR` | PK, FK → `orders.order_id` | Tidak | Identitas pesanan |
| `version` | `INTEGER` | PK | Tidak | Nomor versi ≥ 1 |
| `event_date` | `DATE` | — | Tidak | Tanggal acara dalam kalender lokal |
| `event_location` | `VARCHAR` | — | Ya | Lokasi acara bila diisi |
| `status` | `VARCHAR` | — | Tidak | `DRAFT`, `CONFIRMED`, `CANCELLED`, atau `FULFILLED` |
| `effective_at` | `DATETIME` | — | Tidak | Saat versi mulai berlaku |
| `available_at` | `DATETIME` | — | Tidak | Saat versi tersedia bagi sistem |
| `confirmed_at` | `DATETIME` | — | Ya | Waktu konfirmasi. Wajib untuk `CONFIRMED` dan `FULFILLED` |
| `fulfilled_at` | `DATETIME` | — | Ya | Jika diisi, status harus `FULFILLED` dan waktunya di antara konfirmasi dan efektivitas |
| `source` | `VARCHAR` | — | Ya | Sumber revisi. Mendukung pelacakan revisi atas seed |

`effective_at <= available_at` dan `confirmed_at <= effective_at` jika waktu konfirmasi diisi. Indeks terpisah pada `event_date` dan `available_at`.

## `order_items`

Rincian menu untuk versi pesanan tertentu.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `order_id` | `VARCHAR` | PK, FK → `order_revisions.order_id` | Tidak | Komponen pertama FK revisi |
| `version` | `INTEGER` | PK, FK → `order_revisions.version` | Tidak | Komponen kedua FK revisi |
| `menu_id` | `VARCHAR` | PK, FK → `menus.menu_id` | Tidak | Menu pada revisi |
| `confirmed_portions` | `INTEGER` | — | Tidak | Integer lebih besar dari nol, diperiksa pula dengan SQLite `typeof` |
| `bom_version` | `VARCHAR` | — | Tidak | Versi BOM dipilih layanan. Relasi ke resep ditegakkan dalam aplikasi |

FK `(order_id, version)` harus menunjuk ke pasangan yang sama pada `order_revisions`.

## `users`

Identitas akun dashboard.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `username` | `VARCHAR` | PK | Tidak | Identitas pengguna, misalnya `ppic` |
| `role` | `VARCHAR` | — | Tidak | `MARKETING`, `PPIC`, atau `PFA` |
| `password_hash` | `VARCHAR` | — | Tidak | Hash pengguna dengan PBKDF2-HMAC-SHA256 dan salt |
| `active` | `BOOLEAN` | — | Tidak | Akun hanya dapat digunakan bila aktif. Bawaan ORM `true` |

## `devices`

Registri autentikasi perangkat/simulator dan pemetaan lokasi ke bahan.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `sensor_id` | `VARCHAR` | PK | Tidak | ID terdaftar, misalnya `SNS-GDG-01` |
| `ingredient_id` | `VARCHAR` | FK → `ingredients.ingredient_id` | Tidak | Bahan yang boleh dilaporkan oleh sensor. Diindeks |
| `key_hash` | `VARCHAR` | — | Tidak | Hash SHA-256 kunci perangkat, unik |
| `active` | `BOOLEAN` | — | Tidak | Perangkat aktif. Bawaan ORM `true` |
| `source` | `VARCHAR` | — | Tidak | Provenance registrasi, misalnya `synthetic` atau `physical`. Bawaan ORM `operational` |
| `location_id` | `VARCHAR` | — | Ya | ID lokasi opsional dari registri |

## `iot_telemetry_logs`

Audit paket yang strukturnya dapat dibaca, termasuk paket yang ditolak.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `log_id` | `VARCHAR` | PK | Tidak | ID audit `TLM-…` |
| `sensor_id` | `VARCHAR` | — | Tidak | ID dari paket, dipertahankan walau sensor tidak dikenali |
| `ingredient_id` | `VARCHAR` | FK → `ingredients.ingredient_id` | Tidak | ID bahan dari paket, dipertahankan walau paket ditolak |
| `registered_sensor_id` | `VARCHAR` | FK → `devices.sensor_id` | Ya | ID terdaftar dari autentikasi, bila ada |
| `measured_weight` | `FLOAT` | — | Tidak | Angka asli dari paket |
| `unit` | `VARCHAR` | — | Tidak | Satuan asal paket, misalnya `g` |
| `recorded_at` | `DATETIME` | — | Tidak | Saat pembacaan sensor |
| `received_at` | `DATETIME` | — | Tidak | Saat backend menerima paket |
| `validation_status` | `VARCHAR` | — | Tidak | `ACCEPTED` atau `REJECTED` |
| `rejection_code` | `VARCHAR` | — | Ya | Kode penolakan. Kosong untuk paket diterima |
| `stored_value` | `FLOAT` | — | Ya | Nilai yang dikonversi ke satuan dasar, hanya untuk paket diterima |
| `base_unit` | `VARCHAR` | FK → `ingredients.base_unit` | Ya | Satuan dasar hanya untuk paket diterima, misalnya `kg` |
| `device_source` | `VARCHAR` | — | Ya | Sumber dari registri perangkat |
| `location_id` | `VARCHAR` | — | Ya | Lokasi dari registri perangkat |

FK komposit `(ingredient_id, base_unit)` berlaku ketika satuan dasar terisi. Paket diterima mensyaratkan nilai tersimpan dan berat nonnegatif, ID terdaftar sama dengan sensor paket, serta `recorded_at <= received_at`. Paket ditolak menyimpan kode dan mengosongkan nilai serta satuan dasar. Indeks `(sensor_id, recorded_at)` dan `(ingredient_id, received_at)`.

## `iot_telemetry_request_rejections`

Audit penolakan request saat struktur paket belum lolos validasi atau parsing.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `log_id` | `VARCHAR` | PK | Tidak | ID audit |
| `received_at` | `DATETIME` | — | Tidak | Saat backend mencatat penolakan. Diindeks |
| `rejection_code` | `VARCHAR` | — | Tidak | Kode penolakan request |

## `weekly_demand`

Rekap kuantitas riwayat per bahan dan per minggu sebagai sumber lag.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `week_start` | `DATE` | PK | Tidak | Senin awal minggu ISO |
| `ingredient_id` | `VARCHAR` | PK, FK → `ingredients.ingredient_id` | Tidak | Bahan pada rekap |
| `base_unit` | `VARCHAR` | FK → `ingredients.base_unit` | Tidak | Satuan dasar yang cocok dengan bahan |
| `quantity` | `FLOAT` | — | Tidak | Kuantitas demand minggu itu, nonnegatif |
| `available_at` | `DATETIME` | — | Tidak | Waktu rekap boleh dipakai untuk inferensi |
| `complete` | `BOOLEAN` | — | Tidak | Kelengkapan rekap. Hanya rekap lengkap memenuhi syarat lag |
| `source` | `VARCHAR` | — | Tidak | Provenance seri, misalnya `synthetic` |

FK komposit `(ingredient_id, base_unit)`.

## `feedback_evidence`

Rekonsiliasi mingguan berversi yang sudah disetujui untuk fitur `prev_error_adj`.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `week_start` | `DATE` | PK | Tidak | Senin awal minggu ISO |
| `ingredient_id` | `VARCHAR` | PK, FK → `ingredients.ingredient_id` | Tidak | Bahan yang direkonsiliasi |
| `approved_at` | `DATETIME` | PK | Tidak | Waktu persetujuan, bagian identitas versi |
| `payload` | `JSON` | — | Tidak | Rekonsiliasi dan bukti gerakan stok sebagai JSON |
| `source` | `VARCHAR` | — | Tidak | Provenance rekonsiliasi, misalnya `synthetic` |

## `forecast_runs`

Header audit inferensi dan snapshot yang dipakai model.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `forecast_run_id` | `VARCHAR` | PK | Tidak | ID run `FC-…` |
| `target_period` | `VARCHAR` | — | Tidak | Minggu ISO target |
| `model_version` | `VARCHAR` | — | Tidak | Identitas artefak model |
| `cutoff_at` | `DATETIME` | — | Tidak | Batas waktu visibilitas input |
| `published_at` | `DATETIME` | — | Tidak | Waktu publikasi hasil, ≥ cutoff |
| `snapshot_id` | `VARCHAR` | — | Tidak | Identitas snapshot fitur |
| `bom_version` | `VARCHAR` | — | Tidak | Versi katalog BOM |
| `calendar_version` | `VARCHAR` | — | Tidak | Versi kalender musim |
| `source` | `VARCHAR` | — | Tidak | Provenance input |
| `season_flags` | `JSON` | — | Tidak | Flag Ramadan, musim pernikahan, dan akhir tahun |
| `feedback_reasons` | `JSON` | — | Tidak | Alasan penggunaan atau ketiadaan feedback per bahan |
| `feedback_audit` | `JSON` | — | Tidak | Metadata penelusuran koreksi per bahan |

Indeks `(target_period, published_at)`.

## `forecast_run_items`

Keluaran inferensi untuk setiap bahan di dalam run.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `forecast_run_id` | `VARCHAR` | PK, FK → `forecast_runs.forecast_run_id` | Tidak | Header run prediksi |
| `ingredient_id` | `VARCHAR` | PK, FK → `ingredients.ingredient_id` | Tidak | Bahan yang diprediksi |
| `base_unit` | `VARCHAR` | FK → `ingredients.base_unit` | Tidak | Satuan dasar yang cocok dengan bahan |
| `predicted_demand` | `FLOAT` | — | Tidak | Prediksi demand tambahan, nonnegatif |
| `prev_error_adj` | `FLOAT` | — | Tidak | Nilai koreksi historis bertanda dalam satuan dasar |
| `confirmed_bom` | `FLOAT` | — | Tidak | Kebutuhan BOM yang sudah terkonfirmasi di cutoff, nonnegatif |

FK komposit `(ingredient_id, base_unit)`.

## `shopping_lists`

Header dan status daftar belanja mingguan.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `list_id` | `VARCHAR` | PK | Tidak | ID daftar `SL-…` |
| `planning_period` | `VARCHAR` | — | Tidak | Minggu ISO, unik. SQL memeriksa format dan rentang `01`–`53` |
| `status` | `VARCHAR` | — | Tidak | `DRAFT`, `VALIDATED_BY_PPIC`, atau `SENT_TO_PFA`. Bawaan ORM `DRAFT` |
| `created_at` | `DATETIME` | — | Tidak | Waktu pembuatan draf |
| `forecast_run_id` | `VARCHAR` | FK → `forecast_runs.forecast_run_id` | Ya | Run terkait bila menggunakan forecast |
| `warnings` | `JSON` | — | Tidak | Daftar peringatan kalkulasi. Bawaan ORM array kosong |
| `ppic_notes` | `VARCHAR` | — | Ya | Catatan PPIC untuk daftar |
| `validated_by` | `VARCHAR` | FK → `users.username` | Ya | Akun PPIC yang menyetujui |
| `validated_at` | `DATETIME` | — | Ya | Waktu validasi, ≥ pembuatan |
| `procurement_required` | `BOOLEAN` | — | Ya | Terisi setelah approval, bernilai benar jika ada kuantitas final positif |
| `sent_at` | `DATETIME` | — | Ya | Ada hanya pada status terkirim, ≥ waktu validasi |

Status setelah `DRAFT` mewajibkan `validated_at`, `validated_by`, dan `procurement_required`. Status `SENT_TO_PFA` juga mewajibkan `procurement_required = true`. Indeks `(status, planning_period)`.

## `shopping_list_items`

Komponen rekomendasi, snapshot stok, dan keputusan final per bahan.

| Kolom | Tipe SQLite | Kunci | NULL? | Keterangan |
| --- | --- | --- | --- | --- |
| `list_id` | `VARCHAR` | PK, FK → `shopping_lists.list_id` | Tidak | Header daftar belanja |
| `ingredient_id` | `VARCHAR` | PK, FK → `ingredients.ingredient_id` | Tidak | Bahan yang direncanakan |
| `base_unit` | `VARCHAR` | FK → `ingredients.base_unit` | Tidak | Satuan dasar yang cocok dengan bahan |
| `bom_confirmed_need` | `FLOAT` | — | Tidak | Kuantitas dari order terkonfirmasi |
| `ai_additional_forecast` | `FLOAT` | — | Tidak | Demand tambahan dari model atau nol |
| `safety_stock` | `FLOAT` | — | Tidak | Buffer yang disalin saat kalkulasi |
| `iot_available_stock` | `FLOAT` | — | Ya | Nilai stok snapshot jika tersedia |
| `stock_status` | `VARCHAR` | — | Tidak | `FRESH` atau `STALE` |
| `system_net_recommendation` | `FLOAT` | — | Tidak | Hasil kalkulasi bersih, tetap tersimpan setelah approve |
| `ppic_final_qty` | `FLOAT` | — | Ya | Kuantitas yang diputuskan PPIC dalam satuan dasar |
| `ppic_notes` | `VARCHAR` | — | Ya | Catatan item, termasuk cek stok usang dan alasan penolakan AI jika diisi |

FK komposit `(ingredient_id, base_unit)`. Semua kuantitas nonnegatif bila berisi nilai.

## Perilaku transaksi dan lifecycle

| Operasi | Persistensi dan aturan |
| --- | --- |
| Pesanan baru | Satu transaksi mengisi `orders`, `order_revisions` versi 1, dan `order_items`. Versi awal berstatus `CONFIRMED`. |
| Revisi | Nomor versi terkini menjadi prasyarat. Layanan menambah revisi dan baris menu baru, sehingga pembacaan kembali pada cutoff terdahulu masih dapat memakai versi lama. Pencarian memeriksa efektivitas dan ketersediaan versi. API revisi hanya menerima pesanan terkonfirmasi. |
| Telemetri | Paket diterima ditulis ke log dan menimpa stok serta waktu sinkron terakhir dalam satu transaksi. Pembaruan kondisional menjaga urutan waktu per bahan. Paket yang lolos parsing tetapi gagal validasi bisnis disimpan dengan status `REJECTED`, sedangkan audit kesalahan struktur masuk ke `iot_telemetry_request_rejections`. Paket ditolak tidak mengubah inventori. |
| Forecast | `DatabaseSnapshots` menyeleksi bukti yang tersedia pada cutoff. `DatabaseRuns` menyimpan header dan item inferensi, termasuk BOM dan nilai koreksi, sebagai satu run. |
| Kalkulasi | Reservasi periode, pembacaan order dan stok, pembacaan snapshot inferensi, penyimpanan run opsional, serta isi draf memakai satu transaksi. Kesalahan mengembalikan keadaan sebelum transaksi. |
| Buat draf SYSTEM | Reservasi dan penulisan item dilakukan dalam satu transaksi. Pembuatan melalui kalkulasi dan melalui SYSTEM berbagi constraint unik periode. Periode tetap terpakai pada setiap status, termasuk setelah dikirim dan setelah hasil final nol. |
| Approve dan send | Masing-masing menggunakan transaksi terpisah dengan prasyarat status. Approve menyimpan seluruh kuantitas final dan audit PPIC. Send hanya mengubah daftar yang tervalidasi dan masih perlu pengadaan. |
| Restart | Backend membuka kembali database yang sama dari `SIKEMBANG_DB_PATH`. Uji HTTP Sprint 7 membaca kembali daftar terkirim dan versi pesanan setelah restart serta memeriksa integritas dan FK. |

`init-db` membuat tabel yang belum ada dan menambahkan kolom provenance/lokasi yang belum tersedia pada database lama. `create_app` mengharuskan file dan skema disiapkan terlebih dahulu. Engine mengaktifkan `PRAGMA foreign_keys=ON` pada setiap koneksi. `seed` memasukkan fixture dengan ID stabil, merekap empat minggu selesai relatif terhadap cutoff demo, dan mempertahankan data yang sudah ada. Rekap menggunakan bagian arsip sintetis yang tersedia atau generator bertumpu pada seed dan tanggal minggu. Hash password tetap memakai salt acak. [Inisialisasi](../../ml/src/sikembang_backend/db.py), [CLI](../../ml/src/sikembang_backend/manage.py), [seed](../../ml/src/sikembang_backend/seed.py).

## Provenance data

| Jenis | Penggunaan dan batas bukti |
| --- | --- |
| Referensi publik SonoKembang | Konteks layanan katering untuk D2 dan penyusunan asumsi. |
| Rekaman bisnis sintetis | Pesanan seed, histori demand dan dataset evaluasi adalah hasil generator/fixture. `order_revisions.source` dapat kosong pada seed. Baca sumber pesanan induk sebagai provenance versi tersebut. |
| Resep representatif | `ml/config/catalog-and-bom-v1.json` menetapkan bahan, menu, dan BOM per porsi. Fixture ini mewakili bentuk resep untuk pengujian. Formula resep operasional perusahaan belum divalidasi. |
| Feedback historis sintetis | Arsip rekonsiliasi terpisah di `feedback_evidence` memungkinkan pengujian koreksi. Riwayat pengukuran skala fisik perusahaan belum tersedia untuk validasi ini. |
| Telemetri simulasi | Paket dikirim melalui kontrak perangkat. `device_source=synthetic` mengikuti registri dan muncul pada bukti Sprint 7. |
| Telemetri fisik | Registrasi manual dapat memakai `physical` beserta lokasi. Penerimaan paket dari alat fisik membutuhkan pembuktian dengan serial, OLED, API, dan audit database. |
| Data demo yang dimasukkan pengguna | Pesanan baru melalui API dapat tercatat sebagai `operational` karena jalur inputnya. Label ini tidak membuktikan transaksi nyata SonoKembang. |

Data bisnis dan evaluasi sintetis menguji reproduktibilitas prototipe. Pengukuran akurasi di SonoKembang memerlukan transaksi dan rekonsiliasi stok yang terverifikasi. [Metadata katalog dan generator](../../ml/config) · [bukti browser dan provenance telemetri](../testing/sprint7_browser_evidence.json) · [walkthrough fisik](../../firmware/esp32_scale/README.md).
