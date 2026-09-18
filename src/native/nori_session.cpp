#include "bividi/nori_session.hpp"
#include "bividi/decxin_observation.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <limits>
#include <mutex>
#include <optional>
#include <sstream>
#include <thread>
#include <utility>

namespace bividi::nori {
namespace {

using Clock = std::chrono::steady_clock;

TriggerMode next_trigger_mode(TriggerMode mode) noexcept {
    switch (mode) {
        case TriggerMode::free_run: return TriggerMode::software;
        case TriggerMode::software: return TriggerMode::hardware;
        case TriggerMode::hardware: return TriggerMode::command;
        case TriggerMode::command: return TriggerMode::free_run;
    }
    return TriggerMode::free_run;
}

std::uint32_t measured_imu_rate_hz(const decxin::DecodedFrame& frame) noexcept {
    const decxin::ImuSample* first = nullptr;
    const decxin::ImuSample* last = nullptr;
    std::uint32_t valid_count = 0;
    for (const auto& sample : frame.timing.imu_samples) {
        if (!sample.valid) continue;
        if (first == nullptr) first = &sample;
        last = &sample;
        ++valid_count;
    }
    if (first == nullptr || last == nullptr || valid_count < 2 ||
        last->extended_time_us <= first->extended_time_us) {
        return 0;
    }
    const auto span_us = last->extended_time_us - first->extended_time_us;
    const double rate = static_cast<double>(valid_count - 1) * 1'000'000.0 /
                        static_cast<double>(span_us);
    if (rate <= 0.0 || rate > static_cast<double>(std::numeric_limits<std::uint32_t>::max())) {
        return 0;
    }
    return static_cast<std::uint32_t>(std::llround(rate));
}

std::uint32_t quantize_gain(int gain_x10, const SensorGainInfo& info) noexcept {
    const auto requested = static_cast<std::uint32_t>(std::max(0, (gain_x10 + 5) / 10));
    if (info.maximum < info.minimum) return requested;

    const auto clamped = std::clamp(requested, info.minimum, info.maximum);
    const auto step = info.step == 0 ? 1u : info.step;
    const auto offset = clamped - info.minimum;
    const auto steps = (static_cast<std::uint64_t>(offset) + step / 2u) / step;
    const auto quantized = static_cast<std::uint64_t>(info.minimum) + steps * step;
    return static_cast<std::uint32_t>(
        std::min<std::uint64_t>(quantized, info.maximum));
}

void track_sequence(
    CaptureStatus& status,
    std::uint64_t sequence,
    bool& have_last,
    std::uint64_t& last_sequence) noexcept {
    if (!have_last) {
        have_last = true;
        last_sequence = sequence;
        return;
    }

    if (sequence == last_sequence) {
        ++status.duplicates;
        return;
    }

    if (sequence > last_sequence) {
        if (sequence > last_sequence + 1) {
            status.drops += sequence - last_sequence - 1;
        }
        last_sequence = sequence;
        return;
    }

    // Linux V4L2 sequence is 32-bit. Recognize the normal wrap case without
    // teaching the public capture contract about platform-specific bit widths.
    constexpr std::uint64_t kU32Max = 0xffffffffULL;
    constexpr std::uint64_t kHalfU32 = 0x80000000ULL;
    if (last_sequence <= kU32Max && sequence <= kU32Max &&
        last_sequence - sequence > kHalfU32) {
        const auto advance = (kU32Max - last_sequence) + 1 + sequence;
        if (advance > 1) status.drops += advance - 1;
        last_sequence = sequence;
        return;
    }

    ++status.out_of_order;
}

std::string source_id(const StreamConfig& config) {
    std::ostringstream out;
    out << "nori:" << config.device_index << "/mode:" << config.mode_index;
    return out.str();
}

SensorCapabilities make_observation_capabilities() {
    SensorCapabilities caps{};
    caps.cameras = {
        {
            "camera_a",
            "primary",
            PixelFormat::bgr24,
            CameraModality::unknown,
            static_cast<std::uint32_t>(decxin::kCameraWidth),
            static_cast<std::uint32_t>(decxin::kTransportHeight),
        },
        {
            "camera_b",
            "primary",
            PixelFormat::bgr24,
            CameraModality::unknown,
            static_cast<std::uint32_t>(decxin::kCameraWidth),
            static_cast<std::uint32_t>(decxin::kTransportHeight),
        },
    };
    caps.stereo_pairs = {{"stereo0", "camera_a", "camera_b"}};
    caps.imu = true;
    caps.audio = false;
    caps.timing.host_receive_monotonic = true;
    caps.timing.device_frame_time = false;
    caps.timing.exposure_start_end = true;
    caps.timing.imu_sample_time = true;
    // The device carries common embedded timing metadata, but no runtime
    // measurement in this adapter establishes a synchronization bound.
    caps.timing.hardware_sync = false;
    return caps;
}

}  // namespace

struct NoriCaptureSession::Impl {
    explicit Impl(NoriSessionConfig session_config)
        : config(std::move(session_config)),
          capabilities(make_observation_capabilities()) {
        const auto conformance = validate_capabilities(capabilities);
        if (!conformance.ok) {
            throw std::invalid_argument("internal Nori normalized capabilities are invalid");
        }
        state.capture.state = CaptureState::idle;
        state.source_id = source_id(config.stream);
        state.last_action = "Nori session starting";
        worker = std::thread([this] { worker_loop(); });
    }

