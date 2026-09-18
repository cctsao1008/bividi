#pragma once

#include "bividi/capabilities.hpp"
#include "bividi/capture.hpp"

#include <cstdint>
#include <string>

namespace bividi {

[[nodiscard]] const char* trigger_mode_name(TriggerMode mode) noexcept;

// Engineering/UI stereo preview only. This remains deliberately smaller than
// the stable SensorObservation contract: it carries two borrowed image views
// plus the lease and timing needed to display them safely.
struct StereoPreviewFrame {
    FrameLease lease{};
    ImageView camera_a{};
    ImageView camera_b{};
    std::uint64_t sequence = 0;
    std::uint64_t host_receive_monotonic_ns = 0;
    std::uint64_t exposure_start_us = 0;
    std::uint64_t exposure_end_us = 0;
    std::uint32_t imu_rate_hz = 0;

    [[nodiscard]] bool valid() const noexcept {
        return lease.valid() && !camera_a.empty() && !camera_b.empty();
    }
};

// Lightweight engineering/runtime status shared by viewer and web front ends.
// This control/status surface does not replace SensorObservation.
struct SessionStatus {
    CaptureStatus capture{};
    double fps = 0.0;
    double nominal_fps = 0.0;
    int exposure_us = 0;
    int gain_x10 = 0;
    TriggerMode trigger_mode = TriggerMode::free_run;
    std::uint64_t exposure_start_us = 0;
    std::uint64_t exposure_end_us = 0;
    std::uint32_t imu_rate_hz = 0;
    std::string source_id;
    std::string last_action;

    [[nodiscard]] bool running() const noexcept {
        return capture.state == CaptureState::running;
    }
};

// Shared lifecycle/control surface for engineering front ends. Normalized data
// consumers should use the SensorObservation boundary rather than this preview
// interface.
class CaptureSession {
public:
    virtual ~CaptureSession() = default;

    [[nodiscard]] virtual SessionStatus snapshot() const = 0;

    // Optional engineering-preview surface. A returned frame keeps its backing
    // image storage alive through FrameLease and may therefore outlive the
    // session mutex/producer iteration that published it.
    [[nodiscard]] virtual bool latest_stereo_preview(StereoPreviewFrame& out) const {
        out = {};
        return false;
    }

    virtual bool toggle_capture() = 0;
    virtual bool cycle_trigger() = 0;
    virtual bool reconnect() = 0;
    virtual bool set_exposure_us(int value) = 0;
    virtual bool set_gain_x10(int value) = 0;
};

// Hardware-independent reference session used by viewer/web self-tests and as
// the behavioral oracle for future live-session wiring.
class SyntheticCaptureSession final : public CaptureSession {
public:
    SyntheticCaptureSession();
    ~SyntheticCaptureSession() override;

    SyntheticCaptureSession(const SyntheticCaptureSession&) = delete;
    SyntheticCaptureSession& operator=(const SyntheticCaptureSession&) = delete;

    [[nodiscard]] SessionStatus snapshot() const override;
    bool toggle_capture() override;
    bool cycle_trigger() override;
    bool reconnect() override;
    bool set_exposure_us(int value) override;
    bool set_gain_x10(int value) override;

private:
    struct Impl;
    Impl* impl_ = nullptr;
};

}  // namespace bividi
