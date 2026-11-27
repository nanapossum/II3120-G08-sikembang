# Pengujian dan verifikasi

Bukti di bawah berasal dari audit Sprint 7 pada 27 November 2026. Perubahan hardening yang diuji tercatat di `ac5b405`. Sprint 8 mengonsolidasikan bukti ke handoff. Run utama HTTP menggunakan Uvicorn dan SQLite terisolasi pada cutoff 12.00 WIB. Run browser memakai Chrome headless, Vite preview, dan database lain. Kedua run memakai model beku `xgb-v1-f9a770b940f71fc8`.

## Hasil pengujian

| Tujuan | Metode dan skenario | Hasil yang diharapkan | Hasil yang diamati | Status dan bukti |
|---|---|---|---|---|
| Setup Windows dan dependensi | Venv bersih, lockfile, package editable, npm ci terisolasi | Instalasi lengkap, dependency check bersih | pip check bersih dan npm ci memasang 244 paket | PASS · [log](../testing/sprint7_test_results.txt) |
| Schema, seed dan persistence | Init, seed dan seed ulang setelah demo, restart Uvicorn | Relasi sah, seed ulang menjaga data | integrity ok, FK check kosong, 0 baris baru pada seed ulang, order dan PFA terbaca setelah restart | PASS · [HTTP/SQLite](../testing/sprint7_http_evidence.json) |
| Autentikasi dan pembatasan peran | JWT valid/hilang/kedaluwarsa, DEVICE, SYSTEM, header role palsu | 401 atau 403 pada akses yang salah | Route terproteksi. Regresi kunci SYSTEM yang bertabrakan dengan registry berubah dari 201 ke 403 | PASS · [tes auth](../../ml/tests/test_backend_auth.py) · [tes draf](../../ml/tests/test_backend_drafts.py) |
| Order dan konflik | Buat order, revisi 40→60 porsi, ulangi versi lama | 201 versi 1, 200 versi 2, 409 konflik | HTTP memberi VERSION_CONFLICT dan SQLite menyimpan versi 1 serta 2 | PASS · [HTTP](../testing/sprint7_http_evidence.json) |
| Ingest dan audit telemetry | 17.500 g, pakai timestamp pada batas 300 detik, 8 paket tidak valid | 201 dan 17,5 kg. Penolakan tercatat | 17,5 kg FRESH, 8 log penolakan, nilai valid bertahan. Unit dan batas 60 menit juga diuji | PASS simulasi · [HTTP](../testing/sprint7_http_evidence.json) · [tes stok](../../ml/tests/test_backend_inventory.py) |
| Dataset dan temporal | Regenerasi seed 3120 dan rekonstruksi raw JSONL, lag, target dan cutoff | Hash bundle sama, histori tersedia pada cutoff | 10 berkas identik, 17.920 baris direkonstruksi. Audit tidak menemukan leakage pada pemeriksaan itu | PASS sintetis · [audit ML](../testing/sprint7_ml_evidence.json) |
| Evaluasi, serialisasi dan reload | Set test kronologis, perbandingan nol/median/XGBoost, evaluasi berkas UBJ | Prediksi konsisten dan skor terukur per bahan | 3.640 prediksi persis, MAE ternormalisasi 0,073093 vs median 0,074741 | PASS sintetis · [audit ML](../testing/sprint7_ml_evidence.json) · [grafik](evidence/evaluation/02-mae.png) |
| Endpoint forecast | POST prediksi dengan bahan/tanggal sah dan fixture histori kurang | 201 versi/run/item, 422 saat lag hilang | Respons beras 4,498 kg, model asli dan run tersimpan. Histori kurang mengembalikan 422 INSUFFICIENT_HISTORY | PASS · [HTTP](../testing/sprint7_http_evidence.json) |
| Feedback | Ledger replay tersegel, pembanding netral, provenance fisik dalam fixture | Koreksi sesuai cutoff dan satu kali pada model | Simulasi nonnol direproduksi. Run HTTP live memakai UNAVAILABLE/0,0 untuk histori tanpa ledger. Audit fisik nyata belum tersedia | PASS simulasi · [bukti replay](evidence/evaluation/feedback-replay.json) |
| Kalkulasi | Fixture D2, stok berubah, tanpa artefak, opsi tanpa AI | 37,5 kg untuk input D2, delta 3 kg saat stok turun 3 kg, no-AI berhasil | Model aktual 4,498 kg. Net 57,998→60,998 kg. Saat model absen, AI aktif mendapat 500 MODEL_UNAVAILABLE dan no-AI mendapat 201 | PASS · [HTTP](../testing/sprint7_http_evidence.json) |
| Lifecycle, audit dan error | Draf, konflik aktif, invalid transition, approval g/ml, PPIC dan PFA setelah kirim | 409 pada konflik. Approval kanonis. Proyeksi sesuai peran | 42.250 g→42,25 kg pada run HTTP. Tes 3.750 ml→3,75 liter lulus. PPIC menyimpan keputusan nol, PFA menampilkan hanya jumlah positif | PASS · [HTTP](../testing/sprint7_http_evidence.json) · [tes lifecycle](../../ml/tests/test_backend_shopping_lists.py) |
| Frontend lint/unit/build | ESLint, Vitest, tsc dan Vite | Exit 0 | 34 tes lulus pada 9 berkas. Build memberi peringatan ukuran chunk di atas 500 kB | PASS · [log](../testing/sprint7_test_results.txt) |
| Frontend live dan mock | Browser beralih mock dan live, alur Marketing → PPIC → PFA | MSW aktif di mock, request live ke backend | 20 respons API live berasal dari backend, 0 live melalui worker. PFA melihat 42,25 kg. Peran mock dan stok via MSW terbukti | PASS · [browser](../testing/sprint7_browser_evidence.json) |
| Firmware host dan target | C++11 dan Arduino CLI FQBN ESP32 | Tes kebijakan dan program target berhasil | 9 kelompok host lulus. Build target exit 0, flash 815.437 byte, RAM global 46.824 byte | PASS · [bukti firmware](evidence/firmware-build.json) |
| Integrasi fisik | Deteksi board, rencana upload/kalibrasi/Wi-Fi/OLED/ingest | Port terdeteksi dan bobot fisik masuk ke PPIC | Windows dan Arduino CLI mendeteksi 0 port serial. Belum ada upload, kalibrasi, atau pembacaan fisik terverifikasi | BLOCKED · [bukti firmware](evidence/firmware-build.json) |
| E2E dan restart | Order, telemetry simulasi, XGBoost, DRAFT, approval, send dan PFA | Alur persisten lintas peran | 38 respons HTTP, 11 operasi bisnis, 3 database terisolasi dan pembacaan PFA sesudah restart | PASS simulasi · [HTTP](../testing/sprint7_http_evidence.json) |

