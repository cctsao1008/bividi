#include "bividi/nori.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

namespace {

std::uint32_t parse_u32(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoul(value, &used, 10);
        if (value[used] != '\0' || parsed > 0xffffffffUL) {
            throw std::out_of_range("range");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

std::filesystem::path mjpeg_dump_path(
    const std::filesystem::path& directory,
    std::uint32_t captured,
    std::uint64_t sequence) {
    std::ostringstream name;
    name << "frame_" << std::setw(6) << std::setfill('0') << (captured + 1)
         << "_seq_" << std::setw(10) << std::setfill('0') << sequence
         << ".jpg";
    return directory / name.str();
}

}  // namespace

int main(int argc, char** argv) {
    bividi::nori::StreamConfig config{};
    std::uint32_t frame_limit = 1;
    std::filesystem::path dump_mjpeg_dir;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--device" && i + 1 < argc) {
            config.device_index = parse_u32(argv[++i], "device index");
        } else if (arg == "--mode" && i + 1 < argc) {
            config.mode_index = parse_u32(argv[++i], "mode index");
        } else if (arg == "--frames" && i + 1 < argc) {
            frame_limit = parse_u32(argv[++i], "frame count");
        } else if (arg == "--timeout-ms" && i + 1 < argc) {
            config.timeout_ms = parse_u32(argv[++i], "timeout");
        } else if (arg == "--dump-mjpeg-dir" && i + 1 < argc) {
            dump_mjpeg_dir = argv[++i];
        } else if (arg == "--no-trigger-config") {
            config.configure_free_run = false;
        } else if (arg == "--help") {
            std::cout
                << "bividi-nori-grab [--device N] [--mode N] [--frames N] [--timeout-ms N] "
                   "[--dump-mjpeg-dir DIR] [--no-trigger-config]\n";
            return 0;
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            return 2;
        }
    }

    try {
        bividi::nori::Stream stream(config);
        const auto selected = stream.mode();
        std::cout << "stream device=" << stream.device_index()
                  << " mode=" << config.mode_index
                  << ' ' << selected.width << 'x' << selected.height << '@' << selected.fps
                  << ' ' << bividi::nori::transport_format_name(selected.format)
                  << (selected.bottom_up ? " bottom-up" : "") << '\n';

        if (!dump_mjpeg_dir.empty()) {
            if (selected.format != bividi::nori::TransportFormat::mjpeg) {
                std::cerr << "bividi-nori-grab: --dump-mjpeg-dir requires an MJPEG mode\n";
                return 2;
            }
            std::filesystem::create_directories(dump_mjpeg_dir);
            std::cout << "raw MJPEG dump: " << dump_mjpeg_dir.string() << '\n';
        }

        for (std::uint32_t captured = 0; captured < frame_limit; ++captured) {
            auto frame = stream.next_frame();
            if (!frame.valid()) {
                std::cerr << "bividi-nori-grab: timeout/no-buffer\n";
                return 4;
            }

            if (!dump_mjpeg_dir.empty()) {
                const auto path = mjpeg_dump_path(dump_mjpeg_dir, captured, frame.sequence);
                std::ofstream output(path, std::ios::binary | std::ios::trunc);
                if (!output) {
                    throw std::runtime_error("cannot open MJPEG dump file: " + path.string());
                }
                output.write(
                    reinterpret_cast<const char*>(frame.data),
                    static_cast<std::streamsize>(frame.size));
                if (!output) {
                    throw std::runtime_error("failed writing MJPEG dump file: " + path.string());
                }
            }

            std::cout << "frame sequence=" << frame.sequence
                      << " bytes=" << frame.size
                      << " host_ns=" << frame.host_receive_monotonic_ns
                      << " sdk_time=" << bividi::nori::sdk_timestamp_encoding_name(frame.sdk_timestamp.encoding);
            if (frame.sdk_timestamp.encoding == bividi::nori::SdkTimestampEncoding::seconds_microseconds) {
                std::cout << ':' << frame.sdk_timestamp.seconds << '.' << frame.sdk_timestamp.microseconds;
            } else if (frame.sdk_timestamp.encoding == bividi::nori::SdkTimestampEncoding::windows_filetime_100ns) {
                std::cout << ':' << frame.sdk_timestamp.filetime_100ns;
            }
            std::cout << " actual=" << frame.mode.width << 'x' << frame.mode.height << '@' << frame.mode.fps
                      << ' ' << bividi::nori::transport_format_name(frame.mode.format) << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-grab: " << error.what() << '\n';
        return 3;
    }
}
