#include "bividi/nori_decxin.hpp"

namespace bividi::nori {

DecxinPipeline::DecxinPipeline(NormalizationOwnership ownership) noexcept : ownership_(ownership) {}

void DecxinPipeline::reset_timestamps() noexcept {
    decoder_.reset_timestamps();
}

DecodedCapture DecxinPipeline::decode(const RawFrame& raw_frame) {
    auto normalized = normalize_to_bgr24(raw_frame, ownership_);

    DecodedCapture result{};
    result.sdk_timestamp = normalized.sdk_timestamp;
    result.source_mode = normalized.source_mode;
    result.vendor_buffer_index = normalized.vendor_buffer_index;
    result.vendor_buffer_offset = normalized.vendor_buffer_offset;
    result.decoded = decoder_.decode_frame(normalized.captured);
    return result;
}

}  // namespace bividi::nori
