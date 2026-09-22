#pragma once

#ifdef BIVIDI_HAVE_DEPTH

#include "bividi/session.hpp"

#include <opencv2/calib3d.hpp>
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace bividi_web {

struct QuickDepthResult {
    bool available = false;
    std::uint64_t revision = 0;
    std::uint64_t source_sequence = 0;
    double valid_fraction = 0.0;
    double processing_ms = 0.0;
    cv::Mat disparity_preview;
    cv::Mat proximity_preview;
    std::string error;
};

inline cv::Mat quick_depth_gray_view(const bividi::ImageView& view, int width, int height) {
    if (view.empty() || view.pixel_format != bividi::PixelFormat::bgr24 || view.bytes_per_pixel != 3) {
        return {};
    }

    cv::Mat source(
        static_cast<int>(view.height),
        static_cast<int>(view.width),
        CV_8UC3,
        const_cast<std::uint8_t*>(view.data),
        view.row_stride);

    cv::Mat resized;
    cv::resize(source, resized, cv::Size(width, height), 0.0, 0.0, cv::INTER_AREA);

    cv::Mat gray;
    cv::cvtColor(resized, gray, cv::COLOR_BGR2GRAY);
    return gray;
}

inline QuickDepthResult compute_quick_depth_pair(
    const cv::Mat& left_gray,
    const cv::Mat& right_gray,
    std::uint64_t sequence,
    int num_disparities = 160) {
    QuickDepthResult out;
    out.source_sequence = sequence;

    if (left_gray.empty() || right_gray.empty() ||
        left_gray.type() != CV_8UC1 || right_gray.type() != CV_8UC1 ||
        left_gray.size() != right_gray.size()) {
        out.error = "quick-depth input must be equal-size 8-bit grayscale images";
        return out;
    }

    num_disparities = std::max(16, ((num_disparities + 15) / 16) * 16);
    if (num_disparities >= left_gray.cols) {
        num_disparities = std::max(16, ((left_gray.cols / 2) / 16) * 16);
    }
    if (num_disparities < 16) {
        out.error = "quick-depth image is too narrow for StereoSGBM";
        return out;
    }

    constexpr int block_size = 5;
    auto matcher = cv::StereoSGBM::create(
        0,
        num_disparities,
        block_size,
        8 * block_size * block_size,
        32 * block_size * block_size,
        1,
        31,
        8,
        80,
        2,
        cv::StereoSGBM::MODE_SGBM_3WAY);

    cv::Mat disparity16;
    matcher->compute(left_gray, right_gray, disparity16);

    cv::Mat disparity;
    disparity16.convertTo(disparity, CV_32F, 1.0 / 16.0);
    const cv::Mat valid = disparity > 1.0f;
    out.valid_fraction = static_cast<double>(cv::countNonZero(valid)) /
                         static_cast<double>(valid.total());

    cv::Mat disparity8(disparity.size(), CV_8UC1, cv::Scalar(0));
    cv::Mat scaled;
    disparity.convertTo(scaled, CV_32F, 255.0 / static_cast<double>(num_disparities));
    cv::min(scaled, 255.0, scaled);
    cv::max(scaled, 0.0, scaled);
    scaled.convertTo(disparity8, CV_8UC1);
    disparity8.setTo(0, ~valid);

    cv::Mat disparity_color;
    cv::applyColorMap(disparity8, disparity_color, cv::COLORMAP_TURBO);
    disparity_color.setTo(cv::Scalar(0, 0, 0), ~valid);

    // This is deliberately a relative near/far visualization, not metric depth.
    // Larger disparity means closer structure, so the same fixed-scale disparity
    // drives a proximity heatmap without inventing focal length or baseline.
    cv::Mat proximity_color;
    cv::applyColorMap(disparity8, proximity_color, cv::COLORMAP_JET);
    proximity_color.setTo(cv::Scalar(0, 0, 0), ~valid);

    out.disparity_preview = std::move(disparity_color);
    out.proximity_preview = std::move(proximity_color);
    out.available = true;
    return out;
}

class QuickDepthPreviewService {
public:
    explicit QuickDepthPreviewService(
        bividi::CaptureSession& session,
        int width = 640,
        int height = 400,
        int target_fps = 10,
        int num_disparities = 160)
        : session_(session),
          width_(width),
          height_(height),
          target_fps_(std::max(1, target_fps)),
          num_disparities_(num_disparities),
          worker_([this] { run(); }) {}

    ~QuickDepthPreviewService() {
        stop_.store(true);
        if (worker_.joinable()) worker_.join();
    }

    QuickDepthPreviewService(const QuickDepthPreviewService&) = delete;
    QuickDepthPreviewService& operator=(const QuickDepthPreviewService&) = delete;

    void reset() {
        std::lock_guard<std::mutex> lock(mutex_);
        last_source_sequence_ = 0;
        result_ = {};
    }

    std::string status_json() const {
        const auto snapshot = latest();
        std::ostringstream out;
        out << "{\"enabled\":true,"
            << "\"mode\":\"quick_uncalibrated\","
            << "\"available\":" << (snapshot.available ? "true" : "false") << ','
            << "\"revision\":" << snapshot.revision << ','
            << "\"sequence\":" << snapshot.source_sequence << ','
            << "\"valid_fraction\":" << snapshot.valid_fraction << ','
            << "\"processing_ms\":" << snapshot.processing_ms << ','
            << "\"width\":" << width_ << ','
            << "\"height\":" << height_ << ','
            << "\"target_fps\":" << target_fps_ << ','
            << "\"left_camera\":\"camera_b\","
            << "\"right_camera\":\"camera_a\","
            << "\"metric\":false,"
            << "\"rectified\":false,"
            << "\"error\":\"" << json_escape(snapshot.error) << "\"}";
        return out.str();
    }

    std::vector<unsigned char> image_jpeg(bool proximity) const {
        const auto snapshot = latest();
        if (!snapshot.available) {
            return placeholder_jpeg(
                proximity ? "Relative near/far preview" : "Uncalibrated disparity preview",
                snapshot.error.empty() ? "waiting for paired live stereo preview" : snapshot.error);
        }
        return encode_jpeg(proximity ? snapshot.proximity_preview : snapshot.disparity_preview);
    }

private:
    static std::string json_escape(const std::string& value) {
        std::ostringstream out;
        for (const char ch : value) {
            switch (ch) {
                case '\\': out << "\\\\"; break;
                case '"': out << "\\\""; break;
                case '\n': out << "\\n"; break;
                case '\r': out << "\\r"; break;
                case '\t': out << "\\t"; break;
                default: out << ch; break;
            }
        }
        return out.str();
    }

    QuickDepthResult latest() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return result_;
    }

    static std::vector<unsigned char> encode_jpeg(const cv::Mat& image) {
        std::vector<unsigned char> encoded;
        if (image.empty()) return encoded;
        const std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, 86};
        cv::imencode(".jpg", image, encoded, params);
        return encoded;
    }

    static std::vector<unsigned char> placeholder_jpeg(
        const std::string& title,
        const std::string& detail) {
        cv::Mat canvas(400, 640, CV_8UC3, cv::Scalar(20, 23, 27));
        cv::putText(canvas, title, cv::Point(28, 176), cv::FONT_HERSHEY_SIMPLEX,
                    0.68, cv::Scalar(222, 226, 231), 2, cv::LINE_AA);
        std::string clipped = detail;
        if (clipped.size() > 78) clipped.resize(78);
        cv::putText(canvas, clipped, cv::Point(28, 214), cv::FONT_HERSHEY_SIMPLEX,
                    0.44, cv::Scalar(154, 163, 174), 1, cv::LINE_AA);
        return encode_jpeg(canvas);
    }

    void publish(QuickDepthResult next) {
        std::lock_guard<std::mutex> lock(mutex_);
        next.revision = result_.revision + 1;
        result_ = std::move(next);
    }

    void run() {
        const auto period = std::chrono::milliseconds(std::max(1, 1000 / target_fps_));
        while (!stop_.load()) {
            const auto started = std::chrono::steady_clock::now();
            bividi::StereoPreviewFrame preview;
            if (session_.latest_stereo_preview(preview) && preview.valid()) {
                bool is_new = false;
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    is_new = preview.sequence != last_source_sequence_;
                    if (is_new) last_source_sequence_ = preview.sequence;
                }

                if (is_new) {
                    QuickDepthResult next;
                    try {
                        // Physical mapping measured on the delivered rig:
                        // front-view left lens -> camera_a, front-view right lens -> camera_b.
                        // In the rig-forward convention this makes camera_b the stereo-left eye.
                        const auto left = quick_depth_gray_view(preview.camera_b, width_, height_);
                        const auto right = quick_depth_gray_view(preview.camera_a, width_, height_);
                        next = compute_quick_depth_pair(left, right, preview.sequence, num_disparities_);
                    } catch (const cv::Exception& error) {
                        next.source_sequence = preview.sequence;
                        next.error = error.what();
                    } catch (const std::exception& error) {
                        next.source_sequence = preview.sequence;
                        next.error = error.what();
                    }
                    const auto finished = std::chrono::steady_clock::now();
                    next.processing_ms = std::chrono::duration<double, std::milli>(finished - started).count();
                    publish(std::move(next));
                }
            }

            const auto elapsed = std::chrono::steady_clock::now() - started;
            if (elapsed < period) std::this_thread::sleep_for(period - elapsed);
        }
    }

    bividi::CaptureSession& session_;
    int width_ = 640;
    int height_ = 400;
    int target_fps_ = 10;
    int num_disparities_ = 160;
    mutable std::mutex mutex_;
    QuickDepthResult result_{};
    std::uint64_t last_source_sequence_ = 0;
    std::atomic<bool> stop_{false};
    std::thread worker_;
};

inline bool quick_depth_self_test() {
    constexpr int width = 320;
    constexpr int height = 200;
    constexpr int disparity_px = 24;

    cv::Mat left(height, width, CV_8UC1);
    cv::RNG rng(0xB1D1D1u);
    rng.fill(left, cv::RNG::UNIFORM, 0, 255);

    cv::Mat right(height, width, CV_8UC1, cv::Scalar(0));
    left(cv::Rect(disparity_px, 0, width - disparity_px, height))
        .copyTo(right(cv::Rect(0, 0, width - disparity_px, height)));

    const auto result = compute_quick_depth_pair(left, right, 7, 96);
    return result.available &&
           result.source_sequence == 7 &&
           result.valid_fraction > 0.40 &&
           !result.disparity_preview.empty() &&
           !result.proximity_preview.empty();
}

}  // namespace bividi_web

#endif  // BIVIDI_HAVE_DEPTH
