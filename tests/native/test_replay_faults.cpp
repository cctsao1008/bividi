#include "bividi/replay_faults.hpp"

#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;

struct TempFile {
    fs::path path;

    explicit TempFile(const std::string& content) {
        const auto nonce = std::chrono::steady_clock::now().time_since_epoch().count();
        path = fs::temp_directory_path() / ("bividi-fault-recipe-" + std::to_string(nonce) + ".json");
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        if (!out) throw std::runtime_error("cannot create temporary recipe");
        out << content;
        out.close();
    }

    ~TempFile() {
        std::error_code error;
        fs::remove(path, error);
    }
};

bividi::TimePoint host_ns(std::uint64_t ticks) {
    return {ticks, bividi::TimeUnit::nanoseconds, bividi::ClockDomain::host_monotonic, "fixture.host", true};
}

bividi::TimePoint device_us(std::uint64_t ticks, const std::string& id) {
    return {ticks, bividi::TimeUnit::microseconds, bividi::ClockDomain::device, id, true};
}

bividi::RawTimestampEvidence raw_device_us(std::uint32_t ticks, const std::string& id) {
    return {ticks, 32, bividi::TimeUnit::microseconds, id, true};
}

bividi::ExposureTiming exposure(std::uint64_t start, std::uint64_t end) {
    bividi::ExposureTiming result{};
    result.start = device_us(start, "fixture.camera");
    result.end = device_us(end, "fixture.camera");
    result.raw_start = raw_device_us(static_cast<std::uint32_t>(start), "fixture.camera");
    result.raw_end = raw_device_us(static_cast<std::uint32_t>(end), "fixture.camera");
    return result;
}

bividi::ImuObservation imu_sample(std::uint64_t ticks, int bias = 0) {
    bividi::ImuObservation imu{};
    imu.sensor_id = "imu0";
    imu.sample_time = device_us(ticks, "fixture.imu");
    imu.raw_time = raw_device_us(static_cast<std::uint32_t>(ticks), "fixture.imu");
    imu.accel_raw_counts = {1 + bias, 2 + bias, 3 + bias};
    imu.gyro_raw_counts = {4 + bias, 5 + bias, 6 + bias};
    imu.raw_valid = true;
    imu.validity = bividi::ObservationValidity::valid;
    return imu;
}

