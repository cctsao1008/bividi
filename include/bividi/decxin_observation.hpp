#pragma once

#include "bividi/decxin.hpp"
#include "bividi/observation.hpp"

#include <string>

namespace bividi::decxin {

// Context owned above the device decoder. Physical left/right naming remains
// deliberately absent until #35 supplies measured camera mapping evidence.
struct ObservationContext {
    std::string source_id;
    EvidenceKind evidence = EvidenceKind::unknown;
    std::uint64_t continuity_epoch = 0;
    ContinuityState continuity = ContinuityState::continuous;
    CalibrationIdentity calibration{};
    std::string configuration_revision;
    std::string camera_a_stream_id = "camera_a";
    std::string camera_b_stream_id = "camera_b";
    std::string camera_clock_id = "decxin.camera";
    std::string imu_clock_id = "decxin.imu";
};

// Convert a leased DECXIN decode result into the platform-independent #11
// observation contract. Raw IMU counts/timestamps are preserved; SI values are
// intentionally left unavailable until an explicit measured/imported inertial
// calibration owns that conversion.
[[nodiscard]] SensorObservation to_sensor_observation(
    const DecodedFrame& decoded,
    const ObservationContext& context);

}  // namespace bividi::decxin
