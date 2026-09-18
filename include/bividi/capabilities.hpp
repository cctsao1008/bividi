#pragma once

#include "bividi/image_view.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace bividi {

// Native runtime capability vocabulary. These types describe the logical
// sensor topology exposed after platform/backend and device-adapter probing;
// they intentionally contain no vendor SDK or operating-system objects.

enum class CameraModality {
    unknown,
    visible,
    infrared,
};

enum class TriggerMode {
    free_run,
    software,
    hardware,
    command,
};

struct CameraStreamInfo {
    std::string stream_id;
    std::string role = "primary";
    PixelFormat pixel_format = PixelFormat::unknown;
    CameraModality modality = CameraModality::unknown;
    std::uint32_t width = 0;
    std::uint32_t height = 0;

    [[nodiscard]] bool structurally_valid() const noexcept {
        return !stream_id.empty() && !role.empty() && width != 0 && height != 0;
    }
};

// A stereo relationship is explicit topology. It does not by itself claim a
// left/right physical mapping, calibration, or measured synchronization bound.
struct StereoPairInfo {
    std::string pair_id;
    std::string camera_a_stream_id;
    std::string camera_b_stream_id;

    [[nodiscard]] bool structurally_valid() const noexcept {
        return !pair_id.empty() && !camera_a_stream_id.empty() &&
               !camera_b_stream_id.empty() &&
               camera_a_stream_id != camera_b_stream_id;
    }
};

struct TimingCapabilities {
    bool host_receive_monotonic = true;
    bool device_frame_time = false;
    bool exposure_start_end = false;
    bool imu_sample_time = false;
    bool hardware_sync = false;
};

struct SensorCapabilities {
    std::vector<CameraStreamInfo> cameras;
    std::vector<StereoPairInfo> stereo_pairs;
    bool imu = false;
    bool audio = false;
    TimingCapabilities timing{};
    std::vector<TriggerMode> trigger_modes;

    [[nodiscard]] const CameraStreamInfo* find_camera(const std::string& stream_id) const noexcept {
        for (const auto& camera : cameras) {
            if (camera.stream_id == stream_id) {
                return &camera;
            }
        }
        return nullptr;
    }

    [[nodiscard]] const StereoPairInfo* find_stereo_pair(const std::string& pair_id) const noexcept {
        for (const auto& pair : stereo_pairs) {
            if (pair.pair_id == pair_id) {
                return &pair;
            }
        }
        return nullptr;
    }
};

}  // namespace bividi
