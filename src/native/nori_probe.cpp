#include "bividi/nori.hpp"

#include "Nori_Xvision_API.h"

#include <iomanip>
#include <sstream>
#include <utility>

namespace bividi::nori {
namespace {

constexpr std::uint32_t kMjpg = 0x47504a4d;
constexpr std::uint32_t kYuyv = 0x56595559;
constexpr std::uint32_t kYuy2 = 0x32595559;
constexpr std::uint32_t kMjpgToBgr24 = kMjpg + 0x01;
constexpr std::uint32_t kYuy2ToBgr24 = kYuy2 + 0x01;

template <typename T, std::size_t N>
std::string fixed_string(const T (&buffer)[N]) {
    const auto* text = reinterpret_cast<const char*>(buffer);
    std::size_t length = 0;
    while (length < N && text[length] != '\0') {
        ++length;
    }
    return std::string(text, length);
}

[[noreturn]] void fail(const char* operation, std::uint32_t code) {
    std::ostringstream out;
    out << operation << " failed (0x" << std::hex << std::uppercase << code << ')';
    throw Error(out.str());
}

void check(const char* operation, std::uint32_t code) {
    if (code != NORI_OK) {
        fail(operation, code);
    }
}

class SdkGuard {
public:
    explicit SdkGuard(bool active) : active_(active) {}
    ~SdkGuard() {
        if (active_) {
            Nori_Xvision_UnInit();
        }
    }

    SdkGuard(const SdkGuard&) = delete;
    SdkGuard& operator=(const SdkGuard&) = delete;

private:
    bool active_ = false;
};

TransportFormat transport_format(std::uint32_t raw_format, bool& bottom_up) noexcept {
    bottom_up = false;
    if (raw_format == kMjpg) {
        return TransportFormat::mjpeg;
    }
    if (raw_format == kYuyv || raw_format == kYuy2) {
        return TransportFormat::yuyv;
    }
    if (raw_format == kMjpgToBgr24 || raw_format == kYuy2ToBgr24) {
        // Windows 10.00.10 documents the SDK-decoded BGR24 variants as
        // bottom-up. Linux 10.00.06 does not advertise these enum values.
        bottom_up = true;
        return TransportFormat::bgr24;
    }
    return TransportFormat::unknown;
}

}  // namespace

const char* transport_format_name(TransportFormat format) noexcept {
    switch (format) {
        case TransportFormat::mjpeg: return "mjpeg";
        case TransportFormat::yuyv: return "yuyv";
        case TransportFormat::bgr24: return "bgr24";
        case TransportFormat::unknown: return "unknown";
    }
    return "unknown";
}

std::vector<DeviceInfo> probe_devices() {
    std::uint32_t device_count = 0;
    check("Nori_Xvision_Init", Nori_Xvision_Init(NORI_USB_DEVICE, &device_count));
    SdkGuard guard(true);

    std::vector<DeviceInfo> devices;
    devices.reserve(device_count);

    for (std::uint32_t device_index = 0; device_index < device_count; ++device_index) {
        DeviceInfo device{};
        device.index = device_index;

        DEVICE_INFO vendor_info{};
        check(
            "Nori_Xvision_GetDeviceInfo",
            Nori_Xvision_GetDeviceInfo(device_index, &vendor_info));
        device.vendor_id = vendor_info.idVendor;
        device.product_id = vendor_info.idProduct;
        device.device_bcd = vendor_info.bcdDevice;
        device.usb_bcd = static_cast<std::uint32_t>(vendor_info.bcdUSB);
        device.manufacturer = fixed_string(vendor_info.iManufacturer);
        device.product = fixed_string(vendor_info.iProduct);
        device.serial = fixed_string(vendor_info.iSerialNumber);

        VERSION_INFO vendor_version{};
        check(
            "Nori_Xvision_GetVersion",
            Nori_Xvision_GetVersion(device_index, &vendor_version));
        device.version.sdk_version = fixed_string(vendor_version.SDKVersion);
        device.version.device_type = fixed_string(vendor_version.DeviceType);
        device.version.isp_version = fixed_string(vendor_version.ISPVersion);
        device.version.fpga_version = fixed_string(vendor_version.FPGAVersion);

        std::uint32_t mode_count = 0;
        check(
            "Nori_Xvision_GetDeviceVideoInfoSize",
            Nori_Xvision_GetDeviceVideoInfoSize(device_index, &mode_count));
        device.modes.reserve(mode_count);

        for (std::uint32_t mode_index = 0; mode_index < mode_count; ++mode_index) {
            VIDEO_INFO vendor_mode{};
            check(
                "Nori_Xvision_GetDeviceVideoInfo",
                Nori_Xvision_GetDeviceVideoInfo(device_index, mode_index, &vendor_mode));

            VideoMode mode{};
            mode.raw_format = vendor_mode.u_Format;
            mode.width = vendor_mode.u_Width;
            mode.height = vendor_mode.u_Height;
            mode.fps = vendor_mode.f_Fps;
            mode.format = transport_format(vendor_mode.u_Format, mode.bottom_up);
            device.modes.push_back(mode);
        }

        devices.push_back(std::move(device));
    }

    return devices;
}

}  // namespace bividi::nori
