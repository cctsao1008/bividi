# IMU Allan Deviation / Noise Laboratory

Owner: Issue #47  
Applies to: stationary Bividi IMU recordings, including DECXIN AR0234 + ICM-42688-P traces  
Status: dependency-free analysis tooling implemented; physical long-run evidence pending delivered hardware

## Purpose

`tools/analyze_imu_allan.py` turns a lossless `bividi-nori-imu-record` trace into Allan-deviation evidence suitable for estimating the IMU noise terms needed by Kalibr and later VIO work.

The boundary is intentionally conservative:

```text
raw IMU trace
    ↓
stationary/timing evidence
    ↓
Allan deviation in raw counts
    ↓
explicit verified raw→SI scale
    ↓
operator-selected fit windows
    ↓
per-axis candidate noise terms
    ↓
optional explicit axis reduction
    ↓
Kalibr candidate parameters
```

The analyzer does **not** silently infer sensor full-scale, pick a fit region, reduce axes, or promote candidate numbers into a Bividi calibration artifact.

## Why Allan deviation

Kalibr models two IMU error processes per sensor family:

- additive white measurement noise;
- slowly varying bias random walk.

Kalibr's IMU noise-model documentation identifies these on a log-log Allan-deviation plot as approximately:

```text
white measurement noise   slope -1/2
bias random walk          slope +1/2
```

For its parameter convention, Kalibr describes the white-noise parameter as the fitted white-noise line evaluated at `tau = 1 s`, and the bias-random-walk parameter as the fitted +1/2 line evaluated at `tau = 3 s`.

Reference: <https://github.com/ethz-asl/kalibr/wiki/IMU-Noise-Model>

That reference also recommends using a long stationary recording (roughly 15–24 hours) when measuring a real IMU rather than deriving four noise parameters from a short capture.

## Estimator implemented by Bividi

The default implementation is:

```text
streaming dyadic non-overlapping Allan deviation
```

Cluster sizes are powers of two:

```text
m = 1, 2, 4, 8, ...
tau = m × sample_period
```

For each `m`, adjacent non-overlapping cluster averages are compared:

```text
ADEV(tau) = sqrt( 1/2 × mean( (ybar[k+1] - ybar[k])^2 ) )
```

The dyadic aggregation is recursive, so the analyzer keeps `O(log N)` estimator state instead of loading a 15–24 hour trace into RAM. This is important for high-rate IMUs.

Non-overlapping Allan deviation has lower statistical efficiency than an overlapping estimator, but retains the canonical process slopes and is practical as a dependency-free long-run path. For publication-grade or final calibration work, cross-check the result against an independent established Allan implementation such as the Kalibr-recommended `allan_variance_ros` path.

## Input

The analyzer consumes the lossless CSV produced by:

```bash
bividi-nori-imu-record ... --output-prefix <SESSION>
```

Required evidence includes:

```text
sample_valid
imu_extended_time_us
accel_raw_x/y/z
gyro_raw_x/y/z
```

Raw counts remain authoritative. The current DECXIN decoder's vendor-demo full-scale assumptions are not silently reused as calibration truth.

## First pass: raw-count Allan curve

No scale is required to inspect curve shape:

```bash
python tools/analyze_imu_allan.py \
  ar0234_stationary.imu.csv \
  --output-prefix ar0234_stationary
```

Outputs:

```text
ar0234_stationary.allan.csv
ar0234_stationary.allan.json
ar0234_stationary.allan.md
```

The raw-count curve is useful for checking whether usable `-1/2` and `+1/2` regions exist before any candidate Kalibr parameter is generated.

## Explicit SI conversion

Kalibr parameters require SI units. Conversion is allowed only when the sensor scale has been independently verified:

```bash
python tools/analyze_imu_allan.py \
  ar0234_stationary.imu.csv \
  --accel-g-per-count <VERIFIED_VALUE> \
  --gyro-dps-per-count <VERIFIED_VALUE> \
  --scale-source "<how this scale was verified>" \
  --output-prefix ar0234_stationary_si
```

The analyzer converts:

```text
accelerometer → m/s^2
gyroscope     → rad/s
```

Supplying a scale without `--scale-source` is rejected.

## Fit windows are experiment parameters

The tool deliberately does not search the curve and announce a noise model automatically.

