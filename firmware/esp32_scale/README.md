# ESP32 scale untuk SiKembang

Sketch `esp32_scale.ino` membaca HX711, menampilkan gram pada OLED, dan mengirim pembacaan stabil ke FastAPI. Gunakan referensi tim `.ai-context/IOT_FIRMWARE_ORIGINAL.ino` untuk membandingkan perangkat asli.

## Papan, pustaka, dan sambungan

| Bagian | Konfigurasi |
|---|---|
| Papan target | ESP32 Dev Module klasik, FQBN `esp32:esp32:esp32` |
| OLED SSD1306 dan Adafruit GFX | 128×64, alamat I²C `0x3C`, SDA GPIO 25, SCL GPIO 26, tanpa pin reset khusus |
| HX711 dan load cell | DOUT GPIO 32, SCK GPIO 33 |
| Tombol tare | GPIO 27, aktif LOW dengan pull-up internal |
| Serial Monitor | 115200 baud |
| Faktor kalibrasi | −120,0 dari perangkat tim, masih sementara |

Pertahankan wiring dan catu daya kit tim. Periksa common ground, rating modul, dan kompatibilitas sinyal 3,3 V pada GPIO ESP32 sebelum menyambung ulang. Gunakan kabel USB data dan pastikan model papan sesuai target.

