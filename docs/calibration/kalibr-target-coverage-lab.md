# Kalibr AprilGrid Target / Image-Plane Coverage Laboratory

Owner: Issue #47  
Upstream: `bividi.calibration.kalibr_dynamic_session.v1`  
Outputs: exact Kalibr observation export + dependency-free coverage evidence  
Status: tooling implemented; physical AR0234 target-coverage measurements pending

## Purpose

Camera↔IMU calibration needs two different excitation classes:

```text
inertial motion excitation
    -> analyze_camera_imu_excitation.py

visual target / image-plane excitation
    -> export_kalibr_target_observations.py
    -> analyze_kalibr_target_coverage.py
```

A session can contain strong multi-axis IMU motion while the calibration board stays near the image centre at nearly one scale. The reverse is also possible. Neither evidence class replaces the other.

This laboratory therefore measures the **actual AprilGrid observations used by the pinned ETH Zurich Kalibr detector path** rather than running a second independent AprilTag/OpenCV detector.

## Why the detector is reused instead of reimplemented

At reviewed Kalibr revision:

```text
1f60227442d25e36365ef5f72cd80b9666d73467
```

`kalibr_common.TargetExtractor.extractCornersFromDataset()` calls `GridDetector.findTarget()` for each image and retains successful `GridCalibrationTargetObservation` objects.

The Python binding exposes the exact observation surfaces needed here:

```text
GridCalibrationTargetObservation.getCornersImageFrame()
GridCalibrationTargetObservation.getCornersIdx()
```

The camera↔IMU path configures AprilGrid detection in `IccSensors.IccCamera.setupCalibrationTarget()` using:

```text
AprilgridOptions.minTagsForValidObs = max(tagRows, tagCols) + 1
GridDetectorOptions.filterCornerOutliers = True
```

The Bividi adapter mirrors that reviewed setup. It does **not** estimate corners independently.

This is intentional: a second detector could disagree about subpixel corner location, accepted tags, outlier filtering, or corner IDs and would then measure a target-coverage dataset that is not identical to the one Kalibr optimizes.

## Two-layer boundary

The external-runtime dependency stays isolated:

```text
prepared Bividi dynamic session
        |
        |  inside pinned Kalibr environment
        v
export_kalibr_target_observations.py
        |
        |  neutral CSV + JSON evidence
        v
analyze_kalibr_target_coverage.py
        |
        |  Python standard library only
        v
coverage JSON + Markdown report
```

`export_kalibr_target_observations.py` lazily imports:

```text
kalibr_common
aslam_cv
aslam_cameras_april
numpy
cv2
```

Normal Bividi CI does not install Kalibr. Its self-test verifies the adapter's dependency-free staging/identity helpers. The coverage analyzer is fully dependency-free and is exercised on Windows and Linux CI.

## Export exact Kalibr observations

Run the adapter in the reviewed Kalibr environment with the Bividi repository mounted/available:

```bash
python tools/export_kalibr_target_observations.py \
  ar0234_kalibr_001/session.json \
  --output-prefix ar0234_kalibr_001/target
```

It reads the prepared session's staged:

```text
camera_a.csv
camera_b.csv
camchain.yaml
target.yaml
```

Before detection it requires camera A/B timestamp, frame-index, and frame-sequence identities to match exactly.

For each staged image it writes one detection row, including failed detections. Successful detections additionally write one row per Kalibr corner.

Artifacts:

```text
target.target-detections.csv
    one row per camera frame
    success / corner count / image dimensions
    detected-corner bbox + centroid

target.target-corners.csv
    one row per accepted Kalibr corner
    camera / timestamp / frame identity
    Kalibr corner ID
    x/y pixel coordinate

target.target-observations.json
    exact source hashes
    exact output hashes
    Kalibr revision
    detector setup contract
    target metadata and Kalibr target corner count
```

The target corner count comes from the Kalibr target object itself (`grid.size()`); Bividi does not infer it from a hand-maintained AprilGrid indexing formula.

