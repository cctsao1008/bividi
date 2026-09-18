# Replay Fault Injection v1

Status: deterministic observation-stage and artifact/file-integrity fault recipes are implemented for Issue #59. Physical USB/recovery campaigns remain separate #35 evidence.

## Purpose

Bividi needs repeatable sensor-fault regression without adding test-only branches to the live DECXIN/Nori decoder. Fault injection is therefore split by abstraction layer instead of pretending every failure is a valid normalized observation.

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

## Observation-stage recipe

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

`id` values must be unique. Unknown recipe fields and action-specific fields are rejected instead of ignored. `seed` is mandatory provenance. V1 actions are deterministic and do not consume randomness; the seed is reserved so future stochastic actions can be introduced without changing the top-level provenance model. Exact 64-bit values may be decimal strings to avoid accidental precision loss in intermediate JSON implementations.

### Observation-stage v1 actions

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

## Artifact-integrity recipe

Artifact corruption is intentionally a separate pre-import layer because a truncated image, malformed CSV, bad manifest, or damaged MCAP is not a legitimate `SensorObservation`.

Schema identifier:

```text
bividi.replay_artifact_fault_recipe.v1
```

The tool copies a source directory before mutation. It never modifies the source tree in place.

```bash
python tools/apply_replay_artifact_faults.py \
  --source path/to/source-session \
  --output path/to/mutated-session \
  --recipe examples/replay-faults/artifact-integrity-v1.json \
  --manifest path/to/application.json
```

The application manifest records the canonical recipe SHA-256, source/output tree digests, seed, per-rule before/after file hashes and sizes, and whether the source tree remained unchanged after copying.

Artifact targets must be normalized relative paths inside the copied output root. Absolute paths, `.`/`..`, missing files, ambiguous text replacements, invalid offsets, and output overwrite are rejected.

### Artifact v1 actions

| Action | Parameters | Effect |
|---|---|---|
| `delete_file` | none | remove one existing file |
| `truncate_file` | `size_bytes` | retain exactly the first N bytes; extension beyond current size is rejected |
| `xor_byte` | `offset`, `mask` | flip selected bits at one exact byte offset |
| `replace_text` | `old`, `new` | UTF-8 replacement only when the old text occurs exactly once |
| `replace_bytes_hex` | `data_hex` | replace a file with exact bytes encoded as hexadecimal |

`replace_bytes_hex` exists so compact image/container fixtures can be made deterministically without introducing an image-processing dependency into the mutator itself.

Artifact `expected_disposition` values describe the layer expected to reject the artifact:

```text
reject_artifact
decode_failure
schema_reject
integrity_reject
```

They are provenance, not an instruction to repair the input.

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

The interceptor records this contract in the recipe but does **not** enforce or repair downstream behavior.

```text
fault recipe describes injected evidence
        !=
consumer policy deciding what to do with it
```

A VIO frontend may reset on a continuity discontinuity, while a recorder may preserve the same observation as degraded evidence. Those are different layer policies and must be tested separately.

Post-interceptor observations are not automatically passed back through the source conformance checker. Some tests deliberately create inconsistent evidence so the intended consumer can prove it rejects or degrades that input.

## Determinism and reset

`RecipeReplayInterceptor` exposes counters for source observations processed, observations emitted, and rules triggered. `InterceptedReplaySource::reset()` resets the source timeline, pending interceptor outputs, and recipe interceptor state. Re-running the same deterministic v1 recipe against the same recording therefore produces the same output stream.

Artifact recipes are deterministic by construction: the same source tree plus canonical recipe yields the same output bytes and application manifest hashes. If a rule fails, the partially copied/mutated output directory is removed rather than left as apparently usable evidence.

## CI coverage

The observation-stage native fixture verifies:

```text
position 0: duplicate + host timestamp shift
position 1: remove camera B + mark stereo unsynchronized
position 2: IMU timestamp jump + sequence rollback + new continuity epoch
position 3: drop observation
position 4: drop all IMU
```

It also verifies strict recipe parsing, duplicate-rule-ID/drop-position validation, 64-bit seed parsing, action/disposition naming, counters, and deterministic reset.

The artifact layer verifies copy-on-write behavior, strict path containment, exact recipe hashing, source/output tree digests, delete/truncate/XOR/text/binary replacement, invalid-rule cleanup, and a concrete MCAP integrity path. MCAP tests rewrite one camera payload into a new CRC-valid container while leaving the Bividi envelope hash unchanged; `read_observations()` must reject the payload SHA-256 mismatch. A truncated MCAP must not return partial observations.

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

Those remain physical #35 qualification evidence. Artifact corruption proves importer/storage behavior against deterministic bad bytes; it does not prove that a specific physical transport will produce those bytes or recover in the same way.

## Relationship to downstream depth/VIO

The immediate value of this layer is to make discontinuity policy testable before #9 depth and #46 VIO consume live hardware evidence. Derived pipelines should be able to prove they do not silently integrate across sequence rollback, timestamp reversal, missing stereo input, IMU gaps, or a declared new continuity epoch.

A replay fault test is reliability evidence for software behavior only; it is not a calibration or physical-accuracy result.
