# Package-native Kalibr camera↔IMU candidate import

Owner: Issue #109 under #47  
Upstream: package-native dynamic-session staging (#103) and external Kalibr solve  
Downstream: solver-quality, temporal review, repeatability, and promotion evidence  
Status: package migration only; imported transform/time shift remain candidate solver results

## Command surface

The consolidated import command is package-native:

```bash
bividi-calib camera-imu import-kalibr --self-test
```

It routes through:

```text
bividi.calibration.kalibr_camera_imu_import_command
        ↓
bividi.calibration.kalibr_camera_imu_import
        ↓
bividi.calibration.artifact_validator
```

The historical source-tree entry point remains a thin compatibility wrapper:

```text
tools/import_kalibr_camera_imu.py
```

No source checkout is required by the installed command. The previous sibling-tool import of `tools/validate_calibration_artifact.py` is removed; artifact validation now uses the already package-native validator directly.

## Input and output boundary

The importer consumes:

```text
prepared bividi.calibration.kalibr_dynamic_session.v1 session.json
+
Kalibr result camchain YAML containing selected camera T_cam_imu and timeshift_cam_imu
+
explicit operator camera-axis convention and calibration id
```

It produces:

```text
bividi.calibration.camera_imu.v1 candidate artifact
+
bividi.calibration.kalibr_camera_imu_import.v1 import sidecar
```

The sidecar status remains:

```text
imported_candidate_requires_review
```

That status is intentional. Import is a format/provenance boundary, not calibration acceptance.

## Preserved transform and time semantics

Camera topology remains:

```text
cam0 -> camera_a
cam1 -> camera_b
```

The importer does not rename either camera left/right.

Kalibr `T_cam_imu` is preserved as the transform from the IMU frame to the selected camera frame:

```text
transform.from_frame = imu_reference.frame
transform.to_frame   = selected camera frame
translation_unit     = m
```

No silent inversion is performed.

The camera↔IMU time offset remains defined exactly as:

```text
t_imu_s = t_camera_reference_s + offset_s
```

and the artifact records the prepared session's explicit camera timestamp semantic:

```text
exposure_start
exposure_midpoint
or
exposure_end
```

No zero offset, frame timestamp meaning, or alternate sign convention is inferred.

## Provenance and integrity

The importer preserves SHA-256 verification of the prepared session's bound IMU calibration and dynamic capture, checks the expected schemas, and requires the session/IMU specimen serial to match.

Imported provenance continues to record:

```text
kind = imported
tool = import_kalibr_camera_imu.py
tool_version = 1
external_backend = ethz-asl/kalibr
external_backend_revision = revision recorded by the prepared session
```

An optional external container identifier is retained when supplied. An optional solver report is SHA-256 bound into the import sidecar and noted in the candidate artifact, but attaching a solver report does not promote the candidate.

The constructed `bividi.calibration.camera_imu.v1` artifact is checked with `bividi.calibration.artifact_validator`, including rigid-transform invariants, frame consistency, time-offset definition, camera timestamp reference, provenance structure, and required metadata.

## Exit-code contract

The package command follows the frozen calibration vocabulary:

```text
0  successful candidate import
2  usage/input/schema/hash/domain/validation/write failure
3  reserved for completed evaluated FAIL and therefore not used by this importer
```

Historically the source tool returned `3` for import/domain failures. The package command adapter normalizes that process-level collision to `2`; artifact content, transform/time values, validation rules, and candidate status are unchanged.

## Interpretation boundary

A successful import means only that a provenance-bound Kalibr result was parsed, mapped into the explicit Bividi frame/time contract, and structurally validated.

It does **not** establish:

```text
solver residual quality
camera↔IMU temporal correctness against device-domain evidence
independent-session repeatability
physical transform accuracy
downstream VIO accuracy
promotion readiness
```

Those remain separate evidence classes. In particular:

```text
valid imported T_cam_imu + timeshift_cam_imu
    != accepted camera↔IMU calibration
```

## CI boundary

Normal Ubuntu and Windows CI can run both the installed `--self-test` path and the direct compatibility wrapper without ROS or Kalibr installed. The importer parses a synthetic Kalibr-style YAML fixture and validates the resulting candidate with the package-native artifact validator.

The synthetic self-test preserves the characterized checks for transform direction, translation, time-shift sign/value, camera timestamp semantic, candidate sidecar status, and rejection of malformed result YAML.
