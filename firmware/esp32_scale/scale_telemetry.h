#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>

namespace scale_telemetry {

class RawWindow {
public:
    void clear() {
        count_ = 0;
        next_ = 0;
    }

    void add(int32_t raw) {
        values_[next_] = raw;
        next_ = (next_ + 1) % sampleCount;
        if (count_ < sampleCount) {
            ++count_;
        }
    }

    bool full() const {
        return count_ == sampleCount;
    }

    double average() const {
        int64_t sum = 0;
        for (uint8_t i = 0; i < count_; ++i) {
            sum += values_[i];
        }
        return count_ ? static_cast<double>(sum) / count_ : 0.0;
    }

    bool isStable(float calibrationFactor, float maxSpreadGrams) const {
        if (!full()) {
            return false;
        }
        int32_t low = values_[0];
        int32_t high = values_[0];
        for (uint8_t i = 1; i < count_; ++i) {
            if (values_[i] < low) {
                low = values_[i];
            }
            if (values_[i] > high) {
                high = values_[i];
            }
        }
        return (static_cast<double>(high) - low) / std::fabs(calibrationFactor) <= maxSpreadGrams;
    }

private:
    static constexpr uint8_t sampleCount = 5;
    int32_t values_[sampleCount]{};
    uint8_t count_ = 0;
    uint8_t next_ = 0;
};

struct Measurement {
    Measurement(float weight = 0.0f, uint32_t sampledAt = 0, int64_t utc = 0,
                uint32_t clockVersion = 0, uint32_t sensorVersion = 0)
        : grams(weight), sampledAtMs(sampledAt), utcMicros(utc),
          clockGeneration(clockVersion), sensorGeneration(sensorVersion) {}

    bool isCurrent(uint32_t currentClockGeneration, uint32_t currentSensorGeneration,
                   uint32_t now, uint32_t maxAgeMs) const {
        return currentClockGeneration != 0 && clockGeneration == currentClockGeneration &&
               sensorGeneration == currentSensorGeneration && now - sampledAtMs <= maxAgeMs;
    }

    float grams;
    uint32_t sampledAtMs;
    int64_t utcMicros;
    uint32_t clockGeneration;
    uint32_t sensorGeneration;
};

class ClockSyncState {
public:
    void begin() {
        enabled_ = true;
        synced_ = false;
    }

    void end() {
        enabled_ = false;
        synced_ = false;
    }

    void recordSync(bool valid, uint32_t nowSeconds) {
        if (!enabled_) {
            return;
        }
        synced_ = valid;
        if (synced_) {
            if (++generation_ == 0) {
                ++generation_;
            }
            lastSyncSecond_ = nowSeconds;
        }
    }

