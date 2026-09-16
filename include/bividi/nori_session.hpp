#pragma once

#include "bividi/nori.hpp"
#include "bividi/nori_decxin.hpp"
#include "bividi/session.hpp"

#include <memory>

namespace bividi::nori {

struct NoriSessionConfig {
    StreamConfig stream{};
};

// Live DECXIN/Nori implementation of the shared CaptureSession boundary.
//
// All vendor-SDK calls are serialized on a private worker thread. The worker
// uses DecxinPipeline(own_output), so the latest preview may be retained by UI
// clients without pinning a vendor capture buffer from the Nori pool.
class NoriCaptureSession final : public bividi::CaptureSession {
public:
    explicit NoriCaptureSession(NoriSessionConfig config = {});
    ~NoriCaptureSession() override;

    NoriCaptureSession(const NoriCaptureSession&) = delete;
    NoriCaptureSession& operator=(const NoriCaptureSession&) = delete;

    [[nodiscard]] SessionStatus snapshot() const override;
    [[nodiscard]] bool latest_stereo_preview(StereoPreviewFrame& out) const override;

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
