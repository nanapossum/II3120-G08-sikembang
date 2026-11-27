# Status handoff dan Definition of Done

## Snapshot repository

Audit menggunakan `feat/ai-forecast` pada commit lokal `ac5b405` untuk implementasi dan pengujian Sprint 7. GitHub menampilkan `origin/feat/ai-forecast=e869edf` dan `origin/dev=1a775ca`. Sebelum paket Sprint 8 ditulis, kontribusi lokal terhadap `origin/dev` berisi 10 commit dan 109 berkas. GitHub API tidak mengembalikan PR terbuka dari `feat/ai-forecast` atau `feat/rafif-ai-forecast` ke `dev` saat pemeriksaan. Draf untuk review tim tersedia lokal. [Usulan PR](pr-draft.md)

| Bagian | Isi yang dibagikan |
|---|---|
| Kode | Aplikasi React, FastAPI dan fixture, konfigurasi contoh, pengujian, serta firmware tanpa kunci |
| Dokumen dan bukti | Panduan repo, SVG/Mermaid, potret browser simulasi, grafik evaluasi, dan JSON yang sudah disanitasi |
| Artefak model | `model.ubj` 90.820 byte dan `manifest.json` 12.670 byte. Model dan manifest disediakan sebagai paket lokal terpisah, atau dapat direproduksi dari generator/training |
| Data tergenerasi | `ml/generated/synthetic-v1/` dapat direproduksi dengan seed 3120. Raw history, CSV split dan cache runtime dikecualikan Git |
| Data lokal | SQLite, env lokal, venv, `secrets.h` dan berkas konteks privat berada di luar paket repo |

Periksa `git status --short --branch`, `git diff --check`, dan `git diff --stat origin/dev...HEAD` saat tim meninjau. Cocokkan model yang dibagikan dengan manifest dan `/api/health`. [Runbook](windows.md) · [Bukti model](../testing/sprint7_ml_evidence.json)

## Definition of Done

| Kriteria | Status |
|---|---|
| Referensi arsitektur dan 11 endpoint, ERD dan data dictionary | Selesai untuk implementasi yang diaudit |
| Instruksi Windows, loopback, setup model, dan jalur simulator | Selesai. Seed, Swagger, predict, dan telemetry diperiksa pada database terisolasi |
| XGBoost terlatih, data sintetis reproducible, grafik dan feedback | Selesai untuk data sintetis |
| Alur Marketing → PPIC → PFA dan persistence | PASS pada backend live dan telemetry simulasi |
| Firmware dan integrasi perangkat | Build PASS. Upload, kalibrasi dan telemetry fisik menunggu perangkat |
| Materi laporan, 8 slide siap salin, Q&A, bukti dan kontingensi | Selesai sebagai paket untuk digabungkan ke dokumen kelompok |
| Mapping TC D2 individual | Menunggu salinan Tabel 11.1. Kelompok TC dan skenario terverifikasi sudah dicatat |
| Draf PR menuju `dev` | Siap direview lokal. Remote membawa baseline Sprint 6E |

## Batas operasional

- Dataset, BOM representatif, stok seed dan feedback replay bersumber sintetis. Skor test mengukur fixture tersebut. Akurasi pada transaksi operasional memerlukan data dan evaluasi perusahaan.
- Jalur fisik masih membutuhkan board terdeteksi, kalibrasi, LAN/Wi-Fi/NTP, dan pembacaan sensor sampai PPIC. Ledger fisik mingguan memerlukan pemisahan restock, konsumsi dan pergerakan lain, persetujuan serta run referensi yang tepat.
- Kalender artefak mencakup 2020–2026. Target 2026-W53 sudah melintasi 2027 dan menghasilkan 500 INTERNAL_ERROR. Periode berikutnya memerlukan bundle kalender dan artefak yang kompatibel. Fallback demo memanfaatkan periode audit tetap atau no-AI.
- Revisi versi tersedia di API. Form Marketing saat ini membuat order, dengan menu statis. PFA menerima daftar permintaan bahan. Pembelian pemasok, pembayaran, produksi dan pengiriman berada di luar cakupan prototipe.

## Tindakan tim

1. Penanggung jawab backend memeriksa satu checkout tim yang telah menerima baseline hardening dan paket D3. Bagikan arsip model kompatibel lewat kanal tim dan pakai database demo baru.
2. Penanggung jawab hardware menjalankan checklist fisik dan mencatat port, faktor kalibrasi, massa rujukan, waktu, sumber, status HTTP dan tampilan PPIC. Gunakan simulator pada demo jika bukti fisik belum lengkap.
3. Penulis laporan memasukkan ringkasan hasil, gambar serta caption dari indeks. Cocokkan bab final dengan format kelompok. Bila Tabel 11.1 tersedia, lengkapi mapping individual termasuk TC-08/09.
4. Presenter menempelkan materi ke PPT kelompok, menguji ukuran SVG/PNG dalam layout aktual, dan melatih alur termasuk fallback. Labeli potret frontend sebagai backend live dengan telemetry simulasi.
5. Pemilik branch meninjau diff dengan anggota tim dan menyiapkan publikasi sesuai persetujuan kelompok. [Materi laporan](report-material.md) · [Materi PPT](ppt-material.md) · [Indeks bukti](EVIDENCE_INDEX.md) · [Checklist demo](demo.md)
