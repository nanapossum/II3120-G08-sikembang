#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_sntp.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <sys/time.h>

#include <atomic>
#include "scale_telemetry.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

using namespace scale_telemetry;
using namespace ScaleConfig;

constexpr int oledSda = 25;
constexpr int oledScl = 26;
constexpr uint8_t oledAddress = 0x3C;
constexpr int loadCellDoutPin = 32;
constexpr int loadCellSckPin = 33;
constexpr int tareButtonPin = 27;
constexpr uint32_t tareHoldMs = 1000;
constexpr uint32_t tareTimeoutMs = 5000;
constexpr uint32_t hx711TimeoutMs = 1500;
constexpr uint32_t displayIntervalMs = 250;
constexpr uint32_t sampleMaxAgeMs = 2000;
constexpr uint32_t wifiAttemptTimeoutMs = 12000;
constexpr uint32_t clockWaitNoticeMs = 15000;
constexpr uint32_t clockSyncMaxAgeSeconds = 2UL * 60 * 60;
constexpr uint32_t retryMinimumMs = 2000;
constexpr uint32_t retryMaximumMs = 30000;
constexpr uint16_t httpTimeoutMs = 3000;
constexpr int skippedPost = INT32_MIN;
constexpr int32_t unsetOffset = INT32_MIN;
constexpr int32_t hx711Minimum = -8388608;
constexpr int32_t hx711Maximum = 8388607;

static_assert(calibrationFactor != 0.0f, "Calibration factor must be nonzero");
static_assert(stabilitySpreadGrams > 0.0f, "Stability spread must be positive");
static_assert(reportingChangeGrams > 0.0f, "Reporting change must be positive");
static_assert(zeroToleranceGrams >= 0.0f, "Calibrated zero tolerance must be nonnegative");
static_assert(minimumReportIntervalMs > 0 && heartbeatMs >= minimumReportIntervalMs,
              "Heartbeat must allow the minimum reporting interval");

enum class NetworkStatus {
    ConfigRequired,
    Offline,
    Connecting,
    ClockSync,
    ClockTimeout,
    Ready,
    Accepted,
    Unauthorized,
    Invalid,
    Conflict,
    HttpTimeout,
    HttpError
};

Adafruit_SSD1306 display(128, 64, &Wire, -1);
HX711 scale;
Preferences preferences;
RawWindow samples;
TareButton tareButton;
QueueHandle_t latestMeasurement = nullptr;
std::atomic<const char *> networkLabel{"Konfigurasi Wi-Fi/API"};
std::atomic<uint32_t> sensorGeneration{1};
portMUX_TYPE clockLock = portMUX_INITIALIZER_UNLOCKED;
ClockSyncState clockState;
NetworkStatus currentNetworkStatus = NetworkStatus::ConfigRequired;

bool oledReady = false;
bool preferencesReady = false;
bool tareInProgress = false;
bool haveWeight = false;
bool negativeWeight = false;
bool hx711SignalInvalid = false;
int32_t rawOffset = unsetOffset;
uint32_t tareStartedAt = 0;
uint32_t lastSampleAt = 0;
uint32_t lastDisplayAt = 0;
uint32_t lastTareFailureAt = 0;
bool showTareFailure = false;
float displayGrams = 0.0f;

// Explicit declarations keep the Arduino sketch preprocessor from generating
// prototypes before the status and measurement types.
void setNetworkStatus(NetworkStatus status, const char *label);
void onClockSync(struct timeval *time);
int64_t utcMicroseconds(const struct timeval &time);
bool canPost(const Measurement &reading);
int postTelemetry(const String &endpoint, const Measurement &reading);
void recordHttpResult(int code);
void readScale(uint32_t now);

void setNetworkStatus(NetworkStatus status, const char *label) {
    if (currentNetworkStatus != status) {
        currentNetworkStatus = status;
        networkLabel.store(label);
        Serial.printf("[Jaringan] %s\n", label);
    }
}

bool networkConfigured() {
    return wifiSsid[0] != '\0' && std::strncmp(wifiSsid, "REPLACE_", 8) != 0 &&
        std::strncmp(wifiPassword, "REPLACE_", 8) != 0 &&
        isDeviceKey(deviceKey) && std::strncmp(deviceKey, "REPLACE_", 8) != 0 &&
        isBackendUrl(backendBaseUrl) && isDeviceId(sensorId) && isDeviceId(ingredientId);
}

uint32_t nextRetryDelay(uint32_t previousMs) {
    if (previousMs == 0) {
        return retryMinimumMs;
    }
    return previousMs < retryMaximumMs / 2 ? previousMs * 2 : retryMaximumMs;
}

