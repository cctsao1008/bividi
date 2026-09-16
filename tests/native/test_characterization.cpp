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
    using bividi::characterization::SequenceTracker;
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

    std::cout << "bividi characterization test: PASS\n";
    return 0;
}
