# Tanya jawab evaluasi SiKembang

## Arsitektur

**Mengapa memakai FastAPI?** FastAPI mendukung skema request dan response, dependensi autentikasi, pengelompokan router, dan OpenAPI otomatis. Backend dan model menggunakan Python sehingga orkestrasi pengadaan dapat memanggil inferensi secara langsung. Swagger UI juga memudahkan penguji memanggil kontrak yang sama dengan UI. [Factory aplikasi](../../ml/src/sikembang_backend/app.py) · [API](api.md)

**Mengapa modular monolith?** Kelima layanan logis tetap memiliki kontrak dan modul terpisah, dengan deployment satu proses dan penyimpanan yang sama. Pendekatan ini memudahkan transaksi atomik saat menghitung dan menyimpan draf beserta run model. Batas SoaML mendeskripsikan pembagian tanggung jawab dan pihak pengguna layanan. [Arsitektur](system.md)

**Bagaimana lima layanan SoaML dipetakan?** OrderService menangani create, revisi, dan pembacaan. InventoryIoTService menangani ingest dan stok. AIForecastService menggabungkan adapter inferensi, penyedia snapshot, feedback, dan penyimpan run. ProcurementCalcService mengorkestrasi perhitungan. ShoppingListService mencakup persetujuan, kirim, baca, serta `DraftService` untuk pembuatan draf. Pemetaan mencakup sebelas operasi bisnis dan rutenya. [Matriks lengkap](traceability.md)

**Mengapa SQLite dan apa batasnya?** SQLite mudah diinisialisasi pada Windows dan cukup untuk prototipe dengan beberapa peran dan sensor. SQLAlchemy mengaktifkan foreign key dan mengatur transaksi. SQLite membatasi konkurensi penulis dan belum menyediakan pola server terdistribusi yang dibutuhkan bila banyak lokasi mengirim telemetry bersamaan. [Kamus dan perilaku database](database.md)

**Bagaimana skala produksi ditangani?** Evaluasi beban dan SLA terlebih dahulu. Jalur evolusi meliputi database server dengan migrasi dan backup, HTTPS serta pengelolaan identitas perangkat, observabilitas, dan antrean ingest bila volume serta kebutuhan retry meningkat. Katalog, safety stock, ledger, dan peran perlu ditetapkan dengan mitra. [Arsitektur](system.md)

## AI

**Mengapa memilih XGBoost?** Boosted trees dapat menangkap interaksi nonlinier antara lag, musim, dan konteks cutoff pada data tabular kecil. Ia memiliki format model native dan dapat dijalankan lokal. Baseline nol dan median historis mengecek apakah kompleksitasnya menghasilkan perbaikan dalam protokol uji yang sama. [Eksperimen](ai.md)

**Apa yang sebenarnya diprediksi?** Kebutuhan tambahan per bahan bagi sisa minggu target ISO pada cutoff perencanaan. Label memakai selisih nonnegatif antara kebutuhan pesanan terpenuhi yang relevan dan kebutuhan BOM dari pesanan yang sudah terkonfirmasi saat cutoff. Hasil dikembalikan dalam kg, liter atau butir. [Definisi target](ai.md)

**Mengapa tidak memprediksi langsung daftar belanja?** Kuantitas belanja harus merespons revisi pesanan, stok terkini, aturan resep, safety stock, dan keputusan manusia. Model menangani ketidakpastian permintaan tambahan. Perhitungan deterministik menggabungkan hasil model dengan komponen operasional yang dapat diperiksa PPIC. [Integrasi](diagrams/05-feedback.svg) · [Kalkulasi](api.md)

**Bagaimana penghitungan ganda dicegah?** Snapshot memakai versi pesanan yang tersedia saat cutoff. Penyusunan target mengurangi BOM terkonfirmasi dari kebutuhan yang terealisasi untuk bagian periode yang relevan. Saat kalkulasi, sistem menjumlahkan BOM yang dapat diketahui pada cutoff dengan prediksi residu tambahan tepat satu kali. [Pembentukan target](../../ml/src/ai_forecast/orders.py)

