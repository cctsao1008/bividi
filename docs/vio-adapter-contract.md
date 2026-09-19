# Stereo-inertial VIO adapter contract

This document freezes the first hardware-independent boundary for Issue #46. It defines how normalized `SensorObservation` data becomes a backend-ready stereo-inertial packet and how a derived pose result is represented. It does **not** select or implement a visual-inertial odometry algorithm.

## Placement

```text
SensorObservation (#11)
        ↓
VioInputAdapter
        ↓
VioPacket
        ↓
optional VioBackend
        ↓
PoseObservation
```

The adapter is built as the standalone dependency-light `bividi_vio` target. It depends on Bividi's normalized observation contract but is not part of raw acquisition. The public VIO header contains no Nori/DECXIN, OpenCV, ROS, Kalibr, dense-depth, or third-party VIO types.

## Required evidence

A packet is backend-ready only when all of the following are explicit:

- source is available and the observation is fully valid;
- the configured stereo pair is present and explicitly synchronized;
- both configured camera observations are usable and fully valid;
- camera reference time is derived from compatible device-clock exposure timing;
- at least one IMU sample is present, calibrated to SI units, valid, finite, and on the same device clock/unit as the cameras;
- IMU timestamps arrive in strictly increasing source order with no duplicates;
- stereo, IMU, and camera↔IMU calibration identities are all non-empty;
- configuration revision is non-empty.

Raw IMU counts remain valid evidence at the observation layer, but raw-only samples are not accepted as VIO input.

## Time semantics

Camera time is selected explicitly by `VioCameraTimeReference`:

- `exposure_start`;
- `exposure_midpoint`;
- `exposure_end`.

`exposure_midpoint` is calculated as `start + (end - start) / 2`, which avoids unsigned overflow. Start and end must both be present on the same device clock with the same unit and clock id.

The two stereo cameras must produce the same selected reference timestamp. IMU sample timestamps must use that same clock domain, unit, and clock id.

Host receive time is provenance only. It is never substituted for a missing camera/exposure timestamp and is never used as the VIO alignment clock.

## Continuity and reset semantics

`VioPacket` distinguishes processable input from state-control input:

- first backend-ready packet in an epoch → `ready` + `reinitialize`;
- same continuous epoch → `ready` + no reset;
- new continuity epoch → `ready` + `reinitialize`;
- observation marked `reinitialized` → `ready` + `reinitialize`;
- observation marked `discontinuity` → `reset_required` + `reset_before_next`; it is not backend-ready;
- invalid source/data/calibration/timing → `rejected` with a specific reason.

The adapter never fabricates continuity. It consumes the normalized source's explicit continuity state/epoch and does not silently repair missing or out-of-order samples.

## Derived pose contract

`PoseObservation` is a downstream result, not a raw sensor observation. Its transform convention is `world_from_body`: position and quaternion place the VIO body frame in the backend-defined world frame.

A valid derived result preserves:

- camera-reference device timestamp;
- position in metres;
- `xyzw` orientation quaternion, normalized to unit length;
- velocity in metres per second;
- explicit tracking state and validity;
- stereo / IMU / camera↔IMU calibration identities;
- configuration revision;
- backend id and backend version;
- continuity epoch and source sequence identity.

`validate_pose_observation()` rejects non-device timestamps, non-finite vectors/quaternions, non-normalized quaternions, missing calibration/config identity, missing backend identity/version, or an implicit/uninitialized tracking state.

## What this does not prove

The adapter tests architecture and state semantics only. They do not establish VIO accuracy, drift, initialization quality, timing accuracy, or robustness on the delivered AR0234 hardware.

Live VIO characterization remains blocked on measured evidence from #35, #8, and #47. A third-party VIO backend must still be selected separately after license, integration, calibration, CPU/runtime, and recovery-behaviour review. Dense depth from #9 is not a prerequisite for this interface.
