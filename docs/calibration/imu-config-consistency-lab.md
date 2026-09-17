# IMU Configuration Consistency Laboratory

Owner: Issue #47  
Applies to: Bividi IMU calibration-session manifests with bound six-position / gyro-rotation / timing evidence  
Status: hardware-independent analysis tooling implemented; physical specimen evidence pending delivered hardware

## Purpose

`tools/analyze_imu_config_consistency.py` compares **declared IMU configuration** against independently measured physical response.

The problem it addresses is subtle but important:

```text
manifest says ±4 g / ±1000 dps / 200 Hz
                 ↓
calibration analyses consume raw counts
                 ↓
but the actual sensor configuration may differ
```

A provenance manifest prevents evidence from different sessions/configurations from being mixed, but a manifest cannot by itself prove that the operator-declared register settings are physically true.

This laboratory adds a second layer:

```text
declared configuration
        vs
measured response
```

It does **not** claim sensor-register readback.

## Inputs

The primary input is a validated calibration-session manifest:

```text
bividi.calibration.imu_session_manifest.v1
```

The manifest already binds every analysis JSON by SHA-256. The consistency tool re-checks those hashes before using them.

Relevant bound analysis roles are:

```text
six_position    required for accelerometer range consistency
gyro_rotation   required for absolute gyro range consistency
stationary      optional ODR evidence
allan           optional ODR evidence
```

Six-position and gyro-rotation reports also contribute device-timestamp-derived ODR measurements.

## Accelerometer range consistency

The six-position laboratory measures one-g response directly from gravity:

```text
+axis pose
-axis pose
    ↓
0.5 * (mean_plus - mean_minus)
    ↓
counts / g
```

The DECXIN decoder exposes raw accelerometer values as signed 16-bit fields. Under the declared full-scale model, the expected response is:

```text
expected_counts_per_g = 32768 / declared_accelerometer_range_g
```

The tool compares this expectation to the six-position report's per-target-axis column L2 response.

This is deliberately called a **consistency check** rather than register verification. The measurement still contains real-world uncertainty from:

```text
fixture alignment
sensor scale error
cross-axis coupling
mechanical misalignment
pose repeatability
```

## Gyroscope range consistency

Absolute gyro scale is only observable when the controlled-rotation experiment has a trusted angle reference.

`tools/analyze_imu_gyro_rotation.py` produces an absolute sensitivity matrix only when run with an explicit command such as:

```bash
--expected-angle-deg 180
```

When that evidence exists, the expected signed-16-bit sensitivity from the declared range is:

```text
counts_per_dps       = 32768 / declared_gyroscope_range_dps
counts_per_rad_s     = counts_per_dps * 180/pi
```

The consistency analyzer compares that expectation against the measured column-L2 magnitude of the 3x3 gyro sensitivity matrix.

Column magnitude is used because it remains meaningful under axis permutation/sign changes.

If the gyro rotation report has no trusted-angle sensitivity matrix, gyro range consistency remains **unavailable** rather than being fabricated from the vendor-demo `±1000 dps` assumption.

## Output-data-rate consistency

The declared IMU ODR is compared against effective rates measured from extended device IMU timestamps.

Evidence can come from:

```text
stationary analysis
Allan analysis
six-position poses
gyro stationary baseline
gyro +/-XYZ runs
```

The tool does not use:

```text
host receive cadence
camera FPS
USB arrival timing
```

as substitutes for IMU ODR.

## Filter boundary

The session manifest records declared accelerometer and gyroscope filter configuration, but the scale/ODR experiments do not uniquely identify digital-filter register values.

Therefore the report explicitly says:

```text
filter_configuration.physically_verified = false
```

until one of the following becomes available:

```text
vendor/API register readback
explicit I2C/register access
documented firmware configuration receipt
separate transfer-function experiment with sufficient observability
```

Do not infer a filter register from scale/ODR evidence alone.

## Evidence-only mode

By default no tolerance is invented:

```bash
python tools/analyze_imu_config_consistency.py \
  ar0234_imu_session.json \
  --output-prefix ar0234_config_check
```

The result status is:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

and the report contains the measured-vs-declared deltas without declaring pass/fail.

Outputs:

```text
ar0234_config_check.config.json
ar0234_config_check.config.md
```

## Explicit gating

After the team has a justified requirement or baseline, explicit tolerances can be supplied:

```bash
python tools/analyze_imu_config_consistency.py \
  ar0234_imu_session.json \
  --max-accel-scale-error-pct 2 \
  --max-gyro-scale-error-pct 2 \
  --max-odr-error-pct 1 \
  --require-gyro-scale \
  --output-prefix ar0234_config_gate
```

The numbers above are CLI examples only. They are **not** Bividi default acceptance limits.

With explicit thresholds the report can become:

```text
PASS
FAIL
INCOMPLETE
```

No hidden threshold is applied.

## Recommended physical workflow

Once the AR0234/ICM42688 specimen is available:

```text
1. Record the declared IMU configuration in the session manifest.
2. Run stationary/timing characterization.
3. Run six-position gravity experiment.
4. Compare measured counts/g against declared accel range.
5. Run controlled +/-XYZ rotations.
6. If a trusted angle fixture is available, solve absolute gyro sensitivity.
7. Compare measured gyro sensitivity against declared gyro range.
8. Compare device-timestamp ODR evidence across all runs.
9. Investigate any mismatch before promoting calibration values.
```

A mismatch should be treated as an experiment/configuration investigation, not automatically "fixed" by rewriting the manifest to whatever value makes the math agree.

## Relationship to the provenance gate

The two tools solve different problems:

```text
imu_calibration_provenance.py
    ↓
Are these files from the same declared specimen/configuration/session?

analyze_imu_config_consistency.py
    ↓
Does measured physical response agree with that declared configuration?
```

Both are needed before a measured IMU artifact should be promoted.

## Guardrails

- The analyzer does not read IMU registers.
- The signed 16-bit expectation follows the raw packet representation used by the DECXIN decoder.
- Accelerometer response inherits six-position fixture and alignment uncertainty.
- Gyroscope response inherits commanded-angle/turntable uncertainty.
- ODR is measured in the IMU device-time domain.
- Filter configuration remains provenance, not verified measurement, unless an independent mechanism establishes it.
- No pass/fail tolerance is invented by default.
- A physically inconsistent declaration must be investigated before final calibration promotion.

Related: `imu-calibration-provenance-gate.md`, `imu-six-position-axis-lab.md`, `imu-gyro-rotation-lab.md`, `imu-allan-noise-lab.md`, Issue #47, Issue #46.
