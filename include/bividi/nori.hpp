#pragma once

#include "bividi/capture.hpp"

#include <cstddef>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace bividi::nori {

enum class TransportFormat {
    unknown,
    mjpeg,
    yuyv,
    bgr24,
};

struct VideoMode {
    std::uint32_t raw_format = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    float fps = 0.0f;
    TransportFormat format = TransportFormat::unknown;
    bool bottom_up = false;
};

struct VersionInfo {
    std::string sdk_version;
    std::string device_type;
    std::string isp_version;
    std::string fpga_version;
};

struct DeviceInfo {
    std::uint32_t index = 0;
    std::uint16_t vendor_id = 0;
    std::uint16_t product_id = 0;
    std::uint16_t device_bcd = 0;
    std::uint32_t usb_bcd = 0;
    std::string manufacturer;
    std::string product;
    std::string serial;
    VersionInfo version{};
    std::vector<VideoMode> modes;
};

enum class SdkTimestampEncoding {
    unknown,
    seconds_microseconds,
    windows_filetime_100ns,
};

struct SdkFrameTimestamp {
    SdkTimestampEncoding encoding = SdkTimestampEncoding::unknown;
    std::int64_t seconds = 0;
    std::int32_t microseconds = 0;
    std::uint64_t filetime_100ns = 0;
};

// Vendor-transport frame borrowed from the Nori SDK pool.
//
// This is intentionally below CapturedFrame: MJPEG/YUYV cannot be represented
// honestly as ImageView. A later normalization step turns this raw transport
// payload into a top-down BGR24 CapturedFrame for the DECXIN decoder.
struct RawFrame {
    FrameLease lease{};
    const std::uint8_t* data = nullptr;
    std::size_t size = 0;
    VideoMode mode{};
    std::uint64_t sequence = 0;
    std::uint64_t host_receive_monotonic_ns = 0;
    SdkFrameTimestamp sdk_timestamp{};
    std::uint32_t vendor_buffer_offset = 0;

    [[nodiscard]] bool valid() const noexcept {
        return lease.valid() && data != nullptr && size != 0;
    }
};

struct StreamConfig {
    std::uint32_t device_index = 0;
    std::uint32_t mode_index = 0;
    std::uint32_t timeout_ms = 2000;
    bool configure_free_run = true;
};

class Error : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

[[nodiscard]] const char* transport_format_name(TransportFormat format) noexcept;
[[nodiscard]] const char* sdk_timestamp_encoding_name(SdkTimestampEncoding encoding) noexcept;

// Enumerate Nori USB devices and their advertised modes using the supplied
// vendor SDK. Vendor structs remain private to the implementation.
[[nodiscard]] std::vector<DeviceInfo> probe_devices();

// Minimal zero-copy pull-buffer stream for bring-up.
//
// Exactly one vendor frame may remain leased at a time. This mirrors the
// supplied grab_image sample and makes ownership/backpressure deterministic.
// Destroying Stream while a RawFrame survives is safe: the private stream
// state stays alive until the final frame lease returns the buffer to the SDK.
class Stream {
public:
    explicit Stream(StreamConfig config = {});
    ~Stream();

    Stream(Stream&&) noexcept;
    Stream& operator=(Stream&&) noexcept;
    Stream(const Stream&) = delete;
    Stream& operator=(const Stream&) = delete;

    [[nodiscard]] RawFrame next_frame();
    [[nodiscard]] VideoMode mode() const;
    [[nodiscard]] std::uint32_t device_index() const noexcept;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

}  // namespace bividi::nori
