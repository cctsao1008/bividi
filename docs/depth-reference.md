# Deterministic Stereo Depth Reference

Status: first hardware-independent implementation slice for Issue #9. The module is an optional OpenCV/calib3d downstream consumer; it is not part of `bividi_core` and does not establish physical AR0234 depth accuracy.

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

The public header is `include/bividi/depth.hpp`; OpenCV types are allowed there because this is explicitly an OpenCV-dependent downstream module rather than a core domain contract.

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

The coordinate frame is carried explicitly as `camera_a_rectified` in this first slice; later observation integration must bind this to the corresponding calibration/source identity rather than infer physical `left/right` labels.

## Deterministic test geometry

The native test uses the same simple geometry chosen for the first #58 synthetic SensorRig:

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
7. display-preview separation from numeric results.

These tolerances are algorithmic regression tolerances for the synthetic fixture, not product acceptance thresholds.

## Next integration slices

The first implementation intentionally stops short of claiming a complete runtime depth product. The high-value next steps are:

```text
#58 generated session
        ↓
#31 ReplaySource
        ↓
#11 SensorObservation stereo-pair selection
        ↓
#9 depth processor
        ↓
derived depth observation / recorder / UI
```

Then use #59 fault recipes to prove that missing camera data, synchronization degradation, sequence discontinuity, and timing faults cause explicit rejection/reset/degraded output rather than silent geometry fabrication.

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
- Visualization is not numeric geometry.
- Depth is a derived product and never overwrites raw observation provenance.
- GPU acceleration is deferred until profiling identifies a justified bottleneck.