### Revision guard

The adapter rejects an unreviewed Kalibr revision by default.

`--allow-unreviewed-kalibr-revision` exists only for deliberate investigation after detector/API changes have been reviewed. It is not a routine compatibility switch.

## Analyze coverage

The second stage has no Kalibr dependency:

```bash
python tools/analyze_kalibr_target_coverage.py \
  ar0234_kalibr_001/target.target-observations.json \
  --output-prefix ar0234_kalibr_001/target
```

Outputs:

```text
target.target-coverage.json
target.target-coverage.md
```

The analyzer re-verifies the SHA-256 of both exported CSV files before using them.

## Metrics

### Per-camera detection completeness

For `camera_a` and `camera_b`:

```text
successful frames / staged frames
observed corners per successful frame
unique Kalibr corner IDs seen
unique corner IDs / target corner count
```

The unique-corner fraction is **target-space coverage evidence**. It answers whether the session repeatedly saw only a subset of the board.

### Image-plane coverage

Every accepted pixel coordinate is normalized as:

```text
x_norm = x / (width - 1)
y_norm = y / (height - 1)
```

The report includes:

```text
global normalized x/y extrema
convex-hull area of all accepted corners over the session
span of per-frame target centroids in X/Y
per-frame target bounding-box area distribution
max/min positive target bounding-box area ratio
```

The global convex-hull area indicates how broadly accepted target observations covered the image plane.

The frame bounding-box area ratio is only a **scale proxy**. Perspective, clipping, target pose, and lens distortion also affect it; it is not a direct range estimate.

### Stereo visual overlap

Because the staged stereo indexes are identity-matched, the analyzer also reports:

```text
fraction of frames where both cameras detect the target
number of common Kalibr corner IDs per joint detection
```

This catches sessions where one camera frequently loses the board even though the other camera is well covered.

## Assessment policy

Default status:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

No universal board-coverage threshold is invented.

When a product requirement or measured-good campaign establishes justified limits, explicit gates may be supplied:

```bash
--min-detection-fraction <0..1>
--min-stereo-detection-fraction <0..1>
--min-target-corner-fraction <0..1>
--min-global-hull-area-fraction <0..1>
--min-centroid-span-x <0..1>
--min-centroid-span-y <0..1>
--min-scale-proxy-ratio <positive>
```

Only supplied gates participate in PASS/FAIL.

## Interpretation boundaries

```text
good AprilGrid image-plane coverage
    != low Kalibr residuals
    != strong IMU excitation
    != formal estimator observability proof
    != physically accurate T_cam_imu / time offset
```

The evidence stack remains deliberately separated:

```text
dynamic session provenance
        +
IMU/camera time coverage + inertial excitation
        +
AprilGrid target/image-plane coverage
        +
Kalibr normalized/physical residual quality
        +
imported T_cam_imu + timeshift
        +
device-time temporal review
        +
independent-session repeatability
        ↓
review / promotion decision
```

## Physical AR0234 procedure

When hardware is available, collect dynamic calibration sessions that deliberately vary both motion and visual target geometry:

```text
rotate around multiple body axes
translate while retaining target visibility
move the board/session footprint through image centre + edges + corners
vary target apparent scale / distance
vary target tilt / perspective
retain simultaneous visibility in both cameras where practical
avoid long static segments dominating the recording
```

The exact numeric acceptance envelope should be established from repeated measured-good sessions and downstream VIO behaviour rather than from arbitrary generic values.

## Guardrails

- The adapter uses Kalibr detections; the analyzer never redetects corners.
- Camera A/B are not renamed physical left/right without #35 evidence.
- A failed Kalibr target detection stays a failed frame; it is not silently removed from the denominator.
- Corner IDs remain Kalibr's target IDs.
- Image-plane metrics are descriptive evidence unless explicit thresholds are supplied.
- No vendor synchronization claim is used as a visual-coverage threshold.
- Physical AR0234 quality remains unproven until measured sessions are run.

Related: #8, #35, #47, #46.
