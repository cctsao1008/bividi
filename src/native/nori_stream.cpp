#include "bividi/nori.hpp"

#include "Nori_Xvision_API.h"

#include <atomic>
#include <chrono>
#include <sstream>
#include <utility>

namespace bividi::nori {
namespace {

constexpr std::uint32_t kMjpg = 0x47504a4d;
constexpr std::uint32_t kYuyv = 0x56595559;
constexpr std::uint32_t kYuy2 = 0x32595559;
constexpr std::uint32_t kMjpgToBgr24 = kMjpg + 0x01;
constexpr std::uint32_t kYuy2ToBgr24 = kYuy2 + 0x01;

[[noreturn]] void fail(const char* operation, std::uint32_t code) {
    std::ostringstream out;
    out << operation << " failed (0x" << std::hex << std::uppercase << code << ')';
    throw Error(out.str());
}

void check(const char* operation, std::uint32_t code) {
    if (code != NORI_OK) {
        fail(operation, code);
    }
}

// The Windows SDK exposes FRAME_BUFFER_OUT::PixFormat as an anonymous struct
// rather than VIDEO_INFO, even though both carry the same four fields. Keep
// this adapter structural so advertised modes and per-frame modes share one
// normalization path without relying on an invalid implicit conversion.
template <typename VendorModeLike>
VideoMode video_mode_from_vendor(const VendorModeLike& vendor_mode) noexcept {
    VideoMode mode{};
    mode.raw_format = vendor_mode.u_Format;
    mode.width = vendor_mode.u_Width;
    mode.height = vendor_mode.u_Height;
    mode.fps = vendor_mode.f_Fps;
    if (vendor_mode.u_Format == kMjpg) {
        mode.format = TransportFormat::mjpeg;
    } else if (vendor_mode.u_Format == kYuyv || vendor_mode.u_Format == kYuy2) {
        mode.format = TransportFormat::yuyv;
    } else if (vendor_mode.u_Format == kMjpgToBgr24 || vendor_mode.u_Format == kYuy2ToBgr24) {
        mode.format = TransportFormat::bgr24;
        mode.bottom_up = true;
    }
    return mode;
}

std::uint64_t monotonic_now_ns() noexcept {
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count());
}

E_TRIGGER_MODE vendor_trigger_mode(TriggerMode mode) {
    switch (mode) {
        case TriggerMode::free_run: return NON_TRIIGER_MODE;
        case TriggerMode::software: return SOFTWARE_TRIIGER_MODE;
        case TriggerMode::hardware: return HARDWARE_TRIGGER_MODE;
        case TriggerMode::command: return COMMAND_TRIGGER_MODE;
    }
    return NON_TRIIGER_MODE;
}

TriggerMode normalized_trigger_mode(E_TRIGGER_MODE mode) noexcept {
    switch (mode) {
        case SOFTWARE_TRIIGER_MODE: return TriggerMode::software;
        case HARDWARE_TRIIGER_MODE: return TriggerMode::hardware;
        case COMMAND_TRIGGER_MODE: return TriggerMode::command;
        case NON_TRIIGER_MODE:
        default:
            return TriggerMode::free_run;
    }
}

#ifdef _WIN32
using VendorFrame = FRAME_BUFFER_OUT;
#else
using VendorFrame = FRAME_BUFFER_DATA;
#endif

}  // namespace

const char* sdk_timestamp_encoding_name(SdkTimestampEncoding encoding) noexcept {
    switch (encoding) {
        case SdkTimestampEncoding::seconds_microseconds: return "seconds+microseconds";
        case SdkTimestampEncoding::windows_filetime_100ns: return "windows-filetime-100ns";
        case SdkTimestampEncoding::unknown: return "unknown";
    }
    return "unknown";
}

