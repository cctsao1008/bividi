# IMU controlled gyroscope rotation / axis laboratory

Issue #95 moves the characterized dependency-free controlled-rotation analyzer into the installed package without changing its integration, axis-mapping, or sensitivity semantics.

## Command mapping

```text
bividi-calib imu gyro-rotation ...
        ↓
bividi.calibration.imu_gyro_rotation_command
        ↓
bividi.calibration.imu_gyro_rotation

legacy tools/analyze_imu_gyro_rotation.py
        ↓
thin compatibility wrapper
        ↓
same packaged implementation/command adapter
```

The report schema remains `bividi.calibration.imu_gyro_rotation_analysis.v1`.

## Experiment boundary

The laboratory consumes one stationary baseline plus six controlled dynamic traces:

```text
plus_x  minus_x
plus_y  minus_y
plus_z  minus_z
```

`plus_*` means positive target-frame right-hand-rule rotation about Bividi +X/+Y/+Z; `minus_*` is the equal-magnitude opposite turn. Incorrect physical labelling changes the inferred sign and is therefore an experiment error, not something the analyzer silently repairs.

The stationary baseline provides the raw-count gyroscope bias candidate. Each dynamic trace is bias-corrected and integrated over the extended device timestamp using trapezoidal integration. No nominal sample rate is substituted for the measured timestamp intervals.

## Axis/sign and symmetry evidence

For each target axis, the analyzer combines the positive/negative integrated turns as:

```text
response = 0.5 * (integral_plus - integral_minus)
pair_center = 0.5 * (integral_plus + integral_minus)
```

The three response columns form the raw integral response matrix. From that matrix the analyzer reports:

- best signed raw-axis permutation into the target Bividi frame;
- signed-permutation determinant / handedness evidence;
- assigned response, off-axis coupling ratio, and dominance ratio;
- +/- pair-center magnitude and center-to-response ratio.

These remain candidate/sanity evidence. No default coupling, pair-symmetry, handedness, or bias-stability acceptance thresholds are invented.

## Explicit-angle sensitivity boundary

Without `--expected-angle-deg`, the analyzer reports only axis/sign/coupling/symmetry evidence. Absolute gyro sensitivity is **not inferred**.

When the operator supplies a common expected rotation magnitude, the analyzer may additionally estimate:

```text
raw_gyro_counts ~= bias + S * target_angular_rate_rad_s
```

and report:

- `S`, a 3x3 raw-counts-per-rad/s sensitivity matrix;
- `S^-1`, target rad/s per raw count;
- infinity-norm condition evidence;
- reconstructed target integrated angle for all six runs;
- per-run integrated-angle residuals.

The common-angle model assumes the six commanded turns have equal magnitude. Turntable/fixture error therefore remains experiment error; the tool does not reinterpret the commanded angle as an independently measured truth source.

## Accelerometer ↔ gyroscope mapping boundary

`--accelerometer-sixpos-json` may supply a `bividi.calibration.imu_six_position_analysis.v1` report. The controlled-rotation analyzer compares its gyroscope signed permutation with the accelerometer signed permutation.

A match is evidence that both packet sensor axes use the same target-frame convention. A mismatch is reported for investigation; neither mapping is silently preferred or auto-corrected.

This is the complementary evidence to `imu six-position`: static gravity can constrain accelerometer axis/sign but cannot establish gyroscope axis/sign, while controlled rotations provide that gyroscope evidence.

## Data-quality boundary

Invalid IMU samples and duplicate/backward extended device timestamps are rejected by default. Existing `--allow-invalid-samples` and `--allow-timing-anomalies` options remain explicitly exploratory. Non-positive intervals are never integrated.

No DECXIN vendor-demo gyro full-scale or nominal sensitivity is reused as measured truth.

## Outputs

Existing surfaces are preserved:

```text
Markdown on stdout
optional PREFIX.gyro.csv
optional PREFIX.gyro.json
optional PREFIX.gyro.md
```

The report status remains:

```text
candidate_evidence_only_not_promoted_to_calibration_artifact
```

## Exit contract

Package-native invocation uses the shared calibration command vocabulary:

```text
0  completed analysis
2  usage / input / analysis-domain error
3  reserved for an explicit evaluated evidence FAIL
```

The gyro-rotation laboratory owns no PASS/FAIL disposition, so it does not use exit `3`. The command adapter only normalizes the historical tool's domain-error exit code; it does not alter integration math, axis mapping, sensitivity estimation, report content, or interpretation.
