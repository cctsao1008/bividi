#include "bividi/vio_kimera.hpp"

#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

namespace {

bividi::TimePoint time(std::uint64_t ticks, bividi::TimeUnit unit = bividi::TimeUnit::microseconds) {
    return {ticks, unit, bividi::ClockDomain::device, "rig.device", true};
}

bividi::VioPacket packet() {
    static const std::array<std::uint8_t, 8> left{{1, 2, 3, 4, 5, 6, 7, 8}};
    static const std::array<std::uint8_t, 8> right{{9, 10, 11, 12, 13, 14, 15, 16}};
    bividi::VioPacket value{};
    value.state = bividi::VioPacketState::ready;
    value.reset = bividi::VioResetDirective::none;
    value.sequence = 42;
    value.sequence_present = true;
    value.continuity_epoch = 7;
    value.stereo.reference_time = time(1050);
    value.stereo.camera_a.stream_id = "camera_a";
    value.stereo.camera_b.stream_id = "camera_b";
    value.stereo.camera_a.lease = bividi::FrameLease::adopt(new int(1), [](int* p) noexcept { delete p; });
    value.stereo.camera_b.lease = bividi::FrameLease::adopt(new int(2), [](int* p) noexcept { delete p; });
    value.stereo.camera_a.image = {left.data(), 4, 2, 4, 1, bividi::PixelFormat::gray8};
    value.stereo.camera_b.image = {right.data(), 4, 2, 4, 1, bividi::PixelFormat::gray8};
    value.imu = {
        {time(900), {{1.0, 2.0, 3.0}}, {{4.0, 5.0, 6.0}}},
        {time(1000), {{7.0, 8.0, 9.0}}, {{10.0, 11.0, 12.0}}},
    };
    return value;
}

void test_feed_mapping_and_zero_copy_lifetime() {
    auto source = packet();
    const auto left_ptr = source.stereo.camera_a.image.data;
    const auto left_count = source.stereo.camera_a.lease.use_count();
    const auto result = bividi::translate_kimera_feed(source);
    assert(result.ready);
    assert(result.frame_id == 42);
    assert(result.camera_timestamp_ns == 1050000);
    assert(result.continuity_epoch == 7);
    assert(result.directive == bividi::KimeraPipelineDirective::none);
    assert(result.left.image.data == left_ptr);
    assert(result.left.lease.valid());
    assert(result.left.lease.use_count() > left_count);
    assert(result.imu.size() == 2);
    assert(result.imu[0].timestamp_ns == 900000);
    assert((result.imu[0].accel_gyro == std::array<double, 6>{{1, 2, 3, 4, 5, 6}}));
    assert(result.upstream_revision == bividi::kKimeraVioRevision);
}

void test_reinitialize_requires_pipeline_recreation() {
    auto source = packet();
    source.reset = bividi::VioResetDirective::reinitialize;
    const auto result = bividi::translate_kimera_feed(source);
    assert(result.ready);
    assert(result.directive == bividi::KimeraPipelineDirective::recreate_pipeline_before_feed);
}

void test_ns_and_us_conversion_and_overflow() {
    auto source = packet();
    source.stereo.reference_time = time(123, bividi::TimeUnit::nanoseconds);
    source.imu[0].sample_time = time(100, bividi::TimeUnit::nanoseconds);
    source.imu[1].sample_time = time(120, bividi::TimeUnit::nanoseconds);
    auto result = bividi::translate_kimera_feed(source);
    assert(result.ready && result.camera_timestamp_ns == 123);

    source = packet();
    const auto max_ns = static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max());
    source.stereo.reference_time = time(max_ns / 1000 + 1);
    result = bividi::translate_kimera_feed(source);
    assert(!result.ready);
    assert(result.reason.find("camera device timestamp") != std::string::npos);

    source = packet();
    source.imu[1].sample_time = time(max_ns / 1000 + 1);
    result = bividi::translate_kimera_feed(source);
    assert(!result.ready);
    assert(result.reason.find("IMU device timestamp") != std::string::npos);
}

void test_nonready_missing_sequence_and_reset_before_next_reject() {
    auto source = packet();
    source.state = bividi::VioPacketState::reset_required;
    assert(!bividi::translate_kimera_feed(source).ready);
    source = packet();
    source.sequence_present = false;
    assert(!bividi::translate_kimera_feed(source).ready);
    source = packet();
    source.reset = bividi::VioResetDirective::reset_before_next;
    assert(!bividi::translate_kimera_feed(source).ready);
}

void test_ns_conversion_preserves_strict_ordering() {
    auto source = packet();
    source.imu[0].sample_time = time(100, bividi::TimeUnit::nanoseconds);
    source.imu[1].sample_time = time(100, bividi::TimeUnit::nanoseconds);
    const auto result = bividi::translate_kimera_feed(source);
    assert(!result.ready);
    assert(result.reason.find("strictly increasing") != std::string::npos);
}

}  // namespace

int main() {
    test_feed_mapping_and_zero_copy_lifetime();
    test_reinitialize_requires_pipeline_recreation();
    test_ns_and_us_conversion_and_overflow();
    test_nonready_missing_sequence_and_reset_before_next_reject();
    test_ns_conversion_preserves_strict_ordering();
    std::cout << "bividi Kimera feed translation contract test: PASS\n";
    return 0;
}
