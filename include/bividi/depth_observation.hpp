#pragma once

#include "bividi/depth.hpp"
#include "bividi/observation.hpp"

#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>

namespace bividi::depth {

// Disposition of one normalized SensorObservation at the optional #9 depth
// boundary. A rejected observation never carries a plausible/fabricated depth
// product; callers may inspect reason/provenance and wait for the next usable
// stereo observation.
enum class StereoDepthObservationDisposition {
    processed,
    rejected_source_unavailable,
    rejected_observation_invalid,
    rejected_pair_status_missing,
    rejected_synchronization,
    rejected_camera_missing,
    rejected_camera_unusable,
    rejected_calibration_identity,
    rejected_sequence_non_monotonic,
};

struct StereoDepthObservationPolicy {
    // Replay and synthetic evidence may legitimately preserve synchronization
    // as unknown. This option permits processing while retaining that unknown
    // state in the result; it never upgrades unknown to synchronized.
    bool allow_unknown_synchronization = true;

    // Observation-level degradation may be caused by a modality irrelevant to
    // stereo depth (for example IMU quality). Camera observations themselves
    // are still required to be fully valid below.
    bool allow_degraded_observation = true;

    // Current ReplaySource does not invent a stereo calibration identity for
    // recordings that did not carry one. Set this true for consumers that only
    // accept observations explicitly bound to the selected calibration ID.
    bool require_observation_calibration_identity = false;

    // A forward sequence gap is safe for per-frame StereoSGBM only after the
    // derived-stream state is explicitly reset. The numerical kernel itself is
    // stateless, but this adapter keeps the continuity contract explicit for
    // downstream/temporal consumers.
    bool reset_on_sequence_gap = true;
};

struct StereoDepthObservationResult {
    StereoDepthObservationDisposition disposition =
        StereoDepthObservationDisposition::rejected_observation_invalid;
    std::string reason;

    std::string source_id;
    EvidenceKind evidence = EvidenceKind::unknown;
    std::uint64_t sequence = 0;
    bool sequence_present = false;
    std::uint64_t continuity_epoch = 0;
    ContinuityState continuity = ContinuityState::continuous;

    std::string pair_id;
    SynchronizationState synchronization = SynchronizationState::unknown;
    std::string calibration_id;

    // True when a discontinuity/epoch/gap/pending rejected frame caused the
    // adapter's derived-stream chronology to be cleared before this input.
    bool reset_before_process = false;
    bool sequence_gap_detected = false;
    std::uint64_t reset_generation = 0;

    StereoDepthResult depth{};

    [[nodiscard]] bool processed() const noexcept {
        return disposition == StereoDepthObservationDisposition::processed;
    }
};

[[nodiscard]] inline const char* stereo_depth_observation_disposition_name(
    StereoDepthObservationDisposition disposition) noexcept {
    switch (disposition) {
        case StereoDepthObservationDisposition::processed: return "processed";
        case StereoDepthObservationDisposition::rejected_source_unavailable:
            return "rejected_source_unavailable";
        case StereoDepthObservationDisposition::rejected_observation_invalid:
            return "rejected_observation_invalid";
        case StereoDepthObservationDisposition::rejected_pair_status_missing:
            return "rejected_pair_status_missing";
        case StereoDepthObservationDisposition::rejected_synchronization:
            return "rejected_synchronization";
        case StereoDepthObservationDisposition::rejected_camera_missing:
            return "rejected_camera_missing";
        case StereoDepthObservationDisposition::rejected_camera_unusable:
            return "rejected_camera_unusable";
        case StereoDepthObservationDisposition::rejected_calibration_identity:
            return "rejected_calibration_identity";
        case StereoDepthObservationDisposition::rejected_sequence_non_monotonic:
            return "rejected_sequence_non_monotonic";
    }
    return "unknown";
}

// Adapter from the stable #11 SensorObservation boundary into the #9 calibrated
// stereo-depth numerical kernel. It owns no acquisition state and does not
// modify raw observations. The explicit StereoPairInfo ordering determines
// which normalized stream is calibration camera A vs camera B.
class StereoDepthObservationProcessor {
public:
    StereoDepthObservationProcessor(
        SensorCapabilities capabilities,
        std::string pair_id,
        StereoDepthCalibration calibration,
        StereoDepthConfig config = {},
        StereoDepthObservationPolicy policy = {})
        : capabilities_(std::move(capabilities)),
          pair_id_(std::move(pair_id)),
          calibration_(std::move(calibration)),
          processor_(calibration_, config),
          policy_(policy) {
        const auto cap_validation = validate_capabilities(capabilities_);
        if (!cap_validation.ok) {
            throw std::invalid_argument("depth observation adapter requires conforming SensorCapabilities");
        }
        pair_ = capabilities_.find_stereo_pair(pair_id_);
        if (pair_ == nullptr) {
            throw std::invalid_argument("depth observation adapter pair_id is not present in capabilities");
        }
        const auto* camera_a = capabilities_.find_camera(pair_->camera_a_stream_id);
        const auto* camera_b = capabilities_.find_camera(pair_->camera_b_stream_id);
        if (camera_a == nullptr || camera_b == nullptr) {
            throw std::invalid_argument("depth observation adapter stereo pair references missing camera capability");
        }
        if (camera_a->width != static_cast<std::uint32_t>(calibration_.width) ||
            camera_a->height != static_cast<std::uint32_t>(calibration_.height) ||
            camera_b->width != static_cast<std::uint32_t>(calibration_.width) ||
            camera_b->height != static_cast<std::uint32_t>(calibration_.height)) {
            throw std::invalid_argument("depth observation adapter capability geometry disagrees with calibration");
        }
        if (!supported_pixel_format(camera_a->pixel_format) ||
            !supported_pixel_format(camera_b->pixel_format)) {
            throw std::invalid_argument("depth observation adapter requires GRAY8 or BGR24 camera capabilities");
        }
    }

