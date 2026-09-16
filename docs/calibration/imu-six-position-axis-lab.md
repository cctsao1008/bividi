# Six-Position IMU Gravity / Axis Laboratory

Owner: Issue #47  
Applies to: stationary Bividi IMU recordings, including DECXIN AR0234 + ICM-42688-P traces  
Status: hardware-independent analyzer implemented; physical six-pose evidence pending delivered hardware

## Purpose

`tools/analyze_imu_six_position.py` uses six stationary recordings to turn IMU axis/range assumptions into measured evidence before any VIO or camera↔IMU calibration consumes them.

The six poses are:

```text
+X up
-X up
+Y up
-Y up
+Z up
-Z up
```

Here `+X up` means the **target Bividi IMU +X axis physically points upward** while the rig is stationary. Under the usual accelerometer specific-force convention, the expected target-frame reading is approximately:

```text
+X up -> [+1,  0,  0] g
-X up -> [-1,  0,  0] g
+Y up -> [ 0, +1,  0] g
-Y up -> [ 0, -1,  0] g
+Z up -> [ 0,  0, +1] g
-Z up -> [ 0,  0, -1] g
```

This definition avoids the common ambiguity between "gravity vector points downward" and "accelerometer reports upward specific force".

## Input

Record six lossless stationary traces with `bividi-nori-imu-record`, one for each pose. Keep sensor range, output data rate, filtering, firmware, and host path unchanged across all six captures.

Example naming:

```text
sixpos_px.imu.csv
sixpos_nx.imu.csv
sixpos_py.imu.csv
sixpos_ny.imu.csv
sixpos_pz.imu.csv
sixpos_nz.imu.csv
```

Then run:

```bash
python tools/analyze_imu_six_position.py \
  --plus-x  sixpos_px.imu.csv \
  --minus-x sixpos_nx.imu.csv \
  --plus-y  sixpos_py.imu.csv \
  --minus-y sixpos_ny.imu.csv \
  --plus-z  sixpos_pz.imu.csv \
  --minus-z sixpos_nz.imu.csv \
  --output-prefix ar0234_sixpos
```

Outputs:

```text
ar0234_sixpos.sixpos.csv   pose-level raw statistics
ar0234_sixpos.sixpos.json  machine-readable model/evidence
ar0234_sixpos.sixpos.md    human-readable report
```

## What is estimated

For the six pose means the tool fits the evidence-only affine gravity model:

```text
raw_counts ~= bias_raw + A_raw_per_g * target_specific_force_g
```

`A_raw_per_g` is a 3x3 matrix whose rows are raw packet X/Y/Z and whose columns are target Bividi X/Y/Z. Its inverse is also reported:

```text
target_specific_force_g ~= inverse(A) * (raw_counts - bias_raw)
```

This gives a compact sanity model containing:

- raw accelerometer bias candidate;
- counts-per-g scale for each target axis;
- axis permutation/sign evidence;
- cross-axis coupling evidence;
- scale spread across axes;
- pair-center disagreement;
- matrix determinant and condition number;
- per-pose fit residuals.

The matrix is **not automatically promoted** into `bividi.calibration.imu.v1`. A six-pose gravity test cannot cleanly separate fixture alignment error from sensor-axis misalignment, so the matrix remains candidate evidence until reviewed.

## Signed axis mapping

The analyzer evaluates all six permutations of raw X/Y/Z and chooses the assignment maximizing the absolute gravity response across target X/Y/Z.

For every target axis it reports an expression such as:

```text
target_x ~= +raw_y
target_y ~= -raw_z
target_z ~= -raw_x
```

It also emits a signed-permutation matrix and its determinant.

Interpretation:

```text
det = +1  mapping preserves handedness
det = -1  mapping flips handedness
```

This statement is conditional: it is only meaningful when both the raw sensor basis and the target Bividi basis have independently defined handedness. Do not use the determinant alone to declare the physical sensor frame right-handed.

## Scale sanity without trusting vendor-demo full-scale

The six-pose experiment itself supplies a gravity reference. For each target axis the tool reports the L2 response in raw counts per g and its reciprocal g/count estimate.

This lets the delivered specimen answer questions such as:

```text
Is the actual configured scale close to one consistent counts/g value?
Are X/Y/Z scales materially different?
Does the observed range look compatible with the believed register configuration?
```

The tool does **not** reuse the DECXIN decode demo's `±4 g` assumption as calibration truth.

If the observed counts/g later agrees with a read-back hardware range/register configuration, that agreement can become provenance for SI conversion in the stationary and Allan tools.

## Cross-axis and pose-quality evidence

For each target-axis gravity column the report contains:

```text
assigned dominant raw component
column L2 counts/g
off-axis L2 / dominant ratio
dominant / second-largest ratio
```

It also compares the center of every +/- pair:

```text
center_X = (mean(+X) + mean(-X)) / 2
center_Y = (mean(+Y) + mean(-Y)) / 2
center_Z = (mean(+Z) + mean(-Z)) / 2
```

If the experiment were ideal, all three centers would represent the same raw bias. Their disagreement is therefore useful evidence for fixture tilt, temperature drift, nonlinearity, motion, or other model violations.

No default pass/fail threshold is invented for these metrics. Establish thresholds only after real hardware repeatability data exists or a system requirement defines one.

## Gyroscope limitation

Six stationary gravity poses **cannot determine gyroscope axis permutation or sign** because static gravity does not excite angular rate.

The report only aggregates stationary gyro mean evidence across the six sessions:

```text
weighted raw gyro mean
pose-to-pose mean range
```

Do not infer:

```text
accelerometer axis map == gyroscope axis map
```

merely because both sensors reside in the same IMU package. A controlled positive/negative rotation experiment is required to verify gyro X/Y/Z sign and permutation independently.

That controlled-rotation check is the natural companion to this laboratory before #46 VIO.

## Acquisition discipline

For meaningful physical evidence:

1. Mechanically fixture each target axis as close to vertical as practical.
2. Keep the unit stationary during each capture.
3. Use the same IMU range, ODR, filtering, firmware, and power state in all six poses.
4. Allow thermal conditions to be documented and reasonably stable.
5. Record enough samples to make the pose mean stable for the experiment; Bividi deliberately does not invent a universal duration threshold before specimen data exists.
6. Run `audit_imu_timing.py` if timing continuity is in doubt.
7. Repeat the complete six-pose set when configuration changes could invalidate scale/bias evidence.

By default the analyzer rejects invalid IMU samples and duplicate/backward device timestamps. Exploratory overrides exist:

```text
--allow-invalid-samples
--allow-timing-anomalies
```

Results produced with those overrides need explicit review before reuse.

## Relationship to the rest of #47

```text
six-position gravity lab
    -> accelerometer axis/sign/scale sanity

stationary analyzer
    -> gyro bias + raw variance evidence

Allan lab
    -> noise density + bias random-walk candidates

gyro controlled-rotation lab (next)
    -> gyro axis/sign convention

camera↔IMU timing audit + Kalibr
    -> temporal + spatial camera/IMU calibration
```

All of these remain evidence inputs. #46 must consume a reviewed measured calibration revision, not assumptions embedded in the VIO backend.

Related: `imu-stationary-analysis.md`, `imu-allan-noise-lab.md`, `camera-imu-timestamp-audit.md`, Issue #47, Issue #46.
