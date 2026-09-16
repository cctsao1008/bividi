#include "bividi/characterization.hpp"
#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace {

using bividi::characterization::BoundedSampleSeries;
using bividi::characterization::DistributionSummary;
using bividi::characterization::LinearTrendSummary;
using bividi::characterization::SequenceSummary;
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
    std::uint32_t rss_sample_ms = 1000;
    std::uint64_t stop_start_every_frames = 0;
    std::uint32_t stop_start_pause_ms = 250;
    std::uint64_t reconnect_every_frames = 0;
    std::uint32_t reconnect_pause_ms = 500;
    std::uint32_t recovery_timeout_ms = 10000;
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
    std::uint64_t rss_sample_failures = 0;
    std::uint64_t fault_operation_failures = 0;
    std::uint64_t fault_recovery_failures = 0;
    std::uint64_t current_timeout_streak = 0;
    std::uint64_t max_timeout_streak = 0;
    std::uint64_t current_decode_error_streak = 0;
    std::uint64_t max_decode_error_streak = 0;

    // These series are deliberately bounded. The per-frame CSV remains the
    // lossless trace; in-memory samples exist only to produce convenient
    // approximate run summaries without manufacturing an RSS growth slope.
    BoundedSampleSeries host_interval_us;
    BoundedSampleSeries sdk_interval_us;
    BoundedSampleSeries es_interval_us;
    BoundedSampleSeries ee_interval_us;
    BoundedSampleSeries exposure_duration_us;
    BoundedSampleSeries imu_interval_us;
    BoundedSampleSeries imu_cross_frame_gap_us;
    BoundedSampleSeries imu_valid_samples_per_frame;
    BoundedSampleSeries raw_bytes;
    BoundedSampleSeries recovery_latency_ms;

    // RSS samples are low-rate (default 1 Hz) and retain paired timestamps for
    // regression. They are separate from the high-rate bounded metric series.
    std::vector<double> rss_time_s;
    std::vector<double> rss_bytes;

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

enum class FaultKind {
    stop_start,
    reconnect,
};

struct FaultEvent {
    std::uint64_t id = 0;
    FaultKind kind = FaultKind::stop_start;
    std::uint64_t after_decoded_frame = 0;
    double started_elapsed_s = 0.0;
    std::uint32_t pause_ms = 0;
    bool operation_succeeded = false;
    bool recovered = false;
    double recovery_ms = 0.0;
    std::optional<std::uint64_t> pre_sequence;
    std::optional<std::uint64_t> post_sequence;
    std::optional<std::uint32_t> pre_es_raw_us;
    std::optional<std::uint32_t> post_es_raw_us;
    std::optional<bool> sequence_reset_observed;
    std::optional<bool> device_time_reset_observed;
    std::string error;
    Clock::time_point started_at{};
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
        << "  --device N                    Nori device index (default 0)\n"
        << "  --mode N                      advertised mode index (default 0)\n"
        << "  --duration-s SEC              measurement duration (default 60)\n"
        << "  --frames N                    optional decoded-frame stop condition\n"
        << "  --warmup-frames N             decoded warm-up frames (default 30)\n"
        << "  --timeout-ms N                GetFrameBuff timeout (default 2000)\n"
        << "  --rss-sample-ms N             RSS sample interval; 0 disables (default 1000)\n"
        << "  --stop-start-every-frames N   inject VideoStop/VideoStart every N frames\n"
        << "  --stop-start-pause-ms N       injected stop duration (default 250)\n"
        << "  --reconnect-every-frames N    destroy/reopen SDK stream every N frames\n"
        << "  --reconnect-pause-ms N        delay between close/reopen (default 500)\n"
        << "  --recovery-timeout-ms N       first-frame recovery deadline (default 10000)\n"
        << "  --output-prefix PATH          write PATH.csv/.rss.csv/.events.csv/.json\n"
        << "  --no-trigger-config           do not force free-run during stream setup\n";
}

