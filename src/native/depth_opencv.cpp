#include "bividi/depth.hpp"

#include <opencv2/calib3d.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace bividi::depth {
namespace {

constexpr const char* kStereoCalibrationSchema = "bividi.calibration.stereo.v1";

std::string require_string(const cv::FileNode& parent, const char* key) {
    const auto node = parent[key];
    if (node.empty() || !node.isString()) {
        throw std::invalid_argument(std::string("missing/invalid calibration string: ") + key);
    }
    std::string value;
    node >> value;
    if (value.empty()) {
        throw std::invalid_argument(std::string("empty calibration string: ") + key);
    }
    return value;
}

int require_int(const cv::FileNode& parent, const char* key) {
    const auto node = parent[key];
    if (node.empty() || !node.isInt()) {
        throw std::invalid_argument(std::string("missing/invalid calibration integer: ") + key);
    }
    int value = 0;
    node >> value;
    return value;
}

double require_number(const cv::FileNode& parent, const char* key) {
    const auto node = parent[key];
    if (node.empty() || (!node.isInt() && !node.isReal())) {
        throw std::invalid_argument(std::string("missing/invalid calibration number: ") + key);
    }
    double value = 0.0;
    node >> value;
    if (!std::isfinite(value)) {
        throw std::invalid_argument(std::string("non-finite calibration number: ") + key);
    }
    return value;
}

cv::Mat require_matrix(const cv::FileNode& parent, const char* key, int rows, int cols) {
    const auto node = parent[key];
    if (node.empty() || !node.isSeq() || static_cast<int>(node.size()) != rows) {
        throw std::invalid_argument(std::string("invalid calibration matrix rows: ") + key);
    }

    cv::Mat result(rows, cols, CV_64F);
    int r = 0;
    for (auto row_it = node.begin(); row_it != node.end(); ++row_it, ++r) {
        const cv::FileNode row = *row_it;
        if (!row.isSeq() || static_cast<int>(row.size()) != cols) {
            throw std::invalid_argument(std::string("invalid calibration matrix columns: ") + key);
        }
        int c = 0;
        for (auto value_it = row.begin(); value_it != row.end(); ++value_it, ++c) {
            const cv::FileNode value_node = *value_it;
            if (!value_node.isInt() && !value_node.isReal()) {
                throw std::invalid_argument(std::string("non-numeric calibration matrix value: ") + key);
            }
            double value = 0.0;
            value_node >> value;
            if (!std::isfinite(value)) {
                throw std::invalid_argument(std::string("non-finite calibration matrix value: ") + key);
            }
            result.at<double>(r, c) = value;
        }
    }
    return result;
}

cv::Mat require_vector(const cv::FileNode& parent, const char* key, int min_count) {
    const auto node = parent[key];
    if (node.empty() || !node.isSeq() || static_cast<int>(node.size()) < min_count) {
        throw std::invalid_argument(std::string("invalid calibration vector: ") + key);
    }
    cv::Mat result(1, static_cast<int>(node.size()), CV_64F);
    int c = 0;
    for (auto it = node.begin(); it != node.end(); ++it, ++c) {
        const cv::FileNode value_node = *it;
        if (!value_node.isInt() && !value_node.isReal()) {
            throw std::invalid_argument(std::string("non-numeric calibration vector value: ") + key);
        }
        double value = 0.0;
        value_node >> value;
        if (!std::isfinite(value)) {
            throw std::invalid_argument(std::string("non-finite calibration vector value: ") + key);
        }
        result.at<double>(0, c) = value;
    }
    return result;
}

bool finite_matrix(const cv::Mat& matrix) {
    if (matrix.empty() || matrix.depth() != CV_64F) return false;
    for (int r = 0; r < matrix.rows; ++r) {
        for (int c = 0; c < matrix.cols; ++c) {
            if (!std::isfinite(matrix.at<double>(r, c))) return false;
        }
    }
    return true;
}

void require_shape(const cv::Mat& matrix, int rows, int cols, const char* name) {
    if (matrix.rows != rows || matrix.cols != cols || matrix.type() != CV_64F || !finite_matrix(matrix)) {
        throw std::invalid_argument(std::string("invalid stereo-depth calibration matrix: ") + name);
    }
}

cv::Mat borrowed_mat(const ImageView& view) {
    if (view.empty()) throw std::invalid_argument("stereo-depth input image is empty");
    if (view.width > static_cast<std::size_t>(std::numeric_limits<int>::max()) ||
        view.height > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        throw std::invalid_argument("stereo-depth input geometry exceeds OpenCV integer range");
    }

    int type = 0;
    std::size_t expected_bpp = 0;
    switch (view.pixel_format) {
        case PixelFormat::gray8:
            type = CV_8UC1;
            expected_bpp = 1;
            break;
        case PixelFormat::bgr24:
            type = CV_8UC3;
            expected_bpp = 3;
            break;
        default:
            throw std::invalid_argument("stereo-depth input must be GRAY8 or BGR24");
    }
    if (view.bytes_per_pixel != expected_bpp || view.row_stride < view.row_bytes()) {
        throw std::invalid_argument("stereo-depth input stride/pixel representation is inconsistent");
    }

    // cv::Mat has no const-data header constructor. The pipeline only passes
    // this header to read-only OpenCV operations; source ownership stays with
    // the caller for the duration of process().
    return cv::Mat(
        static_cast<int>(view.height),
        static_cast<int>(view.width),
        type,
        const_cast<std::uint8_t*>(view.data),
        view.row_stride);
}

cv::Mat to_gray(const cv::Mat& image) {
    if (image.type() == CV_8UC1) return image;
    if (image.type() == CV_8UC3) {
        cv::Mat gray;
        cv::cvtColor(image, gray, cv::COLOR_BGR2GRAY);
        return gray;
    }
    throw std::invalid_argument("unsupported rectified image representation");
}

cv::Mat normalized_preview(const cv::Mat& values, const cv::Mat& valid_mask, bool reverse) {
    if (values.empty() || values.type() != CV_32FC1 || valid_mask.type() != CV_8UC1 ||
        values.size() != valid_mask.size()) {
        throw std::invalid_argument("invalid preview source matrices");
    }
    cv::Mat preview(values.size(), CV_8UC1, cv::Scalar(0));
    double min_value = 0.0;
    double max_value = 0.0;
    cv::minMaxLoc(values, &min_value, &max_value, nullptr, nullptr, valid_mask);
    if (!std::isfinite(min_value) || !std::isfinite(max_value)) return preview;

    const double range = max_value - min_value;
    for (int y = 0; y < values.rows; ++y) {
        for (int x = 0; x < values.cols; ++x) {
            if (valid_mask.at<std::uint8_t>(y, x) == 0) continue;
            const float value = values.at<float>(y, x);
            if (!std::isfinite(value)) continue;
            double t = range > 1e-12 ? (static_cast<double>(value) - min_value) / range : 1.0;
            t = std::clamp(t, 0.0, 1.0);
            if (reverse) t = 1.0 - t;
            preview.at<std::uint8_t>(y, x) = static_cast<std::uint8_t>(std::lround(255.0 * t));
        }
    }
    return preview;
}

}  // namespace

