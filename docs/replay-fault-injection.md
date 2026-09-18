# Replay Fault Injection v1

Status: deterministic observation-stage fault recipes implemented for Issue #59. Artifact/file-integrity corruption and physical USB/recovery campaigns remain separate follow-up layers.

## Purpose

Bividi needs repeatable sensor-fault regression without adding test-only branches to the live DECXIN/Nori decoder. Fault injection therefore operates on the normalized `SensorObservation` replay stream through the explicit `ReplayObservationInterceptor` seam.

```text
recorded native session
        ↓
ReplaySource
        ↓
source-conformance-checked SensorObservation
        ↓
InterceptedReplaySource
        ↓
RecipeReplayInterceptor
        ↓
mutated / duplicated / dropped observation stream
        ↓
consumer regression assertions
```

Normal replay does not instantiate this interceptor and is unchanged.

## Recipe schema

Schema identifier:

```text
bividi.replay_fault_recipe.v1
```

Example:

```json
{
  "schema": "bividi.replay_fault_recipe.v1",
  "seed": 0,
  "rules": [
    {
      "id": "camera-b-missing",
      "at_source_position": 50,
      "action": "remove_camera",
      "stream_id": "camera_b",
      "expected_disposition": "consumer_degraded"
    }
  ]
}
```

`at_source_position` refers to the zero-based original replay-source position, not the number of already-emitted observations. This remains stable when earlier rules duplicate or drop outputs.

`id` values must be unique. Unknown recipe fields and action-specific fields are rejected instead of ignored.

`seed` is mandatory provenance. V1 actions are deterministic and do not consume randomness; the seed is reserved so future stochastic actions can be introduced without changing the top-level provenance model.

For exact 64-bit values the JSON loader accepts decimal strings as well as ordinary JSON integers. This avoids accidental precision loss through intermediate JSON/number implementations.

## V1 actions

| Action | Parameters | Effect |
|---|---|---|
| `drop` | none | emit no observation for the source position |
| `duplicate` | `copies` | emit the current observation plus N additional copies |
| `sequence_delta` | `delta` | add signed delta to original sequence |
| `host_time_delta_ns` | `delta` | add signed delta to host-monotonic nanosecond timestamp |
| `remove_camera` | `stream_id` | remove the named camera observation |
| `drop_all_imu` | none | remove all IMU samples from the observation |
| `imu_sample_time_delta_us` | `delta` | shift normalized device-domain IMU sample times; raw finite-width evidence is left unchanged |
| `set_stereo_synchronization` | `pair_id`, `state` | set pair status to `unknown`, `synchronized`, `unsynchronized`, or `degraded` |
| `set_continuity` | `state`, `epoch_delta` | set continuity state and apply signed epoch delta |

Rules for one source position execute in recipe order. `duplicate` duplicates the current value at that point, so later mutations at the same source position apply to every duplicate. `drop` must be the only rule at its source position to avoid an ambiguous dead rule sequence.

The engine checks signed-delta overflow/underflow and rejects actions whose required evidence is absent. For example, `host_time_delta_ns` requires an explicit host-monotonic nanosecond timestamp and `imu_sample_time_delta_us` requires at least one device-domain microsecond IMU sample.

## Expected disposition is evidence, not repair policy

Every rule declares `expected_disposition`:

```text
observe_fault
explicit_gap
consumer_degraded
consumer_reject
new_continuity_epoch
reset_derived_pipeline
```

The interceptor records this contract in the recipe but does **not** enforce or repair the downstream response. This separation is intentional:

```text
fault recipe describes injected evidence
        !=
consumer policy deciding what to do with it
```

A VIO frontend may reset on a continuity discontinuity, while a recorder may preserve the same observation as degraded evidence. Those are different layer policies and must be tested separately.

Post-interceptor observations are not automatically passed back through the source conformance checker. Some tests deliberately create inconsistent evidence so the intended consumer can prove it rejects or degrades that input.

## Determinism and reset

`RecipeReplayInterceptor` exposes counters for:

- source observations processed;
- observations emitted;
- recipe rules triggered.

`InterceptedReplaySource::reset()` resets the underlying source timeline, pending interceptor outputs, and recipe interceptor state. Re-running the same deterministic v1 recipe against the same recording therefore produces the same output sequence.

## Current CI coverage

The compact native fixture verifies:

```text
position 0: duplicate + host timestamp shift
position 1: remove camera B + mark stereo unsynchronized
position 2: IMU timestamp jump + sequence rollback + new continuity epoch
position 3: drop observation
position 4: drop all IMU
```

It also verifies strict recipe parsing, duplicate-rule-ID/drop-position validation, 64-bit seed parsing, action/disposition naming, counters, and deterministic reset.

## What this slice does not cover

Observation-stage recipes cannot faithfully model every corruption class. File/container integrity faults belong below the normalized observation boundary, for example:

```text
truncated PNG
corrupt CSV
manifest/hash mismatch
unsupported MCAP schema
missing MCAP camera payload
```

Those should be exercised against the native-session and MCAP importers themselves, not faked as valid `SensorObservation` objects.

Likewise, synthetic replay does not validate physical behavior:

```text
USB unplug/replug
hub reset
power interruption
vendor SDK reopen
real frame synchronization
real clock drift
real sensor/USB corruption
```

Those remain physical #35 qualification evidence.

## Relationship to downstream depth/VIO

The immediate value of this layer is to make discontinuity policy testable before #9 depth and #46 VIO consume live hardware evidence. Derived pipelines should be able to prove they do not silently integrate across sequence rollback, timestamp reversal, missing stereo input, IMU gaps, or a declared new continuity epoch.

A replay fault test is reliability evidence for software behavior only; it is not a calibration or physical-accuracy result.
