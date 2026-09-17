# Calibration artifacts

This directory contains small, versioned calibration contracts and examples. Large calibration image/video/IMU datasets do not belong in ordinary Git history by default.

Two calibration workstreams own different artifact families:

```text
Issue #8   camera / stereo geometry
Issue #47  IMU + camera↔IMU calibration
```

## Current schemas

```text
schemas/imu-calibration-v1.schema.json
schemas/camera-imu-calibration-v1.schema.json
schemas/imu-calibration-session-v1.schema.json
schemas/kalibr-dynamic-session-v1.schema.json
schemas/kalibr-solver-quality-v1.schema.json
schemas/camera-imu-excitation-v1.schema.json
schemas/kalibr-target-observations-v1.schema.json
schemas/kalibr-target-coverage-v1.schema.json
schemas/camera-imu-evidence-manifest-v1.schema.json
```

The first two schemas are promoted numerical calibration artifacts. The IMU session schema and camera↔IMU evidence manifest are provenance/evidence contracts used around promotion. The Kalibr dynamic-session schema is an **adapter manifest** for one staged external solver input bundle; it is not a promoted camera↔IMU result. The solver-quality, dynamic-excitation, Kalibr target-observation, and target-coverage schemas describe review evidence and likewise are not promoted calibration results. These contracts are intentionally independent of ROS/Kalibr runtime types in Bividi Core. External solver formats remain adapters, not Bividi's persistent public calibration schema.

## Evidence before artifact promotion

Issue #47 deliberately separates measurement evidence from a promoted calibration artifact. Current tooling includes:

```text
bividi-nori-imu-record                    lossless raw IMU + ES/EE trace
bividi-nori-calib-record                  synchronized stereo PNG + raw IMU dynamic trace

tools/audit_imu_timing.py                 device-time cadence / gap / camera↔IMU timing audit
tools/analyze_imu_stationary.py           stationary raw bias/variance evidence
tools/analyze_imu_allan.py                long-run Allan/noise characterization
tools/analyze_imu_six_position.py         six-pose accelerometer axis/sign/scale sanity
tools/analyze_imu_gyro_rotation.py        controlled-turn gyro axis/sign/scale sanity
tools/imu_calibration_provenance.py       session compatibility + SHA-256 promotion gate
tools/analyze_imu_config_consistency.py   declared range/ODR vs measured-response consistency
tools/export_kalibr_imu.py                reviewed IMU artifact -> Kalibr imu.yaml adapter
tools/prepare_kalibr_dynamic_session.py   dynamic trace -> provenance-bound Kalibr staging bundle
tools/write_kalibr_rosbag.py              legacy ROS1 transport for upstream ethz-asl/kalibr
tools/write_ros2_calibration_mcap.py      ROS2 rosbag2/MCAP interoperability adapter
tools/analyze_camera_imu_excitation.py    dynamic time coverage + multi-axis excitation evidence
tools/export_kalibr_target_observations.py exact pinned-Kalibr AprilGrid observation export
tools/analyze_kalibr_target_coverage.py   target-ID/image-plane/stereo visual coverage evidence
tools/import_kalibr_camera_imu.py         strict Kalibr T_cam_imu/time-shift importer
tools/analyze_kalibr_solver_quality.py    Kalibr normalized/physical residual evidence + explicit gates
tools/review_camera_imu_time_offset.py    device-time temporal evidence review
tools/compare_camera_imu_calibrations.py  multi-session spatial/temporal repeatability
tools/camera_imu_calibration_provenance.py final evidence integrity/review/promotion gate
```

Analyzer outputs are evidence/candidates until specimen identity, capture configuration, frame convention, units, method, and review provenance justify promotion into a versioned artifact. In particular, the six-position affine gravity model, controlled-turn gyro sensitivity candidate, Allan-derived noise candidates, staged Kalibr input bundle, dynamic-excitation report, Kalibr target-coverage report, and Kalibr residual-quality report are not automatically promoted calibration values.

## Session provenance gate

