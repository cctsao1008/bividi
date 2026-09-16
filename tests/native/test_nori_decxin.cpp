#include "bividi/nori_decxin.hpp"

#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string_view>
#include <vector>

namespace {

std::array<std::uint8_t, 16> parse_group(std::string_view hex) {
    assert(hex.size() == 32);
    auto nibble = [](char c) -> std::uint8_t {
        if (c >= '0' && c <= '9') return static_cast<std::uint8_t>(c - '0');
        if (c >= 'a' && c <= 'f') return static_cast<std::uint8_t>(c - 'a' + 10);
        if (c >= 'A' && c <= 'F') return static_cast<std::uint8_t>(c - 'A' + 10);
        assert(false && "invalid hex digit");
        return 0;
    };

    std::array<std::uint8_t, 16> result{};
    for (std::size_t i = 0; i < result.size(); ++i) {
        result[i] = static_cast<std::uint8_t>((nibble(hex[i * 2]) << 4) | nibble(hex[i * 2 + 1]));
    }
    return result;
}

std::vector<std::uint8_t> golden_payload() {
    constexpr std::array<std::string_view, 12> groups = {{
        "101b02000000000001ad096901ad26af",
        "01ace563ffade01e01520054ffc20049",
        "01acebe3ffa8e03201680054ffc00049",
        "01acf263ffa7e04a01760052ffbf0047",
        "01acf8e3ffa9e04d01770051ffbe0046",
        "01acff63ffabe03f017e004effbf0045",
        "01ad05e3ffaae04101930048ffbf0044",
        "01ad0c63ffa6e05501a80040ffbe0043",
        "01ad12e3ff9de06701bc0036ffbb0041",
        "01ad1963ff91e07501d50027ffb9003e",
        "01ad1fe3ff89e07901ea0015ffb7003b",
        "01ad2663ff86e07101fb0002ffb60037",
    }};

    std::vector<std::uint8_t> payload;
    payload.reserve(groups.size() * 16);
    for (const auto hex : groups) {
        const auto group = parse_group(hex);
        payload.insert(payload.end(), group.begin(), group.end());
    }
    return payload;
}

void encode_group_into_row(
    std::vector<std::uint8_t>& storage,
    std::size_t row_stride,
    std::size_t row_index,
    const std::uint8_t* group) {
    auto* row = storage.data() + row_index * row_stride;
    std::fill(row, row + row_stride, 0xff);

    constexpr std::size_t marker_x = 8;
    row[marker_x * 3 + 1] = 0;
    constexpr std::size_t first_bit_x = marker_x + bividi::decxin::kCodeCell / 2;

    for (std::size_t byte_index = 0; byte_index < bividi::decxin::kGroupSize; ++byte_index) {
        for (std::size_t bit_index = 0; bit_index < 8; ++bit_index) {
            const auto bit_number = byte_index * 8 + bit_index;
            const auto x = first_bit_x + bit_number * bividi::decxin::kCodeCell;
            const bool one = ((group[byte_index] >> bit_index) & 1u) != 0;
            const std::uint8_t level = one ? 100u : 0u;
            row[x * 3 + 1] = level;
            row[(x + 1) * 3 + 1] = level;
        }
    }
}

std::vector<std::uint8_t> synthetic_transport_frame(const std::vector<std::uint8_t>& payload) {
    constexpr std::size_t stride = bividi::decxin::kTransportWidth * 3;
    std::vector<std::uint8_t> storage(stride * bividi::decxin::kTransportHeight, 0xff);
    const auto group_count = payload.size() / bividi::decxin::kGroupSize;
    for (std::size_t group_index = 0; group_index < group_count; ++group_index) {
        encode_group_into_row(
            storage,
            stride,
            2 + group_index * bividi::decxin::kCodeCell,
            payload.data() + group_index * bividi::decxin::kGroupSize);
    }
    return storage;
}

bividi::nori::RawFrame make_raw_frame() {
    auto* storage = new std::vector<std::uint8_t>(synthetic_transport_frame(golden_payload()));

    bividi::nori::RawFrame raw{};
    raw.lease = bividi::FrameLease::adopt(
        storage,
        [](std::vector<std::uint8_t>* owned) noexcept { delete owned; });
    raw.data = storage->data();
    raw.size = storage->size();
    raw.mode.width = bividi::decxin::kTransportWidth;
    raw.mode.height = bividi::decxin::kTransportHeight;
    raw.mode.fps = 60.0f;
    raw.mode.format = bividi::nori::TransportFormat::bgr24;
    raw.mode.bottom_up = false;
    raw.sequence = 123;
    raw.host_receive_monotonic_ns = 987654321;
    raw.sdk_timestamp.encoding = bividi::nori::SdkTimestampEncoding::seconds_microseconds;
    raw.sdk_timestamp.seconds = 77;
    raw.sdk_timestamp.microseconds = 456789;
    raw.vendor_buffer_offset = 64;
    return raw;
}

}  // namespace

int main() {
    auto raw = make_raw_frame();
    const auto raw_data = raw.data;

    bividi::nori::DecxinPipeline pipeline;
    auto decoded = pipeline.decode(raw);

    assert(decoded.valid());
    assert(decoded.decoded.sequence == 123);
    assert(decoded.decoded.host_receive_monotonic_ns == 987654321);
    assert(decoded.decoded.timing.header.protocol_type == 1);
    assert(decoded.decoded.timing.exposure_duration_us() == 7494u);
    assert(decoded.decoded.timing.imu_samples.size() == 11u);
    assert(decoded.decoded.metadata_region.data == raw_data);
    assert(decoded.decoded.camera_a.data == raw_data + bividi::decxin::kMetadataWidth * 3);
    assert(decoded.sdk_timestamp.encoding == bividi::nori::SdkTimestampEncoding::seconds_microseconds);
    assert(decoded.sdk_timestamp.seconds == 77);
    assert(decoded.sdk_timestamp.microseconds == 456789);
    assert(decoded.source_mode.format == bividi::nori::TransportFormat::bgr24);
    assert(decoded.source_mode.width == bividi::decxin::kTransportWidth);
    assert(decoded.vendor_buffer_offset == 64);

    // The decoded camera views must keep the backing transport alive even after
    // the caller releases its RawFrame lease.
    raw.lease.reset();
    assert(decoded.decoded.lease.valid());
    assert(decoded.decoded.camera_a.data == raw_data + bividi::decxin::kMetadataWidth * 3);

    std::cout << "bividi Nori -> DECXIN pipeline test: PASS\n";
    return 0;
}
