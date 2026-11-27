/*
 * SiKembang IoT Smart Scale Firmware (ESP32 DevKit + HX711 + OLED SSD1306)
 *
 * Kredensial Wi-Fi, URL server, dan X-Device-Key dibaca dari "secrets.h".
 * Salin "secrets.example.h" menjadi "secrets.h" sebelum upload ke ESP32.
 */

// ============================================================================
// BAGIAN 1: KONFIGURASI UTAMA (EDIT SESUAI PERANGKAT & KALIBRASI ANDA)
// ============================================================================
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

// Identitas perangkat & bahan (wajib cocok dengan registrasi di backend SQLite)
static const char* SENSOR_ID       = "SNS-GDG-ESP32-01";
static const char* INGREDIENT_ID   = "ING-001";
static const char* INGREDIENT_NAME = "Beras";

// Faktor kalibrasi Load Cell 20kg (ubah sesuai hasil kalibrasi beban referensi)
static const float CALIBRATION_FACTOR = -120.0f;

// Server NTP untuk sinkronisasi timestamp UTC (wajib untuk field recorded_at)
static const char* NTP_SERVER_1 = "pool.ntp.org";
static const char* NTP_SERVER_2 = "time.google.com";

// ============================================================================
// BAGIAN 2: SPESIFIKASI HARDWARE & PARAMETER SENSOR (JANGAN UBAH PINOUT)
// ============================================================================
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <math.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

// Pinout HX711 (Load Cell 20kg)
static const int HX711_DOUT_PIN = 32;
static const int HX711_SCK_PIN  = 33;

// Pinout OLED SSD1306 128x64 I2C (alamat 0x3C)
static const int     OLED_SDA_PIN  = 25;
static const int     OLED_SCL_PIN  = 26;
static const uint8_t OLED_I2C_ADDR = 0x3C;
static const int     OLED_WIDTH    = 128;
static const int     OLED_HEIGHT   = 64;

// Pinout tombol fisik Tare (INPUT_PULLUP, aktif LOW)
static const int TARE_BUTTON_PIN = 27;

// Parameter kestabilan sensor berat
static const uint8_t  HX711_AVG_SAMPLES       = 3;      // scale.get_units(3)
static const float    AUTO_ZERO_DRIFT_G       = 1.5f;   // Auto-zero jika drift < 1.5 g
static const float    AUTO_ZERO_MIN_TRIGGER_G = 0.05f;  // Hindari tare berulang saat sudah tepat 0.0 g
static const uint8_t  AUTO_ZERO_COUNTER_LIMIT = 15;     // Counter non-blocking sebelum auto-zero
static const float    DEADBAND_G              = 0.5f;   // Deadband 0.5 gram

// Parameter pengiriman telemetri & jaringan
static const float         WEIGHT_DELTA_THRESHOLD_G = 2.0f;    // Kirim jika selisih > 2.0 g
static const unsigned long HEARTBEAT_INTERVAL_MS    = 5000UL;  // Heartbeat setiap 5 detik
static const unsigned long SEND_COOLDOWN_MS         = 1800UL;  // Cooldown 1.8 dtk (cegah 409)
static const unsigned long ERROR_RETRY_COOLDOWN_MS  = 3000UL;  // Jeda retry saat server/jaringan gagal
static const uint16_t      HTTP_TIMEOUT_MS          = 2000;    // Timeout HTTP maksimal 2000 ms
static const unsigned long WIFI_RECONNECT_MS        = 5000UL;  // Interval auto-reconnect Wi-Fi
static const unsigned long SAMPLE_INTERVAL_MS       = 150UL;   // Interval pembacaan load cell
static const unsigned long DISPLAY_INTERVAL_MS      = 200UL;   // Refresh rate OLED
static const unsigned long TARE_DEBOUNCE_MS         = 60UL;    // Debounce tombol tare
static const time_t        MIN_VALID_EPOCH          = 1735689600L; // 2025-01-01T00:00:00Z

// ============================================================================
// BAGIAN 3: OBJEK PERANGKAT & STATE GLOBAL
// ============================================================================
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);
HX711 scale;

bool          oledReady         = false;
bool          sensorReady       = false;
bool          secretsValid      = false;
bool          ntpConfigured     = false;
bool          hasSentOnce       = false;
float         currentWeightG    = 0.0f;
float         lastSentWeightG   = 0.0f;
int64_t       lastSentUtcMicros = 0;
uint8_t       driftCounter      = 0;

