#include "bividi/session.hpp"

#include <cassert>
#include <chrono>
#include <iostream>
#include <thread>

int main() {
    bividi::SyntheticCaptureSession session;

    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    auto status = session.snapshot();
    assert(status.source_id == "synthetic");
    assert(status.running());
    assert(status.capture.frames > 0);
    assert(status.nominal_fps == 60.0);
    assert(status.exposure_us == 7500);
    assert(status.gain_x10 == 10);
    assert(status.trigger_mode == bividi::TriggerMode::free_run);
    assert(status.imu_rate_hz == 600);

    const auto paused_at = status.capture.frames;
    assert(session.toggle_capture());
    status = session.snapshot();
    assert(!status.running());
    assert(status.capture.state == bividi::CaptureState::paused);

    std::this_thread::sleep_for(std::chrono::milliseconds(40));
    status = session.snapshot();
    assert(status.capture.frames == paused_at);

    assert(session.set_exposure_us(8123));
    assert(session.set_gain_x10(37));
    assert(session.cycle_trigger());
    status = session.snapshot();
    assert(status.exposure_us == 8123);
    assert(status.gain_x10 == 37);
    assert(status.trigger_mode == bividi::TriggerMode::software);
    assert(std::string(bividi::trigger_mode_name(status.trigger_mode)) == "Software");

    assert(session.reconnect());
    status = session.snapshot();
    assert(status.capture.frames == 0);
    assert(status.capture.drops == 0);
    assert(status.exposure_start_us == 0);
    assert(status.exposure_end_us == 0);
    assert(status.capture.state == bividi::CaptureState::paused);

    assert(session.toggle_capture());
    std::this_thread::sleep_for(std::chrono::milliseconds(40));
    status = session.snapshot();
    assert(status.running());
    assert(status.capture.frames > 0);
    assert(status.exposure_end_us >= status.exposure_start_us);

    std::cout << "bividi session test: PASS\n";
    return 0;
}
