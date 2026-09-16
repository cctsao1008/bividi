#pragma once

#include <cstdint>
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

class Error : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

[[nodiscard]] const char* transport_format_name(TransportFormat format) noexcept;

// Enumerate Nori USB devices and their advertised modes using the supplied
// vendor SDK. Vendor structs remain private to the implementation.
[[nodiscard]] std::vector<DeviceInfo> probe_devices();

}  // namespace bividi::nori