int64_t utcMicroseconds(const struct timeval &time) {
    return static_cast<int64_t>(time.tv_sec) * 1000000 + time.tv_usec;
}

uint32_t uptimeSeconds() {
    return static_cast<uint32_t>(esp_timer_get_time() / 1000000);
}

void onClockSync(struct timeval *time) {
    const bool valid = time != nullptr && plausibleUtc(utcMicroseconds(*time));
    const uint32_t nowSeconds = uptimeSeconds();
    portENTER_CRITICAL(&clockLock);
    clockState.recordSync(valid, nowSeconds);
    portEXIT_CRITICAL(&clockLock);
}

uint32_t synchronizedClockGeneration() {
    const uint32_t nowSeconds = uptimeSeconds();
    portENTER_CRITICAL(&clockLock);
    const uint32_t generation = clockState.currentGeneration(nowSeconds, clockSyncMaxAgeSeconds);
    portEXIT_CRITICAL(&clockLock);
    return generation;
}

void suspendClock() {
    portENTER_CRITICAL(&clockLock);
    clockState.end();
    portEXIT_CRITICAL(&clockLock);
    xQueueReset(latestMeasurement);
    esp_sntp_stop();
}

void startClock() {
    portENTER_CRITICAL(&clockLock);
    clockState.begin();
    portEXIT_CRITICAL(&clockLock);
    configTime(0, 0, ntpPrimary, ntpSecondary);
}

bool canPost(const Measurement &reading) {
    return WiFi.status() == WL_CONNECTED &&
        reading.isCurrent(synchronizedClockGeneration(), sensorGeneration.load(), millis(), sampleMaxAgeMs);
}

int postTelemetry(const String &endpoint, const Measurement &reading) {
    char payload[320];
    if (!canPost(reading)) {
        return skippedPost;
    }
    if (!formatPayload(payload, sizeof(payload), sensorId, ingredientId, reading, true)) {
        return 0; // Invalid local payload. No request has been sent.
    }
    WiFiClient connection;
    HTTPClient request;
    request.setConnectTimeout(httpTimeoutMs);
    request.setTimeout(httpTimeoutMs);
    request.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
    request.setReuse(false);
    if (!request.begin(connection, endpoint)) {
        return HTTPC_ERROR_CONNECTION_REFUSED;
    }
    request.addHeader("Content-Type", "application/json");
    request.addHeader("X-Device-Key", deviceKey);
    const int status = canPost(reading)
        ? request.POST(reinterpret_cast<uint8_t *>(payload), std::strlen(payload))
        : skippedPost;
    request.end();
    return status;
}

void recordHttpResult(int code) {
    Serial.printf("[HTTP] Status %d\n", code);
    if (code == 201) {
        setNetworkStatus(NetworkStatus::Accepted, "Telemetri OK");
    } else if (code == 401 || code == 403) {
        setNetworkStatus(NetworkStatus::Unauthorized, "Autentikasi gagal");
    } else if (code == 0 || code == 400 || code == 422) {
        setNetworkStatus(NetworkStatus::Invalid, "Telemetri ditolak");
    } else if (code == 409) {
        setNetworkStatus(NetworkStatus::Conflict, "Konflik waktu");
    } else if (code == HTTPC_ERROR_READ_TIMEOUT || code == 408 || code == 504) {
        setNetworkStatus(NetworkStatus::HttpTimeout, "Waktu HTTP habis");
    } else {
        setNetworkStatus(NetworkStatus::HttpError, "Koneksi/API gagal");
    }
}

