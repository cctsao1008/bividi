#pragma once

#include "bividi/vio.hpp"

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace bividi {

inline constexpr const char* kKimeraVioRepository = "MIT-SPARK/Kimera-VIO";
inline constexpr const char* kKimeraVioRevision = "ce8c59b7b273ab5ac29db7e5572e1623760e19c7";

enum class KimeraPipelineDirective {
    none,
    recreate_pipeline_before_feed,
};

struct KimeraCameraFeed {
    std::string stream_id;
    FrameLease lease{};
    ImageView image{};
};

// Matches pinned Kimera ImuAccGyr ordering: accel xyz, then gyro xyz.
struct KimeraImuFeed {
    std::int64_t timestamp_ns = 0;
    std::array<double, 6> accel_gyro{};
};

struct KimeraFeedDescription {
    bool ready = false;
    std::string reason;
    std::uint64_t frame_id = 0;
    std::int64_t camera_timestamp_ns = 0;
    std::uint64_t continuity_epoch = 0;
    KimeraPipelineDirective directive = KimeraPipelineDirective::none;
    KimeraCameraFeed left{};
    KimeraCameraFeed right{};
    std::vector<KimeraImuFeed> imu;
    std::string upstream_repository = kKimeraVioRepository;
    std::string upstream_revision = kKimeraVioRevision;
};

[[nodiscard]] KimeraFeedDescription translate_kimera_feed(const VioPacket& packet);

}  // namespace bividi
