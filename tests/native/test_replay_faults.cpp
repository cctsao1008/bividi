#include "bividi/replay_faults.hpp"

#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
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

    // Fault tests do not dereference image bytes. An invalid camera observation
    // is still sufficient to exercise stream/pair metadata mutation.
    bividi::CameraObservation a{};
    a.stream_id = "camera_a";
    a.validity = bividi::ObservationValidity::invalid;
    bividi::CameraObservation b{};
    b.stream_id = "camera_b";
    b.validity = bividi::ObservationValidity::invalid;
    observation.cameras = {a, b};
    observation.stereo_pairs.push_back({"stereo0", bividi::SynchronizationState::unknown});

    bividi::ImuObservation imu{};
    imu.sensor_id = "imu0";
    imu.sample_time = device_us(2'000 + sequence, "fixture.imu");
    imu.raw_time = {2'000 + sequence, 32, bividi::TimeUnit::microseconds, "fixture.imu", true};
    imu.accel_raw_counts = {1, 2, 3};
    imu.gyro_raw_counts = {4, 5, 6};
    imu.raw_valid = true;
    imu.validity = bividi::ObservationValidity::valid;
    observation.imu.push_back(imu);
    return observation;
}

const char* kRecipe = R"JSON({
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

void test_recipe_load_and_deterministic_actions() {
    TempFile recipe_file(kRecipe);
    const auto recipe = bividi::load_replay_fault_recipe(recipe_file.path);
    assert(recipe.schema == bividi::kReplayFaultRecipeSchema);
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
    // Raw finite-width evidence is deliberately unchanged, making the injected
    // normalized timestamp jump observable instead of silently repairing it.
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
    // Cameras remain present, so this particular mutation remains structurally
    // representable. Consumers still see the explicit recipe expectation.
    assert(output[0].cameras.size() == 2);

    const auto stats = interceptor.stats();
    assert(stats.source_observations == 5);
    assert(stats.emitted_observations == 5);  // 2 + 1 + 1 + 0 + 1
    assert(stats.triggered_rules == 9);

    interceptor.reset();
    assert(interceptor.stats().source_observations == 0);
    assert(interceptor.stats().emitted_observations == 0);
    assert(interceptor.stats().triggered_rules == 0);
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

void test_fault_name_surfaces() {
    assert(std::string(bividi::replay_fault_action_name(bividi::ReplayFaultAction::remove_camera)) == "remove_camera");
    assert(std::string(bividi::replay_fault_expected_disposition_name(
               bividi::ReplayFaultExpectedDisposition::reset_derived_pipeline)) == "reset_derived_pipeline");
}

}  // namespace

int main() {
    test_recipe_load_and_deterministic_actions();
    test_programmatic_validation_rejects_ambiguous_drop_position();
    test_json_rejects_unknown_action_fields();
    test_fault_name_surfaces();
    std::cout << "bividi replay fault recipe tests: PASS\n";
    return 0;
}