StereoDepthCalibration load_calibration_json(const std::string& path) {
    cv::FileStorage file(path, cv::FileStorage::READ | cv::FileStorage::FORMAT_JSON);
    if (!file.isOpened()) {
        throw std::invalid_argument("cannot open stereo calibration artifact: " + path);
    }

    StereoDepthCalibration out;
    file["schema"] >> out.schema;
    if (out.schema != kStereoCalibrationSchema) {
        throw std::invalid_argument("unsupported stereo calibration schema: " + out.schema);
    }
    file["calibration_id"] >> out.calibration_id;
    if (out.calibration_id.empty()) throw std::invalid_argument("stereo calibration_id is empty");

    const auto provenance = file["provenance"];
    out.evidence_kind = require_string(provenance, "kind");

    const auto capture = file["capture"];
    out.camera_a_identity = require_string(capture, "camera_a_identity");
    out.camera_b_identity = require_string(capture, "camera_b_identity");

    const auto image = file["image"];
    out.width = require_int(image, "width");
    out.height = require_int(image, "height");

    const auto camera_model = file["camera_model"];
    const auto projection = require_string(camera_model, "projection");
    const auto distortion = require_string(camera_model, "distortion");
    if (projection != "pinhole" || (distortion != "opencv5" && distortion != "opencv-rational")) {
        throw std::invalid_argument("#9 first slice supports #8 pinhole opencv5/opencv-rational calibration only");
    }

    const auto cameras = file["cameras"];
    const auto camera_a = cameras["camera_a"];
    const auto camera_b = cameras["camera_b"];
    out.K_a = require_matrix(camera_a, "K", 3, 3);
    out.D_a = require_vector(camera_a, "D", 4);
    out.K_b = require_matrix(camera_b, "K", 3, 3);
    out.D_b = require_vector(camera_b, "D", 4);

    const auto stereo = file["stereo"];
    out.baseline_m = require_number(stereo, "baseline_m");

    const auto rectification = file["rectification"];
    out.R1 = require_matrix(rectification, "R1", 3, 3);
    out.R2 = require_matrix(rectification, "R2", 3, 3);
    out.P1 = require_matrix(rectification, "P1", 3, 4);
    out.P2 = require_matrix(rectification, "P2", 3, 4);
    out.Q = require_matrix(rectification, "Q", 4, 4);

    validate_calibration(out);
    return out;
}