bividi::SensorObservation make_observation(std::uint64_t sequence) {
    bividi::SensorObservation observation{};
    observation.source_id = "fixture";
    observation.evidence = bividi::EvidenceKind::synthetic;
    observation.source_state = bividi::SourceState::available;
    observation.validity = bividi::ObservationValidity::valid;
    observation.sequence = sequence;
    observation.sequence_present = true;
    observation.continuity_epoch = 7;
    observation.continuity = bividi::ContinuityState::continuous;
    observation.timing.host_receive = host_ns(1'000'000'000ULL + sequence * 1'000'000ULL);

    // Fault tests do not dereference image bytes. Invalid camera observations
    // still carry timing evidence so device-clock mutation can be tested without
    // manufacturing an image lease.
    bividi::CameraObservation a{};
    a.stream_id = "camera_a";
    a.exposure = exposure(1'000 + sequence, 1'100 + sequence);
    a.validity = bividi::ObservationValidity::invalid;
    bividi::CameraObservation b{};
    b.stream_id = "camera_b";
    b.exposure = exposure(1'000 + sequence, 1'100 + sequence);
    b.validity = bividi::ObservationValidity::invalid;
    observation.cameras = {a, b};
    observation.stereo_pairs.push_back({"stereo0", bividi::SynchronizationState::unknown});

    observation.imu.push_back(imu_sample(2'000 + sequence));
    return observation;
}

bividi::SensorObservation make_multi_imu_observation(std::uint64_t sequence) {
    auto observation = make_observation(sequence);
    observation.imu.push_back(imu_sample(2'010 + sequence, 10));
    observation.imu.push_back(imu_sample(2'020 + sequence, 20));
    return observation;
}

const char* kRecipeV1 = R"JSON({
  "schema": "bividi.replay_fault_recipe.v1",
  "seed": "18446744073709551615",
  "rules": [
    {
      "id": "duplicate-zero",
      "at_source_position": 0,
      "action": "duplicate",
      "copies": 1,
      "expected_disposition": "observe_fault"
    },
    {
      "id": "host-backward-zero",
      "at_source_position": 0,
      "action": "host_time_delta_ns",
      "delta": -500000,
      "expected_disposition": "consumer_reject"
    },
    {
      "id": "missing-camera-b",
      "at_source_position": 1,
      "action": "remove_camera",
      "stream_id": "camera_b",
      "expected_disposition": "consumer_degraded"
    },
    {
      "id": "stereo-unsync",
      "at_source_position": 1,
      "action": "set_stereo_synchronization",
      "pair_id": "stereo0",
      "state": "unsynchronized",
      "expected_disposition": "consumer_degraded"
    },
    {
      "id": "imu-time-jump",
      "at_source_position": 2,
      "action": "imu_sample_time_delta_us",
      "delta": 10000,
      "expected_disposition": "consumer_reject"
    },
    {
      "id": "sequence-backward",
      "at_source_position": 2,
      "action": "sequence_delta",
      "delta": -2,
      "expected_disposition": "explicit_gap"
    },
    {
      "id": "new-epoch",
      "at_source_position": 2,
      "action": "set_continuity",
      "state": "discontinuity",
      "epoch_delta": 1,
      "expected_disposition": "reset_derived_pipeline"
    },
    {
      "id": "drop-three",
      "at_source_position": 3,
      "action": "drop",
      "expected_disposition": "explicit_gap"
    },
    {
      "id": "drop-imu-four",
      "at_source_position": 4,
      "action": "drop_all_imu",
      "expected_disposition": "consumer_reject"
    }
  ]
})JSON";

const char* kRecipeV2 = R"JSON({
  "schema": "bividi.replay_fault_recipe.v2",
  "seed": 42,
  "rules": [
    {
      "id": "camera-b-backward",
      "at_source_position": 0,
      "action": "camera_exposure_time_delta_us",
      "stream_id": "camera_b",
      "delta": -100,
      "expected_disposition": "consumer_degraded"
    },
    {
      "id": "imu-index-duplicate-time",
      "at_source_position": 0,
      "action": "imu_sample_time_delta_at_index_us",
      "imu_index": 1,
      "delta": -10,
      "expected_disposition": "consumer_reject"
    },
    {
      "id": "duplicate-one-imu",
      "at_source_position": 1,
      "action": "duplicate_imu_sample",
      "imu_index": 0,
      "copies": 2,
      "expected_disposition": "consumer_reject"
    },
    {
      "id": "drop-middle-imu",
      "at_source_position": 2,
      "action": "drop_imu_sample",
      "imu_index": 1,
      "expected_disposition": "explicit_gap"
    }
  ]
})JSON";

void test_v1_recipe_remains_compatible() {
    TempFile recipe_file(kRecipeV1);
    const auto recipe = bividi::load_replay_fault_recipe(recipe_file.path);
    assert(recipe.schema == bividi::kReplayFaultRecipeSchemaV1);
    assert(recipe.seed == std::numeric_limits<std::uint64_t>::max());
    assert(recipe.rules.size() == 9);
    assert(recipe.rules[0].action == bividi::ReplayFaultAction::duplicate);
    assert(recipe.rules[0].copies == 1);
    assert(recipe.rules[7].expected == bividi::ReplayFaultExpectedDisposition::explicit_gap);

    bividi::RecipeReplayInterceptor interceptor(recipe);
    std::vector<bividi::SensorObservation> output;

    const auto zero = make_observation(10);
    interceptor.transform(0, zero, output);
    assert(output.size() == 2);
    assert(output[0].sequence == 10 && output[1].sequence == 10);
    assert(output[0].timing.host_receive.ticks == zero.timing.host_receive.ticks - 500'000ULL);
    assert(output[1].timing.host_receive.ticks == output[0].timing.host_receive.ticks);

    output.clear();
    interceptor.transform(1, make_observation(11), output);
    assert(output.size() == 1);
    assert(output[0].cameras.size() == 1);
    assert(output[0].cameras[0].stream_id == "camera_a");
    assert(output[0].stereo_pairs.size() == 1);
    assert(output[0].stereo_pairs[0].synchronization == bividi::SynchronizationState::unsynchronized);

    output.clear();
    const auto two = make_observation(12);
    interceptor.transform(2, two, output);
    assert(output.size() == 1);
    assert(output[0].sequence == 10);
    assert(output[0].imu[0].sample_time.ticks == two.imu[0].sample_time.ticks + 10'000ULL);
    assert(output[0].imu[0].raw_time.raw_ticks == two.imu[0].raw_time.raw_ticks);
    assert(output[0].continuity == bividi::ContinuityState::discontinuity);
    assert(output[0].continuity_epoch == 8);

    output.clear();
    interceptor.transform(3, make_observation(13), output);
    assert(output.empty());

    output.clear();
    interceptor.transform(4, make_observation(14), output);
    assert(output.size() == 1);
    assert(output[0].imu.empty());
    assert(output[0].cameras.size() == 2);

    const auto stats = interceptor.stats();
    assert(stats.source_observations == 5);
    assert(stats.emitted_observations == 5);
    assert(stats.triggered_rules == 9);

    interceptor.reset();
    assert(interceptor.stats().source_observations == 0);
    assert(interceptor.stats().emitted_observations == 0);
    assert(interceptor.stats().triggered_rules == 0);
}

void test_v2_device_clock_and_indexed_imu_actions() {
    TempFile recipe_file(kRecipeV2);
    const auto recipe = bividi::load_replay_fault_recipe(recipe_file.path);
    assert(recipe.schema == bividi::kReplayFaultRecipeSchemaV2);
    assert(recipe.rules.size() == 4);

    bividi::RecipeReplayInterceptor interceptor(recipe);
    std::vector<bividi::SensorObservation> output;

    const auto zero = make_multi_imu_observation(20);
    interceptor.transform(0, zero, output);
    assert(output.size() == 1);
    assert(output[0].cameras[0].exposure.start.ticks == zero.cameras[0].exposure.start.ticks);
    assert(output[0].cameras[1].exposure.start.ticks == zero.cameras[1].exposure.start.ticks - 100ULL);
    assert(output[0].cameras[1].exposure.end.ticks == zero.cameras[1].exposure.end.ticks - 100ULL);
    // Normalized exposure moved but finite-width transport evidence was not repaired.
    assert(output[0].cameras[1].exposure.raw_start.raw_ticks == zero.cameras[1].exposure.raw_start.raw_ticks);
    assert(output[0].cameras[1].exposure.raw_end.raw_ticks == zero.cameras[1].exposure.raw_end.raw_ticks);
    assert(output[0].imu.size() == 3);
    assert(output[0].imu[1].sample_time.ticks == output[0].imu[0].sample_time.ticks);
    assert(output[0].imu[1].raw_time.raw_ticks == zero.imu[1].raw_time.raw_ticks);

    output.clear();
    const auto one = make_multi_imu_observation(21);
    interceptor.transform(1, one, output);
    assert(output.size() == 1);
    assert(output[0].imu.size() == 5);
    assert(output[0].imu[0].sample_time.ticks == output[0].imu[1].sample_time.ticks);
    assert(output[0].imu[0].sample_time.ticks == output[0].imu[2].sample_time.ticks);
    assert(output[0].imu[3].sample_time.ticks == one.imu[1].sample_time.ticks);

    output.clear();
    const auto two = make_multi_imu_observation(22);
    interceptor.transform(2, two, output);
    assert(output.size() == 1);
    assert(output[0].imu.size() == 2);
    assert(output[0].imu[0].sample_time.ticks == two.imu[0].sample_time.ticks);
    assert(output[0].imu[1].sample_time.ticks == two.imu[2].sample_time.ticks);

    const auto stats = interceptor.stats();
    assert(stats.source_observations == 3);
    assert(stats.emitted_observations == 3);
    assert(stats.triggered_rules == 4);
}

void test_v1_rejects_v2_only_action() {
    TempFile recipe_file(R"JSON({
      "schema": "bividi.replay_fault_recipe.v1",
      "seed": 0,
      "rules": [{
        "id": "too-new",
        "at_source_position": 0,
        "action": "drop_imu_sample",
        "imu_index": 0,
        "expected_disposition": "explicit_gap"
      }]
    })JSON");

    bool rejected = false;
    try {
        (void)bividi::load_replay_fault_recipe(recipe_file.path);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    assert(rejected);

    bividi::ReplayFaultRecipe programmatic{};
    programmatic.schema = bividi::kReplayFaultRecipeSchemaV1;
    bividi::ReplayFaultRule rule{};
    rule.id = "too-new-programmatic";
    rule.action = bividi::ReplayFaultAction::drop_imu_sample;
    programmatic.rules.push_back(rule);
    rejected = false;
    try {
        bividi::validate_replay_fault_recipe(programmatic);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void test_programmatic_validation_rejects_ambiguous_drop_position() {
    bividi::ReplayFaultRecipe recipe{};
    bividi::ReplayFaultRule drop{};
    drop.id = "drop";
    drop.at_source_position = 1;
    drop.action = bividi::ReplayFaultAction::drop;
    recipe.rules.push_back(drop);

    bividi::ReplayFaultRule delta{};
    delta.id = "delta";
    delta.at_source_position = 1;
    delta.action = bividi::ReplayFaultAction::sequence_delta;
    delta.delta = 1;
    recipe.rules.push_back(delta);

    bool rejected = false;
    try {
        bividi::validate_replay_fault_recipe(recipe);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void test_json_rejects_unknown_action_fields() {
    TempFile recipe_file(R"JSON({
      "schema": "bividi.replay_fault_recipe.v1",
      "seed": 0,
      "rules": [{
        "id": "bad",
        "at_source_position": 0,
        "action": "drop",
        "copies": 2,
        "expected_disposition": "explicit_gap"
      }]
    })JSON");

    bool rejected = false;
    try {
        (void)bividi::load_replay_fault_recipe(recipe_file.path);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    assert(rejected);
}

void test_indexed_actions_reject_missing_index() {
    TempFile recipe_file(R"JSON({
      "schema": "bividi.replay_fault_recipe.v2",
      "seed": 0,
      "rules": [{
        "id": "bad-index",
        "at_source_position": 0,
        "action": "drop_imu_sample",
        "imu_index": 99,
        "expected_disposition": "consumer_reject"
      }]
    })JSON");
    const auto recipe = bividi::load_replay_fault_recipe(recipe_file.path);
    bividi::RecipeReplayInterceptor interceptor(recipe);
    std::vector<bividi::SensorObservation> output;
    bool rejected = false;
    try {
        interceptor.transform(0, make_observation(1), output);
    } catch (const std::runtime_error&) {
        rejected = true;
    }
    assert(rejected);
}

void test_fault_name_surfaces() {
    assert(std::string(bividi::replay_fault_action_name(bividi::ReplayFaultAction::remove_camera)) == "remove_camera");
    assert(std::string(bividi::replay_fault_action_name(
               bividi::ReplayFaultAction::camera_exposure_time_delta_us)) == "camera_exposure_time_delta_us");
    assert(std::string(bividi::replay_fault_action_name(
               bividi::ReplayFaultAction::duplicate_imu_sample)) == "duplicate_imu_sample");
    assert(std::string(bividi::replay_fault_expected_disposition_name(
               bividi::ReplayFaultExpectedDisposition::reset_derived_pipeline)) == "reset_derived_pipeline");
}

}  // namespace

int main() {
    test_v1_recipe_remains_compatible();
    test_v2_device_clock_and_indexed_imu_actions();
    test_v1_rejects_v2_only_action();
    test_programmatic_validation_rejects_ambiguous_drop_position();
    test_json_rejects_unknown_action_fields();
    test_indexed_actions_reject_missing_index();
    test_fault_name_surfaces();
    std::cout << "bividi replay fault recipe tests: PASS\n";
    return 0;
}
