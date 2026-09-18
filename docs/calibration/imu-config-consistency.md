# IMU configuration-consistency laboratory

Status: package-native under Issue #97.

The operator command is:

```bash
bividi-calib imu config-consistency <imu-session-manifest.json> [options]
```

The installed implementation is split deliberately:

```text
bividi.calibration.imu_config_consistency
    characterized analysis/report implementation

bividi.calibration.imu_config_consistency_command
    command adapter for the frozen exit-code contract

tools/analyze_imu_config_consistency.py
    thin source-tree compatibility wrapper
```

Package migration does not change report schema `bividi.calibration.imu_config_consistency.v1`, manifest schema expectation `bividi.calibration.imu_session_manifest.v1`, range/ODR calculations, SHA-256 evidence binding, or report content.

## What it actually verifies

This is a **physical-response consistency check**, not sensor-register readback.

The session manifest declares accelerometer range, gyroscope range, output-data rate, filters, and configuration source. Bound analysis reports then provide independent measured evidence:

- six-position counts/g evidence checks declared accelerometer range;
- controlled-rotation absolute sensitivity checks declared gyroscope range only when the gyro report was created with an explicit trusted commanded angle;
- stationary, Allan, six-position, and gyro-rotation device-time rates may contribute ODR evidence;
- every bound analysis file is verified against the SHA-256 stored in the manifest before it is used.

The current quantizer expectation is the characterized signed 16-bit raw-packet model: magnitude full scale is 32768 counts. That is a packet-representation model, not proof of a hardware register value.

## Filter boundary

Scale and ODR experiments do not uniquely identify filter register settings. The report therefore keeps:

```text
filter_configuration.physically_verified = false
```

Declared accelerometer/gyroscope filter values remain configuration provenance unless a separate readback or transfer-function experiment establishes them physically.

## Gate semantics

Without explicit thresholds, the report remains:

```text
EVIDENCE_ONLY_NO_THRESHOLDS
```

Optional operator thresholds are:

```text
--max-accel-scale-error-pct
--max-gyro-scale-error-pct
--max-odr-error-pct
--require-gyro-scale
```

No default acceptance tolerance is supplied by Bividi. When explicit thresholds are present, the existing analyzer may produce `PASS`, `FAIL`, or `INCOMPLETE` according to available evidence. This command does not currently require a separate named policy-source field; package migration must not invent one.

The package command adapter applies the common command vocabulary:

```text
0  completed, non-failing analysis
2  usage / malformed input / schema / hash / command-domain error
3  completed explicit evidence evaluation with status FAIL
```

This intentionally fixes the historical source-script exit-code collision without changing analysis semantics: the original implementation used `3` for input/domain errors and `2` for an evaluated FAIL. The compatibility wrapper now reaches the same package command contract as `bividi-calib`.

## Evidence limitations

- A matching response does not prove which sensor register is programmed.
- Accelerometer scale inherits six-position fixture/alignment and cross-axis uncertainty.
- Gyroscope absolute scale is unavailable unless controlled rotation used a trusted explicit angle reference.
- ODR is derived from extended IMU device timestamps; host receive cadence and camera FPS are not substitutes.
- Vendor demo values are not promoted into measured configuration evidence.

The output remains analysis/gate evidence. It is not itself the final IMU calibration promotion step; provenance/promotion remains a separate command boundary.