    [[nodiscard]] const SensorCapabilities& capabilities() const noexcept { return capabilities_; }
    [[nodiscard]] const StereoPairInfo& stereo_pair() const noexcept { return *pair_; }
    [[nodiscard]] const StereoDepthCalibration& calibration() const noexcept { return calibration_; }
    [[nodiscard]] const StereoDepthObservationPolicy& policy() const noexcept { return policy_; }
    [[nodiscard]] std::uint64_t reset_generation() const noexcept { return reset_generation_; }

    // Explicit external reset. The underlying StereoSGBM kernel is per-frame;
    // this clears adapter chronology and increments the derived-stream reset
    // generation so callers can make reset provenance visible.
    void reset() noexcept {
        clear_chronology();
        pending_reset_ = false;
        ++reset_generation_;
    }

    [[nodiscard]] StereoDepthObservationResult process(const SensorObservation& observation) {
        StereoDepthObservationResult result = base_result(observation);

        bool reset_now = false;
        if (pending_reset_) {
            clear_chronology();
            pending_reset_ = false;
            ++reset_generation_;
            reset_now = true;
        }

        const bool explicit_boundary =
            observation.continuity != ContinuityState::continuous ||
            (have_epoch_ && observation.continuity_epoch != last_epoch_);
        if (explicit_boundary) {
            clear_chronology();
            ++reset_generation_;
            reset_now = true;
        }

        if (!reset_now && have_sequence_ && observation.sequence_present) {
            if (observation.sequence <= last_sequence_) {
                result.reset_before_process = false;
                result.reset_generation = reset_generation_;
                return reject(
                    std::move(result),
                    observation,
                    StereoDepthObservationDisposition::rejected_sequence_non_monotonic,
                    "stereo-depth observation sequence is duplicate or out-of-order",
                    false);
            }
            if (observation.sequence > last_sequence_ + 1) {
                result.sequence_gap_detected = true;
                if (policy_.reset_on_sequence_gap) {
                    clear_chronology();
                    ++reset_generation_;
                    reset_now = true;
                }
            }
        }

        result.reset_before_process = reset_now;
        result.reset_generation = reset_generation_;

        if (observation.source_state != SourceState::available) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_source_unavailable,
                "stereo-depth source is not available", reset_now);
        }
        if (observation.validity == ObservationValidity::invalid ||
            (!policy_.allow_degraded_observation &&
             observation.validity == ObservationValidity::degraded)) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_observation_invalid,
                "stereo-depth observation validity is not acceptable", reset_now);
        }

        const auto* pair_status = find_pair_status(observation);
        if (pair_status == nullptr) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_pair_status_missing,
                "stereo-depth observation lacks status for selected stereo pair", reset_now);
        }
        result.synchronization = pair_status->synchronization;
        if (pair_status->synchronization == SynchronizationState::unsynchronized ||
            pair_status->synchronization == SynchronizationState::degraded ||
            (pair_status->synchronization == SynchronizationState::unknown &&
             !policy_.allow_unknown_synchronization)) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_synchronization,
                "stereo-depth synchronization state is not acceptable", reset_now);
        }

        if (policy_.require_observation_calibration_identity &&
            observation.calibration.stereo.empty()) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_calibration_identity,
                "stereo-depth observation has no stereo calibration identity", reset_now);
        }
        if (!observation.calibration.stereo.empty() &&
            observation.calibration.stereo != calibration_.calibration_id) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_calibration_identity,
                "stereo-depth observation calibration identity differs from selected artifact", reset_now);
        }

        const auto* camera_a = find_camera(observation, pair_->camera_a_stream_id);
        const auto* camera_b = find_camera(observation, pair_->camera_b_stream_id);
        if (camera_a == nullptr || camera_b == nullptr) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_camera_missing,
                "stereo-depth observation is missing a selected stereo camera", reset_now);
        }
        if (!camera_ready(*camera_a) || !camera_ready(*camera_b)) {
            return reject(
                std::move(result), observation,
                StereoDepthObservationDisposition::rejected_camera_unusable,
                "stereo-depth selected camera observation is not fully valid/usable", reset_now);
        }

        result.depth = processor_.process(camera_a->image, camera_b->image);
        result.disposition = StereoDepthObservationDisposition::processed;
        result.reason.clear();
        remember(observation);
        return result;
    }

