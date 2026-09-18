#include "bividi/replay_faults.hpp"

#include <opencv2/core.hpp>

#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace bividi {
namespace {

using KeySet = std::set<std::string>;

std::string read_required_string(const cv::FileNode& node, const char* key, const std::string& context) {
    const auto child = node[key];
    if (child.empty() || !child.isString()) {
        throw std::runtime_error(context + "." + key + " must be a string");
    }
    std::string value;
    child >> value;
    if (value.empty()) {
        throw std::runtime_error(context + "." + key + " must not be empty");
    }
    return value;
}

std::uint64_t parse_u64_text(const std::string& text, const std::string& context) {
    try {
        std::size_t used = 0;
        const auto value = std::stoull(text, &used, 10);
        if (used != text.size()) throw std::invalid_argument("trailing");
        return value;
    } catch (const std::exception&) {
        throw std::runtime_error(context + " must be an unsigned integer");
    }
}

std::int64_t parse_i64_text(const std::string& text, const std::string& context) {
    try {
        std::size_t used = 0;
        const auto value = std::stoll(text, &used, 10);
        if (used != text.size()) throw std::invalid_argument("trailing");
        return value;
    } catch (const std::exception&) {
        throw std::runtime_error(context + " must be a signed integer");
    }
}

std::uint64_t read_u64(const cv::FileNode& node, const char* key, const std::string& context) {
    const auto child = node[key];
    if (child.empty()) {
        throw std::runtime_error(context + "." + key + " is required");
    }
    if (child.isInt()) {
        const int value = static_cast<int>(child);
        if (value < 0) throw std::runtime_error(context + "." + key + " must be >= 0");
        return static_cast<std::uint64_t>(value);
    }
    if (child.isString()) {
        std::string text;
        child >> text;
        return parse_u64_text(text, context + "." + key);
    }
    throw std::runtime_error(context + "." + key + " must be an integer or decimal string");
}

std::size_t read_index(const cv::FileNode& node, const char* key, const std::string& context) {
    const auto value = read_u64(node, key, context);
    if (value > std::numeric_limits<std::size_t>::max()) {
        throw std::runtime_error(context + "." + key + " exceeds size_t");
    }
    return static_cast<std::size_t>(value);
}

std::int64_t read_i64(const cv::FileNode& node, const char* key, const std::string& context) {
    const auto child = node[key];
    if (child.empty()) {
        throw std::runtime_error(context + "." + key + " is required");
    }
    if (child.isInt()) {
        return static_cast<std::int64_t>(static_cast<int>(child));
    }
    if (child.isString()) {
        std::string text;
        child >> text;
        return parse_i64_text(text, context + "." + key);
    }
    throw std::runtime_error(context + "." + key + " must be an integer or decimal string");
}

void require_keys(const cv::FileNode& node, const KeySet& allowed, const std::string& context) {
    if (!node.isMap()) throw std::runtime_error(context + " must be an object");
    for (const auto& key : node.keys()) {
        if (allowed.count(key) == 0) {
            throw std::runtime_error(context + " has unsupported field: " + key);
        }
    }
}

bool supported_schema(const std::string& schema) noexcept {
    return schema == kReplayFaultRecipeSchemaV1 || schema == kReplayFaultRecipeSchemaV2;
}

bool requires_v2(ReplayFaultAction action) noexcept {
    switch (action) {
        case ReplayFaultAction::camera_exposure_time_delta_us:
        case ReplayFaultAction::drop_imu_sample:
        case ReplayFaultAction::duplicate_imu_sample:
        case ReplayFaultAction::imu_sample_time_delta_at_index_us:
            return true;
        default:
            return false;
    }
}

ReplayFaultAction parse_action(const std::string& value, const std::string& context) {
    if (value == "drop") return ReplayFaultAction::drop;
    if (value == "duplicate") return ReplayFaultAction::duplicate;
    if (value == "sequence_delta") return ReplayFaultAction::sequence_delta;
    if (value == "host_time_delta_ns") return ReplayFaultAction::host_time_delta_ns;
    if (value == "remove_camera") return ReplayFaultAction::remove_camera;
    if (value == "drop_all_imu") return ReplayFaultAction::drop_all_imu;
    if (value == "imu_sample_time_delta_us") return ReplayFaultAction::imu_sample_time_delta_us;
    if (value == "set_stereo_synchronization") return ReplayFaultAction::set_stereo_synchronization;
    if (value == "set_continuity") return ReplayFaultAction::set_continuity;
    if (value == "camera_exposure_time_delta_us") return ReplayFaultAction::camera_exposure_time_delta_us;
    if (value == "drop_imu_sample") return ReplayFaultAction::drop_imu_sample;
    if (value == "duplicate_imu_sample") return ReplayFaultAction::duplicate_imu_sample;
    if (value == "imu_sample_time_delta_at_index_us") return ReplayFaultAction::imu_sample_time_delta_at_index_us;
    throw std::runtime_error(context + " unsupported action: " + value);
}

ReplayFaultExpectedDisposition parse_expected(const std::string& value, const std::string& context) {
    if (value == "observe_fault") return ReplayFaultExpectedDisposition::observe_fault;
    if (value == "explicit_gap") return ReplayFaultExpectedDisposition::explicit_gap;
    if (value == "consumer_degraded") return ReplayFaultExpectedDisposition::consumer_degraded;
    if (value == "consumer_reject") return ReplayFaultExpectedDisposition::consumer_reject;
    if (value == "new_continuity_epoch") return ReplayFaultExpectedDisposition::new_continuity_epoch;
    if (value == "reset_derived_pipeline") return ReplayFaultExpectedDisposition::reset_derived_pipeline;
    throw std::runtime_error(context + " unsupported expected_disposition: " + value);
}

SynchronizationState parse_synchronization(const std::string& value, const std::string& context) {
    if (value == "unknown") return SynchronizationState::unknown;
    if (value == "synchronized") return SynchronizationState::synchronized;
    if (value == "unsynchronized") return SynchronizationState::unsynchronized;
    if (value == "degraded") return SynchronizationState::degraded;
    throw std::runtime_error(context + " unsupported synchronization state: " + value);
}

ContinuityState parse_continuity(const std::string& value, const std::string& context) {
    if (value == "continuous") return ContinuityState::continuous;
    if (value == "discontinuity") return ContinuityState::discontinuity;
    if (value == "reinitialized") return ContinuityState::reinitialized;
    throw std::runtime_error(context + " unsupported continuity state: " + value);
}

std::uint64_t apply_delta(std::uint64_t value, std::int64_t delta, const std::string& context) {
    if (delta >= 0) {
        const auto amount = static_cast<std::uint64_t>(delta);
        if (amount > std::numeric_limits<std::uint64_t>::max() - value) {
            throw std::runtime_error(context + " positive delta overflows uint64");
        }
        return value + amount;
    }

    // Avoid negating INT64_MIN.
    const auto amount = static_cast<std::uint64_t>(-(delta + 1)) + 1;
    if (amount > value) {
        throw std::runtime_error(context + " negative delta underflows uint64");
    }
    return value - amount;
}

void validate_rule(const ReplayFaultRule& rule) {
    if (rule.id.empty()) throw std::invalid_argument("fault rule id must not be empty");
    switch (rule.action) {
        case ReplayFaultAction::drop:
        case ReplayFaultAction::drop_all_imu:
        case ReplayFaultAction::drop_imu_sample:
            break;

        case ReplayFaultAction::duplicate:
        case ReplayFaultAction::duplicate_imu_sample:
            if (rule.copies == 0) throw std::invalid_argument("duplicate rule copies must be >= 1");
            break;

        case ReplayFaultAction::sequence_delta:
        case ReplayFaultAction::host_time_delta_ns:
        case ReplayFaultAction::imu_sample_time_delta_us:
        case ReplayFaultAction::imu_sample_time_delta_at_index_us:
            if (rule.delta == 0) throw std::invalid_argument("delta fault rule must use non-zero delta");
            break;

        case ReplayFaultAction::remove_camera:
            if (rule.stream_id.empty()) throw std::invalid_argument("remove_camera rule requires stream_id");
            break;

        case ReplayFaultAction::camera_exposure_time_delta_us:
            if (rule.stream_id.empty()) {
                throw std::invalid_argument("camera_exposure_time_delta_us rule requires stream_id");
            }
            if (rule.delta == 0) {
                throw std::invalid_argument("camera_exposure_time_delta_us rule requires non-zero delta");
            }
            break;

        case ReplayFaultAction::set_stereo_synchronization:
            if (rule.pair_id.empty()) {
                throw std::invalid_argument("set_stereo_synchronization rule requires pair_id");
            }
            break;

        case ReplayFaultAction::set_continuity:
            break;
    }
}

ImuObservation& indexed_imu(
    SensorObservation& observation,
    const ReplayFaultRule& rule,
    const std::string& context) {
    if (rule.imu_index >= observation.imu.size()) {
        throw std::runtime_error(
            context + " imu_index " + std::to_string(rule.imu_index) +
            " is outside observation IMU sample count " + std::to_string(observation.imu.size()));
    }
    return observation.imu[rule.imu_index];
}

void apply_rule(const ReplayFaultRule& rule, SensorObservation& observation) {
    switch (rule.action) {
        case ReplayFaultAction::drop:
        case ReplayFaultAction::duplicate:
            return;  // observation-cardinality actions are handled by the caller.

        case ReplayFaultAction::sequence_delta:
            if (!observation.sequence_present) {
                throw std::runtime_error("fault rule " + rule.id + " requires sequence_present=true");
            }
            observation.sequence = apply_delta(observation.sequence, rule.delta, "fault rule " + rule.id + " sequence");
            return;

        case ReplayFaultAction::host_time_delta_ns:
            if (!observation.timing.host_receive.present ||
                observation.timing.host_receive.domain != ClockDomain::host_monotonic ||
                observation.timing.host_receive.unit != TimeUnit::nanoseconds) {
                throw std::runtime_error("fault rule " + rule.id + " requires host_receive nanoseconds");
            }
            observation.timing.host_receive.ticks = apply_delta(
                observation.timing.host_receive.ticks,
                rule.delta,
                "fault rule " + rule.id + " host_receive");
            return;

        case ReplayFaultAction::remove_camera: {
            const auto before = observation.cameras.size();
            observation.cameras.erase(
                std::remove_if(
                    observation.cameras.begin(),
                    observation.cameras.end(),
                    [&](const CameraObservation& camera) { return camera.stream_id == rule.stream_id; }),
                observation.cameras.end());
            if (observation.cameras.size() == before) {
                throw std::runtime_error(
                    "fault rule " + rule.id + " camera stream not present: " + rule.stream_id);
            }
            return;
        }

        case ReplayFaultAction::drop_all_imu:
            if (observation.imu.empty()) {
                throw std::runtime_error("fault rule " + rule.id + " requires at least one IMU sample");
            }
            observation.imu.clear();
            return;

        case ReplayFaultAction::imu_sample_time_delta_us:
            if (observation.imu.empty()) {
                throw std::runtime_error("fault rule " + rule.id + " requires at least one IMU sample");
            }
            for (auto& sample : observation.imu) {
                if (!sample.sample_time.present || sample.sample_time.domain != ClockDomain::device ||
                    sample.sample_time.unit != TimeUnit::microseconds) {
                    throw std::runtime_error(
                        "fault rule " + rule.id + " requires device-domain IMU microsecond sample_time");
                }
                sample.sample_time.ticks = apply_delta(
                    sample.sample_time.ticks,
                    rule.delta,
                    "fault rule " + rule.id + " imu sample_time");
            }
            return;

        case ReplayFaultAction::set_stereo_synchronization: {
            const auto it = std::find_if(
                observation.stereo_pairs.begin(),
                observation.stereo_pairs.end(),
                [&](const StereoPairStatus& pair) { return pair.pair_id == rule.pair_id; });
            if (it == observation.stereo_pairs.end()) {
                throw std::runtime_error(
                    "fault rule " + rule.id + " stereo pair not present: " + rule.pair_id);
            }
            it->synchronization = rule.synchronization;
            return;
        }

        case ReplayFaultAction::set_continuity:
            observation.continuity = rule.continuity;
            observation.continuity_epoch = apply_delta(
                observation.continuity_epoch,
                rule.delta,
                "fault rule " + rule.id + " continuity_epoch");
            return;

        case ReplayFaultAction::camera_exposure_time_delta_us: {
            const auto it = std::find_if(
                observation.cameras.begin(),
                observation.cameras.end(),
                [&](const CameraObservation& camera) { return camera.stream_id == rule.stream_id; });
            if (it == observation.cameras.end()) {
                throw std::runtime_error(
                    "fault rule " + rule.id + " camera stream not present: " + rule.stream_id);
            }
            auto& exposure = it->exposure;
            if (!exposure.complete() ||
                exposure.start.domain != ClockDomain::device || exposure.end.domain != ClockDomain::device ||
                exposure.start.unit != TimeUnit::microseconds || exposure.end.unit != TimeUnit::microseconds) {
                throw std::runtime_error(
                    "fault rule " + rule.id + " requires complete device-domain microsecond camera exposure timing");
            }
            exposure.start.ticks = apply_delta(
                exposure.start.ticks, rule.delta, "fault rule " + rule.id + " exposure start");
            exposure.end.ticks = apply_delta(
                exposure.end.ticks, rule.delta, "fault rule " + rule.id + " exposure end");
            // Finite-width raw ES/EE evidence is deliberately preserved so the
            // synthetic normalized-device-time inconsistency remains visible.
            return;
        }

        case ReplayFaultAction::drop_imu_sample: {
            (void)indexed_imu(observation, rule, "fault rule " + rule.id);
            observation.imu.erase(observation.imu.begin() + static_cast<std::ptrdiff_t>(rule.imu_index));
            return;
        }

        case ReplayFaultAction::duplicate_imu_sample: {
            const auto sample = indexed_imu(observation, rule, "fault rule " + rule.id);
            const auto insertion = observation.imu.begin() + static_cast<std::ptrdiff_t>(rule.imu_index + 1);
            observation.imu.insert(insertion, rule.copies, sample);
            return;
        }

        case ReplayFaultAction::imu_sample_time_delta_at_index_us: {
            auto& sample = indexed_imu(observation, rule, "fault rule " + rule.id);
            if (!sample.sample_time.present || sample.sample_time.domain != ClockDomain::device ||
                sample.sample_time.unit != TimeUnit::microseconds) {
                throw std::runtime_error(
                    "fault rule " + rule.id + " requires device-domain IMU microsecond sample_time");
            }
            sample.sample_time.ticks = apply_delta(
                sample.sample_time.ticks,
                rule.delta,
                "fault rule " + rule.id + " indexed imu sample_time");
            // Raw finite-width timestamp evidence is deliberately unchanged.
            return;
        }
    }
}

ReplayFaultRule parse_rule(
    const cv::FileNode& node,
    std::size_t index,
    const std::string& recipe_schema) {
    const std::string context = "rules[" + std::to_string(index) + "]";
    const auto id = read_required_string(node, "id", context);
    const auto action_text = read_required_string(node, "action", context);
    const auto expected_text = read_required_string(node, "expected_disposition", context);

    ReplayFaultRule rule{};
    rule.id = id;
    rule.at_source_position = read_index(node, "at_source_position", context);
    rule.action = parse_action(action_text, context);
    rule.expected = parse_expected(expected_text, context);

    if (recipe_schema == kReplayFaultRecipeSchemaV1 && requires_v2(rule.action)) {
        throw std::runtime_error(
            context + " action " + action_text + " requires schema " + kReplayFaultRecipeSchemaV2);
    }

    KeySet allowed{"id", "at_source_position", "action", "expected_disposition"};
    switch (rule.action) {
        case ReplayFaultAction::drop:
        case ReplayFaultAction::drop_all_imu:
            break;

        case ReplayFaultAction::duplicate: {
            allowed.insert("copies");
            const auto copies = read_u64(node, "copies", context);
            if (copies == 0 || copies > std::numeric_limits<std::uint32_t>::max()) {
                throw std::runtime_error(context + ".copies must be in [1, uint32_max]");
            }
            rule.copies = static_cast<std::uint32_t>(copies);
            break;
        }

        case ReplayFaultAction::sequence_delta:
        case ReplayFaultAction::host_time_delta_ns:
        case ReplayFaultAction::imu_sample_time_delta_us:
            allowed.insert("delta");
            rule.delta = read_i64(node, "delta", context);
            break;

        case ReplayFaultAction::remove_camera:
            allowed.insert("stream_id");
            rule.stream_id = read_required_string(node, "stream_id", context);
            break;

        case ReplayFaultAction::set_stereo_synchronization:
            allowed.insert("pair_id");
            allowed.insert("state");
            rule.pair_id = read_required_string(node, "pair_id", context);
            rule.synchronization = parse_synchronization(
                read_required_string(node, "state", context), context + ".state");
            break;

        case ReplayFaultAction::set_continuity:
            allowed.insert("state");
            allowed.insert("epoch_delta");
            rule.continuity = parse_continuity(
                read_required_string(node, "state", context), context + ".state");
            rule.delta = read_i64(node, "epoch_delta", context);
            break;

        case ReplayFaultAction::camera_exposure_time_delta_us:
            allowed.insert("stream_id");
            allowed.insert("delta");
            rule.stream_id = read_required_string(node, "stream_id", context);
            rule.delta = read_i64(node, "delta", context);
            break;

        case ReplayFaultAction::drop_imu_sample:
            allowed.insert("imu_index");
            rule.imu_index = read_index(node, "imu_index", context);
            break;

        case ReplayFaultAction::duplicate_imu_sample: {
            allowed.insert("imu_index");
            allowed.insert("copies");
            rule.imu_index = read_index(node, "imu_index", context);
            const auto copies = read_u64(node, "copies", context);
            if (copies == 0 || copies > std::numeric_limits<std::uint32_t>::max()) {
                throw std::runtime_error(context + ".copies must be in [1, uint32_max]");
            }
            rule.copies = static_cast<std::uint32_t>(copies);
            break;
        }

        case ReplayFaultAction::imu_sample_time_delta_at_index_us:
            allowed.insert("imu_index");
            allowed.insert("delta");
            rule.imu_index = read_index(node, "imu_index", context);
            rule.delta = read_i64(node, "delta", context);
            break;
    }

    require_keys(node, allowed, context);
    validate_rule(rule);
    return rule;
}

}  // namespace

