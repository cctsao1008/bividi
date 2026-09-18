#pragma once

#include "bividi/image_view.hpp"

#include <opencv2/core.hpp>

#include <cstdint>
#include <string>

namespace bividi::depth {

// OpenCV-dependent, downstream stereo geometry. This API is intentionally not
// part of bividi_core or the raw SensorObservation contract.
struct StereoDepthCalibration {
    std::string schema;
    std::string calibration_id;
    std::string evidence_kind;
    std::string camera_a_identity;
    std::string camera_b_identity;
    std::string rectified_frame = "camera_a_rectified";

    int width = 0;
    int height = 0;
    double baseline_m = 0.0;

    cv::Mat K_a;  // 3x3 CV_64F
    cv::Mat D_a;  // 1xN CV_64F
    cv::Mat K_b;  // 3x3 CV_64F
    cv::Mat D_b;  // 1xN CV_64F
    cv::Mat R1;   // 3x3 CV_64F
    cv::Mat R2;   // 3x3 CV_64F
    cv::Mat P1;   // 3x4 CV_64F
    cv::Mat P2;   // 3x4 CV_64F
    cv::Mat Q;    // 4x4 CV_64F
};

struct StereoDepthConfig {
    int min_disparity = 0;
    int num_disparities = 64;  // OpenCV requires a positive multiple of 16.
    int block_size = 5;        // odd, >= 3
    int uniqueness_ratio = 10;
    int disp12_max_diff = 1;
    int pre_filter_cap = 31;
    int speckle_window_size = 0;
    int speckle_range = 0;
    bool compute_xyz = false;
};

struct MetricGeometry {
    cv::Mat depth_m;    // CV_32FC1; invalid pixels are quiet NaN.
    cv::Mat xyz_m;      // optional CV_32FC3 in rectified camera-A coordinates.
    cv::Mat valid_mask; // CV_8UC1, 255 exactly where numeric geometry is valid.
};

struct StereoDepthResult {
    std::string calibration_id;
    std::string coordinate_frame;

    cv::Mat rectified_a;       // owned, same channel count as source
    cv::Mat rectified_b;       // owned, same channel count as source
    cv::Mat disparity_px;      // CV_32FC1; invalid pixels are quiet NaN
    cv::Mat valid_mask;        // CV_8UC1
    cv::Mat depth_m;           // CV_32FC1, meters
    cv::Mat xyz_m;             // optional CV_32FC3, meters
};

// Loads exactly the geometry needed by #9 from a versioned #8
// bividi.calibration.stereo.v1 artifact. This is not a replacement for the #8
// promotion/provenance gate; it is a strict consumer of an already selected
// artifact.
[[nodiscard]] StereoDepthCalibration load_calibration_json(const std::string& path);

// Validate the geometry contract before rectification or metric conversion.
// Throws std::invalid_argument on malformed/incompatible calibration data.
void validate_calibration(const StereoDepthCalibration& calibration);
void validate_config(const StereoDepthConfig& config);

// Deterministic metric conversion that is separately testable from StereoSGBM.
// Uses rectified P1 focal/principal-point geometry plus the measured/synthetic
// baseline carried by the calibration artifact:
//     Z = fx * baseline / disparity
[[nodiscard]] MetricGeometry metric_geometry_from_disparity(
    const cv::Mat& disparity_px,
    const cv::Mat& disparity_valid_mask,
    const StereoDepthCalibration& calibration,
    bool compute_xyz);

class StereoDepthProcessor {
public:
    StereoDepthProcessor(StereoDepthCalibration calibration, StereoDepthConfig config = {});

    [[nodiscard]] const StereoDepthCalibration& calibration() const noexcept { return calibration_; }
    [[nodiscard]] const StereoDepthConfig& config() const noexcept { return config_; }

    // Input images are borrowed. Results are owned OpenCV matrices and remain
    // valid after the source ImageView/FrameLease is released.
    [[nodiscard]] StereoDepthResult process(const ImageView& camera_a, const ImageView& camera_b) const;

private:
    StereoDepthCalibration calibration_;
    StereoDepthConfig config_;
    cv::Mat map_a_x_;
    cv::Mat map_a_y_;
    cv::Mat map_b_x_;
    cv::Mat map_b_y_;
};

// UI-only visualization helpers. They never replace the float disparity/depth
// products above and do not alter validity semantics.
[[nodiscard]] cv::Mat disparity_preview_u8(const StereoDepthResult& result);
[[nodiscard]] cv::Mat depth_preview_u8(const StereoDepthResult& result);

}  // namespace bividi::depth
