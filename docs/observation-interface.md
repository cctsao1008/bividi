# Native SensorObservation contract

Status: **Issue #11 — contract v1**

Bividi's stable native consumer boundary is the combination of:

```text
SensorCapabilities
SensorObservation
```

The contract describes normalized sensor topology and observations after platform/backend and device-adapter processing. It does not expose Nori/DECXIN, V4L2, Media Foundation, ROS, MCAP, OpenCV ownership types, or a downstream perception model.

## Boundary

```text
Nori live backend
Replay backend (#31)
Synthetic SensorRig (#58)
future V4L2 / Media Foundation
          ↓
Platform Backend
          ↓
Device Adapter
          ↓
SensorCapabilities + SensorObservation
          ↓
Calibration · Depth · VIO · Recorder · Robotics · LSMM
```

Durable rules:

```text
platform != device
device transport != sensor topology
transport payload != host observation
raw observation != derived product
observation != semantic truth
```

## Capability contract

`SensorCapabilities` describes runtime topology. Camera streams and stereo relationships are explicit:

```text
CameraStreamInfo[]
StereoPairInfo[]
IMU present / absent
audio present / absent
TimingCapabilities
TriggerMode[]
```

Two cameras do not become a stereo pair merely because both exist. `StereoPairInfo` names a relationship only; it does not claim physical left/right ordering, calibration quality, or a measured synchronization bound.

Image representation and physical modality remain separate. `PixelFormat` describes the host-visible image representation while `CameraModality` describes physical sensing modality when known.

## Observation contract

`SensorObservation` v1 carries:

```text
contract_version
source_id
evidence kind
source state
observation validity
sequence + sequence_present
continuity epoch / state
host and replay timing context
calibration identities
configuration revision
camera observations[]
IMU observations[]
stereo-pair status[]
```

`sequence_present` is explicit so sequence value `0` can remain a legitimate producer sequence rather than being overloaded as “not available”.

The contract intentionally supports mono, stereo, camera-only, IMU-only, and mixed sensor sources. Missing modalities are represented by absent observations/capabilities, not fabricated defaults.

## Image ownership

`ImageView` remains a non-owning image description. Each usable `CameraObservation` carries a `FrameLease` that keeps the backing resource alive.

This preserves the existing rule:

```text
image geometry != buffer ownership
```

No `cv::Mat` or vendor buffer handle is required by the core contract.

## Timing domains

There is no generic single `timestamp` field.

`TimePoint` always names:

```text
ticks
unit
clock domain
clock id
presence
```

The current clock domains are:

```text
host_monotonic
  host receive/acquisition boundary time

device
  extended device/frame/exposure/IMU time

replay
  replay scheduling timeline only
```

A camera observation may expose a device-domain `frame_time` when the device/API provides an unambiguous frame timestamp semantic. Exposure start/end remain separate fields. An adapter must not manufacture `frame_time` by silently choosing exposure start, midpoint, or end.

IMU sample time is attached to each IMU observation. Replay scheduling time never overwrites producer/device timestamps.

Finite-width source timestamps may additionally be preserved as `RawTimestampEvidence`. They are evidence for rollover/audit work; downstream code should use the extended `TimePoint` for normalized ordering.

`TimingCapabilities` declares which timing surfaces a source actually provides. Conformance validation requires those surfaces only when the corresponding capability is declared.

## Stereo synchronization state

A declared stereo pair and a synchronization claim are separate concepts.

`SensorObservation.stereo_pairs[]` carries per-pair status using:

```text
SynchronizationState
  unknown
  synchronized
  unsynchronized
  degraded
```

`unknown` is a valid and important state. A vendor protocol statement or common transport packet does not automatically justify publishing `synchronized`; that state should reflect the producer's documented evidence policy. Physical synchronization bounds remain characterization evidence, not topology.

## IMU raw versus SI values

`ImuObservation` can preserve either or both:

```text
raw accel/gyro counts
calibrated SI accel [m/s^2] / gyro [rad/s]
```

The flags are explicit:

```text
raw_valid
si_valid
```

