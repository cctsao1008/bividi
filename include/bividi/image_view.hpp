#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>

namespace bividi {

enum class PixelFormat {
    unknown,
    gray8,
    bgr24,
};

struct ImageView {
    const std::uint8_t* data = nullptr;
    std::size_t width = 0;
    std::size_t height = 0;
    std::size_t row_stride = 0;
    std::size_t bytes_per_pixel = 0;
    PixelFormat pixel_format = PixelFormat::unknown;

    [[nodiscard]] bool empty() const noexcept {
        return data == nullptr || width == 0 || height == 0;
    }

    [[nodiscard]] std::size_t row_bytes() const noexcept {
        return width * bytes_per_pixel;
    }

    [[nodiscard]] ImageView subview(std::size_t x, std::size_t sub_width) const {
        if (empty()) {
            throw std::invalid_argument("cannot slice an empty image view");
        }
        if (sub_width == 0 || x > width || sub_width > width - x) {
            throw std::out_of_range("image subview is outside source geometry");
        }
        return ImageView{
            data + x * bytes_per_pixel,
            sub_width,
            height,
            row_stride,
            bytes_per_pixel,
            pixel_format,
        };
    }
};

}  // namespace bividi
