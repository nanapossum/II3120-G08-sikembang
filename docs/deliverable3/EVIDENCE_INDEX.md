# Indeks bukti Deliverable 3

Gunakan SVG untuk diagram yang dapat diperbesar dan PNG untuk gambar eksperimen dan antarmuka. Pilih caption dan konteks dari [draf laporan](report-material.md) atau [materi PPT](ppt-material.md). Nomor D3 berikut merujuk urutan yang diusulkan untuk kontribusi ini.

## Diagram sistem dan implementasi

Seluruh visual berasal dari source code dan kontrak yang diselaraskan dengan implementasi Sprint 7. Sumber Mermaid dan rendisi dipasangkan agar mudah diperbarui.

| Artefak | Tujuan dan sumber | Laporan · PPT | Status |
|---|---|---|---|
| [Arsitektur keseluruhan SVG](diagrams/01-system.svg) · [Mermaid](diagrams/01-system.mmd) | Peran, frontend, lima batas FastAPI, SQLite, model, dan perangkat/simulator | Arsitektur · D3-01 | Siap |
| [Komponen backend SVG](diagrams/02-backend.svg) · [Mermaid](diagrams/02-backend.mmd) | Router/auth, layanan, adapter DB, artefak dan feedback. Sumber factory dan modul backend | Implementasi backend · D3-02 | Siap |
| [Pipeline training SVG](diagrams/03-training.svg) · [Mermaid](diagrams/03-training.mmd) | Histori, fitur, split, baseline, XGBoost, dan evaluasi | Dataset dan pelatihan · D3-03 | Siap |
| [Pipeline inferensi SVG](diagrams/04-inference.svg) · [Mermaid](diagrams/04-inference.mmd) | Forecast request, snapshot, lag, musim, cutoff, dan respons | Implementasi AI · D3-03 | Siap |
| [Feedback AI–IoT SVG](diagrams/05-feedback.svg) · [Mermaid](diagrams/05-feedback.mmd) | Jalur pengurangan stok kini dan jalur feedback historis tersegel | Feedback dan pengadaan · D3-06 | Siap |
| [Sequence E2E SVG](diagrams/06-sequence.svg) · [Mermaid](diagrams/06-sequence.mmd) | Interaksi order, perangkat, inferensi, review dan PFA | Alur prototipe · D3-08 | Siap |
| [Lifecycle daftar SVG](diagrams/07-lifecycle.svg) · [Mermaid](diagrams/07-lifecycle.mmd) | DRAFT, review, kirim, aturan no-procurement dan konflik | Lifecycle · D3-07 | Siap |
| [Wiring dan komunikasi SVG](diagrams/08-iot.svg) · [Mermaid](diagrams/08-iot.mmd) | Pin asli, alur ESP32 dan REST. Sumber firmware terintegrasi | IoT · D3-05 | Siap sebagai diagram wiring |
| [ERD SVG](diagrams/09-erd.svg) · [Mermaid](diagrams/09-erd.mmd) | 16 entitas audit dari ORM dan SQLite. Perbesar pada laporan untuk membaca atribut | Database · D3-02 atau lampiran | Siap |
| [Alur pengguna SVG](diagrams/10-user-flow.svg) · [Mermaid](diagrams/10-user-flow.mmd) | Langkah UI per role, status dan koneksi dengan REST | Integrasi frontend · D3-07/08 | Siap |

Rendisi dapat dibuat ulang dengan Mermaid CLI 11.12.0, Chrome yang terpasang, dan [tema lokal](diagrams/theme.json). Pada Windows lokal, instalasi ini dipisahkan dari dependensi frontend. Gunakan path executable Chrome aktual ketika membentuk konfigurasi Puppeteer.

```powershell
$env:PUPPETEER_SKIP_DOWNLOAD = 'true'
npm.cmd install --prefix ml/runtime/sprint8/mermaid --no-save --no-package-lock --no-audit --no-fund @mermaid-js/mermaid-cli@11.12.0
@{ executablePath = 'C:/Program Files/Google/Chrome/Application/chrome.exe'; headless = $true } |
    ConvertTo-Json | Set-Content -Encoding ASCII ml/runtime/sprint8/puppeteer.json
$mmdc = 'ml/runtime/sprint8/mermaid/node_modules/.bin/mmdc.cmd'
foreach ($source in (Get-ChildItem docs/deliverable3/diagrams -Filter '*.mmd' | Sort-Object Name)) {
    $target = [IO.Path]::ChangeExtension($source.FullName, '.svg')
    & $mmdc -i $source.FullName -o $target -c docs/deliverable3/diagrams/theme.json -p ml/runtime/sprint8/puppeteer.json -b white
    if ($LASTEXITCODE -ne 0) { throw "Render gagal untuk $($source.Name)" }
}
```