Browser membuat order melalui form Marketing. Uji revisi dilakukan melalui REST karena layar edit order belum tersedia. Screenshot browser memakai 21,5 kg dari fixture tersendiri. Skenario pembanding procurement memakai 17,5 kg dari run HTTP. Seluruh telemetry yang diterima pada run tersebut tercatat `synthetic`.

## Perintah yang dieksekusi saat audit

Jalankan dari root repository. Path venv di bawah adalah lingkungan bersih yang dipakai saat audit. Gunakan path Python venv yang tersedia di mesin pengulang.

```powershell
$env:OMP_NUM_THREADS = '2'
rtk proxy ml/runtime/sprint7/venv/Scripts/python.exe -m pytest ml/tests -q -p no:cacheprovider
rtk proxy npm.cmd run lint
rtk proxy npm.cmd test
rtk proxy npm.cmd run build
rtk proxy ml/runtime/sprint7/venv/Scripts/python.exe -X utf8 docs/testing/verify_sprint7.py --cutoff 2026-11-27T12:00:00+07:00
$env:SIKEMBANG_TEST_PYTHON = 'ml/runtime/sprint7/venv/Scripts/python.exe'
rtk proxy node ml/testing/verify_sprint7_browser.mjs --preview
rtk proxy ml/.venv/Scripts/python.exe docs/testing/verify_sprint7_firmware.py
rtk proxy ml/.venv/Scripts/python.exe -m ai_forecast.dataset --seed 3120 --output ml/runtime/sprint7/ml/synthetic-v1
rtk proxy ml/.venv/Scripts/python.exe docs/testing/sprint7_verify_ml.py --dataset ml/generated/synthetic-v1 --regenerated ml/runtime/sprint7/ml/synthetic-v1 --artifact ml/artifacts/xgb-v1-f9a770b940f71fc8 --output docs/testing/sprint7_ml_evidence.json --chart-output ml/runtime/sprint7/ml/charts
```

Pytest lengkap menghasilkan **405 lulus** dengan satu peringatan deprekasi Starlette TestClient. Seleksi terfokus mencatat 75 lulus untuk Auth/Draft, 71 untuk ShoppingList/Inventory, 136 untuk ML, dan 42 untuk forecast/feedback/procurement. Seleksi tersebut bertumpang tindih dengan suite lengkap. File bukti reproduksi ML dapat disimpan ke path baru saat mengulang.

D2 Bab IX menjadi sumber kontrak dan PPT mengelompokkan TC-01–12. Definisi kasus individual dari Tabel 11.1 masih diperlukan untuk mengaitkan hasil ke nomor TC-08 atau TC-09 secara spesifik. Skenario aktual prediksi dan pengadaan beserta statusnya tersedia pada matriks dan log. [Matriks traceability](traceability.md) · [Indeks bukti](EVIDENCE_INDEX.md)
