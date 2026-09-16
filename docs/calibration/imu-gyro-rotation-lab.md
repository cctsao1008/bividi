# Controlled Gyroscope Rotation / Axis Laboratory

Owner: Issue #47  
Applies to: Bividi IMU traces recorded with a fixed sensor configuration  
Status: dependency-free analysis tooling implemented; physical controlled-turn evidence pending delivered hardware

## Purpose

`tools/analyze_imu_gyro_rotation.py` complements the six-position accelerometer laboratory by establishing gyroscope axis/sign evidence from controlled angular motion.

Static gravity can identify accelerometer axes, but it cannot identify gyroscope axis permutation or positive-rotation sign. This laboratory closes that gap with one stationary baseline plus six controlled rotations:

```text
stationary baseline
+X rotation
-X rotation
+Y rotation
-Y rotation
+Z rotation
-Z rotation
```

The positive direction is the **right-hand rule about the target Bividi +axis**. The operator must physically label the experiment accordingly; the tool does not infer which mechanical turn was intended.

## Evidence boundary

The default path remains raw-count based:

```text
lossless .imu.csv traces
        ↓
stationary raw gyro bias
        ↓
bias-corrected device-time integration
        ↓
+/- pair response matrix
        ↓
best signed raw-axis permutation
        ↓
cross-axis / symmetry evidence
```

No DECXIN demo full-scale, nominal rate, or gyro sensitivity is reused as calibration truth.

If the experiment also supplies a known common rotation angle, the tool can estimate an evidence-only 3×3 sensitivity model:

```text
raw_gyro_counts ~= bias_raw + S * target_angular_rate_rad_s
```

where `S` has units of raw counts per rad/s. Its inverse maps raw counts to target rad/s.

## Recording protocol

Keep the following fixed across all seven traces:

```text
device / specimen
firmware
IMU range
IMU output-data rate
IMU filtering
transport / decode path
```

Recommended sequence:

1. Mount the rig so the target Bividi IMU frame is physically understood.
2. Record a stationary baseline long enough to estimate gyro mean bias.
3. Rotate about target +X in the positive right-hand-rule direction; record the complete turn.
4. Repeat an equal-magnitude turn about target +X in the negative direction.
5. Repeat for target Y and Z.
6. Avoid simultaneous multi-axis rotation as much as practical.
7. If absolute scale is desired, use a fixture/turntable that makes the six commanded angle magnitudes equal and known.
8. Keep stationary lead-in/lead-out sections if convenient; after bias subtraction they should contribute little integrated angle.

The trace labels mean commanded target-frame rotation, not raw packet axis:

```text
plus_x  = positive rotation about target Bividi +X
minus_x = equal-magnitude negative rotation about target Bividi +X
...
```

## Axis/sign-only analysis

A known angle is not required to infer the dominant signed mapping:

```bash
python tools/analyze_imu_gyro_rotation.py \
  --stationary gyro_static.imu.csv \
  --plus-x  gyro_px.imu.csv \
  --minus-x gyro_nx.imu.csv \
  --plus-y  gyro_py.imu.csv \
  --minus-y gyro_ny.imu.csv \
  --plus-z  gyro_pz.imu.csv \
  --minus-z gyro_nz.imu.csv \
  --output-prefix ar0234_gyro_axes
```

Outputs:

```text
ar0234_gyro_axes.gyro.csv
ar0234_gyro_axes.gyro.json
ar0234_gyro_axes.gyro.md
```

For each target axis the tool reports:

```text
assigned raw axis
sign
integrated response
column L2 response
cross-axis L2 ratio
dominance ratio
```

The assignment is global: all six XYZ permutations are evaluated and the best signed one-to-one mapping is selected. It is not a greedy per-axis choice.

## +/- pair symmetry

For each target axis the analyzer computes:

```text
response = 0.5 * (integral_plus - integral_minus)
pair_center = 0.5 * (integral_plus + integral_minus)
```

With equal-magnitude opposite turns and good bias subtraction, `pair_center` should be small relative to `response`.

