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

struct QuickDisparityPreview {
    bool available = false;
    double valid_fraction = 0.0;
    cv::Mat disparity_preview;
    cv::Mat proximity_preview;
    std::string error;
};

struct QuickRectificationEstimate {
    bool accepted = false;
    int matches = 0;
    int inliers = 0;
    double median_vertical_before_px = 0.0;
    double median_vertical_after_px = 0.0;
    cv::Mat left_h;
    cv::Mat right_h;
    std::string reason;
};

struct QuickRectificationState {
    bool ready = false;
    std::uint64_t attempts = 0;
    int matches = 0;
    int inliers = 0;
    double median_vertical_before_px = 0.0;
    double median_vertical_after_px = 0.0;
    cv::Mat left_h;
    cv::Mat right_h;
    std::string reason = "searching for a stable epipolar transform";
};

struct QuickDepthResult {
    bool available = false;
    bool rectified = false;
    std::uint64_t revision = 0;
    std::uint64_t source_sequence = 0;
    double raw_valid_fraction = 0.0;
    double valid_fraction = 0.0;
    double processing_ms = 0.0;
    std::uint64_t rectification_attempts = 0;
    int rectification_matches = 0;
    int rectification_inliers = 0;
    double median_vertical_before_px = 0.0;
    double median_vertical_after_px = 0.0;
    cv::Mat raw_disparity_preview;
    cv::Mat disparity_preview;
    cv::Mat proximity_preview;
    std::string rectification_reason;
    std::string error;
};

