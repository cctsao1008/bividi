#include "bividi/vio_kimera.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <utility>

namespace bividi {
namespace {

std::optional<std::int64_t> timestamp_ns(const TimePoint& time) {
    if (!time.present || time.domain != ClockDomain::device || time.clock_id.empty()) {
        return std::nullopt;
    }
    constexpr auto max_ns = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    if (time.unit == TimeUnit::nanoseconds) {
        if (time.ticks > max_ns) {
            return std::nullopt;
        }
        return static_cast<std::int64_t>(time.ticks);
    }
    if (time.unit == TimeUnit::microseconds) {
        constexpr std::uint64_t scale = 1000;
        if (time.ticks > max_ns / scale) {
            return std::nullopt;
        }
        return static_cast<std::int64_t>(time.ticks * scale);
    }
    return std::nullopt;
}

bool finite6(const std::array<double, 6>& values) {
    return std::all_of(values.begin(), values.end(), [](double value) { return std::isfinite(value); });
}

KimeraFeedDescription reject(std::string reason) {
    KimeraFeedDescription result{};
    result.reason = std::move(reason);
    return result;
}

}  // namespace

KimeraFeedDescription translate_kimera_feed(const VioPacket& packet) {
    if (!packet.backend_ready()) {
        return reject("VioPacket is not backend-ready");
    }
    if (!packet.sequence_present) {
        return reject("Kimera FrameId requires an explicit source sequence");
    }
    if (!packet.stereo.camera_a.lease.valid() || !packet.stereo.camera_b.lease.valid() ||
        packet.stereo.camera_a.image.empty() || packet.stereo.camera_b.image.empty()) {
        return reject("Kimera feed requires live stereo image leases/views");
    }

    const auto camera_ns = timestamp_ns(packet.stereo.reference_time);
    if (!camera_ns) {
        return reject("camera device timestamp cannot be represented as signed nanoseconds");
    }

    KimeraPipelineDirective directive = KimeraPipelineDirective::none;
    if (packet.reset == VioResetDirective::reinitialize) {
        directive = KimeraPipelineDirective::recreate_pipeline_before_feed;
    } else if (packet.reset != VioResetDirective::none) {
        return reject("reset-before-next packet cannot be fed to Kimera");
    }

    if (packet.imu.empty()) {
        return reject("Kimera feed requires at least one IMU sample");
    }

    std::vector<KimeraImuFeed> imu;
    imu.reserve(packet.imu.size());
    std::optional<std::int64_t> previous;
    for (const auto& sample : packet.imu) {
        const auto sample_ns = timestamp_ns(sample.sample_time);
        if (!sample_ns) {
            return reject("IMU device timestamp cannot be represented as signed nanoseconds");
        }
        if (previous && *sample_ns <= *previous) {
            return reject("Kimera IMU timestamps must remain strictly increasing after ns conversion");
        }
        std::array<double, 6> accel_gyro{{
            sample.accel_m_s2[0], sample.accel_m_s2[1], sample.accel_m_s2[2],
            sample.gyro_rad_s[0], sample.gyro_rad_s[1], sample.gyro_rad_s[2],
        }};
        if (!finite6(accel_gyro)) {
            return reject("Kimera IMU values must be finite");
        }
        imu.push_back({*sample_ns, accel_gyro});
        previous = *sample_ns;
    }

    KimeraFeedDescription result{};
    result.ready = true;
    result.frame_id = packet.sequence;
    result.camera_timestamp_ns = *camera_ns;
    result.continuity_epoch = packet.continuity_epoch;
    result.directive = directive;
    result.left = {
        packet.stereo.camera_a.stream_id,
        packet.stereo.camera_a.lease,
        packet.stereo.camera_a.image,
    };
    result.right = {
        packet.stereo.camera_b.stream_id,
        packet.stereo.camera_b.lease,
        packet.stereo.camera_b.image,
    };
    result.imu = std::move(imu);
    return result;
}

}  // namespace bividi
