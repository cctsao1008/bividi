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
owned compressed-packet copy
        |
        +--> vendor lease returned immediately
        |
        v
bounded decode queue
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

## Ownership and acquisition/decode decoupling

`NoriCaptureSession` no longer holds a vendor SDK capture buffer while OpenCV/DECXIN decode runs. The acquisition thread copies each raw transport packet into bounded owned storage and returns the vendor lease before decode begins. A second private thread consumes that bounded queue through `DecxinPipeline(NormalizationOwnership::own_output)`.

The default `NoriSessionConfig::decode_queue_depth` is 256. It is a finite burst-absorption bound, not permission for unbounded processing latency. `SessionStatus` exposes source continuity plus decode-queue capacity, current occupancy, high-water mark, overflow count, and explicit lifecycle flush count so transport loss can be distinguished from downstream queue pressure.

Decoded camera storage is owned independently. Copies returned by `latest_observation()` retain that storage through `FrameLease`, so downstream consumers do not pin either the vendor capture pool or a queued compressed packet.

The two-stage runtime design was promoted after physical qualification showed the distinction clearly: synchronous full-frame MJPEG decode could lose source sequences, while the bounded copy-before-decode qualifier captured and decoded a 3000-frame run with zero source gaps, zero decoded gaps, and zero queue overflows.

## Evidence semantics

A frame acquired from the live vendor-backed sensor path is tagged `EvidenceKind::measured`. This means the observation came from physical acquisition. It does **not** imply any of the following:

- a measured stereo synchronization bound;
- a promoted stereo calibration;
- a promoted IMU calibration;
- a promoted camera-IMU calibration;
- validated metric-depth accuracy.

Physical lens mapping has now been measured by direct occlusion on the delivered specimen:

```text
observer facing the lens side:
front-view LEFT lens  -> camera_a
front-view RIGHT lens -> camera_b
```

This evidence does not by itself rename the public streams to `stereo_left` / `stereo_right`; that naming remains deferred until the rig/calibration coordinate convention is frozen.

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

`camera_a` / `camera_b` remain the runtime identifiers even though physical front-view orientation is now measured. They are transport-stable names; final stereo left/right naming belongs to the calibrated rig convention.

## Continuity and stale-data behavior

The first normalized observation after a successful connection is marked `reinitialized`.

After a successful reconnect or an explicit stop/start lifecycle boundary:

1. queued pre-transition packets are flushed and counted;
2. in-flight stale decode output is rejected by generation/epoch checks;
3. DECXIN timestamp extenders reset on the next decode generation;
4. the continuity epoch increments after an established connection;
5. the first newly published observation is marked `reinitialized`.

Source sequence gaps, duplicates, and out-of-order frames are tracked before the decode queue. Published-frame continuity remains separately visible through the existing capture counters. A queue overflow is counted explicitly and will also become observable as a downstream published-sequence discontinuity when a later sequence arrives.

The normalized observation marks a non-reinitialized published sequence jump as `ContinuityState::discontinuity`; it does not silently rewrite evidence to make the stream appear continuous.

On a capture/connect/decode error, queued packets and cached normalized output are invalidated rather than leaving plausible stale sensor results available to downstream consumers.

## Web depth consequence

The browser depth service already accepts any `CaptureSession` that also implements `ObservationSnapshotSource`. Therefore a Nori-enabled build can use the same explicit calibrated depth path as replay once a calibration artifact is supplied.

That wiring is architectural availability only. Until physical calibration, synchronization, and depth validation are completed on the delivered AR0234 specimen, a live depth image must not be described as validated AR0234 metric-depth accuracy.

## CI boundary

Normal CI does not possess the proprietary Nori SDK or physical hardware. The workflow therefore syntax-checks `src/native/nori_session.cpp` directly against the public C++17 headers, while the hardware-independent observation tests pin the multiple-inheritance/API contract and conservative default evidence/calibration state.

Physical acquisition behavior remains gated by the Issue #35 hardware campaign.
