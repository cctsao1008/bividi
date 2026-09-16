#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <string>

namespace {

using Clock = std::chrono::steady_clock;

struct Options {
    bividi::nori::StreamConfig stream{};
    double duration_s = 60.0;
    std::uint64_t frame_limit = 0;
    std::uint32_t warmup_frames = 30;
    std::string output_prefix = "bividi_nori_imu";
};

std::uint32_t parse_u32(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoull(value, &used, 10);
        if (value[used] != '\0' || parsed > std::numeric_limits<std::uint32_t>::max()) {
            throw std::out_of_range("range");
        }
        return static_cast<std::uint32_t>(parsed);
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

std::uint64_t parse_u64(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoull(value, &used, 10);
        if (value[used] != '\0') throw std::out_of_range("range");
        return parsed;
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

double parse_positive_double(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const double parsed = std::stod(value, &used);
        if (value[used] != '\0' || !(parsed > 0.0)) throw std::out_of_range("range");
        return parsed;
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

std::string json_escape(const std::string& input) {
    std::ostringstream out;
    for (const unsigned char ch : input) {
        switch (ch) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default:
                if (ch < 0x20) {
                    out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                        << static_cast<int>(ch) << std::dec << std::setfill(' ');
                } else {
                    out << static_cast<char>(ch);
                }
        }
    }
    return out.str();
}

void usage() {
    std::cout
        << "bividi-nori-imu-record [options]\n"
        << "  --device N           Nori device index (default 0)\n"
        << "  --mode N             advertised mode index (default 0)\n"
        << "  --duration-s SEC     recording duration (default 60)\n"
        << "  --frames N           optional decoded-frame stop condition\n"
        << "  --warmup-frames N    decoded warm-up frames (default 30)\n"
        << "  --timeout-ms N       GetFrameBuff timeout (default 2000)\n"
        << "  --output-prefix PATH output PATH.imu.csv + PATH.json\n"
        << "  --no-trigger-config  do not force free-run during stream setup\n";
}

const bividi::nori::DeviceInfo* find_device(
    const std::vector<bividi::nori::DeviceInfo>& devices,
    std::uint32_t index) {
    for (const auto& device : devices) {
        if (device.index == index) return &device;
    }
    return nullptr;
}

}  // namespace

int main(int argc, char** argv) {
    Options options{};
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--device" && i + 1 < argc) {
            options.stream.device_index = parse_u32(argv[++i], "device index");
        } else if (arg == "--mode" && i + 1 < argc) {
            options.stream.mode_index = parse_u32(argv[++i], "mode index");
        } else if (arg == "--duration-s" && i + 1 < argc) {
            options.duration_s = parse_positive_double(argv[++i], "duration");
        } else if (arg == "--frames" && i + 1 < argc) {
            options.frame_limit = parse_u64(argv[++i], "frame count");
        } else if (arg == "--warmup-frames" && i + 1 < argc) {
            options.warmup_frames = parse_u32(argv[++i], "warmup frame count");
        } else if (arg == "--timeout-ms" && i + 1 < argc) {
            options.stream.timeout_ms = parse_u32(argv[++i], "timeout");
        } else if (arg == "--output-prefix" && i + 1 < argc) {
            options.output_prefix = argv[++i];
        } else if (arg == "--no-trigger-config") {
            options.stream.configure_free_run = false;
        } else if (arg == "--help") {
            usage();
            return 0;
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            usage();
            return 2;
        }
    }

    if (options.output_prefix.empty()) {
        std::cerr << "output prefix must not be empty\n";
        return 2;
    }

    const std::string csv_path = options.output_prefix + ".imu.csv";
    const std::string json_path = options.output_prefix + ".json";

