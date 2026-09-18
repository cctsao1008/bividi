#include "bividi/observation.hpp"

#include <cmath>
#include <set>
#include <string>

namespace bividi {
namespace {

bool finite3(const std::array<double, 3>& value) noexcept {
    return std::isfinite(value[0]) && std::isfinite(value[1]) && std::isfinite(value[2]);
}

void validate_exposure(const ExposureTiming& exposure, ConformanceResult& result, const std::string& prefix) {
    if (!exposure.start.structurally_valid()) {
        result.add_error(prefix + ".exposure.start is malformed");
    }
    if (!exposure.end.structurally_valid()) {
        result.add_error(prefix + ".exposure.end is malformed");
    }
    if (!exposure.raw_start.structurally_valid()) {
        result.add_error(prefix + ".exposure.raw_start is malformed");
    }
    if (!exposure.raw_end.structurally_valid()) {
        result.add_error(prefix + ".exposure.raw_end is malformed");
    }

    if (exposure.complete()) {
        if (exposure.start.domain != exposure.end.domain ||
            exposure.start.unit != exposure.end.unit ||
            exposure.start.clock_id != exposure.end.clock_id) {
            result.add_error(prefix + ".exposure start/end must use the same clock and unit");
        } else if (exposure.end.ticks < exposure.start.ticks) {
            result.add_error(prefix + ".exposure end precedes start");
        }
    }
}

}  // namespace

ConformanceResult validate_capabilities(const SensorCapabilities& capabilities) {
    ConformanceResult result{};
    std::set<std::string> camera_ids;
    std::set<std::string> pair_ids;

    for (const auto& camera : capabilities.cameras) {
        if (!camera.structurally_valid()) {
            result.add_error("camera capability is malformed");
            continue;
        }
        if (!camera_ids.insert(camera.stream_id).second) {
            result.add_error("duplicate camera stream_id: " + camera.stream_id);
        }
    }

    for (const auto& pair : capabilities.stereo_pairs) {
        if (!pair.structurally_valid()) {
            result.add_error("stereo pair capability is malformed");
            continue;
        }
        if (!pair_ids.insert(pair.pair_id).second) {
            result.add_error("duplicate stereo pair_id: " + pair.pair_id);
        }
        if (camera_ids.count(pair.camera_a_stream_id) == 0) {
            result.add_error("stereo pair references unknown camera: " + pair.camera_a_stream_id);
        }
        if (camera_ids.count(pair.camera_b_stream_id) == 0) {
            result.add_error("stereo pair references unknown camera: " + pair.camera_b_stream_id);
        }
    }

    return result;
}

ConformanceResult validate_observation(
    const SensorObservation& observation,
    const SensorCapabilities* capabilities) {
    ConformanceResult result{};

    if (observation.contract_version != kObservationContractVersion) {
        result.add_error("unsupported observation contract version");
    }
    if (observation.source_id.empty()) {
        result.add_error("source_id must not be empty");
    }
    if (!observation.timing.host_receive.structurally_valid()) {
        result.add_error("host_receive time is malformed");
    }
    if (!observation.timing.replay_schedule.structurally_valid()) {
        result.add_error("replay_schedule time is malformed");
    }
    if (observation.timing.host_receive.present &&
        observation.timing.host_receive.domain != ClockDomain::host_monotonic) {
        result.add_error("host_receive time must use host_monotonic clock domain");
    }
    if (observation.timing.replay_schedule.present &&
        observation.timing.replay_schedule.domain != ClockDomain::replay) {
        result.add_error("replay_schedule time must use replay clock domain");
    }
    if (observation.source_state != SourceState::available &&
        observation.validity == ObservationValidity::valid) {
        result.add_error("disconnected/error source cannot report a valid observation");
    }

    if (capabilities != nullptr) {
        const auto cap_result = validate_capabilities(*capabilities);
        for (const auto& error : cap_result.errors) {
            result.add_error("capabilities: " + error);
        }
        if (capabilities->timing.host_receive_monotonic &&
            observation.source_state == SourceState::available &&
            observation.validity != ObservationValidity::invalid &&
            !observation.timing.host_receive.present) {
            result.add_error("observation is missing required host receive monotonic time");
        }
    }

    std::set<std::string> camera_ids;
    for (const auto& camera : observation.cameras) {
        const std::string prefix = "camera[" + camera.stream_id + "]";
        if (camera.stream_id.empty()) {
            result.add_error("camera stream_id must not be empty");
        } else if (!camera_ids.insert(camera.stream_id).second) {
            result.add_error("duplicate camera observation: " + camera.stream_id);
        }

        if (!camera.frame_time.structurally_valid()) {
            result.add_error(prefix + ".frame_time is malformed");
        }
        validate_exposure(camera.exposure, result, prefix);

        if (camera.validity != ObservationValidity::invalid && !camera.usable()) {
            result.add_error(prefix + " is marked usable but has no leased image");
        }

        if (capabilities != nullptr && !camera.stream_id.empty()) {
            const auto* info = capabilities->find_camera(camera.stream_id);
            if (info == nullptr) {
                result.add_error(prefix + " is not declared by capabilities");
            } else if (!camera.image.empty()) {
                if (camera.image.width != info->width || camera.image.height != info->height) {
                    result.add_error(prefix + " geometry differs from capabilities");
                }
                if (info->pixel_format != PixelFormat::unknown &&
                    camera.image.pixel_format != info->pixel_format) {
                    result.add_error(prefix + " pixel format differs from capabilities");
                }
            }

            if (capabilities->timing.device_frame_time &&
                camera.validity != ObservationValidity::invalid) {
                if (!camera.frame_time.present) {
                    result.add_error(prefix + " is missing required device frame time");
                } else if (camera.frame_time.domain != ClockDomain::device) {
                    result.add_error(prefix + ".frame_time must use device clock domain");
                }
            }
            if (capabilities->timing.exposure_start_end &&
                camera.validity != ObservationValidity::invalid &&
                !camera.exposure.complete()) {
                result.add_error(prefix + " is missing required exposure start/end timing");
            }
        }
    }

    if (capabilities != nullptr && !capabilities->imu && !observation.imu.empty()) {
        result.add_error("IMU observations present while capabilities declare no IMU");
    }

    for (std::size_t i = 0; i < observation.imu.size(); ++i) {
        const auto& sample = observation.imu[i];
        const std::string prefix = "imu[" + std::to_string(i) + "]";
        if (sample.sensor_id.empty()) {
            result.add_error(prefix + ".sensor_id must not be empty");
        }
        if (!sample.sample_time.structurally_valid()) {
            result.add_error(prefix + ".sample_time is malformed");
        }
        if (!sample.raw_time.structurally_valid()) {
            result.add_error(prefix + ".raw_time is malformed");
        }
        if (sample.validity != ObservationValidity::invalid && !sample.sample_time.present) {
            result.add_error(prefix + " requires an explicit sample_time");
        }
        if (sample.validity != ObservationValidity::invalid && !sample.raw_valid && !sample.si_valid) {
            result.add_error(prefix + " carries neither raw nor SI measurement data");
        }
        if (sample.si_valid && (!finite3(sample.accel_m_s2) || !finite3(sample.gyro_rad_s))) {
            result.add_error(prefix + " contains non-finite SI values");
        }
        if (capabilities != nullptr && capabilities->timing.imu_sample_time &&
            sample.validity != ObservationValidity::invalid &&
            sample.sample_time.domain != ClockDomain::device) {
            result.add_error(prefix + " must use device clock domain");
        }
    }

    std::set<std::string> pair_ids;
    for (const auto& pair : observation.stereo_pairs) {
        if (pair.pair_id.empty()) {
            result.add_error("stereo pair status requires non-empty pair_id");
            continue;
        }
        if (!pair_ids.insert(pair.pair_id).second) {
            result.add_error("duplicate stereo pair status: " + pair.pair_id);
        }
        if (capabilities != nullptr && capabilities->find_stereo_pair(pair.pair_id) == nullptr) {
            result.add_error("stereo pair status references undeclared pair: " + pair.pair_id);
        }
    }

    if (observation.source_state == SourceState::available &&
        observation.validity != ObservationValidity::invalid &&
        observation.cameras.empty() && observation.imu.empty()) {
        result.add_error("usable observation carries no camera or IMU data");
    }

    return result;
}

}  // namespace bividi
