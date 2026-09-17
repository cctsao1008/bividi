# Stereo calibration readiness (#8)

Issue #8 is the geometry gate for metric stereo depth (#9) and one of the two calibration gates for live stereo-inertial VIO (#46). The active reference device is the DECXIN AR0234 stereo + IMU module, but the calibration contracts deliberately use `camera_a` / `camera_b`, not vendor transport types or assumed left/right names.

The governing rule is:

> **Target first. Dataset evidence second. Solve third. Repeatability fourth. Promotion last.**

A calibration solver returning numbers is not enough. Bividi keeps the physical target, specimen/mode identity, dataset quality, reprojection/epipolar evidence, physical baseline sanity, independent repeatability, and final promotion provenance separate so that a weak evidence class cannot be hidden by a low aggregate RMS.

## Tooling stack

```text
stereo_calibration_workbench.py
  target      target definition + ChArUco render / AprilGrid Kalibr YAML
  session     deterministic paired-image session manifest
  inspect     target detection + corner/image-plane/quality evidence
  solve       mono intrinsics + fixed-intrinsic stereo solve + rectification
  validate    dependency-free artifact semantics
  rectify     rectified visual inspection pair + epipolar guide lines

review_calibration_target_scale.py
  physical print-scale evidence

review_stereo_geometry.py
  calibrated baseline vs physical measurement

compare_stereo_calibrations.py
  independent-solve repeatability

stereo_calibration_provenance.py
  final hash-bound integrity/review/promotion gate

plan_stereo_calibration_campaign.py
  specimen-specific physical campaign + RUNBOOK.md + completeness audit
```

Python OpenCV + NumPy are required only for rendering, image inspection, solve, and rectification. Contract validation, campaign planning, target-scale review, geometry review, repeatability comparison, and final promotion are standard-library-only. This keeps calibration tooling out of Bividi Core and does not add ROS/Kalibr to the runtime.

## 1. Physical calibration target

The native path uses ChArUco because it combines robust marker identification with subpixel chessboard intersections and maps cleanly into OpenCV calibration. AprilGrid remains an explicit separate target family for optional ETH Kalibr interoperability and #47 camera↔IMU work.

Example ChArUco target definition and printable image:

```bash
python tools/stereo_calibration_workbench.py target \
  --family charuco \
  --target-id ar0234-charuco-v1 \
  --squares-x 8 --squares-y 6 \
  --square-mm 30 --marker-mm 22 \
  --dictionary DICT_5X5_1000 \
  --output target.json \
  --render target.png
```

The target artifact records the physical dimensions. Printing is not considered verified merely because the requested DPI or page size looked correct. Measure the printed board physically and record the evidence:

```bash
python tools/review_calibration_target_scale.py target.json \
  --measured-width-mm <measured> \
  --measurement-source "caliper asset ID / operator / date" \
  --method "caliper across outer board width" \
  --max-abs-delta-percent <policy-limit> \
  --policy-source <lab-policy> \
  --output target-scale.json
```

Without an explicit limit the review remains `EVIDENCE_ONLY_NO_THRESHOLDS`.

### AprilGrid interoperability

AprilGrid is not silently converted into ChArUco. Generate its physical definition separately and, when needed, export Kalibr target metadata:

```bash
python tools/stereo_calibration_workbench.py target \
  --family aprilgrid \
  --target-id ar0234-aprilgrid-v1 \
  --tag-rows 6 --tag-cols 6 \
  --tag-size-mm 36 --tag-spacing-ratio 0.3 \
  --output aprilgrid.json \
  --kalibr-yaml target.yaml
```

The native workbench does not invent AprilTag artwork. Printed AprilGrid generation remains an external, separately verified artifact; the Bividi metadata still records exact tag geometry.

## 2. Capture/session contract

Large image datasets stay outside normal Git history. One session uses paired camera directories plus a versioned manifest:

```text
session-01/
  camera_a/
  camera_b/
  session.json
  dataset-quality.json
  stereo-calibration.json
  geometry-review.json
  rectified-sample.png
```

The session manifest binds:

```text
specimen model + serial
Nori device/mode identity
pixel format and image geometry
camera_a / camera_b identity
#35 camera-mapping evidence when available
target path + SHA-256
paired image filenames
synthetic / measured / imported provenance
```

