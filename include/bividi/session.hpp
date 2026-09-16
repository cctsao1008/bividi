#pragma once

#include "bividi/capture.hpp"

#include <cstdint>
#include <string>

namespace bividi {

enum class TriggerMode {
    free_run,
    software,
    hardware,
    command,
};

[[nodiscard]] const char* trigger_mode_name(TriggerMode mode) noexcept;

// Lightweight engineering/runtime status shared by viewer and web front ends.
// This is not the final sensor-observation schema owned by Issue #11.
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

// Shared lifecycle/control surface for engineering front ends.
// Frame delivery remains on CapturedFrame -> device adapter -> decoded-frame
// boundaries until the normalized observation contract is frozen under #11.
class CaptureSession {
public:
    virtual ~CaptureSession() = default;

    [[nodiscard]] virtual SessionStatus snapshot() const = 0;
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
