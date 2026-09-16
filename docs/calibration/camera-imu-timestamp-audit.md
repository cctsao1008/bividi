# Camera↔IMU Timestamp Audit

Owner: Issue #47  
Depends on: #35 Nori live decode path  
Status: recorder + offline audit tooling implemented; physical AR0234 evidence pending

## Purpose

The timestamp audit quantifies the relationship between camera exposure time and IMU sample time **inside the DECXIN device timestamp domain** before any motion-based temporal calibration is trusted.

```text
Nori transport
    ↓
DECXIN decode
    ↓
bividi-nori-imu-record
    ↓
lossless raw timestamp/count CSV
    ↓
audit_imu_timing.py
    ↓
continuity + nearest-sample timing report
```

This path does not infer physical synchronization accuracy from host receive time and does not claim that nearest-sample timing equals a calibrated camera↔IMU time offset.

## Recording

Build with the supplied Nori SDK and OpenCV transport-normalization path, then run:

```bash
bividi-nori-imu-record \
  --device <DEVICE> \
  --mode <MODE> \
  --duration-s 60 \
  --warmup-frames 30 \
  --output-prefix ar0234_imu_timing
```

Outputs:

```text
ar0234_imu_timing.imu.csv
ar0234_imu_timing.json
```

The CSV is intentionally raw-count/timestamp oriented. Per IMU sample it records:

```text
frame index / sequence
host receive monotonic timestamp (provenance only)
exposure-start raw + extended device time
exposure-end raw + extended device time
sample index / validity
IMU raw + extended device time
raw accelerometer XYZ counts
raw gyroscope XYZ counts
```

The recorder deliberately does **not** write scaled SI accelerometer/gyro values. The current decoder can reproduce vendor-demo scaling, but #47 must not promote those full-scale assumptions into measured calibration truth before the actual sensor configuration is verified.

## Offline audit

Run:

```bash
python tools/audit_imu_timing.py \
  ar0234_imu_timing.imu.csv \
  --json-out ar0234_imu_timing.audit.json \
  --markdown-out ar0234_imu_timing.audit.md
```

The report computes:

```text
valid / invalid IMU sample count
effective IMU rate from extended timestamps
IMU interval P50 / P95 / P99 / max
duplicate and backward timestamp intervals
raw 32-bit IMU rollover count
valid samples per frame
exposure-start/end interval distributions
exposure duration distribution
raw ES / EE rollover counts
nearest IMU sample to every exposure start
nearest IMU sample to every exposure end
signed (IMU - camera) nearest-sample distributions
absolute nearest-sample distributions
```

Nearest-sample lookup uses the complete valid IMU timeline, not only the IMU samples packaged in the same frame.

## Gap definition

There is no hard-coded gap threshold. An arbitrary built-in factor would turn an analysis convention into a false device requirement.

When the experiment defines a threshold, supply it explicitly:

```bash
python tools/audit_imu_timing.py \
  ar0234_imu_timing.imu.csv \
  --gap-threshold-us <EXPLICIT_THRESHOLD>
```

The output records both the threshold and the number of intervals above it.

## Clock-domain rule

The audit uses:

```text
DECXIN exposure extended time
DECXIN IMU extended time
```

These are comparable because they are interpreted within the same decoded device-time domain.

`host_receive_monotonic_ns` is retained in the trace for acquisition provenance but is **not** subtracted from device timestamps. Host and device clock epochs are not assumed to be identical.

## Relationship to Kalibr

This audit and Kalibr answer different questions:

```text
protocol/timestamp audit
    → cadence, continuity, rollover, nearest-sample geometry

Kalibr temporal calibration
    → motion-optimized camera↔IMU time shift
```

Both should be retained. If the motion-based temporal result disagrees materially with the protocol-level timing evidence, investigate exposure timestamp semantics, dataset timestamp assignment, sensor pipeline delay, reset/rollover handling, or frame pairing instead of silently choosing one number.

## What is still unmeasured

Until a physical AR0234 campaign is run, the repository does not claim:

```text
actual IMU sample rate
actual camera↔IMU offset
actual synchronization error
actual IMU axis convention
actual accelerometer / gyro scale
```

Related: #35, #47, #46.
