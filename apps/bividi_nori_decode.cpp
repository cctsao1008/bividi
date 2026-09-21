#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <exception>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <numeric>
#include <string>
#include <thread>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;

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

void print_sdk_time(const bividi::nori::SdkFrameTimestamp& timestamp) {
    std::cout << bividi::nori::sdk_timestamp_encoding_name(timestamp.encoding);
    if (timestamp.encoding == bividi::nori::SdkTimestampEncoding::seconds_microseconds) {
        std::cout << ':' << timestamp.seconds << '.' << timestamp.microseconds;
    } else if (timestamp.encoding == bividi::nori::SdkTimestampEncoding::windows_filetime_100ns) {
        std::cout << ':' << timestamp.filetime_100ns;
    }
}

struct SequenceStats {
    bool have_last = false;
    std::uint64_t first = 0;
    std::uint64_t last = 0;
    std::uint64_t observations = 0;
    std::uint64_t gap_events = 0;
    std::uint64_t missing = 0;
    std::uint64_t duplicates = 0;
    std::uint64_t out_of_order = 0;

    void observe(std::uint64_t sequence) noexcept {
        ++observations;
        if (!have_last) {
            have_last = true;
            first = last = sequence;
            return;
        }
        if (sequence == last) {
            ++duplicates;
            return;
        }
        if (sequence > last) {
            const auto delta = sequence - last;
            if (delta > 1) {
                ++gap_events;
                missing += delta - 1;
            }
            last = sequence;
            return;
        }
        ++out_of_order;
    }
};

struct Distribution {
    std::size_t count = 0;
    double minimum = 0.0;
    double maximum = 0.0;
    double mean = 0.0;
    double p50 = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
};

double percentile(const std::vector<double>& sorted, double q) {
    if (sorted.empty()) return 0.0;
    if (sorted.size() == 1) return sorted.front();
    const double position = q * static_cast<double>(sorted.size() - 1);
    const auto lower = static_cast<std::size_t>(position);
    const auto upper = std::min(lower + 1, sorted.size() - 1);
    const double weight = position - static_cast<double>(lower);
    return sorted[lower] * (1.0 - weight) + sorted[upper] * weight;
}

Distribution summarize(std::vector<double> values) {
    Distribution result{};
    if (values.empty()) return result;
    std::sort(values.begin(), values.end());
    result.count = values.size();
    result.minimum = values.front();
    result.maximum = values.back();
    result.mean = std::accumulate(values.begin(), values.end(), 0.0) /
                  static_cast<double>(values.size());
    result.p50 = percentile(values, 0.50);
    result.p95 = percentile(values, 0.95);
    result.p99 = percentile(values, 0.99);
    return result;
}

bividi::nori::RawFrame copy_raw_packet(const bividi::nori::RawFrame& raw) {
    if (!raw.valid()) throw bividi::nori::Error("cannot copy an invalid Nori raw frame");

    auto* bytes = new std::vector<std::uint8_t>(raw.data, raw.data + raw.size);
    bividi::nori::RawFrame owned = raw;
    owned.lease = bividi::FrameLease::adopt(
        bytes,
        [](std::vector<std::uint8_t>* storage) noexcept { delete storage; });
    owned.data = bytes->data();
    owned.size = bytes->size();
    return owned;
}

void print_sequence_summary(const char* name, const SequenceStats& stats) {
    std::cout << name << " observations=" << stats.observations;
    if (stats.have_last) {
        std::cout << " sequence=" << stats.first << "->" << stats.last;
    }
    std::cout << " gap_events=" << stats.gap_events
              << " missing=" << stats.missing
              << " duplicates=" << stats.duplicates
              << " out_of_order=" << stats.out_of_order << '\n';
}

