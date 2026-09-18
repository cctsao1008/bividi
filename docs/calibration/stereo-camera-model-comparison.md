# Stereo camera-model comparison

Status: hardware-independent comparison laboratory for Issue #61. Physical AR0234 model selection remains pending measured #35/#8 sessions.

## Purpose

The delivered lens must not be classified from a seller FOV label. Bividi therefore compares plausible projection/distortion models on exactly the same hash-bound stereo session.

```text
same #8 stereo session + same target
                ↓
       detect common ChArUco evidence
                ↓
    ┌───────────┼───────────────────┐
    ↓           ↓                   ↓
opencv5   opencv-rational   opencv-fisheye4
    └───────────┼───────────────────┘
                ↓
 fit + edge + epipolar + usable-map evidence
                ↓
 explicit named selection policy
                ↓
 selected model candidate
```

No candidate is selected automatically from minimum training RMS.

## Command

```bash
bividi-calib stereo model-compare stereo-session.json \
  --output model-comparison.json \
  --markdown model-comparison.md
```

Default candidates are:

```text
opencv5
opencv-rational
opencv-fisheye4
```

A deliberate subset can be compared with `--models`, but at least two distinct models are required.

The default output selection status is:

```text
INSUFFICIENT_EVIDENCE_NO_SELECTION_POLICY
```

To record an intentional selection, both fields are required:

```bash
bividi-calib stereo model-compare stereo-session.json \
  --select-model opencv-rational \
  --policy-source lab/ar0234-optics-model-policy-v1 \
  --output model-comparison.json
```

This records `SELECTED_BY_EXPLICIT_POLICY`; it does not imply that the policy limits are correct, that the chosen calibration has been promoted, or that physical accuracy has been validated.

## Candidate implementations

`opencv5` and `opencv-rational` use the existing #8 pinhole/OpenCV path. The rational candidate enables `CALIB_RATIONAL_MODEL`; current `opencv5` behavior remains the default #8 solve and is not changed by this laboratory.

`opencv-fisheye4` uses the separate OpenCV fisheye API surface:

```text
cv2.fisheye.calibrate
cv2.fisheye.stereoCalibrate
cv2.fisheye.stereoRectify
cv2.fisheye.undistortPoints
cv2.fisheye.initUndistortRectifyMap
```

The fisheye path is available for evaluation only. Its existence does not assert that the purchased nominal-100° lens is fisheye.

## Comparison evidence

Each candidate records:

- mono calibration RMS and per-view RMS for camera A/B;
- outer-image-quartile reprojection distribution;
- stereo RMS, `R`, `T`, baseline, and common-pair count;
- rectified vertical epipolar residual distribution;
- valid rectification-map fraction for camera A/B;
- solved `K`, `D`, projection family, and distortion-parameter count.

The outer-image metric is defined from the raw detected target points whose image-center radius lies in the dataset's outermost quartile. It is descriptive evidence, not a quality threshold. Using a quartile avoids inventing a fixed FOV/pixel radius from seller optics.

The valid-map fraction is computed consistently from the actual remap coordinates for all model families. This is used instead of pretending that the regular OpenCV ROI returned by pinhole `stereoRectify` has an identical semantic equivalent in the fisheye API.

## Evidence binding

The report schema is:

```text
bividi.calibration.stereo_model_comparison.v1
```

The report binds:

```text
session path + SHA-256 + session_id + provenance kind
target path + SHA-256 + target_id/family
device/capture identity
OpenCV/tool revision
all compared candidate results
selection policy source, if any
```

All candidates are solved in one invocation from the same verified #8 session; the tool therefore cannot silently compare different source datasets.

## What the metrics do not prove

```text
lower training RMS
    != better physical model

single-session edge residual
    != cross-session stability

synthetic solver recovery
    != measured AR0234 optics

model selection
    != calibration promotion
```

Independent-session repeatability remains owned by the #8 repeatability evidence. A later #61 promotion-binding slice should attach the selected model-comparison report to the promoted stereo artifact/evidence graph without weakening existing #8 provenance gates.

Held-out/cross-session evaluation should be added when real sessions exist. The v1 laboratory deliberately does not fabricate held-out evidence from duplicated synthetic views.

## CI

Dependency-light CI tests selection semantics and proves that lower RMS alone does not auto-select a model. The OpenCV job separately exercises:

- `opencv5` synthetic pinhole solve/rectification;
- `opencv-rational` synthetic pinhole solve/rectification;
- `opencv-fisheye4` synthetic fisheye solve/rectification.

These tests validate software paths and conventions only. They do not select the AR0234 physical lens model.
