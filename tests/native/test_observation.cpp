#include "bividi/decxin_observation.hpp"
#include "bividi/nori_session.hpp"
#include "bividi/observation.hpp"
#include "bividi/observation_source.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <type_traits>
#include <vector>

namespace {

static_assert(
    std::is_base_of_v<bividi::ObservationSnapshotSource, bividi::nori::NoriCaptureSession>,
    "live Nori session must expose the normalized observation snapshot boundary");

bividi::SensorCapabilities stereo_imu_capabilities() {
    bividi::SensorCapabilities caps{};
    caps.cameras = {
        {"camera_a", "primary", bividi::PixelFormat::bgr24, bividi::CameraModality::unknown, 4, 2},
        {"camera_b", "primary", bividi::PixelFormat::bgr24, bividi::CameraModality::unknown, 4, 2},
    };
    caps.stereo_pairs = {{"stereo0", "camera_a", "camera_b"}};
    caps.imu = true;
    // DECXIN exposure start/end are explicit. The generic visual frame-time
    // reference remains unset until a consumer/calibration path chooses ES,
    // midpoint, EE, or another documented convention.
    caps.timing.device_frame_time = false;
    caps.timing.exposure_start_end = true;
    caps.timing.imu_sample_time = true;
    caps.trigger_modes = {bividi::TriggerMode::free_run, bividi::TriggerMode::software};
    return caps;
}

void test_nori_normalized_source_defaults_do_not_claim_sync_or_calibration() {
    bividi::nori::NoriSessionConfig config{};
    assert(config.evidence == bividi::EvidenceKind::measured);
    assert(config.calibration.stereo.empty());
    assert(config.calibration.imu.empty());
    assert(config.calibration.camera_imu.empty());
    assert(config.configuration_revision.empty());
}

void test_capability_validation() {
    auto caps = stereo_imu_capabilities();
    assert(bividi::validate_capabilities(caps).ok);
    assert(caps.find_camera("camera_a") != nullptr);
    assert(caps.find_stereo_pair("stereo0") != nullptr);

    caps.cameras.push_back(caps.cameras.front());
    const auto duplicate = bividi::validate_capabilities(caps);
    assert(!duplicate.ok);
}

void test_clock_domains_remain_distinct() {
    bividi::SensorObservation observation{};
    observation.source_id = "synthetic:test";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.validity = bividi::ObservationValidity::invalid;
    observation.timing.host_receive = {
        100,
        bividi::TimeUnit::nanoseconds,
        bividi::ClockDomain::host_monotonic,
        "host.steady_clock",
        true,
    };
    observation.timing.replay_schedule = {
        50,
        bividi::TimeUnit::microseconds,
        bividi::ClockDomain::replay,
        "replay.timeline",
        true,
    };

    const auto result = bividi::validate_observation(observation);
    assert(result.ok);
    assert(observation.timing.host_receive.domain != observation.timing.replay_schedule.domain);
}

void test_decxin_normalization() {
    struct Storage {
        std::vector<std::uint8_t> pixels;
    };

    int releases = 0;
    auto* storage = new Storage{{
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
        13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
        37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48,
    }};
    auto lease = bividi::FrameLease::adopt(
        storage,
        [&releases](Storage* value) noexcept {
            ++releases;
            delete value;
        });

    bividi::decxin::DecodedFrame decoded{};
    decoded.lease = lease;
    decoded.camera_a = {
        storage->pixels.data(), 4, 2, 12, 3, bividi::PixelFormat::bgr24};
    decoded.camera_b = {
        storage->pixels.data() + 24, 4, 2, 12, 3, bividi::PixelFormat::bgr24};
    decoded.sequence = 42;
    decoded.host_receive_monotonic_ns = 123456789;
    decoded.timing.header.exposure_start_raw_us = 1000;
    decoded.timing.header.exposure_end_raw_us = 1100;
    decoded.timing.exposure_start_us = 1000;
    decoded.timing.exposure_end_us = 1100;

    bividi::decxin::ImuSample raw{};
    raw.raw_time_us = 1050;
    raw.extended_time_us = 1050;
    raw.accel_raw = {{1, -2, 3}};
    raw.gyro_raw = {{4, -5, 6}};
    raw.valid = true;
    decoded.timing.imu_samples.push_back(raw);

    bividi::decxin::ObservationContext context{};
    context.source_id = "decxin:test";
    context.evidence = bividi::EvidenceKind::synthetic;
    context.continuity_epoch = 7;
    context.calibration.stereo = "stereo-synthetic-v1";
    context.configuration_revision = "config-test";

    auto observation = bividi::decxin::to_sensor_observation(decoded, context);
    assert(observation.contract_version == bividi::kObservationContractVersion);
    assert(observation.source_id == "decxin:test");
    assert(observation.evidence == bividi::EvidenceKind::synthetic);
    assert(observation.sequence_present);
    assert(observation.sequence == 42);
    assert(observation.continuity_epoch == 7);
    assert(observation.timing.host_receive.present);
    assert(observation.timing.host_receive.domain == bividi::ClockDomain::host_monotonic);
    assert(observation.timing.host_receive.unit == bividi::TimeUnit::nanoseconds);
    assert(observation.cameras.size() == 2);
    assert(!observation.cameras[0].frame_time.present);
    assert(observation.cameras[0].exposure.start.domain == bividi::ClockDomain::device);
    assert(observation.cameras[0].exposure.start.unit == bividi::TimeUnit::microseconds);
    assert(observation.cameras[0].exposure.raw_start.bit_width == 32);
    assert(observation.stereo_pairs.size() == 1);
    assert(observation.stereo_pairs[0].pair_id == "stereo0");
    assert(observation.stereo_pairs[0].synchronization == bividi::SynchronizationState::unknown);
    assert(observation.imu.size() == 1);
    assert(observation.imu[0].raw_valid);
    assert(!observation.imu[0].si_valid);
    assert(observation.imu[0].accel_raw_counts[1] == -2);
    assert(observation.imu[0].gyro_raw_counts[2] == 6);

    const auto caps = stereo_imu_capabilities();
    const auto result = bividi::validate_observation(observation, &caps);
    assert(result.ok);

    decoded.lease.reset();
    lease.reset();
    assert(releases == 0);
    observation.cameras.clear();
    assert(releases == 1);
}

void test_conformance_rejects_wrong_topology_and_clock() {
    auto caps = stereo_imu_capabilities();
    caps.imu = false;

    bividi::SensorObservation observation{};
    observation.source_id = "synthetic:bad";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.validity = bividi::ObservationValidity::degraded;
    observation.timing.host_receive = {
        1,
        bividi::TimeUnit::nanoseconds,
        bividi::ClockDomain::device,
        "wrong.clock",
        true,
    };

    bividi::ImuObservation imu{};
    imu.sample_time = {
        10,
        bividi::TimeUnit::microseconds,
        bividi::ClockDomain::device,
        "imu.clock",
        true,
    };
    imu.raw_valid = true;
    imu.validity = bividi::ObservationValidity::valid;
    observation.imu.push_back(imu);

    observation.stereo_pairs.push_back({"missing-pair", bividi::SynchronizationState::synchronized});

    const auto result = bividi::validate_observation(observation, &caps);
    assert(!result.ok);
}

void test_declared_device_frame_time_must_be_present() {
    auto caps = stereo_imu_capabilities();
    caps.timing.device_frame_time = true;

    std::vector<std::uint8_t> pixels(24, 0);
    auto lease = bividi::FrameLease::adopt(new int(1), [](int* value) noexcept { delete value; });

    bividi::SensorObservation observation{};
    observation.source_id = "synthetic:frame-time";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.validity = bividi::ObservationValidity::valid;
    observation.timing.host_receive = {
        1,
        bividi::TimeUnit::nanoseconds,
        bividi::ClockDomain::host_monotonic,
        "host.steady_clock",
        true,
    };

    bividi::CameraObservation camera{};
    camera.stream_id = "camera_a";
    camera.lease = lease;
    camera.image = {pixels.data(), 4, 2, 12, 3, bividi::PixelFormat::bgr24};
    camera.exposure.start = {10, bividi::TimeUnit::microseconds, bividi::ClockDomain::device, "cam", true};
    camera.exposure.end = {20, bividi::TimeUnit::microseconds, bividi::ClockDomain::device, "cam", true};
    camera.validity = bividi::ObservationValidity::valid;
    observation.cameras.push_back(camera);

    const auto result = bividi::validate_observation(observation, &caps);
    assert(!result.ok);
}

}  // namespace

int main() {
    test_nori_normalized_source_defaults_do_not_claim_sync_or_calibration();
    test_capability_validation();
    test_clock_domains_remain_distinct();
    test_decxin_normalization();
    test_conformance_rejects_wrong_topology_and_clock();
    test_declared_device_frame_time_must_be_present();
    std::cout << "bividi observation contract test: PASS\n";
    return 0;
}