struct Stream::Impl {
    explicit Impl(StreamConfig stream_config) : config(std::move(stream_config)) {
        try {
            std::uint32_t device_count = 0;
            check("Nori_Xvision_Init", Nori_Xvision_Init(NORI_USB_DEVICE, &device_count));
            sdk_initialized = true;

            if (config.device_index >= device_count) {
                throw Error("Nori device index is outside the enumerated device range");
            }

            std::uint32_t mode_count = 0;
            check(
                "Nori_Xvision_GetDeviceVideoInfoSize",
                Nori_Xvision_GetDeviceVideoInfoSize(config.device_index, &mode_count));
            if (config.mode_index >= mode_count) {
                throw Error("Nori video mode index is outside the advertised mode range");
            }

            VIDEO_INFO vendor_mode{};
            check(
                "Nori_Xvision_GetDeviceVideoInfo",
                Nori_Xvision_GetDeviceVideoInfo(config.device_index, config.mode_index, &vendor_mode));
            selected_mode = video_mode_from_vendor(vendor_mode);

            check(
                "Nori_Xvision_DeviceVideoInit",
                Nori_Xvision_DeviceVideoInit(config.device_index, vendor_mode));
            video_initialized = true;

            if (config.configure_free_run) {
                check(
                    "Nori_Xvision_SetTriggerMode",
                    Nori_Xvision_SetTriggerMode(config.device_index, NON_TRIIGER_MODE));
            }

            start_video();
        } catch (...) {
            cleanup();
            throw;
        }
    }

    ~Impl() {
        cleanup();
    }

    void cleanup() noexcept {
        if (video_started) {
            Nori_Xvision_VideoStop(config.device_index);
            video_started = false;
        }
        if (video_initialized) {
            Nori_Xvision_DeviceVideoUnInit(config.device_index);
            video_initialized = false;
        }
        if (sdk_initialized) {
            Nori_Xvision_UnInit();
            sdk_initialized = false;
        }
    }

    void start_video() {
        if (video_started) return;
        if (!video_initialized) {
            throw Error("Nori video device is not initialized");
        }
        check("Nori_Xvision_VideoStart", Nori_Xvision_VideoStart(config.device_index));
        video_started = true;
    }

    void stop_video() {
        if (!video_started) return;
        if (outstanding.load(std::memory_order_acquire) != 0) {
            throw Error("cannot stop Nori video while a raw frame is still leased");
        }
        check("Nori_Xvision_VideoStop", Nori_Xvision_VideoStop(config.device_index));
        video_started = false;
    }

    void ensure_manual_exposure() {
#ifdef _WIN32
        long value = 0;
        long flags = 0;
        long step = 0;
        long minimum = 0;
        long maximum = 0;
        long default_value = 0;
        long caps_flags = 0;
        check(
            "Nori_Xvision_GetCameraTerminalControl(CameraControl_Exposure)",
            Nori_Xvision_GetCameraTerminalControl(
                config.device_index,
                CameraControl_Exposure,
                &value,
                &flags,
                &step,
                &minimum,
                &maximum,
                &default_value,
                &caps_flags));
        if (flags != CameraControl_Flags_Manual) {
            check(
                "Nori_Xvision_SetCameraTerminalControl(CameraControl_Exposure)",
                Nori_Xvision_SetCameraTerminalControl(
                    config.device_index,
                    CameraControl_Exposure,
                    value,
                    CameraControl_Flags_Manual));
        }
#else
        std::int32_t current = 0;
        std::int32_t flags = 0;
        std::int32_t step = 0;
        std::int32_t minimum = 0;
        std::int32_t maximum = 0;
        std::int32_t default_value = 0;
        check(
            "Nori_Xvision_GetProcessingUnitControl(V4L2_CID_EXPOSURE_AUTO)",
            Nori_Xvision_GetProcessingUnitControl(
                config.device_index,
                V4L2_CID_EXPOSURE_AUTO,
                &current,
                &flags,
                &step,
                &minimum,
                &maximum,
                &default_value));
        if (current != V4L2_EXPOSURE_MANUAL) {
            check(
                "Nori_Xvision_SetProcessingUnitControl(V4L2_CID_EXPOSURE_AUTO)",
                Nori_Xvision_SetProcessingUnitControl(
                    config.device_index,
                    V4L2_CID_EXPOSURE_AUTO,
                    V4L2_EXPOSURE_MANUAL));
        }
#endif
    }