struct QuickPatchMatch {
    cv::Point2f left;
    cv::Point2f right;
    double score = 0.0;
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

inline QuickDisparityPreview compute_quick_disparity(
    const cv::Mat& left_gray,
    const cv::Mat& right_gray,
    int num_disparities = 160) {
    QuickDisparityPreview out;

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

    cv::applyColorMap(disparity8, out.disparity_preview, cv::COLORMAP_TURBO);
    out.disparity_preview.setTo(cv::Scalar(0, 0, 0), ~valid);

    // Deliberately relative only: larger disparity is rendered as closer
    // structure without inventing focal length, baseline, or metric scale.
    cv::applyColorMap(disparity8, out.proximity_preview, cv::COLORMAP_JET);
    out.proximity_preview.setTo(cv::Scalar(0, 0, 0), ~valid);

    out.available = true;
    return out;
}

inline double median_vertical_error(
    const std::vector<cv::Point2f>& left,
    const std::vector<cv::Point2f>& right) {
    if (left.empty() || left.size() != right.size()) return 0.0;
    std::vector<double> errors;
    errors.reserve(left.size());
    for (std::size_t i = 0; i < left.size(); ++i) {
        errors.push_back(std::abs(static_cast<double>(left[i].y - right[i].y)));
    }
    const auto middle = errors.begin() + static_cast<std::ptrdiff_t>(errors.size() / 2);
    std::nth_element(errors.begin(), middle, errors.end());
    return *middle;
}

inline bool quick_rectification_homography_sane(const cv::Mat& h, const cv::Size size) {
    if (h.empty() || h.rows != 3 || h.cols != 3) return false;
    const double determinant = cv::determinant(h);
    if (!std::isfinite(determinant) || std::abs(determinant) < 1e-9) return false;

    std::vector<cv::Point2f> corners{
        {0.0f, 0.0f},
        {static_cast<float>(size.width - 1), 0.0f},
        {static_cast<float>(size.width - 1), static_cast<float>(size.height - 1)},
        {0.0f, static_cast<float>(size.height - 1)},
    };
    std::vector<cv::Point2f> warped;
    cv::perspectiveTransform(corners, warped, h);
    if (warped.size() != corners.size()) return false;

    for (const auto& point : warped) {
        if (!std::isfinite(point.x) || !std::isfinite(point.y)) return false;
        if (point.x < -2.0f * size.width || point.x > 3.0f * size.width ||
            point.y < -2.0f * size.height || point.y > 3.0f * size.height) {
            return false;
        }
    }
    return true;
}

inline std::vector<QuickPatchMatch> quick_patch_matches(
    const cv::Mat& left_gray,
    const cv::Mat& right_gray) {
    cv::Mat left_features;
    cv::Mat right_features;
    auto clahe = cv::createCLAHE(2.0, cv::Size(8, 8));
    clahe->apply(left_gray, left_features);
    clahe->apply(right_gray, right_features);

    std::vector<cv::Point2f> corners;
    cv::goodFeaturesToTrack(left_features, corners, 360, 0.01, 8.0, cv::noArray(), 5);

    constexpr int radius = 5;
    constexpr int vertical_search = 40;
    constexpr int disparity_back = 240;
    constexpr int disparity_forward = 40;
    std::vector<QuickPatchMatch> matches;
    matches.reserve(corners.size());

    for (const auto& point : corners) {
        const int lx = static_cast<int>(std::lround(point.x));
        const int ly = static_cast<int>(std::lround(point.y));
        if (lx - radius < 0 || lx + radius >= left_features.cols ||
            ly - radius < 0 || ly + radius >= left_features.rows) {
            continue;
        }

        const cv::Rect patch_rect(lx - radius, ly - radius, radius * 2 + 1, radius * 2 + 1);
        const cv::Mat patch = left_features(patch_rect);

        const int center_x_min = std::max(radius, lx - disparity_back);
        const int center_x_max = std::min(right_features.cols - radius - 1, lx + disparity_forward);
        const int center_y_min = std::max(radius, ly - vertical_search);
        const int center_y_max = std::min(right_features.rows - radius - 1, ly + vertical_search);
        if (center_x_min > center_x_max || center_y_min > center_y_max) continue;

        const cv::Rect search_rect(
            center_x_min - radius,
            center_y_min - radius,
            center_x_max - center_x_min + radius * 2 + 1,
            center_y_max - center_y_min + radius * 2 + 1);
        const cv::Mat search = right_features(search_rect);
        cv::Mat correlation;
        cv::matchTemplate(search, patch, correlation, cv::TM_CCOEFF_NORMED);
        double min_value = 0.0;
        double max_value = 0.0;
        cv::Point min_location;
        cv::Point max_location;
        cv::minMaxLoc(correlation, &min_value, &max_value, &min_location, &max_location);
        if (!std::isfinite(max_value) || max_value < 0.82) continue;

        const cv::Point2f right_point(
            static_cast<float>(search_rect.x + max_location.x + radius),
            static_cast<float>(search_rect.y + max_location.y + radius));
        matches.push_back({point, right_point, max_value});
    }

    std::sort(matches.begin(), matches.end(), [](const QuickPatchMatch& a, const QuickPatchMatch& b) {
        return a.score > b.score;
    });
    if (matches.size() > 220) matches.resize(220);
    return matches;
}

inline QuickRectificationEstimate estimate_quick_rectification(
    const cv::Mat& left_gray,
    const cv::Mat& right_gray) {
    QuickRectificationEstimate out;
    if (left_gray.empty() || right_gray.empty() ||
        left_gray.type() != CV_8UC1 || right_gray.type() != CV_8UC1 ||
        left_gray.size() != right_gray.size()) {
        out.reason = "rectification requires equal-size grayscale images";
        return out;
    }

    const auto matches = quick_patch_matches(left_gray, right_gray);
    out.matches = static_cast<int>(matches.size());
    if (out.matches < 40) {
        out.reason = "fewer than 40 high-correlation stereo patch matches";
        return out;
    }

    std::vector<cv::Point2f> left_points;
    std::vector<cv::Point2f> right_points;
    left_points.reserve(matches.size());
    right_points.reserve(matches.size());
    for (const auto& match : matches) {
        left_points.push_back(match.left);
        right_points.push_back(match.right);
    }

    cv::Mat inlier_mask;
    const cv::Mat fundamental = cv::findFundamentalMat(
        left_points,
        right_points,
        cv::FM_RANSAC,
        1.5,
        0.995,
        inlier_mask);
    if (fundamental.empty() || inlier_mask.empty()) {
        out.reason = "RANSAC fundamental-matrix estimation failed";
        return out;
    }

    std::vector<cv::Point2f> left_inliers;
    std::vector<cv::Point2f> right_inliers;
    const int mask_count = static_cast<int>(inlier_mask.total());
    for (int i = 0; i < mask_count; ++i) {
        if (inlier_mask.ptr<unsigned char>()[i] == 0) continue;
        left_inliers.push_back(left_points[static_cast<std::size_t>(i)]);
        right_inliers.push_back(right_points[static_cast<std::size_t>(i)]);
    }
    out.inliers = static_cast<int>(left_inliers.size());
    if (out.inliers < 30 || out.inliers * 100 < out.matches * 35) {
        out.reason = "fundamental-matrix inlier support is too weak";
        return out;
    }

    out.median_vertical_before_px = median_vertical_error(left_inliers, right_inliers);
    if (!cv::stereoRectifyUncalibrated(
            left_inliers,
            right_inliers,
            fundamental,
            left_gray.size(),
            out.left_h,
            out.right_h,
            5.0)) {
        out.reason = "stereoRectifyUncalibrated rejected the estimated geometry";
        return out;
    }

    if (!quick_rectification_homography_sane(out.left_h, left_gray.size()) ||
        !quick_rectification_homography_sane(out.right_h, right_gray.size())) {
        out.reason = "estimated rectification homography is geometrically unsafe";
        return out;
    }

    std::vector<cv::Point2f> left_rectified;
    std::vector<cv::Point2f> right_rectified;
    cv::perspectiveTransform(left_inliers, left_rectified, out.left_h);
    cv::perspectiveTransform(right_inliers, right_rectified, out.right_h);
    out.median_vertical_after_px = median_vertical_error(left_rectified, right_rectified);

    if (!std::isfinite(out.median_vertical_before_px) ||
        !std::isfinite(out.median_vertical_after_px)) {
        out.reason = "rectification produced non-finite epipolar residuals";
        return out;
    }
    if (out.median_vertical_after_px > 1.5) {
        out.reason = "rectified median vertical residual exceeds 1.5 px";
        return out;
    }
    if (out.median_vertical_before_px > 1.0 &&
        out.median_vertical_after_px > out.median_vertical_before_px * 0.70) {
        out.reason = "rectification does not sufficiently improve vertical alignment";
        return out;
    }
    if (out.median_vertical_before_px <= 1.0 &&
        out.median_vertical_after_px > out.median_vertical_before_px + 0.25) {
        out.reason = "rectification worsens an already-small vertical residual";
        return out;
    }

    out.accepted = true;
    out.reason = "locked from GFTT + NCC patch matches + RANSAC fundamental matrix";
    return out;
}

inline QuickDepthResult compute_quick_depth_pair(
    const cv::Mat& left_gray,
    const cv::Mat& right_gray,
    std::uint64_t sequence,
    int num_disparities = 160) {
    QuickDepthResult out;
    out.source_sequence = sequence;
    const auto raw = compute_quick_disparity(left_gray, right_gray, num_disparities);
    out.available = raw.available;
    out.raw_valid_fraction = raw.valid_fraction;
    out.valid_fraction = raw.valid_fraction;
    out.raw_disparity_preview = raw.disparity_preview;
    out.disparity_preview = raw.disparity_preview;
    out.proximity_preview = raw.proximity_preview;
    out.error = raw.error;
    out.rectification_reason = "raw unrectified fallback";
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
        rectification_ = {};
    }

