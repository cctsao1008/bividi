#pragma once

#include "bividi/observation.hpp"

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace bividi {

enum class VioCameraTimeReference {
    exposure_start,
    exposure_midpoint,
    exposure_end,
};

enum class VioPacketState {
    ready,
    reset_required,
    rejected,
};

enum class VioResetDirective {
    none,
    reinitialize,
    reset_before_next,
};

enum class VioTrackingState {
    uninitialized,
    initializing,
    tracking,
    lost,
    rejected,
};

struct VioAdapterConfig {
    std::string camera_a_stream_id = "camera_a";
    std::string camera_b_stream_id = "camera_b";
    std::string stereo_pair_id = "stereo0";
    VioCameraTimeReference camera_time_reference = VioCameraTimeReference::exposure_midpoint;
};

struct VioCameraFrame {
    std::string stream_id;
    FrameLease lease{};
    ImageView image{};
};

struct VioStereoFrame {
    VioCameraFrame camera_a{};
    VioCameraFrame camera_b{};
    TimePoint reference_time{};
};

struct VioImuSample {
    TimePoint sample_time{};
    std::array<double, 3> accel_m_s2{};
    std::array<double, 3> gyro_rad_s{};
};

struct VioPacket {
    VioPacketState state = VioPacketState::rejected;
    VioResetDirective reset = VioResetDirective::none;
    std::string reason;

    std::string source_id;
    EvidenceKind evidence = EvidenceKind::unknown;
    std::uint64_t sequence = 0;
    bool sequence_present = false;
    std::uint64_t continuity_epoch = 0;
    ContinuityState continuity = ContinuityState::continuous;

    CalibrationIdentity calibration{};
    std::string configuration_revision;
    VioCameraTimeReference camera_time_reference = VioCameraTimeReference::exposure_midpoint;
    VioStereoFrame stereo{};
    std::vector<VioImuSample> imu;

    [[nodiscard]] bool backend_ready() const noexcept {
        return state == VioPacketState::ready;
    }
};

// Derived result only. The transform convention is world_from_body: position
// and quaternion place the VIO body frame in the backend-defined world frame.
// Timestamp is the camera reference timestamp from the packet, never host time.
struct PoseObservation {
    TimePoint timestamp{};
    std::array<double, 3> position_world_m{};
    std::array<double, 4> orientation_world_from_body_xyzw{{0.0, 0.0, 0.0, 1.0}};
    std::array<double, 3> velocity_world_m_s{};
    VioTrackingState tracking = VioTrackingState::uninitialized;
    ObservationValidity validity = ObservationValidity::invalid;

    CalibrationIdentity calibration{};
    std::string configuration_revision;
    std::string backend_id;
    std::string backend_version;
    std::uint64_t continuity_epoch = 0;
    std::uint64_t source_sequence = 0;
    bool source_sequence_present = false;
};

struct VioPoseValidation {
    bool ok = true;
    std::string error;
};

[[nodiscard]] VioPoseValidation validate_pose_observation(const PoseObservation& pose);

class VioInputAdapter {
public:
    explicit VioInputAdapter(VioAdapterConfig config = {});

    [[nodiscard]] VioPacket adapt(const SensorObservation& observation);
    void reset() noexcept;

    [[nodiscard]] const VioAdapterConfig& config() const noexcept { return config_; }

private:
    VioAdapterConfig config_{};
    std::optional<std::uint64_t> active_epoch_;
};

class VioBackend {
public:
    virtual ~VioBackend() = default;
    virtual void reset(std::uint64_t continuity_epoch) = 0;
    [[nodiscard]] virtual PoseObservation process(const VioPacket& packet) = 0;
};

}  // namespace bividi
