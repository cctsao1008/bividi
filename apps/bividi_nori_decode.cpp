#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"

#include <cstdlib>
#include <iostream>
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

void print_sdk_time(const bividi::nori::SdkFrameTimestamp& timestamp) {
    std::cout << bividi::nori::sdk_timestamp_encoding_name(timestamp.encoding);
    if (timestamp.encoding == bividi::nori::SdkTimestampEncoding::seconds_microseconds) {
        std::cout << ':' << timestamp.seconds << '.' << timestamp.microseconds;
    } else if (timestamp.encoding == bividi::nori::SdkTimestampEncoding::windows_filetime_100ns) {
        std::cout << ':' << timestamp.filetime_100ns;
    }
}

}  // namespace

int main(int argc, char** argv) {
    bividi::nori::StreamConfig config{};
    std::uint32_t frame_limit = 1;

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
        } else if (arg == "--no-trigger-config") {
            config.configure_free_run = false;
        } else if (arg == "--help") {
            std::cout << "bividi-nori-decode [--device N] [--mode N] [--frames N] [--timeout-ms N] [--no-trigger-config]\n";
            return 0;
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            return 2;
        }
    }

    try {
        bividi::nori::Stream stream(config);
        bividi::nori::DecxinPipeline pipeline;

        const auto selected = stream.mode();
        std::cout << "decode stream device=" << stream.device_index()
                  << " mode=" << config.mode_index
                  << ' ' << selected.width << 'x' << selected.height << '@' << selected.fps
                  << ' ' << bividi::nori::transport_format_name(selected.format)
                  << (selected.bottom_up ? " bottom-up" : "") << '\n';

        for (std::uint32_t captured = 0; captured < frame_limit; ++captured) {
            auto raw = stream.next_frame();
            if (!raw.valid()) {
                std::cerr << "bividi-nori-decode: timeout/no-buffer\n";
                return 4;
            }

            auto frame = pipeline.decode(raw);
            if (!frame.valid()) {
                std::cerr << "bividi-nori-decode: invalid decoded frame\n";
                return 5;
            }

            std::cout << "frame sequence=" << frame.decoded.sequence
                      << " source=" << bividi::nori::transport_format_name(frame.source_mode.format)
                      << " sdk_time=";
            print_sdk_time(frame.sdk_timestamp);
            std::cout << " host_ns=" << frame.decoded.host_receive_monotonic_ns
                      << " ES=" << frame.decoded.timing.exposure_start_us
                      << " EE=" << frame.decoded.timing.exposure_end_us
                      << " exposure_us=" << frame.decoded.timing.exposure_duration_us()
                      << " imu_samples=" << frame.decoded.timing.imu_samples.size()
                      << " camera_a=" << frame.decoded.camera_a.width << 'x' << frame.decoded.camera_a.height
                      << " camera_b=" << frame.decoded.camera_b.width << 'x' << frame.decoded.camera_b.height
                      << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-decode: " << error.what() << '\n';
        return 3;
    }
}
