#pragma once

#ifdef BIVIDI_HAVE_DEPTH

#include "bividi/depth_snapshot.hpp"

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cstdint>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace bividi_web {

inline const char* synchronization_name(bividi::SynchronizationState state) noexcept {
    switch (state) {
        case bividi::SynchronizationState::unknown: return "unknown";
        case bividi::SynchronizationState::synchronized: return "synchronized";
        case bividi::SynchronizationState::unsynchronized: return "unsynchronized";
        case bividi::SynchronizationState::degraded: return "degraded";
    }
    return "unknown";
}

inline std::string json_escape(const std::string& value) {
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

class DepthPreviewService {
public:
    DepthPreviewService(
        bividi::ObservationSnapshotSource& source,
        std::string pair_id,
        bividi::depth::StereoDepthCalibration calibration)
        : calibration_id_(calibration.calibration_id),
          pair_id_(std::move(pair_id)),
          processor_(source, pair_id_, std::move(calibration), preview_config()) {}

    [[nodiscard]] const std::string& calibration_id() const noexcept { return calibration_id_; }
    [[nodiscard]] const std::string& pair_id() const noexcept { return pair_id_; }

    std::string status_json() {
        bividi::depth::StereoDepthSnapshot snapshot;
        const bool present = processor_.latest(snapshot);
        if (!present) {
            std::ostringstream out;
            out << "{\"enabled\":true,\"observation_available\":false,"
                << "\"processed\":false,\"revision\":0,"
                << "\"calibration_id\":\"" << json_escape(calibration_id_) << "\","
                << "\"pair_id\":\"" << json_escape(pair_id_) << "\","
                << "\"disposition\":\"waiting_for_observation\","
                << "\"reason\":\"waiting for normalized observation\"}";
            return out.str();
        }

        const auto& result = snapshot.result;
        const char* disposition = snapshot.processing_error.empty()
            ? bividi::depth::stereo_depth_observation_disposition_name(result.disposition)
            : "processing_error";
        const std::string reason = snapshot.processing_error.empty()
            ? result.reason
            : snapshot.processing_error;

        std::ostringstream out;
        out << "{\"enabled\":true,"
            << "\"observation_available\":true,"
            << "\"processed\":" << (result.processed() ? "true" : "false") << ','
            << "\"revision\":" << snapshot.revision << ','
            << "\"source_id\":\"" << json_escape(result.source_id) << "\","
            << "\"sequence_present\":" << (result.sequence_present ? "true" : "false") << ','
            << "\"sequence\":" << result.sequence << ','
            << "\"continuity_epoch\":" << result.continuity_epoch << ','
            << "\"reset_generation\":" << result.reset_generation << ','
            << "\"reset_before_process\":" << (result.reset_before_process ? "true" : "false") << ','
            << "\"sequence_gap_detected\":" << (result.sequence_gap_detected ? "true" : "false") << ','
            << "\"calibration_id\":\"" << json_escape(calibration_id_) << "\","
            << "\"pair_id\":\"" << json_escape(pair_id_) << "\","
            << "\"synchronization\":\"" << synchronization_name(result.synchronization) << "\","
            << "\"valid_fraction\":" << snapshot.valid_fraction << ','
            << "\"disposition\":\"" << disposition << "\","
            << "\"reason\":\"" << json_escape(reason) << "\"}";
        return out.str();
    }

    std::vector<unsigned char> image_jpeg(bool depth) {
        bividi::depth::StereoDepthSnapshot snapshot;
        if (!processor_.latest(snapshot)) {
            return placeholder_jpeg("Derived geometry", "waiting for normalized observation");
        }
        if (!snapshot.processing_error.empty()) {
            return placeholder_jpeg("Derived geometry error", snapshot.processing_error);
        }
        if (!snapshot.result.processed()) {
            return placeholder_jpeg(
                "Derived geometry rejected",
                snapshot.result.reason.empty()
                    ? bividi::depth::stereo_depth_observation_disposition_name(snapshot.result.disposition)
                    : snapshot.result.reason);
        }

        const auto& source = depth ? snapshot.depth_preview : snapshot.disparity_preview;
        if (source.empty()) {
            return placeholder_jpeg("Derived geometry", "preview unavailable");
        }
        return encode_engineering_preview(
            source,
            depth ? "Metric depth preview" : "Disparity preview",
            snapshot.result.sequence_present
                ? "source sequence " + std::to_string(snapshot.result.sequence)
                : "source sequence unavailable");
    }

private:
    static bividi::depth::StereoDepthConfig preview_config() {
        bividi::depth::StereoDepthConfig config{};
        config.compute_xyz = false;
        return config;
    }

    static std::vector<unsigned char> encode_engineering_preview(
        const cv::Mat& gray,
        const std::string& title,
        const std::string& subtitle) {
        cv::Mat bgr;
        if (gray.type() == CV_8UC1) {
            cv::cvtColor(gray, bgr, cv::COLOR_GRAY2BGR);
        } else if (gray.type() == CV_8UC3) {
            bgr = gray.clone();
        } else {
            return placeholder_jpeg(title, "unsupported preview matrix");
        }

        cv::Mat canvas(400, 640, CV_8UC3, cv::Scalar(16, 18, 20));
        const double scale = std::min(640.0 / bgr.cols, 340.0 / bgr.rows);
        const int width = std::max(1, static_cast<int>(bgr.cols * scale));
        const int height = std::max(1, static_cast<int>(bgr.rows * scale));
        cv::Mat resized;
        cv::resize(bgr, resized, cv::Size(width, height), 0.0, 0.0, cv::INTER_NEAREST);
        resized.copyTo(canvas(cv::Rect((640 - width) / 2, 52 + (340 - height) / 2, width, height)));
        cv::putText(canvas, title, cv::Point(20, 28), cv::FONT_HERSHEY_SIMPLEX,
                    0.66, cv::Scalar(236, 238, 241), 2, cv::LINE_AA);
        cv::putText(canvas, subtitle, cv::Point(20, 49), cv::FONT_HERSHEY_SIMPLEX,
                    0.42, cv::Scalar(168, 175, 184), 1, cv::LINE_AA);

        std::vector<unsigned char> encoded;
        const std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, 88};
        cv::imencode(".jpg", canvas, encoded, params);
        return encoded;
    }

    static std::vector<unsigned char> placeholder_jpeg(
        const std::string& title,
        const std::string& detail) {
        cv::Mat canvas(400, 640, CV_8UC3, cv::Scalar(20, 23, 27));
        cv::putText(canvas, title, cv::Point(28, 178), cv::FONT_HERSHEY_SIMPLEX,
                    0.70, cv::Scalar(222, 226, 231), 2, cv::LINE_AA);
        std::string clipped = detail;
        if (clipped.size() > 78) clipped.resize(78);
        cv::putText(canvas, clipped, cv::Point(28, 214), cv::FONT_HERSHEY_SIMPLEX,
                    0.46, cv::Scalar(154, 163, 174), 1, cv::LINE_AA);
        std::vector<unsigned char> encoded;
        const std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, 82};
        cv::imencode(".jpg", canvas, encoded, params);
        return encoded;
    }

    std::string calibration_id_;
    std::string pair_id_;
    bividi::depth::StereoDepthSnapshotProcessor processor_;
};

}  // namespace bividi_web

#endif  // BIVIDI_HAVE_DEPTH
