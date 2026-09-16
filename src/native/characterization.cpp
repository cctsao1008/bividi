#include "bividi/characterization.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

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
