#include "bividi/characterization.hpp"
#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

using bividi::characterization::DistributionSummary;
using bividi::characterization::SequenceTracker;
using bividi::nori::DecodedCapture;
using bividi::nori::DeviceInfo;
using bividi::nori::SdkFrameTimestamp;
using bividi::nori::SdkTimestampEncoding;
using bividi::nori::StreamConfig;
using bividi::nori::VideoMode;
using Clock = std::chrono::steady_clock;

struct Options {
    StreamConfig stream{};
    double duration_s = 60.0;
    std::uint64_t frame_limit = 0;
    std::uint32_t warmup_frames = 30;
    std::string output_prefix = "bividi_nori_characterization";
};

struct RunData {
    std::uint64_t warmup_decoded = 0;
    std::uint64_t raw_frames = 0;
    std::uint64_t decoded_frames = 0;
    std::uint64_t timeouts = 0;
    std::uint64_t decode_errors = 0;
    std::uint64_t mode_mismatches = 0;
    std::uint64_t sdk_timestamp_encoding_changes = 0;

    std::vector<double> host_interval_us;
    std::vector<double> sdk_interval_us;
    std::vector<double> es_interval_us;
    std::vector<double> ee_interval_us;
    std::vector<double> exposure_duration_us;
    std::vector<double> imu_interval_us;
    std::vector<double> imu_cross_frame_gap_us;
    std::vector<double> imu_valid_samples_per_frame;
    std::vector<double> raw_bytes;

    std::optional<std::uint64_t> first_host_ns;
    std::optional<std::uint64_t> last_host_ns;
    std::optional<std::uint64_t> previous_host_ns;
    std::optional<std::uint64_t> previous_sdk_us;
    std::optional<std::uint64_t> previous_es_us;
    std::optional<std::uint64_t> previous_ee_us;
    std::optional<std::uint64_t> previous_imu_last_us;
    std::optional<SdkTimestampEncoding> sdk_encoding;
};

struct ImuFrameInfo {
    std::optional<std::uint64_t> first;
    std::optional<std::uint64_t> last;
    std::optional<std::uint64_t> cross_frame_gap;
    std::uint64_t valid_count = 0;
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
        if (value[used] != '\0' || !std::isfinite(parsed) || parsed <= 0.0) {
            throw std::out_of_range("range");
        }
        return parsed;
    } catch (...) {
        std::cerr << "invalid " << name << ": " << value << '\n';
        std::exit(2);
    }
}

void usage() {
    std::cout
        << "bividi-nori-characterize [options]\n"
        << "  --device N           Nori device index (default 0)\n"
        << "  --mode N             advertised mode index (default 0)\n"
        << "  --duration-s SEC     measurement duration, stop condition (default 60)\n"
        << "  --frames N           optional decoded-frame stop condition\n"
        << "  --warmup-frames N    decoded warm-up frames before measurement (default 30)\n"
        << "  --timeout-ms N       GetFrameBuff timeout (default 2000)\n"
        << "  --output-prefix PATH output PATH.csv + PATH.json\n"
        << "  --no-trigger-config  do not force free-run during stream setup\n";
}

