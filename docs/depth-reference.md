# Deterministic Stereo Depth Reference

Status: hardware-independent numerical kernel, normalized `SensorObservation` adapter, and deterministic replay/fault integration for Issue #9. The module is an optional OpenCV/calib3d downstream consumer; it is not part of `bividi_core` and does not establish physical AR0234 depth accuracy.

## Purpose

Provide one correctness-first classical stereo path with explicit calibration identity and invalid-pixel semantics:

```text
camera A/B ImageView
        +
selected #8 stereo calibration
        ↓
rectification maps
        ↓
rectified pair
        ↓
OpenCV StereoSGBM
        ↓
float disparity [px] + valid mask
        ↓
Z = fx * baseline / disparity
        ↓
metric depth [m]
        ↓
optional XYZ in rectified camera-A coordinates
```

This is a deterministic reference implementation for plumbing, regression, replay, and later hardware characterization. It is deliberately not CUDA/GPU optimized and does not attempt to select a physically correct matcher policy before measured data exists.

## Build boundary

`bividi_depth` is only created when the optional OpenCV `core`, `imgproc`, and `calib3d` components are available.

```text
bividi_core
    ↑
bividi_depth   [optional OpenCV geometry consumer]
```

Acquisition, replay, #11 observation types, and vendor/device backends remain usable without the depth target.

The numerical public header is `include/bividi/depth.hpp`. The normalized observation adapter is `include/bividi/depth_observation.hpp`. OpenCV types are allowed at this boundary because depth is explicitly an OpenCV-dependent downstream module rather than a core domain contract.

## Calibration contract

`load_calibration_json()` consumes the geometry required from the versioned #8 artifact:

```text
schema = bividi.calibration.stereo.v1
calibration_id
capture camera A/B identities
image width / height
camera A/B K and D
baseline_m
R1 / R2
P1 / P2
Q
```

The loader currently supports the first #8 native pinhole models:

```text
opencv5
opencv-rational
```

It validates matrix dimensions, finite values, positive baseline/focal lengths, image geometry, identity presence, and consistency between `baseline_m` and the horizontal baseline encoded by `P2` when present.

The loader is **not** a replacement for #8 artifact promotion. A synthetic or measured calibration can be consumed for the appropriate test/research purpose, but physical metric-depth claims still require the measured #8 evidence gate.

## Matcher configuration

The first reference matcher is `cv::StereoSGBM`. Parameters are explicit in `StereoDepthConfig`, including:

- `min_disparity`;
- `num_disparities` (positive multiple of 16);
- odd `block_size`;
- uniqueness ratio;
- left/right consistency threshold;
- pre-filter cap;
- optional speckle filtering;
- optional XYZ generation.

No matcher settings are labeled as AR0234-optimal yet. Those values become characterization parameters once real calibrated captures exist.

## Numeric products

The engineering products remain separate from display products.

`StereoDepthResult` keeps:

```text
rectified_a / rectified_b     owned image matrices
disparity_px                  CV_32F pixels
valid_mask                    CV_8U
depth_m                       CV_32F meters
xyz_m                         optional CV_32FC3 meters
calibration_id
coordinate_frame
```

Invalid disparity/depth/XYZ is never encoded as a plausible metric zero. Invalid float samples are quiet NaN and the validity mask is zero.

The UI-only helpers:

```text
disparity_preview_u8()
depth_preview_u8()
```

produce normalized 8-bit images and do not replace the numeric arrays or their validity mask.

## Metric geometry

The first horizontal rectified path uses:

```text
Z = fx * B / d
```

where:

- `fx` comes from rectified `P1`;
- `B` is `baseline_m` from the selected #8 calibration artifact;
- `d` is finite positive disparity in pixels.

Optional XYZ is expressed in the rectified camera-A optical frame:

```text
X = (u - cx) * Z / fx
Y = (v - cy) * Z / fy
Z = fx * B / d
```

The coordinate frame is carried explicitly as `camera_a_rectified` in this first slice; later physical integration must bind this to the corresponding calibration/source identity rather than infer physical `left/right` labels.

## Normalized `SensorObservation` adapter

`StereoDepthObservationProcessor` is the explicit bridge from the #11 normalized observation contract to the numerical depth kernel:

```text
SensorCapabilities + selected StereoPairInfo
                  +
SensorObservation
                  +
selected #8 StereoDepthCalibration
                  ↓
StereoDepthObservationProcessor
                  ↓
processed depth result
        or
explicit rejection with no depth matrices
```

The adapter does not alter acquisition data and does not manufacture repaired observations. It selects the two streams from the declared `StereoPairInfo` ordering and requires the corresponding camera observations to be fully valid/usable.

Current per-observation gates include:

- source must be `available`;
- observation must not be invalid;
- the selected stereo pair must have a status entry;
- `unsynchronized` and `degraded` stereo status are rejected;
- `unknown` synchronization may be allowed by policy for replay/synthetic evidence, but remains `unknown` in the result and is never upgraded to synchronized;
- both selected camera observations must exist and be fully valid/leased;
- if the observation carries a stereo calibration ID, it must equal the selected calibration artifact ID;
- deployments may additionally require that every observation explicitly carries that calibration ID.

