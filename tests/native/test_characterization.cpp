#include "bividi/characterization.hpp"

#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <vector>

namespace {

bool near(double a, double b, double eps = 1e-9) {
    return std::abs(a - b) <= eps;
}

}  // namespace

int main() {
    using bividi::characterization::BoundedSampleSeries;
    using bividi::characterization::SequenceSummary;
    using bividi::characterization::SequenceTracker;
    using bividi::characterization::add_sequence_summary;
    using bividi::characterization::linear_trend;
    using bividi::characterization::process_resident_set_bytes;
    using bividi::characterization::summarize;

    {
        const auto s = summarize({1.0, 2.0, 3.0, 4.0, 5.0});
        assert(s.count == 5);
        assert(near(s.minimum, 1.0));
        assert(near(s.maximum, 5.0));
        assert(near(s.mean, 3.0));
        assert(near(s.p50, 3.0));
        assert(near(s.p95, 4.8));
        assert(near(s.p99, 4.96));
    }

    {
        const auto nan = std::numeric_limits<double>::quiet_NaN();
        const auto s = summarize({nan, 10.0, 20.0});
        assert(s.count == 2);
        assert(near(s.minimum, 10.0));
        assert(near(s.maximum, 20.0));
        assert(near(s.mean, 15.0));
        assert(near(s.p50, 15.0));
    }

    {
        BoundedSampleSeries samples(4);
        for (int i = 0; i < 20; ++i) samples.push_back(static_cast<double>(i));
        assert(samples.seen_count() == 20);
        assert(samples.size() <= 4);
        assert(samples.sample_stride() >= 2);
        const auto& retained = samples.values();
        for (std::size_t i = 1; i < retained.size(); ++i) {
            assert(retained[i] > retained[i - 1]);
        }
    }

    {
        const auto t = linear_trend({0.0, 1.0, 2.0, 3.0}, {100.0, 110.0, 120.0, 130.0});
        assert(t.count == 4);
        assert(near(t.slope_per_second, 10.0));
        assert(near(t.intercept, 100.0));
        assert(near(t.r_squared, 1.0));
    }

    {
        const auto nan = std::numeric_limits<double>::quiet_NaN();
        const auto t = linear_trend({0.0, 1.0, 2.0}, {10.0, nan, 14.0});
        assert(t.count == 2);
        assert(near(t.slope_per_second, 2.0));
        assert(near(t.intercept, 10.0));
        assert(near(t.r_squared, 1.0));
    }

    {
        SequenceTracker tracker(64);
        tracker.observe(100);
        tracker.observe(101);
        tracker.observe(104);
        tracker.observe(104);
        tracker.observe(103);
        const auto s = tracker.summary();
        assert(s.observations == 5);
        assert(s.drops == 2);
        assert(s.duplicates == 1);
        assert(s.out_of_order == 1);
        assert(s.wraps == 0);
    }

    {
        SequenceTracker tracker(32);
        tracker.observe(0xfffffffeULL);
        tracker.observe(0xffffffffULL);
        tracker.observe(1);
        const auto s = tracker.summary();
        assert(s.observations == 3);
        assert(s.drops == 1);  // sequence 0 was skipped across the wrap
        assert(s.duplicates == 0);
        assert(s.out_of_order == 0);
        assert(s.wraps == 1);
    }

    {
        SequenceSummary total{};
        add_sequence_summary(total, SequenceSummary{10, 2, 1, 0, 1});
        add_sequence_summary(total, SequenceSummary{5, 1, 0, 2, 0});
        assert(total.observations == 15);
        assert(total.drops == 3);
        assert(total.duplicates == 1);
        assert(total.out_of_order == 2);
        assert(total.wraps == 1);
    }

#if defined(_WIN32) || defined(__APPLE__) || defined(__linux__)
    {
        const auto rss = process_resident_set_bytes();
        assert(rss.has_value());
        assert(*rss > 0);
    }
#endif

    std::cout << "bividi characterization test: PASS\n";
    return 0;
}
