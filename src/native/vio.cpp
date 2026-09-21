#include "bividi/vio.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace bividi {
namespace {

VioPacket rejected_packet(const SensorObservation& observation, const VioAdapterConfig& config, std::string reason) {
    VioPacket packet{};
    packet.state = VioPacketState::rejected;
    packet.reason = std::move(reason);
    packet.source_id = observation.source_id;
    packet.evidence = observation.evidence;
    packet.sequence = observation.sequence;
    packet.sequence_present = observation.sequence_present;
    packet.continuity_epoch = observation.continuity_epoch;
    packet.continuity = observation.continuity;
    packet.calibration = observation.calibration;
    packet.configuration_revision = observation.configuration_revision;
    packet.camera_time_reference = config.camera_time_reference;
    return packet;
}

bool nonempty_calibration(const CalibrationIdentity& calibration) {
    return !calibration.stereo.empty() && !calibration.imu.empty() && !calibration.camera_imu.empty();
}

bool same_clock(const TimePoint& a, const TimePoint& b) {
    return a.present && b.present &&
           a.domain == b.domain &&
           a.unit == b.unit &&
           a.clock_id == b.clock_id;
}

bool is_device_time(const TimePoint& time) {
    return time.present &&
           time.domain == ClockDomain::device &&
           time.unit != TimeUnit::unknown &&
           !time.clock_id.empty();
}

std::optional<TimePoint> camera_reference_time(
    const CameraObservation& camera,
    VioCameraTimeReference reference) {
    const auto& start = camera.exposure.start;
    const auto& end = camera.exposure.end;
    if (!is_device_time(start) || !is_device_time(end) || !same_clock(start, end) || end.ticks < start.ticks) {
        return std::nullopt;
    }

    if (reference == VioCameraTimeReference::exposure_start) {
        return start;
    }
    if (reference == VioCameraTimeReference::exposure_end) {
        return end;
    }

    // Overflow-safe integer midpoint: start + floor((end-start)/2).
    TimePoint midpoint = start;
    midpoint.ticks = start.ticks + (end.ticks - start.ticks) / 2;
    return midpoint;
}

const CameraObservation* find_camera(const SensorObservation& observation, const std::string& stream_id) {
    const auto found = std::find_if(
        observation.cameras.begin(), observation.cameras.end(),
        [&stream_id](const CameraObservation& camera) { return camera.stream_id == stream_id; });
    return found == observation.cameras.end() ? nullptr : &*found;
}

const StereoPairStatus* find_pair(const SensorObservation& observation, const std::string& pair_id) {
    const auto found = std::find_if(
        observation.stereo_pairs.begin(), observation.stereo_pairs.end(),
        [&pair_id](const StereoPairStatus& pair) { return pair.pair_id == pair_id; });
    return found == observation.stereo_pairs.end() ? nullptr : &*found;
}

bool finite3(const std::array<double, 3>& values) {
    return std::all_of(values.begin(), values.end(), [](double value) { return std::isfinite(value); });
}

bool same_imu_payload(const VioImuSample& a, const VioImuSample& b) {
    return a.accel_m_s2 == b.accel_m_s2 && a.gyro_rad_s == b.gyro_rad_s;
}

}  // namespace

VioInputAdapter::VioInputAdapter(VioAdapterConfig config) : config_(std::move(config)) {}

void VioInputAdapter::reset() noexcept {
    active_epoch_.reset();
    last_emitted_imu_.reset();
}

