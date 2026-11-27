# Demonstrasi D3 dan checklist bukti

Rencana 7–9 menit. Gunakan React live dan FastAPI yang menulis ke SQLite. Tulis sumber stok yang sedang dipakai pada slide atau layar pembuka. Untuk demo yang telah diuji, labelnya **backend live · telemetry simulasi**.

## Persiapan

- Siapkan dua terminal menjalankan backend dan Vite dengan [panduan Windows](windows.md). Pastikan `/api/health` menampilkan `database=ok` dan versi XGBoost `xgb-v1-f9a770b940f71fc8`.
- Siapkan login lokal Marketing, PPIC, dan PFA. Buka Swagger di `http://127.0.0.1:8000/docs` dan frontend di `http://127.0.0.1:5173`.
- Catat periode ISO yang dicetak seed. Gunakan database demo baru jika periode itu sudah memiliki daftar. Siapkan database lain untuk perbandingan stok atau pilihan tanpa AI. Pertahankan database yang sama untuk uji restart.
- Jika skala sudah dikalibrasi dan lulus pemeriksaan manual, pilih jalur fisik. Uji Sprint 7 mendeteksi nol port COM. Mode fallback yang terverifikasi adalah simulator eksternal ke FastAPI. [Panduan perangkat](../../firmware/esp32_scale/README.md)

## Alur presentasi

| Bagian | Tindakan di layar | Narasi dan tanda berhasil |
|---|---|---|
| 0:00–0:45 | Tampilkan arsitektur singkat dan health. | “Pesanan, stok, dan forecast bertemu pada satu alur pengadaan. Sumber stok pada demo ini adalah simulator.” Health menampilkan versi model. |
| 0:45–2:00 | Masuk sebagai Marketing, pilih kategori, tanggal acara dalam periode, menu, porsi dan lokasi. Kirim, lalu catat ID order. | Order terkonfirmasi tersimpan. Versi awal 1. Sebutkan bahwa revisi versi tersedia lewat REST. |
| 2:00–2:45 | Kirim nilai stabil secara fisik atau jalankan klien simulator sesuai mode terpilih. Masuk PPIC dan buka planning. | Paket simulasi 17.500 g menjadi 17,5 kg dan stok tampil segar. Pastikan kredensial, SSID dan Serial tidak terlihat di proyektor. |
| 2:45–4:15 | Tunjukkan order dan stok, pertahankan opsi AI, klik hitung. Bila perlu tampilkan respons predict beras dari terminal terpisah. | XGBoost memberi kebutuhan tambahan dari lag dan fitur kalender/bukti sebelumnya. Kalkulasi menambah BOM dan safety stock serta mengurangi stok. Sistem menyimpan satu DRAFT untuk periode. |
| 4:15–5:45 | Buka review. Ubah satu kuantitas, tolak tambahan AI untuk satu bahan, lalu isi catatan bagi stok usang. Klik **Setujui dan kirim ke PFA**. | Tindakan PPIC tersimpan pada approval. Tombol memanggil approval dan send secara berurutan. Jika send gagal setelah approval, ulangi tindakan kirim yang tersedia. |
| 5:45–6:30 | Masuk PFA dan buka permintaan bahan. | Daftar SENT_TO_PFA menampilkan kuantitas akhir positif beserta unit. |
| 6:30–8:00 | Tampilkan bukti model dan tes. Opsional restart backend, lalu refresh daftar PFA. | SQLite mempertahankan order dan daftar. Jelaskan batas data sintetis, ablation, dan status peralatan fisik. |

Bila penguji meminta angka pembanding, pakai dua fixture 2026-W48 yang sudah dijalankan. BOM 69 kg, AI aktual 4,498 kg, dan safety 5 kg sama. Stok turun 20,5→17,5 kg dan rekomendasi naik 57,998→60,998 kg. Itu bukti dua database terpisah. Contoh 37,5 kg D2 adalah fixture aritmetika. [Perbandingan aktual](../testing/sprint7_http_evidence.json) · [Metrik model](ai.md)

### Telemetry simulasi ke backend live

Jalankan dari root repo dengan backend loopback dan registry seed. `SNS-GDG-01` terikat ke `ING-001`. Perintah memakai kunci pada file environment lokal. Buka tampilan PPIC setelah HTTP 201. Hindari paket simulasi beras bersamaan dengan demo timbangan fisik untuk bahan yang sama.

```powershell
. .\ml\runtime\backend.env.ps1
$reading = @{
    sensor_id = 'SNS-GDG-01'
    ingredient_id = 'ING-001'
    measured_weight = 17500
    unit = 'g'
    recorded_at = [DateTimeOffset]::UtcNow.AddSeconds(-1).ToString('o')
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/iot/telemetry' `
    -Headers @{'X-Device-Key'=$env:SIKEMBANG_DEVICE_RICE_KEY} `
    -ContentType 'application/json' -Body $reading
```

Jika backend sudah dipasang untuk perangkat fisik, ganti URL loopback dengan alamat IP laptop yang dipakai listener. Simulator web pada mode mock cocok untuk menunjukkan UI ketika backend sedang dipulihkan. Tampilkan label **web mock · MSW** saat berpindah.

## Selingan teknis yang aman

