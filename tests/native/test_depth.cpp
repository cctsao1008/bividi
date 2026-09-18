#include "bividi/depth.hpp"
#include "bividi/depth_observation.hpp"

#include <opencv2/core.hpp>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr int kWidth = 96;
constexpr int kHeight = 64;
constexpr int kDisparity = 4;
constexpr std::uint32_t kSeed = 0xB1D1D1u;

std::uint8_t texture(int x, int y) {
    std::uint32_t v = kSeed ^
        (static_cast<std::uint32_t>(x + 0x9E37) * 0x045D9F3Bu) ^
        (static_cast<std::uint32_t>(y + 0x7F4A) * 0x27D4EB2Du);
    v ^= v >> 16;
    v *= 0x7FEB352Du;
    v ^= v >> 15;
    v *= 0x846CA68Bu;
    v ^= v >> 16;
    int value = 24 + static_cast<int>(v % 208u);
    value += (((x / 8) + (y / 8)) & 1) ? 36 : -36;
    value = std::max(0, std::min(255, value));
    return static_cast<std::uint8_t>(value);
}

cv::Mat render(int stereo_offset_px) {
    cv::Mat image(kHeight, kWidth, CV_8UC1);
    for (int y = 0; y < image.rows; ++y) {
        for (int x = 0; x < image.cols; ++x) {
            image.at<std::uint8_t>(y, x) = texture(x + stereo_offset_px, y);
        }
    }
    return image;
}

bividi::ImageView view(const cv::Mat& image) {
    return bividi::ImageView{
        image.data,
        static_cast<std::size_t>(image.cols),
        static_cast<std::size_t>(image.rows),
        static_cast<std::size_t>(image.step),
        1,
        bividi::PixelFormat::gray8,
    };
}

bividi::depth::StereoDepthCalibration calibration() {
    bividi::depth::StereoDepthCalibration c;
    c.schema = "bividi.calibration.stereo.v1";
    c.calibration_id = "synthetic-depth-fixture-v1";
    c.evidence_kind = "synthetic";
    c.camera_a_identity = "camera_a";
    c.camera_b_identity = "camera_b";
    c.rectified_frame = "camera_a_rectified";
    c.width = kWidth;
    c.height = kHeight;
    c.baseline_m = 0.10;
    c.K_a = (cv::Mat_<double>(3, 3) <<
        80.0, 0.0, 47.5,
        0.0, 80.0, 31.5,
        0.0, 0.0, 1.0);
    c.K_b = c.K_a.clone();
    c.D_a = cv::Mat::zeros(1, 5, CV_64F);
    c.D_b = cv::Mat::zeros(1, 5, CV_64F);
    c.R1 = cv::Mat::eye(3, 3, CV_64F);
    c.R2 = cv::Mat::eye(3, 3, CV_64F);
    c.P1 = (cv::Mat_<double>(3, 4) <<
        80.0, 0.0, 47.5, 0.0,
        0.0, 80.0, 31.5, 0.0,
        0.0, 0.0, 1.0, 0.0);
    c.P2 = (cv::Mat_<double>(3, 4) <<
        80.0, 0.0, 47.5, -8.0,
        0.0, 80.0, 31.5, 0.0,
        0.0, 0.0, 1.0, 0.0);
    c.Q = (cv::Mat_<double>(4, 4) <<
        1.0, 0.0, 0.0, -47.5,
        0.0, 1.0, 0.0, -31.5,
        0.0, 0.0, 0.0, 80.0,
        0.0, 0.0, 10.0, 0.0);
    return c;
}

bividi::SensorCapabilities capabilities() {
    bividi::SensorCapabilities caps{};
    caps.cameras = {
        {"camera_a", "primary", bividi::PixelFormat::gray8,
         bividi::CameraModality::unknown, kWidth, kHeight},
        {"camera_b", "primary", bividi::PixelFormat::gray8,
         bividi::CameraModality::unknown, kWidth, kHeight},
    };
    caps.stereo_pairs = {{"stereo0", "camera_a", "camera_b"}};
    return caps;
}

bividi::FrameLease dummy_lease() {
    return bividi::FrameLease::adopt(new int(7), [](int* value) noexcept { delete value; });
}

