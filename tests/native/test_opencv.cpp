#include "bividi/image_view.hpp"
#include "bividi/opencv.hpp"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

int main() {
    constexpr std::size_t width = 8;
    constexpr std::size_t height = 3;
    constexpr std::size_t stride = 32;  // deliberately wider than width * 3

    std::vector<std::uint8_t> storage(stride * height, 0);
    for (std::size_t y = 0; y < height; ++y) {
        for (std::size_t x = 0; x < width; ++x) {
            const auto offset = y * stride + x * 3;
            storage[offset + 0] = static_cast<std::uint8_t>(x + 1);
            storage[offset + 1] = static_cast<std::uint8_t>(y + 10);
            storage[offset + 2] = 0x7f;
        }
    }

    const bividi::ImageView full{
        storage.data(),
        width,
        height,
        stride,
        3,
        bividi::PixelFormat::bgr24,
    };

    const auto roi = full.subview(2, 4);
    const auto mat = bividi::opencv::wrap_bgr24(roi);

    assert(mat.rows == static_cast<int>(height));
    assert(mat.cols == 4);
    assert(mat.type() == CV_8UC3);
    assert(mat.step[0] == stride);
    assert(mat.data == storage.data() + 2 * 3);

    // Verify the cv::Mat header reads directly from the borrowed source buffer.
    assert(mat.at<cv::Vec3b>(0, 0)[0] == 3);
    assert(mat.at<cv::Vec3b>(2, 3)[0] == 6);
    assert(mat.at<cv::Vec3b>(2, 3)[1] == 12);

    storage[2 * 3] = 0xaa;
    assert(mat.at<cv::Vec3b>(0, 0)[0] == 0xaa);

    bool rejected = false;
    try {
        const bividi::ImageView unsupported{
            storage.data(), width, height, stride, 1, bividi::PixelFormat::unknown};
        (void)bividi::opencv::wrap_bgr24(unsupported);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);

    std::cout << "bividi OpenCV bridge tests: PASS\n";
    return 0;
}
