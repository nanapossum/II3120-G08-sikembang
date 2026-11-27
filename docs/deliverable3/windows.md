# Menjalankan SiKembang pada Windows

Panduan untuk PowerShell dari root repository. Lingkungan audit memakai Python 3.13.2 dan Node.js 24.19.0 dengan npm 11.17.0. Backend berjalan di loopback selama demo simulator. Dua terminal cukup untuk backend dan frontend. Terminal ketiga dipakai untuk request uji atau Serial Monitor.

## 1. Checkout dan environment

```powershell
git clone --branch feat/ai-forecast --single-branch https://github.com/nanapossum/II3120-G08-sikembang.git
Set-Location II3120-G08-sikembang
git branch --show-current
git log -1 --oneline
py -3.13 --version
node --version
npm.cmd --version
```

Clone dan checkout branch remote diverifikasi di direktori terpisah. Pada audit handoff, remote masih di `e869edf`. Baseline yang dipakai dokumen ini adalah `ac5b405`, commit hardening Sprint 7 yang tersedia di checkout pemilik. Jika log clone masih menunjukkan `e869edf`, minta pemilik menyediakan snapshot yang memuat `ac5b405` dan paket Sprint 8 melalui jalur tim. Contoh API versi terbaru mengikuti snapshot tersebut.

```powershell
py -3.13 -m venv ml/.venv
. .\ml\.venv\Scripts\Activate.ps1
$python = (Resolve-Path .\ml\.venv\Scripts\python.exe).Path
& $python -m pip install -r ml/requirements-dev.lock
& $python -m pip install --no-build-isolation --no-deps -e ml
& $python -m pip check
```

Buat venv tanpa mewarisi paket global. Jika kebijakan PowerShell memblokir aktivasi, jalankan langkah mulai `$python` dengan path eksplisit yang sama. Instalasi lockfile, package editable, dan pemeriksaan dependensi lulus pada venv bersih Sprint 7.

## 2. Artefak model untuk run normal

Gunakan paket artefak dari pemilik model di `ml/artifacts/xgb-v1-f9a770b940f71fc8/`. Loader memerlukan setidaknya `manifest.json` dan `model.ubj`. Folder ini dikecualikan Git. Untuk mengecek paket, gunakan hash manifest dan model seperti di bukti ML, lalu cocokkan respons health saat FastAPI berjalan. Histori empat minggu yang dibutuhkan demo normal dibuat oleh seed. Bundle replay dipakai untuk reproduksi data dan evaluasi.

```powershell
$modelDir = 'ml/artifacts/xgb-v1-f9a770b940f71fc8'
if (-not (Test-Path -LiteralPath $modelDir)) {
    $modelZip = Read-Host 'Path arsip model dari tim'
    Expand-Archive -LiteralPath $modelZip -DestinationPath $modelDir
}
```

```powershell
Test-Path ml/artifacts/xgb-v1-f9a770b940f71fc8/manifest.json
Test-Path ml/artifacts/xgb-v1-f9a770b940f71fc8/model.ubj
Get-FileHash -Algorithm SHA256 ml/artifacts/xgb-v1-f9a770b940f71fc8/model.ubj
```