    try {
        const auto devices = bividi::nori::probe_devices();
        const auto* device = find_device(devices, options.stream.device_index);
        if (device == nullptr) throw bividi::nori::Error("selected device was not found");
        if (options.stream.mode_index >= device->modes.size()) {
            throw bividi::nori::Error("selected mode index is outside the probed mode list");
        }

        bividi::nori::Stream stream(options.stream);
        const auto mode = stream.mode();
        bividi::nori::DecxinPipeline pipeline;

        std::uint64_t warmup_decoded = 0;
        for (std::uint32_t i = 0; i < options.warmup_frames; ++i) {
            auto raw = stream.next_frame();
            if (!raw.valid()) continue;
            try {
                auto capture = pipeline.decode(raw);
                if (capture.valid()) ++warmup_decoded;
            } catch (const std::exception&) {
                pipeline.reset_timestamps();
            }
        }
        pipeline.reset_timestamps();

        std::ofstream csv(csv_path, std::ios::binary | std::ios::trunc);
        if (!csv) throw std::runtime_error("cannot open IMU CSV output: " + csv_path);
        csv << "frame_index,frame_sequence,host_receive_monotonic_ns,"
               "exposure_start_raw_us,exposure_end_raw_us,"
               "exposure_start_extended_us,exposure_end_extended_us,"
               "sample_index,sample_valid,imu_raw_time_us,imu_extended_time_us,"
               "accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n";

        std::uint64_t raw_frames = 0;
        std::uint64_t decoded_frames = 0;
        std::uint64_t imu_samples = 0;
        std::uint64_t valid_imu_samples = 0;
        std::uint64_t timeouts = 0;
        std::uint64_t decode_errors = 0;

        const auto start = Clock::now();
        while (true) {
            const double elapsed = std::chrono::duration<double>(Clock::now() - start).count();
            if (elapsed >= options.duration_s) break;
            if (options.frame_limit != 0 && decoded_frames >= options.frame_limit) break;

            auto raw = stream.next_frame();
            if (!raw.valid()) {
                ++timeouts;
                continue;
            }
            ++raw_frames;

            bividi::nori::DecodedCapture capture{};
            try {
                capture = pipeline.decode(raw);
            } catch (const std::exception& error) {
                ++decode_errors;
                std::cerr << "decode error after raw frame " << raw_frames << ": "
                          << error.what() << '\n';
                pipeline.reset_timestamps();
                continue;
            }
            if (!capture.valid()) {
                ++decode_errors;
                pipeline.reset_timestamps();
                continue;
            }

            const auto frame_index = decoded_frames++;
            const auto& timing = capture.decoded.timing;
            for (std::size_t sample_index = 0; sample_index < timing.imu_samples.size(); ++sample_index) {
                const auto& sample = timing.imu_samples[sample_index];
                ++imu_samples;
                if (sample.valid) ++valid_imu_samples;
                csv << frame_index << ','
                    << capture.decoded.sequence << ','
                    << capture.decoded.host_receive_monotonic_ns << ','
                    << timing.header.exposure_start_raw_us << ','
                    << timing.header.exposure_end_raw_us << ','
                    << timing.exposure_start_us << ','
                    << timing.exposure_end_us << ','
                    << sample_index << ','
                    << (sample.valid ? "true" : "false") << ','
                    << sample.raw_time_us << ','
                    << sample.extended_time_us << ','
                    << sample.accel_raw[0] << ',' << sample.accel_raw[1] << ',' << sample.accel_raw[2] << ','
                    << sample.gyro_raw[0] << ',' << sample.gyro_raw[1] << ',' << sample.gyro_raw[2] << '\n';
            }
        }
        csv.flush();
        if (!csv) throw std::runtime_error("failed while writing IMU CSV output");

        std::ofstream json(json_path, std::ios::binary | std::ios::trunc);
        if (!json) throw std::runtime_error("cannot open IMU summary output: " + json_path);
        json << std::setprecision(12)
             << "{\n"
             << "  \"schema\": \"bividi.nori.imu_trace.v1\",\n"
             << "  \"device\": {\n"
             << "    \"index\": " << device->index << ",\n"
             << "    \"vendor_id\": " << device->vendor_id << ",\n"
             << "    \"product_id\": " << device->product_id << ",\n"
             << "    \"serial\": \"" << json_escape(device->serial) << "\",\n"
             << "    \"sdk_version\": \"" << json_escape(device->version.sdk_version) << "\",\n"
             << "    \"device_type\": \"" << json_escape(device->version.device_type) << "\",\n"
             << "    \"isp_version\": \"" << json_escape(device->version.isp_version) << "\",\n"
             << "    \"fpga_version\": \"" << json_escape(device->version.fpga_version) << "\"\n"
             << "  },\n"
             << "  \"mode\": {\n"
             << "    \"index\": " << options.stream.mode_index << ",\n"
             << "    \"width\": " << mode.width << ",\n"
             << "    \"height\": " << mode.height << ",\n"
             << "    \"nominal_fps\": " << mode.fps << ",\n"
             << "    \"transport\": \"" << bividi::nori::transport_format_name(mode.format) << "\"\n"
             << "  },\n"
             << "  \"run\": {\n"
             << "    \"requested_duration_s\": " << options.duration_s << ",\n"
             << "    \"requested_frame_limit\": " << options.frame_limit << ",\n"
             << "    \"warmup_requested\": " << options.warmup_frames << ",\n"
             << "    \"warmup_decoded\": " << warmup_decoded << ",\n"
             << "    \"raw_frames\": " << raw_frames << ",\n"
             << "    \"decoded_frames\": " << decoded_frames << ",\n"
             << "    \"imu_samples\": " << imu_samples << ",\n"
             << "    \"valid_imu_samples\": " << valid_imu_samples << ",\n"
             << "    \"timeouts\": " << timeouts << ",\n"
             << "    \"decode_errors\": " << decode_errors << "\n"
             << "  },\n"
             << "  \"scaling_note\": \"CSV intentionally records raw accel/gyro counts only. Vendor-demo full-scale assumptions are not promoted to measured calibration.\",\n"
             << "  \"artifact\": \"" << json_escape(csv_path) << "\"\n"
             << "}\n";
        json.flush();
        if (!json) throw std::runtime_error("failed while writing IMU summary output");

        std::cout << "IMU recording complete\n"
                  << "  decoded_frames=" << decoded_frames
                  << " imu_samples=" << imu_samples
                  << " valid_imu_samples=" << valid_imu_samples
                  << " timeouts=" << timeouts
                  << " decode_errors=" << decode_errors << '\n'
                  << "  csv=" << csv_path << '\n'
                  << "  json=" << json_path << '\n';
        return decoded_frames == 0 ? 6 : 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-imu-record: " << error.what() << '\n';
        return 3;
    }
}
