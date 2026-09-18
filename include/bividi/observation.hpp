#pragma once

#include "bividi/capabilities.hpp"
#include "bividi/capture.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace bividi {

inline constexpr std::uint32_t kObservationContractVersion = 1;

enum class EvidenceKind {
    unknown,
    synthetic,
    measured,
    imported,
};

enum class ObservationValidity {
    valid,
    degraded,
    invalid,
};

enum class SourceState {
    available,
    disconnected,
    error,
};

enum class ContinuityState {
    continuous,
    discontinuity,
    reinitialized,
};

enum class ClockDomain {
    unknown,
    host_monotonic,
    device,
    replay,
};

enum class TimeUnit {
    unknown,
    nanoseconds,
    microseconds,
};

// One explicit point on one named clock. Different clock domains are never
// collapsed into a single timestamp field.
struct TimePoint {
    std::uint64_t ticks = 0;
    TimeUnit unit = TimeUnit::unknown;
    ClockDomain domain = ClockDomain::unknown;
    std::string clock_id;
    bool present = false;

    [[nodiscard]] bool structurally_valid() const noexcept {
        return !present || (unit != TimeUnit::unknown && domain != ClockDomain::unknown && !clock_id.empty());
    }
};

// Optional preservation of the finite-width timestamp representation that was
// extended into TimePoint. It is evidence, not the normalized comparison clock.
struct RawTimestampEvidence {
    std::uint64_t raw_ticks = 0;
    std::uint8_t bit_width = 0;
    TimeUnit unit = TimeUnit::unknown;
    std::string clock_id;
    bool present = false;

    [[nodiscard]] bool structurally_valid() const noexcept {
        return !present || (bit_width != 0 && bit_width <= 64 && unit != TimeUnit::unknown && !clock_id.empty());
    }
};

struct ExposureTiming {
    TimePoint start{};
    TimePoint end{};
    RawTimestampEvidence raw_start{};
    RawTimestampEvidence raw_end{};

    [[nodiscard]] bool complete() const noexcept {
        return start.present && end.present;
    }
};

struct CalibrationIdentity {
    std::string stereo;
    std::string imu;
    std::string camera_imu;
};

struct ObservationTiming {
    TimePoint host_receive{};
    TimePoint replay_schedule{};
};

struct CameraObservation {
    std::string stream_id;
    FrameLease lease{};
    ImageView image{};
    ExposureTiming exposure{};
    ObservationValidity validity = ObservationValidity::invalid;

    [[nodiscard]] bool usable() const noexcept {
        return validity != ObservationValidity::invalid && lease.valid() && !image.empty();
    }
};

// IMU observations may carry raw counts and/or calibrated SI values. This lets
// calibration/replay preserve evidence without inventing an unverified scale,
// while downstream VIO can explicitly require si_valid=true.
struct ImuObservation {
    std::string sensor_id = "imu0";
    TimePoint sample_time{};
    RawTimestampEvidence raw_time{};

    std::array<std::int32_t, 3> accel_raw_counts{};
    std::array<std::int32_t, 3> gyro_raw_counts{};
    bool raw_valid = false;

    std::array<double, 3> accel_m_s2{};
    std::array<double, 3> gyro_rad_s{};
    bool si_valid = false;

    ObservationValidity validity = ObservationValidity::invalid;
};

struct SensorObservation {
    std::uint32_t contract_version = kObservationContractVersion;
    std::string source_id;
    EvidenceKind evidence = EvidenceKind::unknown;
    SourceState source_state = SourceState::available;
    ObservationValidity validity = ObservationValidity::invalid;

    std::uint64_t sequence = 0;
    std::uint64_t continuity_epoch = 0;
    ContinuityState continuity = ContinuityState::continuous;

    ObservationTiming timing{};
    CalibrationIdentity calibration{};
    std::string configuration_revision;

    std::vector<CameraObservation> cameras;
    std::vector<ImuObservation> imu;
};

struct ConformanceResult {
    bool ok = true;
    std::vector<std::string> errors;

    void add_error(std::string error) {
        ok = false;
        errors.push_back(std::move(error));
    }
};

[[nodiscard]] ConformanceResult validate_capabilities(const SensorCapabilities& capabilities);
[[nodiscard]] ConformanceResult validate_observation(
    const SensorObservation& observation,
    const SensorCapabilities* capabilities = nullptr);

}  // namespace bividi
