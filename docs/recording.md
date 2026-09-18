# Bividi Recording and Replay Contract

Status: native `SensorObservation` replay and explicit replay interception are implemented; the first Bividi-native `SensorObservation` MCAP semantic codec is implemented. Direct MCAP-backed replay/live-recording integration remains follow-up work in Issue #31.

## Purpose

Define how Bividi records and replays sensor observations reproducibly without making the recording container part of the core observation model.

The preferred long-term recording container is MCAP. MCAP is an adapter/storage format; Bividi's logical observation contract remains independent of it.

For ROS interoperability, the preferred modern path is ROS2 `rosbag2` with MCAP storage. Any ROS1 `.bag` generation in the calibration toolchain is a narrow compatibility adapter for an external legacy solver and must not be interpreted as the Bividi recording architecture.

```text
SensorObservation + SensorCapabilities
        |
        +--> native Bividi session replay adapter
        |
        +--> explicit replay interception decorator (#59)
        |
        +--> Bividi-native SensorObservation MCAP codec v1
        |
        +--> ROS2 rosbag2 + MCAP interoperability adapter
        |
        +--> ROS1 .bag only where a specific external tool requires it
```

## Native replay source

The first native replay importer intentionally starts from the existing Nori calibration-session evidence layout rather than inventing a second recording schema:

```text
capture.json
frames.csv
imu.csv
camera_a/*.png
camera_b/*.png
        ↓
ReplaySource
        ↓
SensorCapabilities + SensorObservation v1
```

`ReplaySource` supports:

```text
step
as-fast-as-possible
real-time
scaled replay
```

Original producer timing is preserved. Real-time/scaled playback adds a separate replay scheduling clock and never overwrites the recorded host/device timestamps.

The importer reconstructs the union of camera-frame and IMU frame indices. Therefore a recorder `frame_stride` that intentionally omits some image pairs does not silently delete the corresponding IMU-bearing observations.

## Explicit replay interception seam

Issue #59 needs deterministic fault injection without teaching the production DECXIN/Nori decoder about test-only corruption modes. The interception point is therefore an explicit decorator **above** normal `ReplaySource`:

```text
recorded session
    ↓
ReplaySource
    ↓
materialized + source-conformance-checked SensorObservation
    ↓
InterceptedReplaySource                 [only when explicitly constructed]
    ↓
ReplayObservationInterceptor
    ↓
zero / one / many emitted observations
    ↓
consumer / regression assertion
```

Normal replay does not pass through this decorator, so production replay behavior is unchanged when no fault test is requested.

`ReplayObservationInterceptor` can buffer an input and later emit it, emit multiple copies, emit nothing, or mutate the observation. This is sufficient as a transport-independent seam for later #59 recipes such as drop, duplicate, reorder, timestamp mutation, missing camera, IMU mutation, and explicit continuity changes.

The pre-interceptor observation has already passed the normal replay source conformance check. **Post-interceptor observations are deliberately not automatically repaired or revalidated by the interception stage.** A fault recipe may intentionally create degraded or structurally invalid evidence; the consuming regression test must assert the layer-specific expected disposition, for example rejection, degraded validity, a new continuity epoch, a derived-pipeline reset, or an explicit gap.

`source_size()` and `source_position()` refer to the original source timeline even when an interceptor changes the number or order of emitted observations. `reset()` rewinds the original replay source, clears buffered emitted observations, and resets interceptor state so a recipe remains deterministic.

The interception seam itself does not define a recipe format, seed policy, or fault taxonomy. Those are owned by #59. It also does not replace physical disconnect/reconnect, USB, hub, power, SDK recovery, or synchronization testing in #35.

## Engineering viewer / web replay

`ReplayCaptureSession` adapts the native replay stream to the existing engineering `CaptureSession` surface without changing the normalized observation contract.

Viewer example:

```bash
bividi-viewer \
  --source replay \
  --session path/to/bividi_nori_calib_session \
  --replay-rate 1.0
```

Web console example:

```bash
bividi-web \
  --source replay \
  --session path/to/bividi_nori_calib_session \
  --replay-rate 1.0
```

Replay exposure/gain/trigger controls are deliberately read-only/unavailable. Pause/resume and reset/restart are playback controls, not attempts to mutate the recorded sensor evidence.

Calibration-session PNGs are normally lossless mono images. Their `SensorObservation` image representation remains `GRAY8`; only the engineering preview adapter converts an owned display copy to BGR for the existing viewer/web renderer. The replay observation itself is not relabeled as BGR.

## Recorded unit

A recording session should preserve enough information to reconstruct the observation context:

```text
session
  source identity
  capture mode identity
  sequence / sequence-presence
  producer timestamps
  acquisition / synchronization status
  calibration identity
  configuration identity
  camera observations / media
  IMU observations
  optional derived products
  validity / quality metadata
  producer/version metadata
  provenance/artifact hashes
```

The stable native boundary is the #11 `SensorCapabilities` + `SensorObservation` contract. Storage schemas are adapters to that boundary, not replacements for it.

## Required separation

```text
raw captured evidence
    !=
derived geometry
    !=
AI / semantic interpretation
```

