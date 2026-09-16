#pragma once

#include "bividi/capture.hpp"

#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace bividi::decxin {

inline constexpr std::size_t kTransportWidth = 4000;
inline constexpr std::size_t kTransportHeight = 1200;
inline constexpr std::size_t kMetadataWidth = 160;
inline constexpr std::size_t kCameraWidth = 1920;
inline constexpr std::size_t kGroupSize = 16;
inline constexpr std::size_t kCodeCell = 8;
inline constexpr std::uint8_t kIcm42688DeviceType = 1;

class DecodeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct DeviceGroup {
    std::uint8_t device_type = 0;
    std::uint8_t group_count = 0;
};

struct NoriHeader {
    std::uint8_t protocol_type = 0;
    std::array<DeviceGroup, 5> device_groups{};
    std::uint32_t exposure_start_raw_us = 0;
    std::uint32_t exposure_end_raw_us = 0;

    [[nodiscard]] std::size_t total_groups() const noexcept;
};

struct ImuSample {
    std::uint32_t raw_time_us = 0;
    std::uint64_t extended_time_us = 0;
    std::array<std::int16_t, 3> accel_raw{};
    std::array<std::int16_t, 3> gyro_raw{};
    std::array<double, 3> accel_mg{};
    std::array<double, 3> gyro_dps{};
    bool valid = true;
};

struct Metadata {
    NoriHeader header{};
    std::uint64_t exposure_start_us = 0;
    std::uint64_t exposure_end_us = 0;
    std::vector<ImuSample> imu_samples;

    [[nodiscard]] std::uint64_t exposure_duration_us() const noexcept {
        return exposure_end_us - exposure_start_us;
    }
};

// Device-family decode result. This is intentionally not the final public
// Bividi Observation contract owned by Issue #11.
//
// When produced from a CapturedFrame, the lease and host acquisition metadata
// are carried forward so the camera subviews remain valid without a copy.
struct DecodedFrame {
    FrameLease lease{};
    ImageView metadata_region{};
    ImageView camera_a{};
    ImageView camera_b{};
    Metadata timing{};
    std::uint64_t sequence = 0;
    std::uint64_t host_receive_monotonic_ns = 0;

    [[nodiscard]] bool valid() const noexcept {
        return !camera_a.empty() && !camera_b.empty();
    }
};

class TimestampExtender32 {
public:
    void reset() noexcept;
    [[nodiscard]] std::uint64_t extend(std::uint32_t raw_value) noexcept;

private:
    bool has_last_ = false;
    std::uint32_t last_raw_ = 0;
    std::uint64_t epoch_ = 0;
};

[[nodiscard]] NoriHeader decode_header(const std::array<std::uint8_t, kGroupSize>& group0);
[[nodiscard]] ImuSample decode_icm42688_group(
    const std::array<std::uint8_t, kGroupSize>& group,
    TimestampExtender32* clock = nullptr);

class Decoder {
public:
    void reset_timestamps() noexcept;

    [[nodiscard]] Metadata decode_payload(const std::vector<std::uint8_t>& payload);
    [[nodiscard]] std::vector<std::uint8_t> extract_payload(const ImageView& bgr24_frame) const;
    [[nodiscard]] DecodedFrame decode_frame(const ImageView& bgr24_frame);
    [[nodiscard]] DecodedFrame decode_frame(const CapturedFrame& captured_frame);

private:
    TimestampExtender32 exposure_clock_;
    TimestampExtender32 imu_clock_;
};

}  // namespace bividi::decxin
