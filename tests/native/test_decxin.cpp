#include "bividi/decxin.hpp"
#include "bividi/image_view.hpp"

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
    assert(payload.size() % bividi::decxin::kGroupSize == 0);
    constexpr std::size_t stride = bividi::decxin::kTransportWidth * 3;
    std::vector<std::uint8_t> storage(stride * bividi::decxin::kTransportHeight, 0xff);

    const auto group_count = payload.size() / bividi::decxin::kGroupSize;
    for (std::size_t group_index = 0; group_index < group_count; ++group_index) {
        const auto row_index = 2 + group_index * bividi::decxin::kCodeCell;
        encode_group_into_row(
            storage,
            stride,
            row_index,
            payload.data() + group_index * bividi::decxin::kGroupSize);
    }
    return storage;
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

void test_encoded_frame_path() {
    const auto payload = golden_payload();
    auto storage = synthetic_transport_frame(payload);
    constexpr std::size_t stride = bividi::decxin::kTransportWidth * 3;
    const bividi::ImageView frame{
        storage.data(),
        bividi::decxin::kTransportWidth,
        bividi::decxin::kTransportHeight,
        stride,
        3,
        bividi::PixelFormat::bgr24,
    };

    bividi::decxin::Decoder decoder;
    const auto extracted = decoder.extract_payload(frame);
    assert(extracted == payload);

    decoder.reset_timestamps();
    const auto decoded = decoder.decode_frame(frame);
    assert(decoded.valid());
    assert(!decoded.lease.valid());
    assert(decoded.sequence == 0);
    assert(decoded.host_receive_monotonic_ns == 0);
    assert(decoded.timing.header.protocol_type == 1);
    assert(decoded.timing.exposure_duration_us() == 7494u);
    assert(decoded.timing.imu_samples.size() == 11u);

    assert(decoded.metadata_region.data == storage.data());
    assert(decoded.metadata_region.width == bividi::decxin::kMetadataWidth);
    assert(decoded.camera_a.data == storage.data() + bividi::decxin::kMetadataWidth * 3);
    assert(decoded.camera_b.data ==
           storage.data() + (bividi::decxin::kMetadataWidth + bividi::decxin::kCameraWidth) * 3);
    assert(decoded.camera_a.row_stride == stride);
    assert(decoded.camera_b.row_stride == stride);
}

void test_captured_frame_preserves_lease_and_host_metadata() {
    struct OwnedTransport {
        std::vector<std::uint8_t> pixels;
    };

    int releases = 0;
    auto* owner = new OwnedTransport{synthetic_transport_frame(golden_payload())};
    auto lease = bividi::FrameLease::adopt(
        owner,
        [&releases](OwnedTransport* transport) noexcept {
            ++releases;
            delete transport;
        });

    constexpr std::size_t stride = bividi::decxin::kTransportWidth * 3;
    const bividi::ImageView transport{
        owner->pixels.data(),
        bividi::decxin::kTransportWidth,
        bividi::decxin::kTransportHeight,
        stride,
        3,
        bividi::PixelFormat::bgr24,
    };

    bividi::CapturedFrame captured{
        lease,
        transport,
        77,
        987654321,
    };
    lease.reset();
    assert(releases == 0);

    bividi::decxin::Decoder decoder;
    auto decoded = decoder.decode_frame(captured);
    assert(decoded.valid());
    assert(decoded.lease.valid());
    assert(decoded.sequence == 77);
    assert(decoded.host_receive_monotonic_ns == 987654321);
    assert(decoded.camera_a.data == owner->pixels.data() + bividi::decxin::kMetadataWidth * 3);
    assert(decoded.timing.exposure_duration_us() == 7494u);

    captured.lease.reset();
    assert(releases == 0);
    assert(decoded.camera_a.data == owner->pixels.data() + bividi::decxin::kMetadataWidth * 3);

    decoded.lease.reset();
    assert(releases == 1);
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
    test_encoded_frame_path();
    test_captured_frame_preserves_lease_and_host_metadata();
    test_rollover();
    test_image_view_is_zero_copy();
    std::cout << "bividi native tests: PASS\n";
    return 0;
}
