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
    std::uint32_t vendor_buffer_offset = 0;

    [[nodiscard]] bool valid() const noexcept {
        return decoded.valid();
    }
};

// Stateful DECXIN decoder for a Nori source. Timestamp rollover extension is
// intentionally owned here across consecutive frames.
class DecxinPipeline {
public:
    void reset_timestamps() noexcept;
    [[nodiscard]] DecodedCapture decode(const RawFrame& raw_frame);

private:
    decxin::Decoder decoder_;
};

}  // namespace bividi::nori
