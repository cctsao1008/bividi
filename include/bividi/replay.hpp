#pragma once

#include "bividi/observation.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace bividi {

enum class ReplayPacing {
    step,
    as_fast_as_possible,
    real_time,
    scaled,
};

// Optional replay-stage interception seam used by deterministic test tooling.
// ReplaySource materializes and conformance-checks the source observation first;
// an interceptor stage may then emit zero, one, or many observations and may
// buffer observations until a later input or flush(). This is what lets #59
// implement drop/duplicate/reorder/timing/pairing faults without adding fault
// branches to production device decoding.
//
// Interceptor output is deliberately NOT revalidated by the stage: a fault
// recipe may intentionally produce degraded or structurally invalid evidence.
// Consumers/tests remain responsible for asserting the expected disposition.
class ReplayObservationInterceptor {
public:
    virtual ~ReplayObservationInterceptor() = default;

    virtual void reset() {}

    virtual void transform(
        std::size_t source_position,
        SensorObservation observation,
        std::vector<SensorObservation>& output) = 0;

    virtual void flush(std::vector<SensorObservation>& output) {
        (void)output;
    }
};

struct ReplayConfig {
    std::filesystem::path session_dir;
    ReplayPacing pacing = ReplayPacing::step;
    double rate = 1.0;
    std::string source_id;
    EvidenceKind evidence_override = EvidenceKind::unknown;
};

// Adapter-level provenance from the imported recording. This remains separate
// from SensorObservation so vendor/source metadata does not expand the stable
// core observation contract.
struct ReplayMetadata {
    std::string source_schema;
    std::string product;
    std::string serial;
    std::string sdk_version;
    std::string device_type;
    std::string isp_version;
    std::string fpga_version;
    std::uint32_t mode_index = 0;
    double nominal_fps = 0.0;
    std::uint32_t frame_stride = 1;
    EvidenceKind evidence = EvidenceKind::unknown;
    std::size_t timeline_observations = 0;
    std::size_t image_pairs = 0;
    std::size_t imu_samples = 0;
};

// Native replay importer for Bividi recording/session evidence. The first
// supported importer is the existing Nori calibration-session layout:
// capture.json + frames.csv + imu.csv + camera_a/b image files.
//
// Replay always emits the #11 SensorObservation contract. Original producer
// timing is preserved; replay pacing is carried separately in the replay clock
// domain and never overwrites host/device timestamps.
class ReplaySource {
public:
    explicit ReplaySource(ReplayConfig config);
    ~ReplaySource();

    ReplaySource(ReplaySource&&) noexcept;
    ReplaySource& operator=(ReplaySource&&) noexcept;

    ReplaySource(const ReplaySource&) = delete;
    ReplaySource& operator=(const ReplaySource&) = delete;

    [[nodiscard]] const SensorCapabilities& capabilities() const noexcept;
    [[nodiscard]] const ReplayMetadata& metadata() const noexcept;
    [[nodiscard]] std::size_t size() const noexcept;
    [[nodiscard]] std::size_t position() const noexcept;
    [[nodiscard]] bool eof() const noexcept;

    // Emits the next original observation in deterministic source order. Step
    // and as-fast modes never sleep. Real-time/scaled modes pace from preserved
    // original host-receive deltas when those deltas are monotonic.
    bool next(SensorObservation& out);

    // Rewind to the first recorded observation. Original timestamps/sequence
    // are unchanged; a new replay scheduling epoch begins on the next call.
    void reset();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// Decorator above ReplaySource that provides the explicit #59 fault-injection
// interception point. Normal replay does not pass through this class, so fault
// support adds no branches to the production decoder/import path.
class InterceptedReplaySource {
public:
    InterceptedReplaySource(
        ReplaySource source,
        std::shared_ptr<ReplayObservationInterceptor> interceptor);
    ~InterceptedReplaySource();

    InterceptedReplaySource(InterceptedReplaySource&&) noexcept;
    InterceptedReplaySource& operator=(InterceptedReplaySource&&) noexcept;

    InterceptedReplaySource(const InterceptedReplaySource&) = delete;
    InterceptedReplaySource& operator=(const InterceptedReplaySource&) = delete;

    [[nodiscard]] const SensorCapabilities& capabilities() const noexcept;
    [[nodiscard]] const ReplayMetadata& metadata() const noexcept;

    // Source timeline size/position remain explicit even if the interceptor
    // drops or duplicates emitted observations.
    [[nodiscard]] std::size_t source_size() const noexcept;
    [[nodiscard]] std::size_t source_position() const noexcept;
    [[nodiscard]] bool eof() const noexcept;

    bool next(SensorObservation& out);
    void reset();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

[[nodiscard]] const char* replay_pacing_name(ReplayPacing pacing) noexcept;

}  // namespace bividi
