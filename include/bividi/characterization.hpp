#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace bividi::characterization {

struct DistributionSummary {
    std::size_t count = 0;
    double minimum = 0.0;
    double maximum = 0.0;
    double mean = 0.0;
    double p50 = 0.0;
    double p95 = 0.0;
    double p99 = 0.0;
};

// Deterministic linear-interpolated percentiles over a sorted copy of the
// finite inputs. Empty/all-non-finite input returns a zero-initialized summary.
[[nodiscard]] DistributionSummary summarize(const std::vector<double>& values);

struct SequenceSummary {
    std::uint64_t observations = 0;
    std::uint64_t drops = 0;
    std::uint64_t duplicates = 0;
    std::uint64_t out_of_order = 0;
    std::uint64_t wraps = 0;
};

// Small continuity tracker used by live characterization tools. A bit width of
// 32 matches Linux V4L2 sequence semantics; 64 disables wrap classification for
// normal practical runs and suits the Windows Nori frame number.
class SequenceTracker {
public:
    explicit SequenceTracker(unsigned bit_width = 64) noexcept;

    void reset() noexcept;
    void observe(std::uint64_t sequence) noexcept;

    [[nodiscard]] const SequenceSummary& summary() const noexcept { return summary_; }
    [[nodiscard]] bool has_last() const noexcept { return has_last_; }
    [[nodiscard]] std::uint64_t last() const noexcept { return last_; }

private:
    unsigned bit_width_ = 64;
    bool has_last_ = false;
    std::uint64_t last_ = 0;
    SequenceSummary summary_{};
};

}  // namespace bividi::characterization
