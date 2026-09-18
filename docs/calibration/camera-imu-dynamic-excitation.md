# Camera↔IMU Dynamic Excitation Laboratory

Owner: Issue #47  
Upstream: prepared `bividi.calibration.kalibr_dynamic_session.v1`  
Output: `bividi.calibration.camera_imu_excitation.v1` JSON + Markdown evidence  
Status: package-native hardware-independent analyzer implemented; physical AR0234 motion evidence pending

## Purpose

A camera↔IMU calibration can produce numerically small residuals even when the recording does not sufficiently exercise all motion directions. Bividi therefore keeps motion-excitation evidence separate from solver-fit evidence.

```text
prepared dynamic session
  camera_a.csv
  camera_b.csv
  imu0.csv
        ↓
bividi-calib camera-imu excitation
        ↓
time coverage
camera/IMU cadence
angular activity by axis
integrated absolute rotation
specific-force variation
motion-direction balance proxies
        ↓
JSON + Markdown evidence
```

This tool deliberately does **not** claim a formal Kalibr observability proof.

## Package / compatibility mapping

The installed implementation is:

```text
bividi.calibration.camera_imu_excitation
bividi.calibration.camera_imu_excitation_command
```

The historical entry point remains available as a thin compatibility wrapper:

```text
tools/analyze_camera_imu_excitation.py
```

`bividi-calib camera-imu excitation` therefore runs without a Bividi source checkout. Package migration changes only command routing/exit normalization; report math, schema, gates, provenance identity, and interpretation stay unchanged.

The frozen command exits are:

```text
0  evidence-only or explicit PASS
2  usage/input/schema/domain/read/write error
3  completed report FAIL
```

The historical source script used `3` for domain errors and `7` for an evaluated FAIL. The package command adapter corrects that process-level collision without changing report status semantics.

## Why this is a separate evidence class

The following statements are not equivalent:

```text
Kalibr converged
solver residuals are small
motion excites all useful directions
parameters are mathematically observable
calibration is physically accurate
```

`tools/analyze_kalibr_solver_quality.py` addresses optimizer fit. This laboratory addresses whether the staged recording contains broad camera/IMU time coverage and multi-axis inertial motion evidence.

Formal estimator observability depends on the model, trajectory, target geometry, parameterization, and optimization structure. The current tool therefore uses the word **excitation**, not `observability PASS`.

## Input contract

Run it on the `session.json` produced by `bividi-calib camera-imu prepare`:

```bash
bividi-calib camera-imu excitation \
  ar0234_kalibr_001/session.json \
  --output-prefix ar0234_kalibr_001/excitation
```

The analyzer resolves and SHA-256 binds:

```text
session.json
camera_a.csv
camera_b.csv
imu0.csv
```

It rejects non-increasing camera or IMU timestamps and non-finite IMU values.

## Camera and time-coverage evidence

For both camera indexes and the IMU stream the report records:

```text
sample count
first/last timestamp
duration
effective rate
interval min/max/mean/std/P50/P95/P99
```

The staged stereo indexes are expected to represent the same captured frame pairs, so `camera_a` and `camera_b` timestamps must be identical. A mismatch is a structural failure.

The analyzer also computes the common interval among:

```text
camera_a
camera_b
imu0
```

and reports:

```text
shared_duration_s
shared_fraction_of_union
```

No minimum overlap is invented by default.

## Angular excitation

The staged IMU file is already in the Bividi target IMU frame and SI units. For each gyro axis the report records:

```text
signed distribution
absolute-value distribution
RMS
P95 / max magnitude
axis energy fraction
integrated signed rotation
integrated absolute rotation
```

Integration uses the actual staged IMU timestamps and trapezoidal integration:

```text
∫ ω_axis dt
∫ |ω_axis| dt
```

`integrated_abs_rotation_rad` is useful for detecting a trajectory that barely moves one axis even when the session is long.

## Gyro directionality proxy

The analyzer computes the 3×3 second-moment matrix:

```text
E[ω ωᵀ]
```

and its eigenvalues. The normalized eigenvalue fractions summarize how angular activity is distributed over three orthogonal directions.

Examples of interpretation:

```text
fractions ≈ [1, 0, 0]
    → strongly one-dimensional angular activity

fractions with three non-trivial components
    → broader angular-direction excitation
```

This is an **excitation directionality proxy**. It is not a Kalibr Fisher-information matrix and is not a formal parameter-observability metric.

## Specific-force variation

Accelerometer samples contain specific force, including gravity expressed in the moving sensor frame. The tool therefore does not label accelerometer variation as pure translational acceleration.

It computes:

```text
mean specific-force vector
sample - whole-session mean vector
per-axis variation distribution
variation-vector norm
3×3 variation covariance
eigenvalue energy fractions
```

The variation contains both:

```text
gravity direction changes caused by orientation
+
true linear acceleration
```

That is useful excitation evidence for an inertial calibration trajectory, but it must not be interpreted as isolated vehicle translation.

## Target-coverage boundary

The staged camera indexes contain timestamps and image references, but not AprilGrid corner coordinates or image-plane target tracks.

Therefore this tool explicitly reports:

```text
target_detection_coverage = not_evaluated_from_staged_index_csv
```

A trajectory can have strong IMU excitation while the AprilGrid is poorly visible, confined to one image region, blurred, or absent. Target extraction/coverage needs separate evidence.

## Default assessment

With structurally valid input and no explicit numeric requirements:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Bividi does not invent universal motion thresholds. Structural failures such as mismatched stereo timestamps can still produce a completed `FAIL` without numeric gates.

## Optional requirement-based gates

When a physical procedure, validated baseline, or product requirement justifies limits, use explicit gates:

```bash
bividi-calib camera-imu excitation \
  ar0234_kalibr_001/session.json \
  --min-shared-duration-s <LIMIT> \
  --min-shared-fraction <LIMIT> \
  --min-abs-rotation-rad-per-axis <LIMIT> \
  --min-gyro-rms-rad-s-per-axis <LIMIT> \
  --min-accel-variation-std-m-s2-per-axis <LIMIT> \
  --max-gyro-axis-energy-fraction <LIMIT> \
  --min-gyro-smallest-energy-fraction <LIMIT> \
  --min-accel-variation-smallest-energy-fraction <LIMIT> \
  --output-prefix ar0234_kalibr_001/excitation
```

Per-axis minimum gates report the limiting axis. Directionality gates report normalized fractions and remain procedure-specific rather than universal calibration rules.

## Recommended evidence stack

The #47 dynamic review should ultimately combine independent evidence classes:

```text
dynamic-session provenance
        +
excitation / common-time evidence
        +
Kalibr solver residual quality
        +
T_cam_imu + time-shift import
        +
device-domain temporal review
        +
independent-session repeatability
        +
target detection / image-plane coverage
        +
protocol timing evidence
        +
downstream VIO behavior
```

Passing one layer must not silently substitute for another.

## CI

The dependency-free self-test exercises:

```text
camera/IMU cadence parsing
stereo timestamp identity
common-time coverage
per-axis angular integration
3×3 symmetric eigenvalue analysis
multi-axis evidence-only result
explicit PASS gates
one-axis excitation FAIL under an explicit directionality gate
stereo timestamp mismatch structural FAIL
Markdown rendering
```

No ROS, MCAP, OpenCV, or Kalibr installation is required for this analysis self-test. Ubuntu and Windows also execute package-level tests that run the installed command outside a source checkout while retaining the direct compatibility-wrapper self-test.

Related: #8, #35, #47, #46.