const char* fault_kind_name(FaultKind kind) noexcept {
    return kind == FaultKind::stop_start ? "stop_start" : "reconnect";
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

std::string csv_escape(const std::string& input) {
    if (input.find_first_of(",\"\r\n") == std::string::npos) return input;
    std::string out = "\"";
    for (const char ch : input) {
        if (ch == '"') out += "\"\"";
        else out += ch;
    }
    out += '"';
    return out;
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

std::string optional_u32(const std::optional<std::uint32_t>& value) {
    return value.has_value() ? std::to_string(*value) : std::string{};
}

std::string optional_bool_csv(const std::optional<bool>& value) {
    if (!value.has_value()) return {};
    return *value ? "true" : "false";
}

void write_json_optional_u64(std::ostream& out, const std::optional<std::uint64_t>& value) {
    if (value.has_value()) out << *value;
    else out << "null";
}

void write_json_optional_u32(std::ostream& out, const std::optional<std::uint32_t>& value) {
    if (value.has_value()) out << *value;
    else out << "null";
}

void write_json_optional_bool(std::ostream& out, const std::optional<bool>& value) {
    if (value.has_value()) out << (*value ? "true" : "false");
    else out << "null";
}

const DeviceInfo* find_device(const std::vector<DeviceInfo>& devices, std::uint32_t index) {
    for (const auto& device : devices) {
        if (device.index == index) return &device;
    }
    return nullptr;
}

void write_distribution(std::ostream& out, const DistributionSummary& s) {
    out << "{\"count\":" << s.count
        << ",\"min\":" << s.minimum
        << ",\"max\":" << s.maximum
        << ",\"mean\":" << s.mean
        << ",\"p50\":" << s.p50
        << ",\"p95\":" << s.p95
        << ",\"p99\":" << s.p99 << '}';
}

void write_trend(std::ostream& out, const LinearTrendSummary& trend) {
    out << "{\"count\":" << trend.count
        << ",\"slope_per_second\":" << trend.slope_per_second
        << ",\"intercept\":" << trend.intercept
        << ",\"r_squared\":" << trend.r_squared << '}';
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

void reset_interval_baselines(RunData& data) {
    data.previous_host_ns.reset();
    data.previous_sdk_us.reset();
    data.previous_es_us.reset();
    data.previous_ee_us.reset();
    data.previous_imu_last_us.reset();
}

std::string assessment(
    const RunData& data,
    const SequenceSummary& sequence,
    std::size_t unrecovered_faults) {
    if (data.decoded_frames == 0 || data.fault_operation_failures != 0 ||
        data.fault_recovery_failures != 0 || unrecovered_faults != 0) {
        return "fail";
    }
    if (data.timeouts != 0 || data.decode_errors != 0 || data.mode_mismatches != 0 ||
        sequence.drops != 0 || sequence.duplicates != 0 || sequence.out_of_order != 0) {
        return "warn";
    }
    return "pass";
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
        } else if (arg == "--rss-sample-ms" && i + 1 < argc) {
            options.rss_sample_ms = parse_u32(argv[++i], "RSS sample interval");
        } else if (arg == "--stop-start-every-frames" && i + 1 < argc) {
            options.stop_start_every_frames = parse_u64(argv[++i], "stop/start interval");
        } else if (arg == "--stop-start-pause-ms" && i + 1 < argc) {
            options.stop_start_pause_ms = parse_u32(argv[++i], "stop/start pause");
        } else if (arg == "--reconnect-every-frames" && i + 1 < argc) {
            options.reconnect_every_frames = parse_u64(argv[++i], "reconnect interval");
        } else if (arg == "--reconnect-pause-ms" && i + 1 < argc) {
            options.reconnect_pause_ms = parse_u32(argv[++i], "reconnect pause");
        } else if (arg == "--recovery-timeout-ms" && i + 1 < argc) {
            options.recovery_timeout_ms = parse_u32(argv[++i], "recovery timeout");
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
    if (options.recovery_timeout_ms == 0) {
        std::cerr << "recovery timeout must be greater than zero\n";
        return 2;
    }

    const std::string csv_path = options.output_prefix + ".csv";
    const std::string rss_path = options.output_prefix + ".rss.csv";
    const std::string events_path = options.output_prefix + ".events.csv";
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

        auto stream = std::make_unique<bividi::nori::Stream>(options.stream);
        const auto selected_mode = stream->mode();
        bividi::nori::DecxinPipeline pipeline(bividi::nori::NormalizationOwnership::own_output);

        std::cout << "warming up device=" << options.stream.device_index
                  << " mode=" << options.stream.mode_index
                  << ' ' << selected_mode.width << 'x' << selected_mode.height
                  << '@' << selected_mode.fps << ' '
                  << bividi::nori::transport_format_name(selected_mode.format)
                  << " frames=" << options.warmup_frames << '\n';

        RunData data{};
        for (std::uint32_t i = 0; i < options.warmup_frames; ++i) {
            auto raw = stream->next_frame();
            if (!raw.valid()) continue;
            try {
                auto capture = pipeline.decode(raw);
                raw.lease.reset();
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
        SequenceSummary sequence_total{};
        std::uint64_t continuity_epoch = 0;

        std::ofstream csv(csv_path, std::ios::binary | std::ios::trunc);
        if (!csv) throw std::runtime_error("cannot open CSV output: " + csv_path);
        csv << "sample_index,continuity_epoch,recovery_event_id,sequence,host_receive_ns,host_interval_us,"
               "sdk_timestamp_encoding,sdk_timestamp_us,sdk_interval_us,"
               "exposure_start_raw_us,exposure_end_raw_us,"
               "exposure_start_extended_us,exposure_end_extended_us,"
               "es_interval_us,ee_interval_us,exposure_duration_us,"
               "imu_total_samples,imu_valid_samples,imu_first_us,imu_last_us,"
               "imu_cross_frame_gap_us,raw_bytes,transport,width,height,"
               "vendor_buffer_index,vendor_buffer_offset\n";

        std::vector<FaultEvent> events;
        std::optional<std::size_t> pending_event;
        std::uint64_t next_stop_start_frame = options.stop_start_every_frames;
        std::uint64_t next_reconnect_frame = options.reconnect_every_frames;
        std::optional<std::uint64_t> last_sequence;
        std::optional<std::uint32_t> last_es_raw;
        bool fatal_fault = false;

        const auto measurement_wall_start = Clock::now();
        auto next_rss_sample = measurement_wall_start;

        auto sample_rss = [&](bool force) {
            if (options.rss_sample_ms == 0) return;
            const auto now = Clock::now();
            if (!force && now < next_rss_sample) return;
            const auto rss = bividi::characterization::process_resident_set_bytes();
            if (rss.has_value()) {
                const double elapsed = std::chrono::duration<double>(now - measurement_wall_start).count();
                data.rss_time_s.push_back(elapsed);
                data.rss_bytes.push_back(static_cast<double>(*rss));
            } else {
                ++data.rss_sample_failures;
            }
            next_rss_sample = now + std::chrono::milliseconds(options.rss_sample_ms);
        };

        auto close_sequence_epoch = [&] {
            bividi::characterization::add_sequence_summary(sequence_total, sequence.summary());
            sequence.reset();
            ++continuity_epoch;
            reset_interval_baselines(data);
        };

        auto check_recovery_timeout = [&]() -> bool {
            if (!pending_event.has_value()) return false;
            auto& event = events[*pending_event];
            const auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                Clock::now() - event.started_at).count();
            if (elapsed_ms <= static_cast<std::int64_t>(options.recovery_timeout_ms)) return false;
            event.error = "recovery timeout waiting for first valid decoded frame";
            ++data.fault_recovery_failures;
            pending_event.reset();
            return true;
        };

        sample_rss(true);
        while (true) {
            sample_rss(false);
            if (check_recovery_timeout()) {
                fatal_fault = true;
                break;
            }

            const double wall_elapsed =
                std::chrono::duration<double>(Clock::now() - measurement_wall_start).count();
            if (wall_elapsed >= options.duration_s) break;
            if (options.frame_limit != 0 && data.decoded_frames >= options.frame_limit) break;

            auto raw = stream->next_frame();
            if (!raw.valid()) {
                ++data.timeouts;
                ++data.current_timeout_streak;
                data.max_timeout_streak = std::max(data.max_timeout_streak, data.current_timeout_streak);
                continue;
            }
            data.current_timeout_streak = 0;
            ++data.raw_frames;
            const auto raw_size = raw.size;
            const auto raw_mode = raw.mode;
            const auto vendor_buffer_index = raw.vendor_buffer_index;
            const auto vendor_buffer_offset = raw.vendor_buffer_offset;
            if (!mode_matches(selected_mode, raw_mode)) ++data.mode_mismatches;

            DecodedCapture capture{};
            try {
                capture = pipeline.decode(raw);
                raw.lease.reset();
            } catch (const std::exception& error) {
                raw.lease.reset();
                ++data.decode_errors;
                ++data.current_decode_error_streak;
                data.max_decode_error_streak =
                    std::max(data.max_decode_error_streak, data.current_decode_error_streak);
                std::cerr << "decode error after raw frame " << data.raw_frames
                          << ": " << error.what() << '\n';
                pipeline.reset_timestamps();
                reset_interval_baselines(data);
                continue;
            }
            if (!capture.valid()) {
                ++data.decode_errors;
                ++data.current_decode_error_streak;
                data.max_decode_error_streak =
                    std::max(data.max_decode_error_streak, data.current_decode_error_streak);
                pipeline.reset_timestamps();
                reset_interval_baselines(data);
                continue;
            }
            data.current_decode_error_streak = 0;

            ++data.decoded_frames;
            sequence.observe(capture.decoded.sequence);
            data.raw_bytes.push_back(static_cast<double>(raw_size));

            std::optional<std::uint64_t> recovered_event_id;
            if (pending_event.has_value()) {
                auto& event = events[*pending_event];
                event.recovered = true;
                event.recovery_ms = std::chrono::duration<double, std::milli>(
                    Clock::now() - event.started_at).count();
                event.post_sequence = capture.decoded.sequence;
                event.post_es_raw_us = capture.decoded.timing.header.exposure_start_raw_us;
                if (event.pre_sequence.has_value()) {
                    event.sequence_reset_observed = *event.post_sequence <= *event.pre_sequence;
                }
                if (event.pre_es_raw_us.has_value()) {
                    event.device_time_reset_observed = *event.post_es_raw_us < *event.pre_es_raw_us;
                }
                data.recovery_latency_ms.push_back(event.recovery_ms);
                recovered_event_id = event.id;
                pending_event.reset();
            }

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
                << continuity_epoch << ','
                << optional_u64(recovered_event_id) << ','
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

            last_sequence = capture.decoded.sequence;
            last_es_raw = capture.decoded.timing.header.exposure_start_raw_us;

            if (!pending_event.has_value()) {
                std::optional<FaultKind> due_fault;
                std::uint32_t pause_ms = 0;
                if (options.reconnect_every_frames != 0 &&
                    data.decoded_frames >= next_reconnect_frame) {
                    due_fault = FaultKind::reconnect;
                    pause_ms = options.reconnect_pause_ms;
                    next_reconnect_frame += options.reconnect_every_frames;
                } else if (options.stop_start_every_frames != 0 &&
                           data.decoded_frames >= next_stop_start_frame) {
                    due_fault = FaultKind::stop_start;
                    pause_ms = options.stop_start_pause_ms;
                    next_stop_start_frame += options.stop_start_every_frames;
                }

                if (due_fault.has_value()) {
                    FaultEvent event{};
                    event.id = events.size() + 1;
                    event.kind = *due_fault;
                    event.after_decoded_frame = data.decoded_frames;
                    event.pause_ms = pause_ms;
                    event.started_at = Clock::now();
                    event.started_elapsed_s = std::chrono::duration<double>(
                        event.started_at - measurement_wall_start).count();
                    event.pre_sequence = last_sequence;
                    event.pre_es_raw_us = last_es_raw;
                    events.push_back(event);
                    const auto event_index = events.size() - 1;

                    close_sequence_epoch();
                    try {
                        if (*due_fault == FaultKind::stop_start) {
                            stream->stop_video();
                            if (pause_ms != 0) {
                                std::this_thread::sleep_for(std::chrono::milliseconds(pause_ms));
                            }
                            stream->start_video();
                        } else {
                            stream.reset();
                            if (pause_ms != 0) {
                                std::this_thread::sleep_for(std::chrono::milliseconds(pause_ms));
                            }
                            stream = std::make_unique<bividi::nori::Stream>(options.stream);
                            if (!mode_matches(selected_mode, stream->mode())) ++data.mode_mismatches;
                            pipeline.reset_timestamps();
                        }
                        events[event_index].operation_succeeded = true;
                        pending_event = event_index;
                        std::cout << "fault event " << events[event_index].id
                                  << " type=" << fault_kind_name(*due_fault)
                                  << " after_frame=" << data.decoded_frames << '\n';
                    } catch (const std::exception& error) {
                        events[event_index].error = error.what();
                        ++data.fault_operation_failures;
                        fatal_fault = true;
                        break;
                    }
                    sample_rss(true);
                }
            }
        }

        if (pending_event.has_value()) {
            auto& event = events[*pending_event];
            if (event.error.empty()) event.error = "measurement ended before recovery frame";
            ++data.fault_recovery_failures;
            pending_event.reset();
        }

        bividi::characterization::add_sequence_summary(sequence_total, sequence.summary());
        sample_rss(true);
        csv.flush();
        if (!csv) throw std::runtime_error("failed while writing CSV output: " + csv_path);

        std::ofstream rss_csv(rss_path, std::ios::binary | std::ios::trunc);
        if (!rss_csv) throw std::runtime_error("cannot open RSS output: " + rss_path);
        rss_csv << "sample_index,elapsed_s,rss_bytes,rss_mib\n";
        for (std::size_t i = 0; i < data.rss_bytes.size(); ++i) {
            rss_csv << i << ',' << std::setprecision(12) << data.rss_time_s[i] << ','
                    << static_cast<std::uint64_t>(data.rss_bytes[i]) << ','
                    << data.rss_bytes[i] / (1024.0 * 1024.0) << '\n';
        }
        rss_csv.flush();
        if (!rss_csv) throw std::runtime_error("failed while writing RSS output: " + rss_path);

        std::ofstream events_csv(events_path, std::ios::binary | std::ios::trunc);
        if (!events_csv) throw std::runtime_error("cannot open event output: " + events_path);
        events_csv << "event_id,type,after_decoded_frame,started_elapsed_s,pause_ms,"
                      "operation_succeeded,recovered,recovery_ms,pre_sequence,post_sequence,"
                      "sequence_reset_observed,pre_es_raw_us,post_es_raw_us,"
                      "device_time_reset_observed,error\n";
        for (const auto& event : events) {
            events_csv << event.id << ',' << fault_kind_name(event.kind) << ','
                       << event.after_decoded_frame << ',' << event.started_elapsed_s << ','
                       << event.pause_ms << ','
                       << (event.operation_succeeded ? "true" : "false") << ','
                       << (event.recovered ? "true" : "false") << ','
                       << event.recovery_ms << ','
                       << optional_u64(event.pre_sequence) << ','
                       << optional_u64(event.post_sequence) << ','
                       << optional_bool_csv(event.sequence_reset_observed) << ','
                       << optional_u32(event.pre_es_raw_us) << ','
                       << optional_u32(event.post_es_raw_us) << ','
                       << optional_bool_csv(event.device_time_reset_observed) << ','
                       << csv_escape(event.error) << '\n';
        }
        events_csv.flush();
        if (!events_csv) throw std::runtime_error("failed while writing event output: " + events_path);

        if (data.decoded_frames == 0) {
            std::cerr << "no decoded frames captured; artifacts were written but summary is not meaningful\n";
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

        const auto host_stats = bividi::characterization::summarize(data.host_interval_us);
        const auto sdk_stats = bividi::characterization::summarize(data.sdk_interval_us);
        const auto es_stats = bividi::characterization::summarize(data.es_interval_us);
        const auto ee_stats = bividi::characterization::summarize(data.ee_interval_us);
        const auto exposure_stats = bividi::characterization::summarize(data.exposure_duration_us);
        const auto imu_interval_stats = bividi::characterization::summarize(data.imu_interval_us);
        const auto imu_gap_stats = bividi::characterization::summarize(data.imu_cross_frame_gap_us);
        const auto imu_count_stats = bividi::characterization::summarize(data.imu_valid_samples_per_frame);
        const auto byte_stats = bividi::characterization::summarize(data.raw_bytes);
        const auto recovery_stats = bividi::characterization::summarize(data.recovery_latency_ms);
        const auto rss_stats = bividi::characterization::summarize(data.rss_bytes);
        const auto rss_trend = bividi::characterization::linear_trend(data.rss_time_s, data.rss_bytes);

        std::size_t unrecovered_faults = 0;
        std::size_t reconnect_events = 0;
        std::size_t stop_start_events = 0;
        std::size_t sequence_resets = 0;
        std::size_t device_time_resets = 0;
        for (const auto& event : events) {
            if (!event.recovered) ++unrecovered_faults;
            if (event.kind == FaultKind::reconnect) ++reconnect_events;
            else ++stop_start_events;
            if (event.sequence_reset_observed.value_or(false)) ++sequence_resets;
            if (event.device_time_reset_observed.value_or(false)) ++device_time_resets;
        }

        const auto run_assessment = assessment(data, sequence_total, unrecovered_faults);
        const double rss_growth_mib_per_hour =
            rss_trend.slope_per_second * 3600.0 / (1024.0 * 1024.0);

        std::ofstream json(json_path, std::ios::binary | std::ios::trunc);
        if (!json) throw std::runtime_error("cannot open JSON output: " + json_path);
        json << std::setprecision(12);
        json << "{\n"
             << "  \"schema\": \"bividi.nori.characterization.v2\",\n"
             << "  \"assessment\": \"" << run_assessment << "\",\n"
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
             << "    \"max_timeout_streak\": " << data.max_timeout_streak << ",\n"
             << "    \"decode_errors\": " << data.decode_errors << ",\n"
             << "    \"max_decode_error_streak\": " << data.max_decode_error_streak << ",\n"
             << "    \"mode_mismatches\": " << data.mode_mismatches << ",\n"
             << "    \"sdk_timestamp_encoding_changes\": " << data.sdk_timestamp_encoding_changes << ",\n"
             << "    \"measured_elapsed_s\": " << measured_elapsed_s << ",\n"
             << "    \"measured_fps\": " << measured_fps << ",\n"
             << "    \"nominal_expected_frames_over_measured_elapsed\": "
             << selected_mode.fps * measured_elapsed_s << ",\n"
             << "    \"fatal_fault\": " << (fatal_fault ? "true" : "false") << "\n"
             << "  },\n"
             << "  \"sequence_within_active_epochs\": {\n"
             << "    \"epochs\": " << (continuity_epoch + 1) << ",\n"
             << "    \"observations\": " << sequence_total.observations << ",\n"
             << "    \"drops\": " << sequence_total.drops << ",\n"
             << "    \"duplicates\": " << sequence_total.duplicates << ",\n"
             << "    \"out_of_order\": " << sequence_total.out_of_order << ",\n"
             << "    \"wraps\": " << sequence_total.wraps << "\n"
             << "  },\n"
             << "  \"fault_injection\": {\n"
             << "    \"stop_start_every_frames\": " << options.stop_start_every_frames << ",\n"
             << "    \"stop_start_pause_ms\": " << options.stop_start_pause_ms << ",\n"
             << "    \"reconnect_every_frames\": " << options.reconnect_every_frames << ",\n"
             << "    \"reconnect_pause_ms\": " << options.reconnect_pause_ms << ",\n"
             << "    \"recovery_timeout_ms\": " << options.recovery_timeout_ms << ",\n"
             << "    \"events\": " << events.size() << ",\n"
             << "    \"stop_start_events\": " << stop_start_events << ",\n"
             << "    \"reconnect_events\": " << reconnect_events << ",\n"
             << "    \"operation_failures\": " << data.fault_operation_failures << ",\n"
             << "    \"recovery_failures\": " << data.fault_recovery_failures << ",\n"
             << "    \"unrecovered_events\": " << unrecovered_faults << ",\n"
             << "    \"sequence_resets_observed\": " << sequence_resets << ",\n"
             << "    \"device_time_resets_observed\": " << device_time_resets << ",\n"
             << "    \"recovery_latency_ms\": ";
        write_distribution(json, recovery_stats);
        json << "\n  },\n"
             << "  \"memory\": {\n"
             << "    \"rss_sample_ms\": " << options.rss_sample_ms << ",\n"
             << "    \"sample_failures\": " << data.rss_sample_failures << ",\n"
             << "    \"rss_bytes\": ";
        write_distribution(json, rss_stats);
        json << ",\n    \"linear_trend\": ";
        write_trend(json, rss_trend);
        json << ",\n"
             << "    \"growth_mib_per_hour\": " << rss_growth_mib_per_hour << ",\n"
             << "    \"note\": \"RSS slope is descriptive evidence, not by itself a memory-leak verdict. High-rate summary telemetry is bounded so the characterizer does not grow linearly just by retaining percentile inputs.\"\n"
             << "  },\n"
             << "  \"summary_sampling\": {\n"
             << "    \"capacity_per_high_rate_metric\": " << data.host_interval_us.capacity() << ",\n"
             << "    \"host_interval_seen\": " << data.host_interval_us.seen_count() << ",\n"
             << "    \"host_interval_retained\": " << data.host_interval_us.size() << ",\n"
             << "    \"host_interval_stride\": " << data.host_interval_us.sample_stride() << ",\n"
             << "    \"imu_interval_seen\": " << data.imu_interval_us.seen_count() << ",\n"
             << "    \"imu_interval_retained\": " << data.imu_interval_us.size() << ",\n"
             << "    \"imu_interval_stride\": " << data.imu_interval_us.sample_stride() << ",\n"
             << "    \"note\": \"When a high-rate series reaches capacity, retained samples are deterministically decimated across the run. The per-frame CSV remains the lossless evidence source.\"\n"
             << "  },\n"
             << "  \"distributions\": {\n";

        json << "    \"host_interval_us\": "; write_distribution(json, host_stats); json << ",\n";
        json << "    \"sdk_interval_us\": "; write_distribution(json, sdk_stats); json << ",\n";
        json << "    \"exposure_start_interval_us\": "; write_distribution(json, es_stats); json << ",\n";
        json << "    \"exposure_end_interval_us\": "; write_distribution(json, ee_stats); json << ",\n";
        json << "    \"exposure_duration_us\": "; write_distribution(json, exposure_stats); json << ",\n";
        json << "    \"imu_interval_us\": "; write_distribution(json, imu_interval_stats); json << ",\n";
        json << "    \"imu_cross_frame_gap_us\": "; write_distribution(json, imu_gap_stats); json << ",\n";
        json << "    \"imu_valid_samples_per_frame\": "; write_distribution(json, imu_count_stats); json << ",\n";
        json << "    \"raw_frame_bytes\": "; write_distribution(json, byte_stats); json << "\n";

        json << "  },\n"
             << "  \"events\": [\n";
        for (std::size_t i = 0; i < events.size(); ++i) {
            const auto& event = events[i];
            json << "    {\"id\":" << event.id
                 << ",\"type\":\"" << fault_kind_name(event.kind) << "\""
                 << ",\"after_decoded_frame\":" << event.after_decoded_frame
                 << ",\"started_elapsed_s\":" << event.started_elapsed_s
                 << ",\"pause_ms\":" << event.pause_ms
                 << ",\"operation_succeeded\":" << (event.operation_succeeded ? "true" : "false")
                 << ",\"recovered\":" << (event.recovered ? "true" : "false")
                 << ",\"recovery_ms\":" << event.recovery_ms
                 << ",\"pre_sequence\":";
            write_json_optional_u64(json, event.pre_sequence);
            json << ",\"post_sequence\":";
            write_json_optional_u64(json, event.post_sequence);
            json << ",\"sequence_reset_observed\":";
            write_json_optional_bool(json, event.sequence_reset_observed);
            json << ",\"pre_es_raw_us\":";
            write_json_optional_u32(json, event.pre_es_raw_us);
            json << ",\"post_es_raw_us\":";
            write_json_optional_u32(json, event.post_es_raw_us);
            json << ",\"device_time_reset_observed\":";
            write_json_optional_bool(json, event.device_time_reset_observed);
            json << ",\"error\":\"" << json_escape(event.error) << "\"}";
            if (i + 1 != events.size()) json << ',';
            json << '\n';
        }
        json << "  ],\n"
             << "  \"clock_domain_note\": \"Host monotonic, SDK frame time, and embedded DECXIN device time are summarized independently. Planned stop/reconnect gaps start a new continuity epoch and are measured as recovery events rather than misclassified as spontaneous drops/jitter.\",\n"
             << "  \"artifacts\": {\n"
             << "    \"trace_csv\": \"" << json_escape(csv_path) << "\",\n"
             << "    \"rss_csv\": \"" << json_escape(rss_path) << "\",\n"
             << "    \"events_csv\": \"" << json_escape(events_path) << "\",\n"
             << "    \"summary_json\": \"" << json_escape(json_path) << "\"\n"
             << "  }\n"
             << "}\n";
        json.flush();
        if (!json) throw std::runtime_error("failed while writing JSON output: " + json_path);

        std::cout << "characterization complete assessment=" << run_assessment << '\n'
                  << "  decoded_frames=" << data.decoded_frames
                  << " measured_fps=" << measured_fps
                  << " drops=" << sequence_total.drops
                  << " duplicates=" << sequence_total.duplicates
                  << " out_of_order=" << sequence_total.out_of_order << '\n'
                  << "  fault_events=" << events.size()
                  << " unrecovered=" << unrecovered_faults
                  << " recovery_p95_ms=" << recovery_stats.p95 << '\n'
                  << "  RSS_MiB p50=" << rss_stats.p50 / (1024.0 * 1024.0)
                  << " p99=" << rss_stats.p99 / (1024.0 * 1024.0)
                  << " growth_MiB_per_hour=" << rss_growth_mib_per_hour << '\n'
                  << "  csv=" << csv_path << '\n'
                  << "  rss=" << rss_path << '\n'
                  << "  events=" << events_path << '\n'
                  << "  json=" << json_path << '\n';

        return run_assessment == "fail" ? 7 : 0;
    } catch (const std::exception& error) {
        std::cerr << "bividi-nori-characterize: " << error.what() << '\n';
        return 3;
    }
}