Build it from already captured paired images:

```bash
python tools/stereo_calibration_workbench.py session \
  --session-id ar0234-stereo-01 \
  --target target.json \
  --camera-a-dir session-01/camera_a \
  --camera-b-dir session-01/camera_b \
  --model DECXIN-AR0234 \
  --serial <physical-serial> \
  --device 0 --mode 0 \
  --pixel-format <actual-format> \
  --width <camera-width> --height <camera-height> \
  --camera-mapping-evidence "#35 physical A/B mapping record" \
  --provenance measured \
  --output session-01/session.json
```

The builder requires matching filenames by default and refuses unpaired data unless `--allow-unpaired` is explicit.

## 3. Capture procedure

Do not collect twenty nearly identical frontal center images. A useful stereo calibration session deliberately varies the target through the observable image/pose space:

- center, four quadrants, near all image edges and corners;
- multiple apparent scales / board distances;
- positive and negative tilt around both board axes;
- roll variation;
- target visible in both cameras for stereo observations;
- enough stillness/exposure quality to avoid avoidable blur;
- lighting that avoids severe clipping while preserving usable contrast.

Keep poor frames visible to the inspection stage rather than silently deleting evidence. Re-capture a weak dataset instead of forcing the solver to accept it.

## 4. Dataset quality and corner coverage

`inspect` reuses the same ChArUco target definition and reports, per camera and stereo pair:

```text
detection / corner IDs
common stereo corner IDs
per-frame convex-hull image coverage
whole-session image-plane hull coverage
target-corner ID coverage
centroid x/y span
Laplacian-variance sharpness proxy
black/white clipping fraction
valid stereo pair count
```

Example:

```bash
python tools/stereo_calibration_workbench.py inspect session-01/session.json \
  --output session-01/dataset-quality.json
```

Default status is `EVIDENCE_ONLY_NO_THRESHOLDS`. Lab/product requirements may enable explicit gates, for example minimum valid pairs, minimum common corners, image-plane hull coverage, sharpness, or clipping. The workbench never supplies universal defaults for those limits.

Coverage, sharpness, and clipping are dataset evidence. They are not independent proof of calibration accuracy.

## 5. Intrinsic + stereo solve

The native offline solve performs:

```text
camera_a ChArUco observations -> mono K/D
camera_b ChArUco observations -> mono K/D
common stereo corner IDs      -> stereoCalibrate(CALIB_FIX_INTRINSIC)
                             -> R/T/E/F
                             -> stereoRectify
                             -> R1/R2/P1/P2/Q + valid ROIs
                             -> rectified vertical residual distribution
```

Example:

```bash
python tools/stereo_calibration_workbench.py solve session-01/session.json \
  --calibration-id ar0234-stereo-01 \
  --provenance measured \
  --distortion-model opencv5 \
  --output session-01/stereo-calibration.json
```

`opencv-rational` is also available for deliberate model comparison. Do not infer the camera model from the seller's `100°` product label.

The artifact contains:

```text
K/D per camera
mono RMS + per-view reprojection RMS
calibration-derived pinhole FOV approximation
R/T + baseline + E/F
stereo RMS
R1/R2/P1/P2/Q
valid rectification ROIs
vertical epipolar absolute-error distribution
source session + target hashes
specimen/mode/provenance
```

Optional numeric gates for mono RMS, stereo RMS, and rectified epipolar p95 must be supplied explicitly with a named policy source.

## 6. Artifact validation

The dependency-free semantic validator checks matrix shapes, positive focal lengths, a proper right-handed stereo rotation, non-zero translation/baseline, rectification matrix shapes, and explicit provenance kind.

```bash
python tools/stereo_calibration_workbench.py validate session-01/stereo-calibration.json
```

This is structural/semantic validation, not a substitute for dataset or fit-quality review.

## 7. Rectification inspector

Render a rectified camera A/B pair with shared horizontal guides:

```bash
python tools/stereo_calibration_workbench.py rectify \
  --calibration session-01/stereo-calibration.json \
  --camera-a session-01/camera_a/<frame>.png \
  --camera-b session-01/camera_b/<frame>.png \
  --output session-01/rectified-sample.png
```

The picture is debugging evidence. Acceptance still uses the numeric vertical epipolar residuals stored by the solve.

## 8. Physical stereo geometry sanity

