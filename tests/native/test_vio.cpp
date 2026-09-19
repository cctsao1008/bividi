#include "bividi/vio.hpp"

#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>
#include <utility>

namespace {

constexpr std::array<std::uint8_t, 8> kCameraA{{1, 2, 3, 4, 5, 6, 7, 8}};
constexpr std::array<std::uint8_t, 8> kCameraB{{9, 10, 11, 12, 13, 14, 15, 16}};

bividi::TimePoint device_time(std::uint64_t ticks, std::string clock = "rig.device_us") {
    return {ticks, bividi::TimeUnit::microseconds, bividi::ClockDomain::device, std::move(clock), true};
}

bividi::CameraObservation camera(
    const char* stream_id,
    const std::uint8_t* pixels,
    std::uint64_t start = 1000,
    std::uint64_t end = 1100) {
    bividi::CameraObservation result{};
    result.stream_id = stream_id;
    result.lease = bividi::FrameLease::adopt(new int(1), [](int* value) noexcept { delete value; });
    result.image = {pixels, 4, 2, 4, 1, bividi::PixelFormat::gray8};
    result.exposure.start = device_time(start);
    result.exposure.end = device_time(end);
    result.validity = bividi::ObservationValidity::valid;
    return result;
}

bividi::ImuObservation imu(std::uint64_t ticks) {
    bividi::ImuObservation result{};
    result.sample_time = device_time(ticks);
    result.accel_m_s2 = {{0.0, 0.0, 9.80665}};
    result.gyro_rad_s = {{0.01, 0.02, 0.03}};
    result.si_valid = true;
    result.validity = bividi::ObservationValidity::valid;
    return result;
}

bividi::SensorObservation good_observation(std::uint64_t epoch = 7) {
    bividi::SensorObservation observation{};
    observation.source_id = "synthetic:vio";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.source_state = bividi::SourceState::available;
    observation.validity = bividi::ObservationValidity::valid;
    observation.sequence = 42;
    observation.sequence_present = true;
    observation.continuity_epoch = epoch;
    observation.continuity = bividi::ContinuityState::continuous;
    observation.timing.host_receive = {
        123456789,
        bividi::TimeUnit::nanoseconds,
        bividi::ClockDomain::host_monotonic,
        "host.steady_clock",
        true,
    };
    observation.calibration.stereo = "stereo-v1";
    observation.calibration.imu = "imu-v1";
    observation.calibration.camera_imu = "camera-imu-v1";
    observation.configuration_revision = "config-v1";
    observation.cameras = {
        camera("camera_a", kCameraA.data()),
        camera("camera_b", kCameraB.data()),
    };
    observation.stereo_pairs = {{"stereo0", bividi::SynchronizationState::synchronized}};
    observation.imu = {imu(900), imu(1000), imu(1100)};
    return observation;
}

class FakeBackend final : public bividi::VioBackend {
public:
    void reset(std::uint64_t continuity_epoch) override {
        ++reset_calls;
        last_reset_epoch = continuity_epoch;
    }

    bividi::PoseObservation process(const bividi::VioPacket& packet) override {
        assert(packet.backend_ready());
        ++process_calls;
        bividi::PoseObservation pose{};
        pose.timestamp = packet.stereo.reference_time;
        pose.position_world_m = {{1.0, 2.0, 3.0}};
        pose.orientation_world_from_body_xyzw = {{0.0, 0.0, 0.0, 1.0}};
        pose.velocity_world_m_s = {{0.1, 0.2, 0.3}};
        pose.tracking = bividi::VioTrackingState::tracking;
        pose.validity = bividi::ObservationValidity::valid;
        pose.calibration = packet.calibration;
        pose.configuration_revision = packet.configuration_revision;
        pose.backend_id = "fake-vio";
        pose.backend_version = "test-1";
        pose.continuity_epoch = packet.continuity_epoch;
        pose.source_sequence = packet.sequence;
        pose.source_sequence_present = packet.sequence_present;
        return pose;
    }

