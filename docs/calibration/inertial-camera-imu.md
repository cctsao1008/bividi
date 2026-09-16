# Inertial and Camera↔IMU Calibration Contract

Owner: Issue #47  
Depends on: stable normalized capture from #35  
Downstream consumer: #46 VIO  
Status: pre-hardware schemas/validation/export adapter implemented; physical measurements pending

## Boundary

Bividi owns the persistent calibration semantics. External solvers such as ETH Zurich Kalibr are optional tools behind an explicit adapter boundary.

```text
Bividi measured session / calibration artifact
                    ↓
             export adapter
                    ↓
          Kalibr ROS/YAML inputs
                    ↓
            external optimizer
                    ↓
             import adapter
                    ↓
       Bividi versioned artifact
```

ROS/Kalibr types must not appear in Bividi Core or the live capture contract.

## Current artifact families

```text
bividi.calibration.imu.v1
bividi.calibration.camera_imu.v1
```

Machine-readable schemas live under `calibration/schemas/`; synthetic examples live under `calibration/examples/`.

Unknown/unmeasured terms remain absent. In particular, an unknown time offset, extrinsic, bias, scale term, or noise parameter must not silently become zero.

## Units

The v1 inertial artifacts use SI units for calibration values:

```text
gyro bias / stddev                 rad/s
accelerometer mean / stddev       m/s^2
gyro noise density                rad/s/sqrt(Hz)
accelerometer noise density       m/s^2/sqrt(Hz)
gyro bias random walk             rad/s^2/sqrt(Hz)
accelerometer bias random walk    m/s^3/sqrt(Hz)
rigid-transform translation       m
camera↔IMU time offset            s
```

The DECXIN embedded device timestamp counter itself remains represented in microseconds where timestamp audit artifacts need it; this is distinct from calibration parameter units.

## Transform convention

A camera↔IMU artifact names both ends explicitly:

```text
transform.from_frame = imu_reference.frame
transform.to_frame   = camera_reference.frame
```

The 4×4 matrix transforms a homogeneous point expressed in `from_frame` into `to_frame` coordinates.

For the first AR0234 reference rig, keep the reference camera named `camera_a` until #35 physically establishes A/B ↔ left/right identity. Do not encode an unmeasured left/right assumption in calibration artifacts.

A valid transform must contain a proper right-handed rotation (orthonormal, determinant +1) and homogeneous last row `[0, 0, 0, 1]`.

## Camera↔IMU time-offset convention

The sign is explicit and fixed in v1:

```text
t_imu_s = t_camera_reference_s + offset_s
```

The camera timestamp semantic must also be named:

```text
exposure_start
exposure_midpoint
exposure_end
frame_timestamp
```

DECXIN exposes both exposure start and exposure end. Co-packaging camera and IMU timestamps does not prove that either one is already the calibrated visual timestamp reference, so the selected semantic must remain explicit through dataset export and solver import.

## Kalibr mapping

Kalibr's `imu.yaml` expects these fields:

```text
accelerometer_noise_density
accelerometer_random_walk
gyroscope_noise_density
gyroscope_random_walk
rostopic
update_rate
```

`tools/export_kalibr_imu.py` maps only explicit Bividi measurements/imported values:

```text
Bividi noise.accelerometer_noise_density_m_s2_sqrt_hz
    → Kalibr accelerometer_noise_density

Bividi noise.accelerometer_bias_random_walk_m_s3_sqrt_hz
    → Kalibr accelerometer_random_walk

Bividi noise.gyroscope_noise_density_rad_s_sqrt_hz
    → Kalibr gyroscope_noise_density

Bividi noise.gyroscope_bias_random_walk_rad_s2_sqrt_hz
    → Kalibr gyroscope_random_walk
```

For `update_rate`, the exporter prefers timestamp-derived `timing.effective_rate_hz`; if absent it uses `imu.sample_rate_hz_measured`. It deliberately refuses to substitute the nominal rate.

The exporter also refuses synthetic artifacts by default. `--allow-synthetic` exists only for fixtures and adapter testing.

Example:

```bash
python tools/export_kalibr_imu.py \
  calibration/measured/<imu-artifact>.json \
  --rostopic /imu0 \
  --output imu.yaml \
  --manifest-out imu.export.json
```

The sidecar records the source artifact hash, calibration ID, exact field mapping, update-rate source, and exporter revision when available.

## Kalibr camera↔IMU mapping

Kalibr uses `T_cam_imu` for the transformation from IMU coordinates into camera coordinates. That matches the Bividi v1 transform directly **only when**:

```text
Bividi from_frame == Kalibr IMU frame
Bividi to_frame   == the corresponding Kalibr camera frame
```

Kalibr's `timeshift_cam_imu` convention is:

```text
t_imu = t_cam + shift
```

Bividi v1 deliberately uses the same sign equation. A future importer/exporter can therefore map the numeric value directly only after verifying that the Bividi `camera_time_reference` is the same image timestamp semantic used in the exported Kalibr dataset.

Do not map a time shift merely because the sign matches; timestamp semantic and dataset construction still matter.

## What is intentionally not exported yet

A complete Kalibr camera/IMU session also needs camera intrinsics/extrinsics, target metadata, images, IMU samples, and a ROS-bag-compatible dataset. The camera chain depends on measured #8 stereo calibration and verified #35 camera identity.

Therefore this pre-hardware phase does **not** fabricate:

```text
camchain.yaml intrinsics
camera A/B → left/right identity
physical T_cam_imu
physical timeshift_cam_imu
measured IMU noise
ROS bag data
```

Those appear only after their upstream measurements exist.

## Validation

Use:

```bash
python tools/validate_calibration_artifact.py <artifact.json>
```

The dependency-free validator checks the high-value structural and semantic invariants in normal CI, including proper rigid-transform geometry, explicit transform direction, time-offset sign definition, provenance, units/positive noise values, and right-handed frame declarations.

The JSON Schema files remain the durable machine-readable contract. A standards-compliant JSON Schema implementation may additionally validate them in richer environments.

## Live-hardware sequence

After #35 provides stable physical capture:

```text
stationary recording
    ↓
bias / variance / timestamp audit
    ↓
long stationary recording
    ↓
noise / random-walk characterization
    ↓
axis convention verification
    ↓
measured IMU artifact
    ↓
Kalibr imu.yaml export
    ↓
dynamic camera+IMU calibration session
    ↓
Kalibr spatial + temporal solve
    ↓
protocol/timestamp cross-check
    ↓
measured/imported camera↔IMU artifact
    ↓
#46 VIO
```

No physical AR0234 calibration values are present in the repository yet.

Related: #35, #8, #47, #46.
