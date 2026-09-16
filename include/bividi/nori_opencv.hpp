#pragma once

#include "bividi/nori.hpp"

namespace bividi::nori {

enum class NormalizationOwnership {
    borrow_when_possible,
    own_output,
};

// Normalized host image plus the Nori SDK-side timing/provenance that should
// remain available for characterization. `captured.transport` is always
// top-down BGR24 when this object is valid.
struct NormalizedFrame {
    CapturedFrame captured{};
    SdkFrameTimestamp sdk_timestamp{};
    VideoMode source_mode{};
    std::uint32_t vendor_buffer_index = 0;
    std::uint32_t vendor_buffer_offset = 0;

    [[nodiscard]] bool valid() const noexcept {
        return captured.valid();
    }
};

// Convert one Nori raw transport frame into the BGR24 image contract consumed
// by the DECXIN encoded-pixel decoder. MJPEG/YUYV and bottom-up BGR24 are
// normalized explicitly. Top-down BGR24 may remain zero-copy for synchronous
// bring-up, or be copied to owned storage for asynchronous consumers that must
// promptly return the vendor buffer pool lease.
[[nodiscard]] NormalizedFrame normalize_to_bgr24(
    const RawFrame& frame,
    NormalizationOwnership ownership = NormalizationOwnership::borrow_when_possible);

}  // namespace bividi::nori