    int reset_calls = 0;
    int process_calls = 0;
    std::uint64_t last_reset_epoch = 0;
};

void test_midpoint_time_and_first_packet_reinitialize() {
    bividi::VioInputAdapter adapter;
    auto observation = good_observation();
    const auto packet = adapter.adapt(observation);
    assert(packet.backend_ready());
    assert(packet.reset == bividi::VioResetDirective::reinitialize);
    assert(packet.stereo.reference_time.present);
    assert(packet.stereo.reference_time.ticks == 1050);
    assert(packet.stereo.reference_time.domain == bividi::ClockDomain::device);
    assert(packet.stereo.reference_time.clock_id == "rig.device_us");
    assert(packet.imu.size() == 3);
    assert(packet.imu[0].sample_time.ticks == 900);
    assert(packet.calibration.stereo == "stereo-v1");
    assert(packet.calibration.imu == "imu-v1");
    assert(packet.calibration.camera_imu == "camera-imu-v1");
    assert(packet.configuration_revision == "config-v1");
    assert(packet.sequence == 42 && packet.sequence_present);
    assert(packet.evidence == bividi::EvidenceKind::synthetic);

    observation.sequence = 43;
    const auto next = adapter.adapt(observation);
    assert(next.backend_ready());
    assert(next.reset == bividi::VioResetDirective::none);
}

void test_midpoint_is_overflow_safe() {
    bividi::VioInputAdapter adapter;
    auto observation = good_observation();
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    observation.cameras[0].exposure.start.ticks = maximum - 10;
    observation.cameras[0].exposure.end.ticks = maximum;
    observation.cameras[1].exposure.start.ticks = maximum - 10;
    observation.cameras[1].exposure.end.ticks = maximum;
    observation.imu = {imu(maximum - 20), imu(maximum - 10), imu(maximum)};
    const auto packet = adapter.adapt(observation);
    assert(packet.backend_ready());
    assert(packet.stereo.reference_time.ticks == maximum - 5);
}

void test_explicit_start_and_end_references() {
    for (const auto& entry : {
             std::pair{bividi::VioCameraTimeReference::exposure_start, std::uint64_t{1000}},
             std::pair{bividi::VioCameraTimeReference::exposure_end, std::uint64_t{1100}},
         }) {
        bividi::VioAdapterConfig config{};
        config.camera_time_reference = entry.first;
        bividi::VioInputAdapter adapter(config);
        const auto packet = adapter.adapt(good_observation());
        assert(packet.backend_ready());
        assert(packet.stereo.reference_time.ticks == entry.second);
    }
}

void test_host_time_is_never_camera_alignment_fallback() {
    bividi::VioInputAdapter adapter;
    auto observation = good_observation();
    observation.cameras[0].exposure = {};
    observation.cameras[1].exposure = {};
    assert(observation.timing.host_receive.present);
    const auto packet = adapter.adapt(observation);
    assert(!packet.backend_ready());
    assert(packet.state == bividi::VioPacketState::rejected);
    assert(packet.reason.find("exposure timing") != std::string::npos);
}

void test_calibration_and_configuration_are_mandatory() {
    for (int field = 0; field < 4; ++field) {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        if (field == 0) observation.calibration.stereo.clear();
        if (field == 1) observation.calibration.imu.clear();
        if (field == 2) observation.calibration.camera_imu.clear();
        if (field == 3) observation.configuration_revision.clear();
        const auto packet = adapter.adapt(observation);
        assert(packet.state == bividi::VioPacketState::rejected);
    }
}

void test_stereo_sync_validity_and_clock_are_explicit() {
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.stereo_pairs[0].synchronization = bividi::SynchronizationState::unknown;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.cameras[1].validity = bividi::ObservationValidity::degraded;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.cameras[1].exposure.start.clock_id = "other.device";
        observation.cameras[1].exposure.end.clock_id = "other.device";
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.cameras[1].exposure.start.ticks += 1;
        observation.cameras[1].exposure.end.ticks += 1;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
}

void test_imu_requires_si_device_clock_and_strict_source_order() {
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.imu[1].si_valid = false;
        observation.imu[1].raw_valid = true;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.imu[1].sample_time.clock_id = "different.device";
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.imu[2].sample_time.ticks = observation.imu[1].sample_time.ticks;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.imu[2].sample_time.ticks = 950;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.imu[0].accel_m_s2[0] = std::numeric_limits<double>::quiet_NaN();
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
}

void test_continuity_reset_semantics_do_not_carry_state_across_epoch() {
    bividi::VioInputAdapter adapter;
    auto observation = good_observation(10);
    assert(adapter.adapt(observation).reset == bividi::VioResetDirective::reinitialize);
    assert(adapter.adapt(observation).reset == bividi::VioResetDirective::none);

    observation.continuity = bividi::ContinuityState::discontinuity;
    const auto discontinuity = adapter.adapt(observation);
    assert(discontinuity.state == bividi::VioPacketState::reset_required);
    assert(discontinuity.reset == bividi::VioResetDirective::reset_before_next);
    assert(!discontinuity.backend_ready());

    observation.continuity = bividi::ContinuityState::continuous;
    const auto after_reset = adapter.adapt(observation);
    assert(after_reset.backend_ready());
    assert(after_reset.reset == bividi::VioResetDirective::reinitialize);

    observation.continuity_epoch = 11;
    const auto new_epoch = adapter.adapt(observation);
    assert(new_epoch.backend_ready());
    assert(new_epoch.reset == bividi::VioResetDirective::reinitialize);

    observation.continuity = bividi::ContinuityState::reinitialized;
    const auto declared = adapter.adapt(observation);
    assert(declared.backend_ready());
    assert(declared.reset == bividi::VioResetDirective::reinitialize);
}

void test_source_and_observation_state_rejection() {
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.source_state = bividi::SourceState::disconnected;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
    {
        bividi::VioInputAdapter adapter;
        auto observation = good_observation();
        observation.validity = bividi::ObservationValidity::degraded;
        assert(adapter.adapt(observation).state == bividi::VioPacketState::rejected);
    }
}

void test_fake_backend_reset_process_and_pose_validation() {
    bividi::VioInputAdapter adapter;
    FakeBackend backend;
    const auto packet = adapter.adapt(good_observation(55));
    assert(packet.backend_ready());
    if (packet.reset == bividi::VioResetDirective::reinitialize) {
        backend.reset(packet.continuity_epoch);
    }
    const auto pose = backend.process(packet);
    assert(backend.reset_calls == 1);
    assert(backend.last_reset_epoch == 55);
    assert(backend.process_calls == 1);
    assert(pose.timestamp.ticks == packet.stereo.reference_time.ticks);
    assert(pose.timestamp.domain == bividi::ClockDomain::device);
    assert(pose.calibration.camera_imu == "camera-imu-v1");
    assert(pose.backend_id == "fake-vio");
    assert(bividi::validate_pose_observation(pose).ok);

    auto bad = pose;
    bad.orientation_world_from_body_xyzw = {{0.0, 0.0, 0.0, 2.0}};
    assert(!bividi::validate_pose_observation(bad).ok);

    bad = pose;
    bad.timestamp = good_observation().timing.host_receive;
    assert(!bividi::validate_pose_observation(bad).ok);
}

}  // namespace

int main() {
    test_midpoint_time_and_first_packet_reinitialize();
    test_midpoint_is_overflow_safe();
    test_explicit_start_and_end_references();
    test_host_time_is_never_camera_alignment_fallback();
    test_calibration_and_configuration_are_mandatory();
    test_stereo_sync_validity_and_clock_are_explicit();
    test_imu_requires_si_device_clock_and_strict_source_order();
    test_continuity_reset_semantics_do_not_carry_state_across_epoch();
    test_source_and_observation_state_rejection();
    test_fake_backend_reset_process_and_pose_validation();
    std::cout << "bividi VIO adapter contract test: PASS\n";
    return 0;
}
