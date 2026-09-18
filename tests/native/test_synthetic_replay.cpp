#include "bividi/observation.hpp"
#include "bividi/observation_source.hpp"
#include "bividi/replay.hpp"
#include "bividi/replay_session.hpp"

#include <cassert>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

const bividi::CameraObservation& require_camera(
    const bividi::SensorObservation& observation,
    const std::string& stream_id) {
    for (const auto& camera : observation.cameras) {
        if (camera.stream_id == stream_id) return camera;
    }
    throw std::runtime_error("missing expected synthetic camera stream: " + stream_id);
}

void test_replay_capture_session_observation_snapshot(const std::filesystem::path& session_dir) {
    bividi::SensorObservation retained;
    {
        bividi::ReplaySessionConfig config{};
        config.session_dir = session_dir;
        config.rate = 1000.0;
        bividi::ReplayCaptureSession session(config);

        // The normalized tap is deliberately separate from CaptureSession. A
        // downstream consumer must opt into ObservationSnapshotSource rather
        // than treating the BGR engineering preview as sensor evidence.
        bividi::ObservationSnapshotSource& source = session;
        const auto& caps = source.observation_capabilities();
        assert(caps.cameras.size() == 2);
        assert(caps.stereo_pairs.size() == 1);
        assert(caps.cameras[0].pixel_format == bividi::PixelFormat::gray8);

        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (!source.latest_observation(retained) &&
               std::chrono::steady_clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
        assert(retained.sequence_present);
        assert(retained.sequence >= 1000 && retained.sequence <= 1002);
        assert(retained.evidence == bividi::EvidenceKind::synthetic);
        assert(retained.cameras.size() == 2);

        const auto conformance = bividi::validate_observation(retained, &caps);
        assert(conformance.ok);
    }

    // The copied SensorObservation owns the source frame lifetime through its
    // FrameLease copies; destroying the UI/session adapter must not invalidate
    // the normalized snapshot handed to a downstream processor.
    const auto& camera_a = require_camera(retained, "camera_a");
    const auto& camera_b = require_camera(retained, "camera_b");
    assert(camera_a.lease.valid());
    assert(camera_b.lease.valid());
    assert(!camera_a.image.empty());
    assert(!camera_b.image.empty());
    assert(camera_a.image.data[0] == camera_a.image.data[0]);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: bividi_synthetic_replay_tests SESSION_DIR\n";
        return 2;
    }

    const std::filesystem::path session_dir(argv[1]);

    bividi::ReplayConfig config{};
    config.session_dir = session_dir;
    config.pacing = bividi::ReplayPacing::step;
    bividi::ReplaySource replay(config);

    assert(replay.size() == 3);
    assert(replay.metadata().evidence == bividi::EvidenceKind::synthetic);
    assert(replay.metadata().product == "Bividi Synthetic SensorRig");
    assert(replay.metadata().frame_stride == 1);

    const auto& caps = replay.capabilities();
    assert(caps.cameras.size() == 2);
    assert(caps.stereo_pairs.size() == 1);
    assert(caps.cameras[0].width == 96);
    assert(caps.cameras[0].height == 64);
    assert(caps.cameras[0].pixel_format == bividi::PixelFormat::gray8);
    assert(caps.cameras[1].pixel_format == bividi::PixelFormat::gray8);
    assert(caps.imu);
    assert(caps.timing.exposure_start_end);
    assert(caps.timing.imu_sample_time);

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(observation.evidence == bividi::EvidenceKind::synthetic);
    assert(observation.sequence_present && observation.sequence == 1000);
    assert(observation.continuity == bividi::ContinuityState::reinitialized);
    assert(observation.cameras.size() == 2);
    assert(!observation.imu.empty());

    const auto& camera_a = require_camera(observation, "camera_a");
    const auto& camera_b = require_camera(observation, "camera_b");
    assert(camera_a.image.pixel_format == bividi::PixelFormat::gray8);
    assert(camera_b.image.pixel_format == bividi::PixelFormat::gray8);
    assert(camera_a.image.width == 96 && camera_a.image.height == 64);
    assert(camera_b.image.width == 96 && camera_b.image.height == 64);

    // The checked-in generator's static fixture is deliberately exact:
    // fx=80 px, baseline=0.10 m, plane Z=2.0 m -> disparity=4 px.
    constexpr std::size_t disparity = 4;
    for (std::size_t y = 0; y < camera_a.image.height; ++y) {
        const auto* row_a = camera_a.image.data + y * camera_a.image.row_stride;
        const auto* row_b = camera_b.image.data + y * camera_b.image.row_stride;
        for (std::size_t x_b = 0; x_b + disparity < camera_b.image.width; ++x_b) {
            assert(row_b[x_b] == row_a[x_b + disparity]);
        }
    }

    assert(camera_a.exposure.start.present);
    assert(camera_a.exposure.end.present);
    assert(camera_a.exposure.start.ticks == 1000000ULL);
    assert(camera_a.exposure.end.ticks == 1005000ULL);
    assert(camera_a.exposure.raw_start.present);
    assert(camera_a.exposure.raw_start.raw_ticks == 1000000ULL);
    assert(camera_a.exposure.raw_start.bit_width == 32);

    // The v1 synthetic fixture declares zero camera↔IMU time offset and assigns
    // the first IMU sample to the exposure-start device timestamp.
    const auto& first_imu = observation.imu.front();
    assert(first_imu.sample_time.present);
    assert(first_imu.sample_time.ticks == camera_a.exposure.start.ticks);
    assert(first_imu.raw_time.present);
    assert(first_imu.raw_time.raw_ticks == first_imu.sample_time.ticks);
    assert(first_imu.raw_time.bit_width == 32);
    assert(first_imu.raw_valid);
    assert(!first_imu.si_valid);
    assert(first_imu.accel_raw_counts[0] == 0);
    assert(first_imu.accel_raw_counts[1] == 0);
    assert(first_imu.accel_raw_counts[2] == 16384);
    assert(first_imu.gyro_raw_counts[0] == 0);
    assert(first_imu.gyro_raw_counts[1] == 0);
    assert(first_imu.gyro_raw_counts[2] == 0);

    const auto conformance = bividi::validate_observation(observation, &caps);
    if (!conformance.ok) {
        for (const auto& error : conformance.errors) {
            std::cerr << error << '\n';
        }
        return 1;
    }

    bividi::SensorObservation second;
    assert(replay.next(second));
    assert(second.evidence == bividi::EvidenceKind::synthetic);
    assert(second.sequence_present && second.sequence == 1001);
    assert(second.continuity == bividi::ContinuityState::continuous);

    test_replay_capture_session_observation_snapshot(session_dir);

    std::cout << "synthetic SensorRig native replay conformance: PASS\n";
    return 0;
}
