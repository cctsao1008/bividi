#pragma once

#include "bividi/observation.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>

namespace bividi {

enum class ReplayPacing {
    step,
    as_fast_as_possible,
    real_time,
    scaled,
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

[[nodiscard]] const char* replay_pacing_name(ReplayPacing pacing) noexcept;

}  // namespace bividi
