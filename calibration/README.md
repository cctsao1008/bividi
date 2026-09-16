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
```

The schemas are intentionally independent of OpenCV, ROS, Kalibr, DECXIN/Nori transport structs, and runtime backend types. External solver formats are adapters, not Bividi's persistent public calibration schema.

## Evidence before artifact promotion

Issue #47 deliberately separates measurement evidence from a promoted calibration artifact. Current hardware-independent tooling includes:

```text
bividi-nori-imu-record              lossless raw IMU + ES/EE trace

tools/audit_imu_timing.py           device-time cadence / gap / camera↔IMU timing audit
tools/analyze_imu_stationary.py     stationary raw bias/variance evidence
tools/analyze_imu_allan.py          long-run Allan/noise characterization
tools/analyze_imu_six_position.py   six-pose accelerometer axis/sign/scale sanity
tools/export_kalibr_imu.py          reviewed IMU artifact -> Kalibr imu.yaml adapter
```

Analyzer outputs are evidence/candidates until specimen identity, capture configuration, frame convention, units, method, and review provenance justify promotion into a versioned artifact. In particular, the six-position affine gravity model and Allan-derived Kalibr candidates are not automatically written into `bividi.calibration.imu.v1`.

## Provenance is mandatory

Every artifact must state whether its values are:

```text
synthetic
measured
imported
```

Synthetic examples are useful for schema/CI work but are not specimen measurements. Imported results must identify the external backend; solver/container/revision information should be retained when available.

Unknown or unmeasured calibration terms stay absent. Do not convert an unknown bias, scale, extrinsic, or time offset into a numeric zero merely to fill a field.

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

Validate an artifact with:

```bash
python tools/validate_calibration_artifact.py calibration/examples/imu-synthetic-v1.json
python tools/validate_calibration_artifact.py calibration/examples/camera-imu-synthetic-v1.json
```

The dependency-free validator is used by normal CI. The JSON Schema files remain the durable machine-readable contract and may additionally be checked with a standards-compliant JSON Schema validator in environments that provide one.

## Artifact retention

A measured artifact should identify enough context to reject accidental reuse across incompatible hardware or modes, including device identity/serial, sensor model, frame convention, calibration/session identity, tool revision/provenance, and the relevant capture mode or rate where applicable.

Large source datasets remain external to normal Git history. Keep stable hashes or external references when reproducibility requires them.

Related: #8, #35, #47.
