# Bividi Recording and Replay Contract

Status: native `SensorObservation` replay implemented; MCAP storage adapter remains follow-up work in Issue #31.

## Purpose

Define how Bividi records and replays sensor observations reproducibly without making the recording container part of the core observation model.

The preferred long-term recording container is MCAP. MCAP is an adapter/storage format; Bividi's logical observation contract remains independent of it.

For ROS interoperability, the preferred modern path is ROS2 `rosbag2` with MCAP storage. Any ROS1 `.bag` generation in the calibration toolchain is a narrow compatibility adapter for an external legacy solver and must not be interpreted as the Bividi recording architecture.

```text
SensorObservation + SensorCapabilities
        |
        +--> native Bividi session replay adapter
        |
        +--> MCAP native/storage adapter          [follow-up]
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

## Channel-family direction for MCAP

The eventual MCAP adapter should map the frozen observation boundary into versioned channels roughly along these roles:

```text
/bividi/source/<id>/observation
/bividi/source/<id>/camera/<stream-id>
/bividi/source/<id>/imu/<sensor-id>
/bividi/source/<id>/status
/bividi/source/<id>/calibration
/bividi/source/<id>/derived/disparity
/bividi/source/<id>/derived/depth
/bividi/source/<id>/derived/quality
```

Exact serialized message schemas remain an Issue #31 follow-up. Channel naming must not alter the C++ observation semantics.

ROS2 calibration interoperability currently uses standard `sensor_msgs/msg/Image` and `sensor_msgs/msg/Imu` topics because external robotics tools understand those message contracts. Those ROS2 topic/message types remain adapters; they do not replace Bividi's own observation schema.

## Timestamp policy

Preserve producer timestamps explicitly and do not replace them with playback time.

Current native replay keeps distinct:

- original host receive monotonic time;
- device exposure start and exposure end;
- device IMU sample time;
- finite-width raw timestamp evidence;
- optional replay scheduling time.

There is deliberately no automatic camera visual-frame timestamp synthesized from exposure start, midpoint, or exposure end. Any algorithm requiring such a reference must select and document that semantic explicitly.

When exporting a calibration session to ROS2/MCAP, the explicitly selected sensor-derived timestamp is used for both the ROS message header and rosbag2 record timestamp. Host-arrival time is not silently substituted.

## Integrity checks

The native replay importer rejects evidence that cannot be reconstructed consistently, including:

- `frames.csv` / `imu.csv` identity disagreements for the same frame index;
- malformed or missing required metadata columns;
- absolute or session-escaping media paths;
- image decode failures;
- camera A/B geometry or representation mismatch;
- unsupported image representations;
- mid-session image geometry/format changes.

Replay success proves that the recording obeys the replay contract. It does not prove physical synchronization, calibration accuracy, or hardware quality.

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

Hardware-independent replay fixtures verify:

```text
recorded mono stereo + raw IMU
  → ReplaySource
  → SensorObservation
  → pause / reset / scaled timing
  → engineering BGR preview copy
```

The fixture intentionally includes an IMU-only timeline observation between image-bearing observations to ensure `frame_stride` does not collapse source chronology.

Physical AR0234 validation remains owned by #35, #8, and #47 evidence campaigns.

## Non-goals

- MCAP is not the Bividi core API.
- `CaptureSession` preview state is not the Bividi normalized data API.
- ROS2 messages are not the Bividi core API.
- ROS1 `.bag` is not the preferred Bividi recording format.
- Replay scheduling time is not original sensor time.
- Replay does not manufacture SI IMU values from unverified vendor-demo scaling.
- Replay does not upgrade unknown stereo synchronization into measured synchronization.
- Recording or replay success does not prove camera synchronization or timing quality.
- Large media should not be committed to normal Git history.
