#include "bividi/nori.hpp"

#include <iomanip>
#include <iostream>

int main() {
    try {
        const auto devices = bividi::nori::probe_devices();
        std::cout << "Nori devices: " << devices.size() << '\n';

        for (const auto& device : devices) {
            std::cout << "\n[" << device.index << "] "
                      << (device.product.empty() ? "<unknown product>" : device.product)
                      << "  VID:PID="
                      << std::hex << std::setfill('0')
                      << std::setw(4) << device.vendor_id << ':'
                      << std::setw(4) << device.product_id
                      << std::dec << std::setfill(' ') << '\n';
            std::cout << "  manufacturer: " << device.manufacturer << '\n';
            std::cout << "  serial:       " << device.serial << '\n';
            std::cout << "  SDK:          " << device.version.sdk_version << '\n';
            std::cout << "  device type:  " << device.version.device_type << '\n';
            std::cout << "  ISP:          " << device.version.isp_version << '\n';
            std::cout << "  FPGA:         " << device.version.fpga_version << '\n';
            std::cout << "  modes:        " << device.modes.size() << '\n';

            for (std::size_t i = 0; i < device.modes.size(); ++i) {
                const auto& mode = device.modes[i];
                std::cout << "    " << i << ": "
                          << mode.width << 'x' << mode.height << '@' << mode.fps
                          << "  " << bividi::nori::transport_format_name(mode.format)
                          << "  raw=0x" << std::hex << mode.raw_format << std::dec;
                if (mode.bottom_up) {
                    std::cout << "  bottom-up";
                }
                std::cout << '\n';
            }
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-probe: " << error.what() << '\n';
        return 2;
    }
}