void validate_calibration(const StereoDepthCalibration& calibration) {
    if (calibration.schema != kStereoCalibrationSchema) {
        throw std::invalid_argument("stereo-depth calibration must be bividi.calibration.stereo.v1");
    }
    if (calibration.calibration_id.empty() || calibration.camera_a_identity.empty() ||
        calibration.camera_b_identity.empty()) {
        throw std::invalid_argument("stereo-depth calibration identity is incomplete");
    }
    if (calibration.width <= 0 || calibration.height <= 0) {
        throw std::invalid_argument("stereo-depth calibration image geometry is invalid");
    }
    if (!std::isfinite(calibration.baseline_m) || calibration.baseline_m <= 0.0) {
        throw std::invalid_argument("stereo-depth baseline must be finite and positive");
    }

    require_shape(calibration.K_a, 3, 3, "K_a");
    require_shape(calibration.K_b, 3, 3, "K_b");
    if (calibration.D_a.empty() || calibration.D_b.empty() || calibration.D_a.type() != CV_64F ||
        calibration.D_b.type() != CV_64F || !finite_matrix(calibration.D_a) || !finite_matrix(calibration.D_b)) {
        throw std::invalid_argument("stereo-depth distortion vectors are invalid");
    }
    require_shape(calibration.R1, 3, 3, "R1");
    require_shape(calibration.R2, 3, 3, "R2");
    require_shape(calibration.P1, 3, 4, "P1");
    require_shape(calibration.P2, 3, 4, "P2");
    require_shape(calibration.Q, 4, 4, "Q");

    const double fx = calibration.P1.at<double>(0, 0);
    const double fy = calibration.P1.at<double>(1, 1);
    if (!(fx > 0.0) || !(fy > 0.0)) {
        throw std::invalid_argument("rectified P1 focal lengths must be positive");
    }

    const double p2_fx = calibration.P2.at<double>(0, 0);
    if (std::abs(p2_fx) > 1e-12) {
        const double projected_baseline = std::abs(calibration.P2.at<double>(0, 3) / p2_fx);
        const double tolerance = std::max(1e-8, calibration.baseline_m * 1e-4);
        if (projected_baseline > 1e-12 && std::abs(projected_baseline - calibration.baseline_m) > tolerance) {
            throw std::invalid_argument("rectified P2 baseline disagrees with calibration baseline_m");
        }
    }
}