After reviewing the curve/local slopes, choose explicit tau ranges:

```bash
python tools/analyze_imu_allan.py \
  ar0234_stationary.imu.csv \
  --accel-g-per-count <VERIFIED_VALUE> \
  --gyro-dps-per-count <VERIFIED_VALUE> \
  --scale-source "<verification>" \
  --white-window <TAU_MIN>:<TAU_MAX> \
  --random-walk-window <TAU_MIN>:<TAU_MAX> \
  --output-prefix ar0234_stationary_fit
```

For every axis the report contains both:

```text
free log-log slope + R²
fixed-slope fit used for the Kalibr convention
```

The free slope is diagnostic evidence showing whether the selected window actually resembles the expected process. No default slope-error acceptance threshold is invented.

## Per-axis first, scalar later

Kalibr accepts one scalar noise density and one scalar random-walk value for each sensor family. Bividi does not silently decide how three measured axes should become one scalar.

Without an axis policy the analysis stops at per-axis candidates.

If the experiment explicitly wants a scalar, select a policy:

```bash
--kalibr-axis-policy max
--kalibr-axis-policy mean
--kalibr-axis-policy median
```

Example:

```bash
python tools/analyze_imu_allan.py \
  ar0234_stationary.imu.csv \
  --accel-g-per-count <VERIFIED_VALUE> \
  --gyro-dps-per-count <VERIFIED_VALUE> \
  --scale-source "<verification>" \
  --white-window 0.1:2 \
  --random-walk-window 10:200 \
  --kalibr-axis-policy max \
  --output-prefix ar0234_stationary_fit
```

The numerical windows above are **syntax examples only**, not recommended ICM-42688 values. Real windows must come from the measured curve.

## Candidate output semantics

When all prerequisites are explicit, the report can emit candidate fields corresponding to Kalibr's IMU configuration:

```text
accelerometer_noise_density
gyroscope_noise_density
accelerometer_random_walk
gyroscope_random_walk
update_rate
```

Units follow the Bividi calibration schema / Kalibr convention:

```text
accelerometer_noise_density       m/s^2 / sqrt(Hz)
gyroscope_noise_density           rad/s / sqrt(Hz)
accelerometer_random_walk         m/s^3 / sqrt(Hz)
gyroscope_random_walk             rad/s^2 / sqrt(Hz)
update_rate                       Hz
```

The JSON marks these values as:

```text
candidate_only_not_promoted_to_calibration_artifact
```

Promotion into `bividi.calibration.imu.v1` remains a separate reviewed step with specimen/session provenance.

## Timing guardrails

Allan analysis assumes a regularly sampled time series.

By default the tool rejects:

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

Results obtained with those switches should not be promoted to calibration without explaining the discontinuity handling.

The analyzer derives the sample period from first-to-last device time by default. An explicit `--sample-rate-hz` may be supplied when the experiment has a separately justified rate definition. This does not repair missing samples.

Run `tools/audit_imu_timing.py` alongside the Allan analysis and inspect the lossless trace for large forward gaps before accepting a fit.

## Recommended physical workflow

After stable #35 capture is available:

```text
1. Fix IMU range / filter / sample configuration.
2. Keep the rig mechanically stationary.
3. Keep temperature/environment as stable as practical.
4. Record a long lossless raw-count session.
5. Audit timestamps and invalid samples.
6. Confirm raw→SI scale from actual configuration, not vendor demo code.
7. Compute Allan curve.
8. Inspect local slopes and choose fit windows explicitly.
9. Produce per-axis candidate parameters.
10. Select an axis-reduction policy only when justified.
11. Cross-check against an independent Allan implementation.
12. Promote reviewed values into an IMU calibration artifact.
13. Export the measured artifact through `export_kalibr_imu.py`.
```

If range, digital filtering, output data rate, firmware, or other sensor configuration changes, treat the prior noise characterization as potentially invalid until re-verified.

## What this does not measure

Stationary Allan analysis does not solve:

```text
accelerometer scale/misalignment
camera↔IMU spatial extrinsics
camera↔IMU temporal offset
temperature coefficients
motion-dependent vibration/noise
full VIO accuracy
```

Those remain separate #47 / #8 / #46 evidence paths.

Related: `inertial-camera-imu.md`, `camera-imu-timestamp-audit.md`, Issue #47, Issue #46.