Compare the recovered `||T||` with an explicit physical baseline measurement:

```bash
python tools/review_stereo_geometry.py session-01/stereo-calibration.json \
  --physical-baseline-mm <measured> \
  --measurement-source "fixture/caliper/operator/date" \
  --method "optical-center proxy / mechanical reference description" \
  --output session-01/geometry-review.json
```

A mechanical measurement is only a baseline sanity check. It does not independently establish full 6DoF camera extrinsics, and measurement/fixture uncertainty should be retained when material.

## 9. Independent repeatability

A single successful solve is not a repeatability claim. Capture and solve at least two independent sessions, then compare:

```bash
python tools/compare_stereo_calibrations.py \
  sessions/session-01/stereo-calibration.json \
  sessions/session-02/stereo-calibration.json \
  sessions/session-03/stereo-calibration.json \
  --output final/repeatability.json
```

The comparator first rejects incompatible specimen/mode/target/camera-model inputs, then reports pairwise/max deltas for:

```text
stereo rotation angle
baseline
translation direction
fx/fy
principal point
```

Default is evidence-only. Promotion requires explicit repeatability limits from the lab/product policy.

## 10. Final artifact promotion

The promotion gate hash-binds these evidence classes:

```text
target definition
target physical scale review
selected stereo session
dataset quality report
selected stereo calibration artifact
physical geometry review
independent repeatability report
```

Profiles:

```text
integrity   hashes + schemas + cross-links
review      integrity + no quality evidence may be FAIL
promotion   review + measured provenance
            + #35 camera mapping evidence
            + every quality report explicit PASS
            + every PASS has explicit gates
            + named lab/product policy source
```

Build:

```bash
python tools/stereo_calibration_provenance.py build \
  --target target/target.json \
  --target-scale target/target-scale.json \
  --session sessions/session-01/session.json \
  --dataset-quality sessions/session-01/dataset-quality.json \
  --calibration sessions/session-01/stereo-calibration.json \
  --geometry-review sessions/session-01/geometry-review.json \
  --repeatability final/repeatability.json \
  --profile promotion \
  --policy-source <lab-policy> \
  --output final/stereo-evidence.json
```

`PROMOTION_READY` is a controlled evidence disposition, not independent proof that the physical calibration is perfect.

## 11. Specimen-specific campaign planner

Initialize the whole live-hardware runbook before touching the specimen:

```bash
python tools/plan_stereo_calibration_campaign.py init ar0234-stereo-001 \
  --campaign-id ar0234-stereo-001 \
  --model DECXIN-AR0234 \
  --serial <physical-serial> \
  --device 0 --mode 0 \
  --pixel-format <actual-format> \
  --width <width> --height <height> \
  --camera-mapping-evidence "#35 mapping record" \
  --session-count 3
```

This produces `campaign.json` and `RUNBOOK.md`. Audit expected artifacts without pretending presence is quality:

```bash
python tools/plan_stereo_calibration_campaign.py audit \
  ar0234-stereo-001/campaign.json \
  --output ar0234-stereo-001/audit.json
```

States are `complete`, `ready`, and `blocked`. The campaign audit checks only expected file presence/top-level schema. Hash, quality, and promotion policy remain owned by the individual evidence tools.

## Kalibr boundary

Kalibr remains an optional reference solver. AprilGrid metadata can be generated from the target tool, and a representative stereo dataset may be exported/run externally for an independent comparison. That result does not replace the Bividi artifact contract and ROS/Kalibr does not become a dependency of #9 depth or the normal runtime.

The exact Kalibr corner/target semantics used by #47 should be reused for a future automated stereo reference adapter rather than re-detecting the same AprilGrid through an unrelated detector.

## What is still physical-hardware blocked

The tooling can be CI-tested now, but these claims remain unavailable until the delivered AR0234 specimen is exercised:

```text
physical camera_a / camera_b orientation
actual live mode / pixel format used for calibration
verified printed target scale used in the lab
real target coverage and image quality
measured K/D for both cameras
measured R/T/baseline
real rectified epipolar residuals
mechanical baseline cross-check
independent-session repeatability
policy-gated PROMOTION_READY evidence bundle
```

Until then, #9 may use explicitly synthetic calibration for software development but must not claim measured metric depth, and #46 must not claim measured live VIO accuracy.