The report exposes the ratio but does **not** invent a pass/fail threshold. Large pair-center error may indicate, among other possibilities:

```text
unequal commanded angles
stationary-bias drift
fixture asymmetry
timing/data loss
unmodelled cross-axis motion
```

## Optional absolute sensitivity from a known angle

When every +/− turn has the same known magnitude, provide it explicitly:

```bash
python tools/analyze_imu_gyro_rotation.py \
  --stationary gyro_static.imu.csv \
  --plus-x  gyro_px.imu.csv \
  --minus-x gyro_nx.imu.csv \
  --plus-y  gyro_py.imu.csv \
  --minus-y gyro_ny.imu.csv \
  --plus-z  gyro_pz.imu.csv \
  --minus-z gyro_nz.imu.csv \
  --expected-angle-deg 180 \
  --output-prefix ar0234_gyro_scale
```

The angle is an **experiment input**, not a sensor assumption.

For a commanded angle `theta` the paired integrated response gives:

```text
S[:,axis] = response[:,axis] / theta_rad
```

with units:

```text
raw counts / (rad/s)
```

The inverse candidate matrix has units:

```text
(rad/s) / raw count
```

The report also maps each integrated run back to a target-frame angle and reports residual magnitude against the commanded turn.

A known angle does not by itself make the result a final calibration. Turntable angle error, mounting error, non-axis-aligned motion, and bias drift remain measurement uncertainties.

## Compare accelerometer and gyroscope packet axes

The six-position accelerometer laboratory produces its own signed mapping. Compare it directly:

```bash
python tools/analyze_imu_gyro_rotation.py \
  ... \
  --accelerometer-sixpos-json ar0234_sixpos.sixpos.json \
  --output-prefix ar0234_gyro_axes
```

The analyzer reports whether the accelerometer and gyroscope signed permutations match.

A match is useful evidence that both packet fields use the same target-frame convention. A mismatch is not auto-corrected and neither side is silently preferred; inspect packet decoding, physical labels, fixture convention, and sensor configuration.

## Positive-rotation convention

Use the target-frame right-hand rule:

```text
thumb points along +axis
curled fingers define positive rotation
```

For example, `plus_z` means a positive right-hand turn about target +Z, regardless of which raw gyro field responds positively.

This convention is critical. If a physically negative turn is labelled `plus_z`, the tool will faithfully infer the opposite gyro sign.

## Timing / integration guardrails

Integration uses the extended **device IMU timestamps** from the lossless trace, not nominal sample rate and not host receive time.

By default the analyzer rejects:

```text
invalid samples
duplicate timestamps
backward timestamps
```

Exploratory overrides exist:

```text
--allow-invalid-samples
--allow-timing-anomalies
```

If nonpositive intervals are allowed, they are counted but not integrated. Skipping invalid samples creates larger integration intervals and can bias results; such output should not be promoted without explaining the discontinuity handling.

## Relationship to the six-position gravity lab

The two laboratories solve different observability problems:

```text
six-position gravity lab
    ↓
accelerometer axis / sign / counts-per-g evidence

controlled gyro rotation lab
    ↓
gyroscope axis / sign / optional rate-scale evidence
```

Together they can establish whether accelerometer and gyroscope packet axes agree with the intended Bividi IMU frame.

Neither experiment alone proves the camera↔IMU rigid transform. Camera↔IMU spatial calibration remains a separate dynamic calibration problem, with Kalibr as the first external reference backend.

## What this does not prove

This tool does not by itself establish:

```text
final gyro scale/misalignment calibration
turntable metrology uncertainty
temperature dependence
vibration sensitivity
camera↔IMU spatial extrinsic
camera↔IMU time offset
VIO accuracy
```

The generated JSON is explicitly marked:

```text
candidate_evidence_only_not_promoted_to_calibration_artifact
```

Promotion into `bividi.calibration.imu.v1` remains a separate reviewed step with specimen/configuration/session provenance.

Related: `imu-six-position-axis-lab.md`, `imu-stationary-analysis.md`, `imu-allan-noise-lab.md`, Issue #47, Issue #46.