    ~Impl() {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stop = true;
        }
        wake.notify_all();
        if (worker.joinable()) worker.join();
    }

    void set_error(const std::string& message) {
        std::lock_guard<std::mutex> lock(mutex);
        state.capture.state = CaptureState::error;
        state.fps = 0.0;
        state.last_action = message;
        latest_preview = {};
        latest_normalized_observation = {};
    }

    void publish_connection(Stream& stream) {
        const auto selected = stream.mode();
        TriggerMode trigger = TriggerMode::free_run;
        int exposure = 0;
        int gain_x10 = 0;

        try { trigger = stream.trigger_mode(); } catch (...) {}
        try { exposure = static_cast<int>(stream.exposure_us()); } catch (...) {}
        try { gain_x10 = static_cast<int>(stream.gain_info().current * 10u); } catch (...) {}

        std::lock_guard<std::mutex> lock(mutex);
        if (have_connected_before) {
            ++continuity_epoch;
        } else {
            have_connected_before = true;
        }
        next_observation_reinitialized = true;

        state.capture = {};
        state.capture.state = desired_running ? CaptureState::running : CaptureState::paused;
        state.fps = 0.0;
        state.nominal_fps = selected.fps;
        state.exposure_us = exposure;
        state.gain_x10 = gain_x10;
        state.trigger_mode = trigger;
        state.exposure_start_us = 0;
        state.exposure_end_us = 0;
        state.imu_rate_hz = 0;
        state.source_id = source_id(config.stream);
        state.last_action = "Nori stream connected";
        latest_preview = {};
        latest_normalized_observation = {};
        have_last_sequence = false;
        last_sequence = 0;
        fps_window_frames = 0;
        fps_window_start = Clock::now();
    }

    void apply_controls(Stream& stream) {
        std::optional<int> exposure;
        std::optional<int> gain;
        std::optional<TriggerMode> trigger;
        {
            std::lock_guard<std::mutex> lock(mutex);
            exposure.swap(pending_exposure_us);
            gain.swap(pending_gain_x10);
            trigger.swap(pending_trigger_mode);
        }

        if (trigger.has_value()) {
            try {
                stream.set_trigger_mode(*trigger);
                const auto actual = stream.trigger_mode();
                std::lock_guard<std::mutex> lock(mutex);
                state.trigger_mode = actual;
                state.last_action = std::string("trigger mode -> ") + trigger_mode_name(actual);
            } catch (const std::exception& error) {
                std::lock_guard<std::mutex> lock(mutex);
                state.last_action = std::string("trigger control failed: ") + error.what();
            }
        }

        if (exposure.has_value()) {
            try {
                stream.set_exposure_us(static_cast<std::uint32_t>(*exposure));
                const auto actual = stream.exposure_us();
                std::lock_guard<std::mutex> lock(mutex);
                state.exposure_us = static_cast<int>(actual);
                state.last_action = "exposure updated";
            } catch (const std::exception& error) {
                std::lock_guard<std::mutex> lock(mutex);
                state.last_action = std::string("exposure control failed: ") + error.what();
            }
        }

        if (gain.has_value()) {
            try {
                const auto before = stream.gain_info();
                const auto target = quantize_gain(*gain, before);
                stream.set_gain_multiplier(target);
                const auto actual = stream.gain_info();
                std::lock_guard<std::mutex> lock(mutex);
                state.gain_x10 = static_cast<int>(actual.current * 10u);
                state.last_action = "gain updated";
            } catch (const std::exception& error) {
                std::lock_guard<std::mutex> lock(mutex);
                state.last_action = std::string("gain control failed: ") + error.what();
            }
        }
    }