unsigned long lastSampleMs      = 0;
unsigned long lastDisplayMs     = 0;
unsigned long lastWifiRetryMs   = 0;
unsigned long lastSendAttemptMs = 0;
unsigned long lastSuccessSendMs = 0;
unsigned long lastSensorOkMs    = 0;
unsigned long tareNoticeUntilMs = 0;

// State tombol tare non-blocking
bool          lastButtonReading = HIGH;
bool          stableButtonState = HIGH;
unsigned long lastDebounceMs    = 0;

// Status koneksi & HTTP untuk tampilan OLED
int  lastHttpCode = 0;
char netStatusText[24] = "Offline";

// ============================================================================
// BAGIAN 4: UTILITAS KONFIGURASI, WAKTU (NTP), DAN JARINGAN
// ============================================================================
bool checkSecretsConfigured() {
  if (WIFI_SSID[0] == '\0' || strcmp(WIFI_SSID, "NAMA_WIFI_ANDA") == 0) {
    return false;
  }
  if (SERVER_URL[0] == '\0' || strncmp(SERVER_URL, "http://", 7) != 0) {
    return false;
  }
  if (strlen(DEVICE_KEY) < 32 || strncmp(DEVICE_KEY, "GANTI_DENGAN_", 13) == 0) {
    return false;
  }
  return true;
}

bool isNtpSynced() {
  struct timeval tv;
  if (gettimeofday(&tv, nullptr) != 0) {
    return false;
  }
  return tv.tv_sec >= MIN_VALID_EPOCH;
}

bool formatUtcIso8601(char* outBuf, size_t outLen, int64_t& utcMicrosOut) {
  struct timeval tv;
  if (gettimeofday(&tv, nullptr) != 0 || tv.tv_sec < MIN_VALID_EPOCH) {
    return false;
  }
  struct tm utcTm;
  if (gmtime_r(&tv.tv_sec, &utcTm) == nullptr) {
    return false;
  }
  utcMicrosOut = static_cast<int64_t>(tv.tv_sec) * 1000000LL + static_cast<int64_t>(tv.tv_usec);
  int written = snprintf(
    outBuf,
    outLen,
    "%04d-%02d-%02dT%02d:%02d:%02d.%06ldZ",
    utcTm.tm_year + 1900,
    utcTm.tm_mon + 1,
    utcTm.tm_mday,
    utcTm.tm_hour,
    utcTm.tm_min,
    utcTm.tm_sec,
    static_cast<long>(tv.tv_usec)
  );
  return written > 0 && static_cast<size_t>(written) < outLen;
}

void setNetStatus(const char* status) {
  snprintf(netStatusText, sizeof(netStatusText), "%s", status);
}

void maintainWifiAndNtp(unsigned long now) {
  if (!secretsValid) {
    setNetStatus("Isi secrets.h!");
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    ntpConfigured = false;
    setNetStatus("Offline");
    if (now - lastWifiRetryMs >= WIFI_RECONNECT_MS) {
      lastWifiRetryMs = now;
      Serial.println("[WiFi] Menghubungkan ulang ke Wi-Fi...");
      WiFi.disconnect(false);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
    }
    return;
  }

  if (!ntpConfigured) {
    ntpConfigured = true;
    configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);
    Serial.print("[WiFi] Terhubung, IP: ");
    Serial.println(WiFi.localIP());
    Serial.println("[NTP] Memulai sinkronisasi jam UTC...");
  }

  if (!isNtpSynced()) {
    setNetStatus("NTP Sync...");
  } else if (lastHttpCode == 0) {
    setNetStatus("NTP OK | Ready");
  }
}

// ============================================================================
// BAGIAN 5: SENSOR BERAT (HX711) & TOMBOL TARE NON-BLOCKING
// ============================================================================
void performManualTare(unsigned long now) {
  Serial.println("[Scale] Tombol Tare ditekan -> melakukan tare...");
  if (scale.wait_ready_timeout(500)) {
    scale.tare(5);
    driftCounter   = 0;
    currentWeightG = 0.0f;
    tareNoticeUntilMs = now + 1200UL;
    Serial.println("[Scale] Tare selesai (0.0 g).");
  } else {
    Serial.println("[Scale] Tare gagal: HX711 belum siap.");
  }
}

void pollTareButton(unsigned long now) {
  bool reading = digitalRead(TARE_BUTTON_PIN);
  if (reading != lastButtonReading) {
    lastDebounceMs = now;
    lastButtonReading = reading;
  }
  if ((now - lastDebounceMs) >= TARE_DEBOUNCE_MS) {
    if (reading != stableButtonState) {
      stableButtonState = reading;
      if (stableButtonState == LOW) {
        performManualTare(now);
      }
    }
  }
}