A rejection returns empty disparity/depth/XYZ matrices. This is the central no-fake-depth rule at the normalized observation boundary.

### Derived-stream continuity

StereoSGBM itself is per-frame, but the adapter still keeps derived-stream chronology explicit so later recorder/temporal consumers cannot mistake a discontinuous result sequence for continuous geometry.

The adapter:

- records a reset generation;
- resets chronology at `reinitialized` / `discontinuity` boundaries or continuity-epoch changes;
- rejects duplicate/backward sequence numbers within one continuous epoch;
- treats a forward sequence gap as a reset boundary by default;
- schedules a fresh generation after a rejected usable-frame fault such as a missing camera;
- preserves source ID, evidence kind, sequence, continuity epoch/state, pair ID, synchronization state, and calibration ID in the adapter result.

This reset is deliberately adapter/derived-stream state. It does not claim that the stateless numerical `StereoSGBM` kernel itself has hidden temporal state.

## Deterministic test geometry

The native tests use the same simple geometry chosen for the first #58 synthetic SensorRig:

```text
image      96 x 64
fx         80 px
baseline   0.10 m
plane Z    2.0 m
expected d 4 px
```

The texture is deterministic and camera B samples the same virtual plane at the exact 4-pixel offset. Tests separately prove:

1. exact metric conversion of a known 4-pixel disparity;
2. invalid-mask → NaN propagation;
3. XYZ coordinate math;
4. identity rectification → StereoSGBM → median disparity near 4 px;
5. resulting median depth near 2 m;
6. rejection of inconsistent calibration/configuration/input geometry;
7. display-preview separation from numeric results;
8. normalized stereo-pair selection and synthetic provenance preservation;
9. unknown synchronization preservation without silent promotion;
10. no depth output for missing camera, unsynchronized pair, or calibration mismatch;
11. explicit reset generation across rejected frames, sequence gaps, and continuity epochs;
12. duplicate/backward normalized observation rejection.

These tolerances are algorithmic regression tolerances for the synthetic fixture, not product acceptance thresholds.

## End-to-end replay and fault evidence

The deterministic #58 session is now exercised through the real replay and derived-consumer chain in CTest:

```text
#58 generated static-plane session
        ↓
#31 ReplaySource
        ↓
#11 SensorObservation + StereoPairInfo
        ↓
StereoDepthObservationProcessor
        ↓
#9 StereoSGBM
        ↓
disparity ≈ 4 px
metric depth ≈ 2 m
XYZ
```

This test does not construct a substitute camera observation at the depth boundary. The generated session is decoded by `ReplaySource`, preserving synthetic provenance, sequence/continuity semantics, camera leases, and the replay source's `unknown` stereo-synchronization evidence. The depth policy permits that unknown state for this synthetic/replay regression while keeping it explicitly `unknown` in the derived result.

The same CTest binary places #59's `RecipeReplayInterceptor` between `ReplaySource` and the real depth consumer and proves these layer-specific dispositions:

```text
remove camera_b
    → rejected_camera_missing
    → no disparity/depth/XYZ
    → next usable frame starts a new derived-stream generation

set stereo0 = unsynchronized
    → rejected_synchronization
    → no depth
    → recovery resets before derived output

duplicate observation
    → first copy may be processed
    → second identical sequence is rejected_sequence_non_monotonic
    → recovery resets

set continuity = discontinuity, epoch +1
    → current frame may still produce per-frame depth
    → reset occurs before that derived output
    → return to the recorded epoch is another explicit boundary, not silent repair
```

This is the first concrete proof that a real derived consumer reacts to deterministic replay faults instead of merely proving the fault injector can mutate observations.

## Remaining software-only slices

Useful remaining synthetic/replay work is narrower now:

- add an explicit forward `sequence_delta` recipe through the same chain to pin sequence-gap reset behavior at the #59 seam (the adapter behavior is already unit-tested);
- add timestamp-only replay faults as evidence-preservation tests without treating timestamp mutation itself as a synchronization estimator;
- decide whether a recorder/derived-product envelope should persist the depth result plus source/calibration/reset provenance;
- expose depth in viewer/web only after keeping numeric geometry separate from visualization and after deciding the runtime cost budget.

These are software-contract tasks. They still cannot establish physical stereo synchronization, USB recovery, or AR0234 metric accuracy.

After physical hardware arrives:

```text
#35 live acquisition evidence
        +
#8 promoted measured calibration
        ↓
real AR0234 depth characterization
        ↓
range / error / invalid-rate / latency evidence
```

## Guardrails

- Synthetic success is not physical depth accuracy.
- Nominal/seller FOV or baseline never substitutes for promoted calibration.
- Camera A/B are not silently renamed physical left/right.
- Invalid disparity is never converted into a finite fake depth.
- A rejected normalized observation produces no plausible depth product.
- `unknown` synchronization stays unknown even when policy permits synthetic/replay processing.
- Visualization is not numeric geometry.
- Depth is a derived product and never overwrites raw observation provenance.
- Replay/fault success proves software disposition, not physical disconnect/reconnect or synchronization behavior.
- GPU acceleration is deferred until profiling identifies a justified bottleneck.
