#include "bividi/replay.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

namespace fs = std::filesystem;

struct TempSession {
    fs::path path;

    explicit TempSession(const std::string& suffix) {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() /
               ("bividi-replay-" + suffix + "-" + std::to_string(nonce));
        fs::create_directories(path / "camera_a");
        fs::create_directories(path / "camera_b");
    }

    ~TempSession() {
        std::error_code error;
        fs::remove_all(path, error);
    }
};

void write_text(const fs::path& path, const std::string& content) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("cannot create test file: " + path.string());
    out << content;
    out.flush();
    if (!out) throw std::runtime_error("cannot write test file: " + path.string());
}

void write_image(const fs::path& path, int base) {
    cv::Mat image(2, 4, CV_8UC1);
    for (int y = 0; y < image.rows; ++y) {
        for (int x = 0; x < image.cols; ++x) {
            image.at<unsigned char>(y, x) = static_cast<unsigned char>(base + y * 4 + x);
        }
    }
    if (!cv::imwrite(path.string(), image)) {
        throw std::runtime_error("cannot write test image: " + path.string());
    }
}

void make_fixture(const fs::path& root, bool mismatched_identity = false) {
    write_image(root / "camera_a" / "0000000000.png", 10);
    write_image(root / "camera_b" / "0000000000.png", 30);
    write_image(root / "camera_a" / "0000000002.png", 50);
    write_image(root / "camera_b" / "0000000002.png", 70);

    write_text(
        root / "capture.json",
        "{\n"
        "  \"schema\": \"bividi.nori.camera_imu_dynamic_trace.v1\",\n"
        "  \"provenance\": {\"kind\": \"synthetic\"},\n"
        "  \"device\": {\n"
        "    \"product\": \"fixture\", \"serial\": \"SYN-001\",\n"
        "    \"sdk_version\": \"fixture-sdk\", \"device_type\": \"fixture-type\",\n"
        "    \"isp_version\": \"fixture-isp\", \"fpga_version\": \"fixture-fpga\"\n"
        "  },\n"
        "  \"mode\": {\"index\": 0, \"nominal_fps\": 1000.0},\n"
        "  \"run\": {\"frame_stride\": 2}\n"
        "}\n");

    write_text(
        root / "frames.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns,sdk_timestamp_encoding,sdk_seconds,sdk_microseconds,sdk_filetime_100ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,camera_a_path,camera_b_path\n"
        "0,10,1000000000,unknown,0,0,0,1000,1100,1000,1100,camera_a/0000000000.png,camera_b/0000000000.png\n"
        "2,12,1002000000,unknown,0,0,0,3000,3100,3000,3100,camera_a/0000000002.png,camera_b/0000000002.png\n");

    const std::string second_sequence = mismatched_identity ? "99" : "11";
    write_text(
        root / "imu.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,sample_index,sample_valid,imu_raw_time_us,imu_extended_time_us,accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n"
        "0,10,1000000000,1000,1100,1000,1100,0,true,1050,1050,1,2,3,4,5,6\n"
        "1," + second_sequence + ",1001000000,2000,2100,2000,2100,0,true,2050,2050,7,8,9,10,11,12\n"
        "2,12,1002000000,3000,3100,3000,3100,0,false,3050,3050,13,14,15,16,17,18\n");
}

