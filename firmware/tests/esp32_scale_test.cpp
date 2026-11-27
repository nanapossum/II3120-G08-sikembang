#include "../esp32_scale/scale_telemetry.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <limits>

using namespace scale_telemetry;

void raw_window_requires_five_consistent_samples() {
    RawWindow window;
    for (int32_t raw : {-1000, -1024, -988, -1012}) {
        window.add(raw);
    }
    assert(!window.isStable(-120.0f, 3.0f));
    window.add(-1000);
    assert(window.isStable(-120.0f, 3.0f));
    assert(window.average() == -1004.8);

    window.add(-2200);
    assert(!window.isStable(-120.0f, 3.0f));
    for (int i = 0; i < 4; ++i) {
        window.add(-2200);
    }
    assert(window.isStable(-120.0f, 3.0f));
    assert(window.average() == -2200);
    window.clear();
    assert(!window.isStable(-120.0f, 3.0f));
}

void telemetry_rejects_invalid_weights_and_only_normalizes_calibrated_drift() {
    float grams = -99.0f;
    assert(telemetryWeight(4500.25f, 0.0f, grams));
    assert(grams == 4500.25f);
    assert(telemetryWeight(0.0f, 0.0f, grams));
    assert(!telemetryWeight(-0.01f, 0.0f, grams));
    assert(!telemetryWeight(-0.6f, 0.5f, grams));
    assert(telemetryWeight(-0.5f, 0.5f, grams));
    assert(grams == 0.0f);
    assert(!telemetryWeight(std::numeric_limits<float>::infinity(), 0.5f, grams));
    assert(!telemetryWeight(std::numeric_limits<float>::quiet_NaN(), 0.5f, grams));
}

void timestamps_require_sntp_and_preserve_microseconds() {
    char output[32];
    assert(!formatUtcTimestamp(output, sizeof(output), false, 1767225600123456LL));
    assert(!formatUtcTimestamp(output, sizeof(output), true, 0));
    assert(!formatUtcTimestamp(output, sizeof(output), true, 4102444800000000LL));
    assert(!formatUtcTimestamp(output, 27, true, 1767225600123456LL));
    assert(formatUtcTimestamp(output, sizeof(output), true, 1767225600123456LL));
    assert(std::strcmp(output, "2026-01-01T00:00:00.123456Z") == 0);
    assert(formatUtcTimestamp(output, sizeof(output), true, 1767225600123457LL));
    assert(std::strcmp(output, "2026-01-01T00:00:00.123457Z") == 0);
}

void reporting_uses_acknowledged_weight_and_wrap_safe_time() {
    ReportHistory history;
    assert(history.isDue({4500.0f, 0, 1767225600000000LL}, 0, 10.0f, 60000, 2000));
    history.accept({4500.0f, 0, 1767225600000000LL}, 0);

    assert(!history.isDue({4500.0f, 59999, 1767225600000001LL}, 59999, 10.0f, 60000, 2000));
    assert(history.isDue({4500.0f, 60000, 1767225600000002LL}, 60000, 10.0f, 60000, 2000));
    assert(!history.isDue({4510.0f, 1999, 1767225600000003LL}, 1999, 10.0f, 60000, 2000));
    assert(!history.isDue({4509.0f, 2000, 1767225600000004LL}, 2000, 10.0f, 60000, 2000));
    assert(history.isDue({4510.0f, 2000, 1767225600000005LL}, 2000, 10.0f, 60000, 2000));
    assert(!history.isDue({4510.0f, 2000, 1767225600000000LL}, 2000, 10.0f, 60000, 2000));
    assert(!history.isDue({4510.0f, 2000, 1767225599999999LL}, 2000, 10.0f, 60000, 2000));

    history.accept({4500.0f, UINT32_MAX - 999, 1767225600000000LL}, UINT32_MAX - 999);
    assert(!history.isDue({4490.0f, 999, 1767225600000001LL}, 999, 10.0f, 60000, 2000));
    assert(history.isDue({4490.0f, 1000, 1767225600000001LL}, 1000, 10.0f, 60000, 2000));
}

void payload_contains_actual_weight_and_utc_in_api_schema() {
    char output[320];
    const Measurement reading{4500.25f, 0, 1767225600123456LL};
    assert(formatPayload(output, sizeof(output), "SNS-GDG-ESP32-01", "ING-001", reading, true));
    assert(std::strcmp(output,
        "{\"sensor_id\":\"SNS-GDG-ESP32-01\",\"ingredient_id\":\"ING-001\","
        "\"measured_weight\":4500.25,\"unit\":\"g\",\"recorded_at\":\"2026-01-01T00:00:00.123456Z\"}") == 0);
    assert(!formatPayload(output, sizeof(output), "SNS-GDG-ESP32-01", "ING-001", reading, false));
    assert(!formatPayload(output, sizeof(output), "SNS\"bad", "ING-001", reading, true));
    assert(!formatPayload(output, sizeof(output), "SNS-GDG-ESP32-01", "ING-001",
        {-1.0f, 0, 1767225600123456LL}, true));
}

