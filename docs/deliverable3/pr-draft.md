# Draf pull request SiKembang

**Judul**  
`feat: implement SiKembang backend, predictive AI and IoT integration`

**Branch**  
`feat/ai-forecast` → `dev`

## Summary

```text
React Marketing → order/revisi → SQLite
ESP32 atau simulator → telemetry → stok dan audit
PPIC → kalkulasi [BOM + XGBoost + safety stock − stok] → DRAFT
PPIC → review → VALIDATED_BY_PPIC → SENT_TO_PFA → PFA
```

- Satu FastAPI modular monolith memuat OrderService, InventoryIoTService, AIForecastService, ProcurementCalcService, dan ShoppingListService. SQLite menyimpan revisi, stok, log telemetry, forecast run, serta keputusan PPIC.
- Sebelas operasi bisnis mencakup POST/PUT/GET order, POST telemetry, GET stok, POST predict, POST kalkulasi, dan POST/GET draf/list serta PATCH approve dan POST send. Otorisasi dashboard memakai JWT, perangkat memakai kunci terikat registry, dan SYSTEM HTTP bersifat opt-in.
- Model native `xgb-v1-f9a770b940f71fc8` memakai 18 fitur dari histori, musim, kebutuhan terkonfirmasi, dan feedback historis rekonsiliasi. Feedback tersedia sebelum cutoff dan digunakan sebagai fitur sekali. Intake memeriksa target, transformasi, checksum, dan versi.
- Frontend React live memakai adapter API dan mempertahankan mode mock MSW. PPIC tetap mengontrol kuantitas akhir serta catatan stok usang. PFA menerima jumlah positif.
- Firmware ESP32 membaca HX711, menampilkan OLED, menyimpan tare, serta mengirim pembacaan stabil berwaktu UTC melalui Wi-Fi. Panduan membedakan jalur perangkat dan simulator.

## Evidence

- **Sebelum hardening** · Approval menolak unit kompatibel, audit PPIC menyaring keputusan nol, dan kredensial SYSTEM bisa bertabrakan dengan registry perangkat.
- **Sesudah hardening** · Regresi lulus. Pytest 405 lulus, Vitest 34 lulus, lint/build lulus, C++ host 9 kelompok lulus, Arduino CLI build exit 0. Run HTTP mencatat 38 respons, 11 operasi, integritas SQLite serta pembacaan setelah restart. Chrome mencatat 20 respons API live dari backend.
- **ML** · Test sintetis 3.640 prediksi ulang persis. MAE ternormalisasi 0,073093, median 0,074741 dan baseline nol 0,145075. Ablation validation memberi 0,080872 dengan feedback dan 0,080740 tanpa feedback. [Metrik dan bukti](ai.md)
- **IoT** · Build lolos. Upload, kalibrasi dan telemetry fisik tertunda karena 0 port COM terdeteksi. Input simulator uji 17.500 g disimpan sebagai 17,5 kg. Rekomendasi aktual beras bertambah 3 kg pada database pembanding. [Hasil pengujian](verification.md)
- **Provenance** · Order historis, resep representatif, stok awal, feedback replay dan pengukuran simulator bersumber sintetis. Prediksi berasal dari inferensi XGBoost aktual atas fixture demo. [Indeks bukti](EVIDENCE_INDEX.md)

## Merge Danger

| Aspek | Penilaian |
|---|---|
| Door | Two-way untuk source branch. Simpan database pengguna secara terpisah ketika menjalankan inisialisasi schema baru |
| Blast radius | Backend dan integrasi frontend. Flow penting yang perlu dipastikan saat review adalah proxy live, role gates, lifecycle dan checksum artefak |
| Batas | Revisi via REST, belum ada form edit Marketing. Kalender aktif berhenti pada 2026. Bukti fisik dan rekonsiliasi riwayat fisik belum tersedia |

## Reproduction

Gunakan Python 3.13, venv bersih dan lockfile. Siapkan `manifest.json` dan `model.ubj` kompatibel, environment lokal serta SQLite baru. Jalankan `sikembang_backend.manage init-db`, `seed`, factory FastAPI lalu Vite mode live. Runner HTTP memakai database terisolasi dan cutoff `2026-11-27T12:00:00+07:00`. [Langkah Windows](windows.md) · [Skrip demo](demo.md) · [Traceability](traceability.md)
