#include <opencv2/core.hpp>
#include <opencv2/highgui.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

constexpr char kWindowName[] = "Bividi Viewer";
constexpr int kEyeWidth = 640;
constexpr int kEyeHeight = 360;
constexpr int kPanelHeight = 190;
constexpr int kMaxExposureUs = 20000;
constexpr int kMaxGainX10 = 240;

struct ViewerState {
    bool running = true;
    std::uint64_t frame_count = 0;
    std::uint64_t drop_count = 0;
    int exposure_us = 7500;
    int gain_x10 = 10;
    int trigger_mode = 0;
    double fps = 0.0;
    std::uint64_t exposure_start_us = 0;
    std::uint64_t exposure_end_us = 0;
    std::string last_action = "synthetic source ready";
};

const char* trigger_name(int mode) {
    switch (mode % 4) {
        case 0: return "Free Run";
        case 1: return "Software";
        case 2: return "Hardware";
        default: return "Command";
    }
}

void draw_eye(cv::Mat& image, std::uint64_t frame, bool camera_b, const ViewerState& state) {
    image.setTo(cv::Scalar(28, 30, 34));

    const int direction = camera_b ? -1 : 1;
    const int disparity = camera_b ? -24 : 24;
    const int x = static_cast<int>((frame * 5) % (kEyeWidth - 160)) + 80 + disparity;
    const int y = kEyeHeight / 2 + static_cast<int>(55.0 * std::sin(frame * 0.06));

    cv::rectangle(image, cv::Rect(30, 55, kEyeWidth - 60, kEyeHeight - 110), cv::Scalar(70, 72, 78), 2);
    cv::line(image, cv::Point(kEyeWidth / 2, 55), cv::Point(kEyeWidth / 2, kEyeHeight - 55), cv::Scalar(55, 58, 64), 1);
    cv::circle(image, cv::Point(std::clamp(x, 35, kEyeWidth - 35), y), 32, cv::Scalar(210, 210, 210), -1, cv::LINE_AA);
    cv::circle(image, cv::Point(std::clamp(x + direction * 8, 35, kEyeWidth - 35), y), 12, cv::Scalar(45, 45, 48), -1, cv::LINE_AA);

    const double brightness = std::clamp(0.35 + state.exposure_us / 22000.0 + state.gain_x10 / 600.0, 0.35, 1.35);
    image.convertTo(image, -1, brightness, 0.0);

    cv::putText(
        image,
        camera_b ? "Camera B — synthetic" : "Camera A — synthetic",
        cv::Point(24, 34),
        cv::FONT_HERSHEY_SIMPLEX,
        0.72,
        cv::Scalar(235, 235, 235),
        2,
        cv::LINE_AA);
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

cv::Mat render(const ViewerState& state) {
    cv::Mat camera_a(kEyeHeight, kEyeWidth, CV_8UC3);
    cv::Mat camera_b(kEyeHeight, kEyeWidth, CV_8UC3);
    draw_eye(camera_a, state.frame_count, false, state);
    draw_eye(camera_b, state.frame_count, true, state);

    cv::Mat stereo;
    cv::hconcat(camera_a, camera_b, stereo);

    cv::Mat panel(kPanelHeight, stereo.cols, CV_8UC3, cv::Scalar(18, 20, 23));

    std::ostringstream line0;
    line0 << "SYNTHETIC SOURCE  |  " << (state.running ? "RUNNING" : "PAUSED")
          << "  |  " << state.fps << " FPS"
          << "  |  frame " << state.frame_count << "  drops " << state.drop_count;
    put_status(panel, 0, line0.str(), 0.62);

    std::ostringstream line1;
    line1 << "Exposure: " << state.exposure_us << " us  |  Gain: "
          << state.gain_x10 / 10.0 << "x  |  Trigger: " << trigger_name(state.trigger_mode);
    put_status(panel, 1, line1.str());

    std::ostringstream line2;
    line2 << "ES: " << state.exposure_start_us << " us  |  EE: " << state.exposure_end_us
          << " us  |  IMU: simulated 600 Hz";
    put_status(panel, 2, line2.str());

    put_status(panel, 3, "Keys: SPACE pause/resume   T trigger   C reconnect/reset   S snapshot   Q/ESC quit");
    put_status(panel, 4, "Trackbars: Exposure / Gain   |   Hardware controls will bind through the backend/control boundary.");
    put_status(panel, 5, "Last: " + state.last_action, 0.50);

    cv::Mat canvas;
    cv::vconcat(stereo, panel, canvas);
    return canvas;
}

void reset_session(ViewerState& state) {
    state.frame_count = 0;
    state.drop_count = 0;
    state.exposure_start_us = 0;
    state.exposure_end_us = 0;
    state.last_action = "synthetic reconnect/reset";
}

int self_test() {
    ViewerState state;
    state.frame_count = 42;
    state.exposure_start_us = 700000;
    state.exposure_end_us = state.exposure_start_us + static_cast<std::uint64_t>(state.exposure_us);
    state.fps = 60.0;

    const auto frame = render(state);
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
    if (argc > 1 && std::string(argv[1]) == "--self-test") {
        return self_test();
    }
    if (argc > 1 && std::string(argv[1]) == "--help") {
        std::cout << "bividi-viewer [--self-test]\n"
                  << "SPACE pause/resume, T trigger mode, C reconnect/reset, S snapshot, Q/ESC quit\n";
        return 0;
    }

    ViewerState state;
    cv::namedWindow(kWindowName, cv::WINDOW_NORMAL);
    cv::resizeWindow(kWindowName, kEyeWidth * 2, kEyeHeight + kPanelHeight + 80);
    cv::createTrackbar("Exposure us", kWindowName, &state.exposure_us, kMaxExposureUs);
    cv::createTrackbar("Gain x0.1", kWindowName, &state.gain_x10, kMaxGainX10);

    auto fps_window_start = std::chrono::steady_clock::now();
    std::uint64_t fps_window_frames = 0;
    cv::Mat last_canvas;

    while (true) {
        if (state.running) {
            ++state.frame_count;
            ++fps_window_frames;
            constexpr std::uint64_t frame_period_us = 16667;
            state.exposure_start_us = state.frame_count * frame_period_us;
            state.exposure_end_us = state.exposure_start_us + static_cast<std::uint64_t>(state.exposure_us);
        }

        const auto now = std::chrono::steady_clock::now();
        const auto elapsed = std::chrono::duration<double>(now - fps_window_start).count();
        if (elapsed >= 0.5) {
            state.fps = state.running ? fps_window_frames / elapsed : 0.0;
            fps_window_frames = 0;
            fps_window_start = now;
        }

        last_canvas = render(state);
        cv::imshow(kWindowName, last_canvas);

        const int key = cv::waitKey(16) & 0xff;
        if (key == 27 || key == 'q' || key == 'Q') {
            break;
        }
        if (key == ' ') {
            state.running = !state.running;
            state.last_action = state.running ? "capture resumed" : "capture paused";
        } else if (key == 't' || key == 'T') {
            state.trigger_mode = (state.trigger_mode + 1) % 4;
            state.last_action = std::string("trigger mode -> ") + trigger_name(state.trigger_mode);
        } else if (key == 'c' || key == 'C') {
            reset_session(state);
        } else if (key == 's' || key == 'S') {
            const auto filename = std::string("bividi_snapshot_") + std::to_string(state.frame_count) + ".png";
            if (cv::imwrite(filename, last_canvas)) {
                state.last_action = "snapshot -> " + filename;
            } else {
                state.last_action = "snapshot failed";
            }
        }
    }

    cv::destroyAllWindows();
    return 0;
}
