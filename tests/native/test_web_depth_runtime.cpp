#include "bividi/depth.hpp"
#include "bividi/depth_snapshot.hpp"
#include "bividi/replay_session.hpp"
#include "bividi_web_depth.hpp"

#include <algorithm>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
namespace fs = std::filesystem;

constexpr int kWidth = 96;
constexpr int kHeight = 64;

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

bividi::SensorObservation wait_for_first_observation(bividi::ReplayCaptureSession& session) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (std::chrono::steady_clock::now() < deadline) {
        bividi::SensorObservation observation;
        if (session.latest_observation(observation)) return observation;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    throw std::runtime_error("timed out waiting for replay observation");
}

bividi::depth::StereoDepthConfig deterministic_depth_config() {
    bividi::depth::StereoDepthConfig config{};
    config.num_disparities = 16;
    config.block_size = 5;
    config.uniqueness_ratio = 5;
    config.speckle_window_size = 0;
    config.compute_xyz = false;
    return config;
}

std::uint64_t json_u64(const std::string& json, const std::string& key) {
    const std::string needle = "\"" + key + "\":";
    const auto begin = json.find(needle);
    if (begin == std::string::npos) throw std::runtime_error("missing JSON key: " + key);
    const auto value_begin = begin + needle.size();
    std::size_t used = 0;
    const auto value = std::stoull(json.substr(value_begin), &used, 10);
    if (used == 0) throw std::runtime_error("invalid JSON integer: " + key);
    return value;
}

void require_json_fragment(const std::string& json, const std::string& fragment) {
    if (json.find(fragment) == std::string::npos) {
        throw std::runtime_error("missing JSON fragment: " + fragment + " in " + json);
    }
}

void assert_jpeg(const std::vector<unsigned char>& bytes) {
    assert(bytes.size() > 100);
    assert(bytes[0] == 0xff && bytes[1] == 0xd8);
    assert(bytes[bytes.size() - 2] == 0xff && bytes[bytes.size() - 1] == 0xd9);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: bividi_web_depth_runtime_tests SESSION_DIR CALIBRATION_JSON\n";
        return 2;
    }

    const fs::path session_dir = argv[1];
    const std::string calibration_path = argv[2];
    const auto calibration = bividi::depth::load_calibration_json(calibration_path);
    assert(calibration.calibration_id == "synthetic-depth-fixture-v1");
    assert(calibration.evidence_kind == "synthetic");
    assert(calibration.width == kWidth && calibration.height == kHeight);
    assert(std::abs(calibration.baseline_m - 0.10) < 1e-12);

    // Publish frame 1000 immediately, then make the next 30 Hz source frame take
    // ~33 seconds. This freezes the latest snapshot long enough to deterministically
    // exercise independent HTTP-style status/disparity/depth reads without racing
    // replay chronology.
    bividi::ReplaySessionConfig replay_config{};
    replay_config.session_dir = session_dir;
    replay_config.rate = 0.001;
    bividi::ReplayCaptureSession replay(std::move(replay_config));

    const auto first_observation = wait_for_first_observation(replay);
    assert(first_observation.evidence == bividi::EvidenceKind::synthetic);
    assert(first_observation.sequence_present && first_observation.sequence == 1000);
    assert(first_observation.stereo_pairs.size() == 1);
    assert(first_observation.stereo_pairs[0].pair_id == "stereo0");
    assert(first_observation.stereo_pairs[0].synchronization ==
           bividi::SynchronizationState::unknown);

    // First prove that the exact replay snapshot reaches the numeric #9 geometry
    // boundary with the synthetic ground truth: disparity=4 px and Z=2 m.
    bividi::depth::StereoDepthSnapshotProcessor numeric_consumer(
        replay,
        "stereo0",
        calibration,
        deterministic_depth_config());

    bividi::depth::StereoDepthSnapshot numeric_first;
    assert(numeric_consumer.latest(numeric_first));
    assert(numeric_first.result.processed());
    assert(numeric_first.revision == 1);
    assert(numeric_first.result.sequence_present && numeric_first.result.sequence == 1000);
    assert(numeric_first.result.synchronization == bividi::SynchronizationState::unknown);
    assert(numeric_first.result.reset_before_process);
    assert(numeric_first.result.reset_generation == 1);
    assert(numeric_first.valid_fraction > 0.50);
    assert_plane_geometry(numeric_first.result.depth);

    // Re-reading the same normalized source snapshot must hit the cache instead
    // of manufacturing a duplicate-sequence chronology fault.
    bividi::depth::StereoDepthSnapshot numeric_again;
    assert(numeric_consumer.latest(numeric_again));
    assert(numeric_again.result.processed());
    assert(numeric_again.revision == numeric_first.revision);
    assert(numeric_again.result.disposition == numeric_first.result.disposition);

    // Exercise the browser-facing service in the same pattern as independent
    // /api/depth/status, /disparity.jpg, and /depth.jpg requests.
    bividi_web::DepthPreviewService web_depth(replay, "stereo0", calibration);
    const auto status_before = web_depth.status_json();
    require_json_fragment(status_before, "\"enabled\":true");
    require_json_fragment(status_before, "\"observation_available\":true");
    require_json_fragment(status_before, "\"processed\":true");
    require_json_fragment(status_before, "\"sequence\":1000");
    require_json_fragment(status_before, "\"synchronization\":\"unknown\"");
    require_json_fragment(status_before, "\"calibration_id\":\"synthetic-depth-fixture-v1\"");
    require_json_fragment(status_before, "\"pair_id\":\"stereo0\"");
    require_json_fragment(status_before, "\"disposition\":\"processed\"");
    const auto web_revision = json_u64(status_before, "revision");
    assert(web_revision == 1);

    const auto disparity_jpeg = web_depth.image_jpeg(false);
    const auto depth_jpeg = web_depth.image_jpeg(true);
    assert_jpeg(disparity_jpeg);
    assert_jpeg(depth_jpeg);

    const auto status_after = web_depth.status_json();
    assert(json_u64(status_after, "revision") == web_revision);
    require_json_fragment(status_after, "\"processed\":true");
    assert(status_after.find("rejected_sequence_non_monotonic") == std::string::npos);
    assert(status_after.find("processing_error") == std::string::npos);

    std::cout << "web depth runtime regression: PASS\n"
              << "sequence=1000 disparity~=4px depth~=2m revision=" << web_revision
              << " sync=unknown\n";
    return 0;
}