void backend_url_must_use_a_private_lan_ipv4_address() {
    assert(isBackendUrl("http://192.168.18.42:8000"));
    assert(isBackendUrl("http://10.20.30.40"));
    assert(isBackendUrl("http://172.16.0.1:8000"));
    assert(isBackendUrl("http://172.31.255.254"));
    assert(!isBackendUrl("http://172.15.0.1"));
    assert(!isBackendUrl("http://172.32.0.1"));
    assert(!isBackendUrl("http://100.64.0.7:8000"));
    assert(!isBackendUrl("http://1.1.1.1:8000"));
    assert(!isBackendUrl("http://LOCALHOST:8000"));
    assert(!isBackendUrl("http://127.0.0.1:8000"));
    assert(!isBackendUrl("http://127.5.6.7:8000"));
    assert(!isBackendUrl("http://0.0.0.0:8000"));
    assert(!isBackendUrl("http://192.168.18.256:8000"));
    assert(!isBackendUrl("http://192.168.18.42:65536"));
    assert(!isBackendUrl("http://192.168.18.42:0"));
    assert(!isBackendUrl("http://192.168.18.42:8000/path"));
    assert(!isBackendUrl("http://192.168.18.42:8000@localhost"));
    assert(!isBackendUrl("https://192.168.18.42:8000"));
}

void device_key_matches_the_backend_visible_ascii_contract() {
    char key[258];
    std::memset(key, 'k', sizeof(key));
    key[31] = '\0';
    assert(!isDeviceKey(key));
    key[31] = '!';
    key[32] = '\0';
    assert(isDeviceKey(key));
    key[7] = ' ';
    assert(!isDeviceKey(key));
    key[7] = '\r';
    assert(!isDeviceKey(key));
    key[7] = '\x7f';
    assert(!isDeviceKey(key));
    key[7] = '\xc3';
    assert(!isDeviceKey(key));
    key[7] = '~';
    key[32] = 'k';
    key[256] = '\0';
    assert(isDeviceKey(key));
    key[256] = 'k';
    key[257] = '\0';
    assert(!isDeviceKey(key));
}

void reconnect_requires_fresh_sntp_and_invalidates_old_measurements() {
    ClockSyncState clock;
    assert(clock.currentGeneration(0, 7200) == 0);
    clock.begin();
    assert(clock.currentGeneration(1, 7200) == 0);
    clock.recordSync(true, 1);
    const uint32_t original = clock.currentGeneration(1, 7200);
    assert(original != 0);
    assert(clock.currentGeneration(7201, 7200) == 0);

    clock.end();
    clock.recordSync(true, 2);
    assert(clock.currentGeneration(2, 7200) == 0);
    clock.begin();
    assert(clock.currentGeneration(3, 7200) == 0);
    clock.recordSync(false, 3);
    assert(clock.currentGeneration(3, 7200) == 0);
    clock.recordSync(true, 4);
    const uint32_t reconnected = clock.currentGeneration(4, 7200);
    assert(reconnected != 0 && reconnected != original);
    clock.recordSync(true, 5);
    const uint32_t resynced = clock.currentGeneration(5, 7200);
    assert(resynced != 0 && resynced != reconnected);

    const Measurement queued{4500.0f, 4000, 1767225600000000LL, reconnected, 11};
    assert(queued.isCurrent(reconnected, 11, 5999, 2000));
    assert(!queued.isCurrent(reconnected, 11, 6001, 2000));
    assert(!queued.isCurrent(resynced, 11, 4000, 2000));
    assert(!queued.isCurrent(reconnected, 12, 4000, 2000));
    assert(!queued.isCurrent(0, 11, 4000, 2000));
}

void tare_button_held_at_boot_requires_a_release_and_fresh_hold() {
    TareButton tare;
    assert(!tare.poll(true, 1, 1000));
    assert(!tare.poll(true, 1500, 1000));
    assert(!tare.poll(false, 1600, 1000));
    assert(!tare.poll(true, 1700, 1000));
    assert(!tare.poll(true, 2699, 1000));
    assert(tare.poll(true, 2700, 1000));
    assert(!tare.poll(true, 5000, 1000));
    assert(!tare.poll(false, 5100, 1000));
    assert(!tare.poll(true, 5200, 1000));
    assert(!tare.poll(false, 5300, 1000));
    assert(!tare.poll(true, 5400, 1000));
    assert(tare.poll(true, 6400, 1000));
}

int main() {
    raw_window_requires_five_consistent_samples();
    telemetry_rejects_invalid_weights_and_only_normalizes_calibrated_drift();
    timestamps_require_sntp_and_preserve_microseconds();
    reporting_uses_acknowledged_weight_and_wrap_safe_time();
    payload_contains_actual_weight_and_utc_in_api_schema();
    backend_url_must_use_a_private_lan_ipv4_address();
    device_key_matches_the_backend_visible_ascii_contract();
    reconnect_requires_fresh_sntp_and_invalidates_old_measurements();
    tare_button_held_at_boot_requires_a_release_and_fresh_hold();
    std::puts("ESP32 scale policy tests passed");
}