void updateWeightReading(unsigned long now) {
  if (now - lastSampleMs < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleMs = now;

  if (!scale.is_ready()) {
    if (now - lastSensorOkMs >= 2000UL) {
      sensorReady = false;
    }
    return;
  }

  sensorReady = true;
  lastSensorOkMs = now;

  // Pembacaan rata-rata 3 sampel (sesuai logika stabil hardware)
  float rawWeight = scale.get_units(HX711_AVG_SAMPLES);
  if (!isfinite(rawWeight)) {
    return;
  }

  // Auto-zero non-blocking berbasis counter jika sisa drift di bawah 1.5 gram
  if (fabs(rawWeight) < AUTO_ZERO_DRIFT_G) {
    if (fabs(rawWeight) >= AUTO_ZERO_MIN_TRIGGER_G) {
      driftCounter++;
      if (driftCounter >= AUTO_ZERO_COUNTER_LIMIT) {
        if (scale.is_ready()) {
          scale.tare(3);
          rawWeight = 0.0f;
          Serial.println("[Scale] Auto-zero drift diterapkan.");
        }
        driftCounter = 0;
      }
    } else {
      driftCounter = 0;
    }
  } else {
    driftCounter = 0;
  }

  // Deadband 0.5 gram untuk meredam fluktuasi kecil di sekitar nol
  float filteredWeight = (fabs(rawWeight) < DEADBAND_G) ? 0.0f : rawWeight;

  // Clamp >= 0.0f agar tidak pernah mengirim angka negatif (422 NEGATIVE_VALUE)
  float clampedWeight = fmaxf(0.0f, filteredWeight);
  currentWeightG = (clampedWeight <= 0.0f) ? 0.0f : clampedWeight;
}

// ============================================================================
// BAGIAN 6: PENGIRIMAN HTTP POST TELEMETRI KE BACKEND FASTAPI
// ============================================================================
void maybeSendTelemetry(unsigned long now) {
  if (!secretsValid || !sensorReady || WiFi.status() != WL_CONNECTED) {
    return;
  }

  // Wajib tunggu NTP sinkron sebelum mengirim POST agar recorded_at valid
  if (!isNtpSynced()) {
    setNetStatus("NTP Sync...");
    return;
  }

  // Cooldown minimum antar-kirim (1.8 detik) untuk mencegah 409 OUT_OF_ORDER_READING
  bool lastFailed = (lastHttpCode != 0 && lastHttpCode != 201 && lastHttpCode != 200);
  unsigned long requiredGap = lastFailed ? ERROR_RETRY_COOLDOWN_MS : SEND_COOLDOWN_MS;
  if (lastSendAttemptMs != 0 && (now - lastSendAttemptMs) < requiredGap) {
    return;
  }

  float weightToSend = fmaxf(0.0f, currentWeightG);
  if (!isfinite(weightToSend)) {
    return;
  }

  bool deltaTriggered     = !hasSentOnce || (fabs(weightToSend - lastSentWeightG) > WEIGHT_DELTA_THRESHOLD_G);
  bool heartbeatTriggered = (now - lastSuccessSendMs) >= HEARTBEAT_INTERVAL_MS;
  if (!deltaTriggered && !heartbeatTriggered) {
    return;
  }

  char recordedAt[32];
  int64_t utcMicros = 0;
  if (!formatUtcIso8601(recordedAt, sizeof(recordedAt), utcMicros)) {
    setNetStatus("NTP Sync...");
    return;
  }

  // Pastikan timestamp selalu strictly increasing dibanding pengiriman sukses terakhir
  if (utcMicros <= lastSentUtcMicros) {
    return;
  }

  // Payload JSON 100% cocok dengan skema Pydantic TelemetryRequest
  char payload[256];
  int written = snprintf(
    payload,
    sizeof(payload),
    "{\"sensor_id\":\"%s\",\"ingredient_id\":\"%s\",\"measured_weight\":%.1f,\"unit\":\"g\",\"recorded_at\":\"%s\"}",
    SENSOR_ID,
    INGREDIENT_ID,
    static_cast<double>(weightToSend),
    recordedAt
  );
  if (written <= 0 || static_cast<size_t>(written) >= sizeof(payload)) {
    setNetStatus("ERR Payload");
    return;
  }

  String endpoint = String(SERVER_URL) + "/api/iot/telemetry";
  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.setReuse(false);

  lastSendAttemptMs = now;
  if (!http.begin(client, endpoint)) {
    lastHttpCode = -1;
    setNetStatus("ERR -1");
    Serial.println("[HTTP] Gagal memulai koneksi ke backend.");
    return;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);

  int httpCode = http.POST(reinterpret_cast<uint8_t*>(payload), static_cast<size_t>(written));
  lastHttpCode = httpCode;

  if (httpCode == 201 || httpCode == 200) {
    hasSentOnce       = true;
    lastSentWeightG   = weightToSend;
    lastSentUtcMicros = utcMicros;
    lastSuccessSendMs = millis();

    char okBuf[20];
    snprintf(okBuf, sizeof(okBuf), "%d OK", httpCode);
    setNetStatus(okBuf);
    Serial.printf("[HTTP] %d OK | %.1f g (%.3f kg) | %s\n",
                  httpCode, weightToSend, weightToSend / 1000.0f, recordedAt);
  } else {
    String errBody = (httpCode > 0) ? http.getString() : "";
    char errBuf[20];
    if (httpCode > 0) {
      snprintf(errBuf, sizeof(errBuf), "HTTP %d", httpCode);
    } else {
      snprintf(errBuf, sizeof(errBuf), "ERR %d", httpCode);
    }
    setNetStatus(errBuf);
    Serial.printf("[HTTP] Gagal (%d): %s\n", httpCode, errBody.c_str());
  }

  http.end();
}

// ============================================================================
// BAGIAN 7: TAMPILAN OLED SSD1306 (128x64)
// ============================================================================
void renderOled(unsigned long now) {
  if (!oledReady || (now - lastDisplayMs) < DISPLAY_INTERVAL_MS) {
    return;
  }
  lastDisplayMs = now;

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  // Baris 1: Nama bahan & ID bahan
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.printf("%s (%s)", INGREDIENT_NAME, INGREDIENT_ID);
  display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);

  // Baris 2: Berat aktual dalam gram (font besar)
  display.setTextSize(2);
  display.setCursor(0, 15);
  if (!sensorReady) {
    display.print("HX711 ERR");
  } else if (now < tareNoticeUntilMs) {
    display.print("TARE OK");
  } else {
    display.printf("%.1f g", currentWeightG);
  }

  // Baris 3: Konversi berat dalam kilogram
  display.setTextSize(1);
  display.setCursor(0, 35);
  if (sensorReady) {
    display.printf("= %.3f kg", currentWeightG / 1000.0f);
  } else {
    display.print("Periksa kabel HX711");
  }

  // Baris 4: ID perangkat
  display.setCursor(0, 46);
  display.printf("ID:%s", SENSOR_ID);

  // Baris 5: Status Wi-Fi / NTP / HTTP code terakhir
  display.setCursor(0, 56);
  display.printf("NET: %s", netStatusText);

  display.display();
}

