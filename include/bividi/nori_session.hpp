#pragma once

#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"
#include "bividi/observation_source.hpp"
#include "bividi/session.hpp"

#include <cstdint>
#include <memory>
#include <string>

namespace bividi::nori {

struct NoriSessionConfig {
    StreamConfig stream{};

    // Live MJPEG acquisition is intentionally decoupled from OpenCV/DECXIN
    // decode. Each vendor packet is copied into bounded owned storage, then the
    // vendor lease is returned before decode begins. This depth is therefore a
    // burst-absorption bound, not permission for unbounded latency growth.
    std::uint32_t decode_queue_depth = 256;

    // Individual malformed compressed/metadata frames are recoverable stream
    // events: discard them, expose the failure, and keep acquisition running.
    // Escalate only after this many consecutive decode failures so a genuinely
    // broken stream does not spin forever producing no observations.
    std::uint32_t max_consecutive_decode_failures = 8;

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
// All vendor-SDK calls are serialized on one private acquisition thread. Raw
// transport packets are copied to a bounded owned queue so the vendor buffer
// lease is returned before OpenCV/DECXIN decode runs on a second private thread.
// The published preview/observation owns decoded storage independently of both
// the vendor buffer pool and the compressed-packet queue.
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