void validate_config(const StereoDepthConfig& config) {
    if (config.num_disparities <= 0 || (config.num_disparities % 16) != 0) {
        throw std::invalid_argument("StereoSGBM num_disparities must be a positive multiple of 16");
    }
    if (config.block_size < 3 || (config.block_size % 2) == 0) {
        throw std::invalid_argument("StereoSGBM block_size must be odd and >= 3");
    }
    if (config.uniqueness_ratio < 0 || config.disp12_max_diff < -1 || config.pre_filter_cap < 0 ||
        config.speckle_window_size < 0 || config.speckle_range < 0) {
        throw std::invalid_argument("StereoSGBM configuration contains invalid negative values");
    }
}

MetricGeometry metric_geometry_from_disparity(
    const cv::Mat& disparity_px,
    const cv::Mat& disparity_valid_mask,
    const StereoDepthCalibration& calibration,
    bool compute_xyz) {
    validate_calibration(calibration);
    if (disparity_px.empty() || disparity_px.type() != CV_32FC1 ||
        disparity_valid_mask.type() != CV_8UC1 || disparity_px.size() != disparity_valid_mask.size()) {
        throw std::invalid_argument("metric depth requires CV_32F disparity and matching CV_8U validity mask");
    }
    if (disparity_px.cols != calibration.width || disparity_px.rows != calibration.height) {
        throw std::invalid_argument("disparity geometry does not match calibration geometry");
    }

    const float nan = std::numeric_limits<float>::quiet_NaN();
    MetricGeometry result;
    result.depth_m = cv::Mat(disparity_px.size(), CV_32FC1, cv::Scalar(nan));
    result.valid_mask = cv::Mat(disparity_px.size(), CV_8UC1, cv::Scalar(0));
    if (compute_xyz) {
        result.xyz_m = cv::Mat(disparity_px.size(), CV_32FC3, cv::Scalar(nan, nan, nan));
    }

    const double fx = calibration.P1.at<double>(0, 0);
    const double fy = calibration.P1.at<double>(1, 1);
    const double cx = calibration.P1.at<double>(0, 2);
    const double cy = calibration.P1.at<double>(1, 2);
    const double numerator = fx * calibration.baseline_m;

    for (int y = 0; y < disparity_px.rows; ++y) {
        for (int x = 0; x < disparity_px.cols; ++x) {
            if (disparity_valid_mask.at<std::uint8_t>(y, x) == 0) continue;
            const float disparity = disparity_px.at<float>(y, x);
            if (!std::isfinite(disparity) || disparity <= 0.0f) continue;

            const double z = numerator / static_cast<double>(disparity);
            if (!std::isfinite(z) || z <= 0.0) continue;
            result.depth_m.at<float>(y, x) = static_cast<float>(z);
            result.valid_mask.at<std::uint8_t>(y, x) = 255;

            if (compute_xyz) {
                const double x_m = (static_cast<double>(x) - cx) * z / fx;
                const double y_m = (static_cast<double>(y) - cy) * z / fy;
                result.xyz_m.at<cv::Vec3f>(y, x) = cv::Vec3f(
                    static_cast<float>(x_m),
                    static_cast<float>(y_m),
                    static_cast<float>(z));
            }
        }
    }
    return result;
}

StereoDepthProcessor::StereoDepthProcessor(StereoDepthCalibration calibration, StereoDepthConfig config)
    : calibration_(std::move(calibration)), config_(config) {
    validate_calibration(calibration_);
    validate_config(config_);

    const cv::Size size(calibration_.width, calibration_.height);
    cv::initUndistortRectifyMap(
        calibration_.K_a,
        calibration_.D_a,
        calibration_.R1,
        calibration_.P1,
        size,
        CV_32FC1,
        map_a_x_,
        map_a_y_);
    cv::initUndistortRectifyMap(
        calibration_.K_b,
        calibration_.D_b,
        calibration_.R2,
        calibration_.P2,
        size,
        CV_32FC1,
        map_b_x_,
        map_b_y_);
}

