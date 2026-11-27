# Referensi REST API

FastAPI melayani aplikasi dan perangkat melalui prefiks `/api`. Payload JSON memakai nama atribut snake_case. Tabel berikut mengikuti urutan kontrak D3 dan memetakan operasi ke SoaML D2.

| No. | Endpoint | Peran | Sukses | Operasi SoaML |
| --- | --- | --- | --- | --- |
| 1 | `POST /api/orders` | MARKETING | 201 | `OrderService.catatPesanan` |
| 2 | `PUT /api/orders/{order_id}` | MARKETING | 200 | `OrderService.revisiPesanan` |
| 3 | `GET /api/orders` | PPIC, SYSTEM | 200 | `OrderService.ambilPesananTerkonfirmasi` |
| 4 | `POST /api/iot/telemetry` | DEVICE | 201 | `InventoryIoTService.kirimTelemetri` |
| 5 | `GET /api/inventory/stock` | PPIC, SYSTEM | 200 | `InventoryIoTService.ambilStokTerkini` |
| 6 | `POST /api/ai/predict` | PPIC, SYSTEM | 201 | `AIForecastService.buatPrediksi` |
| 7 | `POST /api/procurement/calculate` | PPIC | 201 | `ProcurementCalcService.hitungKebutuhan` |
| 8 | `POST /api/shopping-lists` | SYSTEM | 201 | `ShoppingListService.simpanDraf` |
| 9 | `PATCH /api/shopping-lists/{list_id}/approve` | PPIC | 200 | `ShoppingListService.validasiDaftar` |
| 10 | `POST /api/shopping-lists/{list_id}/send` | PPIC | 200 | `ShoppingListService.teruskanKePFA` |
| 11 | `GET /api/shopping-lists` | PPIC, PFA | 200 | `ShoppingListService.ambilDaftarBelanja` |

## Autentikasi dan format galat

Dashboard memakai `Authorization: Bearer <JWT>` dari `POST /api/auth/login`. DEVICE memakai `X-Device-Key` dari registri aktif. SYSTEM memakai `X-System-Key` dari konfigurasi server. Endpoint dengan peran gabungan PPIC dan SYSTEM menerima salah satu kredensial. Jika header SYSTEM disertakan, backend memeriksa otoritas SYSTEM. JWT hilang atau tidak valid menghasilkan `401 UNAUTHORIZED`. Peran yang tidak diizinkan menghasilkan `403 FORBIDDEN_ROLE`.

