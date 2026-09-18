# Live Nori normalized observation snapshot

This note defines the first normalized `SensorObservation` snapshot surface exposed by the live DECXIN/Nori session for Issue #35.

## Boundary

The live path is:

```text
Nori SDK / platform backend
        |
        v
RawFrame + vendor buffer lease
        |
        v
normalize_to_bgr24(own_output)
        |
        v
DECXIN decode
        |
        +--> CaptureSession / StereoPreviewFrame
        |
        v
decxin::to_sensor_observation
        |
        v
ObservationSnapshotSource
        |
        +--> recorder / diagnostics / derived consumers
        `--> calibrated depth consumer when explicitly configured
```

`CaptureSession` remains the UI/lifecycle/control surface. The normalized observation tap is a separate opt-in interface and does not turn `CaptureSession` into a sensor-data API.

## Ownership

`NoriCaptureSession` uses `DecxinPipeline(NormalizationOwnership::own_output)`. The vendor buffer lease is returned promptly after decode, while the decoded camera storage is owned independently. Copies returned by `latest_observation()` retain that storage through `FrameLease`.

A consumer may therefore keep a returned normalized observation after the session mutex is released without pinning the Nori vendor capture pool.

## Evidence semantics

A frame acquired from the live vendor-backed sensor path is tagged `EvidenceKind::measured`. This means the observation came from physical acquisition. It does **not** imply any of the following:

- a measured camera A/B to physical left/right mapping;
- a measured stereo synchronization bound;
- a promoted stereo calibration;
- a promoted IMU calibration;
- a promoted camera-IMU calibration;
- validated metric-depth accuracy.

The DECXIN normalized stereo pair continues to report `SynchronizationState::unknown`. `TimingCapabilities::hardware_sync` remains false until a separate runtime/physical measurement justifies a stronger statement.

Calibration identity fields are empty by default. A caller may explicitly provide known calibration identities through `NoriSessionConfig`; the session does not invent them.

## Topology

The live DECXIN adapter exposes the topology it can establish from the decoded transport contract:

- `camera_a`: BGR24, 1920x1200;
- `camera_b`: BGR24, 1920x1200;
- stereo pair `stereo0` = (`camera_a`, `camera_b`);
- raw IMU observations are present when decoded from metadata;
- host receive monotonic time is present;
- exposure start/end device time is present;
- IMU device sample time is present;
- generic visual `frame_time` remains unset because the adapter does not choose ES/midpoint/EE semantics for consumers.

The names `camera_a` and `camera_b` are deliberately retained. Physical left/right identity remains a hardware-evidence task.

## Continuity and stale-data behavior

The first normalized observation after a successful connection is marked `reinitialized`.

After a successful reconnect:

1. cached preview and normalized observation are cleared;
2. DECXIN timestamp extenders are reset;
3. the continuity epoch increments;
4. the first newly published observation is marked `reinitialized`.

Capture sequence gaps, duplicates, and out-of-order frames remain observable through the existing capture counters and sequence values. Derived consumers retain responsibility for their own chronology policy; the session does not silently rewrite evidence to make it appear continuous.

On a capture/connect error, the cached normalized observation is cleared rather than leaving a plausible stale sensor result available to downstream consumers.

## Web depth consequence

The browser depth service already accepts any `CaptureSession` that also implements `ObservationSnapshotSource`. Therefore a Nori-enabled build can use the same explicit calibrated depth path as replay once a calibration artifact is supplied.

That wiring is architectural availability only. Until physical calibration, camera-order mapping, synchronization, and depth validation are completed on the delivered AR0234 specimen, a live depth image must not be described as validated AR0234 metric-depth accuracy.

## CI boundary

Normal CI does not possess the proprietary Nori SDK or physical hardware. The workflow therefore syntax-checks `src/native/nori_session.cpp` directly against the public C++17 headers, while the hardware-independent observation tests pin the multiple-inheritance/API contract and conservative default evidence/calibration state.

Physical acquisition behavior remains gated by the Issue #35 hardware campaign.