Lewati training jika paket model kompatibel tersedia. Ekstraksi arsip dan pemuatan model lolos pada direktori uji baru. [Manifest dan checksum yang diverifikasi](../testing/sprint7_ml_evidence.json) · [Reproduksi model](#7-reproduksi-dataset-dan-model-opsional)

## 3. Konfigurasi dan persistensi

```powershell
New-Item -ItemType Directory ml/runtime -Force | Out-Null
if (-not (Test-Path ml/runtime/backend.env.ps1)) {
    Copy-Item -LiteralPath ml/backend.env.example.ps1 -Destination ml/runtime/backend.env.ps1
}
```

Isi salinan lokal menggunakan sandi demo yang berbeda untuk `marketing`, `ppic`, dan `pfa`. Sandi harus 12–128 karakter. Gunakan JWT signing secret acak minimal 32 byte dan kunci unik 32–256 karakter ASCII terlihat untuk setiap sensor. Simpan dan bagikan akses demo melalui jalur privat tim. `SIKEMBANG_SYSTEM_KEY` opsional untuk uji HTTP SYSTEM. Otorisasi SYSTEM internal tetap dipakai oleh kalkulasi. Gunakan cutoff WIB berjalan untuk demo interaktif. Kalender versi model yang diverifikasi mencakup 2020–2026.

Di terminal backend, muat environment dan pilih SQLite terpisah dari demo lama. Gunakan path baru saat mengulang sebuah skenario yang telah menyimpan daftar pada periode yang sama. Simpan path dan kredensial tetap saat memeriksa persistence dan seed ulang.

```powershell
. .\ml\runtime\backend.env.ps1
$env:SIKEMBANG_DB_PATH = 'ml/runtime/demo-d3.sqlite3'
Remove-Item Env:SIKEMBANG_DEMO_CUTOFF -ErrorAction SilentlyContinue
& $python -m sikembang_backend.manage init-db
& $python -m sikembang_backend.manage seed
& $python -m uvicorn sikembang_backend.app:create_app --factory --host 127.0.0.1 --port 8000
```

`init-db` membuat schema dan memperbarui kolom provenance yang diperlukan. `seed` menambahkan baris yang belum ada. Jika kredensial existing tidak cocok, pilih database demo baru atau gunakan kredensial yang benar. Untuk restart, gunakan path yang sama dan mulai Uvicorn lagi. [Template](../../ml/backend.env.example.ps1) · [SQLite dan seeding](database.md)

## 4. Health, Swagger, dan prediksi aktual

Dari terminal kedua, cek health dan buka Swagger. Untuk forecast, baca periode dari output seed. Prompt menyimpan sandi PPIC di memori terminal. Output prediksi berisi versi model dan ID run.

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod -Uri "$base/api/health"
Start-Process "$base/docs"
$period = Read-Host 'planning_period dari output seed'
$secret = Read-Host 'Sandi PPIC lokal' -AsSecureString
$password = [System.Net.NetworkCredential]::new('', $secret).Password
$session = Invoke-RestMethod -Method Post -Uri "$base/api/auth/login" `
    -ContentType 'application/json' -Body (@{username='ppic'; password=$password} | ConvertTo-Json)
$headers = @{Authorization = "Bearer $($session.access_token)"}
$forecast = @{target_period=$period; ingredient_ids=@('ING-001')} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/api/ai/predict" -Headers $headers `
    -ContentType 'application/json' -Body $forecast
Remove-Variable secret,password,session,headers -ErrorAction SilentlyContinue
```

Jika health menunjukkan `model_version=null`, periksa lokasi dan kompatibilitas artefak. Endpoint forecast memerlukan histori empat minggu. `422 INSUFFICIENT_HISTORY` menunjukkan lag wajib belum lengkap. Contoh sukses dan penolakan aktual disediakan di bukti HTTP. [API](api.md) · [Verifikasi](verification.md)

## 5. Frontend dan identitas demo

Gunakan terminal baru dari root repository. `npm ci` memasang versi dari lockfile.

```powershell
npm.cmd ci
$env:VITE_API_MODE = 'live'
$env:VITE_API_BASE_URL = '/api'
$env:VITE_DEV_PROXY_TARGET = 'http://127.0.0.1:8000'
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Buka [frontend live](http://127.0.0.1:5173). Masuk dengan satu identitas demo yang sudah disediakan. Marketing membuat order, PPIC meninjau dan mengirim, PFA membaca kuantitas akhir. Gunakan **Keluar** untuk berpindah akun. Untuk mode mock, hentikan Vite, atur `$env:VITE_API_MODE = 'mock'`, hapus `VITE_DEV_PROXY_TARGET` di terminal itu, lalu mulai Vite kembali. Simulator web dan pemilih peran muncul pada mock.

Untuk memublikasikan build internal suatu saat, host perlu menyediakan route `/api` yang konsisten, HTTPS dan konfigurasi otorisasi yang terpisah dari dev. Pada demo lokal, Vite memproksi request agar browser memakai origin yang sama. [Integrasi frontend](system.md)

## 6. Simulator, ESP32, dan pengujian

Jalankan alur nyata melalui React live dengan klien simulator yang mengirim telemetry ke FastAPI. Pilih jalur fisik hanya saat sensor, board, kalibrasi, dan jaringan siap. [Skrip demo dan contoh POST simulasi](demo.md) · [Wiring, upload, serial, dan LAN](../../firmware/esp32_scale/README.md)

```powershell
$env:OMP_NUM_THREADS = '2'
& $python -m pytest ml/tests -q -p no:cacheprovider
npm.cmd run lint
npm.cmd test
npm.cmd run build
& $python -X utf8 docs/testing/verify_sprint7.py --cutoff 2026-11-27T12:00:00+07:00
$env:SIKEMBANG_TEST_PYTHON = $python
node ml/testing/verify_sprint7_browser.mjs --preview
```

Runner HTTP dan browser membuat database serta kredensial uji baru. Untuk browser, atur `SIKEMBANG_TEST_CHROME` ke executable Chrome bila instalasinya berbeda. Cutoff HTTP di atas mereproduksi 2026-W48 setelah 27 November 2026 pukul 12.00 WIB. Browser memakai minggu berjalan sehingga memerlukan cakupan kalender model yang sesuai. [Hasil terverifikasi](verification.md)

## 7. Reproduksi dataset dan model opsional

Generator menulis raw history, fitur dan split dalam satu run. Gunakan direktori keluaran baru untuk eksperimen yang berbeda. Set direktori hasil training dari output model. Untuk membandingkan model lama, pakai pasangan bundle dan artefak yang memiliki checksum kompatibel.

```powershell
& $python -m ai_forecast.dataset --seed 3120 --output ml/generated/synthetic-v1
& $python -m ai_forecast.train --dataset ml/generated/synthetic-v1 --output ml/artifacts/reproduction --seed 3120
$reproduced = Read-Host 'Direktori run yang dicetak training'
& $python -m ai_forecast.evaluate --dataset ml/generated/synthetic-v1 --artifact $reproduced
```

Sprint 7 meregenerasi bundle, mengulang evaluasi dengan model beku, mencocokkan 3.640 prediksi, dan merender ulang grafik. Entry point training diverifikasi pada Sprint 3. Command training opsional dengan direktori `reproduction` berstatus belum dijalankan dalam handoff ini. [Training dan format artefak](../../ml/README.md#training-dan-evaluasi-sprint-3) · [Audit ML](ai.md)

## 8. Inferensi standalone untuk replay historis

Harness replay memakai artefak dan dataset pasangannya. Request tersedia untuk 2025-W10 dan 2025-W11 pada cutoff bawaan. Run harness tersimpan di memori untuk replay lokal.

```powershell
$env:SIKEMBANG_ARTIFACT = 'ml/artifacts/xgb-v1-f9a770b940f71fc8'
$env:SIKEMBANG_REPLAY_DATASET = 'ml/generated/synthetic-v1'
$env:SIKEMBANG_REPLAY_TOKEN = [System.Net.NetworkCredential]::new(
    '', (Read-Host 'Bearer harness lokal' -AsSecureString)
).Password
& $python -m uvicorn ai_forecast.harness:create_app --factory --host 127.0.0.1 --port 8010
```

Pada terminal klien, masukkan token replay yang sama.

```powershell
$token = [System.Net.NetworkCredential]::new('', (Read-Host 'Bearer harness yang sama' -AsSecureString)).Password
$payload = @{target_period='2025-W10'; ingredient_ids=@('ING-001','ING-007','ING-012')} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8010/api/ai/predict' `
    -Headers @{Authorization="Bearer $token"} -ContentType 'application/json' -Body $payload
Remove-Variable token -ErrorAction SilentlyContinue
```

Run normal memakai aplikasi `sikembang_backend`, kredensial database dan penyimpanan forecast di SQLite. Smoke test Sprint 8 memulai kedua factory lewat Uvicorn dan memperoleh Swagger 200, prediksi live 201, telemetry simulasi 201, serta prediksi harness 201. [Bukti eksekusi](evidence/windows-smoke.json) · [Contoh standalone dan skenario histori kurang](../../ml/README.md#inferensi-sprint-4)
