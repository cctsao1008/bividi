#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"
#include "bividi/opencv.hpp"

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>

namespace {

using Clock = std::chrono::steady_clock;
namespace fs = std::filesystem;

struct Options {
    bividi::nori::StreamConfig stream{};
    double duration_s = 120.0;
    std::uint64_t frame_limit = 0;
    std::uint32_t warmup_frames = 30;
    std::uint32_t frame_stride = 1;
    int png_compression = 1;
    fs::path output_dir = "bividi_nori_calib_session";
};

std::uint32_t parse_u32(const char* value, const char* name) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoull(value, &used, 10);
        if (value[used] != '\0' || parsed > std::numeric_limits<std::uint32_t>::max()) throw std::out_of_range("range");
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
        const auto parsed = std::stod(value, &used);
        if (value[used] != '\0' || !(parsed > 0.0)) throw std::out_of_range("range");
        return parsed;
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

int parse_png_compression(const char* value) {
    try {
        std::size_t used = 0;
        const auto parsed = std::stoi(value, &used, 10);
        if (value[used] != '\0' || parsed < 0 || parsed > 9) throw std::out_of_range("range");
        return parsed;
    } catch (...) {
        std::cerr << "invalid PNG compression (expected 0..9): " << value << '\n';
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
                    out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch)
                        << std::dec << std::setfill(' ');
                } else {
                    out << static_cast<char>(ch);
                }
        }
    }
    return out.str();
}

std::string frame_name(std::uint64_t frame_index) {
    std::ostringstream out;
    out << std::setw(10) << std::setfill('0') << frame_index << ".png";
    return out.str();
}

std::string sdk_timestamp_encoding(const bividi::nori::SdkFrameTimestamp& timestamp) {
    return bividi::nori::sdk_timestamp_encoding_name(timestamp.encoding);
}

void usage() {
    std::cout
        << "bividi-nori-calib-record [options]\n"
        << "  --device N              Nori device index (default 0)\n"
        << "  --mode N                advertised mode index (default 0)\n"
        << "  --duration-s SEC        recording duration (default 120)\n"
        << "  --frames N              optional decoded-frame stop condition\n"
        << "  --warmup-frames N       decoded warm-up frames (default 30)\n"
        << "  --frame-stride N        save every Nth stereo frame; IMU stays continuous (default 1)\n"
        << "  --timeout-ms N          GetFrameBuff timeout (default 2000)\n"
        << "  --png-compression N     OpenCV PNG compression 0..9 (default 1)\n"
        << "  --output-dir PATH       new session directory\n"
        << "  --no-trigger-config     do not force free-run during stream setup\n";
}

const bividi::nori::DeviceInfo* find_device(
    const std::vector<bividi::nori::DeviceInfo>& devices,
    std::uint32_t index) {
    for (const auto& device : devices) {
        if (device.index == index) return &device;
    }
    return nullptr;
}

