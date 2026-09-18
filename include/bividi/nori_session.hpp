#pragma once

#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"
#include "bividi/observation_source.hpp"
#include "bividi/session.hpp"

#include <memory>
#include <string>

namespace bividi::nori {

struct NoriSessionConfig {
    StreamConfig stream{};

    // A live vendor-backed capture is measured sensor evidence, but that does
    // not imply measured stereo synchronization or calibrated left/right
    // identity. Those remain explicit fields on the normalized observation.
    EvidenceKind evidence = EvidenceKind::measured;
    CalibrationIdentity calibration{};
    std::string configuration_revision;
};

// Live DECXIN/Nori implementation of the shared CaptureSession boundary plus
// an opt-in normalized SensorObservation snapshot surface.
//
// All vendor-SDK calls are serialized on a private worker thread. The worker
// uses DecxinPipeline(own_output), so both the latest preview and normalized
// observation may be retained by downstream consumers without pinning a vendor
// capture buffer from the Nori pool.
//
// Camera identities remain camera_a/camera_b until physical mapping evidence is
// established. The DECXIN pair synchronization state remains UNKNOWN; exposing
// the normalized source must not promote vendor/protocol assumptions into a
// measured synchronization claim.
class NoriCaptureSession final
    : public bividi::CaptureSession,
      public bividi::ObservationSnapshotSource {
public:
    explicit NoriCaptureSession(NoriSessionConfig config = {});
    ~NoriCaptureSession() override;

    NoriCaptureSession(const NoriCaptureSession&) = delete;
    NoriCaptureSession& operator=(const NoriCaptureSession&) = delete;

    [[nodiscard]] SessionStatus snapshot() const override;
    [[nodiscard]] bool latest_stereo_preview(StereoPreviewFrame& out) const override;

    [[nodiscard]] const SensorCapabilities& observation_capabilities() const noexcept override;
    [[nodiscard]] bool latest_observation(SensorObservation& out) const override;

    bool toggle_capture() override;
    bool cycle_trigger() override;
    bool reconnect() override;
    bool set_exposure_us(int value) override;
    bool set_gain_x10(int value) override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace bividi::nori