    void publish_frame(const DecodedCapture& capture) {
        StereoPreviewFrame preview{};
        preview.lease = capture.decoded.lease;
        preview.camera_a = capture.decoded.camera_a;
        preview.camera_b = capture.decoded.camera_b;
        preview.sequence = capture.decoded.sequence;
        preview.host_receive_monotonic_ns = capture.decoded.host_receive_monotonic_ns;
        preview.exposure_start_us = capture.decoded.timing.exposure_start_us;
        preview.exposure_end_us = capture.decoded.timing.exposure_end_us;
        preview.imu_rate_hz = measured_imu_rate_hz(capture.decoded);

        const auto now = Clock::now();
        std::lock_guard<std::mutex> lock(mutex);

        decxin::ObservationContext context{};
        context.source_id = source_id(config.stream);
        context.evidence = config.evidence;
        context.continuity_epoch = continuity_epoch;
        context.continuity = next_observation_reinitialized
            ? ContinuityState::reinitialized
            : ContinuityState::continuous;
        context.calibration = config.calibration;
        context.configuration_revision = config.configuration_revision;
        auto normalized = decxin::to_sensor_observation(capture.decoded, context);
        const auto conformance = validate_observation(normalized, &capabilities);
        if (!conformance.ok) {
            throw Error("Nori normalized observation violated the #11 contract");
        }

        track_sequence(state.capture, preview.sequence, have_last_sequence, last_sequence);
        ++state.capture.frames;
        ++fps_window_frames;
        state.capture.state = CaptureState::running;

        // Keep the configured/read-back shutter in state.exposure_us. Embedded
        // EE-ES is a measured device timestamp interval and must remain a
        // separate time-domain observation instead of becoming control state.
        state.exposure_start_us = preview.exposure_start_us;
        state.exposure_end_us = preview.exposure_end_us;
        if (preview.imu_rate_hz != 0) state.imu_rate_hz = preview.imu_rate_hz;
        latest_preview = std::move(preview);
        latest_normalized_observation = std::move(normalized);
        next_observation_reinitialized = false;

        const auto elapsed = std::chrono::duration<double>(now - fps_window_start).count();
        if (elapsed >= 0.5) {
            state.fps = static_cast<double>(fps_window_frames) / elapsed;
            fps_window_frames = 0;
            fps_window_start = now;
        }
    }

    void wait_disconnected() {
        std::unique_lock<std::mutex> lock(mutex);
        wake.wait(lock, [this] { return stop || reconnect_requested; });
    }

    void wait_paused() {
        std::unique_lock<std::mutex> lock(mutex);
        wake.wait(lock, [this] {
            return stop || reconnect_requested || desired_running ||
                   pending_exposure_us.has_value() || pending_gain_x10.has_value() ||
                   pending_trigger_mode.has_value();
        });
    }

