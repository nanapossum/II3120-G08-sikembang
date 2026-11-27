# Panduan Integrasi End-to-End IoT ESP32 SiKembang

Panduan ini menjelaskan langkah menjalankan **Backend FastAPI**, **Frontend Dashboard PPIC**, **pengujian API via `curl`**, hingga **mengunggah firmware ke ESP32 DevKit + Load Cell 20kg** (`firmware/esp32_sikembang/esp32_sikembang.ino`).

---

## 1. Spesifikasi Hardware & Pinout

| Komponen | Pin ESP32 / Konfigurasi |
|---|---|
| Mikrokontroler | ESP32 DevKit (`ESP32 Dev Module`) |
| HX711 + Load Cell 20kg | `DOUT = GPIO 32`, `SCK = GPIO 33` |
| OLED SSD1306 128×64 I2C | Alamat `0x3C`, `SDA = GPIO 25`, `SCL = GPIO 26`, `Wire.setClock(400000)` |
| Tombol Fisik Tare | `GPIO 27` (`INPUT_PULLUP`, aktif LOW ke GND) |
| Serial Monitor | `115200 baud` |

**Perangkat & Bahan Default:**
- `sensor_id`: `SNS-GDG-ESP32-01`
- `ingredient_id`: `ING-001` (**Beras**, satuan dasar `kg` — otomatis dikonversi dari `g` oleh `InventoryIoTService`)

---

## 2. Menjalankan Backend FastAPI (Akses LAN `0.0.0.0:8000`)

### 2.1. Siapkan Environment & Database SQLite (PowerShell)

Dari root repositori:

```powershell
# 1. Buat & aktifkan virtualenv Python jika belum ada
python -m venv ml\.venv
ml\.venv\Scripts\python.exe -m pip install -e ml

# 2. Salin contoh environment backend (tidak di-commit)
New-Item -ItemType Directory -Force ml\runtime | Out-Null
Copy-Item ml\backend.env.example.ps1 ml\runtime\backend.env.ps1
```

Edit `ml\runtime\backend.env.ps1` lalu isi variabel rahasia (JWT secret min. 32 byte, password akun `marketing`/`ppic`/`pfa` 12–128 karakter, dan key sensor seed min. 32 karakter visible ASCII). Kemudian jalankan:

```powershell
# Muat environment backend
. .\ml\runtime\backend.env.ps1

# Gunakan waktu saat ini (hapus demo cutoff historis agar telemetri live diterima)
Remove-Item Env:SIKEMBANG_DEMO_CUTOFF -ErrorAction SilentlyContinue

# Inisialisasi skema SQLite & seed data awal
ml\.venv\Scripts\python.exe -m sikembang_backend.manage init-db
ml\.venv\Scripts\python.exe -m sikembang_backend.manage seed

# Daftarkan perangkat fisik ESP32 (SNS-GDG-ESP32-01 -> ING-001 Beras)
# Gunakan key unik 32-256 karakter visible ASCII yang SAMA dengan DEVICE_KEY di secrets.h
$env:SIKEMBANG_DEVICE_ESP32_KEY = "ganti-dengan-kunci-esp32-rahasia-minimal-32-karakter"
ml\.venv\Scripts\python.exe -m sikembang_backend.manage register-physical-rice --location GUDANG-UTAMA
```

### 2.2. Jalankan Server Uvicorn pada `0.0.0.0:8000`

```powershell
# Opsional: izinkan origin tambahan bila frontend diakses dari IP LAN selain localhost:5173
# $env:SIKEMBANG_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

ml\.venv\Scripts\python.exe -m uvicorn sikembang_backend.app:create_app --factory --host 0.0.0.0 --port 8000
```

> **Catatan Windows Firewall & IP LAN:**
> 1. Cek IPv4 LAN laptop (Wi-Fi yang sama dengan ESP32) dengan `ipconfig`. Contoh: `192.168.1.10`.
> 2. Pastikan Windows Firewall mengizinkan trafik masuk TCP port `8000` pada profil **Private** (PowerShell Administrator):
>    ```powershell
>    New-NetFirewallRule -Name "SiKembang-Backend-8000" -DisplayName "SiKembang FastAPI 8000" `
>      -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private
>    ```

---

## 3. Menjalankan Frontend Dashboard PPIC (Real-Time Polling)

Di terminal kedua (dari root repositori):

```powershell
npm install

$env:VITE_API_MODE = "live"
$env:VITE_API_BASE_URL = "/api"
$env:VITE_DEV_PROXY_TARGET = "http://127.0.0.1:8000"

npm run dev -- --host 127.0.0.1 --port 5173
```

1. Buka browser ke `http://127.0.0.1:5173` (atau `http://localhost:5173`).
2. Login menggunakan akun **`ppic`** dan password yang Anda atur di `ml\runtime\backend.env.ps1`.
3. Pada halaman **Perencanaan minggu ini** (`/ppic`), tabel **Stok gudang terkini** secara otomatis melakukan polling `GET /api/inventory/stock` setiap **2,5 detik** (`refetchInterval: 2500`), sehingga perubahan berat dari timbangan fisik ESP32 akan langsung muncul tanpa reload halaman.

---

## 4. Uji `POST /api/iot/telemetry` dengan `curl` Sebelum Menyalakan ESP32

Pastikan backend berjalan dan Anda sudah menjalankan `register-physical-rice`.

### PowerShell (Windows — gunakan `curl.exe`)

