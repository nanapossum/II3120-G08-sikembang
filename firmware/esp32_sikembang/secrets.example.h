#pragma once

// ============================================================================
// KONFIGURASI RAHASIA LOKAL ESP32 SIKEMBANG
// Salin file ini menjadi "secrets.h" di folder yang sama lalu isi nilainya.
// File "secrets.h" sudah terdaftar di .gitignore agar tidak ikut ter-commit.
// ============================================================================

#define WIFI_SSID  "NAMA_WIFI_ANDA"
#define WIFI_PASS  "PASSWORD_WIFI_ANDA"

// IPv4 LAN laptop tempat FastAPI (Uvicorn) berjalan, TANPA '/' di akhir.
// Contoh: "http://192.168.1.10:8000"
#define SERVER_URL "http://192.168.1.10:8000"

// Kunci perangkat (min. 32 karakter visible ASCII) yang sama dengan
// SIKEMBANG_DEVICE_ESP32_KEY saat menjalankan register-physical-rice.
#define DEVICE_KEY "GANTI_DENGAN_SIKEMBANG_DEVICE_ESP32_KEY_MIN_32_KARAKTER"
