#pragma once

#include "bividi/session.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/video/tracking.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <numeric>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace bividi_web {

struct SparseFlowCameraResult {
    bool available = false;
    int detected_features = 0;
    int reliable_tracks = 0;
    double retention_fraction = 0.0;
    double mean_motion_px_per_source_frame = 0.0;
    double p95_motion_px_per_source_frame = 0.0;
    double mean_dx_px_per_source_frame = 0.0;
    double mean_dy_px_per_source_frame = 0.0;
    double mean_forward_backward_error_px = 0.0;
    cv::Mat overlay;
};

struct SparseFlowResult {
    bool available = false;
    std::uint64_t revision = 0;
    std::uint64_t source_sequence = 0;
    std::uint64_t sampled_sequence_delta = 0;
    std::uint64_t discontinuity_resets = 0;
    double processing_ms = 0.0;
    SparseFlowCameraResult camera_a;
    SparseFlowCameraResult camera_b;
    std::string reason;
};

inline cv::Mat optical_flow_gray_view(const bividi::ImageView& view, int width, int height) {
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

inline std::vector<cv::Point2f> detect_sparse_flow_features(
    const cv::Mat& gray,
    int max_features = 320) {
    std::vector<cv::Point2f> points;
    if (gray.empty() || gray.type() != CV_8UC1) return points;
    cv::goodFeaturesToTrack(
        gray,
        points,
        std::max(32, max_features),
        0.01,
        8.0,
        cv::noArray(),
        7,
        false,
        0.04);
    return points;
}

inline double percentile95(std::vector<double> values) {
    if (values.empty()) return 0.0;
    const std::size_t index = static_cast<std::size_t>(
        std::floor(0.95 * static_cast<double>(values.size() - 1)));
    std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(index), values.end());
    return values[index];
}

class SparseOpticalFlowTracker {
public:
    void reset() {
        previous_gray_.release();
        previous_points_.clear();
        initialized_ = false;
    }

