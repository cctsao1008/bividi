# IMU six-position gravity / axis laboratory

Issue #93 moves the characterized dependency-free six-position analyzer into the installed package without changing its gravity model or evidence semantics.

## Command mapping

```text
bividi-calib imu six-position ...
        ↓
bividi.calibration.imu_six_position_command
        ↓
bividi.calibration.imu_six_position

legacy tools/analyze_imu_six_position.py
        ↓
thin compatibility wrapper
        ↓
same packaged implementation/command adapter
```

The report schema remains `bividi.calibration.imu_six_position_analysis.v1`.

## Pose convention

The six traces are labelled by the target Bividi IMU frame:

```text
plus_x  minus_x
plus_y  minus_y
plus_z  minus_z
```

`plus_x` means target +X is physically upward while stationary, so the expected accelerometer specific-force vector is approximately `[+1, 0, 0] g`. The same convention applies to the other five poses.

## Candidate gravity model

The characterized analyzer estimates:

```text
raw_counts ~= bias_raw + A_raw_per_g * target_specific_force_g
```

from the six pose means. It reports:

- raw-count bias candidate;
- raw-counts-per-target-g matrix and its inverse;
- pair-center disagreement;
- matrix determinant and infinity-norm condition estimate;
- per-pose residuals in raw counts and calibrated target g;
- the best signed raw-axis permutation;
- handedness evidence from the signed-permutation determinant;
- per-axis counts/g scale estimates, spread, cross-axis ratios, and dominance ratios;
- stationary gyroscope mean/range evidence across the six captures.

The report status remains:

```text
candidate_evidence_only_not_promoted_to_calibration_artifact
```

No package migration step turns this candidate into an accepted calibration artifact.

## Accelerometer / gyroscope boundary

Static gravity supplies directional excitation for the accelerometer, so the six-pose data can provide accelerometer axis/sign and affine scale/coupling evidence.

It cannot establish gyroscope axis/sign mapping. Static poses only provide stationary gyro mean stability evidence; controlled rotations are required for gyro-axis validation. The separate `imu gyro-rotation` laboratory owns that next evidence boundary.

## Data-quality boundary

Each pose trace is streamed from the lossless IMU CSV. Invalid samples and duplicate/backward extended device timestamps are rejected by default. The existing `--allow-invalid-samples` and `--allow-timing-anomalies` flags remain explicit exploratory overrides.

The analyzer does not reuse DECXIN demo accelerometer full-scale as truth and does not invent product thresholds for cross-axis coupling, scale spread, matrix condition, pair-center error, or pose residuals.

## Outputs

Existing output surfaces are preserved:

```text
Markdown on stdout
optional PREFIX.sixpos.csv
optional PREFIX.sixpos.json
optional PREFIX.sixpos.md
```

The CSV summarizes the six pose captures, JSON is the machine-readable candidate report, and Markdown is the human-readable view.

## Exit contract

Package-native invocation uses the shared calibration command vocabulary:

```text
0  completed analysis
2  usage / input / analysis-domain error
3  reserved for an explicit evaluated evidence FAIL
```

The six-position laboratory owns no PASS/FAIL disposition, so it does not use exit `3`. The command adapter only normalizes the historical tool's domain-error exit code; it does not modify gravity math, mapping inference, report content, or interpretation.
