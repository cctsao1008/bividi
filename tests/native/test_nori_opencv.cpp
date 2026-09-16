#include "bividi/nori_opencv.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

namespace {

bividi::nori::RawFrame make_raw(
    std::vector<std::uint8_t> bytes,
    bividi::nori::VideoMode mode,
    std::uint64_t sequence = 7) {
    auto* storage = new std::vector<std::uint8_t>(std::move(bytes));
    bividi::nori::RawFrame frame{};
    frame.lease = bividi::FrameLease::adopt(
        storage,
        [](std::vector<std::uint8_t>* owned) noexcept {
            delete owned;
        });
    frame.data = storage->data();
    frame.size = storage->size();
    frame.mode = mode;
    frame.sequence = sequence;
    frame.host_receive_monotonic_ns = 123456789;
    frame.sdk_timestamp.encoding = bividi::nori::SdkTimestampEncoding::seconds_microseconds;
    frame.sdk_timestamp.seconds = 12;
    frame.sdk_timestamp.microseconds = 345;
    return frame;
}

}  // namespace

int main() {
    using bividi::nori::TransportFormat;
    using bividi::nori::VideoMode;

    {
        VideoMode mode{};
        mode.width = 2;
        mode.height = 2;
        mode.format = TransportFormat::bgr24;
        mode.bottom_up = false;
        auto raw = make_raw({1,2,3,4,5,6,7,8,9,10,11,12}, mode);
        const auto raw_ptr = raw.data;
        const auto before = raw.lease.use_count();
        auto normalized = bividi::nori::normalize_to_bgr24(raw);
        assert(normalized.valid());
        assert(normalized.captured.transport.data == raw_ptr);
        assert(normalized.captured.transport.width == 2);
        assert(normalized.captured.transport.height == 2);
        assert(normalized.captured.transport.row_stride == 6);
        assert(normalized.captured.lease.use_count() == before + 1);
        assert(normalized.captured.sequence == 7);
        assert(normalized.sdk_timestamp.seconds == 12);
    }

    {
        VideoMode mode{};
        mode.width = 2;
        mode.height = 2;
        mode.format = TransportFormat::bgr24;
        mode.bottom_up = true;
        // Bottom row first, then top row.
        auto raw = make_raw({7,8,9,10,11,12,1,2,3,4,5,6}, mode);
        auto normalized = bividi::nori::normalize_to_bgr24(raw);
        const auto* out = normalized.captured.transport.data;
        assert(out != raw.data);
        assert(out[0] == 1 && out[1] == 2 && out[2] == 3);
        assert(out[6] == 7 && out[7] == 8 && out[8] == 9);
    }

    {
        VideoMode mode{};
        mode.width = 2;
        mode.height = 1;
        mode.format = TransportFormat::yuyv;
        auto raw = make_raw({128,128,128,128}, mode);
        auto normalized = bividi::nori::normalize_to_bgr24(raw);
        assert(normalized.captured.transport.width == 2);
        assert(normalized.captured.transport.height == 1);
        const auto* out = normalized.captured.transport.data;
        assert(std::abs(static_cast<int>(out[0]) - static_cast<int>(out[1])) <= 1);
        assert(std::abs(static_cast<int>(out[1]) - static_cast<int>(out[2])) <= 1);
    }

    {
        cv::Mat image(3, 4, CV_8UC3, cv::Scalar(20, 90, 180));
        std::vector<unsigned char> jpeg;
        assert(cv::imencode(".jpg", image, jpeg));

        VideoMode mode{};
        mode.width = 4;
        mode.height = 3;
        mode.format = TransportFormat::mjpeg;
        auto raw = make_raw(std::vector<std::uint8_t>(jpeg.begin(), jpeg.end()), mode);
        auto normalized = bividi::nori::normalize_to_bgr24(raw);
        assert(normalized.valid());
        assert(normalized.captured.transport.width == 4);
        assert(normalized.captured.transport.height == 3);
        assert(normalized.captured.transport.bytes_per_pixel == 3);
    }

    {
        VideoMode mode{};
        mode.width = 2;
        mode.height = 2;
        mode.format = TransportFormat::yuyv;
        auto raw = make_raw({1,2,3}, mode);
        bool threw = false;
        try {
            (void)bividi::nori::normalize_to_bgr24(raw);
        } catch (const bividi::nori::Error&) {
            threw = true;
        }
        assert(threw);
    }

    std::cout << "bividi Nori OpenCV normalization test: PASS\n";
    return 0;
}