ReplayFaultRecipe load_replay_fault_recipe(const std::filesystem::path& path) {
    cv::FileStorage file(path.string(), cv::FileStorage::READ | cv::FileStorage::FORMAT_JSON);
    if (!file.isOpened()) {
        throw std::runtime_error("cannot open replay fault recipe: " + path.string());
    }

    const auto root = file.root();
    require_keys(root, {"schema", "seed", "rules"}, "recipe");

    ReplayFaultRecipe recipe{};
    recipe.schema = read_required_string(root, "schema", "recipe");
    if (!supported_schema(recipe.schema)) {
        throw std::runtime_error("unsupported replay fault recipe schema: " + recipe.schema);
    }
    recipe.seed = read_u64(root, "seed", "recipe");

    const auto rules = root["rules"];
    if (rules.empty() || !rules.isSeq()) {
        throw std::runtime_error("recipe.rules must be a non-empty array");
    }
    std::size_t index = 0;
    for (auto it = rules.begin(); it != rules.end(); ++it, ++index) {
        recipe.rules.push_back(parse_rule(*it, index, recipe.schema));
    }

    validate_replay_fault_recipe(recipe);
    return recipe;
}

void validate_replay_fault_recipe(const ReplayFaultRecipe& recipe) {
    if (!supported_schema(recipe.schema)) {
        throw std::invalid_argument("unsupported replay fault recipe schema: " + recipe.schema);
    }
    if (recipe.rules.empty()) {
        throw std::invalid_argument("replay fault recipe requires at least one rule");
    }

    std::set<std::string> ids;
    std::set<std::size_t> drop_positions;
    std::set<std::size_t> non_drop_positions;
    for (const auto& rule : recipe.rules) {
        validate_rule(rule);
        if (recipe.schema == kReplayFaultRecipeSchemaV1 && requires_v2(rule.action)) {
            throw std::invalid_argument(
                "replay fault action " + std::string(replay_fault_action_name(rule.action)) +
                " requires schema " + kReplayFaultRecipeSchemaV2);
        }
        if (!ids.insert(rule.id).second) {
            throw std::invalid_argument("duplicate replay fault rule id: " + rule.id);
        }
        if (rule.action == ReplayFaultAction::drop) {
            drop_positions.insert(rule.at_source_position);
        } else {
            non_drop_positions.insert(rule.at_source_position);
        }
    }
    for (const auto position : drop_positions) {
        if (non_drop_positions.count(position) != 0) {
            throw std::invalid_argument(
                "drop must be the only rule at source position " + std::to_string(position));
        }
    }
}