    void worker_loop() {
        std::unique_ptr<Stream> stream;
        DecxinPipeline pipeline(NormalizationOwnership::own_output);

        while (true) {
            bool should_reconnect = false;
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (stop) break;
                if (reconnect_requested) {
                    reconnect_requested = false;
                    should_reconnect = true;
                    state.capture.state = CaptureState::idle;
                    state.fps = 0.0;
                    state.last_action = stream ? "reconnecting Nori stream" : "connecting Nori stream";
                    latest_preview = {};
                    latest_normalized_observation = {};
                }
            }

            if (should_reconnect) {
                // Vendor stop/uninit can block. Never hold the public session
                // mutex while tearing down the SDK path.
                stream.reset();
                pipeline.reset_timestamps();
            }

            if (!stream) {
                if (!should_reconnect) {
                    wait_disconnected();
                    continue;
                }

                try {
                    stream = std::make_unique<Stream>(config.stream);
                    pipeline.reset_timestamps();
                    bool run = true;
                    {
                        std::lock_guard<std::mutex> lock(mutex);
                        run = desired_running;
                    }
                    if (!run) stream->stop_video();
                    publish_connection(*stream);
                } catch (const std::exception& error) {
                    stream.reset();
                    set_error(std::string("Nori connect failed: ") + error.what());
                    continue;
                }
            }

            bool run = true;
            bool reconnect = false;
            {
                std::lock_guard<std::mutex> lock(mutex);
                if (stop) break;
                reconnect = reconnect_requested;
                run = desired_running;
            }
            if (reconnect) continue;

            try {
                if (run && !stream->running()) {
                    stream->start_video();
                    std::lock_guard<std::mutex> lock(mutex);
                    state.capture.state = CaptureState::running;
                    state.last_action = "capture resumed";
                } else if (!run && stream->running()) {
                    stream->stop_video();
                    std::lock_guard<std::mutex> lock(mutex);
                    state.capture.state = CaptureState::paused;
                    state.fps = 0.0;
                    state.last_action = "capture paused";
                }
            } catch (const std::exception& error) {
                stream.reset();
                set_error(std::string("Nori stream state failed: ") + error.what());
                continue;
            }

            apply_controls(*stream);

            if (!run) {
                wait_paused();
                continue;
            }

            try {
                auto raw = stream->next_frame();
                if (!raw.valid()) continue;  // timeout/no-buffer is not a fatal stream error

                auto capture = pipeline.decode(raw);
                raw.lease.reset();  // own_output makes prompt vendor-buffer return safe
                if (!capture.valid()) {
                    throw Error("Nori DECXIN pipeline produced an invalid decoded frame");
                }
                publish_frame(capture);
            } catch (const std::exception& error) {
                stream.reset();
                set_error(std::string("Nori capture failed: ") + error.what());
            }
        }
    }

    NoriSessionConfig config{};
    const SensorCapabilities capabilities;
    mutable std::mutex mutex;
    std::condition_variable wake;
    SessionStatus state{};
    StereoPreviewFrame latest_preview{};
    SensorObservation latest_normalized_observation{};
    bool stop = false;
    bool desired_running = true;
    bool reconnect_requested = true;
    std::optional<int> pending_exposure_us;
    std::optional<int> pending_gain_x10;
    std::optional<TriggerMode> pending_trigger_mode;
    bool have_last_sequence = false;
    std::uint64_t last_sequence = 0;
    std::uint64_t continuity_epoch = 0;
    bool have_connected_before = false;
    bool next_observation_reinitialized = true;
    Clock::time_point fps_window_start = Clock::now();
    std::uint64_t fps_window_frames = 0;
    std::thread worker;
};

NoriCaptureSession::NoriCaptureSession(NoriSessionConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

NoriCaptureSession::~NoriCaptureSession() = default;

SessionStatus NoriCaptureSession::snapshot() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->state;
}

bool NoriCaptureSession::latest_stereo_preview(StereoPreviewFrame& out) const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    out = impl_->latest_preview;
    return out.valid();
}

const SensorCapabilities& NoriCaptureSession::observation_capabilities() const noexcept {
    return impl_->capabilities;
}

bool NoriCaptureSession::latest_observation(SensorObservation& out) const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->latest_normalized_observation.cameras.empty()) return false;
    out = impl_->latest_normalized_observation;
    return true;
}

bool NoriCaptureSession::toggle_capture() {
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        impl_->desired_running = !impl_->desired_running;
        impl_->state.last_action = impl_->desired_running ? "resume requested" : "pause requested";
    }
    impl_->wake.notify_all();
    return true;
}

bool NoriCaptureSession::cycle_trigger() {
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        const auto base = impl_->pending_trigger_mode.value_or(impl_->state.trigger_mode);
        impl_->pending_trigger_mode = next_trigger_mode(base);
        impl_->state.last_action = "trigger mode change requested";
    }
    impl_->wake.notify_all();
    return true;
}

bool NoriCaptureSession::reconnect() {
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        impl_->reconnect_requested = true;
        impl_->state.last_action = "reconnect requested";
    }
    impl_->wake.notify_all();
    return true;
}

bool NoriCaptureSession::set_exposure_us(int value) {
    if (value <= 0) return false;
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        impl_->pending_exposure_us = value;
        impl_->state.last_action = "exposure change requested";
    }
    impl_->wake.notify_all();
    return true;
}

bool NoriCaptureSession::set_gain_x10(int value) {
    if (value < 0) return false;
    {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        impl_->pending_gain_x10 = value;
        impl_->state.last_action = "gain change requested";
    }
    impl_->wake.notify_all();
    return true;
}

}  // namespace bividi::nori
