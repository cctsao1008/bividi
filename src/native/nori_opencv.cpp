#include "bividi/nori_opencv.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <utility>

namespace bividi::nori {
namespace {

std::size_t packed_size(std::uint32_t width, std::uint32_t height, std::size_t bytes_per_pixel) {
    if (width == 0 || height == 0 || bytes_per_pixel == 0) {
        throw Error("cannot normalize a zero-sized Nori frame");
    }
    const auto w = static_cast<std::size_t>(width);
    const auto h = static_cast<std::size_t>(height);
    if (w > std::numeric_limits<std::size_t>::max() / h ||
        w * h > std::numeric_limits<std::size_t>::max() / bytes_per_pixel) {
        throw Error("Nori frame geometry overflows host size_t");
    }
    return w * h * bytes_per_pixel;
}

NormalizedFrame base_result(const RawFrame& raw) {
    NormalizedFrame result{};
    result.sdk_timestamp = raw.sdk_timestamp;
    result.source_mode = raw.mode;
    result.vendor_buffer_offset = raw.vendor_buffer_offset;
    result.captured.sequence = raw.sequence;
    result.captured.host_receive_monotonic_ns = raw.host_receive_monotonic_ns;
    return result;
}

void attach_owned_bgr(NormalizedFrame& result, cv::Mat image) {
    if (image.empty() || image.type() != CV_8UC3) {
        throw Error("Nori transport normalization did not produce BGR24");
    }

    auto* storage = new cv::Mat(std::move(image));
    result.captured.lease = FrameLease::adopt(
        storage,
        [](cv::Mat* owned) noexcept {
            delete owned;
        });
    result.captured.transport = ImageView{
        storage->data,
        static_cast<std::size_t>(storage->cols),
        static_cast<std::size_t>(storage->rows),
        storage->step,
        3,
        PixelFormat::bgr24,
    };
}

}  // namespace

NormalizedFrame normalize_to_bgr24(const RawFrame& raw) {
    if (!raw.valid()) {
        throw Error("cannot normalize an invalid Nori raw frame");
    }
    if (raw.mode.width == 0 || raw.mode.height == 0) {
        throw Error("Nori raw frame is missing image geometry");
    }

    auto result = base_result(raw);
    const auto width = static_cast<int>(raw.mode.width);
    const auto height = static_cast<int>(raw.mode.height);

    switch (raw.mode.format) {
        case TransportFormat::bgr24: {
            const auto required = packed_size(raw.mode.width, raw.mode.height, 3);
            if (raw.size < required) {
                throw Error("Nori BGR24 frame is shorter than its declared geometry");
            }

            if (!raw.mode.bottom_up) {
                result.captured.lease = raw.lease;
                result.captured.transport = ImageView{
                    raw.data,
                    raw.mode.width,
                    raw.mode.height,
                    static_cast<std::size_t>(raw.mode.width) * 3,
                    3,
                    PixelFormat::bgr24,
                };
                return result;
            }

            cv::Mat source(
                height,
                width,
                CV_8UC3,
                const_cast<std::uint8_t*>(raw.data),
                static_cast<std::size_t>(raw.mode.width) * 3);
            cv::Mat flipped;
            cv::flip(source, flipped, 0);
            attach_owned_bgr(result, std::move(flipped));
            break;
        }

        case TransportFormat::yuyv: {
            const auto required = packed_size(raw.mode.width, raw.mode.height, 2);
            if (raw.size < required) {
                throw Error("Nori YUYV frame is shorter than its declared geometry");
            }
            if ((raw.mode.width & 1U) != 0U) {
                throw Error("Nori YUYV width must be even");
            }

            cv::Mat source(
                height,
                width,
                CV_8UC2,
                const_cast<std::uint8_t*>(raw.data),
                static_cast<std::size_t>(raw.mode.width) * 2);
            cv::Mat decoded;
            cv::cvtColor(source, decoded, cv::COLOR_YUV2BGR_YUY2);
            attach_owned_bgr(result, std::move(decoded));
            break;
        }

        case TransportFormat::mjpeg: {
            if (raw.size > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
                throw Error("Nori MJPEG payload is too large for OpenCV decode");
            }
            cv::Mat encoded(
                1,
                static_cast<int>(raw.size),
                CV_8UC1,
                const_cast<std::uint8_t*>(raw.data));
            auto decoded = cv::imdecode(encoded, cv::IMREAD_COLOR);
            if (decoded.empty()) {
                throw Error("OpenCV failed to decode Nori MJPEG frame");
            }
            if (decoded.cols != width || decoded.rows != height) {
                throw Error("decoded Nori MJPEG geometry does not match the advertised mode");
            }
            attach_owned_bgr(result, std::move(decoded));
            break;
        }

        case TransportFormat::unknown:
            throw Error("unsupported Nori transport format");
    }

    if (!result.valid() || result.captured.transport.pixel_format != PixelFormat::bgr24) {
        throw Error("Nori transport normalization produced an invalid frame");
    }
    return result;
}

}  // namespace bividi::nori
