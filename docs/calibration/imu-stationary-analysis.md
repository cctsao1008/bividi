# Stationary IMU Analysis

Owner: Issue #47  
Input: `bividi-nori-imu-record` lossless `.imu.csv`  
Status: raw-statistics tooling implemented; physical AR0234 measurements pending

## Purpose

A stationary session is the first inertial characterization step after live capture is stable. The analysis separates what can be measured directly in raw counts from what requires a verified sensor scale.

```text
physical stationary rig
        ↓
bividi-nori-imu-record
        ↓
raw accel / gyro counts + device timestamps
        ↓
analyze_imu_stationary.py
        ↓
raw mean/stddev + timing evidence
        ↓ optional explicit verified scale
SI mean/stddev
```

## Raw-domain analysis

Run without any full-scale assumption:

```bash
python tools/analyze_imu_stationary.py \
  ar0234_stationary.imu.csv \
  --json-out ar0234_stationary.analysis.json \
  --markdown-out ar0234_stationary.analysis.md
```

The tool reports per-axis raw-count mean, population standard deviation, min/max, valid/invalid sample counts, duration/effective rate, and timestamp continuity evidence.

A stationary gyro mean is useful candidate bias evidence. A stationary accelerometer mean contains gravity and therefore is not by itself an accelerometer bias estimate.

## Optional SI conversion

The tool never infers ICM-42688 full-scale from the old vendor decoder demo. If the actual runtime configuration is independently verified, pass the scale explicitly and name its provenance:

```bash
python tools/analyze_imu_stationary.py \
  ar0234_stationary.imu.csv \
  --accel-g-per-count <VERIFIED_VALUE> \
  --gyro-dps-per-count <VERIFIED_VALUE> \
  --scale-source "<HOW THIS SCALE WAS VERIFIED>" \
  --json-out ar0234_stationary.analysis.json
```

The report records the supplied scales and converts accelerometer counts to m/s² and gyro counts to rad/s. Supplying a scale without `--scale-source` is rejected.

## Stationarity assumption

The analyzer does not attempt to classify whether the unit was physically motionless. The operator/test procedure owns that condition. A real campaign should therefore record fixture/setup details and avoid vibration, cable movement, table disturbance, or handling during the stationary window.

## Next step

Stationary mean/stddev is not a complete stochastic IMU model. Kalibr's IMU input also needs continuous-time noise density and bias random walk. Those require a longer, deliberate noise/Allan-deviation characterization or another justified method.

Do not derive those four Kalibr values from a short standard-deviation calculation and present them as equivalent.

Related: `camera-imu-timestamp-audit.md`, `inertial-camera-imu.md`, #35, #47.
