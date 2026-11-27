#pragma once

// Salin ke secrets.h dan isi konfigurasi lokal. secrets.h tidak masuk Git.
namespace ScaleConfig {
constexpr char wifiSsid[] = "REPLACE_WITH_WIFI_SSID";
constexpr char wifiPassword[] = "REPLACE_WITH_WIFI_PASSWORD";
constexpr char backendBaseUrl[] = "http://LAN_IPV4:8000"; // IPv4 privat laptop (RFC 1918), tanpa garis miring penutup.
constexpr char deviceKey[] = "REPLACE_WITH_REGISTERED_DEVICE_KEY";
constexpr char sensorId[] = "SNS-GDG-ESP32-01";
constexpr char ingredientId[] = "ING-001"; // Beras, satuan dasar kg. Verifikasi pemetaan backend.
constexpr char ntpPrimary[] = "pool.ntp.org";
constexpr char ntpSecondary[] = "time.google.com";

constexpr float calibrationFactor = -120.0f; // Faktor sementara dari firmware asli.
constexpr float stabilitySpreadGrams = 3.0f;
constexpr float reportingChangeGrams = 10.0f;
constexpr float zeroToleranceGrams = 0.0f; // Aktifkan hanya setelah toleransi nol terukur.
constexpr unsigned long heartbeatMs = 60000;
constexpr unsigned long minimumReportIntervalMs = 2000;
}
