#pragma once

#include "bividi/replay.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace bividi {

inline constexpr const char* kReplayFaultRecipeSchema = "bividi.replay_fault_recipe.v1";

enum class ReplayFaultAction {
    drop,
    duplicate,
    sequence_delta,
    host_time_delta_ns,
    remove_camera,
    drop_all_imu,
    imu_sample_time_delta_us,
    set_stereo_synchronization,
    set_continuity,
};

enum class ReplayFaultExpectedDisposition {
    observe_fault,
    explicit_gap,
    consumer_degraded,
    consumer_reject,
    new_continuity_epoch,
    reset_derived_pipeline,
};

struct ReplayFaultRule {
    std::string id;
    std::size_t at_source_position = 0;
    ReplayFaultAction action = ReplayFaultAction::drop;
    ReplayFaultExpectedDisposition expected = ReplayFaultExpectedDisposition::observe_fault;

    // Action-specific fields. The JSON loader rejects fields that are not
    // meaningful for the selected action instead of silently ignoring them.
    std::uint32_t copies = 0;          // duplicate: additional copies
    std::int64_t delta = 0;            // sequence/time/epoch delta
    std::string stream_id;             // remove_camera
    std::string pair_id;               // set_stereo_synchronization
    SynchronizationState synchronization = SynchronizationState::unknown;
    ContinuityState continuity = ContinuityState::continuous;
};

struct ReplayFaultRecipe {
    std::string schema = kReplayFaultRecipeSchema;
    std::uint64_t seed = 0;
    std::vector<ReplayFaultRule> rules;
};

struct ReplayFaultStats {
    std::size_t source_observations = 0;
    std::size_t emitted_observations = 0;
    std::size_t triggered_rules = 0;
};

// Strict JSON loader. The recipe is intentionally deterministic in v1; seed is
// required provenance for future seeded stochastic actions but v1 has no random
// action semantics.
[[nodiscard]] ReplayFaultRecipe load_replay_fault_recipe(const std::filesystem::path& path);

// Programmatic validation is also exposed so tests/tools may construct recipes
// without JSON while keeping exactly the same contract.
void validate_replay_fault_recipe(const ReplayFaultRecipe& recipe);

class RecipeReplayInterceptor final : public ReplayObservationInterceptor {
public:
    explicit RecipeReplayInterceptor(ReplayFaultRecipe recipe);

    void reset() override;
    void transform(
        std::size_t source_position,
        SensorObservation observation,
        std::vector<SensorObservation>& output) override;

    [[nodiscard]] const ReplayFaultRecipe& recipe() const noexcept;
    [[nodiscard]] const ReplayFaultStats& stats() const noexcept;

private:
    ReplayFaultRecipe recipe_;
    ReplayFaultStats stats_{};
};

[[nodiscard]] std::shared_ptr<RecipeReplayInterceptor> make_replay_fault_interceptor(
    const std::filesystem::path& recipe_path);

[[nodiscard]] const char* replay_fault_action_name(ReplayFaultAction action) noexcept;
[[nodiscard]] const char* replay_fault_expected_disposition_name(
    ReplayFaultExpectedDisposition disposition) noexcept;

}  // namespace bividi