Semua galat aplikasi memakai envelope `{"error":{"code":"…","message":"…","details":{}}}`. Bentuk request yang salah umumnya menghasilkan `400 VALIDATION_ERROR`. `error.details.fields` dapat memuat lokasi field dan alasannya. Aturan bisnis memakai kode spesifik, termasuk `409` pada konflik dan `422` saat data tidak memenuhi aturan proses. Kesalahan internal dapat menghasilkan `500 INTERNAL_ERROR`. Contoh berikut berasal dari konflik versi Sprint 7. [Handler FastAPI](../../ml/src/sikembang_backend/errors.py).

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "Pesanan sudah direvisi. Muat ulang data terbaru sebelum mengirim revisi.",
    "details": {
      "order_id": "ORD-2026-2B77E30974CE4248A97DF3A39872E8AD",
      "sent_version": 1,
      "current_version": 2
    }
  }
}
```

## Contoh request dan response

Contoh memakai [bukti HTTP Sprint 7](../testing/sprint7_http_evidence.json) dengan fixture sintetis dan cutoff tetap `2026-11-27T12:00:00+07:00`. Array yang disingkat ditandai. Request dengan body JSON menyertakan `Content-Type: application/json`. Request GET dan `send` tanpa body. Untuk percobaan sekarang, gunakan ID hasil request, periode yang didukung, dan telemetri dengan waktu aktual yang sinkron. Header rahasia tidak ditampilkan.

### 1. `POST /api/orders`

**Akses** MARKETING sesuai header autentikasi di atas.

Mencatat pesanan terkonfirmasi versi 1. Wajib `customer_name` nonkosong, `order_category` (`PRASMANAN_WEDDING`, `PRASMANAN_NON_WEDDING`, `NASI_KOTAK`), `event_date` (`YYYY-MM-DD`), dan `items` dengan `menu_id` serta `confirmed_portions` integer positif. `event_location` opsional dan dapat `null`. Transaksi menulis `orders`, `order_revisions`, dan `order_items`. `422 EVENT_DATE_PASSED`, `INVALID_PORTION`, `DUPLICATE_MENU`, `UNKNOWN_MENU`, atau `INVALID_MENU_COMBINATION` jika paket dicampur dengan menu penyusunnya.

Request yang direkam

```http
POST /api/orders
```

```json
{
  "customer_name": "Order uji Sprint 7",
  "order_category": "PRASMANAN_WEDDING",
  "event_date": "2026-11-29",
  "event_location": "Lokasi uji",
  "items": [
    {
      "menu_id": "MNU-W01",
      "confirmed_portions": 40
    }
  ]
}
```

Respons HTTP 201

```json
{
  "order_id": "ORD-2026-2B77E30974CE4248A97DF3A39872E8AD",
  "status": "CONFIRMED",
  "version": 1,
  "created_at": "2026-11-27T12:00:00+07:00"
}
```

Implementasi `OrderService.create`. [Sumber](../../ml/src/sikembang_backend/orders.py).

### 2. `PUT /api/orders/{order_id}`

**Akses** MARKETING sesuai header autentikasi di atas.

Memperbarui pesanan terkonfirmasi. Wajib `order_id` pada path, `version` sama dengan versi terkini, `event_date`, dan `items` berisi daftar menu lengkap pengganti. `event_location` opsional, dapat `null`. Transaksi menambah revisi dan item tanpa menghapus versi sebelumnya. `404 ORDER_NOT_FOUND`, `409 VERSION_CONFLICT` atau `ORDER_REVISION_NOT_AVAILABLE`, `422 ORDER_NOT_CONFIRMED` atau pelanggaran tanggal/menu dari endpoint 1.

Request yang direkam

```http
PUT /api/orders/ORD-2026-2B77E30974CE4248A97DF3A39872E8AD
```

```json
{
  "event_date": "2026-11-29",
  "event_location": "Lokasi uji",
  "items": [
    {
      "menu_id": "MNU-W01",
      "confirmed_portions": 60
    }
  ],
  "version": 1
}
```

Respons HTTP 200

```json
{
  "order_id": "ORD-2026-2B77E30974CE4248A97DF3A39872E8AD",
  "version": 2,
  "updated_at": "2026-11-27T12:00:00+07:00"
}
```

Implementasi `OrderService.revise`. [Sumber](../../ml/src/sikembang_backend/orders.py).

### 3. `GET /api/orders`

**Akses** PPIC, SYSTEM sesuai header autentikasi di atas.

Membaca versi terbaru yang terlihat pada waktu server dari `orders`, `order_revisions`, dan `order_items`. Query `planning_period` wajib dalam bentuk minggu ISO `YYYY-Www`. `status` opsional dengan bawaan `CONFIRMED` dan pilihan `DRAFT`, `CANCELLED`, serta `FULFILLED`. `updated_since` opsional berupa waktu ISO 8601 berzona. `400 VALIDATION_ERROR` jika query salah.

Request yang direkam

```http
GET /api/orders?planning_period=2026-W48
```

Respons HTTP 200 dengan array disingkat

```json
{
  "planning_period": "2026-W48",
  "orders": [
    {
      "order_id": "ORD-2026-2B77E30974CE4248A97DF3A39872E8AD",
      "version": 2,
      "updated_at": "2026-11-27T12:00:00+07:00",
      "customer_name": "Order uji Sprint 7",
      "order_category": "PRASMANAN_WEDDING",
      "event_date": "2026-11-29",
      "event_location": "Lokasi uji",
      "items": [
        {
          "menu_id": "MNU-W01",
          "confirmed_portions": 60
        }
      ]
    }
  ]
}
```

Implementasi `OrderService.list_orders`. [Sumber](../../ml/src/sikembang_backend/orders.py).

### 4. `POST /api/iot/telemetry`

**Akses** DEVICE sesuai header autentikasi di atas.

Mengirim pembacaan untuk sensor yang terdaftar dan aktif. Wajib `sensor_id`, `ingredient_id`, `measured_weight` numerik finit, `unit`, dan `recorded_at` ISO 8601 berzona. Registri yang ditemukan melalui kunci harus cocok dengan kedua ID. Konversi `g` → `kg` dan `ml` → `liter` jika sesuai. Paket boleh tepat 300 detik sebelum penerimaan. Paket diterima membuat audit dan menimpa stok dalam satu transaksi. Penolakan diaudit tanpa mengubah stok. `401 UNAUTHORIZED` untuk kunci, `409 OUT_OF_ORDER_READING` untuk waktu sama atau lebih lama dari sinkron terakhir, serta `422 SENSOR_INGREDIENT_MISMATCH`, `NEGATIVE_VALUE`, `FUTURE_TIMESTAMP`, `STALE_SENSOR_DATA`, atau `UNIT_MISMATCH`.

Request yang direkam

```http
POST /api/iot/telemetry
```

```json
{
  "sensor_id": "SNS-GDG-01",
  "ingredient_id": "ING-001",
  "measured_weight": 17500,
  "unit": "g",
  "recorded_at": "2026-11-27T11:55:00+07:00"
}
```

Respons HTTP 201

```json
{
  "log_id": "TLM-765b44a36b5f40f19755abb2540592c9",
  "validation_status": "ACCEPTED",
  "ingredient_id": "ING-001",
  "stored_value": 17.5,
  "base_unit": "kg",
  "current_stock": 17.5,
  "last_iot_sync": "2026-11-27T11:55:00+07:00"
}
```

Implementasi `InventoryIoTService.ingest`. [Sumber](../../ml/src/sikembang_backend/inventory.py).

### 5. `GET /api/inventory/stock`

**Akses** PPIC, SYSTEM sesuai header autentikasi di atas.

Membaca stok dan safety stock dari `ingredients`. Query `ingredient_ids` opsional berupa nilai dipisahkan koma, misalnya `?ingredient_ids=ING-001,ING-003`. Tanpa filter mengembalikan semua bahan. Stok dianggap `FRESH` jika nilainya tersedia dan usia sinkron antara 0 dan 60 menit. Lainnya `STALE`. `current_stock` dan `last_iot_sync` bisa `null`. `404 UNKNOWN_INGREDIENT` untuk ID yang tidak terdaftar.

Request yang direkam

```http
GET /api/inventory/stock
```

Respons HTTP 200 dengan array disingkat

```json
{
  "as_of": "2026-11-27T12:00:00+07:00",
  "items": [
    {
      "ingredient_id": "ING-001",
      "name": "Beras",
      "current_stock": 17.5,
      "base_unit": "kg",
      "safety_stock": 5,
      "last_iot_sync": "2026-11-27T11:55:00+07:00",
      "stock_status": "FRESH"
    }
  ]
}
```

Implementasi `InventoryIoTService.stock`. [Sumber](../../ml/src/sikembang_backend/inventory.py).

### 6. `POST /api/ai/predict`

**Akses** PPIC, SYSTEM sesuai header autentikasi di atas.

Menjalankan inferensi demand tambahan dan menyimpan `forecast_runs` serta `forecast_run_items`. `target_period` wajib, yaitu minggu ISO saat cutoff atau minggu berikutnya. `ingredient_ids` berupa daftar string opsional. Daftar kosong memakai katalog model. Cutoff ditentukan server atau melalui `SIKEMBANG_DEMO_CUTOFF`. `422 UNKNOWN_INGREDIENT`, `INSUFFICIENT_HISTORY`, `UNSUPPORTED_FORECAST_HORIZON`, `INVALID_FORECAST_INPUT`, `UNIT_MISMATCH`, atau `NEGATIVE_VALUE`. `500 MODEL_UNAVAILABLE` bila artefak gagal dimuat.

Request yang direkam

```http
POST /api/ai/predict
```

```json
{
  "target_period": "2026-W48",
  "ingredient_ids": [
    "ING-001"
  ]
}
```

Respons HTTP 201

```json
{
  "forecast_run_id": "FC-2026-W48-1288cb0965cd484498cff83bfa1a9be1",
  "target_period": "2026-W48",
  "model_version": "xgb-v1-f9a770b940f71fc8",
  "season_flags": {
    "is_ramadan_season": false,
    "is_wedding_season": true,
    "is_year_end": false
  },
  "items": [
    {
      "ingredient_id": "ING-001",
      "predicted_demand": 4.498,
      "base_unit": "kg",
      "prev_error_adj": 0
    }
  ]
}
```

Implementasi `ForecastService.forecast`. [Sumber](../../ml/src/ai_forecast/api.py) · [service inferensi](../../ml/src/ai_forecast/predictor.py).

### 7. `POST /api/procurement/calculate`

**Akses** PPIC sesuai header autentikasi di atas.

Menghitung kebutuhan bersih dan menyimpan draf yang langsung dikembalikan. Wajib `planning_period` (minggu ISO). `include_forecast` boolean opsional dengan bawaan `true`. `false` menjalankan kalkulasi tanpa AI dengan `forecast_run_id` dan `model_version` bernilai `null`. Draf, item, serta run opsional disimpan dalam satu transaksi. `409 ACTIVE_LIST_EXISTS` untuk periode yang sudah memiliki daftar. `422 MISSING_BOM`, `INVENTORY_UNAVAILABLE`, `INVALID_FORECAST_INPUT`, `UNIT_MISMATCH`, `INVALID_PROCUREMENT_INPUT`, atau galat inferensi seperti `INSUFFICIENT_HISTORY`. `500 MODEL_UNAVAILABLE` jika AI diminta saat model gagal dimuat. Stok usang yang masih bernilai menghasilkan peringatan `STALE_STOCK`.

Request yang direkam

```http
POST /api/procurement/calculate
```

```json
{
  "planning_period": "2026-W48",
  "include_forecast": true
}
```

Respons HTTP 201 dengan array disingkat

```json
{
  "list_id": "SL-2026-W48-92cfb8c2dade4d64983db3c78d230152",
  "status": "DRAFT",
  "planning_period": "2026-W48",
  "created_at": "2026-11-27T12:00:00+07:00",
  "items": [
    {
      "ingredient_id": "ING-001",
      "base_unit": "kg",
      "bom_confirmed_need": 69,
      "ai_additional_forecast": 4.498,
      "safety_stock": 5,
      "iot_available_stock": 17.5,
      "stock_status": "FRESH",
      "system_net_recommendation": 60.998
    }
  ],
  "warnings": [
    {
      "code": "STALE_STOCK",
      "ingredient_id": "ING-003",
      "message": "Periksa stok fisik Ayam sebelum menyetujui."
    }
  ],
  "include_forecast": true,
  "forecast_run_id": "FC-2026-W48-dfc3490cd7344926b64ceb1ecd02905e",
  "model_version": "xgb-v1-f9a770b940f71fc8"
}
```

Implementasi `ProcurementCalcService.calculate`. [Sumber](../../ml/src/sikembang_backend/procurement.py).

### 8. `POST /api/shopping-lists`

**Akses** SYSTEM sesuai header autentikasi di atas.

Menyimpan draf eksplisit. `planning_period` dan `items` wajib. Tiap item wajib menyertakan `ingredient_id`, `base_unit`, `bom_confirmed_need`, `ai_additional_forecast`, `safety_stock`, `iot_available_stock`, `stock_status`, dan `system_net_recommendation`. `forecast_run_id` opsional dan dapat `null`. Jika ada, run harus pada periode yang sama dan setiap bahan run harus disertakan dengan satuan, BOM terkonfirmasi dan tambahan forecast yang sama. Bahan tanpa run atau tanpa item forecast harus memiliki nilai tambahan AI nol. Menulis `shopping_lists` dan `shopping_list_items`. `400 VALIDATION_ERROR` untuk item kosong/duplikat, bahan atau satuan salah, rekomendasi tidak sesuai rumus, atau run tidak cocok. `403 FORBIDDEN_ROLE` untuk kunci SYSTEM yang salah atau berimpit dengan registri DEVICE. `409 ACTIVE_LIST_EXISTS` bila periode sudah dipesan.

Request yang direkam

```http
POST /api/shopping-lists
```

```json
{
  "planning_period": "2026-W49",
  "items": [
    {
      "ingredient_id": "ING-001",
      "base_unit": "kg",
      "bom_confirmed_need": 69,
      "ai_additional_forecast": 0,
      "safety_stock": 5,
      "iot_available_stock": 17.5,
      "stock_status": "FRESH",
      "system_net_recommendation": 56.5
    }
  ]
}
```

Respons HTTP 201

```json
{
  "list_id": "SL-2026-W49-97be9981f2744cf9bc8cc6b3d92afdd9",
  "status": "DRAFT"
}
```

Implementasi `DraftService.reserve dan DraftService.populate`. [Sumber](../../ml/src/sikembang_backend/drafts.py).

### 9. `PATCH /api/shopping-lists/{list_id}/approve`

**Akses** PPIC sesuai header autentikasi di atas.

Memvalidasi `list_id` berstatus `DRAFT`. `items` wajib mencakup setiap `ingredient_id` tepat sekali dan `ppic_final_qty` numerik finit nonnegatif. `unit` opsional dengan bawaan satuan dasar. `g` dan `ml` dinormalisasi jika sesuai. `ppic_notes` opsional pada daftar dan item. Catatan item wajib terisi saat stok `STALE`. Transaksi menyimpan keputusan item dan audit PPIC. Seluruh kuantitas nol menghasilkan `procurement_required=false` dengan status `VALIDATED_BY_PPIC`. `404 LIST_NOT_FOUND`, `409 INVALID_STATUS_TRANSITION`, `422 INCOMPLETE_ITEMS`, `NEGATIVE_VALUE`, `UNIT_MISMATCH`, atau `STALE_STOCK_NOTE_REQUIRED`.

Request yang direkam

```http
PATCH /api/shopping-lists/SL-2026-W48-92cfb8c2dade4d64983db3c78d230152/approve
```

```json
{
  "items": [
    {
      "ingredient_id": "ING-001",
      "ppic_final_qty": 42250,
      "unit": "g",
      "ppic_notes": null
    },
    {
      "ingredient_id": "ING-003",
      "ppic_final_qty": 0,
      "unit": "kg",
      "ppic_notes": "Verifikasi stok fixture simulasi"
    },
    {
      "ingredient_id": "ING-007",
      "ppic_final_qty": 0,
      "unit": "butir",
      "ppic_notes": "Verifikasi stok fixture simulasi"
    },
    {
      "ingredient_id": "ING-009",
      "ppic_final_qty": 0,
      "unit": "liter",
      "ppic_notes": "Verifikasi stok fixture simulasi"
    },
    {
      "ingredient_id": "ING-012",
      "ppic_final_qty": 0,
      "unit": "liter",
      "ppic_notes": "Verifikasi stok fixture simulasi"
    }
  ]
}
```

Respons HTTP 200 dengan array disingkat

```json
{
  "list_id": "SL-2026-W48-92cfb8c2dade4d64983db3c78d230152",
  "status": "VALIDATED_BY_PPIC",
  "validated_by": "ppic",
  "validated_at": "2026-11-27T12:00:00+07:00",
  "procurement_required": true,
  "items": [
    {
      "ingredient_id": "ING-001",
      "base_unit": "kg",
      "system_net_recommendation": 60.998,
      "ppic_final_qty": 42.25
    }
  ]
}
```

Implementasi `ShoppingListService.approve`. [Sumber](../../ml/src/sikembang_backend/shopping_lists.py).

### 10. `POST /api/shopping-lists/{list_id}/send`

**Akses** PPIC sesuai header autentikasi di atas.

Meneruskan `list_id` tervalidasi dengan kuantitas final positif. Request tanpa body. Efeknya mengubah status ke `SENT_TO_PFA` dan mencatat `sent_at`. `404 LIST_NOT_FOUND`, `409 INVALID_STATUS_TRANSITION` bila belum disetujui atau sudah dikirim, dan `409 NOTHING_TO_SEND` bila seluruh kuantitas final nol.

Request yang direkam

```http
POST /api/shopping-lists/SL-2026-W48-92cfb8c2dade4d64983db3c78d230152/send
```

Respons HTTP 200

```json
{
  "list_id": "SL-2026-W48-92cfb8c2dade4d64983db3c78d230152",
  "status": "SENT_TO_PFA",
  "sent_at": "2026-11-27T12:00:00+07:00"
}
```

Implementasi `ShoppingListService.send`. [Sumber](../../ml/src/sikembang_backend/shopping_lists.py).

### 11. `GET /api/shopping-lists`

**Akses** PPIC, PFA sesuai header autentikasi di atas.

Membaca daftar dan item beserta nama bahan. Query `status` wajib (`DRAFT`, `VALIDATED_BY_PPIC`, `SENT_TO_PFA`). `planning_period` opsional sebagai filter minggu ISO. PPIC melihat seluruh keputusan serta komponen kalkulasi dan metadata audit. PFA hanya mengakses `SENT_TO_PFA` dengan item final positif. `400 VALIDATION_ERROR` untuk query salah, `403 FORBIDDEN_ROLE` untuk akses yang dilarang.

Request yang direkam

```http
GET /api/shopping-lists?status=SENT_TO_PFA
```

Respons HTTP 200

```json
{
  "lists": [
    {
      "list_id": "SL-2026-W48-92cfb8c2dade4d64983db3c78d230152",
      "planning_period": "2026-W48",
      "status": "SENT_TO_PFA",
      "sent_at": "2026-11-27T12:00:00+07:00",
      "items": [
        {
          "ingredient_id": "ING-001",
          "name": "Beras",
          "base_unit": "kg",
          "ppic_notes": null,
          "ppic_final_qty": 42.25
        }
      ]
    }
  ]
}
```

Implementasi `ShoppingListService.list_by_status`. [Sumber](../../ml/src/sikembang_backend/shopping_lists.py).

## Endpoint pendukung

| Endpoint | Akses | Request | Sukses | Efek dan galat |
| --- | --- | --- | --- | --- |
| `POST /api/auth/login` | Kredensial dashboard | JSON `username` dan `password`, masing-masing 1–128 karakter | `200`, `access_token` dan `token_type: "bearer"`. Header `Cache-Control: no-store` | Baca `users`. `400 VALIDATION_ERROR` atau `401 UNAUTHORIZED`. |
| `GET /api/auth/me` | MARKETING, PPIC, PFA melalui Bearer JWT | Tanpa body atau query | `200`, `username` dan `role` | Memeriksa token dan status akun lewat `users`. `401 UNAUTHORIZED` untuk sesi tidak sah. |
| `GET /api/health` | Publik | Tanpa body atau query | `200`, `status`, `database`, dan `model_version` | Menjalankan `SELECT 1`. Model yang tidak tersedia menghasilkan `model_version: null` saat database sehat. Kegagalan internal memberi `500 INTERNAL_ERROR`. |

Contoh kredensial dan token berikut memakai placeholder.

```json
{
  "username": "ppic",
  "password": "<PASSWORD_LOKAL>"
}
```

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer"
}
```

