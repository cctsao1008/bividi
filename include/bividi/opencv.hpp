#pragma once

#include "bividi/image_view.hpp"

#include <opencv2/core.hpp>

namespace bividi::opencv {

// Returns a zero-copy cv::Mat header over a borrowed BGR24 ImageView.
// The caller must keep the source buffer alive and treat the returned Mat as read-only.
[[nodiscard]] cv::Mat wrap_bgr24(const ImageView& view);

}  // namespace bividi::opencv