**Mengapa empat lag mingguan?** Empat minggu tertutup merangkum pola permintaan jangka pendek dengan biaya data sederhana. Setiap lag harus sudah tersedia saat cutoff. Empat lag merupakan pilihan fitur rancangan. Evaluasi proyek belum menunjukkan jumlah lag optimal untuk operasi perusahaan. [Kamus fitur](ai.md)

**Bagaimana flag musim ditentukan?** Flag aktif bila minimal empat hari pada minggu target masuk interval kalender terkait. Bulan pernikahan pada fixture adalah Juni, Juli, dan November, sedangkan akhir tahun dimulai 15 Desember. Interval Ramadan, asumsi musim pernikahan dan akhir tahun tersimpan pada konfigurasi sebelum prediksi. [Kalender sintetis](../../ml/config/calendar-id-synth-v1.json) · [Metode](ai.md)

**Apa `prev_error_adj`?** Residual dari minggu tertutup. Konsumsi produksi yang diatribusikan direkonsiliasi dengan stok pembuka, stok penutup, dan ledger mutasi. Sistem mengurangi BOM terkonfirmasi referensi untuk mencari kebutuhan tambahan teramati, lalu mengurangi prediksi tambahan referensi. Residual positif berarti perkiraan referensi terlalu rendah. Koreksi dibatasi ±25% skala per baris dan dipakai sebagai fitur model. [Rinciannya](ai.md) · [Bukti replay](evidence/evaluation/feedback-replay.json)

**Bagaimana mencegah temporal leakage?** Snapshot pesanan dipilih sesuai cutoff, lag hanya memakai minggu tertutup yang sudah terbit, dan feedback harus disetujui sebelum cutoff. Split berjalan kronologis dengan purge di perbatasan dan tanggal label diverifikasi. Seleksi parameter memakai validation. Test akhir digunakan untuk perbandingan yang dilaporkan. Audit merekonstruksi 17.920 baris dari sumber. [Audit verifikasi ML](../testing/sprint7_ml_evidence.json)