These may coexist in one eventual MCAP file, but must use separate logical channels/schemas so replay cannot confuse a derived result with the original capture.

## Bividi-native MCAP codec v1

The first native MCAP storage codec is defined in [`mcap-observation.md`](mcap-observation.md). It maps the frozen `SensorObservation` v1 boundary to a versioned MCAP profile while preserving producer timing inside the observation envelope.

The first channel family is intentionally narrow:

```text
/bividi/observation
/bividi/source/<source-id>/camera/<stream-id>
```

The observation envelope preserves sequence, continuity, validity, timing-domain evidence, calibration/configuration identity, IMU data, camera metadata, and stereo synchronization state. Camera byte payloads remain separate binary MCAP messages with explicit byte-count and SHA-256 binding.

MCAP `log_time` / `publish_time` are a deterministic **container-order clock only** in this profile. They are not host receive time, device exposure/IMU time, UTC, or replay scheduling time. The original clocks remain explicit in the Bividi payload.

Direct C++ live recording to this profile and direct MCAP-backed `ReplaySource` integration remain Issue #31 follow-up slices; the storage/semantic contract does not depend on either runtime integration.

ROS2 calibration interoperability currently uses standard `sensor_msgs/msg/Image` and `sensor_msgs/msg/Imu` topics because external robotics tools understand those message contracts. Those ROS2 topic/message types remain adapters; they do not replace Bividi's own observation schema.

## Timestamp policy

Preserve producer timestamps explicitly and do not replace them with playback or storage time.

Current native replay keeps distinct:

- original host receive monotonic time;
- device exposure start and exposure end;
- device IMU sample time;
- finite-width raw timestamp evidence;
- optional replay scheduling time;
- MCAP container-order time when the native MCAP adapter is used.

There is deliberately no automatic camera visual-frame timestamp synthesized from exposure start, midpoint, or exposure end. Any algorithm requiring such a reference must select and document that semantic explicitly.

When exporting a calibration session to ROS2/MCAP, the explicitly selected sensor-derived timestamp is used for both the ROS message header and rosbag2 record timestamp. That calibration interoperability convention is separate from the Bividi-native MCAP profile, whose MCAP record time is deliberately non-semantic container ordering.

## Integrity checks

The native replay importer rejects evidence that cannot be reconstructed consistently, including:

- `frames.csv` / `imu.csv` identity disagreements for the same frame index;
- malformed or missing required metadata columns;
- absolute or session-escaping media paths;
- image decode failures;
- camera A/B geometry or representation mismatch;
- unsupported image representations;
- mid-session image geometry/format changes.

The native MCAP codec independently rejects malformed observation envelopes, unsupported profile/schema versions, non-tight image representations in v1, missing/duplicate/unreferenced camera payloads, and byte-count/SHA-256 mismatches.

Replay or MCAP round-trip success proves that the software/storage contract is obeyed. It does not prove physical synchronization, calibration accuracy, or hardware quality.

## Provenance

Derived outputs must identify:

- source observation ID or sequence;
- calibration ID/hash;
- processing algorithm/config version;
- producer identity;
- validity/status.

Reprocessing a recording produces a new derived result; it must not overwrite the provenance of the original result.

Transport conversion also needs provenance. A ROS2/MCAP or ROS1 export should retain the source session identity/hash and identify the adapter/tool version so the container can be traced back to the same Bividi evidence.

## Test strategy

Hardware-independent replay/MCAP fixtures verify:

```text
recorded mono stereo + raw IMU
  → ReplaySource
  → SensorObservation
  → pause / reset / scaled timing
  → engineering BGR preview copy

recorded session
  → ReplaySource
  → InterceptedReplaySource
  → hold / duplicate / delayed emission / drop
  → deterministic source-position and reset assertions

SensorObservation fixture
  → Bividi-native MCAP
  → SensorObservation
  → semantic digest + exact byte/timestamp equality
```

The replay fixture intentionally includes an IMU-only timeline observation between image-bearing observations to ensure `frame_stride` does not collapse source chronology. The interception fixture proves the seam can change output cardinality/order while the original source timeline and reset behavior remain explicit. The MCAP fixture covers GRAY8 stereo, IMU-only, BGR24, invalid raw IMU, and preserved `unknown` stereo synchronization.

Physical AR0234 validation remains owned by #35, #8, and #47 evidence campaigns.

## Non-goals

- MCAP is not the Bividi core API.
- `CaptureSession` preview state is not the Bividi normalized data API.
- Fault recipes are not part of the production decoder.
- Synthetic/replay fault injection is not physical disconnect/reconnect validation.
- ROS2 messages are not the Bividi core API.
- ROS1 `.bag` is not the preferred Bividi recording format.
- Replay scheduling time is not original sensor time.
- MCAP container-order time is not producer/device time.
- Replay does not manufacture SI IMU values from unverified vendor-demo scaling.
- Replay does not upgrade unknown stereo synchronization into measured synchronization.
- Recording, replay, or MCAP round-trip success does not prove camera synchronization or timing quality.
- Large media should not be committed to normal Git history.