bividi::SensorObservation make_stereo_observation(
    const cv::Mat& camera_a_image,
    const cv::Mat& camera_b_image,
    std::uint64_t sequence,
    bividi::ContinuityState continuity,
    std::uint64_t continuity_epoch,
    bividi::SynchronizationState synchronization = bividi::SynchronizationState::unknown) {
    bividi::SensorObservation observation{};
    observation.source_id = "synthetic:depth-observation-test";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.source_state = bividi::SourceState::available;
    observation.validity = bividi::ObservationValidity::valid;
    observation.sequence = sequence;
    observation.sequence_present = true;
    observation.continuity = continuity;
    observation.continuity_epoch = continuity_epoch;

    const auto lease = dummy_lease();

    bividi::CameraObservation a{};
    a.stream_id = "camera_a";
    a.lease = lease;
    a.image = view(camera_a_image);
    a.validity = bividi::ObservationValidity::valid;

    bividi::CameraObservation b{};
    b.stream_id = "camera_b";
    b.lease = lease;
    b.image = view(camera_b_image);
    b.validity = bividi::ObservationValidity::valid;

    observation.cameras = {a, b};
    observation.stereo_pairs.push_back({"stereo0", synchronization});
    return observation;
}

bividi::depth::StereoDepthConfig depth_config() {
    bividi::depth::StereoDepthConfig config;
    config.num_disparities = 16;
    config.block_size = 5;
    config.uniqueness_ratio = 5;
    config.speckle_window_size = 0;
    config.compute_xyz = true;
    return config;
}

float median(std::vector<float> values) {
    assert(!values.empty());
    const auto middle = values.begin() + static_cast<std::ptrdiff_t>(values.size() / 2);
    std::nth_element(values.begin(), middle, values.end());
    return *middle;
}

void assert_plane_geometry(const bividi::depth::StereoDepthResult& result) {
    std::vector<float> disparities;
    std::vector<float> depths;
    int candidate_pixels = 0;
    for (int y = 10; y < kHeight - 10; ++y) {
        for (int x = 20; x < kWidth - 10; ++x) {
            ++candidate_pixels;
            if (result.valid_mask.at<std::uint8_t>(y, x) == 0) continue;
            disparities.push_back(result.disparity_px.at<float>(y, x));
            depths.push_back(result.depth_m.at<float>(y, x));
        }
    }
    assert(static_cast<int>(disparities.size()) > candidate_pixels * 3 / 4);
    assert(std::abs(median(disparities) - 4.0f) < 0.25f);
    assert(std::abs(median(depths) - 2.0f) < 0.15f);
}

void test_exact_metric_geometry_and_invalid_preservation() {
    auto c = calibration();
    bividi::depth::validate_calibration(c);

    cv::Mat disparity(kHeight, kWidth, CV_32FC1, cv::Scalar(4.0f));
    cv::Mat mask(kHeight, kWidth, CV_8UC1, cv::Scalar(255));
    disparity.at<float>(7, 8) = std::numeric_limits<float>::quiet_NaN();
    mask.at<std::uint8_t>(7, 8) = 0;

    const auto geometry = bividi::depth::metric_geometry_from_disparity(disparity, mask, c, true);
    assert(geometry.depth_m.type() == CV_32FC1);
    assert(geometry.xyz_m.type() == CV_32FC3);
    assert(geometry.valid_mask.type() == CV_8UC1);

    // Z = 80 px * 0.10 m / 4 px = 2.0 m.
    assert(std::abs(geometry.depth_m.at<float>(32, 48) - 2.0f) < 1e-6f);
    const auto xyz = geometry.xyz_m.at<cv::Vec3f>(32, 48);
    assert(std::abs(xyz[0] - 0.0125f) < 1e-6f); // (48 - 47.5) * 2 / 80
    assert(std::abs(xyz[1] - 0.0125f) < 1e-6f); // (32 - 31.5) * 2 / 80
    assert(std::abs(xyz[2] - 2.0f) < 1e-6f);

    assert(geometry.valid_mask.at<std::uint8_t>(7, 8) == 0);
    assert(std::isnan(geometry.depth_m.at<float>(7, 8)));
    const auto invalid_xyz = geometry.xyz_m.at<cv::Vec3f>(7, 8);
    assert(std::isnan(invalid_xyz[0]) && std::isnan(invalid_xyz[1]) && std::isnan(invalid_xyz[2]));
}

