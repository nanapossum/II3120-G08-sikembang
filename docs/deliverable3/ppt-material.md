# Materi PowerPoint Deliverable 3 SiKembang

Sisipkan delapan slide D3 di presentasi gabungan D1–D3. Pada PDF grup, halaman 30 sudah menjadi cover D3 dan dapat dipertahankan sebagai pemisah. Gabungkan ringkasan halaman 32–33 dengan slide D3-01 dan D3-08 agar kronologi desain, implementasi, dan pengujian terbaca sekali. Siapkan sekitar lima menit untuk delapan slide D3 dan satu hingga dua menit untuk demo ringkas. Tambahkan demo langsung hingga tiga menit untuk slot 15 menit. Ketentuan *Tugas Besar II3120* mencantumkan slot kelompok 10 menit pada Rabu dan 15 menit pada Jumat.

Pertahankan format 16:9, judul kiri atas, navigasi bagian di bawah, judul League Spartan Bold, dan isi Garet sesuai template grup. Gunakan latar putih dengan aksen hijau `#274636` dan `#568A35` serta krem pada subjudul seperti halaman 32 PDF. Pakai satu visual utama per slide. Grafik dan tangkapan layar tetap dalam rasio aslinya. Label *telemetri simulasi* dipertahankan pada gambar atau caption yang menampilkan stok uji. Judul, subjudul, lima atau lebih sedikit butir, serta caption di bawah ini dapat ditempel pada template.

## D3-01 · Pendahuluan

**Judul** — Implementasi SiKembang

**Subjudul** — F3 dan F4 pada perencanaan pengadaan SonoKembang Catering Malang

**Teks slide**

- F3 · Pesanan dan revisi tersimpan pada satu sumber
- F4 · Telemetri stok dan prediksi kebutuhan tambahan
- PPIC menetapkan kuantitas akhir untuk PFA

**Visual utama** — Diagram arsitektur dengan fokus pada jalur Marketing → PPIC → PFA. Caption *Dari pesanan terkonfirmasi hingga daftar belanja diterima PFA.* [Diagram sistem](diagrams/01-system.svg)

**Temuan kunci dan catatan presenter** — Jelaskan bahwa modul terpusat mewakili sinkronisasi pada desain D2. Pembelian aktual berada di luar ruang lingkup. Alur utama memakai aplikasi React, FastAPI, dan SQLite. [Materi laporan](report-material.md) · [Keterlacakan](traceability.md)

## D3-02 · Teknologi & API

**Judul** — Satu backend, lima layanan logis

**Subjudul** — FastAPI · React · SQLite

**Teks slide**

- Order · InventoryIoT · AIForecast · ProcurementCalc · ShoppingList
- 11 endpoint bisnis dengan JSON dan otorisasi peran
- SQLite menyimpan revisi, stok, run prediksi, dan keputusan PPIC
- Prediksi dan draf pengadaan tersimpan dalam transaksi yang sama

**Visual utama** — Diagram komponen backend. Tambahkan ERD sebagai slide cadangan untuk pertanyaan skema. Caption *Layanan SoaML terwujud sebagai modul dalam aplikasi FastAPI.* [Komponen backend](diagrams/02-backend.svg) · [ERD](diagrams/09-erd.svg)

**Temuan kunci dan catatan presenter** — Bearer JWT untuk dashboard, `X-Device-Key` untuk sensor, otoritas SYSTEM untuk draf. SQLite mempertahankan revisi dan status setelah restart. Tampilkan `/docs` ketika membahas kontrak. [Spesifikasi API](api.md) · [Kamus data](database.md) · [Bukti restart](../testing/sprint7_http_evidence.json)

## D3-03 · Teknologi & API

**Judul** — Model memperkirakan kebutuhan tambahan

**Subjudul** — XGBoost per bahan dan minggu ISO

**Teks slide**

- Target · Kebutuhan yang masih tersisa setelah BOM terkonfirmasi
- 5.155 pesanan sintetis · 17.920 baris fitur
- 18 fitur · 4 lag mingguan, musim, feedback, konteks cutoff, identitas bahan
- Train 10.570 · validation 3.570 · test 3.640 · purge 140

**Visual utama** — Pipeline training dengan angka split ditempatkan di bawah tahap pemisahan kronologis. Caption *Fitur mengikuti informasi yang tersedia pada cutoff perencanaan.* [Pipeline training](diagrams/03-training.svg)

**Temuan kunci dan catatan presenter** — Satu model gabungan memakai penanda bahan dan skala per baris dari empat lag. Jelaskan bahwa stok terkini masuk kalkulasi pengadaan. Tunjukkan diagram inferensi sebagai cadangan untuk pertanyaan urutan fitur. [Pipeline inferensi](diagrams/04-inference.svg) · [Audit ML](../testing/sprint7_ml_evidence.json)

## D3-04 · Teknologi & API

**Judul** — XGBoost dan baseline pada test sintetis

**Subjudul** — 3.640 baris evaluasi, versi `xgb-v1-f9a770b940f71fc8`

**Teks slide**

- MAE ternormalisasi · XGBoost 0,073093 · median 0,074741 · nol 0,145075
- MAE ternormalisasi turun 2,20% dibanding median
- RMSE turun pada 5 bahan dibanding median
- MAE santan naik dari 1,691 menjadi 1,786 L

**Visual utama** — Grafik RMSE per bahan. Jika ruang cukup, pasang grafik MAE berukuran sama. Caption *Model dan baseline diuji pada baris yang sama. Nilai mentah mengikuti unit setiap bahan.* [Grafik RMSE](evidence/evaluation/03-rmse.png) · [Grafik MAE](evidence/evaluation/02-mae.png)