    uint32_t currentGeneration(uint32_t nowSeconds, uint32_t maxAgeSeconds) const {
        return synced_ && nowSeconds - lastSyncSecond_ < maxAgeSeconds ? generation_ : 0;
    }

private:
    bool enabled_ = false;
    bool synced_ = false;
    uint32_t generation_ = 0;
    uint32_t lastSyncSecond_ = 0;
};

class TareButton {
public:
    bool poll(bool pressed, uint32_t now, uint32_t holdMs) {
        if (!pressed) {
            armed_ = true;
            pressing_ = false;
            return false;
        }
        if (!armed_) {
            return false;
        }
        if (!pressing_) {
            pressing_ = true;
            pressedAt_ = now;
        }
        if (now - pressedAt_ < holdMs) {
            return false;
        }
        armed_ = false;
        return true;
    }

private:
    bool armed_ = false;
    bool pressing_ = false;
    uint32_t pressedAt_ = 0;
};

inline bool telemetryWeight(float grams, float zeroToleranceGrams, float &value) {
    if (!std::isfinite(grams) || grams < -zeroToleranceGrams) {
        return false;
    }
    value = grams < 0.0f ? 0.0f : grams;
    return true;
}

inline bool plausibleUtc(int64_t utcMicros) {
    return utcMicros >= 1735689600000000LL && utcMicros < 4102444800000000LL; // 2025-01-01 to 2100-01-01 UTC
}

inline bool formatUtcTimestamp(char *output, size_t size, bool clockSynced, int64_t utcMicros) {
    if (!clockSynced || !plausibleUtc(utcMicros) || size < 28) {
        return false;
    }
    const int64_t wholeSeconds = utcMicros / 1000000;
    const time_t seconds = static_cast<time_t>(wholeSeconds);
    if (static_cast<int64_t>(seconds) != wholeSeconds) {
        return false;
    }
    struct tm utc{};
#ifdef _WIN32
    if (gmtime_s(&utc, &seconds) != 0) {
#else
    if (gmtime_r(&seconds, &utc) == nullptr) {
#endif
        return false;
    }
    if (std::strftime(output, size, "%Y-%m-%dT%H:%M:%S", &utc) != 19) {
        return false;
    }
    return std::snprintf(output + 19, size - 19, ".%06ldZ", static_cast<long>(utcMicros % 1000000)) == 8;
}

inline bool isDeviceId(const char *id) {
    const size_t size = std::strlen(id);
    if (size == 0 || size > 64) {
        return false;
    }
    for (; *id; ++id) {
        if (!((*id >= 'a' && *id <= 'z') || (*id >= 'A' && *id <= 'Z') ||
              (*id >= '0' && *id <= '9') || *id == '-' || *id == '_')) {
            return false;
        }
    }
    return true;
}

inline bool isDeviceKey(const char *key) {
    const size_t size = std::strlen(key);
    if (size < 32 || size > 256) {
        return false;
    }
    for (; *key; ++key) {
        if (*key < 0x21 || *key > 0x7e) {
            return false;
        }
    }
    return true;
}

inline bool formatPayload(char *output, size_t size, const char *sensorId, const char *ingredientId,
                          const Measurement &reading, bool clockSynced) {
    char timestamp[28];
    if (!isDeviceId(sensorId) || !isDeviceId(ingredientId) ||
        !std::isfinite(reading.grams) || reading.grams < 0.0f ||
        !formatUtcTimestamp(timestamp, sizeof(timestamp), clockSynced, reading.utcMicros)) {
        return false;
    }
    const int written = std::snprintf(output, size,
        "{\"sensor_id\":\"%s\",\"ingredient_id\":\"%s\",\"measured_weight\":%.9g,\"unit\":\"g\",\"recorded_at\":\"%s\"}",
        sensorId, ingredientId, static_cast<double>(reading.grams), timestamp);
    return written > 0 && static_cast<size_t>(written) < size;
}

inline bool isBackendUrl(const char *url) {
    const char prefix[] = "http://";
    if (std::strncmp(url, prefix, sizeof(prefix) - 1) != 0) {
        return false;
    }
    const char *part = url + sizeof(prefix) - 1;
    unsigned octets[4]{};
    for (uint8_t i = 0; i < 4; ++i) {
        const char *start = part;
        while (*part >= '0' && *part <= '9' && part - start < 3) {
            octets[i] = octets[i] * 10 + (*part++ - '0');
        }
        if (part == start || (part - start > 1 && *start == '0') || octets[i] > 255) {
            return false;
        }
        if (i < 3 && *part++ != '.') {
            return false;
        }
    }
    const bool privateAddress = octets[0] == 10 || (octets[0] == 192 && octets[1] == 168) ||
        (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31);
    if (!privateAddress) {
        return false;
    }
    if (*part == '\0') {
        return true;
    }
    if (*part++ != ':') {
        return false;
    }
    unsigned port = 0;
    for (uint8_t i = 0; i < 5 && *part >= '0' && *part <= '9'; ++i) {
        port = port * 10 + (*part++ - '0');
    }
    return *part == '\0' && port > 0 && port <= 65535;
}

class ReportHistory {
public:
    bool isDue(const Measurement &reading, uint32_t now, float changeGrams, uint32_t heartbeatMs,
               uint32_t minimumIntervalMs) const {
        if (!accepted_) {
            return true;
        }
        const uint32_t elapsed = now - lastAcceptedAtMs_;
        return reading.utcMicros > lastAccepted_.utcMicros && elapsed >= minimumIntervalMs &&
               (std::fabs(reading.grams - lastAccepted_.grams) >= changeGrams || elapsed >= heartbeatMs);
    }

    void accept(const Measurement &reading, uint32_t now) {
        accepted_ = true;
        lastAccepted_ = reading;
        lastAcceptedAtMs_ = now;
    }

private:
    bool accepted_ = false;
    Measurement lastAccepted_{};
    uint32_t lastAcceptedAtMs_ = 0;
};

} // namespace scale_telemetry