void test_rectify_sgbm_depth_xyz_vertical_slice() {
    auto c = calibration();
    bividi::depth::StereoDepthProcessor processor(c, depth_config());
    const cv::Mat camera_a = render(0);
    const cv::Mat camera_b = render(kDisparity);
    const auto result = processor.process(view(camera_a), view(camera_b));

    assert(result.calibration_id == "synthetic-depth-fixture-v1");
    assert(result.coordinate_frame == "camera_a_rectified");
    assert(result.rectified_a.size() == camera_a.size());
    assert(result.rectified_b.size() == camera_b.size());
    assert(result.disparity_px.type() == CV_32FC1);
    assert(result.depth_m.type() == CV_32FC1);
    assert(result.xyz_m.type() == CV_32FC3);
    assert_plane_geometry(result);

    const cv::Mat disparity_preview = bividi::depth::disparity_preview_u8(result);
    const cv::Mat depth_preview = bividi::depth::depth_preview_u8(result);
    assert(disparity_preview.type() == CV_8UC1);
    assert(depth_preview.type() == CV_8UC1);
    assert(disparity_preview.size() == camera_a.size());
    assert(depth_preview.size() == camera_a.size());
}

void test_observation_adapter_processes_normalized_pair_without_upgrading_unknown_sync() {
    const cv::Mat camera_a = render(0);
    const cv::Mat camera_b = render(kDisparity);
    bividi::depth::StereoDepthObservationProcessor processor(
        capabilities(), "stereo0", calibration(), depth_config());

    const auto observation = make_stereo_observation(
        camera_a,
        camera_b,
        1000,
        bividi::ContinuityState::reinitialized,
        0,
        bividi::SynchronizationState::unknown);
    const auto result = processor.process(observation);

    assert(result.processed());
    assert(result.source_id == observation.source_id);
    assert(result.evidence == bividi::EvidenceKind::synthetic);
    assert(result.sequence_present && result.sequence == 1000);
    assert(result.pair_id == "stereo0");
    assert(result.synchronization == bividi::SynchronizationState::unknown);
    assert(result.calibration_id == "synthetic-depth-fixture-v1");
    assert(result.reset_before_process);
    assert(result.reset_generation == 1);
    assert(result.depth.calibration_id == result.calibration_id);
    assert_plane_geometry(result.depth);
}

void test_observation_adapter_missing_camera_creates_no_depth_and_resets_recovery() {
    const cv::Mat camera_a = render(0);
    const cv::Mat camera_b = render(kDisparity);
    bividi::depth::StereoDepthObservationProcessor processor(
        capabilities(), "stereo0", calibration(), depth_config());

    auto first = make_stereo_observation(
        camera_a, camera_b, 10, bividi::ContinuityState::reinitialized, 0);
    assert(processor.process(first).processed());

    auto missing = make_stereo_observation(
        camera_a, camera_b, 11, bividi::ContinuityState::continuous, 0);
    missing.cameras.pop_back();
    const auto rejected = processor.process(missing);
    assert(!rejected.processed());
    assert(rejected.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_camera_missing);
    assert(rejected.depth.depth_m.empty());
    assert(rejected.depth.disparity_px.empty());

    auto recovered = make_stereo_observation(
        camera_a, camera_b, 12, bividi::ContinuityState::continuous, 0);
    const auto recovery_result = processor.process(recovered);
    assert(recovery_result.processed());
    assert(recovery_result.reset_before_process);
    assert(recovery_result.reset_generation == 2);
}

void test_observation_adapter_sync_and_calibration_gates() {
    const cv::Mat camera_a = render(0);
    const cv::Mat camera_b = render(kDisparity);

    bividi::depth::StereoDepthObservationProcessor processor(
        capabilities(), "stereo0", calibration(), depth_config());
    auto unsynchronized = make_stereo_observation(
        camera_a,
        camera_b,
        20,
        bividi::ContinuityState::reinitialized,
        0,
        bividi::SynchronizationState::unsynchronized);
    const auto unsync_result = processor.process(unsynchronized);
    assert(!unsync_result.processed());
    assert(unsync_result.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_synchronization);
    assert(unsync_result.depth.depth_m.empty());

    bividi::depth::StereoDepthObservationPolicy strict_sync{};
    strict_sync.allow_unknown_synchronization = false;
    bividi::depth::StereoDepthObservationProcessor strict_processor(
        capabilities(), "stereo0", calibration(), depth_config(), strict_sync);
    auto unknown = make_stereo_observation(
        camera_a,
        camera_b,
        30,
        bividi::ContinuityState::reinitialized,
        0,
        bividi::SynchronizationState::unknown);
    const auto unknown_result = strict_processor.process(unknown);
    assert(!unknown_result.processed());
    assert(unknown_result.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_synchronization);

    bividi::depth::StereoDepthObservationProcessor calibration_processor(
        capabilities(), "stereo0", calibration(), depth_config());
    auto wrong_calibration = make_stereo_observation(
        camera_a, camera_b, 40, bividi::ContinuityState::reinitialized, 0);
    wrong_calibration.calibration.stereo = "different-calibration";
    const auto calibration_result = calibration_processor.process(wrong_calibration);
    assert(!calibration_result.processed());
    assert(calibration_result.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_calibration_identity);
    assert(calibration_result.depth.xyz_m.empty());
}