    TriggerMode trigger_mode() const {
        E_TRIGGER_MODE mode = NON_TRIIGER_MODE;
        check("Nori_Xvision_GetTriggerMode", Nori_Xvision_GetTriggerMode(config.device_index, &mode));
        return normalized_trigger_mode(mode);
    }

    void set_trigger_mode(TriggerMode mode) {
        check(
            "Nori_Xvision_SetTriggerMode",
            Nori_Xvision_SetTriggerMode(config.device_index, vendor_trigger_mode(mode)));
    }

    std::uint32_t exposure_us() const {
        std::uint32_t value = 0;
        check("Nori_Xvision_GetSensorShutter", Nori_Xvision_GetSensorShutter(config.device_index, &value));
        return value;
    }

    void set_exposure_us(std::uint32_t value) {
        ensure_manual_exposure();
        check("Nori_Xvision_SetSensorShutter", Nori_Xvision_SetSensorShutter(config.device_index, value));
    }

    SensorGainInfo gain_info() const {
        SensorGainInfo info{};
        check(
            "Nori_Xvision_GetSensorGain",
            Nori_Xvision_GetSensorGain(
                config.device_index,
                &info.current,
                &info.minimum,
                &info.maximum,
                &info.step));
        return info;
    }

    void set_gain_multiplier(std::uint32_t value) {
        ensure_manual_exposure();
        check("Nori_Xvision_SetSensorGain", Nori_Xvision_SetSensorGain(config.device_index, value));
    }

    void release_frame(VendorFrame* frame) noexcept {
        if (frame != nullptr) {
            last_release_error.store(
                Nori_Xvision_FreeFrameBuff(config.device_index, frame),
                std::memory_order_release);
        }
        outstanding.store(0, std::memory_order_release);
    }

    [[nodiscard]] RawFrame next_frame(const std::shared_ptr<Impl>& keep_alive) {
        if (!video_started) {
            throw Error("Nori video stream is stopped");
        }

        const auto previous_release = last_release_error.exchange(NORI_OK, std::memory_order_acq_rel);
        if (previous_release != NORI_OK) {
            fail("Nori_Xvision_FreeFrameBuff", previous_release);
        }

        std::uint32_t expected = 0;
        if (!outstanding.compare_exchange_strong(expected, 1, std::memory_order_acq_rel)) {
            throw Error("previous Nori raw frame is still leased; release it before requesting another frame");
        }

        VendorFrame* vendor_frame = nullptr;
#ifdef _WIN32
        const auto code = Nori_Xvision_GetFrameBuff(
            config.device_index,
            &vendor_frame,
            config.timeout_ms);
        if (code == NORI_E_NOBUFF) {
            outstanding.store(0, std::memory_order_release);
            return {};
        }
        if (code != NORI_OK) {
            outstanding.store(0, std::memory_order_release);
            fail("Nori_Xvision_GetFrameBuff", code);
        }
#else
        vendor_frame = Nori_Xvision_GetFrameBuff(
            config.device_index,
            config.timeout_ms != 0,
            config.timeout_ms);
        if (vendor_frame == nullptr) {
            outstanding.store(0, std::memory_order_release);
            return {};
        }
#endif

        const auto host_receive_ns = monotonic_now_ns();
        struct LeaseToken {
            std::shared_ptr<Impl> owner;
            VendorFrame* frame = nullptr;
        };

        auto* token = new LeaseToken{keep_alive, vendor_frame};
        RawFrame frame{};
        frame.lease = FrameLease::adopt(
            token,
            [](LeaseToken* leased) noexcept {
                leased->owner->release_frame(leased->frame);
                delete leased;
            });
        frame.data = static_cast<const std::uint8_t*>(vendor_frame->pBufAddr);
#ifdef _WIN32
        frame.size = vendor_frame->u_FrameLen;
        frame.sequence = vendor_frame->u_FrameNum;
        frame.sdk_timestamp.encoding = SdkTimestampEncoding::windows_filetime_100ns;
        frame.sdk_timestamp.filetime_100ns =
            (static_cast<std::uint64_t>(vendor_frame->Frame_Time.dwHighDateTime) << 32) |
            static_cast<std::uint64_t>(vendor_frame->Frame_Time.dwLowDateTime);
#else
        frame.size = vendor_frame->buff_Length;
        frame.sequence = vendor_frame->buffer.sequence;
        frame.sdk_timestamp.encoding = SdkTimestampEncoding::seconds_microseconds;
        frame.sdk_timestamp.seconds = vendor_frame->Frame_Time.tv_sec;
        frame.sdk_timestamp.microseconds = vendor_frame->Frame_Time.tv_usec;
        frame.vendor_buffer_index = vendor_frame->index;
        frame.vendor_buffer_offset = vendor_frame->buff_Offset;
#endif
        frame.mode = video_mode_from_vendor(vendor_frame->PixFormat);
        frame.host_receive_monotonic_ns = host_receive_ns;

        if (!frame.valid()) {
            throw Error("Nori returned an empty frame buffer");
        }
        return frame;
    }

