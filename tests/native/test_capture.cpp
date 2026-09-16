#include "bividi/capture.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

int main() {
    int releases = 0;
    std::vector<std::uint8_t> pixels(12, 0x2a);

    auto lease = bividi::FrameLease::adopt(
        new int(7),
        [&releases](int* token) noexcept {
            ++releases;
            delete token;
        });

    assert(lease.valid());
    assert(lease.use_count() == 1);

    const bividi::ImageView view{
        pixels.data(),
        2,
        2,
        6,
        3,
        bividi::PixelFormat::bgr24,
    };

    {
        bividi::CapturedFrame frame{
            lease,
            view,
            42,
            123456789,
        };

        assert(frame.valid());
        assert(frame.sequence == 42);
        assert(frame.host_receive_monotonic_ns == 123456789);
        assert(frame.lease.use_count() == 2);

        const auto copy = frame;
        assert(copy.valid());
        assert(copy.transport.data == pixels.data());
        assert(copy.lease.use_count() == 3);
        assert(releases == 0);
    }

    assert(releases == 0);
    assert(lease.use_count() == 1);
    lease.reset();
    assert(releases == 1);

    const bividi::CapturedFrame empty{};
    assert(!empty.valid());

    bividi::CaptureStatus status{};
    assert(status.state == bividi::CaptureState::idle);
    status.state = bividi::CaptureState::running;
    status.frames = 100;
    status.drops = 2;
    status.duplicates = 1;
    status.out_of_order = 3;
    assert(status.state == bividi::CaptureState::running);
    assert(status.frames == 100);
    assert(status.drops == 2);
    assert(status.duplicates == 1);
    assert(status.out_of_order == 3);

    std::cout << "bividi capture lifetime test: PASS\n";
    return 0;
}
