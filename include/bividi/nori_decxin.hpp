#pragma once

#include "bividi/decxin.hpp"
#include "bividi/nori_opencv.hpp"

namespace bividi::nori {

// Result of the complete Nori transport -> BGR24 -> DECXIN decode path.
//
// The DECXIN decoded frame keeps the normalized image lease alive. SDK-side
// frame time and source transport provenance remain separate from embedded
// DECXIN exposure/IMU device timestamps so clock domains cannot be confused.
struct DecodedCapture {
    decxin::DecodedFrame decoded{};
    SdkFrameTimestamp sdk_timestamp{};
    VideoMode source_mode{};
    std::uint32_t vendor_buffer_index = 0;
    std::uint32_t vendor_buffer_offset = 0;

    [[nodiscard]] bool valid() const noexcept {
        return decoded.valid();
    }
};

// Stateful DECXIN decoder for a Nori source. Timestamp rollover extension is
// intentionally owned here across consecutive frames. Asynchronous consumers
// should select own_output so retaining a decoded frame never pins a vendor
// capture buffer; synchronous bring-up can keep the zero-copy default.
class DecxinPipeline {
public:
    explicit DecxinPipeline(
        NormalizationOwnership ownership = NormalizationOwnership::borrow_when_possible) noexcept;

    void reset_timestamps() noexcept;
    [[nodiscard]] DecodedCapture decode(const RawFrame& raw_frame);

private:
    NormalizationOwnership ownership_ = NormalizationOwnership::borrow_when_possible;
    decxin::Decoder decoder_;
};

}  // namespace bividi::nori