**Temuan kunci dan catatan presenter** — Tingkat perbaikan berlaku pada data sintetis. Ablation validation `0,080872` dengan feedback dan `0,080740` tanpa feedback. Validasi operasional memerlukan histori perusahaan yang disetujui. [Ablation](evidence/evaluation/06-feedback-ablation.png) · [Audit model](../testing/sprint7_ml_evidence.json)

## D3-05 · Teknologi & API

**Judul** — Integrasi timbangan ESP32

**Subjudul** — Load cell · HX711 · OLED SSD1306 · Wi-Fi LAN

**Teks slide**

- ESP32 mengirim massa dan timestamp melalui REST
- Backend memvalidasi sensor, satuan, waktu, dan urutan paket
- Simulasi live · 17.500 g → 17,5 kg FRESH
- Build ESP32 lulus · upload dan kalibrasi fisik tertunda

**Visual utama** — Diagram wiring dan jalur data ke FastAPI. Caption *Firmware dikompilasi untuk ESP32. Jalur demo memakai sumber telemetri simulasi berlabel.* [Wiring dan komunikasi](diagrams/08-iot.svg)

**Temuan kunci dan catatan presenter** — Build firmware dan uji host lulus. Audit mendeteksi nol port COM. Foto rangkaian, Serial Monitor, OLED dengan beban referensi, dan transaksi fisik menunggu capture manual setelah perangkat diuji. [Panduan firmware](../../firmware/esp32_scale/README.md) · [Verifikasi](verification.md)

## D3-06 · Prototipe & Fitur

**Judul** — Prediksi dan stok menghasilkan draf pengadaan

**Subjudul** — `maks(0, BOM terkonfirmasi + AI + safety stock − stok tersedia)`

**Teks slide**

- Beras · BOM 69 kg + prediksi 4,498 kg + safety 5 kg
- Stok 20,5 kg → rekomendasi 57,998 kg
- Stok simulasi 17,5 kg → rekomendasi 60,998 kg
- Feedback historis berasal dari konsumsi yang direkonsiliasi

**Visual utama** — Dua baris perbandingan stok dan hasil, dengan diagram feedback sebagai cadangan. Caption *Pesanan, cutoff dan model sama. Stok turun 3 kg, rekomendasi naik 3 kg.* [Bukti HTTP](../testing/sprint7_http_evidence.json) · [Alur feedback](diagrams/05-feedback.svg)

**Temuan kunci dan catatan presenter** — Stok terkini menjadi pengurang di pengadaan. `prev_error_adj` masuk sebagai fitur model dari periode tertutup dengan bukti valid. PPIC memeriksa stok usang dan mencatat alasan sebelum approval. [Dokumentasi AI](ai.md) · [Urutan alur](diagrams/06-sequence.svg)

## D3-07 · Prototipe & Fitur

**Judul** — PPIC memvalidasi, PFA menerima

**Subjudul** — `DRAFT → VALIDATED_BY_PPIC → SENT_TO_PFA`

**Teks slide**

- Marketing mencatat pesanan · revisi tersedia melalui API
- PPIC meninjau, mengubah kuantitas, atau menolak saran AI
- PFA menerima kuantitas akhir positif · beras 42,25 kg pada uji live

**Visual utama** — Potret review PPIC dengan detail kuantitas terbaca dan potret PFA sebagai visual kedua. Tambahkan planning sebagai cadangan. Caption *Dashboard React live, FastAPI, XGBoost, dan stok simulasi.* [Planning PPIC](evidence/screenshots/01-ppic-planning.png) · [Review PPIC](evidence/screenshots/02-ppic-review.png) · [Daftar PFA](evidence/screenshots/03-pfa-handoff.png)

**Temuan kunci dan catatan presenter** — Approval dan pengiriman merupakan dua transisi backend. Untuk foto Marketing atau Swagger yang diminta kelompok, lakukan capture manual dan sembunyikan informasi sesi. [Bukti browser](../testing/sprint7_browser_evidence.json) · [Panduan demo](demo.md)

## D3-08 · Pengujian & Demo

**Judul** — Verifikasi alur dari pesanan ke PFA

**Subjudul** — Hasil Sprint 7 dan status demo

**Teks slide**

- 405 Pytest · 34 Vitest · lint dan build frontend lulus
- 38 transaksi HTTP · 11 endpoint bisnis terverifikasi
- Chrome live · 20 respons backend dan alur PPIC → PFA
- Demo · order → stok simulasi → AI → persetujuan → PFA
- Pengukuran fisik dan validasi model pada data mitra menunggu bukti

**Visual utama** — Diagram alur pengguna atau tiga panel ringkas Marketing, PPIC, dan PFA. Panel Marketing memerlukan capture manual. Caption *Verifikasi perangkat lunak memakai API dan database live serta telemetri simulasi.* [Alur pengguna](diagrams/10-user-flow.svg) · [Laporan pengujian](verification.md)

**Temuan kunci dan catatan presenter** — Jalankan demo dengan periode baru pada database demo yang sudah disiapkan. Tunjukkan model version pada respons prediksi dan daftar terkirim pada PFA. Jika demo langsung terhambat, gunakan bukti browser dan JSON HTTP Sprint 7. Sebutkan bahwa pemetaan individual TC menunggu Tabel 11.1 D2. [Demo dan kontingensi](demo.md) · [Paket bukti](EVIDENCE_INDEX.md) · [Keterlacakan](traceability.md)
