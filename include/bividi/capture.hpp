#pragma once

#include "bividi/image_view.hpp"

#include <cstdint>
#include <memory>
#include <utility>

namespace bividi {

// Shared lifetime token for a backend-owned frame buffer.
//
// ImageView deliberately remains a non-owning, stride-aware view. FrameLease
// keeps the backing resource alive without forcing a full-frame copy or
// coupling Bividi core types to a vendor SDK buffer type.
class FrameLease {
public:
    FrameLease() = default;

    template <typename T, typename Deleter>
    [[nodiscard]] static FrameLease adopt(T* resource, Deleter&& deleter) {
        if (resource == nullptr) {
            return {};
        }
        return FrameLease(std::shared_ptr<void>(resource, std::forward<Deleter>(deleter)));
    }

    [[nodiscard]] bool valid() const noexcept {
        return static_cast<bool>(owner_);
    }

    [[nodiscard]] long use_count() const noexcept {
        return owner_.use_count();
    }

    void reset() noexcept {
        owner_.reset();
    }

private:
    explicit FrameLease(std::shared_ptr<void> owner) : owner_(std::move(owner)) {}

    std::shared_ptr<void> owner_;
};

enum class CaptureState {
    idle,
    running,
    disconnected,
    error,
};

struct CaptureStatus {
    CaptureState state = CaptureState::idle;
    std::uint64_t frames = 0;
    std::uint64_t drops = 0;
    std::uint64_t duplicates = 0;
    std::uint64_t out_of_order = 0;
};

// One host-visible transport frame before device-family decoding.
//
// Device time is intentionally absent here: exposure/IMU timestamps are
// device-adapter outputs. host_receive_monotonic_ns records the separate host
// clock domain at the acquisition boundary.
struct CapturedFrame {
    FrameLease lease{};
    ImageView transport{};
    std::uint64_t sequence = 0;
    std::uint64_t host_receive_monotonic_ns = 0;

    [[nodiscard]] bool valid() const noexcept {
        return !transport.empty();
    }
};

}  // namespace bividi
