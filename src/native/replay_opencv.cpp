#include "bividi/replay.hpp"

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace bividi {
namespace {

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

constexpr const char* kNoriDynamicSchema = "bividi.nori.camera_imu_dynamic_trace.v1";

struct ImuRecord {
    std::uint64_t sample_index = 0;
    bool valid = false;
    std::uint32_t raw_time_us = 0;
    std::uint64_t extended_time_us = 0;
    std::array<std::int32_t, 3> accel{};
    std::array<std::int32_t, 3> gyro{};
};

struct TimelineRecord {
    std::uint64_t frame_index = 0;
    bool identity_present = false;
    std::uint64_t sequence = 0;
    std::uint64_t host_receive_monotonic_ns = 0;
    std::uint32_t exposure_start_raw_us = 0;
    std::uint32_t exposure_end_raw_us = 0;
    std::uint64_t exposure_start_extended_us = 0;
    std::uint64_t exposure_end_extended_us = 0;
    bool images_present = false;
    fs::path camera_a_path;
    fs::path camera_b_path;
    std::vector<ImuRecord> imu;
};

struct ImageOwner {
    cv::Mat camera_a;
    cv::Mat camera_b;
};

std::vector<std::string> split_csv(const std::string& line) {
    std::vector<std::string> fields;
    std::size_t start = 0;
    while (true) {
        const auto comma = line.find(',', start);
        if (comma == std::string::npos) {
            fields.push_back(line.substr(start));
            break;
        }
        fields.push_back(line.substr(start, comma - start));
        start = comma + 1;
    }
    if (!fields.empty() && !fields.back().empty() && fields.back().back() == '\r') {
        fields.back().pop_back();
    }
    return fields;
}

std::unordered_map<std::string, std::size_t> header_map(const std::vector<std::string>& header) {
    std::unordered_map<std::string, std::size_t> result;
    for (std::size_t i = 0; i < header.size(); ++i) {
        if (!result.emplace(header[i], i).second) {
            throw std::runtime_error("duplicate CSV header: " + header[i]);
        }
    }
    return result;
}

std::size_t require_column(
    const std::unordered_map<std::string, std::size_t>& header,
    const std::string& name) {
    const auto it = header.find(name);
    if (it == header.end()) {
        throw std::runtime_error("missing required CSV column: " + name);
    }
    return it->second;
}

const std::string& field(
    const std::vector<std::string>& fields,
    std::size_t index,
    const std::string& name) {
    if (index >= fields.size()) {
        throw std::runtime_error("CSV row is missing field: " + name);
    }
    return fields[index];
}

std::uint64_t parse_u64(const std::string& text, const std::string& name) {
    try {
        std::size_t used = 0;
        const auto value = std::stoull(text, &used, 10);
        if (used != text.size()) throw std::invalid_argument("trailing characters");
        return value;
    } catch (const std::exception&) {
        throw std::runtime_error("invalid unsigned integer for " + name + ": " + text);
    }
}

std::uint32_t parse_u32(const std::string& text, const std::string& name) {
    const auto value = parse_u64(text, name);
    if (value > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("value exceeds uint32 for " + name + ": " + text);
    }
    return static_cast<std::uint32_t>(value);
}

std::int32_t parse_i32(const std::string& text, const std::string& name) {
    try {
        std::size_t used = 0;
        const auto value = std::stoll(text, &used, 10);
        if (used != text.size() || value < std::numeric_limits<std::int32_t>::min() ||
            value > std::numeric_limits<std::int32_t>::max()) {
            throw std::out_of_range("range");
        }
        return static_cast<std::int32_t>(value);
    } catch (const std::exception&) {
        throw std::runtime_error("invalid int32 for " + name + ": " + text);
    }
}

bool parse_bool(const std::string& text, const std::string& name) {
    if (text == "true" || text == "1") return true;
    if (text == "false" || text == "0") return false;
    throw std::runtime_error("invalid boolean for " + name + ": " + text);
}

EvidenceKind parse_evidence_kind(const std::string& text) noexcept {
    if (text == "synthetic") return EvidenceKind::synthetic;
    if (text == "measured") return EvidenceKind::measured;
    if (text == "imported") return EvidenceKind::imported;
    return EvidenceKind::unknown;
}

fs::path contained_path(const fs::path& root, const std::string& relative) {
    fs::path rel(relative);
    if (rel.empty() || rel.is_absolute()) {
        throw std::runtime_error("recorded media path must be non-empty and relative: " + relative);
    }

    const auto root_canonical = fs::weakly_canonical(root);
    const auto candidate = fs::weakly_canonical(root / rel);
    auto root_it = root_canonical.begin();
    auto candidate_it = candidate.begin();
    for (; root_it != root_canonical.end(); ++root_it, ++candidate_it) {
        if (candidate_it == candidate.end() || *candidate_it != *root_it) {
            throw std::runtime_error("recorded media path escapes session directory: " + relative);
        }
    }
    return candidate;
}

void merge_identity(
    TimelineRecord& record,
    std::uint64_t sequence,
    std::uint64_t host_ns,
    std::uint32_t es_raw,
    std::uint32_t ee_raw,
    std::uint64_t es_extended,
    std::uint64_t ee_extended) {
    if (!record.identity_present) {
        record.identity_present = true;
        record.sequence = sequence;
        record.host_receive_monotonic_ns = host_ns;
        record.exposure_start_raw_us = es_raw;
        record.exposure_end_raw_us = ee_raw;
        record.exposure_start_extended_us = es_extended;
        record.exposure_end_extended_us = ee_extended;
        return;
    }

    if (record.sequence != sequence || record.host_receive_monotonic_ns != host_ns ||
        record.exposure_start_raw_us != es_raw || record.exposure_end_raw_us != ee_raw ||
        record.exposure_start_extended_us != es_extended ||
        record.exposure_end_extended_us != ee_extended) {
        throw std::runtime_error(
            "frames.csv / imu.csv identity mismatch at frame_index " +
            std::to_string(record.frame_index));
    }
}

std::string read_string(const cv::FileNode& node, const char* key) {
    const auto child = node[key];
    if (child.empty()) return {};
    std::string value;
    child >> value;
    return value;
}

int read_int(const cv::FileNode& node, const char* key, int fallback = 0) {
    const auto child = node[key];
    if (child.empty()) return fallback;
    int value = fallback;
    child >> value;
    return value;
}

double read_double(const cv::FileNode& node, const char* key, double fallback = 0.0) {
    const auto child = node[key];
    if (child.empty()) return fallback;
    double value = fallback;
    child >> value;
    return value;
}

PixelFormat pixel_format(const cv::Mat& image) {
    if (image.type() == CV_8UC1) return PixelFormat::gray8;
    if (image.type() == CV_8UC3) return PixelFormat::bgr24;
    return PixelFormat::unknown;
}

ImageView image_view(const cv::Mat& image) {
    const auto format = pixel_format(image);
    if (format == PixelFormat::unknown || image.empty() || image.cols <= 0 || image.rows <= 0 ||
        image.step > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("unsupported replay image representation");
    }
    return ImageView{
        image.data,
        static_cast<std::uint32_t>(image.cols),
        static_cast<std::uint32_t>(image.rows),
        static_cast<std::uint32_t>(image.step),
        format == PixelFormat::gray8 ? 1u : 3u,
        format,
    };
}

TimePoint device_us(std::uint64_t ticks, const std::string& clock_id) {
    return TimePoint{ticks, TimeUnit::microseconds, ClockDomain::device, clock_id, true};
}

RawTimestampEvidence raw_device_us(std::uint32_t ticks, const std::string& clock_id) {
    return RawTimestampEvidence{ticks, 32, TimeUnit::microseconds, clock_id, true};
}

}  // namespace

struct ReplaySource::Impl {
    explicit Impl(ReplayConfig replay_config) : config(std::move(replay_config)) {
        if (config.session_dir.empty()) {
            throw std::invalid_argument("replay session_dir must not be empty");
        }
        root = fs::weakly_canonical(config.session_dir);
        if (!fs::is_directory(root)) {
            throw std::runtime_error("replay session directory does not exist: " + root.string());
        }
        if (config.pacing == ReplayPacing::scaled && !(config.rate > 0.0)) {
            throw std::invalid_argument("scaled replay rate must be > 0");
        }

        read_capture_json();
        read_frames_csv();
        read_imu_csv();
        finalize_timeline();
        build_capabilities();
    }

    void read_capture_json() {
        const auto path = root / "capture.json";
        cv::FileStorage file(path.string(), cv::FileStorage::READ | cv::FileStorage::FORMAT_JSON);
        if (!file.isOpened()) {
            throw std::runtime_error("cannot open replay capture.json: " + path.string());
        }

        file["schema"] >> metadata.source_schema;
        if (metadata.source_schema != kNoriDynamicSchema) {
            throw std::runtime_error(
                "unsupported replay source schema: " + metadata.source_schema);
        }

        const auto device = file["device"];
        metadata.product = read_string(device, "product");
        metadata.serial = read_string(device, "serial");
        metadata.sdk_version = read_string(device, "sdk_version");
        metadata.device_type = read_string(device, "device_type");
        metadata.isp_version = read_string(device, "isp_version");
        metadata.fpga_version = read_string(device, "fpga_version");

        const auto mode = file["mode"];
        const int mode_index = read_int(mode, "index", 0);
        if (mode_index < 0) throw std::runtime_error("capture.json mode.index must be >= 0");
        metadata.mode_index = static_cast<std::uint32_t>(mode_index);
        metadata.nominal_fps = read_double(mode, "nominal_fps", 0.0);

        const auto run = file["run"];
        const int stride = read_int(run, "frame_stride", 1);
        if (stride <= 0) throw std::runtime_error("capture.json run.frame_stride must be >= 1");
        metadata.frame_stride = static_cast<std::uint32_t>(stride);

        const auto provenance = file["provenance"];
        if (!provenance.empty()) {
            metadata.evidence = parse_evidence_kind(read_string(provenance, "kind"));
        }
        if (config.evidence_override != EvidenceKind::unknown) {
            metadata.evidence = config.evidence_override;
        }

        if (!config.source_id.empty()) {
            source_id = config.source_id;
        } else if (!metadata.serial.empty()) {
            source_id = "replay:nori:" + metadata.serial;
        } else {
            source_id = "replay:" + root.filename().string();
        }
    }

    void read_frames_csv() {
        const auto path = root / "frames.csv";
        std::ifstream input(path, std::ios::binary);
        if (!input) throw std::runtime_error("cannot open frames.csv: " + path.string());

        std::string line;
        if (!std::getline(input, line)) throw std::runtime_error("frames.csv is empty");
        const auto header = header_map(split_csv(line));
        const auto i_frame = require_column(header, "frame_index");
        const auto i_sequence = require_column(header, "frame_sequence");
        const auto i_host = require_column(header, "host_receive_monotonic_ns");
        const auto i_es_raw = require_column(header, "exposure_start_raw_us");
        const auto i_ee_raw = require_column(header, "exposure_end_raw_us");
        const auto i_es_ext = require_column(header, "exposure_start_extended_us");
        const auto i_ee_ext = require_column(header, "exposure_end_extended_us");
        const auto i_a = require_column(header, "camera_a_path");
        const auto i_b = require_column(header, "camera_b_path");

        while (std::getline(input, line)) {
            if (line.empty() || line == "\r") continue;
            const auto fields = split_csv(line);
            const auto frame_index = parse_u64(field(fields, i_frame, "frame_index"), "frame_index");
            auto& record = records[frame_index];
            record.frame_index = frame_index;
            merge_identity(
                record,
                parse_u64(field(fields, i_sequence, "frame_sequence"), "frame_sequence"),
                parse_u64(field(fields, i_host, "host_receive_monotonic_ns"), "host_receive_monotonic_ns"),
                parse_u32(field(fields, i_es_raw, "exposure_start_raw_us"), "exposure_start_raw_us"),
                parse_u32(field(fields, i_ee_raw, "exposure_end_raw_us"), "exposure_end_raw_us"),
                parse_u64(field(fields, i_es_ext, "exposure_start_extended_us"), "exposure_start_extended_us"),
                parse_u64(field(fields, i_ee_ext, "exposure_end_extended_us"), "exposure_end_extended_us"));
            if (record.images_present) {
                throw std::runtime_error("duplicate frames.csv frame_index: " + std::to_string(frame_index));
            }
            record.images_present = true;
            record.camera_a_path = contained_path(root, field(fields, i_a, "camera_a_path"));
            record.camera_b_path = contained_path(root, field(fields, i_b, "camera_b_path"));
            ++metadata.image_pairs;
        }
    }

    void read_imu_csv() {
        const auto path = root / "imu.csv";
        std::ifstream input(path, std::ios::binary);
        if (!input) throw std::runtime_error("cannot open imu.csv: " + path.string());

        std::string line;
        if (!std::getline(input, line)) throw std::runtime_error("imu.csv is empty");
        const auto header = header_map(split_csv(line));
        const auto i_frame = require_column(header, "frame_index");
        const auto i_sequence = require_column(header, "frame_sequence");
        const auto i_host = require_column(header, "host_receive_monotonic_ns");
        const auto i_es_raw = require_column(header, "exposure_start_raw_us");
        const auto i_ee_raw = require_column(header, "exposure_end_raw_us");
        const auto i_es_ext = require_column(header, "exposure_start_extended_us");
        const auto i_ee_ext = require_column(header, "exposure_end_extended_us");
        const auto i_sample = require_column(header, "sample_index");
        const auto i_valid = require_column(header, "sample_valid");
        const auto i_raw_time = require_column(header, "imu_raw_time_us");
        const auto i_ext_time = require_column(header, "imu_extended_time_us");
        const auto i_ax = require_column(header, "accel_raw_x");
        const auto i_ay = require_column(header, "accel_raw_y");
        const auto i_az = require_column(header, "accel_raw_z");
        const auto i_gx = require_column(header, "gyro_raw_x");
        const auto i_gy = require_column(header, "gyro_raw_y");
        const auto i_gz = require_column(header, "gyro_raw_z");

        while (std::getline(input, line)) {
            if (line.empty() || line == "\r") continue;
            const auto fields = split_csv(line);
            const auto frame_index = parse_u64(field(fields, i_frame, "frame_index"), "frame_index");
            auto& record = records[frame_index];
            record.frame_index = frame_index;
            merge_identity(
                record,
                parse_u64(field(fields, i_sequence, "frame_sequence"), "frame_sequence"),
                parse_u64(field(fields, i_host, "host_receive_monotonic_ns"), "host_receive_monotonic_ns"),
                parse_u32(field(fields, i_es_raw, "exposure_start_raw_us"), "exposure_start_raw_us"),
                parse_u32(field(fields, i_ee_raw, "exposure_end_raw_us"), "exposure_end_raw_us"),
                parse_u64(field(fields, i_es_ext, "exposure_start_extended_us"), "exposure_start_extended_us"),
                parse_u64(field(fields, i_ee_ext, "exposure_end_extended_us"), "exposure_end_extended_us"));

            ImuRecord sample{};
            sample.sample_index = parse_u64(field(fields, i_sample, "sample_index"), "sample_index");
            sample.valid = parse_bool(field(fields, i_valid, "sample_valid"), "sample_valid");
            sample.raw_time_us = parse_u32(field(fields, i_raw_time, "imu_raw_time_us"), "imu_raw_time_us");
            sample.extended_time_us = parse_u64(field(fields, i_ext_time, "imu_extended_time_us"), "imu_extended_time_us");
            sample.accel = {{
                parse_i32(field(fields, i_ax, "accel_raw_x"), "accel_raw_x"),
                parse_i32(field(fields, i_ay, "accel_raw_y"), "accel_raw_y"),
                parse_i32(field(fields, i_az, "accel_raw_z"), "accel_raw_z"),
            }};
            sample.gyro = {{
                parse_i32(field(fields, i_gx, "gyro_raw_x"), "gyro_raw_x"),
                parse_i32(field(fields, i_gy, "gyro_raw_y"), "gyro_raw_y"),
                parse_i32(field(fields, i_gz, "gyro_raw_z"), "gyro_raw_z"),
            }};
            record.imu.push_back(sample);
            ++metadata.imu_samples;
        }
    }

    void finalize_timeline() {
        if (records.empty()) {
            throw std::runtime_error("replay session contains no observations");
        }
        timeline.reserve(records.size());
        for (auto& entry : records) {
            if (!entry.second.identity_present) {
                throw std::runtime_error("replay timeline record lacks identity metadata");
            }
            std::sort(
                entry.second.imu.begin(),
                entry.second.imu.end(),
                [](const ImuRecord& a, const ImuRecord& b) {
                    return a.sample_index < b.sample_index;
                });
            timeline.push_back(std::move(entry.second));
        }
        records.clear();
        metadata.timeline_observations = timeline.size();
    }

    std::pair<cv::Mat, cv::Mat> read_pair(const TimelineRecord& record) const {
        if (!record.images_present) return {};
        auto a = cv::imread(record.camera_a_path.string(), cv::IMREAD_UNCHANGED);
        auto b = cv::imread(record.camera_b_path.string(), cv::IMREAD_UNCHANGED);
        if (a.empty() || b.empty()) {
            throw std::runtime_error(
                "failed to decode replay image pair at frame_index " +
                std::to_string(record.frame_index));
        }
        if (a.size() != b.size() || a.type() != b.type()) {
            throw std::runtime_error(
                "replay camera A/B image geometry or representation mismatch at frame_index " +
                std::to_string(record.frame_index));
        }
        if (pixel_format(a) == PixelFormat::unknown) {
            throw std::runtime_error("replay image must be 8-bit mono or BGR");
        }
        return {std::move(a), std::move(b)};
    }

    void build_capabilities() {
        const TimelineRecord* image_record = nullptr;
        for (const auto& record : timeline) {
            if (record.images_present) {
                image_record = &record;
                break;
            }
        }
        if (image_record == nullptr) {
            throw std::runtime_error("replay session contains no image pairs");
        }

        const auto images = read_pair(*image_record);
        const auto format = pixel_format(images.first);
        capabilities.cameras = {
            {"camera_a", "primary", format, CameraModality::unknown,
             static_cast<std::uint32_t>(images.first.cols), static_cast<std::uint32_t>(images.first.rows)},
            {"camera_b", "primary", format, CameraModality::unknown,
             static_cast<std::uint32_t>(images.second.cols), static_cast<std::uint32_t>(images.second.rows)},
        };
        capabilities.stereo_pairs = {{"stereo0", "camera_a", "camera_b"}};
        capabilities.imu = metadata.imu_samples != 0;
        capabilities.timing.host_receive_monotonic = true;
        capabilities.timing.device_frame_time = false;
        capabilities.timing.exposure_start_end = true;
        capabilities.timing.imu_sample_time = capabilities.imu;
        capabilities.timing.hardware_sync = false;

        const auto result = validate_capabilities(capabilities);
        if (!result.ok) {
            throw std::runtime_error("replay capabilities failed conformance validation");
        }
    }

    void pace(const TimelineRecord& record, SensorObservation& observation) {
        if (config.pacing == ReplayPacing::step ||
            config.pacing == ReplayPacing::as_fast_as_possible) {
            return;
        }

        const double rate = config.pacing == ReplayPacing::scaled ? config.rate : 1.0;
        if (!schedule_started) {
            schedule_started = true;
            schedule_wall_start = Clock::now();
            schedule_source_start_ns = record.host_receive_monotonic_ns;
        }

        std::uint64_t replay_ns = 0;
        if (record.host_receive_monotonic_ns >= schedule_source_start_ns) {
            const auto source_delta = record.host_receive_monotonic_ns - schedule_source_start_ns;
            replay_ns = static_cast<std::uint64_t>(static_cast<long double>(source_delta) / rate);
            const auto target = schedule_wall_start + std::chrono::nanoseconds(replay_ns);
            std::this_thread::sleep_until(target);
        }
        observation.timing.replay_schedule = {
            replay_ns,
            TimeUnit::nanoseconds,
            ClockDomain::replay,
            "replay.timeline",
            true,
        };
    }

    SensorObservation materialize(const TimelineRecord& record) {
        SensorObservation observation{};
        observation.source_id = source_id;
        observation.evidence = metadata.evidence;
        observation.source_state = SourceState::available;
        observation.sequence = record.sequence;
        observation.sequence_present = true;
        observation.continuity_epoch = continuity_epoch;
        observation.continuity = position_index == 0 ? ContinuityState::reinitialized : ContinuityState::continuous;
        observation.timing.host_receive = {
            record.host_receive_monotonic_ns,
            TimeUnit::nanoseconds,
            ClockDomain::host_monotonic,
            "recorded.host_monotonic",
            true,
        };

        if (have_previous && record.host_receive_monotonic_ns < previous_host_ns) {
            ++continuity_epoch;
            observation.continuity_epoch = continuity_epoch;
            observation.continuity = ContinuityState::discontinuity;
        }
        if (have_previous && record.frame_index > previous_frame_index + 1) {
            ++continuity_epoch;
            observation.continuity_epoch = continuity_epoch;
            observation.continuity = ContinuityState::discontinuity;
        }

        ExposureTiming exposure{};
        exposure.start = device_us(record.exposure_start_extended_us, "recorded.decXIN.camera");
        exposure.end = device_us(record.exposure_end_extended_us, "recorded.decXIN.camera");
        exposure.raw_start = raw_device_us(record.exposure_start_raw_us, "recorded.decXIN.camera");
        exposure.raw_end = raw_device_us(record.exposure_end_raw_us, "recorded.decXIN.camera");

        if (record.images_present) {
            auto images = read_pair(record);
            if (images.first.cols != static_cast<int>(capabilities.cameras[0].width) ||
                images.first.rows != static_cast<int>(capabilities.cameras[0].height) ||
                pixel_format(images.first) != capabilities.cameras[0].pixel_format) {
                throw std::runtime_error(
                    "replay image geometry/format changed at frame_index " +
                    std::to_string(record.frame_index));
            }

            auto* owner = new ImageOwner{std::move(images.first), std::move(images.second)};
            auto lease = FrameLease::adopt(owner, [](ImageOwner* value) noexcept { delete value; });

            CameraObservation a{};
            a.stream_id = "camera_a";
            a.lease = lease;
            a.image = image_view(owner->camera_a);
            a.exposure = exposure;
            a.validity = ObservationValidity::valid;
            observation.cameras.push_back(std::move(a));

            CameraObservation b{};
            b.stream_id = "camera_b";
            b.lease = lease;
            b.image = image_view(owner->camera_b);
            b.exposure = exposure;
            b.validity = ObservationValidity::valid;
            observation.cameras.push_back(std::move(b));

            observation.stereo_pairs.push_back({"stereo0", SynchronizationState::unknown});
        }

        bool any_valid_imu = false;
        observation.imu.reserve(record.imu.size());
        for (const auto& source : record.imu) {
            ImuObservation sample{};
            sample.sensor_id = "imu0";
            sample.sample_time = device_us(source.extended_time_us, "recorded.decXIN.imu");
            sample.raw_time = raw_device_us(source.raw_time_us, "recorded.decXIN.imu");
            sample.accel_raw_counts = source.accel;
            sample.gyro_raw_counts = source.gyro;
            sample.raw_valid = source.valid;
            sample.si_valid = false;
            sample.validity = source.valid ? ObservationValidity::valid : ObservationValidity::invalid;
            any_valid_imu = any_valid_imu || source.valid;
            observation.imu.push_back(sample);
        }

        if (!observation.cameras.empty() || any_valid_imu) {
            observation.validity = ObservationValidity::valid;
        } else if (!observation.imu.empty()) {
            observation.validity = ObservationValidity::degraded;
        } else {
            observation.validity = ObservationValidity::invalid;
        }

        pace(record, observation);

        const auto conformance = validate_observation(observation, &capabilities);
        if (!conformance.ok) {
            std::string message = "replay observation failed conformance:";
            for (const auto& error : conformance.errors) message += " " + error + ";";
            throw std::runtime_error(message);
        }
        return observation;
    }

    ReplayConfig config;
    fs::path root;
    std::string source_id;
    ReplayMetadata metadata{};
    SensorCapabilities capabilities{};
    std::map<std::uint64_t, TimelineRecord> records;
    std::vector<TimelineRecord> timeline;
    std::size_t position_index = 0;
    std::uint64_t continuity_epoch = 0;
    bool have_previous = false;
    std::uint64_t previous_host_ns = 0;
    std::uint64_t previous_frame_index = 0;
    bool schedule_started = false;
    Clock::time_point schedule_wall_start{};
    std::uint64_t schedule_source_start_ns = 0;
};

ReplaySource::ReplaySource(ReplayConfig config)
    : impl_(std::make_unique<Impl>(std::move(config))) {}

ReplaySource::~ReplaySource() = default;
ReplaySource::ReplaySource(ReplaySource&&) noexcept = default;
ReplaySource& ReplaySource::operator=(ReplaySource&&) noexcept = default;

const SensorCapabilities& ReplaySource::capabilities() const noexcept {
    return impl_->capabilities;
}

const ReplayMetadata& ReplaySource::metadata() const noexcept {
    return impl_->metadata;
}

std::size_t ReplaySource::size() const noexcept {
    return impl_->timeline.size();
}

std::size_t ReplaySource::position() const noexcept {
    return impl_->position_index;
}

bool ReplaySource::eof() const noexcept {
    return impl_->position_index >= impl_->timeline.size();
}

bool ReplaySource::next(SensorObservation& out) {
    if (eof()) {
        out = {};
        return false;
    }

    const auto& record = impl_->timeline[impl_->position_index];
    out = impl_->materialize(record);
    impl_->have_previous = true;
    impl_->previous_host_ns = record.host_receive_monotonic_ns;
    impl_->previous_frame_index = record.frame_index;
    ++impl_->position_index;
    return true;
}

void ReplaySource::reset() {
    impl_->position_index = 0;
    impl_->continuity_epoch = 0;
    impl_->have_previous = false;
    impl_->previous_host_ns = 0;
    impl_->previous_frame_index = 0;
    impl_->schedule_started = false;
    impl_->schedule_source_start_ns = 0;
}

const char* replay_pacing_name(ReplayPacing pacing) noexcept {
    switch (pacing) {
        case ReplayPacing::step: return "step";
        case ReplayPacing::as_fast_as_possible: return "as-fast-as-possible";
        case ReplayPacing::real_time: return "real-time";
        case ReplayPacing::scaled: return "scaled";
    }
    return "unknown";
}

}  // namespace bividi
