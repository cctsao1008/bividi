#include "bividi/decxin_observation.hpp"

#include <stdexcept>

namespace bividi::decxin {
namespace {

TimePoint device_us(std::uint64_t ticks, const std::string& clock_id) {
    return TimePoint{
        ticks,
        TimeUnit::microseconds,
        ClockDomain::device,
        clock_id,
        true,
    };
}

RawTimestampEvidence raw_device_us(
    std::uint32_t ticks,
    const std::string& clock_id) {
    return RawTimestampEvidence{
        ticks,
        32,
        TimeUnit::microseconds,
        clock_id,
        true,
    };
}

}  // namespace

SensorObservation to_sensor_observation(
    const DecodedFrame& decoded,
    const ObservationContext& context) {
    if (!decoded.valid()) {
        throw std::invalid_argument("cannot normalize an invalid DECXIN frame");
    }
    if (!decoded.lease.valid()) {
        throw std::invalid_argument("DECXIN observation requires a leased backing frame");
    }
    if (context.source_id.empty()) {
        throw std::invalid_argument("DECXIN observation source_id must not be empty");
    }
    if (context.camera_a_stream_id.empty() || context.camera_b_stream_id.empty() ||
        context.camera_a_stream_id == context.camera_b_stream_id) {
        throw std::invalid_argument("DECXIN camera stream ids must be distinct and non-empty");
    }
    if (context.camera_clock_id.empty() || context.imu_clock_id.empty()) {
        throw std::invalid_argument("DECXIN normalized device clock ids must not be empty");
    }

    SensorObservation observation{};
    observation.source_id = context.source_id;
    observation.evidence = context.evidence;
    observation.source_state = SourceState::available;
    observation.validity = ObservationValidity::valid;
    observation.sequence = decoded.sequence;
    observation.continuity_epoch = context.continuity_epoch;
    observation.continuity = context.continuity;
    observation.calibration = context.calibration;
    observation.configuration_revision = context.configuration_revision;
    observation.timing.host_receive = TimePoint{
        decoded.host_receive_monotonic_ns,
        TimeUnit::nanoseconds,
        ClockDomain::host_monotonic,
        "host.steady_clock",
        true,
    };

    ExposureTiming exposure{};
    exposure.start = device_us(decoded.timing.exposure_start_us, context.camera_clock_id);
    exposure.end = device_us(decoded.timing.exposure_end_us, context.camera_clock_id);
    exposure.raw_start = raw_device_us(
        decoded.timing.header.exposure_start_raw_us,
        context.camera_clock_id);
    exposure.raw_end = raw_device_us(
        decoded.timing.header.exposure_end_raw_us,
        context.camera_clock_id);

    observation.cameras.push_back(CameraObservation{
        context.camera_a_stream_id,
        decoded.lease,
        decoded.camera_a,
        exposure,
        ObservationValidity::valid,
    });
    observation.cameras.push_back(CameraObservation{
        context.camera_b_stream_id,
        decoded.lease,
        decoded.camera_b,
        exposure,
        ObservationValidity::valid,
    });

    observation.imu.reserve(decoded.timing.imu_samples.size());
    for (const auto& raw : decoded.timing.imu_samples) {
        ImuObservation sample{};
        sample.sensor_id = "imu0";
        sample.sample_time = device_us(raw.extended_time_us, context.imu_clock_id);
        sample.raw_time = raw_device_us(raw.raw_time_us, context.imu_clock_id);
        for (std::size_t axis = 0; axis < 3; ++axis) {
            sample.accel_raw_counts[axis] = raw.accel_raw[axis];
            sample.gyro_raw_counts[axis] = raw.gyro_raw[axis];
        }
        sample.raw_valid = raw.valid;
        sample.si_valid = false;
        sample.validity = raw.valid ? ObservationValidity::valid : ObservationValidity::invalid;
        observation.imu.push_back(sample);
    }

    return observation;
}

}  // namespace bividi::decxin
