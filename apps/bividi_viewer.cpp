#include "bividi/session.hpp"

#include <opencv2/core.hpp>
#include <opencv2/highgui.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
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

void draw_eye(
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

cv::Mat render(const bividi::SessionStatus& state) {
    cv::Mat camera_a(kEyeHeight, kEyeWidth, CV_8UC3);
    cv::Mat camera_b(kEyeHeight, kEyeWidth, CV_8UC3);
    draw_eye(camera_a, state.capture.frames, false, state);
    draw_eye(camera_b, state.capture.frames, true, state);

    cv::Mat stereo;
    cv::hconcat(camera_a, camera_b, stereo);

    cv::Mat panel(kPanelHeight, stereo.cols, CV_8UC3, cv::Scalar(18, 20, 23));

    std::ostringstream line0;
    line0 << state.source_id << " SOURCE  |  " << (state.running() ? "RUNNING" : "PAUSED")
          << "  |  " << state.fps << " FPS"
          << "  |  frame " << state.capture.frames << "  drops " << state.capture.drops;
    put_status(panel, 0, line0.str(), 0.62);

    std::ostringstream line1;
    line1 << "Exposure: " << state.exposure_us << " us  |  Gain: "
          << state.gain_x10 / 10.0 << "x  |  Trigger: "
          << bividi::trigger_mode_name(state.trigger_mode);
    put_status(panel, 1, line1.str());

    std::ostringstream line2;
    line2 << "ES: " << state.exposure_start_us << " us  |  EE: " << state.exposure_end_us
          << " us  |  IMU: simulated " << state.imu_rate_hz << " Hz";
    put_status(panel, 2, line2.str());

    put_status(panel, 3, "Keys: SPACE pause/resume   T trigger   C reconnect/reset   S snapshot   Q/ESC quit");
    put_status(panel, 4, "Trackbars: Exposure / Gain   |   Controls flow through the shared CaptureSession boundary.");
    put_status(panel, 5, "Last: " + state.last_action, 0.50);

    cv::Mat canvas;
    cv::vconcat(stereo, panel, canvas);
    return canvas;
}

int self_test() {
    bividi::SessionStatus state;
    state.capture.state = bividi::CaptureState::running;
    state.capture.frames = 42;
    state.exposure_us = 7500;
    state.gain_x10 = 10;
    state.exposure_start_us = 700000;
    state.exposure_end_us = state.exposure_start_us + static_cast<std::uint64_t>(state.exposure_us);
    state.fps = 60.0;
    state.nominal_fps = 60.0;
    state.imu_rate_hz = 600;
    state.source_id = "synthetic";
    state.last_action = "self-test";

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

    bividi::SyntheticCaptureSession session;
    auto initial = session.snapshot();
    int exposure_trackbar = initial.exposure_us;
    int gain_trackbar = initial.gain_x10;

    cv::namedWindow(kWindowName, cv::WINDOW_NORMAL);
    cv::resizeWindow(kWindowName, kEyeWidth * 2, kEyeHeight + kPanelHeight + 80);
    cv::createTrackbar("Exposure us", kWindowName, &exposure_trackbar, kMaxExposureUs);
    cv::createTrackbar("Gain x0.1", kWindowName, &gain_trackbar, kMaxGainX10);

    cv::Mat last_canvas;

    while (true) {
        auto state = session.snapshot();

        int requested_exposure = cv::getTrackbarPos("Exposure us", kWindowName);
        if (requested_exposure < 1) {
            requested_exposure = 1;
            cv::setTrackbarPos("Exposure us", kWindowName, requested_exposure);
        }
        if (requested_exposure != state.exposure_us) {
            session.set_exposure_us(requested_exposure);
        }

        const int requested_gain = cv::getTrackbarPos("Gain x0.1", kWindowName);
        if (requested_gain != state.gain_x10) {
            session.set_gain_x10(requested_gain);
        }

        state = session.snapshot();
        last_canvas = render(state);
        cv::imshow(kWindowName, last_canvas);

        const int key = cv::waitKey(16) & 0xff;
        if (key == 27 || key == 'q' || key == 'Q') {
            break;
        }
        if (key == ' ') {
            session.toggle_capture();
        } else if (key == 't' || key == 'T') {
            session.cycle_trigger();
        } else if (key == 'c' || key == 'C') {
            session.reconnect();
        } else if (key == 's' || key == 'S') {
            const auto snapshot = session.snapshot();
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