VioPacket VioInputAdapter::adapt(const SensorObservation& observation) {
    if (config_.camera_a_stream_id.empty() || config_.camera_b_stream_id.empty() ||
        config_.camera_a_stream_id == config_.camera_b_stream_id || config_.stereo_pair_id.empty()) {
        return rejected_packet(observation, config_, "invalid VIO adapter camera/stereo configuration");
    }

    if (observation.continuity == ContinuityState::discontinuity) {
        active_epoch_.reset();
        last_emitted_imu_.reset();
        auto packet = rejected_packet(observation, config_, "source continuity discontinuity requires backend reset");
        packet.state = VioPacketState::reset_required;
        packet.reset = VioResetDirective::reset_before_next;
        return packet;
    }

    if (observation.source_state != SourceState::available) {
        return rejected_packet(observation, config_, "sensor source is not available");
    }
    if (observation.validity != ObservationValidity::valid) {
        return rejected_packet(observation, config_, "sensor observation is not fully valid");
    }
    if (!nonempty_calibration(observation.calibration)) {
        return rejected_packet(observation, config_, "stereo, IMU, and camera-IMU calibration identities are required");
    }
    if (observation.configuration_revision.empty()) {
        return rejected_packet(observation, config_, "configuration revision is required");
    }

    const auto* pair = find_pair(observation, config_.stereo_pair_id);
    if (pair == nullptr) {
        return rejected_packet(observation, config_, "configured stereo pair is missing");
    }
    if (pair->synchronization != SynchronizationState::synchronized) {
        return rejected_packet(observation, config_, "stereo pair is not explicitly synchronized");
    }

    const auto* camera_a = find_camera(observation, config_.camera_a_stream_id);
    const auto* camera_b = find_camera(observation, config_.camera_b_stream_id);
    if (camera_a == nullptr || camera_b == nullptr) {
        return rejected_packet(observation, config_, "configured stereo camera stream is missing");
    }
    if (camera_a->validity != ObservationValidity::valid || camera_b->validity != ObservationValidity::valid ||
        !camera_a->usable() || !camera_b->usable()) {
        return rejected_packet(observation, config_, "stereo camera observation is invalid or degraded");
    }

    const auto time_a = camera_reference_time(*camera_a, config_.camera_time_reference);
    const auto time_b = camera_reference_time(*camera_b, config_.camera_time_reference);
    if (!time_a || !time_b) {
        return rejected_packet(observation, config_, "complete compatible device-clock exposure timing is required");
    }
    if (!same_clock(*time_a, *time_b) || time_a->ticks != time_b->ticks) {
        return rejected_packet(observation, config_, "stereo camera reference timestamps do not match");
    }

    if (observation.imu.empty()) {
        return rejected_packet(observation, config_, "at least one SI-valid IMU sample is required");
    }

    const bool new_epoch = !active_epoch_ || *active_epoch_ != observation.continuity_epoch;
    const bool reset_imu_history = new_epoch || observation.continuity == ContinuityState::reinitialized;
    std::optional<VioImuSample> prior_imu;
    if (!reset_imu_history) {
        prior_imu = last_emitted_imu_;
    }

    std::vector<VioImuSample> imu;
    imu.reserve(observation.imu.size());
    std::optional<std::uint64_t> previous_source_ticks;
    bool first_source_sample = true;
    for (const auto& sample : observation.imu) {
        if (sample.validity != ObservationValidity::valid || !sample.si_valid) {
            return rejected_packet(observation, config_, "every VIO IMU sample must be valid calibrated SI data");
        }
        if (!is_device_time(sample.sample_time) || !same_clock(sample.sample_time, *time_a)) {
            return rejected_packet(observation, config_, "IMU sample time must share the camera device clock and unit");
        }
        if (previous_source_ticks && sample.sample_time.ticks <= *previous_source_ticks) {
            return rejected_packet(observation, config_, "IMU sample timestamps must be strictly increasing without duplicates");
        }
        if (!finite3(sample.accel_m_s2) || !finite3(sample.gyro_rad_s)) {
            return rejected_packet(observation, config_, "IMU SI values must be finite");
        }

        previous_source_ticks = sample.sample_time.ticks;
        VioImuSample converted{sample.sample_time, sample.accel_m_s2, sample.gyro_rad_s};

        if (first_source_sample && prior_imu) {
            if (!same_clock(converted.sample_time, prior_imu->sample_time)) {
                return rejected_packet(
                    observation,
                    config_,
                    "IMU device clock changed across observations within one continuity epoch");
            }
            if (converted.sample_time.ticks < prior_imu->sample_time.ticks) {
                return rejected_packet(observation, config_, "IMU sample time moved backward across observations");
            }
            if (converted.sample_time.ticks == prior_imu->sample_time.ticks) {
                if (!same_imu_payload(converted, *prior_imu)) {
                    return rejected_packet(
                        observation,
                        config_,
                        "shared IMU timestamp has different SI payload across observations");
                }
                first_source_sample = false;
                continue;
            }
        }

        imu.push_back(std::move(converted));
        first_source_sample = false;
    }

    if (imu.empty()) {
        return rejected_packet(
            observation,
            config_,
            "VIO packet has no new IMU samples after shared-boundary suppression");
    }

    VioPacket packet{};
    packet.state = VioPacketState::ready;
    packet.source_id = observation.source_id;
    packet.evidence = observation.evidence;
    packet.sequence = observation.sequence;
    packet.sequence_present = observation.sequence_present;
    packet.continuity_epoch = observation.continuity_epoch;
    packet.continuity = observation.continuity;
    packet.calibration = observation.calibration;
    packet.configuration_revision = observation.configuration_revision;
    packet.camera_time_reference = config_.camera_time_reference;
    packet.stereo.camera_a = {camera_a->stream_id, camera_a->lease, camera_a->image};
    packet.stereo.camera_b = {camera_b->stream_id, camera_b->lease, camera_b->image};
    packet.stereo.reference_time = *time_a;
    packet.imu = std::move(imu);

    if (new_epoch || observation.continuity == ContinuityState::reinitialized) {
        packet.reset = VioResetDirective::reinitialize;
    }
    active_epoch_ = observation.continuity_epoch;
    last_emitted_imu_ = packet.imu.back();
    return packet;
}

VioPoseValidation validate_pose_observation(const PoseObservation& pose) {
    if (!is_device_time(pose.timestamp)) {
        return {false, "pose timestamp must be explicit device time"};
    }
    if (!finite3(pose.position_world_m) || !finite3(pose.velocity_world_m_s)) {
        return {false, "pose position/velocity must be finite"};
    }
    if (!std::all_of(
            pose.orientation_world_from_body_xyzw.begin(),
            pose.orientation_world_from_body_xyzw.end(),
            [](double value) { return std::isfinite(value); })) {
        return {false, "pose quaternion must be finite"};
    }
    const double q2 =
        pose.orientation_world_from_body_xyzw[0] * pose.orientation_world_from_body_xyzw[0] +
        pose.orientation_world_from_body_xyzw[1] * pose.orientation_world_from_body_xyzw[1] +
        pose.orientation_world_from_body_xyzw[2] * pose.orientation_world_from_body_xyzw[2] +
        pose.orientation_world_from_body_xyzw[3] * pose.orientation_world_from_body_xyzw[3];
    if (std::abs(q2 - 1.0) > 1e-6) {
        return {false, "pose quaternion must be normalized"};
    }
    if (!nonempty_calibration(pose.calibration) || pose.configuration_revision.empty()) {
        return {false, "pose must preserve stereo/IMU/camera-IMU calibration and configuration identity"};
    }
    if (pose.backend_id.empty() || pose.backend_version.empty()) {
        return {false, "pose backend identity/version are required"};
    }
    if (pose.tracking == VioTrackingState::uninitialized) {
        return {false, "derived pose tracking state must be explicit"};
    }
    return {};
}

}  // namespace bividi