void networkTask(void *) {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(false);
    esp_sntp_set_time_sync_notification_cb(onClockSync);
    const String endpoint = String(backendBaseUrl) + "/api/iot/telemetry";
    ReportHistory reportHistory;
    bool online = false;
    bool connecting = false;
    bool clockStarted = false;
    bool clockWasReady = false;
    uint32_t wifiAttemptAt = 0;
    uint32_t wifiWaitStartedAt = 0;
    uint32_t wifiRetryDelay = 0;
    uint32_t clockAttemptAt = 0;
    uint32_t lastHttpAttemptAt = 0;
    uint32_t httpRetryDelay = 0;

    for (;;) {
        const uint32_t now = millis();
        if (WiFi.status() != WL_CONNECTED) {
            if (online) {
                online = false;
                clockStarted = false;
                clockWasReady = false;
                suspendClock();
                setNetworkStatus(NetworkStatus::Offline, "Wi-Fi terputus");
            }
            if (connecting && now - wifiAttemptAt >= wifiAttemptTimeoutMs) {
                WiFi.disconnect();
                connecting = false;
                wifiWaitStartedAt = now;
                wifiRetryDelay = nextRetryDelay(wifiRetryDelay);
                setNetworkStatus(NetworkStatus::Offline, "Wi-Fi gagal");
            }
            if (!connecting && now - wifiWaitStartedAt >= wifiRetryDelay) {
                setNetworkStatus(NetworkStatus::Connecting, "Wi-Fi menghubung");
                WiFi.begin(wifiSsid, wifiPassword);
                connecting = true;
                wifiAttemptAt = millis();
            }
        } else {
            if (!online) {
                online = true;
                connecting = false;
                wifiRetryDelay = 0;
                clockAttemptAt = now;
                Serial.printf("[Jaringan] Wi-Fi terhubung, IPv4 %s\n", WiFi.localIP().toString().c_str());
                setNetworkStatus(NetworkStatus::ClockSync, "Sinkronisasi NTP");
            }
            // esp_sntp_stop is asynchronous. Wait for the previous session to stop.
            if (!clockStarted && !esp_sntp_enabled()) {
                startClock();
                clockStarted = true;
            }
            if (synchronizedClockGeneration() != 0) {
                if (!clockWasReady) {
                    clockWasReady = true;
                    setNetworkStatus(NetworkStatus::Ready, "Jam UTC siap");
                }
                Measurement reading{};
                if (now - lastHttpAttemptAt >= httpRetryDelay &&
                    xQueuePeek(latestMeasurement, &reading, 0) == pdTRUE) {
                    const uint32_t checkedAt = millis();
                    if (canPost(reading) &&
                        reportHistory.isDue(reading, checkedAt, reportingChangeGrams, heartbeatMs,
                                            minimumReportIntervalMs)) {
                        const int status = postTelemetry(endpoint, reading);
                        if (status != skippedPost) {
                            lastHttpAttemptAt = millis();
                            recordHttpResult(status);
                            if (status == 201) {
                                httpRetryDelay = 0;
                                reportHistory.accept(reading, lastHttpAttemptAt);
                            } else {
                                httpRetryDelay = nextRetryDelay(httpRetryDelay);
                            }
                        }
                    }
                }
            } else if (clockWasReady || now - clockAttemptAt >= clockWaitNoticeMs) {
                clockWasReady = false;
                setNetworkStatus(NetworkStatus::ClockTimeout, "NTP belum sinkron");
            }
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

void discardMeasurement() {
    ++sensorGeneration;
    if (latestMeasurement != nullptr) {
        xQueueReset(latestMeasurement);
    }
}

void resetMeasurements() {
    discardMeasurement();
    samples.clear();
    haveWeight = false;
    negativeWeight = false;
}

void endTare(uint32_t now) {
    tareInProgress = false;
    showTareFailure = true;
    lastTareFailureAt = now;
    resetMeasurements();
    Serial.println("[Timbangan] Tare gagal. Periksa sinyal, kestabilan, atau penyimpanan.");
}

void checkTareButton(uint32_t now) {
    if (tareButton.poll(digitalRead(tareButtonPin) == LOW, now, tareHoldMs) && !tareInProgress) {
        tareInProgress = true;
        tareStartedAt = now;
        showTareFailure = false;
        resetMeasurements();
        Serial.println("[Timbangan] Tare manual. Platform harus kosong.");
    }
    if (tareInProgress && now - tareStartedAt >= tareTimeoutMs) {
        endTare(now);
    }
    if (showTareFailure && now - lastTareFailureAt >= 3000) {
        showTareFailure = false;
    }
}

void readScale(uint32_t now) {
    if (!scale.is_ready()) {
        if (now - lastSampleAt >= hx711TimeoutMs && !hx711SignalInvalid) {
            hx711SignalInvalid = true;
            resetMeasurements();
            Serial.println("[Timbangan] HX711 belum siap");
        }
        return;
    }

    const uint32_t clockGeneration = synchronizedClockGeneration();
    const int32_t raw = scale.read(); // DOUT is already low. Read exactly one conversion.
    const uint32_t sampledAt = millis();
    struct timeval sampledUtc{};
    const bool timestampAvailable = clockGeneration != 0 && gettimeofday(&sampledUtc, nullptr) == 0 &&
        clockGeneration == synchronizedClockGeneration();
    lastSampleAt = sampledAt;
    if (raw <= hx711Minimum || raw >= hx711Maximum) {
        const bool wasInvalid = hx711SignalInvalid;
        hx711SignalInvalid = true;
        resetMeasurements();
        if (!wasInvalid) {
            Serial.println("[Timbangan] Sinyal HX711 di batas ADC");
        }
        return;
    }
    hx711SignalInvalid = false;
    samples.add(raw);
    const bool stable = samples.isStable(calibrationFactor, stabilitySpreadGrams);
    if (tareInProgress) {
        if (stable) {
            const int32_t newOffset = static_cast<int32_t>(std::lround(samples.average()));
            if (!preferencesReady || preferences.putLong("offset", newOffset) != sizeof(newOffset)) {
                endTare(sampledAt);
                return;
            }
            rawOffset = newOffset;
            tareInProgress = false;
            resetMeasurements();
            Serial.println("[Timbangan] Tare disimpan");
        }
        return;
    }
    if (rawOffset == unsetOffset) {
        return;
    }

    displayGrams = static_cast<float>((samples.average() - rawOffset) / calibrationFactor);
    haveWeight = std::isfinite(displayGrams);
    float measuredGrams = 0.0f;
    const bool weightValid = telemetryWeight(displayGrams, zeroToleranceGrams, measuredGrams);
    const bool wasNegative = negativeWeight;
    negativeWeight = displayGrams < 0 && !weightValid;
    if (latestMeasurement != nullptr) {
        const int64_t utcMicros = utcMicroseconds(sampledUtc);
        if (stable && weightValid && timestampAvailable && plausibleUtc(utcMicros)) {
            const Measurement reading{measuredGrams, sampledAt, utcMicros, clockGeneration, sensorGeneration.load()};
            xQueueOverwrite(latestMeasurement, &reading);
        } else {
            discardMeasurement();
        }
    }
    if (stable && negativeWeight && !wasNegative) {
        Serial.printf("[Timbangan] Berat negatif ditolak: %.2f g\n", displayGrams);
    }
}

void renderScale() {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.print("STOK GUDANG (IoT)");
    display.drawFastHLine(0, 10, 128, SSD1306_WHITE);
    display.setCursor(0, 20);
    display.setTextSize(2);
    if (haveWeight) {
        display.print(displayGrams, 1);
        display.print(" g");
    } else {
        display.print("-- g");
    }
    display.setTextSize(1);
    display.setCursor(0, 41);
    if (tareInProgress) {
        display.print("Tare kosong...");
    } else if (hx711SignalInvalid) {
        display.print("Periksa HX711");
    } else if (showTareFailure) {
        display.print("Tare gagal");
    } else if (rawOffset == unsetOffset) {
        display.print("Kosongkan, tahan tare");
    } else if (negativeWeight) {
        display.print("Berat negatif");
    } else if (haveWeight) {
        display.print(displayGrams < 50.0f ? "Stok kosong/min" : "Stok terpantau");
    }
    display.setCursor(0, 55);
    display.print(networkLabel.load());
    display.display();
}

void setup() {
    Serial.begin(115200);
    pinMode(tareButtonPin, INPUT_PULLUP);
    Wire.begin(oledSda, oledScl);
    Wire.setClock(400000);
    oledReady = display.begin(SSD1306_SWITCHCAPVCC, oledAddress, true, false);
    if (!oledReady) {
        Serial.println("[Timbangan] OLED tidak terdeteksi");
    }
    scale.begin(loadCellDoutPin, loadCellSckPin);
    lastSampleAt = millis();
    preferencesReady = preferences.begin("scale6e", false);
    if (preferencesReady) {
        rawOffset = preferences.getLong("offset", unsetOffset);
        if (rawOffset <= hx711Minimum || rawOffset >= hx711Maximum) {
            rawOffset = unsetOffset;
        }
    }
    Serial.println(rawOffset == unsetOffset ? "[Timbangan] Kosongkan platform, lalu tahan tombol tare 1 detik."
                                           : "[Timbangan] Offset tare tersimpan dipakai.");
    if (!networkConfigured()) {
        Serial.println("[Jaringan] Isi secrets.h untuk mengaktifkan telemetri.");
    } else {
        latestMeasurement = xQueueCreate(1, sizeof(Measurement));
        if (latestMeasurement == nullptr ||
            xTaskCreate(networkTask, "telemetry", 8192, nullptr, 1, nullptr) != pdPASS) {
            networkLabel.store("Tugas jaringan gagal");
            Serial.println("[Jaringan] Gagal memulai tugas telemetri.");
        }
    }
}

void loop() {
    const uint32_t now = millis();
    checkTareButton(now);
    readScale(now);
    if (oledReady && now - lastDisplayAt >= displayIntervalMs) {
        lastDisplayAt = now;
        renderScale();
    }
    delay(5);
}