RecipeReplayInterceptor::RecipeReplayInterceptor(ReplayFaultRecipe recipe)
    : recipe_(std::move(recipe)) {
    validate_replay_fault_recipe(recipe_);
}

void RecipeReplayInterceptor::reset() {
    stats_ = {};
}

void RecipeReplayInterceptor::transform(
    std::size_t source_position,
    SensorObservation observation,
    std::vector<SensorObservation>& output) {
    ++stats_.source_observations;

    std::vector<SensorObservation> current;
    current.push_back(std::move(observation));

    for (const auto& rule : recipe_.rules) {
        if (rule.at_source_position != source_position) continue;
        ++stats_.triggered_rules;

        if (rule.action == ReplayFaultAction::drop) {
            current.clear();
            continue;
        }

        if (rule.action == ReplayFaultAction::duplicate) {
            const auto original_count = current.size();
            std::vector<SensorObservation> expanded;
            expanded.reserve(original_count * (static_cast<std::size_t>(rule.copies) + 1));
            for (const auto& item : current) {
                expanded.push_back(item);
                for (std::uint32_t copy = 0; copy < rule.copies; ++copy) {
                    expanded.push_back(item);
                }
            }
            current = std::move(expanded);
            continue;
        }

        for (auto& item : current) {
            apply_rule(rule, item);
        }
    }

    stats_.emitted_observations += current.size();
    for (auto& item : current) output.push_back(std::move(item));
}

