#include "bividi/decxin.hpp"
#include "bividi/image_view.hpp"

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

void test_golden_vector() {
    bividi::decxin::Decoder decoder;
    const auto metadata = decoder.decode_payload(golden_payload());

    assert(metadata.header.protocol_type == 1);
    assert(metadata.header.device_groups[0].device_type == 1);
    assert(metadata.header.device_groups[0].group_count == 11);
    assert(metadata.header.device_groups[1].device_type == 2);
    assert(metadata.header.device_groups[1].group_count == 0);
    assert(metadata.header.exposure_start_raw_us == 28117353u);
    assert(metadata.header.exposure_end_raw_us == 28124847u);
    assert(metadata.exposure_duration_us() == 7494u);
    assert(metadata.imu_samples.size() == 11u);
    assert(metadata.imu_samples.front().raw_time_us == 28108131u);
    assert(metadata.imu_samples.back().raw_time_us == 28124771u);
    assert((metadata.imu_samples.front().accel_raw == std::array<std::int16_t, 3>{{-83, -8162, 338}}));
    assert((metadata.imu_samples.front().gyro_raw == std::array<std::int16_t, 3>{{84, -62, 73}}));
    assert((metadata.imu_samples.back().accel_raw == std::array<std::int16_t, 3>{{-122, -8079, 507}}));
    assert((metadata.imu_samples.back().gyro_raw == std::array<std::int16_t, 3>{{2, -74, 55}}));
}

void test_rollover() {
    bividi::decxin::TimestampExtender32 clock;
    assert(clock.extend(0xfffffff0u) == 0xfffffff0ull);
    assert(clock.extend(0xfffffffeu) == 0xfffffffeull);
    assert(clock.extend(0x00000620u) == (1ull << 32) + 0x620ull);
}

void test_image_view_is_zero_copy() {
    std::vector<std::uint8_t> storage(4000u * 3u * 2u, 0);
    bividi::ImageView frame{
        storage.data(),
        4000,
        2,
        4000u * 3u,
        3,
        bividi::PixelFormat::bgr24,
    };
    const auto camera_a = frame.subview(160, 1920);
    assert(camera_a.data == storage.data() + 160u * 3u);
    assert(camera_a.row_stride == frame.row_stride);
    assert(camera_a.width == 1920u);
}

}  // namespace

int main() {
    test_golden_vector();
    test_rollover();
    test_image_view_is_zero_copy();
    std::cout << "bividi native tests: PASS\n";
    return 0;
}