void test_step_replay_preserves_observations() {
    TempSession temp("step");
    make_fixture(temp.path);

    bividi::ReplayConfig config{};
    config.session_dir = temp.path;
    config.pacing = bividi::ReplayPacing::step;
    bividi::ReplaySource replay(config);

    assert(replay.size() == 3);
    assert(replay.position() == 0);
    assert(!replay.eof());
    assert(replay.metadata().source_schema == "bividi.nori.camera_imu_dynamic_trace.v1");
    assert(replay.metadata().serial == "SYN-001");
    assert(replay.metadata().evidence == bividi::EvidenceKind::synthetic);
    assert(replay.metadata().frame_stride == 2);
    assert(replay.metadata().image_pairs == 2);
    assert(replay.metadata().imu_samples == 3);

    const auto& caps = replay.capabilities();
    assert(caps.cameras.size() == 2);
    assert(caps.stereo_pairs.size() == 1);
    assert(caps.cameras[0].width == 4);
    assert(caps.cameras[0].height == 2);
    assert(caps.cameras[0].pixel_format == bividi::PixelFormat::gray8);
    assert(caps.imu);
    assert(caps.timing.exposure_start_end);
    assert(caps.timing.imu_sample_time);
    assert(!caps.timing.device_frame_time);

    bividi::SensorObservation first;
    assert(replay.next(first));
    assert(first.source_id == "replay:nori:SYN-001");
    assert(first.evidence == bividi::EvidenceKind::synthetic);
    assert(first.sequence_present && first.sequence == 10);
    assert(first.continuity == bividi::ContinuityState::reinitialized);
    assert(first.timing.host_receive.present);
    assert(first.timing.host_receive.ticks == 1000000000ULL);
    assert(!first.timing.replay_schedule.present);
    assert(first.cameras.size() == 2);
    assert(first.cameras[0].image.pixel_format == bividi::PixelFormat::gray8);
    assert(first.cameras[0].image.data[0] == 10);
    assert(first.cameras[1].image.data[0] == 30);
    assert(first.cameras[0].exposure.start.ticks == 1000);
    assert(first.stereo_pairs.size() == 1);
    assert(first.stereo_pairs[0].synchronization == bividi::SynchronizationState::unknown);
    assert(first.imu.size() == 1);
    assert(first.imu[0].raw_valid);
    assert(!first.imu[0].si_valid);
    assert(first.imu[0].accel_raw_counts[2] == 3);

    bividi::SensorObservation second;
    assert(replay.next(second));
    assert(second.sequence == 11);
    assert(second.cameras.empty());
    assert(second.imu.size() == 1);
    assert(second.imu[0].raw_valid);
    assert(second.validity == bividi::ObservationValidity::valid);

    bividi::SensorObservation third;
    assert(replay.next(third));
    assert(third.sequence == 12);
    assert(third.cameras.size() == 2);
    assert(third.imu.size() == 1);
    assert(!third.imu[0].raw_valid);
    assert(third.validity == bividi::ObservationValidity::valid);

    bividi::SensorObservation end;
    assert(!replay.next(end));
    assert(replay.eof());

    replay.reset();
    assert(replay.position() == 0);
    assert(!replay.eof());
    assert(replay.next(first));
    assert(first.sequence == 10);
    assert(first.continuity == bividi::ContinuityState::reinitialized);
}

void test_scaled_replay_uses_separate_schedule_clock() {
    TempSession temp("scaled");
    make_fixture(temp.path);

    bividi::ReplayConfig config{};
    config.session_dir = temp.path;
    config.pacing = bividi::ReplayPacing::scaled;
    config.rate = 2.0;
    bividi::ReplaySource replay(config);

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(observation.timing.host_receive.ticks == 1000000000ULL);
    assert(observation.timing.replay_schedule.present);
    assert(observation.timing.replay_schedule.domain == bividi::ClockDomain::replay);
    assert(observation.timing.replay_schedule.ticks == 0);

    assert(replay.next(observation));
    assert(observation.timing.host_receive.ticks == 1001000000ULL);
    assert(observation.timing.replay_schedule.ticks == 500000ULL);

    assert(replay.next(observation));
    assert(observation.timing.host_receive.ticks == 1002000000ULL);
    assert(observation.timing.replay_schedule.ticks == 1000000ULL);
}

void test_cross_csv_identity_mismatch_is_rejected() {
    TempSession temp("mismatch");
    make_fixture(temp.path, true);

    bool threw = false;
    try {
        bividi::ReplayConfig config{};
        config.session_dir = temp.path;
        bividi::ReplaySource replay(config);
        (void)replay;
    } catch (const std::runtime_error&) {
        threw = true;
    }
    // The mismatch fixture changes a frame that is only in imu.csv, so it is
    // still internally self-consistent. Now mutate frame 0 where both sources
    // are present and verify the importer rejects the disagreement.
    if (!threw) {
        write_text(
            temp.path / "imu.csv",
            "frame_index,frame_sequence,host_receive_monotonic_ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,sample_index,sample_valid,imu_raw_time_us,imu_extended_time_us,accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n"
            "0,999,1000000000,1000,1100,1000,1100,0,true,1050,1050,1,2,3,4,5,6\n");
        try {
            bividi::ReplayConfig config{};
            config.session_dir = temp.path;
            bividi::ReplaySource replay(config);
            (void)replay;
        } catch (const std::runtime_error&) {
            threw = true;
        }
    }
    assert(threw);
}

}  // namespace

int main() {
    test_step_replay_preserves_observations();
    test_scaled_replay_uses_separate_schedule_clock();
    test_cross_csv_identity_mismatch_is_rejected();
    std::cout << "bividi replay test: PASS\n";
    return 0;
}
