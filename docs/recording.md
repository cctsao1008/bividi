# Bividi Recording and Replay Contract

Status: pre-hardware design contract

## Purpose

Define how Bividi records stereo observations for reproducible replay without making the recording container part of the core observation model.

The recommended recording container is MCAP. MCAP is an adapter/storage format; Bividi's logical observation contract remains independent of it.

For ROS interoperability, the preferred modern path is ROS2 `rosbag2` with MCAP storage. Any ROS1 `.bag` generation in the calibration toolchain is a narrow compatibility adapter for an external legacy solver and must not be interpreted as the Bividi recording architecture.

```text
Bividi logical observation/session
        |
        +--> MCAP native/storage adapter
        |
        +--> ROS2 rosbag2 + MCAP interoperability adapter
        |
        +--> ROS1 .bag only where a specific external tool requires it
```

## Recorded unit

A recording session should preserve enough information to reconstruct the observation context:

```text
session
  source identity
  capture mode identity
  sequence/timestamps
  left/right observation references or payloads
  acquisition/sync status
  calibration identity
  rectification state
  optional disparity/depth products
  validity/quality metadata
  producer/version metadata
  provenance/artifact hashes
```

## Required separation

```text
raw captured evidence
    !=
derived geometry
    !=
AI/semantic interpretation
```

These may coexist in one MCAP file, but must use separate logical channels/schemas so replay cannot confuse a derived result with the original capture.

## Proposed channel families

```text
/bividi/source/<id>/left
/bividi/source/<id>/right
/bividi/source/<id>/capture_status
/bividi/source/<id>/calibration
/bividi/source/<id>/disparity
/bividi/source/<id>/depth
/bividi/source/<id>/quality
/bividi/source/<id>/observation
```

Names are provisional until the final observation interface (#11) is frozen.

ROS2 calibration interoperability currently uses standard `sensor_msgs/msg/Image` and `sensor_msgs/msg/Imu` topics because external robotics tools understand those message contracts. Those ROS2 topic/message types remain adapters; they do not replace Bividi's own observation schema.

## Timestamp policy

Preserve producer timestamps explicitly and do not replace them with playback time.

Where available distinguish:

- device/acquisition timestamp;
- host receipt timestamp;
- processing completion timestamp;
- record/write timestamp.

Replay must retain the original timing evidence and may separately expose replay-clock time.

When exporting a calibration session to ROS2/MCAP, the sensor-derived timestamp is used for both the ROS message header and rosbag2 record timestamp. Host-arrival time is not silently substituted.

## Provenance

Derived outputs must identify:

- source observation ID or sequence;
- calibration ID/hash;
- processing algorithm/config version;
- producer identity;
- validity/status.

Reprocessing a recording produces a new derived result; it must not overwrite the provenance of the original result.

Transport conversion also needs provenance. A ROS2/MCAP or ROS1 export should retain the source session identity/hash and identify the adapter/tool version so the container can be traced back to the same Bividi evidence.

## Hardware-independent first step

Before the physical camera arrives, validate the contract with the synthetic provider:

```text
MockStereoProvider
  → BividiHost
  → synthetic StereoObservation
  → MCAP writer
  → MCAP reader/replay provider
  → same logical observation envelope
```

Synthetic data must remain marked synthetic throughout recording and replay.

The #47 calibration path has an additional staged-session adapter that can emit ROS2 rosbag2/MCAP for modern robotics interoperability while keeping the upstream Kalibr ROS1 conversion isolated at the solver boundary.

## Non-goals

- MCAP is not the Bividi core API.
- ROS2 messages are not the Bividi core API.
- ROS1 `.bag` is not the preferred Bividi recording format.
- MCAP does not define semantic truth.
- Recording success does not prove camera synchronization or timing quality.
- Large media should not be committed to normal Git history.