void save_mono_png(const bividi::ImageView& view, const fs::path& path, int compression) {
    const auto bgr = bividi::opencv::wrap_bgr24(view);
    cv::Mat mono;
    cv::cvtColor(bgr, mono, cv::COLOR_BGR2GRAY);
    if (!cv::imwrite(path.string(), mono, {cv::IMWRITE_PNG_COMPRESSION, compression})) {
        throw std::runtime_error("failed to write image: " + path.string());
    }
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
        } else if (arg == "--frame-stride" && i + 1 < argc) {
            options.frame_stride = parse_u32(argv[++i], "frame stride");
            if (options.frame_stride == 0) {
                std::cerr << "frame stride must be >= 1\n";
                return 2;
            }
        } else if (arg == "--timeout-ms" && i + 1 < argc) {
            options.stream.timeout_ms = parse_u32(argv[++i], "timeout");
        } else if (arg == "--png-compression" && i + 1 < argc) {
            options.png_compression = parse_png_compression(argv[++i]);
        } else if (arg == "--output-dir" && i + 1 < argc) {
            options.output_dir = argv[++i];
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

    try {
        if (fs::exists(options.output_dir)) {
            throw std::runtime_error("output directory already exists: " + options.output_dir.string());
        }
        fs::create_directories(options.output_dir / "camera_a");
        fs::create_directories(options.output_dir / "camera_b");

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

        std::ofstream frames(options.output_dir / "frames.csv", std::ios::binary | std::ios::trunc);
        std::ofstream imu(options.output_dir / "imu.csv", std::ios::binary | std::ios::trunc);
        if (!frames || !imu) throw std::runtime_error("cannot open session CSV outputs");

        frames << "frame_index,frame_sequence,host_receive_monotonic_ns,"
                  "sdk_timestamp_encoding,sdk_seconds,sdk_microseconds,sdk_filetime_100ns,"
                  "exposure_start_raw_us,exposure_end_raw_us,"
                  "exposure_start_extended_us,exposure_end_extended_us,"
                  "camera_a_path,camera_b_path\n";
        imu << "frame_index,frame_sequence,host_receive_monotonic_ns,"
               "exposure_start_raw_us,exposure_end_raw_us,"
               "exposure_start_extended_us,exposure_end_extended_us,"
               "sample_index,sample_valid,imu_raw_time_us,imu_extended_time_us,"
               "accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n";

        std::uint64_t raw_frames = 0;
        std::uint64_t decoded_frames = 0;
        std::uint64_t image_pairs = 0;
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
                std::cerr << "decode error after raw frame " << raw_frames << ": " << error.what() << '\n';
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
                imu << frame_index << ',' << capture.decoded.sequence << ',' << capture.decoded.host_receive_monotonic_ns << ','
                    << timing.header.exposure_start_raw_us << ',' << timing.header.exposure_end_raw_us << ','
                    << timing.exposure_start_us << ',' << timing.exposure_end_us << ','
                    << sample_index << ',' << (sample.valid ? "true" : "false") << ','
                    << sample.raw_time_us << ',' << sample.extended_time_us << ','
                    << sample.accel_raw[0] << ',' << sample.accel_raw[1] << ',' << sample.accel_raw[2] << ','
                    << sample.gyro_raw[0] << ',' << sample.gyro_raw[1] << ',' << sample.gyro_raw[2] << '\n';
            }

            if ((frame_index % options.frame_stride) == 0) {
                const auto name = frame_name(frame_index);
                const fs::path a_rel = fs::path("camera_a") / name;
                const fs::path b_rel = fs::path("camera_b") / name;
                save_mono_png(capture.decoded.camera_a, options.output_dir / a_rel, options.png_compression);
                save_mono_png(capture.decoded.camera_b, options.output_dir / b_rel, options.png_compression);
                frames << frame_index << ',' << capture.decoded.sequence << ',' << capture.decoded.host_receive_monotonic_ns << ','
                       << sdk_timestamp_encoding(capture.sdk_timestamp) << ','
                       << capture.sdk_timestamp.seconds << ',' << capture.sdk_timestamp.microseconds << ','
                       << capture.sdk_timestamp.filetime_100ns << ','
                       << timing.header.exposure_start_raw_us << ',' << timing.header.exposure_end_raw_us << ','
                       << timing.exposure_start_us << ',' << timing.exposure_end_us << ','
                       << a_rel.generic_string() << ',' << b_rel.generic_string() << '\n';
                ++image_pairs;
            }
        }

        frames.flush();
        imu.flush();
        if (!frames || !imu) throw std::runtime_error("failed while writing calibration-session CSV output");

        std::ofstream json(options.output_dir / "capture.json", std::ios::binary | std::ios::trunc);
        if (!json) throw std::runtime_error("cannot open dynamic capture summary");
        json << std::setprecision(12)
             << "{\n"
             << "  \"schema\": \"bividi.nori.camera_imu_dynamic_trace.v1\",\n"
             << "  \"device\": {\n"
             << "    \"index\": " << device->index << ",\n"
             << "    \"vendor_id\": " << device->vendor_id << ",\n"
             << "    \"product_id\": " << device->product_id << ",\n"
             << "    \"product\": \"" << json_escape(device->product) << "\",\n"
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
             << "  \"camera_mapping\": {\n"
             << "    \"camera_a\": \"DECXIN decoded camera_a; physical left/right not assumed\",\n"
             << "    \"camera_b\": \"DECXIN decoded camera_b; physical left/right not assumed\"\n"
             << "  },\n"
             << "  \"run\": {\n"
             << "    \"requested_duration_s\": " << options.duration_s << ",\n"
             << "    \"requested_frame_limit\": " << options.frame_limit << ",\n"
             << "    \"warmup_requested\": " << options.warmup_frames << ",\n"
             << "    \"warmup_decoded\": " << warmup_decoded << ",\n"
             << "    \"frame_stride\": " << options.frame_stride << ",\n"
             << "    \"raw_frames\": " << raw_frames << ",\n"
             << "    \"decoded_frames\": " << decoded_frames << ",\n"
             << "    \"image_pairs\": " << image_pairs << ",\n"
             << "    \"imu_samples\": " << imu_samples << ",\n"
             << "    \"valid_imu_samples\": " << valid_imu_samples << ",\n"
             << "    \"timeouts\": " << timeouts << ",\n"
             << "    \"decode_errors\": " << decode_errors << "\n"
             << "  },\n"
             << "  \"timing_note\": \"frames.csv preserves ES and EE separately; no camera visual timestamp reference is chosen during recording\",\n"
             << "  \"scaling_note\": \"imu.csv records raw accel/gyro counts only; vendor-demo scale assumptions are not exported\",\n"
             << "  \"artifacts\": {\n"
             << "    \"frames_csv\": \"frames.csv\",\n"
             << "    \"imu_csv\": \"imu.csv\"\n"
             << "  }\n"
             << "}\n";
        json.flush();
        if (!json) throw std::runtime_error("failed while writing dynamic capture summary");

        std::cout << "dynamic calibration recording complete\n"
                  << "  decoded_frames=" << decoded_frames
                  << " image_pairs=" << image_pairs
                  << " imu_samples=" << imu_samples
                  << " valid_imu_samples=" << valid_imu_samples
                  << " timeouts=" << timeouts
                  << " decode_errors=" << decode_errors << '\n'
                  << "  output_dir=" << options.output_dir.string() << '\n';
        return (decoded_frames == 0 || image_pairs == 0) ? 6 : 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-calib-record: " << error.what() << '\n';
        return 3;
    }
}