```powershell
$TIMESTAMP = [DateTimeOffset]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
$DEVICE_KEY = $env:SIKEMBANG_DEVICE_ESP32_KEY

curl.exe -i -X POST "http://127.0.0.1:8000/api/iot/telemetry" `
  -H "Content-Type: application/json" `
  -H "X-Device-Key: $DEVICE_KEY" `
  -d "{`"sensor_id`":`"SNS-GDG-ESP32-01`",`"ingredient_id`":`"ING-001`",`"measured_weight`":15250.5,`"unit`":`"g`",`"recorded_at`":`"$TIMESTAMP`"}"
```

### Bash / Git Bash / Linux / macOS

```bash
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000000Z")
DEVICE_KEY="ganti-dengan-kunci-esp32-rahasia-minimal-32-karakter"

curl -i -X POST "http://127.0.0.1:8000/api/iot/telemetry" \
  -H "Content-Type: application/json" \
  -H "X-Device-Key: ${DEVICE_KEY}" \
  -d "{\"sensor_id\":\"SNS-GDG-ESP32-01\",\"ingredient_id\":\"ING-001\",\"measured_weight\":15250.5,\"unit\":\"g\",\"recorded_at\":\"${TIMESTAMP}\"}"
```

**Contoh Respons Sukses (`HTTP/1.1 201 Created`):**

```json
{
  "log_id": "TLM-...",
  "validation_status": "ACCEPTED",
  "ingredient_id": "ING-001",
  "stored_value": 15.2505,
  "base_unit": "kg",
  "current_stock": 15.2505,
  "last_iot_sync": "2026-11-27T17:15:00+07:00"
}
```

Setelah menerima `201 Created`, lihat browser Dashboard PPIC: stok **Beras** akan otomatis berubah menjadi **`15,25 kg`** (atau sesuai format tampilan) dengan status **Segar** dalam 2–3 detik.

> **Catatan uji berulang:** Setiap pengiriman ulang dengan `curl` harus menghasilkan nilai `$TIMESTAMP` baru (lebih baru dari `last_iot_sync` sebelumnya), jika sama/lebih lama backend akan mengembalikan `409 OUT_OF_ORDER_READING`.

---

## 5. Mengunggah Firmware ke ESP32

### 5.1. Buat File `secrets.h`

Salin template secrets (file `secrets.h` diabaikan oleh Git melalui `.gitignore`):

```powershell
Copy-Item firmware\esp32_sikembang\secrets.example.h firmware\esp32_sikembang\secrets.h
```

Buka `firmware\esp32_sikembang\secrets.h` dan isi:
- `WIFI_SSID` & `WIFI_PASS`: Wi-Fi 2.4 GHz pada jaringan LAN yang sama dengan laptop backend.
- `SERVER_URL`: `http://<IPv4-LAN-LAPTOP>:8000` (tanpa `/` di akhir).
- `DEVICE_KEY`: nilai yang **sama persis** dengan `SIKEMBANG_DEVICE_ESP32_KEY`.

Sesuaikan juga `CALIBRATION_FACTOR` di bagian paling atas `firmware/esp32_sikembang/esp32_sikembang.ino` bila faktor kalibrasi load cell 20kg Anda berbeda dari `-120.0f`.

### 5.2. Library yang Dibutuhkan (Arduino IDE)

1. Pasang board **esp32** oleh Espressif Systems di Boards Manager, lalu pilih board **ESP32 Dev Module**.
2. Pasang library melalui Library Manager:
   - **HX711 Arduino Library** oleh Bogdan Necula (`bogde`)
   - **Adafruit SSD1306** oleh Adafruit
   - **Adafruit GFX Library** oleh Adafruit (beserta dependensi `Adafruit BusIO`)
   *(Library `WiFi`, `HTTPClient`, dan `Wire` sudah termasuk dalam core ESP32.)*
3. Buka `firmware/esp32_sikembang/esp32_sikembang.ino`, pilih port COM ESP32, lalu klik **Verify** → **Upload**.
4. Buka **Serial Monitor** (`115200 baud`) untuk memantau log koneksi Wi-Fi, NTP, dan respons HTTP.

---

## 6. Arti Indikator Status di Layar OLED

| Status `NET:` di OLED | Arti & Tindakan |
|---|---|
| `Isi secrets.h!` | `secrets.h` belum disalin atau masih berisi nilai placeholder. |
| `Offline` | Wi-Fi belum terhubung; ESP32 otomatis mencoba reconnect tiap 5 detik tanpa membekukan OLED. |
| `NTP Sync...` | Wi-Fi terhubung, sedang menunggu sinkronisasi jam UTC dari server NTP sebelum mengirim HTTP POST. |
| `NTP OK \| Ready` | Jam UTC sinkron, menunggu siklus pengiriman pertama. |
| `201 OK` / `200 OK` | Telemetri diterima backend dan stok di database diperbarui menjadi `FRESH`. |
| `HTTP 401` | `DEVICE_KEY` salah atau perangkat belum didaftarkan lewat `register-physical-rice`. |
| `HTTP 409` | `OUT_OF_ORDER_READING` — `recorded_at` tidak lebih baru dari data terakhir di database. |
| `HTTP 422` | Payload ditolak validasi (`FUTURE_TIMESTAMP`, `STALE_SENSOR_DATA`, `SENSOR_INGREDIENT_MISMATCH`, atau `UNIT_MISMATCH`). Periksa jam laptop & Serial Monitor. |
| `ERR -1` / `ERR -11` | Server tidak dapat dijangkau (cek `SERVER_URL`, server Uvicorn `--host 0.0.0.0`, atau Windows Firewall) / timeout (> 2000 ms). |
