#include "bividi/depth_observation.hpp"
#include "bividi/replay.hpp"
#include "bividi/replay_faults.hpp"

#include <opencv2/core.hpp>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;

constexpr int kWidth = 96;
constexpr int kHeight = 64;

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

bividi::ReplaySource make_replay(const fs::path& session_dir) {
    bividi::ReplayConfig config{};
    config.session_dir = session_dir;
    config.pacing = bividi::ReplayPacing::step;
    return bividi::ReplaySource(config);
}

bividi::depth::StereoDepthObservationProcessor make_depth_consumer(
    const bividi::SensorCapabilities& capabilities) {
    return bividi::depth::StereoDepthObservationProcessor(
        capabilities,
        "stereo0",
        calibration(),
        depth_config());
}

bividi::ReplayFaultRule remove_camera_rule(std::size_t position) {
    bividi::ReplayFaultRule rule{};
    rule.id = "remove-camera-b";
    rule.at_source_position = position;
    rule.action = bividi::ReplayFaultAction::remove_camera;
    rule.expected = bividi::ReplayFaultExpectedDisposition::consumer_reject;
    rule.stream_id = "camera_b";
    return rule;
}

bividi::ReplayFaultRule unsynchronized_rule(std::size_t position) {
    bividi::ReplayFaultRule rule{};
    rule.id = "unsynchronized-stereo";
    rule.at_source_position = position;
    rule.action = bividi::ReplayFaultAction::set_stereo_synchronization;
    rule.expected = bividi::ReplayFaultExpectedDisposition::consumer_reject;
    rule.pair_id = "stereo0";
    rule.synchronization = bividi::SynchronizationState::unsynchronized;
    return rule;
}

bividi::ReplayFaultRule duplicate_rule(std::size_t position) {
    bividi::ReplayFaultRule rule{};
    rule.id = "duplicate-observation";
    rule.at_source_position = position;
    rule.action = bividi::ReplayFaultAction::duplicate;
    rule.expected = bividi::ReplayFaultExpectedDisposition::consumer_reject;
    rule.copies = 1;
    return rule;
}

bividi::ReplayFaultRule continuity_rule(std::size_t position) {
    bividi::ReplayFaultRule rule{};
    rule.id = "new-continuity-epoch";
    rule.at_source_position = position;
    rule.action = bividi::ReplayFaultAction::set_continuity;
    rule.expected = bividi::ReplayFaultExpectedDisposition::reset_derived_pipeline;
    rule.continuity = bividi::ContinuityState::discontinuity;
    rule.delta = 1;
    return rule;
}

bividi::InterceptedReplaySource make_fault_replay(
    const fs::path& session_dir,
    bividi::ReplayFaultRule rule,
    std::shared_ptr<bividi::RecipeReplayInterceptor>& interceptor_out) {
    bividi::ReplayFaultRecipe recipe{};
    recipe.schema = bividi::kReplayFaultRecipeLatestSchema;
    recipe.seed = 0xB1D1D1u;
    recipe.rules.push_back(std::move(rule));
    bividi::validate_replay_fault_recipe(recipe);

    interceptor_out = std::make_shared<bividi::RecipeReplayInterceptor>(std::move(recipe));
    return bividi::InterceptedReplaySource(make_replay(session_dir), interceptor_out);
}

void test_clean_replay_reaches_metric_depth(const fs::path& session_dir) {
    auto replay = make_replay(session_dir);
    assert(replay.metadata().evidence == bividi::EvidenceKind::synthetic);
    assert(replay.capabilities().stereo_pairs.size() == 1);

    auto depth = make_depth_consumer(replay.capabilities());

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(observation.sequence_present && observation.sequence == 1000);
    assert(observation.continuity == bividi::ContinuityState::reinitialized);
    assert(observation.stereo_pairs.size() == 1);
    assert(observation.stereo_pairs[0].synchronization == bividi::SynchronizationState::unknown);

    const auto first = depth.process(observation);
    assert(first.processed());
    assert(first.evidence == bividi::EvidenceKind::synthetic);
    assert(first.synchronization == bividi::SynchronizationState::unknown);
    assert(first.reset_before_process);
    assert(first.reset_generation == 1);
    assert(first.depth.calibration_id == "synthetic-depth-fixture-v1");
    assert_plane_geometry(first.depth);

    assert(replay.next(observation));
    const auto second = depth.process(observation);
    assert(second.processed());
    assert(!second.reset_before_process);
    assert(second.reset_generation == 1);
    assert_plane_geometry(second.depth);
}

