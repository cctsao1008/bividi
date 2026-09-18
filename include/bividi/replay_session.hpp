#pragma once

#include "bividi/replay.hpp"
#include "bividi/session.hpp"

#include <filesystem>
#include <memory>
#include <string>

namespace bividi {

// Engineering/UI adapter over the native ReplaySource. ReplaySource remains the
// authoritative SensorObservation producer; this class only supplies the
// legacy viewer/web lifecycle and preview surface.
struct ReplaySessionConfig {
    std::filesystem::path session_dir;
    double rate = 1.0;
    bool start_paused = false;
    std::string source_id;
    EvidenceKind evidence_override = EvidenceKind::unknown;
};

class ReplayCaptureSession final : public CaptureSession {
public:
    explicit ReplayCaptureSession(ReplaySessionConfig config);
    ~ReplayCaptureSession() override;

    ReplayCaptureSession(const ReplayCaptureSession&) = delete;
    ReplayCaptureSession& operator=(const ReplayCaptureSession&) = delete;

    [[nodiscard]] SessionStatus snapshot() const override;
    [[nodiscard]] bool latest_stereo_preview(StereoPreviewFrame& out) const override;

    bool toggle_capture() override;
    bool cycle_trigger() override;
    bool reconnect() override;
    bool set_exposure_us(int value) override;
    bool set_gain_x10(int value) override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace bividi
