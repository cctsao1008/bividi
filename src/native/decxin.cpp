#include "bividi/decxin.hpp"

#include <algorithm>
#include <limits>

namespace bividi::decxin {
namespace {

constexpr std::uint64_t kUint32Modulus = std::uint64_t{1} << 32;
constexpr std::uint32_t kUint32HalfRange = std::uint32_t{1} << 31;

std::uint32_t read_be32(const std::uint8_t* p) noexcept {
    return (std::uint32_t{p[0]} << 24) |
           (std::uint32_t{p[1]} << 16) |
           (std::uint32_t{p[2]} << 8) |
           std::uint32_t{p[3]};
}

std::int16_t read_be16s(const std::uint8_t* p) noexcept {
    const auto raw = static_cast<std::uint16_t>((std::uint16_t{p[0]} << 8) | p[1]);
    return static_cast<std::int16_t>(raw);
}

std::vector<std::uint8_t> decode_line(const ImageView& frame, std::size_t row_index) {
    if (row_index >= frame.height) {
        return {};
    }
    const auto* row = frame.data + row_index * frame.row_stride;
    if (frame.row_stride < 4 ||
        !(row[0] > 220 && row[1] > 220 && row[2] > 220 && row[3] > 220)) {
        return {};
    }

    constexpr std::size_t channel = 1;
    std::size_t index = 0;
    bool found_start = false;
    while (index < frame.width) {
        if (row[index * 3 + channel] < 220) {
            index += kCodeCell / 2;
            found_start = true;
            break;
        }
        ++index;
    }
    if (!found_start) {
        return {};
    }

    std::vector<std::uint8_t> bits;
    while (index + 1 < frame.width) {
        const int value = row[index * 3 + channel] + row[(index + 1) * 3 + channel];
        if (value < 100) {
            bits.push_back(0);
        } else if (value < 440) {
            bits.push_back(1);
        } else {
            break;
        }
        index += kCodeCell;
    }

    std::vector<std::uint8_t> bytes(bits.size() / 8, 0);
    for (std::size_t byte_index = 0; byte_index < bytes.size(); ++byte_index) {
        std::uint8_t value = 0;
        for (std::size_t bit_index = 0; bit_index < 8; ++bit_index) {
            value |= static_cast<std::uint8_t>(bits[byte_index * 8 + bit_index] << bit_index);
        }
        bytes[byte_index] = value;
    }
    return bytes;
}

std::array<std::uint8_t, kGroupSize> group_at(
    const std::vector<std::uint8_t>& payload,
    std::size_t group_index) {
    const auto begin = group_index * kGroupSize;
    if (begin + kGroupSize > payload.size()) {
        throw DecodeError("declared device group exceeds decoded payload");
    }
    std::array<std::uint8_t, kGroupSize> result{};
    std::copy_n(payload.data() + begin, kGroupSize, result.data());
    return result;
}

}  // namespace

std::size_t NoriHeader::total_groups() const noexcept {
    std::size_t total = 1;
    for (const auto& group : device_groups) {
        total += group.group_count;
    }
    return total;
}

void TimestampExtender32::reset() noexcept {
    has_last_ = false;
    last_raw_ = 0;
    epoch_ = 0;
}

std::uint64_t TimestampExtender32::extend(std::uint32_t raw_value) noexcept {
    if (has_last_ && last_raw_ > raw_value && last_raw_ - raw_value > kUint32HalfRange) {
        epoch_ += kUint32Modulus;
    }
    has_last_ = true;
    last_raw_ = raw_value;
    return epoch_ + raw_value;
}

NoriHeader decode_header(const std::array<std::uint8_t, kGroupSize>& g) {
    const bool legacy = std::equal(g.begin(), g.begin() + 8, g.begin() + 8);
    if (legacy) {
        NoriHeader header{};
        header.protocol_type = 0;
        header.device_groups[0] = DeviceGroup{kIcm42688DeviceType, 11};
        header.exposure_start_raw_us = read_be32(g.data());
        header.exposure_end_raw_us = read_be32(g.data() + 4);
        return header;
    }

    NoriHeader header{};
    header.protocol_type = static_cast<std::uint8_t>(g[0] >> 4);
    header.device_groups = {{
        DeviceGroup{static_cast<std::uint8_t>(((g[0] & 0x0F) << 4) | ((g[1] & 0xF0) >> 4)),
                    static_cast<std::uint8_t>(g[1] & 0x0F)},
        DeviceGroup{g[2], static_cast<std::uint8_t>(g[3] >> 4)},
        DeviceGroup{static_cast<std::uint8_t>(((g[3] & 0x0F) << 4) | ((g[4] & 0xF0) >> 4)),
                    static_cast<std::uint8_t>(g[4] & 0x0F)},
        DeviceGroup{g[5], static_cast<std::uint8_t>(g[6] >> 4)},
        DeviceGroup{static_cast<std::uint8_t>(((g[6] & 0x0F) << 4) | ((g[7] & 0xF0) >> 4)),
                    static_cast<std::uint8_t>(g[7] & 0x0F)},
    }};
    header.exposure_start_raw_us = read_be32(g.data() + 8);
    header.exposure_end_raw_us = read_be32(g.data() + 12);
    return header;
}

ImuSample decode_icm42688_group(
    const std::array<std::uint8_t, kGroupSize>& group,
    TimestampExtender32* clock) {
    ImuSample sample{};
    sample.raw_time_us = read_be32(group.data());
    sample.extended_time_us = clock ? clock->extend(sample.raw_time_us) : sample.raw_time_us;
    sample.accel_raw = {{
        read_be16s(group.data() + 4),
        read_be16s(group.data() + 6),
        read_be16s(group.data() + 8),
    }};
    sample.gyro_raw = {{
        read_be16s(group.data() + 10),
        read_be16s(group.data() + 12),
        read_be16s(group.data() + 14),
    }};

    const bool invalid =
        (sample.accel_raw[0] == -1 && sample.accel_raw[1] == -1 && sample.accel_raw[2] == -1) ||
        sample.gyro_raw[0] == std::numeric_limits<std::int16_t>::min();
    sample.valid = !invalid;
    if (invalid) {
        sample.accel_raw = {{0, 0, 0}};
        sample.gyro_raw = {{0, 0, 0}};
    }

    constexpr double accel_scale_mg = 4000.0 / 32768.0;
    constexpr double gyro_scale_dps = 1000.0 / 32768.0;
    for (std::size_t i = 0; i < 3; ++i) {
        sample.accel_mg[i] = sample.accel_raw[i] * accel_scale_mg;
        sample.gyro_dps[i] = sample.gyro_raw[i] * gyro_scale_dps;
    }
    return sample;
}

void Decoder::reset_timestamps() noexcept {
    exposure_clock_.reset();
    imu_clock_.reset();
}

Metadata Decoder::decode_payload(const std::vector<std::uint8_t>& payload) {
    if (payload.size() < kGroupSize || payload.size() % kGroupSize != 0) {
        throw DecodeError("Nori payload must contain complete 16-byte groups");
    }

    const auto header = decode_header(group_at(payload, 0));
    const auto expected_size = header.total_groups() * kGroupSize;
    if (expected_size != payload.size()) {
        throw DecodeError("Nori payload size does not match header-declared group count");
    }
    if (expected_size > 4096) {
        throw DecodeError("Nori header declares an unreasonable payload size");
    }

    Metadata metadata{};
    metadata.header = header;
    metadata.exposure_start_us = exposure_clock_.extend(header.exposure_start_raw_us);
    metadata.exposure_end_us = exposure_clock_.extend(header.exposure_end_raw_us);

    std::size_t group_index = 1;
    for (const auto& device_group : header.device_groups) {
        for (std::size_t i = 0; i < device_group.group_count; ++i, ++group_index) {
            const auto group = group_at(payload, group_index);
            if (device_group.device_type == kIcm42688DeviceType) {
                metadata.imu_samples.push_back(decode_icm42688_group(group, &imu_clock_));
            }
        }
    }
    return metadata;
}

std::vector<std::uint8_t> Decoder::extract_payload(const ImageView& frame) const {
    if (frame.pixel_format != PixelFormat::bgr24 || frame.bytes_per_pixel != 3) {
        throw DecodeError("DECXIN encoded-pixel decoder requires BGR24 input");
    }
    if (frame.width != kTransportWidth || frame.height != kTransportHeight) {
        throw DecodeError("unsupported DECXIN transport geometry");
    }
    if (frame.row_stride < frame.width * frame.bytes_per_pixel) {
        throw DecodeError("frame row stride is smaller than the declared BGR24 row width");
    }

    std::vector<std::uint8_t> payload;
    std::size_t line_index = 0;
    while (payload.size() < kGroupSize) {
        const auto row_index = 2 + line_index * kCodeCell;
        auto line = decode_line(frame, row_index);
        if (line.empty()) {
            throw DecodeError("unable to decode Nori header from encoded pixels");
        }
        payload.insert(payload.end(), line.begin(), line.end());
        ++line_index;
    }
    if (payload.size() != kGroupSize) {
        throw DecodeError("Nori header decoding did not end on a 16-byte boundary");
    }

    const auto header = decode_header(group_at(payload, 0));
    const auto total_size = header.total_groups() * kGroupSize;
    if (total_size > 4096) {
        throw DecodeError("Nori header declares an unreasonable payload size");
    }
    while (payload.size() < total_size) {
        const auto row_index = 2 + line_index * kCodeCell;
        auto line = decode_line(frame, row_index);
        if (line.empty()) {
            throw DecodeError("encoded Nori payload ended early");
        }
        payload.insert(payload.end(), line.begin(), line.end());
        ++line_index;
    }
    if (payload.size() != total_size) {
        throw DecodeError("Nori payload decoding did not end on the declared group boundary");
    }
    return payload;
}

Observation Decoder::decode_frame(const ImageView& frame) {
    const auto payload = extract_payload(frame);
    Observation observation{};
    observation.metadata_region = frame.subview(0, kMetadataWidth);
    observation.camera_a = frame.subview(kMetadataWidth, kCameraWidth);
    observation.camera_b = frame.subview(kMetadataWidth + kCameraWidth, kCameraWidth);
    observation.timing = decode_payload(payload);
    return observation;
}

}  // namespace bividi::decxin