**Mengapa menggunakan data sintetis?** Riwayat transaksi, resep operasional, dan konsumsi mitra yang lengkap belum tersedia untuk pelatihan. Fixture seed 3120 memungkinkan pengujian ulang terhadap pola musiman, revisi dan pembatalan. Profil publik memberi konteks kategori layanan. [Profil publik](https://sonokembangmalang.com/) · [Provenance data](ai.md)

**Bagaimana membaca MAE dan RMSE?** MAE adalah rerata besarnya kesalahan absolut. RMSE memakai kuadrat galat sebelum diakar sehingga lebih sensitif terhadap kesalahan besar. Laporkan keduanya per bahan dalam unitnya. MAE ternormalisasi membagi galat absolut dengan skala tiap baris berdasarkan empat lag, lalu merata-ratakan dengan bobot setara antar bahan. Bias menandai arah galat rata-rata. [Tabel hasil](report-material.md#pelatihan-dan-evaluasi-xgboost)

**Bagaimana bila model kalah dari baseline?** Pada test sintetis, MAE santan model 1,786 liter dibanding median 1,691 liter. Untuk penerapan riil, bandingkan pada data yang disetujui dan pertahankan baseline apabila lebih baik pada biaya kesalahan bisnis. Prototipe menyediakan review PPIC dan pilihan kalkulasi tanpa AI. Jalur tanpa AI memakai kontribusi tambahan nol. [Evaluasi](ai.md) · [Kalkulasi tanpa AI](../testing/sprint7_http_evidence.json)

**Apakah model melatih ulang otomatis?** Aplikasi memuat artefak versi tetap. Pelatihan, evaluasi, dan perubahan versi dijalankan secara eksplisit melalui perintah reproduksi. Feedback memperbarui nilai fitur jika tersedia. [Panduan Windows](windows.md) · [Artefak dan metadata](ai.md)

**Bagaimana jika histori kurang?** Jika satu lag wajib belum tersedia, request prediksi atau kalkulasi dengan AI dapat gagal dengan `422 INSUFFICIENT_HISTORY`. PPIC dapat memilih perhitungan BOM, safety, dan stok tanpa AI. Histori wajib berbeda dari bukti feedback opsional, yang memiliki fallback netral. [Kontrak API](api.md)

## IoT

**Bagaimana load cell bekerja?** Beban mengubah regangan elemen pengukur dan menghasilkan perubahan diferensial tegangan kecil. HX711 memperkuat serta mendigitalkan sinyal. ESP32 membaca hasil digital dan memakai offset tara serta faktor kalibrasi untuk mengetahui massa. [Wiring dan prosedur kalibrasi](../../firmware/esp32_scale/README.md)

**Mengapa memakai HX711?** Keluaran jembatan load cell memerlukan penguatan dan konversi yang sesuai dengan sinyal kecil. Modul HX711 menyediakan keduanya dengan antarmuka DOUT dan SCK. [Wiring](diagrams/08-iot.svg)

**Apa fungsi ESP32?** ESP32 membaca HX711, mengolah pembacaan stabil, menangani tara dan OLED, menyinkronkan waktu, serta mengirim telemetri melalui Wi-Fi. Firmware memisahkan sampling dan tampilan dari tugas komunikasi. [Firmware](../../firmware/esp32_scale/esp32_scale.ino)

**Bagaimana perangkat berkomunikasi dengan FastAPI?** Perangkat mengirim JSON berisi sensor, bahan, nilai, unit dan waktu UTC ke `POST /api/iot/telemetry` pada LAN dengan `X-Device-Key`. Registry mengikat identitas perangkat pada bahan. Server mengonversi gram ke kg dan menyimpan hasil validasi. [Kontrak telemetri](api.md)

**Mengapa timestamp wajib?** Waktu pengukuran membantu menolak paket yang tertunda, berasal dari masa depan, atau datang tidak berurutan, dan menjadi dasar umur stok. Firmware menunggu SNTP sebelum pengiriman. Backend membandingkan waktu pengukuran dengan waktu penerimaan dan pembacaan sah terakhir. [Kebijakan waktu](../../firmware/esp32_scale/README.md)

**Bagaimana pembacaan invalid ditolak?** Backend memeriksa autentikasi, pasangan sensor dan bahan, struktur, satuan, nilai hingga, nilai negatif, waktu, dan urutan. Paket valid pada umur tepat 300 detik dapat diterima. Umur 301 detik ditolak pada uji. Penolakan menjaga stok hasil pembacaan sah terakhir dan mencatat audit. [Bukti HTTP](../testing/sprint7_http_evidence.json)

**Bagaimana menentukan freshness?** Stok dengan pembacaan sah berumur hingga 60 menit berstatus FRESH. Stok yang lebih lama berstatus STALE dan meminta pemeriksaan PPIC. Stok yang belum tersedia memerlukan pengukuran atau penyiapan data yang valid. [Implementasi stok](../../ml/src/sikembang_backend/inventory.py)

**Bagaimana membedakan restock dan konsumsi?** Gunakan ledger penerimaan, transfer, retur, limbah, koreksi, serta produksi terkait, bersama pengukuran pembuka dan penutup. Penurunan massa dapat muncul dari transfer keluar atau limbah. Kenaikan dapat muncul dari restock. Feedback hanya memakai konsumsi yang dapat direkonsiliasi dan diatribusikan. [Aturan rekonsiliasi](ai.md)

**Apakah perangkat sudah menyediakan feedback historis fisik?** Bukti yang tersedia berasal dari replay sintetis. Verifikasi fisik memerlukan rangkaian aktif, pembacaan batas minggu yang diterima, ledger sesuai lokasi dan bahan, serta run referensi yang sesuai. Audit build lulus dan menemukan nol port COM pada tahap upload. [Verifikasi](verification.md)

**Apa yang terjadi saat Wi-Fi putus?** Sampling dan OLED tetap dikelola lokal. Firmware mengulang koneksi dengan backoff, menyinkronkan waktu ulang, lalu hanya mengirim kandidat yang masih valid. Selama koneksi terputus, stok backend dapat berubah menjadi STALE. Recovery fisik masih harus diperiksa pada perangkat. [Panduan perangkat](../../firmware/esp32_scale/README.md)

## Backend dan logika bisnis

**Bagaimana menghitung BOM?** Ambil revisi pesanan terkonfirmasi yang terlihat pada cutoff, pilih item acara yang relevan, kalikan porsi tiap menu dengan resep berversi, dan jumlahkan per bahan. Resep yang belum tersedia memunculkan galat. [Implementasi pesanan dan BOM](../../ml/src/sikembang_backend/orders.py)

**Bagaimana rumus pengadaan bersih?** `max(0, BOM terkonfirmasi + tambahan AI + safety stock − stok yang diketahui)`. Hitung dan simpan dalam unit kanonis. Contoh audit model untuk beras adalah `69 + 4,498 + 5 − 17,5 = 60,998 kg`. [Contoh HTTP](../testing/sprint7_http_evidence.json)

**Mengapa PPIC masih perlu validasi?** Stok usang, kebutuhan yang belum tercatat, dan galat model dapat memengaruhi kuantitas. PPIC menetapkan jumlah final, memeriksa peringatan, dan meninggalkan catatan serta jejak persetujuan. PFA membaca keputusan yang sudah dikirim. [Lifecycle](diagrams/07-lifecycle.svg)

**Apa yang terjadi saat PPIC menolak tambahan AI?** UI menyesuaikan kuantitas review item dan PPIC masih dapat menyunting hasil. Server menyimpan kuantitas akhir dan catatan terpisah dari rekomendasi awal. Bukti browser menunjukkan tindakan review berjalan di mode live. [Bukti browser](../testing/sprint7_browser_evidence.json)

**Apa yang terjadi saat persediaan melebihi kebutuhan?** Rekomendasi bahan dijepit ke nol. Jika seluruh kuantitas final nol setelah approval, daftar tetap tervalidasi dan pengiriman ditolak sebagai tidak ada pengadaan. PFA menerima baris akhir positif untuk daftar terkirim. [Lifecycle](diagrams/07-lifecycle.svg) · [Tes daftar](../../ml/tests/test_backend_shopping_lists.py)

**Bagaimana menangani revisi yang bertabrakan?** `PUT` membawa versi terakhir yang dibaca pemanggil. Hanya revisi berdasarkan versi aktif yang dapat memutakhirkan kepala order. Versi usang menghasilkan `409 VERSION_CONFLICT`; snapshot sebelumnya tetap tersedia dalam histori. [Bukti revisi](../testing/sprint7_http_evidence.json)

**Bagaimana daftar ganda dicegah?** Reservasi draf berjalan dalam transaksi dan database memberi batas unik pada periode. Pembuatan kedua mengembalikan `409 ACTIVE_LIST_EXISTS`. Batas periode tetap berlaku setelah daftar dikirim sehingga demo ulang yang membuat daftar perlu periode atau database uji terpisah. [Transaksi draf](../../ml/src/sikembang_backend/drafts.py)

**Mengapa stok usang boleh dipakai?** Stok yang diketahui memberi angka kerja untuk draf dengan peringatan. PPIC wajib memberi catatan sebelum menyetujui item dengan peringatan stok. Paket telemetri tertunda diperlakukan melalui aturan usia paket, dan stok tanpa angka menjalankan jalur galat. [Perilaku stok dan approval](api.md)

**Bagaimana memastikan peran ditegakkan?** UI membaca identitas `/me`, dan backend memeriksa token, pengguna aktif serta peran route. DEVICE memakai kredensial registry. SYSTEM internal memiliki otoritas aplikasi, dengan jalur HTTP opsional dan kredensial berbeda. Percobaan role header palsu dan penggunaan kunci DEVICE untuk SYSTEM ditolak. [Autentikasi](../../ml/src/sikembang_backend/auth.py) · [Bukti](verification.md)

## Evaluasi, keterbatasan, dan pertanyaan lanjutan

**Data mana yang nyata dan apakah model sudah divalidasi dengan data transaksi perusahaan?** Kategori layanan berasal dari referensi publik. Pesanan pelatihan, resep, dan feedback adalah fixture sintetis. Order dan keputusan dalam audit demo merupakan input pengujian. Validasi akurasi pada transaksi perusahaan belum dilakukan. [Profil SonoKembang](https://sonokembangmalang.com/) · [Provenance](ai.md)

**Uji mana yang otomatis dan bagaimana memeriksa hasilnya?** Pytest mencakup backend, data, model, dan integrasi. Vitest mencakup frontend. Runner HTTP dan Chrome menguji deployment lokal. Host C++ menguji kebijakan firmware dan Arduino CLI mengompilasi target. Sprint 7 mencatat 405 Pytest, 34 Vitest, 38 respons HTTP dan 20 respons live browser. [Hasil dan perintah](verification.md)

**Uji perangkat fisik mana yang sudah selesai?** Audit telah membaca firmware, menjalankan sembilan kelompok tes host, dan mengompilasi target ESP32. Upload, kalibrasi, pengukuran massa, Wi-Fi dan dashboard fisik masih BLOCKED. Bukti telemetry yang masuk ke backend dan PPIC berasal dari perangkat terdaftar sebagai sumber sintetis. [Status hardware](verification.md)

**Apa yang masih disimulasikan?** Data transaksi, sebagian resep, histori feedback, dan paket timbang demo disiapkan melalui fixture atau simulator. PFA menerima status dan jumlah melalui aplikasi. Transaksi pembelian serta proses fisik setelah handoff berada di luar lingkup. [Provenance](report-material.md) · [Demo](demo.md)

**Apa batas prototipe yang paling berpengaruh?** Belum ada validasi model pada perusahaan, data katalog terbatas, kalender berakhir pada 2026, revisi Marketing masih melalui API, dan telemetri fisik belum terverifikasi. Penerapan produksi membutuhkan data yang disepakati, kalibrasi lapangan, kebijakan kredensial dan komunikasi, serta uji operasional. [Batas dan tindak lanjut](report-material.md#keterbatasan-dan-pengembangan-lanjutan)

**Apakah kenaikan 2,20% membenarkan penggunaan model?** Angka tersebut merupakan perbaikan relatif MAE ternormalisasi atas median historis dalam test sintetis. Seluruh RMSE bahan turun, tetapi MAE santan naik. Keputusan deployment memerlukan evaluasi permintaan nyata, biaya kekurangan atau surplus, dan stabilitas terhadap perubahan pola. [Metrik](../testing/sprint7_ml_evidence.json)

**Apakah `prev_error_adj` terbukti meningkatkan akurasi?** Pada validation, MAE ternormalisasi 0,080872 dengan fitur dan 0,080740 tanpa fitur. Uji membuktikan jalur integrasi koreksi, dengan bukti peningkatan akurasi yang belum tersedia. Pada replay beras, koreksi +9,792 kg tercatat, dan keluaran 14,638 kg sama dengan varian netral pada contoh itu. [Ablation](evidence/evaluation/06-feedback-ablation.png) · [Replay](evidence/evaluation/feedback-replay.json)

**Apa yang terjadi dengan database jika model gagal setelah kalkulasi dimulai?** Jalur dengan AI mengembalikan galat dan transaksi dibatalkan, sehingga run dan draf tidak tersimpan sebagian. Jalur `include_forecast=false` tetap dapat dipakai jika data BOM dan stok tersedia. [Tes rollback](../../ml/tests/test_backend_procurement.py)

**Apakah tanggal setelah 2026 dapat dipakai?** Kalender artefak saat ini berakhir pada 2026 dan dapat menolak minggu yang melintasi rentang, termasuk 2026-W53 yang berakhir pada 2027. Jalankan demo pada cutoff fixture yang terdokumentasi. Perpanjangan membutuhkan kalender, histori, dan pemeriksaan kompatibilitas. [Reproduksi](windows.md)

**Bagaimana membuktikan alur browser memakai FastAPI secara langsung?** Runner Chrome menggunakan Vite preview live, mencatat 20 respons API dari backend, dan mencatat nol respons dari service worker. Bukti database dan pembacaan setelah restart melengkapi jejak tersebut. [Bukti browser](../testing/sprint7_browser_evidence.json) · [Bukti HTTP](../testing/sprint7_http_evidence.json)

**Mengapa tidak menyatakan semua TC D2 lulus berdasarkan bukti?** PPT D2 memuat kelompok TC dan merujuk Tabel 11.1. Dokumen yang tersedia belum memperlihatkan definisi per ID. Status PASS diberikan kepada skenario yang benar-benar dijalankan dan ketepatan pemetaan individual tetap BLOCKED sampai kelompok memperoleh tabel. [Keterlacakan](traceability.md)
