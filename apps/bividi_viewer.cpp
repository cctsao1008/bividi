#include "bividi/session.hpp"

#ifdef BIVIDI_HAVE_REPLAY_SESSION
#include "bividi/replay_session.hpp"
#endif

#ifdef BIVIDI_HAVE_NORI_SESSION
#include "bividi/nori_session.hpp"
#endif

#include <opencv2/core.hpp>
#include <opencv2/highgui.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr char kWindowName[] = "Bividi Viewer";
constexpr int kEyeWidth = 640;
constexpr int kEyeHeight = 360;
constexpr int kPanelHeight = 220;
constexpr int kMaxExposureUs = 20000;
constexpr int kMaxGainX10 = 240;

const char* capture_state_name(bividi::CaptureState state) noexcept {
    switch (state) {
        case bividi::CaptureState::idle: return "IDLE";
        case bividi::CaptureState::running: return "RUNNING";
        case bividi::CaptureState::paused: return "PAUSED";
        case bividi::CaptureState::disconnected: return "DISCONNECTED";
        case bividi::CaptureState::error: return "ERROR";
    }
    return "UNKNOWN";
}

std::uint32_t parse_u32(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoul(value, &used, 10);
        if (value[used] != '\0' || parsed > 0xffffffffUL) {
            throw std::out_of_range("range");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

double parse_positive_double(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stod(value, &used);
        if (value[used] != '\0' || !(parsed > 0.0) || !std::isfinite(parsed)) {
            throw std::out_of_range("range");
        }
        return parsed;
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

void draw_synthetic_eye(
    cv::Mat& image,
    std::uint64_t frame,
    bool camera_b,
    const bividi::SessionStatus& state) {
    image.setTo(cv::Scalar(28, 30, 34));

    const int direction = camera_b ? -1 : 1;
    const int disparity = camera_b ? -24 : 24;
    const int x = static_cast<int>((frame * 5) % (kEyeWidth - 160)) + 80 + disparity;
    const int y = kEyeHeight / 2 + static_cast<int>(55.0 * std::sin(frame * 0.06));

    cv::rectangle(image, cv::Rect(30, 55, kEyeWidth - 60, kEyeHeight - 110), cv::Scalar(70, 72, 78), 2);
    cv::line(image, cv::Point(kEyeWidth / 2, 55), cv::Point(kEyeWidth / 2, kEyeHeight - 55), cv::Scalar(55, 58, 64), 1);
    cv::circle(image, cv::Point(std::clamp(x, 35, kEyeWidth - 35), y), 32, cv::Scalar(210, 210, 210), -1, cv::LINE_AA);
    cv::circle(image, cv::Point(std::clamp(x + direction * 8, 35, kEyeWidth - 35), y), 12, cv::Scalar(45, 45, 48), -1, cv::LINE_AA);

    const double brightness = std::clamp(
        0.35 + state.exposure_us / 22000.0 + state.gain_x10 / 600.0,
        0.35,
        1.35);
    image.convertTo(image, -1, brightness, 0.0);

    cv::putText(
        image,
        camera_b ? "Camera B - synthetic" : "Camera A - synthetic",
        cv::Point(24, 34),
        cv::FONT_HERSHEY_SIMPLEX,
        0.72,
        cv::Scalar(235, 235, 235),
        2,
        cv::LINE_AA);
}

cv::Mat render_live_eye(const bividi::ImageView& view, bool camera_b, bool replay) {
    if (view.empty() || view.pixel_format != bividi::PixelFormat::bgr24 || view.bytes_per_pixel != 3) {
        return {};
    }

    cv::Mat source(
        static_cast<int>(view.height),
        static_cast<int>(view.width),
        CV_8UC3,
        const_cast<std::uint8_t*>(view.data),
        view.row_stride);

    const double scale = std::min(
        static_cast<double>(kEyeWidth) / static_cast<double>(view.width),
        static_cast<double>(kEyeHeight) / static_cast<double>(view.height));
    const int width = std::max(1, static_cast<int>(std::lround(view.width * scale)));
    const int height = std::max(1, static_cast<int>(std::lround(view.height * scale)));

    cv::Mat resized;
    cv::resize(source, resized, cv::Size(width, height), 0.0, 0.0, cv::INTER_AREA);
    cv::Mat canvas(kEyeHeight, kEyeWidth, CV_8UC3, cv::Scalar(16, 18, 20));
    const int x = (kEyeWidth - width) / 2;
    const int y = (kEyeHeight - height) / 2;
    resized.copyTo(canvas(cv::Rect(x, y, width, height)));

    const std::string label = std::string(camera_b ? "Camera B - " : "Camera A - ") +
                              (replay ? "replay" : "live");
    cv::putText(
        canvas,
        label,
        cv::Point(24, 34),
        cv::FONT_HERSHEY_SIMPLEX,
        0.72,
        cv::Scalar(235, 235, 235),
        2,
        cv::LINE_AA);
    return canvas;
}

cv::Mat render_waiting_eye(const bividi::SessionStatus& state, bool camera_b) {
    cv::Mat image(kEyeHeight, kEyeWidth, CV_8UC3, cv::Scalar(22, 24, 28));
    cv::putText(
        image,
        camera_b ? "Camera B - waiting for frame" : "Camera A - waiting for frame",
        cv::Point(34, kEyeHeight / 2 - 8),
        cv::FONT_HERSHEY_SIMPLEX,
        0.62,
        cv::Scalar(220, 220, 220),
        1,
        cv::LINE_AA);
    cv::putText(
        image,
        state.last_action,
        cv::Point(34, kEyeHeight / 2 + 28),
        cv::FONT_HERSHEY_SIMPLEX,
        0.46,
        cv::Scalar(165, 170, 178),
        1,
        cv::LINE_AA);
    return image;
}

void put_status(cv::Mat& panel, int row, const std::string& text, double scale = 0.56) {
    cv::putText(
        panel,
        text,
        cv::Point(22, 30 + row * 27),
        cv::FONT_HERSHEY_SIMPLEX,
        scale,
        cv::Scalar(225, 225, 225),
        1,
        cv::LINE_AA);
}

cv::Mat render(
    const bividi::SessionStatus& state,
    const bividi::StereoPreviewFrame* preview) {
    cv::Mat camera_a;
    cv::Mat camera_b;
    const bool replay = state.source_id.rfind("replay:", 0) == 0;

    if (preview != nullptr && preview->valid()) {
        camera_a = render_live_eye(preview->camera_a, false, replay);
        camera_b = render_live_eye(preview->camera_b, true, replay);
    }

    if (camera_a.empty() || camera_b.empty()) {
        camera_a = cv::Mat(kEyeHeight, kEyeWidth, CV_8UC3);
        camera_b = cv::Mat(kEyeHeight, kEyeWidth, CV_8UC3);
        if (state.source_id == "synthetic") {
            draw_synthetic_eye(camera_a, state.capture.frames, false, state);
            draw_synthetic_eye(camera_b, state.capture.frames, true, state);
        } else {
            camera_a = render_waiting_eye(state, false);
            camera_b = render_waiting_eye(state, true);
        }
    }

    cv::Mat stereo;
    cv::hconcat(camera_a, camera_b, stereo);

    cv::Mat panel(kPanelHeight, stereo.cols, CV_8UC3, cv::Scalar(18, 20, 23));

    std::ostringstream line0;
    line0 << state.source_id << "  |  " << capture_state_name(state.capture.state)
          << "  |  " << state.fps << " FPS"
          << "  |  frame " << state.capture.frames << "  drops " << state.capture.drops
          << "  dup " << state.capture.duplicates << "  ooo " << state.capture.out_of_order;
    put_status(panel, 0, line0.str(), 0.58);

    if (replay) {
        put_status(panel, 1, "Replay source: exposure / gain / trigger controls are unavailable");
    } else {
        std::ostringstream line1;
        line1 << "Exposure: " << state.exposure_us << " us  |  Gain: "
              << state.gain_x10 / 10.0 << "x  |  Trigger: "
              << bividi::trigger_mode_name(state.trigger_mode);
        put_status(panel, 1, line1.str());
    }

    std::ostringstream line2;
    line2 << "ES: " << state.exposure_start_us << " us  |  EE: " << state.exposure_end_us
          << " us  |  IMU: " << state.imu_rate_hz << " Hz";
    put_status(panel, 2, line2.str());

    if (state.decode_queue.capacity != 0) {
        std::ostringstream line3;
        line3 << "Source: " << state.source.frames
              << " frames  drops " << state.source.drops
              << "  dup " << state.source.duplicates
              << "  ooo " << state.source.out_of_order
              << "  |  Queue: " << state.decode_queue.occupancy << '/' << state.decode_queue.capacity
              << "  high " << state.decode_queue.high_watermark
              << "  overflow " << state.decode_queue.overflows
              << "  flushed " << state.decode_queue.flushed_frames;
        put_status(panel, 3, line3.str(), 0.50);
    } else {
        put_status(panel, 3, "Source/decode-queue telemetry unavailable for this session", 0.50);
    }

    put_status(panel, 4, "Keys: SPACE pause/resume   T trigger   C reconnect/reset   S snapshot   Q/ESC quit");
    put_status(panel, 5, replay
        ? "Replay: SPACE pause/resume, C restarts the recorded timeline."
        : "Trackbars: Exposure / Gain   |   Live controls are serialized through CaptureSession.");
    put_status(panel, 6, "Last: " + state.last_action, 0.50);

    cv::Mat canvas;
    cv::vconcat(stereo, panel, canvas);
    return canvas;
}

std::unique_ptr<bividi::CaptureSession> make_session(
    const std::string& source,
    std::uint32_t device,
    std::uint32_t mode,
    std::uint32_t timeout_ms,
    const std::string& replay_session,
    double replay_rate) {
    if (source == "synthetic") {
        return std::make_unique<bividi::SyntheticCaptureSession>();
    }
    if (source == "replay") {
#ifdef BIVIDI_HAVE_REPLAY_SESSION
        if (replay_session.empty()) {
            throw std::runtime_error("replay source requires --session PATH");
        }
        bividi::ReplaySessionConfig config{};
        config.session_dir = replay_session;
        config.rate = replay_rate;
        return std::make_unique<bividi::ReplayCaptureSession>(std::move(config));
#else
        throw std::runtime_error("Replay source was requested but this build does not include native replay support");
#endif
    }
    if (source == "nori") {
#ifdef BIVIDI_HAVE_NORI_SESSION
        bividi::nori::NoriSessionConfig config{};
        config.stream.device_index = device;
        config.stream.mode_index = mode;
        config.stream.timeout_ms = timeout_ms;
        return std::make_unique<bividi::nori::NoriCaptureSession>(config);
#else
        throw std::runtime_error("Nori source was requested but this build does not include the Nori SDK session backend");
#endif
    }
    throw std::runtime_error("unknown viewer source: " + source);
}

int self_test() {
    bividi::SessionStatus state;
    state.capture.state = bividi::CaptureState::running;
    state.capture.frames = 42;
    state.source.frames = 43;
    state.decode_queue.capacity = 256;
    state.decode_queue.occupancy = 1;
    state.decode_queue.high_watermark = 7;
    state.exposure_us = 7500;
    state.gain_x10 = 10;
    state.exposure_start_us = 700000;
    state.exposure_end_us = state.exposure_start_us + static_cast<std::uint64_t>(state.exposure_us);
    state.fps = 60.0;
    state.nominal_fps = 60.0;
    state.imu_rate_hz = 600;
    state.source_id = "synthetic";
    state.last_action = "self-test";

    const auto frame = render(state, nullptr);
    if (frame.empty() || frame.cols != kEyeWidth * 2 || frame.rows != kEyeHeight + kPanelHeight) {
        std::cerr << "bividi-viewer self-test: invalid rendered geometry\n";
        return 1;
    }

    std::vector<unsigned char> encoded;
    if (!cv::imencode(".png", frame, encoded) || encoded.empty()) {
        std::cerr << "bividi-viewer self-test: PNG encode failed\n";
        return 2;
    }

    std::cout << "bividi-viewer self-test: PASS\n";
    std::cout << "geometry=" << frame.cols << "x" << frame.rows << " png_bytes=" << encoded.size() << "\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::string source = "synthetic";
    std::uint32_t device = 0;
    std::uint32_t mode = 0;
    std::uint32_t timeout_ms = 2000;
    std::string replay_session;
    double replay_rate = 1.0;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--self-test") return self_test();
        if (arg == "--help") {
            std::cout << "bividi-viewer [--source synthetic|replay|nori] [--session PATH] [--replay-rate X] [--device N] [--mode N] [--timeout-ms N] [--self-test]\n"
                      << "SPACE pause/resume, T trigger mode, C reconnect/reset, S snapshot, Q/ESC quit\n";
            return 0;
        }
        if (arg == "--source" && i + 1 < argc) {
            source = argv[++i];
        } else if (arg == "--session" && i + 1 < argc) {
            replay_session = argv[++i];
        } else if (arg == "--replay-rate" && i + 1 < argc) {
            replay_rate = parse_positive_double(argv[++i], "replay rate");
        } else if (arg == "--device" && i + 1 < argc) {
            device = parse_u32(argv[++i], "device index");
        } else if (arg == "--mode" && i + 1 < argc) {
            mode = parse_u32(argv[++i], "mode index");
        } else if (arg == "--timeout-ms" && i + 1 < argc) {
            timeout_ms = parse_u32(argv[++i], "timeout");
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            return 2;
        }
    }

    std::unique_ptr<bividi::CaptureSession> session;
    try {
        session = make_session(source, device, mode, timeout_ms, replay_session, replay_rate);
    } catch (const std::exception& error) {
        std::cerr << "bividi-viewer: " << error.what() << '\n';
        return 3;
    }

    auto initial = session->snapshot();
    int exposure_trackbar = initial.exposure_us > 0 ? initial.exposure_us : 1;
    int gain_trackbar = std::max(0, initial.gain_x10);
    int last_exposure_request = exposure_trackbar;
    int last_gain_request = gain_trackbar;
    bool controls_synced = source == "synthetic";

    cv::namedWindow(kWindowName, cv::WINDOW_NORMAL);
    cv::resizeWindow(kWindowName, kEyeWidth * 2, kEyeHeight + kPanelHeight + 80);
    cv::createTrackbar("Exposure us", kWindowName, &exposure_trackbar, kMaxExposureUs);
    cv::createTrackbar("Gain x0.1", kWindowName, &gain_trackbar, kMaxGainX10);

    cv::Mat last_canvas;

    while (true) {
        auto state = session->snapshot();

        if (!controls_synced && source != "replay" && state.exposure_us > 0) {
            exposure_trackbar = std::clamp(state.exposure_us, 1, kMaxExposureUs);
            gain_trackbar = std::clamp(state.gain_x10, 0, kMaxGainX10);
            cv::setTrackbarPos("Exposure us", kWindowName, exposure_trackbar);
            cv::setTrackbarPos("Gain x0.1", kWindowName, gain_trackbar);
            last_exposure_request = exposure_trackbar;
            last_gain_request = gain_trackbar;
            controls_synced = true;
        }

        if (controls_synced) {
            int requested_exposure = cv::getTrackbarPos("Exposure us", kWindowName);
            if (requested_exposure < 1) {
                requested_exposure = 1;
                cv::setTrackbarPos("Exposure us", kWindowName, requested_exposure);
            }
            if (requested_exposure != last_exposure_request &&
                session->set_exposure_us(requested_exposure)) {
                last_exposure_request = requested_exposure;
            }

            const int requested_gain = cv::getTrackbarPos("Gain x0.1", kWindowName);
            if (requested_gain != last_gain_request && session->set_gain_x10(requested_gain)) {
                last_gain_request = requested_gain;
            }
        }

        state = session->snapshot();
        bividi::StereoPreviewFrame preview;
        const bool have_preview = session->latest_stereo_preview(preview);
        last_canvas = render(state, have_preview ? &preview : nullptr);
        cv::imshow(kWindowName, last_canvas);

        const int key = cv::waitKey(16) & 0xff;
        if (key == 27 || key == 'q' || key == 'Q') {
            break;
        }
        if (key == ' ') {
            session->toggle_capture();
        } else if (key == 't' || key == 'T') {
            session->cycle_trigger();
        } else if (key == 'c' || key == 'C') {
            controls_synced = source == "synthetic";
            session->reconnect();
        } else if (key == 's' || key == 'S') {
            const auto snapshot = session->snapshot();
            const auto filename = std::string("bividi_snapshot_") +
                                  std::to_string(snapshot.capture.frames) + ".png";
            if (!cv::imwrite(filename, last_canvas)) {
                std::cerr << "bividi-viewer: snapshot failed: " << filename << "\n";
            } else {
                std::cout << "bividi-viewer: snapshot -> " << filename << "\n";
            }
        }
    }

    cv::destroyAllWindows();
    return 0;
}