void test_remove_camera_fault_rejects_and_recovery_resets(const fs::path& session_dir) {
    std::shared_ptr<bividi::RecipeReplayInterceptor> interceptor;
    auto replay = make_fault_replay(session_dir, remove_camera_rule(1), interceptor);
    auto depth = make_depth_consumer(replay.capabilities());

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(depth.process(observation).processed());

    assert(replay.next(observation));
    const auto missing = depth.process(observation);
    assert(!missing.processed());
    assert(missing.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_camera_missing);
    assert(missing.depth.disparity_px.empty());
    assert(missing.depth.depth_m.empty());
    assert(missing.depth.xyz_m.empty());

    assert(replay.next(observation));
    const auto recovered = depth.process(observation);
    assert(recovered.processed());
    assert(recovered.reset_before_process);
    assert(recovered.reset_generation == 2);
    assert_plane_geometry(recovered.depth);

    const auto stats = interceptor->stats();
    assert(stats.triggered_rules == 1);
    assert(stats.source_observations == 3);
}

void test_unsynchronized_fault_rejects_and_recovery_resets(const fs::path& session_dir) {
    std::shared_ptr<bividi::RecipeReplayInterceptor> interceptor;
    auto replay = make_fault_replay(session_dir, unsynchronized_rule(1), interceptor);
    auto depth = make_depth_consumer(replay.capabilities());

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(depth.process(observation).processed());

    assert(replay.next(observation));
    const auto unsynchronized = depth.process(observation);
    assert(!unsynchronized.processed());
    assert(unsynchronized.synchronization == bividi::SynchronizationState::unsynchronized);
    assert(unsynchronized.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_synchronization);
    assert(unsynchronized.depth.depth_m.empty());

    assert(replay.next(observation));
    const auto recovered = depth.process(observation);
    assert(recovered.processed());
    assert(recovered.reset_before_process);
    assert(recovered.reset_generation == 2);
    assert(recovered.synchronization == bividi::SynchronizationState::unknown);
}

void test_duplicate_fault_rejects_second_derived_result(const fs::path& session_dir) {
    std::shared_ptr<bividi::RecipeReplayInterceptor> interceptor;
    auto replay = make_fault_replay(session_dir, duplicate_rule(1), interceptor);
    auto depth = make_depth_consumer(replay.capabilities());

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(observation.sequence == 1000);
    assert(depth.process(observation).processed());

    assert(replay.next(observation));
    assert(observation.sequence == 1001);
    const auto first_copy = depth.process(observation);
    assert(first_copy.processed());

    assert(replay.next(observation));
    assert(observation.sequence == 1001);
    const auto duplicate = depth.process(observation);
    assert(!duplicate.processed());
    assert(duplicate.disposition ==
           bividi::depth::StereoDepthObservationDisposition::rejected_sequence_non_monotonic);
    assert(duplicate.depth.depth_m.empty());

    assert(replay.next(observation));
    assert(observation.sequence == 1002);
    const auto recovered = depth.process(observation);
    assert(recovered.processed());
    assert(recovered.reset_before_process);
    assert(recovered.reset_generation == 2);

    const auto stats = interceptor->stats();
    assert(stats.triggered_rules == 1);
    assert(stats.emitted_observations == 4);
}

void test_continuity_fault_resets_before_depth(const fs::path& session_dir) {
    std::shared_ptr<bividi::RecipeReplayInterceptor> interceptor;
    auto replay = make_fault_replay(session_dir, continuity_rule(1), interceptor);
    auto depth = make_depth_consumer(replay.capabilities());

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    const auto first = depth.process(observation);
    assert(first.processed());
    assert(first.reset_generation == 1);

    assert(replay.next(observation));
    assert(observation.continuity == bividi::ContinuityState::discontinuity);
    assert(observation.continuity_epoch == 1);
    const auto discontinuity = depth.process(observation);
    assert(discontinuity.processed());
    assert(discontinuity.reset_before_process);
    assert(discontinuity.reset_generation == 2);
    assert_plane_geometry(discontinuity.depth);

    // The interceptor does not rewrite later source evidence. Returning to the
    // recorded epoch is another explicit epoch mismatch and therefore another
    // derived-stream reset, not silent continuity repair.
    assert(replay.next(observation));
    assert(observation.continuity == bividi::ContinuityState::continuous);
    assert(observation.continuity_epoch == 0);
    const auto return_to_recorded_epoch = depth.process(observation);
    assert(return_to_recorded_epoch.processed());
    assert(return_to_recorded_epoch.reset_before_process);
    assert(return_to_recorded_epoch.reset_generation == 3);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: bividi_depth_replay_integration_tests SESSION_DIR\n";
        return 2;
    }

    const fs::path session_dir(argv[1]);
    if (!fs::is_directory(session_dir)) {
        throw std::runtime_error("synthetic session directory does not exist: " + session_dir.string());
    }

    test_clean_replay_reaches_metric_depth(session_dir);
    test_remove_camera_fault_rejects_and_recovery_resets(session_dir);
    test_unsynchronized_fault_rejects_and_recovery_resets(session_dir);
    test_duplicate_fault_rejects_second_derived_result(session_dir);
    test_continuity_fault_resets_before_depth(session_dir);

    std::cout << "synthetic replay -> normalized observation -> depth/fault integration: PASS\n";
    return 0;
}
