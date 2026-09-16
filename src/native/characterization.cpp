#include "bividi/characterization.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <limits>
#include <utility>
#include <vector>

#if defined(_WIN32)
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#elif defined(__APPLE__)
#include <mach/mach.h>
#elif defined(__linux__)
#include <unistd.h>
#endif

namespace bividi::characterization {
namespace {

double percentile(const std::vector<double>& sorted, double q) noexcept {
    if (sorted.empty()) return 0.0;
    if (sorted.size() == 1) return sorted.front();

    const double position = q * static_cast<double>(sorted.size() - 1);
    const auto lower = static_cast<std::size_t>(std::floor(position));
    const auto upper = static_cast<std::size_t>(std::ceil(position));
    if (lower == upper) return sorted[lower];

    const double weight = position - static_cast<double>(lower);
    return sorted[lower] * (1.0 - weight) + sorted[upper] * weight;
}

}  // namespace

DistributionSummary summarize(const std::vector<double>& values) {
    DistributionSummary result{};
    if (values.empty()) return result;

    std::vector<double> sorted;
    sorted.reserve(values.size());
    double sum = 0.0;
    for (const double value : values) {
        if (!std::isfinite(value)) continue;
        sorted.push_back(value);
        sum += value;
    }
    if (sorted.empty()) return result;

    std::sort(sorted.begin(), sorted.end());
    result.count = sorted.size();
    result.minimum = sorted.front();
    result.maximum = sorted.back();
    result.mean = sum / static_cast<double>(sorted.size());
    result.p50 = percentile(sorted, 0.50);
    result.p95 = percentile(sorted, 0.95);
    result.p99 = percentile(sorted, 0.99);
    return result;
}

LinearTrendSummary linear_trend(
    const std::vector<double>& time_seconds,
    const std::vector<double>& values) {
    LinearTrendSummary result{};
    const auto count = std::min(time_seconds.size(), values.size());
    if (count == 0) return result;

    std::vector<std::pair<double, double>> samples;
    samples.reserve(count);
    double sum_x = 0.0;
    double sum_y = 0.0;
    for (std::size_t i = 0; i < count; ++i) {
        const double x = time_seconds[i];
        const double y = values[i];
        if (!std::isfinite(x) || !std::isfinite(y)) continue;
        samples.emplace_back(x, y);
        sum_x += x;
        sum_y += y;
    }
    if (samples.empty()) return result;

    result.count = samples.size();
    const double mean_x = sum_x / static_cast<double>(samples.size());
    const double mean_y = sum_y / static_cast<double>(samples.size());
    result.intercept = mean_y;
    if (samples.size() < 2) return result;

    double sxx = 0.0;
    double sxy = 0.0;
    double syy = 0.0;
    for (const auto& sample : samples) {
        const double dx = sample.first - mean_x;
        const double dy = sample.second - mean_y;
        sxx += dx * dx;
        sxy += dx * dy;
        syy += dy * dy;
    }
    if (sxx <= std::numeric_limits<double>::epsilon()) return result;

    result.slope_per_second = sxy / sxx;
    result.intercept = mean_y - result.slope_per_second * mean_x;
    if (syy <= std::numeric_limits<double>::epsilon()) {
        result.r_squared = 1.0;
    } else {
        result.r_squared = std::clamp((sxy * sxy) / (sxx * syy), 0.0, 1.0);
    }
    return result;
}

std::optional<std::uint64_t> process_resident_set_bytes() noexcept {
#if defined(_WIN32)
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = sizeof(counters);
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters)) == 0) {
        return std::nullopt;
    }
    return static_cast<std::uint64_t>(counters.WorkingSetSize);
#elif defined(__APPLE__)
    mach_task_basic_info info{};
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(
            mach_task_self(),
            MACH_TASK_BASIC_INFO,
            reinterpret_cast<task_info_t>(&info),
            &count) != KERN_SUCCESS) {
        return std::nullopt;
    }
    return static_cast<std::uint64_t>(info.resident_size);
#elif defined(__linux__)
    std::ifstream statm("/proc/self/statm");
    std::uint64_t total_pages = 0;
    std::uint64_t resident_pages = 0;
    if (!(statm >> total_pages >> resident_pages)) return std::nullopt;
    (void)total_pages;
    const long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) return std::nullopt;
    const auto page = static_cast<std::uint64_t>(page_size);
    if (resident_pages > std::numeric_limits<std::uint64_t>::max() / page) {
        return std::nullopt;
    }
    return resident_pages * page;
#else
    return std::nullopt;
#endif
}

void add_sequence_summary(SequenceSummary& total, const SequenceSummary& epoch) noexcept {
    total.observations += epoch.observations;
    total.drops += epoch.drops;
    total.duplicates += epoch.duplicates;
    total.out_of_order += epoch.out_of_order;
    total.wraps += epoch.wraps;
}

SequenceTracker::SequenceTracker(unsigned bit_width) noexcept
    : bit_width_(bit_width == 32 ? 32u : 64u) {}

void SequenceTracker::reset() noexcept {
    has_last_ = false;
    last_ = 0;
    summary_ = {};
}

void SequenceTracker::observe(std::uint64_t sequence) noexcept {
    ++summary_.observations;
    if (!has_last_) {
        has_last_ = true;
        last_ = sequence;
        return;
    }

    if (sequence == last_) {
        ++summary_.duplicates;
        return;
    }

    if (sequence > last_) {
        const auto advance = sequence - last_;
        if (advance > 1) summary_.drops += advance - 1;
        last_ = sequence;
        return;
    }

    if (bit_width_ == 32) {
        constexpr std::uint64_t kMax = 0xffffffffULL;
        constexpr std::uint64_t kHalf = 0x80000000ULL;
        if (last_ <= kMax && sequence <= kMax && last_ - sequence > kHalf) {
            const auto advance = (kMax - last_) + 1 + sequence;
            if (advance > 1) summary_.drops += advance - 1;
            ++summary_.wraps;
            last_ = sequence;
            return;
        }
    }

    ++summary_.out_of_order;
}

}  // namespace bividi::characterization
