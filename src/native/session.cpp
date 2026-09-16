#include "bividi/session.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <mutex>
#include <thread>

namespace bividi {
namespace {

constexpr int kMaxExposureUs = 20000;
constexpr int kMaxGainX10 = 240;
constexpr std::uint64_t kFramePeriodUs = 16667;
constexpr auto kTickPeriod = std::chrono::milliseconds(16);

TriggerMode next_trigger_mode(TriggerMode mode) noexcept {
    switch (mode) {
        case TriggerMode::free_run: return TriggerMode::software;
        case TriggerMode::software: return TriggerMode::hardware;
        case TriggerMode::hardware: return TriggerMode::command;
        case TriggerMode::command: return TriggerMode::free_run;
    }
    return TriggerMode::free_run;
}

}  // namespace

const char* trigger_mode_name(TriggerMode mode) noexcept {
    switch (mode) {
        case TriggerMode::free_run: return "Free Run";
        case TriggerMode::software: return "Software";
        case TriggerMode::hardware: return "Hardware";
        case TriggerMode::command: return "Command";
    }
    return "Unknown";
}

struct SyntheticCaptureSession::Impl {
    Impl() {
        state.capture.state = CaptureState::running;
        state.nominal_fps = 60.0;
        state.exposure_us = 7500;
        state.gain_x10 = 10;
        state.trigger_mode = TriggerMode::free_run;
        state.imu_rate_hz = 600;
        state.source_id = "synthetic";
        state.last_action = "synthetic source ready";
        fps_window_start = std::chrono::steady_clock::now();
        ticker = std::thread([this] { tick_loop(); });
    }

    ~Impl() {
        stop.store(true);
        if (ticker.joinable()) {
            ticker.join();
        }
    }

    void tick_loop() {
        while (!stop.load()) {
            const auto now = std::chrono::steady_clock::now();
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (state.capture.state == CaptureState::running) {
                    ++state.capture.frames;
                    ++fps_window_frames;
                    state.exposure_start_us = state.capture.frames * kFramePeriodUs;
                    state.exposure_end_us =
                        state.exposure_start_us + static_cast<std::uint64_t>(state.exposure_us);
                }

                const auto elapsed = std::chrono::duration<double>(now - fps_window_start).count();
                if (elapsed >= 0.5) {
                    state.fps = fps_window_frames / elapsed;
                    fps_window_frames = 0;
                    fps_window_start = now;
                }
            }
            std::this_thread::sleep_for(kTickPeriod);
        }
    }

    mutable std::mutex mutex;
    SessionStatus state{};
    std::atomic<bool> stop{false};
    std::thread ticker;
    std::chrono::steady_clock::time_point fps_window_start{};
    std::uint64_t fps_window_frames = 0;
};

SyntheticCaptureSession::SyntheticCaptureSession() : impl_(new Impl()) {}

SyntheticCaptureSession::~SyntheticCaptureSession() {
    delete impl_;
    impl_ = nullptr;
}

SessionStatus SyntheticCaptureSession::snapshot() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->state;
}

bool SyntheticCaptureSession::toggle_capture() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->state.capture.state == CaptureState::running) {
        impl_->state.capture.state = CaptureState::paused;
        impl_->state.fps = 0.0;
        impl_->state.last_action = "capture paused";
    } else if (impl_->state.capture.state == CaptureState::paused ||
               impl_->state.capture.state == CaptureState::idle) {
        impl_->state.capture.state = CaptureState::running;
        impl_->state.last_action = "capture resumed";
    } else {
        return false;
    }
    return true;
}

bool SyntheticCaptureSession::cycle_trigger() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.trigger_mode = next_trigger_mode(impl_->state.trigger_mode);
    impl_->state.last_action =
        std::string("trigger mode -> ") + trigger_mode_name(impl_->state.trigger_mode);
    return true;
}

bool SyntheticCaptureSession::reconnect() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.capture.frames = 0;
    impl_->state.capture.drops = 0;
    impl_->state.capture.duplicates = 0;
    impl_->state.capture.out_of_order = 0;
    impl_->state.exposure_start_us = 0;
    impl_->state.exposure_end_us = 0;
    impl_->state.fps = 0.0;
    impl_->fps_window_frames = 0;
    impl_->fps_window_start = std::chrono::steady_clock::now();
    impl_->state.last_action = "synthetic reconnect/reset";
    return true;
}

bool SyntheticCaptureSession::set_exposure_us(int value) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.exposure_us = std::clamp(value, 1, kMaxExposureUs);
    impl_->state.last_action = "exposure updated";
    return true;
}

bool SyntheticCaptureSession::set_gain_x10(int value) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.gain_x10 = std::clamp(value, 0, kMaxGainX10);
    impl_->state.last_action = "gain updated";
    return true;
}

}  // namespace bividi