- **Swagger dan forecast.** Tampilkan daftar endpoint dan respons 201 versi model. Jalankan POST prediksi dengan [contoh login PPIC](windows.md#4-health-swagger-dan-prediksi-aktual). Arahkan perhatian ke `target_period`, `season_flags`, `predicted_demand`, dan `prev_error_adj`.
- **Konflik order.** Gunakan order latihan dan payload PUT pada [dokumen REST](api.md). Lakukan revisi sekali, lalu ulangi dengan nomor versi lama untuk 409 VERSION_CONFLICT. Nilai output itu cocok dengan bukti Sprint 7.
- **Validasi telemetry.** Gunakan paket uji dengan bobot negatif ketika diminta. API memberi 422 NEGATIVE_VALUE dan stok valid tetap terbaca. Bukti mencakup paket terlalu lama dan mismatch sensor/bahan.
- **Riwayat kurang dan no-AI.** Pakai hasil runner terisolasi. Perlihatkan 422 INSUFFICIENT_HISTORY pada fixture yang kehilangan lag. Untuk jalur tanpa AI, matikan opsi AI lalu kalkulasi pada database yang belum memiliki daftar untuk periode itu.
- **Persistensi.** Hentikan Uvicorn setelah daftar terkirim. Mulai lagi dengan path dan konfigurasi yang sama. Masuk atau refresh PFA. Runner mencatat pembacaan daftar dan revisi order setelah restart. [Payload serta respons tersanitasi](../testing/sprint7_http_evidence.json)

## Kontingensi

| Gejala | Pemeriksaan dan pemulihan |
|---|---|
| FastAPI gagal mulai | Pastikan terminal di root, gunakan Python venv, jalankan `pip check`, cek env JWT, jalankan `init-db` pada path demo yang sesuai, lalu mulai kembali. Bila port 8000 terpakai, pilih port bebas dan sesuaikan URL serta Vite proxy. |
| Bundle model hilang | Cocokkan path `SIKEMBANG_ARTIFACT`, `manifest.json`, `model.ubj`, checksum dan `/api/health`. Gunakan paket model kompatibel dari pemilik. Jika belum tersedia, tunjukkan kalkulasi no-AI dengan label yang sesuai dan gunakan hasil XGBoost tersimpan untuk menjelaskan evaluasi. |
| SQLite tidak siap atau seed bertabrakan | Gunakan path yang dapat ditulis dan `init-db` sebelum `seed`. Jika seed existing membutuhkan sandi berbeda, gunakan konfigurasi asal atau database demo baru. |
| Frontend gagal mencapai API | Pastikan Vite live, base URL `/api`, dan `VITE_DEV_PROXY_TARGET` mengarah ke listener FastAPI. Restart Vite setelah perubahan env dan cek Network tab. |
| ESP32 atau COM tidak muncul | Cek kabel data, chipset USB kit, port dan board. Jika tetap tidak siap, gunakan simulator eksternal ke FastAPI. |
| NTP gagal atau timestamp ditolak | Pastikan jam laptop akurat, ESP32 dapat mencapai DNS dan NTP UDP 123, atau gunakan server NTP lokal tepercaya. Tunggu indikator jam UTC siap setelah reconnect. |
| Kunci perangkat tidak cocok | Cocokkan registry, identitas sensor, bahan dan credential pada `secrets.h` lokal. Periksa status 401 atau 422. Pertahankan kunci khusus per sensor. |
| Inferensi tidak punya histori | Tunjukkan kode 422. Mulai ulang skenario dengan database yang diseed untuk periode dan cutoff yang sama, atau pilih mode no-AI secara eksplisit. |
| Kalibrasi menyimpang | Tare pada platform kosong, verifikasi massa referensi dan kapasitas, ukur ulang sebelum memilih mode fisik. Gunakan mode simulator ketika validasi massa tertunda. |
| AP mengisolasi klien | Sambungkan pada LAN tepercaya yang mengizinkan komunikasi laptop–ESP32, verifikasi IP dan firewall per perangkat. Gunakan loopback plus simulator jika akses fisik tidak bisa dipulihkan. |
| `ACTIVE_LIST_EXISTS` | Buka daftar yang sudah tersimpan pada periode itu. Untuk mengulang kalkulasi atau membandingkan hasil, mulai skenario di database yang berbeda. |

## Checklist screenshot

Potret terverifikasi berasal dari Chrome mode live dengan data sintetis dan telemetry simulator. Gunakan nama dan caption berikut pada materi kelompok.

| Potret | Status | Tindakan capture bila perlu |
|---|---|---|
| Planning PPIC | Tersedia | Masuk PPIC setelah order dan telemetry, tampilkan periode, stok 21,5 kg Segar, dan opsi forecast. [PNG](evidence/screenshots/01-ppic-planning.png) |
| Review PPIC | Tersedia | Buka DRAFT dengan kolom BOM, AI, safety, stok, dan net. Tampilkan catatan stale dan keputusan PPIC pada layar. [PNG](evidence/screenshots/02-ppic-review.png) |
| Handoff PFA | Tersedia | Buka daftar terkirim setelah login PFA. Perlihatkan kuantitas final positif dan unit tanpa membuka data login. [PNG](evidence/screenshots/03-pfa-handoff.png) |
| Marketing dan Swagger | Capture tambahan opsional | Foto form order berisi entri demo sebelum kirim. Ambil tangkapan response 201 prediksi yang telah menutup header otorisasi. |
| Foto rakitan, OLED dan response fisik | Capture manual setelah kalibrasi | Tunjukkan papan, angka OLED, massa referensi dan potret stok yang berubah. Cocokkan timestamp dengan log ACCEPTED berprovenance `physical`. |
| Mode mock | Capture tambahan opsional | Jika disertakan, tampilkan pemilih peran dan label MSW. Gunakan caption mode mock terpisah. |