void test_observation_adapter_sequence_and_continuity_reset_semantics() {
    const cv::Mat camera_a = render(0);
    const cv::Mat camera_b = render(kDisparity);
    bividi::depth::StereoDepthObservationProcessor processor(
        capabilities(), "stereo0", calibration(), depth_config());

    auto first = make_stereo_observation(
        camera_a, camera_b, 100, bividi::ContinuityState::reinitialized, 0);
    const auto first_result = processor.process(first);
    assert(first_result.processed());
    assert(first_result.reset_generation == 1);

    auto second = make_stereo_observation(
        camera_a, camera_b, 101, bividi::ContinuityState::continuous, 0);
    const auto second_result = processor.process(second);
    assert(second_result.processed());
    assert(!second_result.reset_before_process);

    auto duplicate = make_stereo_observation(
        camera_a, camera_b, 101, bividi::ContinuityState::continuous, 0);
    const auto duplicate_result = processor.process(duplicate);
    assert(!duplicate_result.processed());
    assert(duplicate_result.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_sequence_non_monotonic);

    auto recovered = make_stereo_observation(
        camera_a, camera_b, 102, bividi::ContinuityState::continuous, 0);
    const auto recovered_result = processor.process(recovered);
    assert(recovered_result.processed());
    assert(recovered_result.reset_before_process);
    assert(recovered_result.reset_generation == 2);

    auto gap = make_stereo_observation(
        camera_a, camera_b, 104, bividi::ContinuityState::continuous, 0);
    const auto gap_result = processor.process(gap);
    assert(gap_result.processed());
    assert(gap_result.sequence_gap_detected);
    assert(gap_result.reset_before_process);
    assert(gap_result.reset_generation == 3);

    auto new_epoch = make_stereo_observation(
        camera_a, camera_b, 105, bividi::ContinuityState::discontinuity, 1);
    const auto epoch_result = processor.process(new_epoch);
    assert(epoch_result.processed());
    assert(epoch_result.reset_before_process);
    assert(epoch_result.reset_generation == 4);
}

void test_bad_configuration_and_geometry_are_rejected() {
    auto c = calibration();
    auto bad = c;
    bad.baseline_m = 0.2;
    bool rejected = false;
    try {
        bividi::depth::validate_calibration(bad);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected); // baseline conflicts with P2 projection geometry

    bividi::depth::StereoDepthConfig bad_config;
    bad_config.num_disparities = 15;
    rejected = false;
    try {
        bividi::depth::validate_config(bad_config);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    bividi::depth::StereoDepthConfig config;
    config.num_disparities = 16;
    bividi::depth::StereoDepthProcessor processor(c, config);
    cv::Mat camera_a = render(0);
    cv::Mat camera_b = render(kDisparity).rowRange(0, kHeight - 1);
    rejected = false;
    try {
        (void)processor.process(view(camera_a), view(camera_b));
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    auto bad_caps = capabilities();
    bad_caps.cameras[1].width = kWidth - 1;
    rejected = false;
    try {
        bividi::depth::StereoDepthObservationProcessor observation_processor(
            bad_caps, "stereo0", calibration(), depth_config());
        (void)observation_processor;
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

}  // namespace

int main() {
    test_exact_metric_geometry_and_invalid_preservation();
    test_rectify_sgbm_depth_xyz_vertical_slice();
    test_observation_adapter_processes_normalized_pair_without_upgrading_unknown_sync();
    test_observation_adapter_missing_camera_creates_no_depth_and_resets_recovery();
    test_observation_adapter_sync_and_calibration_gates();
    test_observation_adapter_sequence_and_continuity_reset_semantics();
    test_bad_configuration_and_geometry_are_rejected();
    std::cout << "bividi depth reference tests: PASS\n";
    return 0;
}