`bividi.calibration.imu_session_manifest.v1` binds one compatible IMU calibration campaign before numerical promotion.

The manifest records and verifies:

```text
specimen model + serial
Nori SDK / device / ISP / FPGA versions
camera mode / transport
IMU model + target frame
accelerometer range
gyroscope range
ODR
accelerometer / gyroscope filter declarations
configuration-source provenance
raw trace + recorder-summary SHA-256
analysis report SHA-256 + report schema
synthetic vs measured provenance
```

Recorder-derived device/mode fields are compared across every capture. A serial, SDK/device/ISP/FPGA revision, or camera-mode mismatch blocks one-session composition rather than silently mixing evidence.

The current recorder does not expose a verified ICM-42688 register snapshot, so range/ODR/filter values remain explicit operator-declared experiment metadata. The provenance gate prevents those declarations from disappearing, but it cannot independently prove an incorrect declaration. Promotion therefore requires a meaningful `configuration_source` describing how those settings were verified.

Use:

```bash
python tools/imu_calibration_provenance.py verify \
  <session.manifest.json> \
  --profile promotion
```

The promotion profile requires the complete stationary + Allan + six-position + controlled-rotation evidence set, non-placeholder configuration/device metadata, measured provenance, and unchanged file hashes. A provenance-gate PASS means the evidence bundle is compatible and immutable according to recorded metadata; it does not replace numerical calibration-quality review.

See `docs/calibration/imu-calibration-provenance-gate.md` for role names and creation examples.

## Configuration consistency gate

A provenance manifest proves that evidence belongs to the same **declared** configuration; it does not prove that the declaration matches the physical sensor state.

`tools/analyze_imu_config_consistency.py` closes part of that gap by comparing:

```text
six-position measured counts/g
    vs declared accelerometer range

known-angle controlled-turn gyro sensitivity
    vs declared gyroscope range

device-timestamp effective sample rates
    vs declared ODR
```

The tool re-verifies every bound analysis SHA-256 before using it. By default it is evidence-only and reports measured-vs-declared deltas without inventing acceptance thresholds. Explicit range/ODR tolerances can be supplied later when justified by requirements or measured baselines.

Filter declarations remain provenance only: scale and cadence experiments cannot uniquely identify filter register settings.

See `docs/calibration/imu-config-consistency-lab.md`.

## Kalibr dynamic-session adapter

`bividi.calibration.kalibr_dynamic_session.v1` records one staged dynamic camera↔IMU input bundle.

The live recorder keeps raw evidence lossless:

```text
camera_a/camera_b lossless mono PNG
ES and EE timestamps kept separately
raw IMU counts + extended IMU timestamps
```

`tools/prepare_kalibr_dynamic_session.py` then requires an explicit camera image-time semantic (`exposure_start`, `exposure_midpoint`, or `exposure_end`) and converts raw IMU counts using the hash-bound six-position and known-angle gyro reports. Vendor-demo `±4 g / ±1000 dps` constants are not used as export truth.

The staged bundle contains camera indexes, calibrated `imu0.csv`, `camchain.yaml`, `imu.yaml`, AprilGrid `target.yaml`, `rosbag-recipe.json`, and `session.json`. The preparer verifies camera/IMU specimen identity and hashes all critical sources.

### Transport boundary

The staged bundle is transport-neutral evidence even though the upstream reference solver is not.

```text
Bividi staged session
        |
        +--> tools/write_ros2_calibration_mcap.py
        |       ROS2 rosbag2 + MCAP interoperability / replay
        |
        +--> tools/write_kalibr_rosbag.py
                ROS1 .bag compatibility for upstream ethz-asl/kalibr
```

`tools/write_kalibr_rosbag.py` therefore remains a **legacy external-solver transport adapter**, not the Bividi recording architecture. It lazily imports ROS1 `rosbag`, `rospy`, `sensor_msgs`, and Python OpenCV only when actually writing the upstream Kalibr bag.