    SparseFlowCameraResult process(
        const cv::Mat& gray,
        std::uint64_t source_sequence_delta) {
        SparseFlowCameraResult out;
        if (gray.empty() || gray.type() != CV_8UC1) return out;

        cv::cvtColor(gray, out.overlay, cv::COLOR_GRAY2BGR);
        if (!initialized_ || previous_gray_.size() != gray.size()) {
            previous_gray_ = gray.clone();
            previous_points_ = detect_sparse_flow_features(gray, max_features_);
            out.detected_features = static_cast<int>(previous_points_.size());
            for (const auto& point : previous_points_) {
                cv::circle(out.overlay, point, 2, cv::Scalar(180, 180, 180), -1, cv::LINE_AA);
            }
            out.available = true;
            initialized_ = true;
            return out;
        }

        if (previous_points_.size() < 32) {
            previous_points_ = detect_sparse_flow_features(previous_gray_, max_features_);
        }
        out.detected_features = static_cast<int>(previous_points_.size());
        if (previous_points_.empty()) {
            previous_gray_ = gray.clone();
            previous_points_ = detect_sparse_flow_features(gray, max_features_);
            out.detected_features = static_cast<int>(previous_points_.size());
            out.available = true;
            return out;
        }

        std::vector<cv::Point2f> forward;
        std::vector<unsigned char> forward_status;
        std::vector<float> forward_error;
        cv::calcOpticalFlowPyrLK(
            previous_gray_,
            gray,
            previous_points_,
            forward,
            forward_status,
            forward_error,
            cv::Size(21, 21),
            3,
            cv::TermCriteria(cv::TermCriteria::COUNT | cv::TermCriteria::EPS, 30, 0.01));

        std::vector<cv::Point2f> previous_valid;
        std::vector<cv::Point2f> forward_valid;
        previous_valid.reserve(previous_points_.size());
        forward_valid.reserve(previous_points_.size());
        const auto in_bounds = [&gray](const cv::Point2f& p) {
            return p.x >= 2.0f && p.y >= 2.0f &&
                   p.x < static_cast<float>(gray.cols - 2) &&
                   p.y < static_cast<float>(gray.rows - 2);
        };
        for (std::size_t i = 0; i < previous_points_.size(); ++i) {
            if (i >= forward_status.size() || forward_status[i] == 0) continue;
            if (i >= forward.size() || !in_bounds(forward[i])) continue;
            previous_valid.push_back(previous_points_[i]);
            forward_valid.push_back(forward[i]);
        }

        std::vector<cv::Point2f> backward;
        std::vector<unsigned char> backward_status;
        std::vector<float> backward_error;
        if (!forward_valid.empty()) {
            cv::calcOpticalFlowPyrLK(
                gray,
                previous_gray_,
                forward_valid,
                backward,
                backward_status,
                backward_error,
                cv::Size(21, 21),
                3,
                cv::TermCriteria(cv::TermCriteria::COUNT | cv::TermCriteria::EPS, 30, 0.01));
        }

        const double frame_delta = static_cast<double>(std::max<std::uint64_t>(1, source_sequence_delta));
        std::vector<cv::Point2f> retained_current;
        std::vector<double> motions;
        retained_current.reserve(forward_valid.size());
        motions.reserve(forward_valid.size());
        double sum_motion = 0.0;
        double sum_dx = 0.0;
        double sum_dy = 0.0;
        double sum_fb = 0.0;

        for (std::size_t i = 0; i < forward_valid.size(); ++i) {
            if (i >= backward_status.size() || backward_status[i] == 0 || i >= backward.size()) continue;
            const double fb_error = cv::norm(backward[i] - previous_valid[i]);
            if (!std::isfinite(fb_error) || fb_error > forward_backward_gate_px_) continue;

            const cv::Point2f delta = forward_valid[i] - previous_valid[i];
            const double dx = static_cast<double>(delta.x) / frame_delta;
            const double dy = static_cast<double>(delta.y) / frame_delta;
            const double motion = std::hypot(dx, dy);
            if (!std::isfinite(motion)) continue;

            retained_current.push_back(forward_valid[i]);
            motions.push_back(motion);
            sum_motion += motion;
            sum_dx += dx;
            sum_dy += dy;
            sum_fb += fb_error;

            cv::arrowedLine(
                out.overlay,
                previous_valid[i],
                forward_valid[i],
                cv::Scalar(70, 230, 255),
                1,
                cv::LINE_AA,
                0,
                0.22);
            cv::circle(out.overlay, forward_valid[i], 2, cv::Scalar(80, 255, 120), -1, cv::LINE_AA);
        }

        out.reliable_tracks = static_cast<int>(retained_current.size());
        out.retention_fraction = previous_points_.empty()
            ? 0.0
            : static_cast<double>(out.reliable_tracks) / static_cast<double>(previous_points_.size());
        if (out.reliable_tracks > 0) {
            const double count = static_cast<double>(out.reliable_tracks);
            out.mean_motion_px_per_source_frame = sum_motion / count;
            out.p95_motion_px_per_source_frame = percentile95(motions);
            out.mean_dx_px_per_source_frame = sum_dx / count;
            out.mean_dy_px_per_source_frame = sum_dy / count;
            out.mean_forward_backward_error_px = sum_fb / count;
        }

        cv::putText(
            out.overlay,
            "LK tracks " + std::to_string(out.reliable_tracks),
            cv::Point(18, 28),
            cv::FONT_HERSHEY_SIMPLEX,
            0.62,
            cv::Scalar(245, 245, 245),
            2,
            cv::LINE_AA);

        previous_gray_ = gray.clone();
        if (retained_current.size() >= min_tracks_before_redetect_) {
            previous_points_ = std::move(retained_current);
        } else {
            previous_points_ = detect_sparse_flow_features(gray, max_features_);
        }
        out.available = true;
        return out;
    }

private:
    cv::Mat previous_gray_;
    std::vector<cv::Point2f> previous_points_;
    bool initialized_ = false;
    int max_features_ = 320;
    std::size_t min_tracks_before_redetect_ = 96;
    double forward_backward_gate_px_ = 1.5;
};