    std::string status_json() const {
        const auto snapshot = latest();
        std::ostringstream out;
        out << "{\"enabled\":true,"
            << "\"mode\":\"quick_uncalibrated\","
            << "\"available\":" << (snapshot.available ? "true" : "false") << ','
            << "\"revision\":" << snapshot.revision << ','
            << "\"sequence\":" << snapshot.source_sequence << ','
            << "\"raw_valid_fraction\":" << snapshot.raw_valid_fraction << ','
            << "\"valid_fraction\":" << snapshot.valid_fraction << ','
            << "\"processing_ms\":" << snapshot.processing_ms << ','
            << "\"width\":" << width_ << ','
            << "\"height\":" << height_ << ','
            << "\"target_fps\":" << target_fps_ << ','
            << "\"left_camera\":\"camera_b\","
            << "\"right_camera\":\"camera_a\","
            << "\"metric\":false,"
            << "\"rectified\":" << (snapshot.rectified ? "true" : "false") << ','
            << "\"rectification_attempts\":" << snapshot.rectification_attempts << ','
            << "\"rectification_matches\":" << snapshot.rectification_matches << ','
            << "\"rectification_inliers\":" << snapshot.rectification_inliers << ','
            << "\"median_vertical_before_px\":" << snapshot.median_vertical_before_px << ','
            << "\"median_vertical_after_px\":" << snapshot.median_vertical_after_px << ','
            << "\"rectification_reason\":\"" << json_escape(snapshot.rectification_reason) << "\","
            << "\"error\":\"" << json_escape(snapshot.error) << "\"}";
        return out.str();
    }

    std::vector<unsigned char> image_jpeg(bool proximity) const {
        const auto snapshot = latest();
        if (!snapshot.available) {
            return placeholder_jpeg(
                proximity ? "Relative near/far preview" : "Stereo disparity preview",
                snapshot.error.empty() ? "waiting for paired live stereo preview" : snapshot.error);
        }
        return encode_jpeg(proximity ? snapshot.proximity_preview : snapshot.disparity_preview);
    }

