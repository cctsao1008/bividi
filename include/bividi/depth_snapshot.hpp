#pragma once

#include "bividi/depth_observation.hpp"
#include "bividi/observation_source.hpp"

#include <opencv2/core.hpp>

#include <cstddef>
#include <cstdint>
#include <exception>
#include <mutex>
#include <string>
#include <utility>

namespace bividi::depth {

// Thread-safe, pull-based adapter for engineering consumers that need the latest
// derived stereo result from an ObservationSnapshotSource. The cache is
// important: StereoDepthObservationProcessor owns chronology state, so two HTTP
// requests for the same source snapshot must not process the same sequence twice
// and accidentally turn the second request into a duplicate-sequence fault.
struct StereoDepthSnapshot {
    bool observation_present = false;
    std::uint64_t revision = 0;
    std::string processing_error;
    StereoDepthObservationResult result{};
    cv::Mat disparity_preview;
    cv::Mat depth_preview;
    double valid_fraction = 0.0;
};

class StereoDepthSnapshotProcessor {
public:
    StereoDepthSnapshotProcessor(
        ObservationSnapshotSource& source,
        std::string pair_id,
        StereoDepthCalibration calibration,
        StereoDepthConfig config = {},
        StereoDepthObservationPolicy policy = {})
        : source_(source),
          processor_(
              source.observation_capabilities(),
              std::move(pair_id),
              std::move(calibration),
              config,
              policy) {}

    [[nodiscard]] const StereoDepthCalibration& calibration() const noexcept {
        return processor_.calibration();
    }

    // Returns false only when the source has not published an observation yet.
    // Rejected observations still return true and carry the explicit consumer
    // disposition with empty numeric/preview products.
    bool latest(StereoDepthSnapshot& out) {
        std::lock_guard<std::mutex> lock(mutex_);

        SensorObservation observation;
        if (!source_.latest_observation(observation)) {
            out = {};
            return false;
        }

        if (!have_cached_ || !same_snapshot(observation, cached_observation_)) {
            cached_ = {};
            cached_.observation_present = true;
            cached_.revision = ++revision_;
            try {
                cached_.result = processor_.process(observation);
                if (cached_.result.processed()) {
                    cached_.disparity_preview = disparity_preview_u8(cached_.result.depth);
                    cached_.depth_preview = depth_preview_u8(cached_.result.depth);
                    const auto valid = cv::countNonZero(cached_.result.depth.valid_mask);
                    const auto pixels = cached_.result.depth.valid_mask.total();
                    cached_.valid_fraction = pixels == 0
                        ? 0.0
                        : static_cast<double>(valid) / static_cast<double>(pixels);
                }
            } catch (const std::exception& error) {
                cached_.processing_error = error.what();
                cached_.result.depth = {};
                cached_.disparity_preview.release();
                cached_.depth_preview.release();
                cached_.valid_fraction = 0.0;
            }
            cached_observation_ = std::move(observation);
            have_cached_ = true;
        }

        out = cached_;
        return true;
    }

    void reset() {
        std::lock_guard<std::mutex> lock(mutex_);
        processor_.reset();
        cached_observation_ = {};
        cached_ = {};
        have_cached_ = false;
        ++revision_;
    }

private:
    static bool same_time(const TimePoint& a, const TimePoint& b) noexcept {
        return a.present == b.present && a.ticks == b.ticks && a.unit == b.unit &&
               a.domain == b.domain && a.clock_id == b.clock_id;
    }

    // SensorObservation intentionally has no storage-instance ID. Image data
    // addresses are safe here because cached_observation_ retains the old
    // FrameLease; a newly materialized replay frame therefore cannot reuse the
    // old backing allocation while that cached snapshot is alive.
    static bool same_snapshot(
        const SensorObservation& a,
        const SensorObservation& b) noexcept {
        if (a.source_id != b.source_id ||
            a.sequence_present != b.sequence_present ||
            a.sequence != b.sequence ||
            a.continuity_epoch != b.continuity_epoch ||
            a.continuity != b.continuity ||
            !same_time(a.timing.host_receive, b.timing.host_receive) ||
            a.cameras.size() != b.cameras.size() ||
            a.imu.size() != b.imu.size()) {
            return false;
        }

        for (std::size_t i = 0; i < a.cameras.size(); ++i) {
            if (a.cameras[i].stream_id != b.cameras[i].stream_id ||
                a.cameras[i].image.data != b.cameras[i].image.data ||
                a.cameras[i].image.width != b.cameras[i].image.width ||
                a.cameras[i].image.height != b.cameras[i].image.height ||
                a.cameras[i].image.pixel_format != b.cameras[i].image.pixel_format) {
                return false;
            }
        }

        if (a.cameras.empty() && !a.imu.empty()) {
            if (!same_time(a.imu.front().sample_time, b.imu.front().sample_time) ||
                !same_time(a.imu.back().sample_time, b.imu.back().sample_time)) {
                return false;
            }
        }
        return true;
    }

    ObservationSnapshotSource& source_;
    StereoDepthObservationProcessor processor_;
    std::mutex mutex_;
    SensorObservation cached_observation_{};
    StereoDepthSnapshot cached_{};
    bool have_cached_ = false;
    std::uint64_t revision_ = 0;
};

}  // namespace bividi::depth