private:
    static bool supported_pixel_format(PixelFormat format) noexcept {
        return format == PixelFormat::gray8 || format == PixelFormat::bgr24;
    }

    static bool camera_ready(const CameraObservation& camera) noexcept {
        return camera.validity == ObservationValidity::valid && camera.usable();
    }

    [[nodiscard]] const StereoPairStatus* find_pair_status(
        const SensorObservation& observation) const noexcept {
        for (const auto& status : observation.stereo_pairs) {
            if (status.pair_id == pair_id_) return &status;
        }
        return nullptr;
    }

    [[nodiscard]] static const CameraObservation* find_camera(
        const SensorObservation& observation,
        const std::string& stream_id) noexcept {
        for (const auto& camera : observation.cameras) {
            if (camera.stream_id == stream_id) return &camera;
        }
        return nullptr;
    }

    [[nodiscard]] StereoDepthObservationResult base_result(
        const SensorObservation& observation) const {
        StereoDepthObservationResult result{};
        result.source_id = observation.source_id;
        result.evidence = observation.evidence;
        result.sequence = observation.sequence;
        result.sequence_present = observation.sequence_present;
        result.continuity_epoch = observation.continuity_epoch;
        result.continuity = observation.continuity;
        result.pair_id = pair_id_;
        result.calibration_id = calibration_.calibration_id;
        if (const auto* status = find_pair_status(observation)) {
            result.synchronization = status->synchronization;
        }
        result.reset_generation = reset_generation_;
        return result;
    }

    [[nodiscard]] StereoDepthObservationResult reject(
        StereoDepthObservationResult result,
        const SensorObservation& observation,
        StereoDepthObservationDisposition disposition,
        std::string reason,
        bool reset_already_performed) {
        result.disposition = disposition;
        result.reason = std::move(reason);
        result.depth = {};

        // Record forward source chronology for ordinary quality failures so a
        // missing/degraded frame does not masquerade as an additional raw
        // sequence gap. The next usable frame nevertheless starts a fresh
        // derived-stream generation if this input had not already reset it.
        remember_if_forward(observation);
        if (!reset_already_performed) pending_reset_ = true;
        return result;
    }

    void clear_chronology() noexcept {
        have_epoch_ = false;
        last_epoch_ = 0;
        have_sequence_ = false;
        last_sequence_ = 0;
    }

    void remember(const SensorObservation& observation) noexcept {
        have_epoch_ = true;
        last_epoch_ = observation.continuity_epoch;
        if (observation.sequence_present) {
            have_sequence_ = true;
            last_sequence_ = observation.sequence;
        } else {
            have_sequence_ = false;
            last_sequence_ = 0;
        }
    }

    void remember_if_forward(const SensorObservation& observation) noexcept {
        if (!have_epoch_ || observation.continuity_epoch != last_epoch_) {
            have_epoch_ = true;
            last_epoch_ = observation.continuity_epoch;
            have_sequence_ = observation.sequence_present;
            last_sequence_ = observation.sequence_present ? observation.sequence : 0;
            return;
        }
        if (observation.sequence_present &&
            (!have_sequence_ || observation.sequence > last_sequence_)) {
            have_sequence_ = true;
            last_sequence_ = observation.sequence;
        }
    }

    SensorCapabilities capabilities_;
    std::string pair_id_;
    const StereoPairInfo* pair_ = nullptr;
    StereoDepthCalibration calibration_;
    StereoDepthProcessor processor_;
    StereoDepthObservationPolicy policy_{};

    bool have_epoch_ = false;
    std::uint64_t last_epoch_ = 0;
    bool have_sequence_ = false;
    std::uint64_t last_sequence_ = 0;
    bool pending_reset_ = false;
    std::uint64_t reset_generation_ = 0;
};

}  // namespace bividi::depth
