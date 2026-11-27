# SiKembang · Handoff Deliverable 3

SiKembang membantu perencanaan pengadaan SonoKembang Catering Malang. Order terkonfirmasi dan revisinya mengatasi F3. Telemetry stok, forecast kebutuhan tambahan, kalkulasi kebutuhan bersih, dan review PPIC mengatasi F4. Hasil akhirnya adalah permintaan bahan untuk PFA. Pembelian ke pemasok, pembayaran, produksi, dan pengiriman berada di luar lingkup demonstrasi.

**Kesiapan demo software** adalah PASS WITH LIMITATIONS untuk backend live dengan telemetry simulasi. Model XGBoost terlatih dan alur Marketing → PPIC → PFA terverifikasi. Firmware ESP32 sudah dikompilasi dan verifikasi fisik menunggu perangkat.

## Pilih pekerjaan

| Tujuan | Dokumen |
|---|---|
| Pasang aplikasi dan jalankan demo | [Windows](windows.md) · [Demo dan pemulihan](demo.md) |
| Pelihara backend, API, atau database | [Sistem dan lima layanan](system.md) · [REST API](api.md) · [ERD dan kamus data](database.md) |
| Jelaskan dan reproduksi model | [AI, dataset dan feedback](ai.md) · [Evaluasi](EVIDENCE_INDEX.md#grafik-evaluasi-dan-distribusi) |
| Siapkan perangkat | [Firmware, wiring, upload, dan kalibrasi](../../firmware/esp32_scale/README.md) |
| Kembangkan atau uji UI | [Integrasi frontend](system.md) · [Konvensi frontend](../architecture.md) |
| Susun laporan dan presentasi | [Draf laporan](report-material.md) · [Isi PPT](ppt-material.md) · [Tanya jawab penguji](qa.md) |
| Pilih bukti dan cocokkan dengan D2 | [Indeks bukti](EVIDENCE_INDEX.md) · [Verifikasi](verification.md) · [Traceability](traceability.md) |
| Serah terima branch | [Definition of Done dan batas](handoff.md) · [Draf deskripsi PR](pr-draft.md) |

## Versi yang dipakai dalam verifikasi

| Lapisan | Teknologi |
|---|---|
| Runtime | Python 3.13.2, Node.js 24.19.0, npm 11.17.0, Windows PowerShell |
| Backend | FastAPI 0.165.0, Pydantic 2.14.4, Uvicorn 0.54.0, SQLAlchemy 2.0.53, SQLite 3.45.3 |
| Identitas | JWT HS256 dengan PyJWT 2.15.1, PBKDF2-HMAC-SHA256 untuk sandi, `X-Device-Key` per perangkat, otorisasi SYSTEM internal dan HTTP opt-in |
| ML dan plot | XGBoost 3.1.3, scikit-learn 1.6.1, NumPy 2.2.6, Matplotlib 3.10.3. Pembacaan CSV memakai library standar Python. Pandas tidak ada pada environment lock yang diuji |
| Web | React 19.3.1, TypeScript 6.0.3, Vite 8.3.8, Tailwind CSS 4.3.5, React Router DOM 7.18.6 |
| Form dan respons API | TanStack Query 5.108.4, React Hook Form 7.92.0, Zod 4.6.7 |
| Pengujian | Pytest 9.1.1, Vitest 5.1.1, ESLint 10.15.0, MSW 3.0.7, Chrome headless. CI repo menjalankan lint, tes dan build frontend |
| Firmware | ESP32 Dev Module, load cell, HX711, SSD1306. Arduino CLI 1.5.1, Arduino-ESP32 2.0.17, HX711 0.7.5, Adafruit SSD1306 2.5.16, GFX 1.12.4, BusIO 1.17.4 |

Satu aplikasi FastAPI menampung lima batas layanan SoaML dan satu database SQLite. Sesi transaksi yang sama dapat menjaga konsistensi stok, run model dan draf. Pemisahan modul memudahkan review tanpa menambah komunikasi antarproses. Platform ini sesuai untuk prototipe lokal dan uji terisolasi. [Arsitektur](system.md) · [Lockfile Python](../../ml/requirements-dev.lock) · [Lockfile frontend](../../package-lock.json)

## Bukti utama

- 405 tes Python dan 34 tes frontend lulus. Audit menggunakan 38 respons HTTP pada 11 operasi bisnis serta 20 respons API live yang direkam browser. [Verifikasi](verification.md)
- Pada data sintetis, XGBoost mencapai MAE ternormalisasi 0,073093 dan median historis 0,074741. Reload mereproduksi 3.640 prediksi. Ambil MAE dan RMSE per bahan dari tabel model. [Evaluasi](ai.md)
- Pada audit pengadaan, stok beras 20,5 kg→17,5 kg menaikkan rekomendasi 57,998→60,998 kg dalam dua database setara. PFA menerima kuantitas hasil review. [Bukti HTTP](../testing/sprint7_http_evidence.json)
- Build ESP32 dan tes host lulus. Tidak ada port COM saat audit sehingga bukti firmware yang tersedia mencakup kompilasi dan kebijakan host. Paket telemetry yang tampil di screenshot berasal dari simulator. [Status fisik](verification.md) · [Demo](demo.md)