```json
{
  "username": "ppic",
  "role": "PPIC"
}
```

Respons health Sprint 7

```json
{
  "status": "ok",
  "database": "ok",
  "model_version": "xgb-v1-f9a770b940f71fc8"
}
```

[Router autentikasi](../../ml/src/sikembang_backend/auth.py) · [Router health](../../ml/src/sikembang_backend/app.py).

## Swagger UI

1. Jalankan FastAPI dari [panduan mode live Windows](../../README.md#menjalankan-mode-live-di-windows). Buka `http://127.0.0.1:8000/docs` untuk Swagger UI. Spesifikasi tersedia di `/openapi.json` dan tampilan alternatif di `/redoc`.
2. Buka `POST /api/auth/login` → **Try it out** dan jalankan dengan kredensial lokal. Salin nilai `access_token`. Klik **Authorize**, lalu isi skema **HTTPBearer** dengan JWT tanpa awalan `Bearer`.
3. Gunakan **Try it out** pada endpoint sesuai peran. Untuk DEVICE isi skema **APIKeyHeader** yang mengirim `X-Device-Key`. Untuk SYSTEM isi **SystemKey** hanya selama langkah yang memerlukan otoritas tersebut. Kosongkan SystemKey sebelum mencoba rute baca dengan peran PPIC.
4. Gunakan database khusus demo. `POST /api/procurement/calculate` dan `POST /api/shopping-lists` menyimpan draf dan memakai periode terkait.
