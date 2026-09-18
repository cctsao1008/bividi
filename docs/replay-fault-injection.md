# Replay Fault Injection

Status: deterministic observation-stage and artifact/file-integrity fault recipes are implemented for Issue #59. Observation recipe v1 is frozen and remains readable; v2 adds device-clock and indexed-IMU fault coverage. Physical USB/recovery campaigns remain separate #35 evidence.

## Purpose

Bividi needs repeatable sensor-fault regression without adding test-only branches to the live DECXIN/Nori decoder. Fault injection is split by abstraction layer instead of pretending every failure is a valid normalized observation.

```text
recorded native session / MCAP
        │
        ├── artifact-integrity recipe
        │       ↓
        │   copied + corrupted artifact tree
        │       ↓
        │   importer / storage rejection path
        │
        └── ReplaySource
                ↓
        source-conformance-checked SensorObservation
                ↓
        InterceptedReplaySource
                ↓
        RecipeReplayInterceptor
                ↓
        mutated / duplicated / dropped observations
                ↓
        consumer regression assertions
```

Normal live capture and normal replay do not instantiate either fault layer.

## Observation-stage recipe versioning

Supported schema identifiers:

```text
bividi.replay_fault_recipe.v1
bividi.replay_fault_recipe.v2
```

V1 remains frozen so checked-in and external v1 recipes retain their original meaning. V2 is a strict superset of v1 and adds camera device-exposure mutation plus indexed IMU drop/duplicate/time mutation. A v1 document that names a v2-only action is rejected rather than interpreted under newer semantics.

New programmatic `ReplayFaultRecipe` values default to v2. Both versions require `seed`, unique rule IDs, zero-based `at_source_position`, exact action-specific fields, and explicit `expected_disposition`.

`at_source_position` refers to the original replay-source position, not the number of already-emitted observations. This remains stable when earlier rules duplicate or drop outputs.

`seed` is provenance. Current deterministic actions do not consume randomness. Exact 64-bit values may be encoded as decimal strings to avoid precision loss through intermediate JSON-number implementations.

### V1 actions

| Action | Parameters | Effect |
|---|---|---|
| `drop` | none | emit no observation for the source position |
| `duplicate` | `copies` | emit the current observation plus N additional copies |
| `sequence_delta` | `delta` | add signed delta to original sequence |
| `host_time_delta_ns` | `delta` | shift host-monotonic receive time |
| `remove_camera` | `stream_id` | remove the named camera observation |
| `drop_all_imu` | none | remove all IMU samples from the observation |
| `imu_sample_time_delta_us` | `delta` | shift every normalized device-domain IMU sample time |
| `set_stereo_synchronization` | `pair_id`, `state` | set pair status to `unknown`, `synchronized`, `unsynchronized`, or `degraded` |
| `set_continuity` | `state`, `epoch_delta` | set continuity state and apply signed epoch delta |

Rules at one source position execute in recipe order. `duplicate` duplicates the current value at that point, so later mutations at the same source position apply to every duplicate. `drop` must be the only rule at its source position.

### V2 additions

| Action | Parameters | Effect |
|---|---|---|
| `camera_exposure_time_delta_us` | `stream_id`, `delta` | shift only the selected camera's normalized exposure start/end device time |
| `drop_imu_sample` | `imu_index` | remove one IMU sample by zero-based vector index |
| `duplicate_imu_sample` | `imu_index`, `copies` | insert N exact copies immediately after one IMU sample |
| `imu_sample_time_delta_at_index_us` | `imu_index`, `delta` | shift only one normalized IMU sample time |

The camera and indexed-IMU time actions deliberately leave finite-width raw timestamp evidence unchanged. That is not a repair omission: it is the intended synthetic inconsistency, allowing a consumer/test to observe that normalized extended time no longer agrees with the preserved transport evidence.

V2 can therefore create representative device-time duplicate/backward/gap and stereo timing-mismatch cases without changing the raw bytes or pretending that the decoder itself produced repaired evidence.

Example:

```json
{
  "schema": "bividi.replay_fault_recipe.v2",
  "seed": 0,
  "rules": [
    {
      "id": "camera-b-device-time-backward",
      "at_source_position": 10,
      "action": "camera_exposure_time_delta_us",
      "stream_id": "camera_b",
      "delta": -500,
      "expected_disposition": "consumer_degraded"
    },
    {
      "id": "imu-duplicate-time",
      "at_source_position": 10,
      "action": "imu_sample_time_delta_at_index_us",
      "imu_index": 1,
      "delta": -1000,
      "expected_disposition": "consumer_reject"
    }
  ]
}
```

The engine checks signed-delta overflow/underflow and rejects actions whose required evidence/index is absent.

## 32-bit rollover fixtures

Rollover is tested separately from arbitrary fault mutation because a valid rollover contains two simultaneously true representations:

```text
raw 32-bit timestamp: wraps modulo 2^32
extended device time: remains monotonic
```

