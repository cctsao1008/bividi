# Package-native Kalibr target observation and coverage evidence

Owner: Issue #107 under #47  
Upstream: package-native `camera-imu prepare` (#103)  
Adjacent evidence: package-native `camera-imu excitation` (#105)  
Status: package migration only; real target extraction still requires the external reviewed ETH Kalibr runtime

## Command surfaces

The consolidated commands are package-native:

```bash
bividi-calib camera-imu target-observations --self-test
bividi-calib camera-imu target-coverage --self-test
```

They route through installed command adapters:

```text
camera-imu target-observations
  -> bividi.calibration.kalibr_target_observations_command
  -> bividi.calibration.export_kalibr_target_observations

camera-imu target-coverage
  -> bividi.calibration.kalibr_target_coverage_command
  -> bividi.calibration.analyze_kalibr_target_coverage
```

The historical source-tree entry points remain thin compatibility wrappers:

```text
tools/export_kalibr_target_observations.py
tools/analyze_kalibr_target_coverage.py
```

The implementation module basenames deliberately preserve those historical tool names because the versioned artifacts record `Path(__file__).name` in provenance.

## Target observations: external-runtime boundary

`target-observations` is not a replacement AprilTag detector and does not make Kalibr a Bividi runtime dependency. Real extraction still runs inside the reviewed ETH Kalibr environment and lazily imports:

```text
cv2
numpy
aslam_cv
aslam_cameras_april
kalibr_common
```

The reviewed Kalibr revision remains:

```text
1f60227442d25e36365ef5f72cd80b9666d73467
```

A different revision is rejected unless the operator explicitly passes:

```bash
--allow-unreviewed-kalibr-revision
```

That option is an explicit review escape hatch, not silent compatibility.

Real extraction continues to use Kalibr's own `GridDetector` and `GridCalibrationTargetObservation` APIs. It preserves the exact stereo frame-identity requirement, AprilGrid-only target construction, Kalibr detector options, returned corner IDs/image coordinates, image-dimension consistency checks, and camera topology names `camera_a` / `camera_b` without inferring physical left/right.

Outputs remain:

```text
*.target-detections.csv
*.target-corners.csv
*.target-observations.json
```

with schema:

```text
bividi.calibration.kalibr_target_observations.v1
```

The manifest keeps SHA-256 binding to the prepared session, staged camera indexes, camchain, target YAML, detections CSV, and corners CSV.

Successful export is observation evidence only. It owns no PASS/FAIL acceptance disposition.

## Target coverage: dependency-free evidence boundary

`target-coverage` consumes only the exported observation manifest and its SHA-bound CSV artifacts. It does not redetect corners and needs no Kalibr/OpenCV runtime.

The output schema remains:

```text
bividi.calibration.kalibr_target_coverage.v1
```

The preserved evidence includes:

```text
per-camera detection fraction
unique target-corner fraction
normalized image-plane bounds
global convex-hull area fraction
per-frame target bounding-box area distribution
centroid X/Y span
scale-proxy ratio
stereo joint-detection fraction
common target-corner IDs per joint detection
```

Normalized coordinates remain `x/(width-1), y/(height-1)`. Bounding-box area remains only a scale proxy; perspective and clipping also affect it.

Without explicit numeric gates the report remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Explicit operator gates may produce `PASS` or `FAIL`. No default target-coverage threshold is introduced by package migration.

## Exit-code contract

The package command vocabulary is:

```text
0  successful / non-failing completion
2  usage, input, schema, hash, runtime, domain, or write failure
3  completed evaluated FAIL only
```

Therefore:

```text
target-observations: 0 or 2; never manufactures 3
target-coverage:     0 evidence-only/PASS, 2 domain/input failure, 3 completed explicit-gate FAIL
```

This process-level normalization does not change artifact/report status or numerical evidence semantics.

## Interpretation guardrails

Target detection and image-plane coverage are separate evidence classes from dynamic inertial excitation, solver residual quality, camera↔IMU temporal correctness, repeated-session stability, and physical calibration accuracy.

In particular:

```text
good image-plane coverage
  != formal parameter observability
  != small solver residuals
  != correct T_cam_imu
  != correct camera↔IMU time offset
  != downstream VIO accuracy
```

Package migration preserves those boundaries. It does not add a new calibration claim, threshold, detector, or runtime dependency.

## CI boundary

Normal Ubuntu/Windows CI runs both installed `--self-test` paths and both legacy wrapper `--self-test` paths without installing Kalibr. The observation self-test exercises the dependency-free contract helpers only; real extraction remains an external-environment integration step.
