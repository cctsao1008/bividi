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
               ("bividi-replay-integrity-" + suffix + "-" + std::to_string(nonce));
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
    if (!out) throw std::runtime_error("cannot create fixture file: " + path.string());
    out << content;
    out.flush();
    if (!out) throw std::runtime_error("cannot write fixture file: " + path.string());
}

void write_image(const fs::path& path, int rows, int cols, int base) {
    cv::Mat image(rows, cols, CV_8UC1);
    for (int y = 0; y < rows; ++y) {
        for (int x = 0; x < cols; ++x) {
            image.at<unsigned char>(y, x) = static_cast<unsigned char>(base + y * cols + x);
        }
    }
    if (!cv::imwrite(path.string(), image)) {
        throw std::runtime_error("cannot write fixture image: " + path.string());
    }
}

void make_fixture(const fs::path& root) {
    write_image(root / "camera_a" / "0000000000.png", 2, 4, 10);
    write_image(root / "camera_b" / "0000000000.png", 2, 4, 30);
    write_image(root / "camera_a" / "0000000002.png", 2, 4, 50);
    write_image(root / "camera_b" / "0000000002.png", 2, 4, 70);

    write_text(
        root / "capture.json",
        "{\n"
        "  \"schema\": \"bividi.nori.camera_imu_dynamic_trace.v1\",\n"
        "  \"provenance\": {\"kind\": \"synthetic\"},\n"
        "  \"device\": {\"product\": \"fixture\", \"serial\": \"SYN-INT\"},\n"
        "  \"mode\": {\"index\": 0, \"nominal_fps\": 30.0},\n"
        "  \"run\": {\"frame_stride\": 2}\n"
        "}\n");

    write_text(
        root / "frames.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns,sdk_timestamp_encoding,sdk_seconds,sdk_microseconds,sdk_filetime_100ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,camera_a_path,camera_b_path\n"
        "0,10,1000000000,unknown,0,0,0,1000,1100,1000,1100,camera_a/0000000000.png,camera_b/0000000000.png\n"
        "2,12,1002000000,unknown,0,0,0,3000,3100,3000,3100,camera_a/0000000002.png,camera_b/0000000002.png\n");

    write_text(
        root / "imu.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,sample_index,sample_valid,imu_raw_time_us,imu_extended_time_us,accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n"
        "0,10,1000000000,1000,1100,1000,1100,0,true,1050,1050,1,2,3,4,5,6\n"
        "1,11,1001000000,2000,2100,2000,2100,0,true,2050,2050,7,8,9,10,11,12\n"
        "2,12,1002000000,3000,3100,3000,3100,0,true,3050,3050,13,14,15,16,17,18\n");
}

bool constructor_rejected(const fs::path& root) {
    try {
        bividi::ReplayConfig config{};
        config.session_dir = root;
        config.pacing = bividi::ReplayPacing::step;
        bividi::ReplaySource replay(config);
        (void)replay;
        return false;
    } catch (const std::exception&) {
        return true;
    }
}

void test_malformed_capture_json_is_rejected() {
    TempSession temp("capture-json");
    make_fixture(temp.path);
    write_text(temp.path / "capture.json", "{\"schema\":");
    assert(constructor_rejected(temp.path));
}

void test_truncated_csv_header_is_rejected() {
    TempSession temp("csv");
    make_fixture(temp.path);
    write_text(
        temp.path / "frames.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns\n"
        "0,10,1000000000\n");
    assert(constructor_rejected(temp.path));
}

void test_corrupt_first_image_is_rejected() {
    TempSession temp("corrupt-image");
    make_fixture(temp.path);
    write_text(temp.path / "camera_a" / "0000000000.png", "not-an-image");
    assert(constructor_rejected(temp.path));
}

void test_stereo_geometry_mismatch_is_rejected() {
    TempSession temp("pair-geometry");
    make_fixture(temp.path);
    write_image(temp.path / "camera_b" / "0000000000.png", 2, 5, 30);
    assert(constructor_rejected(temp.path));
}

void test_mid_session_geometry_change_is_rejected_when_materialized() {
    TempSession temp("mid-geometry");
    make_fixture(temp.path);
    write_image(temp.path / "camera_a" / "0000000002.png", 2, 5, 50);
    write_image(temp.path / "camera_b" / "0000000002.png", 2, 5, 70);

    bividi::ReplayConfig config{};
    config.session_dir = temp.path;
    config.pacing = bividi::ReplayPacing::step;
    bividi::ReplaySource replay(config);

    bividi::SensorObservation observation;
    assert(replay.next(observation));
    assert(observation.sequence == 10);
    assert(replay.next(observation));
    assert(observation.sequence == 11);

    bool rejected = false;
    try {
        (void)replay.next(observation);
    } catch (const std::exception&) {
        rejected = true;
    }
    assert(rejected);
}

void test_session_escape_media_path_is_rejected() {
    TempSession temp("escape");
    make_fixture(temp.path);
    write_text(
        temp.path / "frames.csv",
        "frame_index,frame_sequence,host_receive_monotonic_ns,sdk_timestamp_encoding,sdk_seconds,sdk_microseconds,sdk_filetime_100ns,exposure_start_raw_us,exposure_end_raw_us,exposure_start_extended_us,exposure_end_extended_us,camera_a_path,camera_b_path\n"
        "0,10,1000000000,unknown,0,0,0,1000,1100,1000,1100,../outside.png,camera_b/0000000000.png\n");
    assert(constructor_rejected(temp.path));
}

}  // namespace

int main() {
    test_malformed_capture_json_is_rejected();
    test_truncated_csv_header_is_rejected();
    test_corrupt_first_image_is_rejected();
    test_stereo_geometry_mismatch_is_rejected();
    test_mid_session_geometry_change_is_rejected_when_materialized();
    test_session_escape_media_path_is_rejected();
    std::cout << "bividi replay artifact integrity tests: PASS\n";
    return 0;
}