`tools/write_ros2_calibration_mcap.py` is the modern ROS2 interoperability path. It lazily imports `rosbag2_py`, ROS2 message serialization, `sensor_msgs`, the rosbag2 MCAP storage plugin, and Python OpenCV. It writes the same staged camera and IMU timestamps into ROS2 message headers and rosbag2 record timestamps without substituting host-arrival time.

Normal Bividi CI runs dependency-free self-tests for both adapters and does not install complete ROS1/ROS2 distributions.

The Kalibr adapter keeps the Bividi time-shift sign contract explicit:

```text
t_imu_s = t_camera_reference_s + offset_s
```

and records Kalibr's `T_ci` direction as `imu0 -> cam_i`. A successful external solve still requires review/import before becoming `bividi.calibration.camera_imu.v1`.

## Dynamic excitation evidence

`tools/analyze_camera_imu_excitation.py` analyzes the already-prepared stereo+IMU session before or alongside the external solve. It SHA-256 binds the staged camera indexes and calibrated IMU CSV, verifies stereo timestamp identity, and reports common time coverage, per-stream cadence, per-axis gyro activity, integrated absolute rotation, specific-force variation, and 3D directionality proxies.

The gyroscope proxy uses the eigenvalue balance of `E[ωωᵀ]`. The accelerometer proxy uses the covariance of whole-session mean-centered specific force. These are excitation summaries, not a Kalibr information matrix and not a formal observability proof. Specific-force variation includes both gravity-direction changes and linear acceleration.

With no operator-supplied procedure limits, status stays `EVIDENCE_ONLY_NO_THRESHOLDS`.

See `docs/calibration/camera-imu-dynamic-excitation.md`.

## Kalibr target / image-plane coverage evidence

`tools/export_kalibr_target_observations.py` runs inside the reviewed Kalibr environment and reuses Kalibr's own `GridDetector.findTarget()` plus `GridCalibrationTargetObservation.getCornersImageFrame()` / `getCornersIdx()` surfaces. This avoids introducing an independent detector whose accepted tags, subpixel locations, outlier filtering, or corner IDs could differ from the data Kalibr actually optimizes.

The exporter mirrors the reviewed camera↔IMU AprilGrid setup, records failed detections rather than dropping them, verifies staged camera A/B frame identity, and writes hash-bound detection/corner CSV evidence. The neutral `bividi.calibration.kalibr_target_observations.v1` manifest records the exact Kalibr revision and detector contract.

`tools/analyze_kalibr_target_coverage.py` is dependency-free. It verifies the exported hashes and reports per-camera detection fraction, unique target-corner coverage, normalized image-plane extrema, global corner convex-hull area, target-centroid span, apparent-scale bounding-box proxies, stereo joint-detection fraction, and common corner IDs.

Default status is `EVIDENCE_ONLY_NO_THRESHOLDS`; product/lab gates are opt-in only. These metrics are visual calibration-session evidence, not formal parameter observability or calibration accuracy.

See `docs/calibration/kalibr-target-coverage-lab.md`.

## Kalibr solver-quality evidence

`tools/analyze_kalibr_solver_quality.py` parses the exact `Normalized Residuals` and `Residuals` sections produced by the pinned ETH Zurich Kalibr `printErrorStatistics()` implementation.

It preserves per-camera reprojection statistics plus IMU gyroscope/accelerometer statistics in both normalized and physical units, computes a derived residual-norm RMS from Kalibr's printed population mean/std, and hash-binds the report to the prepared dynamic-session manifest.

The stereo workflow requires residual evidence for `cam0`, `cam1`, and `imu0`; `no corners` on an expected camera is a structural failure. With no operator-supplied numeric limits the status stays `EVIDENCE_ONLY_NO_THRESHOLDS`. Product- or lab-specific limits may later be supplied explicitly.

Solver residuals measure optimizer fit, not calibration truth. They therefore stay independent from temporal review, repeatability, excitation/observability judgment, target coverage, protocol-level timing evidence, and downstream VIO validation.

## Final camera↔IMU evidence promotion gate

