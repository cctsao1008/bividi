#include "bividi/replay_session.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <limits>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

namespace bividi {
namespace {

using Clock = std::chrono::steady_clock;

ReplayConfig source_config(const ReplaySessionConfig& config) {
    if (config.session_dir.empty()) {
        throw std::invalid_argument("replay session_dir must not be empty");
    }
    if (!(config.rate > 0.0) || !std::isfinite(config.rate)) {
        throw std::invalid_argument("replay session rate must be finite and > 0");
    }

    ReplayConfig source{};
    source.session_dir = config.session_dir;
    source.pacing = ReplayPacing::step;
    source.rate = 1.0;
    source.source_id = config.source_id;
    source.evidence_override = config.evidence_override;
    return source;
}

std::string engineering_source_id(
    const ReplaySessionConfig& config,
    const ReplayMetadata& metadata) {
    if (!config.source_id.empty()) return config.source_id;
    if (!metadata.serial.empty()) return "replay:nori:" + metadata.serial;
    return "replay:" + config.session_dir.filename().string();
}

const CameraObservation* find_camera(
    const SensorObservation& observation,
    const char* stream_id) noexcept {
    for (const auto& camera : observation.cameras) {
        if (camera.stream_id == stream_id) return &camera;
    }
    return nullptr;
}

cv::Mat owned_bgr_preview(const ImageView& view) {
    if (view.empty()) return {};

    if (view.pixel_format == PixelFormat::bgr24 && view.bytes_per_pixel == 3) {
        cv::Mat source(
            static_cast<int>(view.height),
            static_cast<int>(view.width),
            CV_8UC3,
            const_cast<std::uint8_t*>(view.data),
            view.row_stride);
        return source.clone();
    }

    if (view.pixel_format == PixelFormat::gray8 && view.bytes_per_pixel == 1) {
        cv::Mat source(
            static_cast<int>(view.height),
            static_cast<int>(view.width),
            CV_8UC1,
            const_cast<std::uint8_t*>(view.data),
            view.row_stride);
        cv::Mat bgr;
        cv::cvtColor(source, bgr, cv::COLOR_GRAY2BGR);
        return bgr;
    }

    throw std::runtime_error("replay preview supports only GRAY8 or BGR24 observations");
}

ImageView bgr_view(const cv::Mat& image) {
    if (image.empty() || image.type() != CV_8UC3 ||
        image.cols <= 0 || image.rows <= 0 ||
        image.step > std::numeric_limits<std::uint32_t>::max()) {
        return {};
    }
    return ImageView{
        image.data,
        static_cast<std::uint32_t>(image.cols),
        static_cast<std::uint32_t>(image.rows),
        static_cast<std::uint32_t>(image.step),
        3,
        PixelFormat::bgr24,
    };
}

struct PreviewOwner {
    cv::Mat camera_a;
    cv::Mat camera_b;
};

std::uint32_t measured_imu_rate_hz(const SensorObservation& observation) noexcept {
    const ImuObservation* first = nullptr;
    const ImuObservation* last = nullptr;
    std::uint32_t count = 0;
    for (const auto& sample : observation.imu) {
        if (sample.validity == ObservationValidity::invalid || !sample.sample_time.present ||
            sample.sample_time.domain != ClockDomain::device ||
            sample.sample_time.unit != TimeUnit::microseconds) {
            continue;
        }
        if (first == nullptr) first = &sample;
        last = &sample;
        ++count;
    }
    if (first == nullptr || last == nullptr || count < 2 ||
        last->sample_time.ticks <= first->sample_time.ticks) {
        return 0;
    }
    const auto span_us = last->sample_time.ticks - first->sample_time.ticks;
    const double rate = static_cast<double>(count - 1) * 1'000'000.0 /
                        static_cast<double>(span_us);
    if (!(rate > 0.0) ||
        rate > static_cast<double>(std::numeric_limits<std::uint32_t>::max())) {
        return 0;
    }
    return static_cast<std::uint32_t>(std::llround(rate));
}

void track_sequence(
    CaptureStatus& status,
    const SensorObservation& observation,
    bool& have_last,
    std::uint64_t& last_sequence) noexcept {
    if (!observation.sequence_present) return;
    const auto sequence = observation.sequence;
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
        if (sequence > last_sequence + 1) status.drops += sequence - last_sequence - 1;
        last_sequence = sequence;
        return;
    }

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

std::uint64_t host_time_ns(const SensorObservation& observation) noexcept {
    const auto& time = observation.timing.host_receive;
    if (!time.present || time.domain != ClockDomain::host_monotonic) return 0;
    if (time.unit == TimeUnit::nanoseconds) return time.ticks;
    if (time.unit == TimeUnit::microseconds &&
        time.ticks <= std::numeric_limits<std::uint64_t>::max() / 1000ULL) {
        return time.ticks * 1000ULL;
    }
    return 0;
}

}  // namespace

struct ReplayCaptureSession::Impl {
    explicit Impl(ReplaySessionConfig replay_config)
        : config(std::move(replay_config)),
          source(source_config(config)),
          desired_running(!config.start_paused) {
        state.capture.state = desired_running ? CaptureState::running : CaptureState::paused;
        state.nominal_fps = source.metadata().nominal_fps;
        state.source_id = engineering_source_id(config, source.metadata());
        state.last_action = desired_running ? "replay ready" : "replay ready (paused)";
        fps_window_start = Clock::now();
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

    void reset_state_locked(const char* action) {
        state.capture = {};
        state.capture.state = desired_running ? CaptureState::running : CaptureState::paused;
        state.fps = 0.0;
        state.exposure_us = 0;
        state.gain_x10 = 0;
        state.exposure_start_us = 0;
        state.exposure_end_us = 0;
        state.imu_rate_hz = 0;
        state.nominal_fps = source.metadata().nominal_fps;
        state.source_id = engineering_source_id(config, source.metadata());
        state.last_action = action;
        latest_preview = {};
        latest_observation = {};
        have_latest_observation = false;
        have_last_sequence = false;
        last_sequence = 0;
        fps_window_frames = 0;
        fps_window_start = Clock::now();
        schedule_started = false;
        schedule_source_start_ns = 0;
        at_eof = false;
    }

    Clock::time_point target_time_locked(const SensorObservation& observation) {
        const auto source_ns = host_time_ns(observation);
        const auto now = Clock::now();
        if (!schedule_started || source_ns == 0 || source_ns < schedule_source_start_ns) {
            schedule_started = true;
            schedule_source_start_ns = source_ns;
            schedule_wall_start = now;
            return now;
        }

        const auto source_delta_ns = source_ns - schedule_source_start_ns;
        const long double scaled_ns =
            static_cast<long double>(source_delta_ns) / static_cast<long double>(config.rate);
        const auto limit = static_cast<long double>(std::numeric_limits<std::int64_t>::max());
        const auto replay_delta_ns = static_cast<std::int64_t>(std::min(scaled_ns, limit));
        return schedule_wall_start + std::chrono::nanoseconds(replay_delta_ns);
    }

    void publish_locked(const SensorObservation& observation) {
        track_sequence(state.capture, observation, have_last_sequence, last_sequence);
        ++state.capture.frames;
        ++fps_window_frames;
        state.capture.state = CaptureState::running;

        // Keep a normalized snapshot independent of the BGR engineering preview.
        // SensorObservation copies retain camera storage via FrameLease.
        latest_observation = observation;
        have_latest_observation = true;

        const auto* camera_a = find_camera(observation, "camera_a");
        const auto* camera_b = find_camera(observation, "camera_b");
        if (camera_a != nullptr && camera_b != nullptr &&
            camera_a->usable() && camera_b->usable()) {
            auto* owner = new PreviewOwner{
                owned_bgr_preview(camera_a->image),
                owned_bgr_preview(camera_b->image),
            };
            auto lease = FrameLease::adopt(owner, [](PreviewOwner* value) noexcept { delete value; });

            StereoPreviewFrame preview{};
            preview.lease = lease;
            preview.camera_a = bgr_view(owner->camera_a);
            preview.camera_b = bgr_view(owner->camera_b);
            preview.sequence = observation.sequence;
            preview.host_receive_monotonic_ns = host_time_ns(observation);
            if (camera_a->exposure.complete() &&
                camera_a->exposure.start.unit == TimeUnit::microseconds &&
                camera_a->exposure.end.unit == TimeUnit::microseconds) {
                preview.exposure_start_us = camera_a->exposure.start.ticks;
                preview.exposure_end_us = camera_a->exposure.end.ticks;
            }
            preview.imu_rate_hz = measured_imu_rate_hz(observation);
            latest_preview = std::move(preview);

            state.exposure_start_us = latest_preview.exposure_start_us;
            state.exposure_end_us = latest_preview.exposure_end_us;
        }

        const auto imu_rate = measured_imu_rate_hz(observation);
        if (imu_rate != 0) state.imu_rate_hz = imu_rate;

        const auto now = Clock::now();
        const auto elapsed = std::chrono::duration<double>(now - fps_window_start).count();
        if (elapsed >= 0.5) {
            state.fps = static_cast<double>(fps_window_frames) / elapsed;
            fps_window_frames = 0;
            fps_window_start = now;
        }
    }

    void set_error(const std::string& message) {
        std::lock_guard<std::mutex> lock(mutex);
        desired_running = false;
        state.capture.state = CaptureState::error;
        state.fps = 0.0;
        state.last_action = message;
        latest_observation = {};
        have_latest_observation = false;
        schedule_started = false;
        wake.notify_all();
    }

    void worker_loop() {
        std::optional<SensorObservation> pending;

        while (true) {
            {
                std::unique_lock<std::mutex> lock(mutex);
                wake.wait(lock, [this] {
                    return stop || reset_requested || desired_running;
                });
                if (stop) break;

                if (reset_requested) {
                    reset_requested = false;
                    lock.unlock();
                    source.reset();
                    pending.reset();
                    lock.lock();
                    reset_state_locked(desired_running ? "replay reset" : "replay reset (paused)");
                }

                if (!desired_running) continue;
            }

            if (!pending.has_value()) {
                try {
                    SensorObservation observation;
                    if (!source.next(observation)) {
                        std::lock_guard<std::mutex> lock(mutex);
                        at_eof = true;
                        desired_running = false;
                        state.capture.state = CaptureState::idle;
                        state.fps = 0.0;
                        state.last_action = "replay reached end";
                        schedule_started = false;
                        continue;
                    }
                    pending = std::move(observation);
                } catch (const std::exception& error) {
                    set_error(std::string("replay failed: ") + error.what());
                    continue;
                }
            }

            std::unique_lock<std::mutex> lock(mutex);
            if (stop) break;
            if (reset_requested || !desired_running) {
                schedule_started = false;
                continue;
            }

            const auto target = target_time_locked(*pending);
            const bool interrupted = wake.wait_until(lock, target, [this] {
                return stop || reset_requested || !desired_running;
            });
            if (interrupted) {
                schedule_started = false;
                continue;
            }

            try {
                publish_locked(*pending);
                pending.reset();
            } catch (const std::exception& error) {
                lock.unlock();
                set_error(std::string("replay preview failed: ") + error.what());
            }
        }
    }

    ReplaySessionConfig config;
    ReplaySource source;

    mutable std::mutex mutex;
    std::condition_variable wake;
    bool stop = false;
    bool desired_running = false;
    bool reset_requested = false;
    bool at_eof = false;

    SessionStatus state{};
    StereoPreviewFrame latest_preview{};
    SensorObservation latest_observation{};
    bool have_latest_observation = false;

    bool have_last_sequence = false;
    std::uint64_t last_sequence = 0;
    std::uint64_t fps_window_frames = 0;
    Clock::time_point fps_window_start{};

    bool schedule_started = false;
    std::uint64_t schedule_source_start_ns = 0;
    Clock::time_point schedule_wall_start{};

    std::thread worker;
};

ReplayCaptureSession::ReplayCaptureSession(ReplaySessionConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

ReplayCaptureSession::~ReplayCaptureSession() = default;

SessionStatus ReplayCaptureSession::snapshot() const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->state;
}

bool ReplayCaptureSession::latest_stereo_preview(StereoPreviewFrame& out) const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    out = impl_->latest_preview;
    return out.valid();
}

const SensorCapabilities& ReplayCaptureSession::observation_capabilities() const noexcept {
    return impl_->source.capabilities();
}

bool ReplayCaptureSession::latest_observation(SensorObservation& out) const {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (!impl_->have_latest_observation) {
        out = {};
        return false;
    }
    out = impl_->latest_observation;
    return true;
}

bool ReplayCaptureSession::toggle_capture() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->state.capture.state == CaptureState::error) return false;

    if (impl_->desired_running) {
        impl_->desired_running = false;
        impl_->state.capture.state = CaptureState::paused;
        impl_->state.fps = 0.0;
        impl_->state.last_action = "replay paused";
        impl_->schedule_started = false;
    } else {
        if (impl_->at_eof) impl_->reset_requested = true;
        impl_->desired_running = true;
        impl_->state.capture.state = CaptureState::running;
        impl_->state.last_action = impl_->at_eof ? "replay restart requested" : "replay resumed";
        impl_->schedule_started = false;
    }
    impl_->wake.notify_all();
    return true;
}

bool ReplayCaptureSession::cycle_trigger() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.last_action = "trigger control unavailable for replay";
    return false;
}

bool ReplayCaptureSession::reconnect() {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->state.capture.state == CaptureState::error) {
        impl_->state.capture.state = CaptureState::idle;
    }
    impl_->desired_running = true;
    impl_->reset_requested = true;
    impl_->at_eof = false;
    impl_->state.capture.state = CaptureState::running;
    impl_->state.last_action = "replay reset requested";
    impl_->schedule_started = false;
    impl_->wake.notify_all();
    return true;
}

bool ReplayCaptureSession::set_exposure_us(int) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.last_action = "exposure control unavailable for replay";
    return false;
}

bool ReplayCaptureSession::set_gain_x10(int) {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    impl_->state.last_action = "gain control unavailable for replay";
    return false;
}

}  // namespace bividi