[Dokumentasi Mermaid CLI](https://github.com/mermaid-js/mermaid-cli) · [Pemeriksaan geometri label di Chrome](evidence/diagram-check.json)

## Grafik evaluasi dan distribusi

Grafik 01–06 merupakan salinan byte-identik dari regenerasi Sprint 7 dengan model yang disimpan. Grafik 07 dibuat dari train split sintetis. Jaga label kg, liter atau butir pada potongan grafik.

| Artefak | Tujuan dan sumber | Laporan · PPT | Status |
|---|---|---|---|
| [01 Aktual vs prediksi](evidence/evaluation/01-actual-vs-predicted.png) | Pair aktual/prediksi dari test chronologis | Evaluasi · D3-04 pendukung | Siap |
| [02 MAE per bahan](evidence/evaluation/02-mae.png) | Nol, median, dan XGBoost pada sampel test yang sama | Evaluasi · D3-04 | Siap |
| [03 RMSE per bahan](evidence/evaluation/03-rmse.png) | Perbandingan error kuadrat dengan unit per bahan | Evaluasi · D3-04 | Siap |
| [04 Distribusi residual](evidence/evaluation/04-residuals.png) | Pola residual aktual dari test | Evaluasi · D3-04 pendukung | Siap |
| [05 Feature importance](evidence/evaluation/05-feature-importance.png) | Gain fitur dari model native | Evaluasi · D3-04 pendukung | Siap |
| [06 Ablation feedback](evidence/evaluation/06-feedback-ablation.png) | Perbandingan validation dengan dan tanpa feedback | Feedback · D3-04/06 | Siap |
| [07 Distribusi sintetis](evidence/evaluation/07-synthetic-distributions.png) | Distribusi target dari train saja | Dataset · D3-03 | Siap |
| [Ringkasan terukur dan checksum](../testing/sprint7_ml_evidence.json) | Audit dataset dan model, metrik aktual serta enam grafik | Dataset/evaluasi · D3-03/04 | PASS sintetis |
| [Replay feedback](evidence/evaluation/feedback-replay.json) | Respons ASGI 201 dari fixture historis dan pembanding netral | AI–IoT · D3-06 | PASS simulasi |

[Skrip audit eksperimen](../testing/sprint7_verify_ml.py) · [Plot train split](evidence/evaluation/plot_synthetic_distributions.py) · [Kamus fitur dan provenance](ai.md)

## API, pengujian, dan potret prototipe

| Artefak | Tujuan dan sumber | Laporan · PPT | Status |
|---|---|---|---|
| [Kamus data dan constraint](database.md) | PK, FK, tipe, nullability, transaksi, dan sumber data | Database · D3-02 | Siap |
| [Tabel API dan contoh](api.md) | 11 operasi bisnis dengan contoh dari receipt tersanitasi | REST · D3-02 | Siap |
| [Run HTTP dan SQLite](../testing/sprint7_http_evidence.json) | Forecast actual, kontrak, 37,5 kg fixture, 17,5 kg simulasi, perbandingan stok ±3 kg, lifecycle, restart | Hasil uji · D3-06/08 | PASS simulasi |
| [Run browser](../testing/sprint7_browser_evidence.json) | 20 respons live dari FastAPI, alur role, pemeriksaan mock MSW | Integrasi frontend · D3-07/08 | PASS |
| [Planning PPIC](evidence/screenshots/01-ppic-planning.png) | Screenshot Chrome backend live dengan stok 21,5 kg dari simulator | Prototipe · D3-06 | Siap · simulasi |
| [Review PPIC](evidence/screenshots/02-ppic-review.png) | Draf aktual, peringatan stok, alur edit/reject sebelum send | Prototipe · D3-07 | Siap · simulasi |
| [Handoff PFA](evidence/screenshots/03-pfa-handoff.png) | Kuantitas akhir 42,25 kg teramati pada run Chrome | Prototipe · D3-07 | Siap · simulasi |
| [Smoke Windows](evidence/windows-smoke.json) | CLI normal dan harness, Swagger 200, prediksi dan telemetry 201 pada database lokal baru | Reproduksi · D3-08 pendukung | PASS |
| [Build firmware dan port serial](evidence/firmware-build.json) | Arduino CLI build dan host tests. Arduino CLI dan Windows mendeteksi nol port serial | IoT · D3-05 | PASS build · BLOCKED fisik |
| [Ringkasan perintah dan tes](../testing/sprint7_test_results.txt) · [Matriks verifikasi](verification.md) | 405 Pytest, 34 Vitest, lint/build, regresi dan batas data | Pengujian · D3-08 | Siap |
| [Pemetaan D2](traceability.md) | F3/F4, BPMN, SoaML, API, DB, UI, dan skenario aktual | Traceability · D3-08/lampiran | Siap · TC individual menunggu Tabel 11.1 |
| [Checklist capture](demo.md#checklist-screenshot) | Langkah memperoleh foto/OLED, jejak fisik dan potret tambahan | Prototipe/IoT · D3-05/08 | Capture fisik menunggu perangkat |

Foto perangkat, OLED, dan dashboard dengan pembacaan fisik memerlukan verifikasi perangkat terlebih dahulu. Potret simulasi pada paket ini tetap diberi label simulasi pada laporan dan PPT. [Putusan handoff](handoff.md)