class OpticalFlowPreviewService {
public:
    explicit OpticalFlowPreviewService(
        bividi::CaptureSession& session,
        int width = 640,
        int height = 400,
        int target_fps = 15)
        : session_(session),
          width_(width),
          height_(height),
          target_fps_(std::max(1, target_fps)),
          worker_([this] { run(); }) {}

    ~OpticalFlowPreviewService() {
        stop_.store(true);
        if (worker_.joinable()) worker_.join();
    }

    OpticalFlowPreviewService(const OpticalFlowPreviewService&) = delete;
    OpticalFlowPreviewService& operator=(const OpticalFlowPreviewService&) = delete;

    void reset() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            result_ = {};
            last_source_sequence_ = 0;
        }
        tracker_reset_requested_.store(true);
    }

    std::string status_json() const {
        const auto snapshot = latest();
        std::ostringstream out;
        out << "{\"enabled\":true,"
            << "\"mode\":\"sparse_pyr_lk\","
            << "\"available\":" << (snapshot.available ? "true" : "false") << ','
            << "\"revision\":" << snapshot.revision << ','
            << "\"sequence\":" << snapshot.source_sequence << ','
            << "\"sampled_sequence_delta\":" << snapshot.sampled_sequence_delta << ','
            << "\"discontinuity_resets\":" << snapshot.discontinuity_resets << ','
            << "\"processing_ms\":" << snapshot.processing_ms << ','
            << "\"width\":" << width_ << ','
            << "\"height\":" << height_ << ','
            << "\"target_fps\":" << target_fps_ << ','
            << "\"forward_backward_gate_px\":1.5,"
            << "\"camera_a\":" << camera_json(snapshot.camera_a) << ','
            << "\"camera_b\":" << camera_json(snapshot.camera_b) << ','
            << "\"reason\":\"" << json_escape(snapshot.reason) << "\"}";
        return out.str();
    }

    std::vector<unsigned char> image_jpeg(bool camera_b) const {
        const auto snapshot = latest();
        const auto& camera = camera_b ? snapshot.camera_b : snapshot.camera_a;
        if (!snapshot.available || !camera.available || camera.overlay.empty()) {
            return placeholder_jpeg(
                camera_b ? "Camera B sparse optical flow" : "Camera A sparse optical flow",
                snapshot.reason.empty() ? "waiting for consecutive stereo preview frames" : snapshot.reason);
        }
        return encode_jpeg(camera.overlay);
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

    static std::string camera_json(const SparseFlowCameraResult& camera) {
        std::ostringstream out;
        out << '{'
            << "\"available\":" << (camera.available ? "true" : "false") << ','
            << "\"detected_features\":" << camera.detected_features << ','
            << "\"reliable_tracks\":" << camera.reliable_tracks << ','
            << "\"retention_fraction\":" << camera.retention_fraction << ','
            << "\"mean_motion_px_per_source_frame\":" << camera.mean_motion_px_per_source_frame << ','
            << "\"p95_motion_px_per_source_frame\":" << camera.p95_motion_px_per_source_frame << ','
            << "\"mean_dx_px_per_source_frame\":" << camera.mean_dx_px_per_source_frame << ','
            << "\"mean_dy_px_per_source_frame\":" << camera.mean_dy_px_per_source_frame << ','
            << "\"mean_forward_backward_error_px\":" << camera.mean_forward_backward_error_px
            << '}';
        return out.str();
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

    SparseFlowResult latest() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return result_;
    }

    void publish(SparseFlowResult next) {
        std::lock_guard<std::mutex> lock(mutex_);
        next.revision = result_.revision + 1;
        result_ = std::move(next);
    }

    void run() {
        const auto period = std::chrono::milliseconds(std::max(1, 1000 / target_fps_));
        while (!stop_.load()) {
            const auto started = std::chrono::steady_clock::now();
            if (tracker_reset_requested_.exchange(false)) {
                tracker_a_.reset();
                tracker_b_.reset();
            }

            bividi::StereoPreviewFrame preview;
            if (session_.latest_stereo_preview(preview) && preview.valid()) {
                std::uint64_t previous_sequence = 0;
                bool is_new = false;
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    previous_sequence = last_source_sequence_;
                    is_new = preview.sequence != last_source_sequence_;
                    if (is_new) last_source_sequence_ = preview.sequence;
                }

                if (is_new) {
                    SparseFlowResult next;
                    next.source_sequence = preview.sequence;
                    next.sampled_sequence_delta = previous_sequence == 0 || preview.sequence <= previous_sequence
                        ? 0
                        : preview.sequence - previous_sequence;
                    next.discontinuity_resets = discontinuity_resets_;
                    try {
                        const bool discontinuity =
                            previous_sequence != 0 &&
                            (preview.sequence <= previous_sequence || next.sampled_sequence_delta > 12);
                        if (discontinuity) {
                            tracker_a_.reset();
                            tracker_b_.reset();
                            ++discontinuity_resets_;
                            next.discontinuity_resets = discontinuity_resets_;
                        }

                        const auto gray_a = optical_flow_gray_view(preview.camera_a, width_, height_);
                        const auto gray_b = optical_flow_gray_view(preview.camera_b, width_, height_);
                        if (gray_a.empty() || gray_b.empty()) {
                            next.reason = "stereo preview is not BGR24 or could not be resized";
                        } else {
                            const auto delta = std::max<std::uint64_t>(1, next.sampled_sequence_delta);
                            next.camera_a = tracker_a_.process(gray_a, delta);
                            next.camera_b = tracker_b_.process(gray_b, delta);
                            next.available = next.camera_a.available && next.camera_b.available;
                            next.reason = discontinuity
                                ? "tracker reset after source-sequence discontinuity"
                                : "forward/backward-consistent pyramidal LK tracks";
                        }
                    } catch (const cv::Exception& error) {
                        next.reason = error.what();
                    } catch (const std::exception& error) {
                        next.reason = error.what();
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
    int target_fps_ = 15;
    mutable std::mutex mutex_;
    SparseFlowResult result_{};
    std::uint64_t last_source_sequence_ = 0;
    std::uint64_t discontinuity_resets_ = 0;
    SparseOpticalFlowTracker tracker_a_;
    SparseOpticalFlowTracker tracker_b_;
    std::atomic<bool> tracker_reset_requested_{false};
    std::atomic<bool> stop_{false};
    std::thread worker_;
};

inline bool optical_flow_self_test() {
    cv::Mat first(400, 640, CV_8UC1, cv::Scalar(0));
    for (int y = 50; y <= 350; y += 40) {
        for (int x = 50; x <= 590; x += 40) {
            cv::rectangle(first, cv::Rect(x - 5, y - 5, 10, 10), cv::Scalar(255), -1);
        }
    }

    cv::Mat transform = (cv::Mat_<double>(2, 3) << 1.0, 0.0, 6.0, 0.0, 1.0, 4.0);
    cv::Mat second;
    cv::warpAffine(first, second, transform, first.size(), cv::INTER_LINEAR, cv::BORDER_CONSTANT);

    SparseOpticalFlowTracker tracker;
    const auto initialized = tracker.process(first, 1);
    const auto moved = tracker.process(second, 1);
    if (!initialized.available || !moved.available || moved.reliable_tracks < 20) return false;
    if (moved.mean_dx_px_per_source_frame < 4.5 || moved.mean_dx_px_per_source_frame > 7.5) return false;
    if (moved.mean_dy_px_per_source_frame < 2.5 || moved.mean_dy_px_per_source_frame > 5.5) return false;
    if (moved.mean_forward_backward_error_px > 1.0) return false;
    return true;
}

}  // namespace bividi_web