const ReplayFaultRecipe& RecipeReplayInterceptor::recipe() const noexcept {
    return recipe_;
}

const ReplayFaultStats& RecipeReplayInterceptor::stats() const noexcept {
    return stats_;
}

std::shared_ptr<RecipeReplayInterceptor> make_replay_fault_interceptor(
    const std::filesystem::path& recipe_path) {
    return std::make_shared<RecipeReplayInterceptor>(load_replay_fault_recipe(recipe_path));
}

const char* replay_fault_action_name(ReplayFaultAction action) noexcept {
    switch (action) {
        case ReplayFaultAction::drop: return "drop";
        case ReplayFaultAction::duplicate: return "duplicate";
        case ReplayFaultAction::sequence_delta: return "sequence_delta";
        case ReplayFaultAction::host_time_delta_ns: return "host_time_delta_ns";
        case ReplayFaultAction::remove_camera: return "remove_camera";
        case ReplayFaultAction::drop_all_imu: return "drop_all_imu";
        case ReplayFaultAction::imu_sample_time_delta_us: return "imu_sample_time_delta_us";
        case ReplayFaultAction::set_stereo_synchronization: return "set_stereo_synchronization";
        case ReplayFaultAction::set_continuity: return "set_continuity";
        case ReplayFaultAction::camera_exposure_time_delta_us: return "camera_exposure_time_delta_us";
        case ReplayFaultAction::drop_imu_sample: return "drop_imu_sample";
        case ReplayFaultAction::duplicate_imu_sample: return "duplicate_imu_sample";
        case ReplayFaultAction::imu_sample_time_delta_at_index_us: return "imu_sample_time_delta_at_index_us";
    }
    return "unknown";
}

const char* replay_fault_expected_disposition_name(
    ReplayFaultExpectedDisposition disposition) noexcept {
    switch (disposition) {
        case ReplayFaultExpectedDisposition::observe_fault: return "observe_fault";
        case ReplayFaultExpectedDisposition::explicit_gap: return "explicit_gap";
        case ReplayFaultExpectedDisposition::consumer_degraded: return "consumer_degraded";
        case ReplayFaultExpectedDisposition::consumer_reject: return "consumer_reject";
        case ReplayFaultExpectedDisposition::new_continuity_epoch: return "new_continuity_epoch";
        case ReplayFaultExpectedDisposition::reset_derived_pipeline: return "reset_derived_pipeline";
    }
    return "unknown";
}

}  // namespace bividi