    std::vector<unsigned char> raw_disparity_jpeg() const {
        const auto snapshot = latest();
        if (!snapshot.available || snapshot.raw_disparity_preview.empty()) {
            return placeholder_jpeg(
                "Raw unrectified disparity",
                snapshot.error.empty() ? "waiting for paired live stereo preview" : snapshot.error);
        }
        return encode_jpeg(snapshot.raw_disparity_preview);
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

    QuickRectificationState rectification_snapshot() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return rectification_;
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

    void update_rectification(const QuickRectificationEstimate& estimate) {
        std::lock_guard<std::mutex> lock(mutex_);
        ++rectification_.attempts;
        rectification_.matches = estimate.matches;
        rectification_.inliers = estimate.inliers;
        rectification_.median_vertical_before_px = estimate.median_vertical_before_px;
        rectification_.median_vertical_after_px = estimate.median_vertical_after_px;
        rectification_.reason = estimate.reason;
        if (estimate.accepted) {
            rectification_.ready = true;
            rectification_.left_h = estimate.left_h.clone();
            rectification_.right_h = estimate.right_h.clone();
        }
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
                    next.source_sequence = preview.sequence;
                    try {
                        // Physical mapping measured on the delivered rig:
                        // front-view left lens -> camera_a, front-view right lens -> camera_b.
                        // In the rig-forward convention this makes camera_b the stereo-left eye.
                        const auto left = quick_depth_gray_view(preview.camera_b, width_, height_);
                        const auto right = quick_depth_gray_view(preview.camera_a, width_, height_);

                        const auto raw = compute_quick_disparity(left, right, num_disparities_);
                        next.available = raw.available;
                        next.raw_valid_fraction = raw.valid_fraction;
                        next.valid_fraction = raw.valid_fraction;
                        next.raw_disparity_preview = raw.disparity_preview;
                        next.disparity_preview = raw.disparity_preview;
                        next.proximity_preview = raw.proximity_preview;
                        next.error = raw.error;

                        auto rectification = rectification_snapshot();
                        if (!rectification.ready &&
                            (rectification.attempts == 0 || preview.sequence % 10 == 0)) {
                            const auto estimate = estimate_quick_rectification(left, right);
                            update_rectification(estimate);
                            rectification = rectification_snapshot();
                        }

                        if (rectification.ready) {
                            cv::Mat left_rectified;
                            cv::Mat right_rectified;
                            cv::warpPerspective(
                                left,
                                left_rectified,
                                rectification.left_h,
                                left.size(),
                                cv::INTER_LINEAR,
                                cv::BORDER_CONSTANT);
                            cv::warpPerspective(
                                right,
                                right_rectified,
                                rectification.right_h,
                                right.size(),
                                cv::INTER_LINEAR,
                                cv::BORDER_CONSTANT);
                            const auto corrected = compute_quick_disparity(
                                left_rectified, right_rectified, num_disparities_);
                            if (corrected.available) {
                                // Guard against a mathematically plausible but practically
                                // destructive lock. Keep raw fallback rather than displaying
                                // a worse transform as an improvement.
                                if (corrected.valid_fraction + 0.03 >= raw.valid_fraction * 0.80) {
                                    next.rectified = true;
                                    next.valid_fraction = corrected.valid_fraction;
                                    next.disparity_preview = corrected.disparity_preview;
                                    next.proximity_preview = corrected.proximity_preview;
                                } else {
                                    next.rectified = false;
                                    next.error = "auto-rectification reduced valid disparity too aggressively; using raw fallback";
                                }
                            }
                        }

                        next.rectification_attempts = rectification.attempts;
                        next.rectification_matches = rectification.matches;
                        next.rectification_inliers = rectification.inliers;
                        next.median_vertical_before_px = rectification.median_vertical_before_px;
                        next.median_vertical_after_px = rectification.median_vertical_after_px;
                        next.rectification_reason = rectification.reason;
                    } catch (const cv::Exception& error) {
                        next.error = error.what();
                    } catch (const std::exception& error) {
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
    QuickRectificationState rectification_{};
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
           !result.raw_disparity_preview.empty() &&
           !result.disparity_preview.empty() &&
           !result.proximity_preview.empty();
}

}  // namespace bividi_web

#endif  // BIVIDI_HAVE_DEPTH
