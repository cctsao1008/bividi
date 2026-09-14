#include "bividi/opencv.hpp"

#include <stdexcept>

namespace bividi::opencv {

cv::Mat wrap_bgr24(const ImageView& view) {
    if (view.empty()) {
        return {};
    }
    if (view.pixel_format != PixelFormat::bgr24 || view.bytes_per_pixel != 3) {
        throw std::invalid_argument("OpenCV bridge currently supports only BGR24 ImageView");
    }
    if (view.row_stride < view.row_bytes()) {
        throw std::invalid_argument("ImageView stride is smaller than its row width");
    }

    return cv::Mat(
        static_cast<int>(view.height),
        static_cast<int>(view.width),
        CV_8UC3,
        const_cast<std::uint8_t*>(view.data),
        view.row_stride);
}

}  // namespace bividi::opencv