StereoDepthResult StereoDepthProcessor::process(const ImageView& camera_a, const ImageView& camera_b) const {
    if (camera_a.width != static_cast<std::size_t>(calibration_.width) ||
        camera_a.height != static_cast<std::size_t>(calibration_.height) ||
        camera_b.width != static_cast<std::size_t>(calibration_.width) ||
        camera_b.height != static_cast<std::size_t>(calibration_.height)) {
        throw std::invalid_argument("stereo-depth input image geometry does not match calibration");
    }

    const cv::Mat source_a = borrowed_mat(camera_a);
    const cv::Mat source_b = borrowed_mat(camera_b);
    if (source_a.type() != source_b.type()) {
        throw std::invalid_argument("stereo-depth camera A/B pixel representations differ");
    }

    StereoDepthResult result;
    result.calibration_id = calibration_.calibration_id;
    result.coordinate_frame = calibration_.rectified_frame;
    cv::remap(source_a, result.rectified_a, map_a_x_, map_a_y_, cv::INTER_LINEAR, cv::BORDER_CONSTANT);
    cv::remap(source_b, result.rectified_b, map_b_x_, map_b_y_, cv::INTER_LINEAR, cv::BORDER_CONSTANT);

    const cv::Mat gray_a = to_gray(result.rectified_a);
    const cv::Mat gray_b = to_gray(result.rectified_b);

    auto matcher = cv::StereoSGBM::create(config_.min_disparity, config_.num_disparities, config_.block_size);
    const int block_area = config_.block_size * config_.block_size;
    matcher->setP1(8 * block_area);
    matcher->setP2(32 * block_area);
    matcher->setDisp12MaxDiff(config_.disp12_max_diff);
    matcher->setPreFilterCap(config_.pre_filter_cap);
    matcher->setUniquenessRatio(config_.uniqueness_ratio);
    matcher->setSpeckleWindowSize(config_.speckle_window_size);
    matcher->setSpeckleRange(config_.speckle_range);
    matcher->setMode(cv::StereoSGBM::MODE_SGBM_3WAY);

    cv::Mat raw_disparity;
    matcher->compute(gray_a, gray_b, raw_disparity);
    if (raw_disparity.type() != CV_16SC1) {
        throw std::runtime_error("StereoSGBM returned an unexpected disparity representation");
    }

    const float nan = std::numeric_limits<float>::quiet_NaN();
    result.disparity_px = cv::Mat(raw_disparity.size(), CV_32FC1, cv::Scalar(nan));
    cv::Mat disparity_valid(raw_disparity.size(), CV_8UC1, cv::Scalar(0));
    for (int y = 0; y < raw_disparity.rows; ++y) {
        for (int x = 0; x < raw_disparity.cols; ++x) {
            const std::int16_t raw = raw_disparity.at<std::int16_t>(y, x);
            const float disparity = static_cast<float>(raw) / 16.0f;
            // Metric depth in this first horizontal-stereo reference path
            // requires finite positive disparity. OpenCV's invalid sentinel and
            // zero/negative disparities remain explicitly invalid.
            if (std::isfinite(disparity) && disparity > 0.0f) {
                result.disparity_px.at<float>(y, x) = disparity;
                disparity_valid.at<std::uint8_t>(y, x) = 255;
            }
        }
    }

    auto metric = metric_geometry_from_disparity(
        result.disparity_px, disparity_valid, calibration_, config_.compute_xyz);
    result.valid_mask = std::move(metric.valid_mask);
    result.depth_m = std::move(metric.depth_m);
    result.xyz_m = std::move(metric.xyz_m);
    return result;
}

cv::Mat disparity_preview_u8(const StereoDepthResult& result) {
    return normalized_preview(result.disparity_px, result.valid_mask, false);
}

cv::Mat depth_preview_u8(const StereoDepthResult& result) {
    // Nearer depth is brighter for the engineering preview.
    return normalized_preview(result.depth_m, result.valid_mask, true);
}

}  // namespace bividi::depth
