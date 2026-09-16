#pragma once

#include "bividi/nori.hpp"

namespace bividi::nori {

// Normalized host image plus the Nori SDK-side timing/provenance that should
// remain available for characterization. `captured.transport` is always
// top-down BGR24 when this object is valid.
struct NormalizedFrame {
    CapturedFrame captured{};
    SdkFrameTimestamp sdk_timestamp{};
    VideoMode source_mode{};
    std::uint32_t vendor_buffer_offset = 0;

    [[nodiscard]] bool valid() const noexcept {
        return captured.valid();
    }
};

// Convert one Nori raw transport frame into the BGR24 image contract consumed
// by the DECXIN encoded-pixel decoder. MJPEG/YUYV and bottom-up BGR24 are
// normalized explicitly; already top-down BGR24 can remain zero-copy.
[[nodiscard]] NormalizedFrame normalize_to_bgr24(const RawFrame& frame);

}  // namespace bividi::nori