This is important for the current DECXIN path. Raw ICM-42688-class counts and timestamps can be normalized into an observation without pretending that vendor-demo range/scaling assumptions are measured specimen calibration. A VIO backend must require `si_valid` and a matching inertial calibration identity rather than silently interpreting raw counts.

## Continuity

`continuity_epoch` separates stretches of observations that may be ordered internally but must not be silently joined across reconnect/reset/discontinuity boundaries.

`ContinuityState` communicates the current transition:

```text
continuous
discontinuity
reinitialized
```

Issue #59 will exercise drop/duplicate/out-of-order/timestamp faults against this boundary. Exact recovery policy belongs to the producer/derived pipeline; the core contract only makes the discontinuity visible.

## Source and validity state

Source availability and observation validity are different concepts:

```text
SourceState
  available
  disconnected
  error

ObservationValidity
  valid
  degraded
  invalid
```

A disconnected/error source cannot publish a `valid` observation. A degraded observation can remain consumable when a producer has explicit reasons to do so.

## Calibration/config identity

The observation carries opaque Bividi revision identifiers:

```text
CalibrationIdentity.stereo
CalibrationIdentity.imu
CalibrationIdentity.camera_imu
configuration_revision
```

These are references, not embedded solver schemas. Consumers resolve the corresponding versioned #8/#47 artifacts separately.

## DECXIN adapter

`bividi::decxin::to_sensor_observation()` is the first hardware-independent conformance adapter.

It maps a leased `decxin::DecodedFrame` to the generic contract while preserving:

- frame sequence with `sequence_present=true`;
- host receive monotonic time;
- exposure start/end extended device time;
- raw 32-bit exposure timestamp evidence;
- camera A/B image views and shared buffer lifetime;
- IMU raw/extended timestamps;
- raw accel/gyro counts;
- an explicit stereo-pair status entry.

The adapter deliberately leaves camera `frame_time` absent rather than choosing ES/midpoint/EE as a universal visual timestamp. Calibration/export paths select and record their required camera-time convention explicitly.

The initial DECXIN stereo-pair synchronization state is `unknown`. The adapter does not upgrade vendor synchronization claims into measured runtime evidence.

It also deliberately does **not** publish unverified IMU SI values. Camera streams remain named `camera_a` / `camera_b`; physical left/right naming remains blocked on #35 evidence.

## Conformance validation

`validate_capabilities()` checks topology consistency, including unique camera/pair identities and stereo references.

`validate_observation()` checks structural invariants such as:

- contract version/source identity;
- optional-sequence semantics;
- clock-domain semantics;
- camera buffer lifetime and declared geometry/pixel format;
- required device frame time only when advertised by capabilities;
- required exposure timing when advertised by capabilities;
- IMU capability/timestamp consistency;
- raw/SI measurement availability;
- finite SI values;
- stereo-pair status references;
- invalid source/observation state combinations.

Conformance means the object obeys the interface contract. It is not a physical accuracy, calibration-quality, or synchronization-accuracy claim.

## Derived products

Disparity, metric depth, XYZ/point clouds, VIO pose, and future SLAM products are not fields of `SensorObservation`.

They are separate derived outputs that reference the source observation/calibration/config context. This prevents an algorithm result from being confused with captured sensor evidence.

## Compatibility and versioning

The C++ contract exports:

```text
kObservationContractVersion = 1
```

Version policy:

- additive capabilities or optional fields that preserve existing semantics may remain within v1;
- changing units, transform meaning, clock meaning, ownership requirements, or validity semantics is a contract-version change;
- enum additions must be handled as unknown/unrecognized by serialization/adapters rather than silently remapped;
- serialized recording formats such as MCAP are adapters and carry the contract version explicitly; they are not the C++ ABI;
- no stable cross-compiler binary ABI is promised by these C++ structs. The durable promise is the documented source/domain contract plus conformance tests.

The legacy Python host/capability model remains useful as a reference/control surface but is no longer the authority for the native runtime observation schema.

## Next integrations

Issue ordering after this contract:

```text
#11 native contract
   ↓
#31 native replay / MCAP
#58 synthetic SensorRig
   ↓
#59 fault injection
   ↓
#9 depth / #46 VIO
```

Physical performance remains gated by #35, measured #8 stereo calibration, and measured #47 inertial/camera-IMU calibration.