Pasang Arduino CLI atau Arduino IDE. Tambahkan indeks Espressif melalui Boards Manager. Gunakan Arduino-ESP32 2.0.17 untuk baseline dan pustaka HX711 Arduino Library 0.7.5 oleh bogde, Adafruit GFX Library 1.12.4, Adafruit SSD1306 2.5.16, dan Adafruit BusIO 1.17.4. Wire, WiFi, HTTPClient, Preferences, SNTP, dan FreeRTOS berasal dari core ESP32. [Instalasi Arduino-ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html) · [Core 2.0.17](https://github.com/espressif/arduino-esp32/releases/tag/2.0.17) · [HX711 oleh bogde](https://github.com/bogde/HX711)

## Konfigurasi perangkat dan backend Windows

1. Dari root repository, tentukan adapter aktif pada LAN privat tepercaya. Pilih IPv4 privat RFC 1918 pada adapter yang juga dapat dijangkau ESP32. Pertahankan hasil `$lan` di terminal tempat Uvicorn dijalankan.

   ```powershell
   Get-NetIPConfiguration |
       Where-Object { $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up' } |
       Select-Object InterfaceAlias, @{Name='IPv4';Expression={$_.IPv4Address.IPAddress}}, IPv4DefaultGateway
   $lan = Read-Host 'IPv4 LAN laptop dari tabel'
   $adapter = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $lan
   Get-NetConnectionProfile -InterfaceAlias $adapter.InterfaceAlias
   ```

2. Siapkan venv, artefak XGBoost, dan template env backend mengikuti panduan proyek. Pakai database demo. Isi `secrets.h` secara lokal dengan SSID, password, `backendBaseUrl` berupa `http://<IPv4 LAN laptop>:8000` tanpa slash penutup, dan kunci unik perangkat. Pertahankan `sensorId=SNS-GDG-ESP32-01` serta `ingredientId=ING-001`. Simpan file konfigurasi, biner, dan log build yang memuat rahasia di penyimpanan lokal. [Template firmware](secrets.example.h) · [Konfigurasi backend](../../ml/README.md#backend-dan-sqlite-sprint-6a)

   ```powershell
   if (-not (Test-Path firmware/esp32_scale/secrets.h)) {
       Copy-Item firmware/esp32_scale/secrets.example.h firmware/esp32_scale/secrets.h
   }

   . .\ml\runtime\backend.env.ps1
   $env:SIKEMBANG_DB_PATH = 'ml/runtime/demo-6e-physical.sqlite3'
   Remove-Item Env:SIKEMBANG_DEMO_CUTOFF -ErrorAction SilentlyContinue
   rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage init-db
   rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage seed
   ```

3. Saat ESP32 fisik telah diidentifikasi, daftarkan dengan kunci yang sama dengan `secrets.h`. Gunakan 32–256 karakter ASCII terlihat dan unik, yang dibuat oleh generator rahasia. Nilai disimpan sebagai hash pada registry. Ganti contoh lokasi dengan ID lokasi fisik yang sebenarnya.

   ```powershell
   $env:SIKEMBANG_DEVICE_ESP32_KEY = [System.Net.NetworkCredential]::new(
       '', (Read-Host 'Kunci ESP32 yang sama dengan secrets.h' -AsSecureString)
   ).Password
   rtk proxy ml\.venv\Scripts\python.exe -m sikembang_backend.manage register-physical-rice --location GUDANG-UTAMA
   rtk proxy ml\.venv\Scripts\python.exe -m uvicorn sikembang_backend.app:create_app --factory --host $lan --port 8000
   ```

4. Di terminal kedua cek listener dan health. Setelah upload sesuai bagian berikut, sambungkan ESP32 ke jaringan yang sama dan peroleh IPv4 ESP32 dari lease DHCP router atau Serial Monitor.

   ```powershell
   $lan = Read-Host 'IPv4 LAN laptop yang dipakai Uvicorn'
   Get-NetTCPConnection -LocalAddress $lan -LocalPort 8000 -State Listen
   Test-NetConnection -ComputerName $lan -Port 8000
   Invoke-RestMethod -Uri "http://$($lan):8000/api/health"
   w32tm /query /status
   ```

5. Bila Windows Firewall perlu pengecualian, gunakan PowerShell Administrator pada LAN tepercaya dengan profil Private. Batasi ke adapter, alamat laptop, port, dan IPv4 ESP32 yang ditentukan. Jaga ruang lingkup saat DHCP berubah.

   ```powershell
   $lan = Read-Host 'IPv4 LAN laptop'
   $esp = Read-Host 'IPv4 ESP32 pada LAN yang sama'
   $adapter = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $lan
   New-NetFirewallRule -Name 'SiKembang-ESP32-6E-8000' -DisplayName 'SiKembang ESP32 6E' `
       -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -LocalAddress $lan `
       -RemoteAddress $esp -InterfaceAlias $adapter.InterfaceAlias -Profile Private
   ```

   Bersihkan rule khusus setelah demo dengan `Remove-NetFirewallRule -Name 'SiKembang-ESP32-6E-8000'`. Akses HTTP prototipe dibatasi ke LAN tepercaya. Produksi memerlukan HTTPS, pengelolaan kredensial perangkat, dan kebijakan akses yang sesuai. Jika health lolos dari laptop tetapi ESP32 gagal konek, periksa alamat, firewall, VLAN, serta isolasi klien AP. NTP memerlukan DNS dan jalur UDP 123 ke host NTP yang dipilih. Pada LAN terisolasi, isi host NTP lokal tepercaya di konfigurasi. [Referensi firewall Microsoft](https://learn.microsoft.com/powershell/module/netsecurity/new-netfirewallrule?view=windowsserver2025-ps)

6. Untuk frontend di laptop, arahkan Vite ke interface yang sama.

   ```powershell
   $lan = Read-Host 'IPv4 LAN laptop yang dipakai Uvicorn'
   $env:VITE_API_MODE = 'live'
   $env:VITE_API_BASE_URL = '/api'
   $env:VITE_DEV_PROXY_TARGET = "http://$($lan):8000"
   rtk proxy npm.cmd ci
   rtk proxy npm.cmd run dev -- --host 127.0.0.1 --port 5173
   ```

## Kompilasi, upload, dan kalibrasi

Dari root repo dengan Arduino CLI pada PATH.

```powershell
$esp32Index = 'https://espressif.github.io/arduino-esp32/package_esp32_index.json'
rtk proxy arduino-cli core update-index --additional-urls $esp32Index
rtk proxy arduino-cli core install 'esp32:esp32@2.0.17' --additional-urls $esp32Index
rtk proxy arduino-cli lib install 'HX711 Arduino Library@0.7.5' 'Adafruit GFX Library@1.12.4' 'Adafruit SSD1306@2.5.16' 'Adafruit BusIO@1.17.4' --no-deps
rtk proxy arduino-cli compile --fqbn esp32:esp32:esp32 --build-path ml/runtime/esp32-6e-build firmware/esp32_scale
rtk proxy arduino-cli board list
$espPort = Read-Host 'COM port ESP32 yang baru muncul'
rtk proxy arduino-cli upload --port $espPort --fqbn esp32:esp32:esp32 --input-dir ml/runtime/esp32-6e-build firmware/esp32_scale
rtk proxy arduino-cli monitor --port $espPort --config baudrate=115200
```

Di Arduino IDE, buka `esp32_scale.ino`, pilih ESP32 Dev Module, pilih COM yang muncul setelah menghubungkan papan, lalu Verify, Upload, dan buka Serial Monitor pada 115200. Jika COM absen, cabut-pasang kabel data dan gunakan driver resmi yang sesuai chipset USB kit. [Kompilasi Arduino CLI](https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_compile) · [Upload Arduino CLI](https://docs.arduino.cc/arduino-cli/commands-reference/arduino-cli_upload)

Jika compiler Windows melaporkan `The filename or extension is too long` dari direktori data Arduino khusus, gunakan lokasi data yang lebih pendek dan pasang core pada lokasi tersebut. Untuk toolchain portabel yang sudah dipasang, `subst` dapat memberi drive sementara ke direktori lokal toolchain. Sesuaikan `ARDUINO_DIRECTORIES_DATA` dengan drive itu selama build. [Batas panjang argumen Windows](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) · [Perintah subst](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/subst)

- Kalibrasi saat platform atau wadah kosong yang disepakati. Lepaskan tombol setelah boot, lalu tahan tare sekitar satu detik dan tunggu offset disimpan. Offset digunakan lagi pada restart, termasuk ketika platform berbeban.
- Tentukan kapasitas terverifikasi dari label/datasheet kit, termasuk berat platform atau wadah. Pilih beberapa massa referensi yang sudah diketahui dan aman. Pastikan titik pembebanan dan kondisi permukaan konsisten.
- Pada setiap massa, tunggu stabil, catat nominal, gram terbaca, selisih, dan pengulangan. Periksa ulang titik nol setelah beban diangkat. Bila faktor perlu disetel, gunakan `faktor_baru = faktor_lama × (gram_terbaca / gram_referensi)` dari pengukuran stabil. Masukkan faktor per perangkat di `secrets.h`, kompilasi ulang, lalu ulangi uji kosong dan beberapa massa.
- Aktifkan toleransi nol hanya setelah noise kosong terukur. Bawaan 0 g menolak pembacaan negatif. Offset tare dapat ditetapkan ulang setelah perubahan mekanik.

## Perilaku telemetry

Pada setiap koneksi baru, perangkat menunggu sinkronisasi SNTP sebelum mengirim JSON `sensor_id`, `ingredient_id`, `measured_weight`, `unit="g"`, dan `recorded_at` UTC ISO 8601 mikrodetik ke `POST /api/iot/telemetry` dengan `X-Device-Key`. InventoryIoTService mengonversi gram ke kg. Periksa Serial saat status berubah dan lihat HTTP 201. Angka yang dikirim berasal dari HX711.

Jendela meliputi lima sampel dengan spread sampai 3 g. Kirim pertama, perubahan minimal 10 g, atau heartbeat tiap 60 detik saat stabil. Jarak minimum kirim 2 detik. Jaringan berjalan pada tugas terpisah dengan timeout koneksi dan I/O 3 detik, Wi-Fi 12 detik per percobaan, serta backoff 2–30 detik. Satu slot membawa sampel baru yang masih segar. Setelah 15 detik tanpa SNTP, status menampilkan kegagalan sinkronisasi. Pemeriksaan status dan heartbeat berlaku walau berat tidak berubah.

Untuk HTTP 401/403 periksa kunci perangkat dan registrasinya. Untuk 422 periksa nilai, satuan, mapping, dan jam. Laptop dan perangkat perlu waktu sinkron agar `FUTURE_TIMESTAMP` serta `STALE_SENSOR_DATA` dapat dibedakan. HTTP 409 berarti pembacaan tidak lebih baru dari stok yang tersimpan. Tunggu pembacaan segar setelah jam stabil. Isi paket dan kunci tidak dicetak pada Serial.

## Walkthrough fisik dan fallback

1. Mulai FastAPI pada LAN tepercaya, upload sketch, pastikan Serial menampilkan Wi-Fi terhubung dan jam UTC siap, serta OLED menampilkan berat stabil yang dapat dibandingkan dengan massa referensi.
2. Tunggu HTTP 201 dan heartbeat. Sebagai PPIC buka `GET /api/inventory/stock?ingredient_ids=ING-001` melalui Swagger atau lihat stok pada browser. Cocokkan gram OLED dengan kg dari respons, `last_iot_sync`, serta status Segar.
3. Periksa log SQLite melalui pembacaan read-only untuk melihat `validation_status=ACCEPTED`, `device_source=physical`, `location_id` terdaftar, dan nilai yang dikonversi. Label fisik digunakan setelah paket benar-benar diterima dari skala. Telemetry stok kini dan feedback mingguan tetap memiliki provenance sendiri.

   ```powershell
   $env:SIKEMBANG_DB_PATH = 'ml/runtime/demo-6e-physical.sqlite3'
   @'
   import os
   import sqlite3
   from pathlib import Path

   database = Path(os.environ["SIKEMBANG_DB_PATH"]).resolve()
   with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
       for row in db.execute("""
           SELECT recorded_at, validation_status, rejection_code, stored_value,
                  base_unit, device_source, location_id
           FROM iot_telemetry_logs WHERE sensor_id = ?
           ORDER BY recorded_at DESC LIMIT 5
       """, ("SNS-GDG-ESP32-01",)):
           print(row)
   '@ | rtk proxy ml\.venv\Scripts\python.exe -X utf8 -
   ```

4. Jalankan alur Marketing → PPIC → PFA pada minggu berjalan. Pada perencanaan PPIC, kalkulasi memakai model XGBoost, BOM yang terkonfirmasi, dan stok baru. Review, isi catatan stok usang, setujui, lalu buka daftar terkirim sebagai PFA.
5. Bandingkan kalkulasi sebelum dan sesudah pada dua database demo terpisah dengan seed, cutoff yang sebanding, dan order yang sama. Hitung draf satu kali di masing-masing. Simpan kedua hasil dan metadata sumber. [Instruksi workflow Sprint 6D](../../README.md#menjalankan-mode-live-di-windows)

 Untuk menambah stok ayam pada demo campuran, kirim **simulasi** dengan sensor `SNS-KLK-01`, bahan `ING-003`, satuan `g` dan kunci `SIKEMBANG_DEVICE_CHICKEN_KEY`. Untuk fallback beras, hentikan pengiriman dari skala fisik, lalu ganti nilai pada contoh dengan `SNS-GDG-01`, `ING-001`, dan `SIKEMBANG_DEVICE_RICE_KEY`. Kedua sensor beras menulis stok `ING-001` yang sama. Simulator web MSW juga tersedia pada mode mock.

```powershell
. .\ml\runtime\backend.env.ps1
$lan = Read-Host 'IPv4 yang dipakai Uvicorn'
$simulated = @{
    sensor_id = 'SNS-KLK-01'
    ingredient_id = 'ING-003'
    measured_weight = 21500
    unit = 'g'
    recorded_at = [DateTimeOffset]::UtcNow.AddSeconds(-1).ToString('o')
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://$($lan):8000/api/iot/telemetry" -Headers @{
    'X-Device-Key' = $env:SIKEMBANG_DEVICE_CHICKEN_KEY
} -ContentType 'application/json' -Body $simulated
```
