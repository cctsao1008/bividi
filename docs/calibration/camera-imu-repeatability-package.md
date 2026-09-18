# Package-native camera↔IMU repeatability evidence

Owner: Issue #115 under #47  
Upstream: package-native Kalibr candidate import (#109), solver quality (#111), temporal review (#113)  
Status: package migration only; pairwise consistency is repeatability evidence, not physical correctness or consensus calibration

## Command surface

The consolidated repeatability command is package-native:

```bash
bividi-calib camera-imu repeatability --self-test
```

It routes through:

```text
bividi.calibration.camera_imu_repeatability_command
        ↓
bividi.calibration.camera_imu_repeatability
        ↓
bividi.calibration.artifact_validator
```

The historical source-tree entry point remains a thin compatibility wrapper:

```text
tools/compare_camera_imu_calibrations.py
```

No Bividi source checkout is required by the installed command. The historical sibling import of `tools/validate_calibration_artifact.py` is replaced with the package-native validator.

## Input and report boundary

The comparator consumes two or more independently produced:

```text
bividi.calibration.camera_imu.v1
```

artifacts and produces repeatability evidence using schema:

```text
bividi.calibration.camera_imu_repeatability.v1
```

The report deliberately contains pairwise comparisons and per-run worst disagreement. It does not contain an averaged transform, consensus calibration, selected winner, or promoted artifact.

## Compatibility contract before comparison

Every source artifact is first structurally validated. The comparator then requires repeated solves to describe the same comparison contract, including:

```text
device model and serial
camera id and frame
camera width and height
camera mode id
IMU model and frame
transform from/to frames
translation unit
right-handed/frame-axis declarations
time-offset definition
camera timestamp reference
external solver backend
```

The exact time-offset definition remains:

```text
t_imu_s = t_camera_reference_s + offset_s
```

Different external backend revisions are rejected by default. The operator may explicitly pass:

```bash
--allow-backend-revision-mismatch
```

only when intentionally studying solver-version effects. Allowing the mismatch does not make those runs equivalent; it merely permits that explicit experiment.

## Distinct-run requirement

Repeatability requires distinct solve outputs. Each source artifact is SHA-256 identified, and duplicate artifact content is rejected.

This prevents accidentally counting the same solve twice as evidence of repeatability.

## Preserved pairwise math

For every unordered pair of runs `i,j`, the comparator computes the relative transform:

```text
ΔT_ij = T_i * inverse(T_j)
```

and reports:

```text
translation_delta_mm
rotation_delta_deg
time_offset_delta_us
```

Translation disagreement is the Euclidean norm of the relative-transform translation, converted metres→millimetres.

Rotation disagreement is derived from the relative rotation matrix using the clamped trace relation:

```text
θ = acos(clamp((trace(R)-1)/2, -1, 1))
```

and converted to degrees.

Time disagreement is:

```text
abs(offset_i_s - offset_j_s) * 1e6
```

in microseconds, after compatibility has already established the same time-offset definition and camera timestamp semantic.

No component-wise Euler subtraction, transform averaging, or alternate time-sign convention is introduced.

## Preserved summaries

For translation, rotation, and time-offset disagreement, the report preserves:

```text
count
minimum
maximum
mean
p50
p95
p99
```

It also records each artifact's worst pairwise:

```text
worst_translation_mm
worst_rotation_deg
worst_time_offset_us
```

For three runs there are exactly three unordered pairwise comparisons.

## Explicit gates only

Without numeric gates, status remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

The existing optional gates remain:

```text
--max-pairwise-translation-mm
--max-pairwise-rotation-deg
--max-pairwise-time-offset-us
```

If supplied gates all pass, status is `PASS`. If an explicitly supplied gate fails, status is `FAIL`.

No default threshold is introduced by package migration. Acceptance values must come from product requirements or a reviewed measured baseline.

## Exit-code contract

The historical standalone tool used one process code for domain failures and another for a completed gate FAIL that collided with the consolidated vocabulary. The package adapter normalizes only the process surface:

```text
0  evidence-only or explicit-gate PASS
2  usage/input/schema/hash/compatibility/domain/read/write failure
3  completed explicit-gate FAIL
```

Report schema, status, numerical evidence, and gate semantics are unchanged.

## Interpretation guardrails

Repeatability answers:

```text
How different are repeated solves from one another?
```

It does not answer:

```text
Which solve is physically correct?
What is the true camera↔IMU transform?
What is the true physical time offset?
Should the runs be averaged?
Is the calibration ready for promotion?
Will downstream VIO meet its accuracy target?
```

Therefore:

```text
small pairwise disagreement
    != physical accuracy
    != solver residual quality
    != temporal correctness
    != promotion readiness
```

A tightly clustered set of biased solves can be repeatable and still wrong. Conversely, disagreement can reveal instability without identifying the correct run.

## No consensus estimator

The comparator intentionally does not produce:

```text
mean translation
mean quaternion/rotation
mean time offset
best run
consensus artifact
```

Those would be new estimation/policy semantics and require separate design and validation. Packaging this existing comparator does not introduce them.

## CI boundary

Normal Ubuntu and Windows CI exercise both:

```bash
bividi-calib camera-imu repeatability --self-test
python tools/compare_camera_imu_calibrations.py --self-test
```

without Kalibr, ROS, OpenCV, or numpy. Package-level regression additionally verifies installed routing outside a checkout, package-native artifact validation, three-run pair counting, explicit completed FAIL mapping, specimen incompatibility, duplicate-content rejection, backend-revision override behavior, write-failure normalization, and command-contract metadata.