// ============================================================================
// BAGIAN 8: SETUP & LOOP UTAMA
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n=== SiKembang ESP32 Smart Scale ===");

  pinMode(TARE_BUTTON_PIN, INPUT_PULLUP);

  // Inisialisasi I2C & OLED SSD1306 sesuai pinout hardware
  Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);
  Wire.setClock(400000);
  oledReady = display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR, true, false);
  if (oledReady) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("SiKembang IoT Scale");
    display.setCursor(0, 16);
    display.println("Inisialisasi sensor...");
    display.display();
  } else {
    Serial.println("[OLED] SSD1306 tidak terdeteksi di alamat 0x3C.");
  }

  // Inisialisasi HX711
  scale.begin(HX711_DOUT_PIN, HX711_SCK_PIN);
  scale.set_scale(CALIBRATION_FACTOR);
  if (scale.wait_ready_timeout(1500)) {
    sensorReady = true;
    lastSensorOkMs = millis();
    scale.tare(5);
    Serial.println("[Scale] HX711 siap & tare awal selesai.");
  } else {
    sensorReady = false;
    Serial.println("[Scale] HX711 belum merespons saat boot.");
  }

  // Inisialisasi Wi-Fi secara non-blocking agar OLED langsung berjalan
  secretsValid = checkSecretsConfigured();
  if (secretsValid) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.persistent(false);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    lastWifiRetryMs = millis();
    setNetStatus("Offline");
    Serial.printf("[WiFi] Menghubungkan ke %s...\n", WIFI_SSID);
  } else {
    setNetStatus("Isi secrets.h!");
    Serial.println("[Config] Salin secrets.example.h ke secrets.h dan isi kredensial Anda.");
  }
}

void loop() {
  unsigned long now = millis();

  pollTareButton(now);
  updateWeightReading(now);
  maintainWifiAndNtp(now);
  maybeSendTelemetry(now);
  renderOled(now);

  delay(10);
}