`tools/camera_imu_calibration_provenance.py` closes the hardware-independent #47 tooling chain. It binds the dynamic session, excitation report, exact Kalibr target observations, target-coverage report, solver-quality report, import manifest, candidate calibration artifact, temporal review, repeatability report, and external Kalibr result files into `bividi.calibration.camera_imu_evidence_manifest.v1`.

The gate re-hashes every bound file and verifies nested cross-links: session identity, backend revision, camera mapping, transform frames, timestamp semantics, candidate hash, result YAML/residual text, and membership of the selected candidate in the repeatability campaign.

Profiles have intentionally different meanings:

```text
integrity   hashes/schemas/cross-links only
review      integrity + no component evidence may be FAIL
promotion   review + every quality report must be explicit PASS
            + every PASS must contain explicit gates
            + a named lab/product policy_source is required
```

The promotion gate owns no numerical thresholds. Thresholds remain with the evidence-producing tools; the final gate only verifies that the recorded policy was actually applied and passed. `PROMOTION_READY` is therefore a controlled release disposition, not independent proof of physical calibration accuracy.

See `docs/calibration/camera-imu-evidence-promotion-gate.md`.

See also:

```text
docs/calibration/kalibr-dynamic-session.md
docs/calibration/ros2-mcap-calibration-transport.md
docs/calibration/camera-imu-dynamic-excitation.md
docs/calibration/kalibr-target-coverage-lab.md
docs/calibration/kalibr-result-import-review.md
docs/calibration/kalibr-solver-quality-gate.md
docs/calibration/camera-imu-repeatability.md
```

## Provenance is mandatory

Every promoted numerical artifact must state whether its values are:

```text
synthetic
measured
imported
```

Synthetic examples are useful for schema/CI work but are not specimen measurements. Imported results must identify the external backend; solver/container/revision information should be retained when available.

Unknown or unmeasured calibration terms stay absent. Do not convert an unknown bias, scale, extrinsic, or time offset into a numeric zero merely to fill a field.

For measured IMU artifacts, retain the validated session identity/hash through the existing `provenance.source_session` and `provenance.source_hash` fields so final numbers can be traced back to the exact evidence manifest.

## Coordinate and timing rules

Camera↔IMU artifacts make transform direction explicit with `from_frame` and `to_frame`; v1 uses metres for translation and requires a proper right-handed rigid transform.

The optional camera↔IMU temporal offset has an explicit sign definition:

```text
t_imu_s = t_camera_reference_s + offset_s
```

`camera_time_reference` must also be named (for example exposure start/end). A bare `time_offset` with an implicit epoch or sign convention is not an acceptable artifact.

For six-position accelerometer work, pose labels use target-frame **specific force**, not an ambiguous gravity-vector sign convention. `+X up` means target +X physically points upward and the expected stationary accelerometer target vector is approximately `[+1, 0, 0] g`.

Static gravity does not establish gyroscope axis permutation/sign. Gyro frame validation requires controlled angular motion rather than copying the accelerometer mapping by assumption.

## Synthetic examples

```text
examples/imu-synthetic-v1.json
examples/camera-imu-synthetic-v1.json
```

These files are deliberately marked `synthetic` and include warnings that they must not be reused as DECXIN AR0234 measurements.

Validate a promoted artifact with:

```bash
python tools/validate_calibration_artifact.py calibration/examples/imu-synthetic-v1.json
python tools/validate_calibration_artifact.py calibration/examples/camera-imu-synthetic-v1.json
```

The dependency-free validator is used by normal CI. The JSON Schema files remain the durable machine-readable contract and may additionally be checked with a standards-compliant JSON Schema validator in environments that provide one.

## Artifact retention

A measured artifact should identify enough context to reject accidental reuse across incompatible hardware or modes, including device identity/serial, sensor model, frame convention, calibration/session identity, tool revision/provenance, and the relevant capture mode or rate where applicable.

Large source datasets remain external to normal Git history. Keep the session manifest with the retained evidence bundle; its hashes are the integrity link between the promoted artifact and large external source data.

Related: #8, #11, #35, #47.