int run_pipelined(
    const bividi::nori::StreamConfig& config,
    std::uint32_t frame_limit,
    std::uint32_t queue_depth) {
    if (queue_depth == 0) return 2;

    bividi::nori::Stream stream(config);
    const auto selected = stream.mode();
    std::cout << "pipelined decode stream device=" << stream.device_index()
              << " mode=" << config.mode_index
              << ' ' << selected.width << 'x' << selected.height << '@' << selected.fps
              << ' ' << bividi::nori::transport_format_name(selected.format)
              << " queue_depth=" << queue_depth << '\n';

    std::deque<bividi::nori::RawFrame> queue;
    std::mutex mutex;
    std::condition_variable wake;
    bool producer_done = false;
    std::atomic<bool> consumer_failed{false};
    std::string consumer_error;
    std::uint64_t queue_overflow_drops = 0;
    std::size_t max_queue_occupancy = 0;
    SequenceStats source_sequence;
    SequenceStats decoded_sequence;
    std::vector<double> decode_ms;
    decode_ms.reserve(frame_limit);
    std::uint64_t decoded_frames = 0;
    std::uint64_t decode_errors = 0;

    const auto total_started = Clock::now();

    std::thread consumer([&] {
        try {
            bividi::nori::DecxinPipeline pipeline(bividi::nori::NormalizationOwnership::own_output);
            for (;;) {
                bividi::nori::RawFrame raw;
                {
                    std::unique_lock<std::mutex> lock(mutex);
                    wake.wait(lock, [&] { return producer_done || !queue.empty(); });
                    if (queue.empty()) {
                        if (producer_done) break;
                        continue;
                    }
                    raw = std::move(queue.front());
                    queue.pop_front();
                }

                const auto started = Clock::now();
                try {
                    auto capture = pipeline.decode(raw);
                    const auto finished = Clock::now();
                    decode_ms.push_back(std::chrono::duration<double, std::milli>(finished - started).count());
                    if (!capture.valid()) {
                        ++decode_errors;
                        continue;
                    }
                    ++decoded_frames;
                    decoded_sequence.observe(capture.decoded.sequence);
                } catch (...) {
                    const auto finished = Clock::now();
                    decode_ms.push_back(std::chrono::duration<double, std::milli>(finished - started).count());
                    ++decode_errors;
                }
            }
        } catch (const std::exception& error) {
            consumer_error = error.what();
            consumer_failed = true;
        }
    });

    std::uint64_t raw_frames = 0;
    std::uint64_t timeouts = 0;
    const auto capture_started = Clock::now();
    while (raw_frames < frame_limit && !consumer_failed.load()) {
        auto raw = stream.next_frame();
        if (!raw.valid()) {
            ++timeouts;
            continue;
        }

        ++raw_frames;
        source_sequence.observe(raw.sequence);

        auto owned = copy_raw_packet(raw);
        raw.lease.reset();

        {
            std::lock_guard<std::mutex> lock(mutex);
            if (queue.size() >= queue_depth) {
                ++queue_overflow_drops;
            } else {
                queue.push_back(std::move(owned));
                max_queue_occupancy = std::max(max_queue_occupancy, queue.size());
            }
        }
        wake.notify_one();
    }
    const auto capture_finished = Clock::now();

    {
        std::lock_guard<std::mutex> lock(mutex);
        producer_done = true;
    }
    wake.notify_all();
    consumer.join();
    const auto total_finished = Clock::now();

    if (consumer_failed.load()) {
        std::cerr << "bividi-nori-decode: pipelined consumer failed: " << consumer_error << '\n';
        return 3;
    }

    const double capture_s = std::chrono::duration<double>(capture_finished - capture_started).count();
    const double total_s = std::chrono::duration<double>(total_finished - total_started).count();
    const auto latency = summarize(std::move(decode_ms));

    std::cout << std::fixed << std::setprecision(3);
    std::cout << "pipeline summary raw_frames=" << raw_frames
              << " decoded_frames=" << decoded_frames
              << " timeouts=" << timeouts
              << " decode_errors=" << decode_errors
              << " queue_overflow_drops=" << queue_overflow_drops
              << " max_queue_occupancy=" << max_queue_occupancy << '/' << queue_depth << '\n';
    print_sequence_summary("source", source_sequence);
    print_sequence_summary("decoded", decoded_sequence);
    std::cout << "capture elapsed_s=" << capture_s
              << " accepted_fps=" << (capture_s > 0.0 && raw_frames > 1
                    ? static_cast<double>(raw_frames - 1) / capture_s : 0.0)
              << '\n';
    std::cout << "total elapsed_s=" << total_s
              << " decoded_fps=" << (total_s > 0.0 ? static_cast<double>(decoded_frames) / total_s : 0.0)
              << '\n';
    std::cout << "decode_ms count=" << latency.count
              << " min=" << latency.minimum
              << " p50=" << latency.p50
              << " p95=" << latency.p95
              << " p99=" << latency.p99
              << " max=" << latency.maximum
              << " mean=" << latency.mean << '\n';

    return (source_sequence.missing == 0 && queue_overflow_drops == 0 && decode_errors == 0) ? 0 : 7;
}

}  // namespace

int main(int argc, char** argv) {
    bividi::nori::StreamConfig config{};
    std::uint32_t frame_limit = 1;
    std::uint32_t queue_depth = 0;

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
        } else if (arg == "--queue-depth" && i + 1 < argc) {
            queue_depth = parse_u32(argv[++i], "queue depth");
        } else if (arg == "--no-trigger-config") {
            config.configure_free_run = false;
        } else if (arg == "--help") {
            std::cout
                << "bividi-nori-decode [--device N] [--mode N] [--frames N] [--timeout-ms N] "
                   "[--queue-depth N] [--no-trigger-config]\n"
                << "  --queue-depth N   enable two-stage qualifier: copy raw transport, return vendor lease, "
                   "then decode from a bounded owned-packet queue\n";
            return 0;
        } else {
            std::cerr << "unknown/incomplete option: " << arg << '\n';
            return 2;
        }
    }

    try {
        if (queue_depth != 0) {
            return run_pipelined(config, frame_limit, queue_depth);
        }

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