The native replay fixture includes camera exposure and IMU timestamps spanning the 32-bit microsecond boundary and asserts that `RawTimestampEvidence` preserves the wrapped value while `TimePoint` preserves the monotonic extended time. The test does not flatten those two domains into one number and does not treat a valid wrap as a discontinuity by itself.

## Artifact-integrity recipe

Artifact corruption is a separate pre-import layer because a truncated image, malformed CSV, bad manifest, or damaged MCAP is not a legitimate `SensorObservation`.

Schema identifier:

```text
bividi.replay_artifact_fault_recipe.v1
```

The tool copies a source directory before mutation and never modifies the source tree in place.

```bash
python tools/apply_replay_artifact_faults.py \
  --source path/to/source-session \
  --output path/to/mutated-session \
  --recipe examples/replay-faults/artifact-integrity-v1.json \
  --manifest path/to/application.json
```

The application manifest records canonical recipe SHA-256, source/output tree digests, seed, per-rule before/after file hashes and sizes, and whether the source tree remained unchanged after copying.

Artifact targets must be normalized relative paths inside the copied output root. Absolute paths, `.`/`..`, missing files, ambiguous text replacements, invalid offsets, and output overwrite are rejected.

### Artifact v1 actions

| Action | Parameters | Effect |
|---|---|---|
| `delete_file` | none | remove one existing file |
| `truncate_file` | `size_bytes` | retain exactly the first N bytes; extension is rejected |
| `xor_byte` | `offset`, `mask` | flip selected bits at one exact byte offset |
| `replace_text` | `old`, `new` | UTF-8 replacement only when old text occurs exactly once |
| `replace_bytes_hex` | `data_hex` | replace a file with exact bytes encoded as hexadecimal |

Artifact expected dispositions are `reject_artifact`, `decode_failure`, `schema_reject`, and `integrity_reject`. They are provenance, not instructions to repair input.

## Expected disposition is evidence, not repair policy

Observation-stage recipes use:

```text
observe_fault
explicit_gap
consumer_degraded
consumer_reject
new_continuity_epoch
reset_derived_pipeline
```

The interceptor records this contract but does not enforce or repair downstream behavior.

```text
fault recipe describes injected evidence
        !=
consumer policy deciding what to do with it
```

A VIO frontend may reset on a continuity discontinuity, while a recorder may preserve the same observation as degraded evidence. Those are different layer policies and must be tested separately.

Post-interceptor observations are not automatically passed back through the source conformance checker. Some tests deliberately create inconsistent evidence so the intended consumer can prove it rejects or degrades that input.

## Determinism and reset

`RecipeReplayInterceptor` exposes counters for source observations processed, observations emitted, and rules triggered. `InterceptedReplaySource::reset()` resets the source timeline, pending interceptor outputs, and recipe interceptor state.

Artifact recipes are deterministic by construction. If a rule fails, the partially copied/mutated output directory is removed rather than left as apparently usable evidence.

## CI coverage

Observation v1 coverage includes observation drop/duplicate, host timestamp shift, missing camera, stereo-unsynchronized state, all-IMU removal, whole-observation IMU time jump, sequence rollback, continuity epoch mutation, strict parsing, and deterministic reset.

Observation v2 coverage adds one-camera exposure-time shift with raw ES/EE preserved, indexed IMU time duplicate/backward construction with raw time preserved, one-sample duplication, and one-sample drop. It also verifies that v1 rejects v2-only actions and that invalid IMU indices fail explicitly.

The native replay integrity fixture includes a 32-bit timestamp rollover case in which camera/IMU raw microsecond timestamps wrap while extended device-domain timestamps remain monotonic.

The artifact layer verifies copy-on-write behavior, path containment, exact recipe hashing, source/output tree digests, delete/truncate/XOR/text/binary replacement, invalid-rule cleanup, native-session importer rejection paths, and MCAP integrity. A CRC-valid MCAP with a mutated camera payload is rejected by Bividi's payload SHA-256 binding; truncated MCAP must not return partial observations.

## Boundary to physical qualification

Synthetic replay still does not validate physical behavior:

```text
USB unplug/replug
hub reset
power interruption
vendor SDK reopen
real frame synchronization
real clock drift
real sensor/USB corruption
```

Those remain physical #35 qualification evidence. Synthetic device-time and artifact corruption prove software behavior against controlled evidence only; they do not prove that a physical transport will produce or recover from the same condition.

## Relationship to downstream depth/VIO

The fault layers make discontinuity policy testable before #9 depth and #46 VIO consume live hardware evidence. Derived pipelines should eventually prove they do not silently integrate across sequence rollback, device-time reversal, missing stereo input, IMU gaps/duplicates, or a declared new continuity epoch.

That downstream reset assertion must be attached to real #9/#46 consumer state once those consumers exist; the replay layer does not invent a fake VIO recovery policy merely to satisfy a test checkbox.

A replay fault test is reliability evidence for software behavior only; it is not a calibration or physical-accuracy result.
