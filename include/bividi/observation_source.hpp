#pragma once

#include "bividi/observation.hpp"

namespace bividi {

// Optional normalized-observation tap for engineering/runtime adapters that
// already own a SensorObservation-producing source. This is intentionally
// separate from CaptureSession: UI preview/lifecycle state is not promoted into
// the stable sensor data contract, and downstream consumers can explicitly opt
// into the normalized #11 boundary when an adapter exposes it.
class ObservationSnapshotSource {
public:
    virtual ~ObservationSnapshotSource() = default;

    [[nodiscard]] virtual const SensorCapabilities& observation_capabilities() const noexcept = 0;

    // Returns the latest published normalized observation. The returned copy
    // retains any backing image buffers through FrameLease, so consumers may
    // process it after the producer mutex has been released.
    [[nodiscard]] virtual bool latest_observation(SensorObservation& out) const = 0;
};

}  // namespace bividi