    StreamConfig config{};
    VideoMode selected_mode{};
    bool sdk_initialized = false;
    bool video_initialized = false;
    bool video_started = false;
    std::atomic<std::uint32_t> outstanding{0};
    std::atomic<std::uint32_t> last_release_error{NORI_OK};
};

Stream::Stream(StreamConfig config) : impl_(std::make_shared<Impl>(std::move(config))) {}
Stream::~Stream() = default;
Stream::Stream(Stream&&) noexcept = default;
Stream& Stream::operator=(Stream&&) noexcept = default;

RawFrame Stream::next_frame() {
    if (!impl_) {
        throw Error("Nori stream is not initialized");
    }
    return impl_->next_frame(impl_);
}

VideoMode Stream::mode() const {
    if (!impl_) {
        throw Error("Nori stream is not initialized");
    }
    return impl_->selected_mode;
}

std::uint32_t Stream::device_index() const noexcept {
    return impl_ ? impl_->config.device_index : 0;
}

bool Stream::running() const noexcept {
    return impl_ && impl_->video_started;
}

void Stream::start_video() {
    if (!impl_) throw Error("Nori stream is not initialized");
    impl_->start_video();
}

void Stream::stop_video() {
    if (!impl_) throw Error("Nori stream is not initialized");
    impl_->stop_video();
}

TriggerMode Stream::trigger_mode() const {
    if (!impl_) throw Error("Nori stream is not initialized");
    return impl_->trigger_mode();
}

void Stream::set_trigger_mode(TriggerMode mode) {
    if (!impl_) throw Error("Nori stream is not initialized");
    impl_->set_trigger_mode(mode);
}

std::uint32_t Stream::exposure_us() const {
    if (!impl_) throw Error("Nori stream is not initialized");
    return impl_->exposure_us();
}

void Stream::set_exposure_us(std::uint32_t value) {
    if (!impl_) throw Error("Nori stream is not initialized");
    impl_->set_exposure_us(value);
}

SensorGainInfo Stream::gain_info() const {
    if (!impl_) throw Error("Nori stream is not initialized");
    return impl_->gain_info();
}

void Stream::set_gain_multiplier(std::uint32_t value) {
    if (!impl_) throw Error("Nori stream is not initialized");
    impl_->set_gain_multiplier(value);
}

}  // namespace bividi::nori
