# IMU Allan / noise laboratory

Issue #91 moves the characterized dependency-free Allan laboratory into the installed package without changing its estimator or evidence semantics.

## Command mapping

```text
bividi-calib imu allan ...
        ↓
bividi.calibration.imu_allan_command
        ↓
bividi.calibration.imu_allan

legacy tools/analyze_imu_allan.py
        ↓
thin compatibility wrapper
        ↓
same packaged implementation/command adapter
```

The implementation report schema remains `bividi.calibration.imu_allan_analysis.v1`.

## Estimator boundary

The estimator remains the existing streaming dyadic non-overlapping Allan deviation implementation:

- cluster sizes are powers of two;
- adjacent non-overlapping cluster averages form the Allan variance pairs;
- estimator memory is O(log N), so long stationary captures do not need to be loaded into RAM;
- the exact streaming result is regression-tested against the direct non-overlapping definition.

Package migration does not replace this with an overlapping estimator or a third-party Allan library.

## Timing boundary

The default sample period is derived from the trace's extended device timestamps using the measured first-to-last effective rate. There is no silent 600 Hz assumption.

`--sample-rate-hz` is an explicit operator override. Duplicate/backward timestamps and invalid samples are rejected by default because they can bias Allan results. `--allow-invalid-samples` and `--allow-timing-anomalies` remain explicit exploratory overrides rather than normal qualification behavior.

## Scale and fit provenance

Raw-count Allan curves are always available. SI curves require operator-supplied `--accel-g-per-count` and/or `--gyro-dps-per-count`, and any supplied scale requires `--scale-source`.

The laboratory does not infer vendor-demo full scale or datasheet noise values as specimen measurements.

Fit regions are never selected automatically:

- `--white-window MIN:MAX` selects the explicit `-1/2` white-noise fit region;
- `--random-walk-window MIN:MAX` selects the explicit `+1/2` random-walk fit region;
- free-slope evidence is reported alongside the fixed-slope reference fit.

`--kalibr-axis-policy {max,mean,median}` is also explicit. It requires SI scales plus both fit windows before per-axis candidates may be reduced to Kalibr-style scalars.

## Promotion boundary

Generated Kalibr parameters carry:

```text
candidate_only_not_promoted_to_calibration_artifact
```

They remain noise-characterization evidence. The Allan laboratory does not promote them into a Bividi IMU calibration artifact by itself.

## Outputs

The existing output surfaces are preserved:

```text
Markdown on stdout
optional PREFIX.allan.csv
optional PREFIX.allan.json
optional PREFIX.allan.md
```

The CSV is the Allan curve view; JSON is the machine-readable analysis report; Markdown is a human-readable rendering of the same analysis.

## Exit contract

Package-native invocation uses the shared calibration command vocabulary:

```text
0  completed analysis
2  usage / input / analysis-domain error
3  reserved for an explicit evaluated evidence FAIL
```

The Allan laboratory has no PASS/FAIL disposition, so it does not use exit `3`. The command adapter only normalizes the historical tool's domain-error exit code; it does not modify estimator math, report content, fit semantics, or evidence interpretation.
