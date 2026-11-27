# Arsitektur frontend SIkembang

Frontend ini hanya berbicara dengan satu hal: kontrak REST API. AI layer dan data layer (SQL) berada
di balik API dan tidak diketahui oleh UI. Karena itu backend boleh ditulis dengan stack apa pun
(FastAPI, Express, Spring, Laravel, dan sebagainya) selama kontraknya sama.

```
UI (features/*, components/*)
   |  hanya memakai hook dan tipe domain camelCase
   v
api/queries.ts + api/services/   <- satu fungsi per endpoint
   |
api/http.ts  (fetch, token, galat, timeout)  +  api/case.ts (snake <-> camel)
   |
api/contracts/  <- skema Zod bentuk data backend (satu-satunya tempat)
   |
REST API backend  (atau MSW di api/mocks/ saat VITE_API_MODE=mock)
```

## Aturan lapisan

1. Komponen di `features/` dan `components/` tidak pernah memanggil `fetch` dan tidak tahu nama
   atribut snake_case. Mereka memakai hook dari `api/queries.ts` atau service dari `api/services`.
2. Kontrak data divalidasi runtime dengan Zod. Skema draf mencakup komponen kalkulasi yang diperlukan
   tabel PPIC. Skema daftar terkirim juga menerima proyeksi PFA dengan kuantitas final, satuan, dan nama.
3. Logika keputusan bisnis di sisi UI (mis. tolak rekomendasi AI) ditulis sebagai fungsi murni di
   `features/*/decisions.ts` dan dites dengan Vitest.
4. Semua warna, ukuran teks, dan radius berasal dari `styles/tokens.css`. Jangan menulis nilai
   mentah (`#fff`, `text-[13px]`) di komponen.

## Mengganti atau menambah backend

| Perbedaan backend                             | Yang diubah                                              |
| --------------------------------------------- | -------------------------------------------------------- |
| Base URL berbeda                              | `VITE_API_BASE_URL` di `.env`                            |
| Casing atribut berbeda (mis. sudah camelCase) | `api/case.ts`                                            |
| Nama atribut atau path berbeda                | `api/contracts/index.ts` dan `api/services/index.ts`     |
| Autentikasi berbeda (cookie, OAuth)           | `configureAuth()` di `api/http.ts` dan `app/session.tsx` |
| Format galat berbeda                          | `api/http.ts` (bagian `!res.ok`) dan `api/errors.ts`     |
| CORS saat dev                                 | isi `VITE_DEV_PROXY_TARGET`                              |

## Endpoint yang dipakai (Bab 9 laporan)

| Layar                    | Endpoint                                                                                                                 |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Marketing: catat pesanan | `POST /api/orders`                                                                                                       |
| PPIC: perencanaan        | `GET /api/orders`, `GET /api/inventory/stock`, `POST /api/procurement/calculate`, `GET /api/shopping-lists?status=DRAFT` |
| PPIC: tinjau dan setujui | `GET /api/shopping-lists` untuk draf dan daftar disetujui, `PATCH /api/shopping-lists/{id}/approve`, `POST /api/shopping-lists/{id}/send` |
| PFA: permintaan masuk    | `GET /api/shopping-lists?status=SENT_TO_PFA`                                                                             |
| Simulator demo           | `POST /api/iot/telemetry` (header `X-Device-Key`)                                                                        |

Forecast dan penyimpanan draf dipanggil antarlayanan dari `POST /api/procurement/calculate`.
`PUT /api/orders/{id}` tersedia melalui `ordersApi.update`, dan layar Marketing saat ini menyediakan
formulir pencatatan pesanan.

## Sesi dan alur live

- Login mengirim kredensial ke `/api/auth/login`, menyimpan JWT per tab, lalu membaca otorisasi melalui
  `/api/auth/me`. Reload memulihkan sesi melalui server. Logout dan sesi kedaluwarsa menghapus token
  serta cache kueri identitas sebelumnya.
- Mock memakai MSW dan pemilih peran demo. Saat origin dialihkan ke live, bootstrap melepaskan worker
  MSW sebelum memuat UI dan menggunakan Vite proxy `/api` untuk FastAPI.
- PPIC menyetujui draf sebelum mengirim. Daftar tervalidasi tetap dapat dikirim ulang setelah galat
  jaringan atau reload. Jika seluruh kuantitas nol, halaman menampilkan status tanpa pengadaan.
- PFA memakai satu respons daftar terkirim. Nama, satuan, kuantitas final positif, serta catatan item
  yang diteruskan berasal dari proyeksi tersebut.

## Menolak rekomendasi AI

Kontrak API tidak memiliki kolom khusus penolakan AI. Pendekatan saat ini tanpa mengubah backend:

- Mode `REJECT_AI` menghitung ulang `ppic_final_qty = max(0, bom_confirmed_need + safety_stock - iot_available_stock)`
  di UI (tanpa `ai_additional_forecast`), lalu PPIC tetap boleh mengetik angka sendiri.
- Alasan penolakan dikirim sebagai awalan `ppic_notes`: `[AI ditolak: <alasan>] <catatan>`.
- `system_net_recommendation` tetap dikembalikan backend sebagai pembanding audit.

Usulan untuk tim backend bila ingin penelusuran yang lebih rapi: tambahkan atribut `ai_decision`
(`ACCEPTED`, `EDITED`, `REJECTED`) dan `ai_reject_reason` pada item `approve`. Setelah itu cukup ubah
`toApproveItems` di `features/review/decisions.ts`.

## Keputusan desain

- Tombol dan highlight memakai fill kontras tinggi, bukan stroke. Outline hanya untuk fokus keyboard.
- Ukuran teks hanya 12/14/16 px, radius hanya 8/12/16 px. Hierarki dibangun lewat weight (Figtree untuk
  judul, tombol, label; Open Sans untuk isi).
- Token berlabel "turunan" di `tokens.css` (soft tint, `error-strong`, `success-strong`) bukan bagian
  dari palet asli. Dipakai agar teks kecil lolos kontras AA.
- Input tanpa border memakai fill `n-100` di atas kartu putih. Rasio kontras batas input terhadap
  latar sekitar 1,4:1, di bawah 3:1 yang disarankan WCAG 1.4.11. Jika tim ingin patuh penuh,
  tambahkan garis bawah 2 px pada `Input` di `components/ui/index.tsx`.