std::string json_escape(const std::string& input) {
    std::ostringstream out;
    for (const unsigned char ch : input) {
        switch (ch) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\b': out << "\\b"; break;
            case '\f': out << "\\f"; break;
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

std::optional<std::uint64_t> sdk_timestamp_us(const SdkFrameTimestamp& timestamp) {
    switch (timestamp.encoding) {
        case SdkTimestampEncoding::seconds_microseconds:
            if (timestamp.seconds < 0 || timestamp.microseconds < 0) return std::nullopt;
            if (static_cast<std::uint64_t>(timestamp.seconds) >
                (std::numeric_limits<std::uint64_t>::max() -
                 static_cast<std::uint64_t>(timestamp.microseconds)) / 1'000'000ULL) {
                return std::nullopt;
            }
            return static_cast<std::uint64_t>(timestamp.seconds) * 1'000'000ULL +
                   static_cast<std::uint64_t>(timestamp.microseconds);
        case SdkTimestampEncoding::windows_filetime_100ns:
            return timestamp.filetime_100ns / 10ULL;
        case SdkTimestampEncoding::unknown:
            return std::nullopt;
    }
    return std::nullopt;
}

std::string optional_u64(const std::optional<std::uint64_t>& value) {
    return value.has_value() ? std::to_string(*value) : std::string{};
}

const DeviceInfo* find_device(const std::vector<DeviceInfo>& devices, std::uint32_t index) {
    for (const auto& device : devices) {
        if (device.index == index) return &device;
    }
    return nullptr;
}

void write_distribution(std::ostream& out, const char* indent, const DistributionSummary& s) {
    out << indent << "{\"count\":" << s.count
        << ",\"min\":" << s.minimum
        << ",\"max\":" << s.maximum
        << ",\"mean\":" << s.mean
        << ",\"p50\":" << s.p50
        << ",\"p95\":" << s.p95
        << ",\"p99\":" << s.p99 << '}';
}

ImuFrameInfo measure_imu_frame(const DecodedCapture& capture, RunData& data) {
    ImuFrameInfo info{};
    std::optional<std::uint64_t> previous_in_frame;

    for (const auto& sample : capture.decoded.timing.imu_samples) {
        if (!sample.valid) continue;
        ++info.valid_count;
        const auto t = sample.extended_time_us;
        if (!info.first.has_value()) info.first = t;
        if (previous_in_frame.has_value() && t > *previous_in_frame) {
            data.imu_interval_us.push_back(static_cast<double>(t - *previous_in_frame));
        }
        previous_in_frame = t;
        info.last = t;
    }

    data.imu_valid_samples_per_frame.push_back(static_cast<double>(info.valid_count));
    if (info.first.has_value() && data.previous_imu_last_us.has_value() &&
        *info.first > *data.previous_imu_last_us) {
        info.cross_frame_gap = *info.first - *data.previous_imu_last_us;
        data.imu_cross_frame_gap_us.push_back(static_cast<double>(*info.cross_frame_gap));
    }
    if (info.last.has_value()) data.previous_imu_last_us = info.last;
    return info;
}

bool mode_matches(const VideoMode& selected, const VideoMode& actual) noexcept {
    return selected.width == actual.width && selected.height == actual.height &&
           selected.format == actual.format && selected.bottom_up == actual.bottom_up;
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

    const std::string csv_path = options.output_prefix + ".csv";
    const std::string json_path = options.output_prefix + ".json";

    try {
        const auto devices = bividi::nori::probe_devices();
        const auto* probed_device = find_device(devices, options.stream.device_index);
        if (probed_device == nullptr) {
            throw bividi::nori::Error("selected Nori device was not found by probe_devices");
        }
        if (options.stream.mode_index >= probed_device->modes.size()) {
            throw bividi::nori::Error("selected Nori mode index is outside the probed mode list");
        }

        bividi::nori::Stream stream(options.stream);
        const auto selected_mode = stream.mode();
        bividi::nori::DecxinPipeline pipeline;

        std::cout << "warming up device=" << options.stream.device_index
                  << " mode=" << options.stream.mode_index
                  << ' ' << selected_mode.width << 'x' << selected_mode.height
                  << '@' << selected_mode.fps << ' '
                  << bividi::nori::transport_format_name(selected_mode.format)
                  << " frames=" << options.warmup_frames << '\n';

        RunData data{};
        for (std::uint32_t i = 0; i < options.warmup_frames; ++i) {
            auto raw = stream.next_frame();
            if (!raw.valid()) continue;
            try {
                auto capture = pipeline.decode(raw);
                if (capture.valid()) ++data.warmup_decoded;
            } catch (const std::exception& error) {
                std::cerr << "warmup decode error: " << error.what() << '\n';
                pipeline.reset_timestamps();
            }
        }
        pipeline.reset_timestamps();

#ifdef _WIN32
        SequenceTracker sequence(64);
#else
        SequenceTracker sequence(32);
#endif

        std::ofstream csv(csv_path, std::ios::binary | std::ios::trunc);
        if (!csv) throw std::runtime_error("cannot open CSV output: " + csv_path);
        csv << "sample_index,sequence,host_receive_ns,host_interval_us,"
               "sdk_timestamp_encoding,sdk_timestamp_us,sdk_interval_us,"
               "exposure_start_raw_us,exposure_end_raw_us,"
               "exposure_start_extended_us,exposure_end_extended_us,"
               "es_interval_us,ee_interval_us,exposure_duration_us,"
               "imu_total_samples,imu_valid_samples,imu_first_us,imu_last_us,"
               "imu_cross_frame_gap_us,raw_bytes,transport,width,height,"
               "vendor_buffer_index,vendor_buffer_offset\n";

        const auto measurement_wall_start = Clock::now();
        while (true) {
            const double wall_elapsed =
                std::chrono::duration<double>(Clock::now() - measurement_wall_start).count();
            if (wall_elapsed >= options.duration_s) break;
            if (options.frame_limit != 0 && data.decoded_frames >= options.frame_limit) break;

            auto raw = stream.next_frame();
            if (!raw.valid()) {
                ++data.timeouts;
                continue;
            }
            ++data.raw_frames;
            const auto raw_size = raw.size;
            const auto raw_mode = raw.mode;
            const auto vendor_buffer_index = raw.vendor_buffer_index;
            const auto vendor_buffer_offset = raw.vendor_buffer_offset;
            if (!mode_matches(selected_mode, raw_mode)) ++data.mode_mismatches;

            DecodedCapture capture{};
            try {
                capture = pipeline.decode(raw);
            } catch (const std::exception& error) {
                ++data.decode_errors;
                std::cerr << "decode error after raw frame " << data.raw_frames
                          << ": " << error.what() << '\n';
                pipeline.reset_timestamps();
                data.previous_es_us.reset();
                data.previous_ee_us.reset();
                data.previous_imu_last_us.reset();
                continue;
            }
            if (!capture.valid()) {
                ++data.decode_errors;
                pipeline.reset_timestamps();
                continue;
            }

            ++data.decoded_frames;
            sequence.observe(capture.decoded.sequence);
            data.raw_bytes.push_back(static_cast<double>(raw_size));

            const auto host_ns = capture.decoded.host_receive_monotonic_ns;
            std::optional<std::uint64_t> host_interval;
            if (!data.first_host_ns.has_value()) data.first_host_ns = host_ns;
            data.last_host_ns = host_ns;
            if (data.previous_host_ns.has_value() && host_ns > *data.previous_host_ns) {
                host_interval = (host_ns - *data.previous_host_ns) / 1000ULL;
                data.host_interval_us.push_back(static_cast<double>(*host_interval));
            }
            data.previous_host_ns = host_ns;

            if (!data.sdk_encoding.has_value()) {
                data.sdk_encoding = capture.sdk_timestamp.encoding;
            } else if (*data.sdk_encoding != capture.sdk_timestamp.encoding) {
                ++data.sdk_timestamp_encoding_changes;
                data.sdk_encoding = capture.sdk_timestamp.encoding;
                data.previous_sdk_us.reset();
            }

            const auto sdk_us = sdk_timestamp_us(capture.sdk_timestamp);
            std::optional<std::uint64_t> sdk_interval;
            if (sdk_us.has_value() && data.previous_sdk_us.has_value() &&
                *sdk_us > *data.previous_sdk_us) {
                sdk_interval = *sdk_us - *data.previous_sdk_us;
                data.sdk_interval_us.push_back(static_cast<double>(*sdk_interval));
            }
            if (sdk_us.has_value()) data.previous_sdk_us = sdk_us;

            const auto es = capture.decoded.timing.exposure_start_us;
            const auto ee = capture.decoded.timing.exposure_end_us;
            std::optional<std::uint64_t> es_interval;
            std::optional<std::uint64_t> ee_interval;
            if (data.previous_es_us.has_value() && es > *data.previous_es_us) {
                es_interval = es - *data.previous_es_us;
                data.es_interval_us.push_back(static_cast<double>(*es_interval));
            }
            if (data.previous_ee_us.has_value() && ee > *data.previous_ee_us) {
                ee_interval = ee - *data.previous_ee_us;
                data.ee_interval_us.push_back(static_cast<double>(*ee_interval));
            }
            data.previous_es_us = es;
            data.previous_ee_us = ee;

            const auto exposure_duration = capture.decoded.timing.exposure_duration_us();
            data.exposure_duration_us.push_back(static_cast<double>(exposure_duration));

            const auto imu = measure_imu_frame(capture, data);

            csv << (data.decoded_frames - 1) << ','
                << capture.decoded.sequence << ','
                << host_ns << ','
                << optional_u64(host_interval) << ','
                << bividi::nori::sdk_timestamp_encoding_name(capture.sdk_timestamp.encoding) << ','
                << optional_u64(sdk_us) << ','
                << optional_u64(sdk_interval) << ','
                << capture.decoded.timing.header.exposure_start_raw_us << ','
                << capture.decoded.timing.header.exposure_end_raw_us << ','
                << es << ',' << ee << ','
                << optional_u64(es_interval) << ','
                << optional_u64(ee_interval) << ','
                << exposure_duration << ','
                << capture.decoded.timing.imu_samples.size() << ','
                << imu.valid_count << ','
                << optional_u64(imu.first) << ','
                << optional_u64(imu.last) << ','
                << optional_u64(imu.cross_frame_gap) << ','
                << raw_size << ','
                << bividi::nori::transport_format_name(raw_mode.format) << ','
                << raw_mode.width << ',' << raw_mode.height << ','
                << vendor_buffer_index << ',' << vendor_buffer_offset << '\n';
        }
        csv.flush();
        if (!csv) throw std::runtime_error("failed while writing CSV output: " + csv_path);

        if (data.decoded_frames == 0) {
            std::cerr << "no decoded frames captured; CSV was written but summary is not meaningful\n";
            return 6;
        }

        double measured_elapsed_s = 0.0;
        double measured_fps = 0.0;
        if (data.first_host_ns.has_value() && data.last_host_ns.has_value() &&
            *data.last_host_ns > *data.first_host_ns) {
            measured_elapsed_s = static_cast<double>(*data.last_host_ns - *data.first_host_ns) / 1e9;
            if (data.decoded_frames > 1 && measured_elapsed_s > 0.0) {
                measured_fps = static_cast<double>(data.decoded_frames - 1) / measured_elapsed_s;
            }
        }

        const auto sequence_summary = sequence.summary();
        const auto host_stats = bividi::characterization::summarize(data.host_interval_us);
        const auto sdk_stats = bividi::characterization::summarize(data.sdk_interval_us);
        const auto es_stats = bividi::characterization::summarize(data.es_interval_us);
        const auto ee_stats = bividi::characterization::summarize(data.ee_interval_us);
        const auto exposure_stats = bividi::characterization::summarize(data.exposure_duration_us);
        const auto imu_interval_stats = bividi::characterization::summarize(data.imu_interval_us);
        const auto imu_gap_stats = bividi::characterization::summarize(data.imu_cross_frame_gap_us);
        const auto imu_count_stats = bividi::characterization::summarize(data.imu_valid_samples_per_frame);
        const auto byte_stats = bividi::characterization::summarize(data.raw_bytes);

        std::ofstream json(json_path, std::ios::binary | std::ios::trunc);
        if (!json) throw std::runtime_error("cannot open JSON output: " + json_path);
        json << std::setprecision(12);
        json << "{\n"
             << "  \"schema\": \"bividi.nori.characterization.v1\",\n"
             << "  \"device\": {\n"
             << "    \"index\": " << probed_device->index << ",\n"
             << "    \"vendor_id\": " << probed_device->vendor_id << ",\n"
             << "    \"product_id\": " << probed_device->product_id << ",\n"
             << "    \"manufacturer\": \"" << json_escape(probed_device->manufacturer) << "\",\n"
             << "    \"product\": \"" << json_escape(probed_device->product) << "\",\n"
             << "    \"serial\": \"" << json_escape(probed_device->serial) << "\",\n"
             << "    \"sdk_version\": \"" << json_escape(probed_device->version.sdk_version) << "\",\n"
             << "    \"device_type\": \"" << json_escape(probed_device->version.device_type) << "\",\n"
             << "    \"isp_version\": \"" << json_escape(probed_device->version.isp_version) << "\",\n"
             << "    \"fpga_version\": \"" << json_escape(probed_device->version.fpga_version) << "\"\n"
             << "  },\n"
             << "  \"mode\": {\n"
             << "    \"index\": " << options.stream.mode_index << ",\n"
             << "    \"width\": " << selected_mode.width << ",\n"
             << "    \"height\": " << selected_mode.height << ",\n"
             << "    \"nominal_fps\": " << selected_mode.fps << ",\n"
             << "    \"transport\": \"" << bividi::nori::transport_format_name(selected_mode.format) << "\",\n"
             << "    \"bottom_up\": " << (selected_mode.bottom_up ? "true" : "false") << "\n"
             << "  },\n"
             << "  \"run\": {\n"
             << "    \"requested_duration_s\": " << options.duration_s << ",\n"
             << "    \"requested_frame_limit\": " << options.frame_limit << ",\n"
             << "    \"warmup_requested\": " << options.warmup_frames << ",\n"
             << "    \"warmup_decoded\": " << data.warmup_decoded << ",\n"
             << "    \"raw_frames\": " << data.raw_frames << ",\n"
             << "    \"decoded_frames\": " << data.decoded_frames << ",\n"
             << "    \"timeouts\": " << data.timeouts << ",\n"
             << "    \"decode_errors\": " << data.decode_errors << ",\n"
             << "    \"mode_mismatches\": " << data.mode_mismatches << ",\n"
             << "    \"sdk_timestamp_encoding_changes\": " << data.sdk_timestamp_encoding_changes << ",\n"
             << "    \"measured_elapsed_s\": " << measured_elapsed_s << ",\n"
             << "    \"measured_fps\": " << measured_fps << ",\n"
             << "    \"nominal_expected_frames_over_measured_elapsed\": "
             << selected_mode.fps * measured_elapsed_s << "\n"
             << "  },\n"
             << "  \"sequence\": {\n"
             << "    \"observations\": " << sequence_summary.observations << ",\n"
             << "    \"drops\": " << sequence_summary.drops << ",\n"
             << "    \"duplicates\": " << sequence_summary.duplicates << ",\n"
             << "    \"out_of_order\": " << sequence_summary.out_of_order << ",\n"
             << "    \"wraps\": " << sequence_summary.wraps << "\n"
             << "  },\n"
             << "  \"distributions\": {\n";

        json << "    \"host_interval_us\": "; write_distribution(json, "", host_stats); json << ",\n";
        json << "    \"sdk_interval_us\": "; write_distribution(json, "", sdk_stats); json << ",\n";
        json << "    \"exposure_start_interval_us\": "; write_distribution(json, "", es_stats); json << ",\n";
        json << "    \"exposure_end_interval_us\": "; write_distribution(json, "", ee_stats); json << ",\n";
        json << "    \"exposure_duration_us\": "; write_distribution(json, "", exposure_stats); json << ",\n";
        json << "    \"imu_interval_us\": "; write_distribution(json, "", imu_interval_stats); json << ",\n";
        json << "    \"imu_cross_frame_gap_us\": "; write_distribution(json, "", imu_gap_stats); json << ",\n";
        json << "    \"imu_valid_samples_per_frame\": "; write_distribution(json, "", imu_count_stats); json << ",\n";
        json << "    \"raw_frame_bytes\": "; write_distribution(json, "", byte_stats); json << "\n";

        json << "  },\n"
             << "  \"clock_domain_note\": \"Host monotonic, SDK frame time, and embedded DECXIN device time are summarized independently. Absolute offsets are intentionally not subtracted across unrelated epochs.\",\n"
             << "  \"artifacts\": {\"trace_csv\": \"" << json_escape(csv_path)
             << "\", \"summary_json\": \"" << json_escape(json_path) << "\"}\n"
             << "}\n";
        json.flush();
        if (!json) throw std::runtime_error("failed while writing JSON output: " + json_path);

        std::cout << "characterization complete\n"
                  << "  decoded_frames=" << data.decoded_frames
                  << " measured_fps=" << measured_fps
                  << " drops=" << sequence_summary.drops
                  << " duplicates=" << sequence_summary.duplicates
                  << " out_of_order=" << sequence_summary.out_of_order << '\n'
                  << "  host_interval_us p50=" << host_stats.p50
                  << " p95=" << host_stats.p95
                  << " p99=" << host_stats.p99 << '\n'
                  << "  ES_interval_us p50=" << es_stats.p50
                  << " p95=" << es_stats.p95
                  << " p99=" << es_stats.p99 << '\n'
                  << "  IMU_interval_us p50=" << imu_interval_stats.p50
                  << " p95=" << imu_interval_stats.p95
                  << " p99=" << imu_interval_stats.p99 << '\n'
                  << "  csv=" << csv_path << '\n'
                  << "  json=" << json_path << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-characterize: " << error.what() << '\n';
        return 3;
    }
}
