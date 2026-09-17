# Inertial and Camera↔IMU Calibration Contract

Owner: Issue #47  
Depends on: stable normalized capture from #35 and measured camera geometry from #8  
Downstream consumer: #46 VIO  
Status: pre-hardware schemas/validation/IMU analysis/dynamic Kalibr export tooling implemented; physical measurements pending

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
             import/review adapter
                    ↓
       Bividi versioned artifact
```

ROS/Kalibr types must not appear in Bividi Core or the normal live capture contract.

## Current artifact / adapter families

```text
bividi.calibration.imu.v1
bividi.calibration.camera_imu.v1
bividi.calibration.imu_session_manifest.v1
bividi.calibration.kalibr_dynamic_session.v1
```

The first two are promoted numerical calibration artifacts. The IMU session manifest binds calibration evidence before promotion. The Kalibr dynamic-session manifest binds one staged external-solver input bundle; it is not itself a calibration result.

Unknown/unmeasured terms remain absent. An unknown time offset, extrinsic, bias, scale term, noise parameter, or camera timestamp semantic must not silently become zero/default.

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

DECXIN embedded timestamp counters remain represented in microseconds where raw timing evidence requires it. Kalibr ROS messages use integer nanosecond header timestamps derived from those device timestamps, not host arrival time.

## Transform convention

A camera↔IMU artifact names both ends explicitly:

```text
transform.from_frame = imu_reference.frame
transform.to_frame   = camera_reference.frame
```

The 4×4 matrix transforms a homogeneous point expressed in `from_frame` into `to_frame` coordinates.

For the AR0234 reference rig, keep the reference camera named `camera_a` until #35 physically establishes A/B ↔ left/right identity. A valid transform must contain a proper right-handed rotation and homogeneous last row `[0, 0, 0, 1]`.

Kalibr revision `1f60227442d25e36365ef5f72cd80b9666d73467` reports `T_ci` as **imu0 → cam_i**. Numeric import into Bividi is direct only when the named Bividi IMU/camera frames are the same frames used by the exported Kalibr session.

## Camera↔IMU time-offset convention

The sign is explicit and fixed in v1:

```text
t_imu_s = t_camera_reference_s + offset_s
```

Kalibr uses the same sign equation for `timeshift_cam_imu`.

The camera timestamp semantic must also be named:

```text
exposure_start
exposure_midpoint
exposure_end
frame_timestamp
```

DECXIN exposes exposure start/end. Co-packaging camera and IMU timestamps does not prove which visual timestamp is appropriate, so dynamic export requires an explicit selection and records it in the session manifest. A Kalibr time shift cannot be imported merely because the sign matches; the timestamp semantic must match too.

## Kalibr IMU mapping

Kalibr `imu.yaml` expects:

```text
accelerometer_noise_density
accelerometer_random_walk
gyroscope_noise_density
gyroscope_random_walk
rostopic
update_rate
```

`tools/export_kalibr_imu.py` maps only explicit Bividi measurements/imported values. For `update_rate`, timestamp-derived `timing.effective_rate_hz` is preferred, then `imu.sample_rate_hz_measured`; the nominal rate is not substituted. Synthetic artifacts are refused by default.

## Dynamic camera+IMU session mapping

When hardware evidence exists, `bividi-nori-calib-record` records one synchronized motion session:

```text
camera_a/camera_b lossless mono PNG
frames.csv with sequence + ES + EE + host/SDK provenance
imu.csv with complete raw IMU samples + device timestamps
capture.json
```

Recording deliberately does not choose a visual timestamp reference and does not scale raw IMU counts.

`tools/prepare_kalibr_dynamic_session.py` then requires:

```text
one dynamic capture
one compatible measured IMU session manifest
one promoted measured IMU artifact
one measured #8/Kalibr-compatible camchain.yaml
one explicit ES/midpoint/EE choice
one explicit AprilGrid definition
```

The raw IMU conversion is derived from hash-bound experiment evidence:

```text
accelerometer:
  six-position bias_raw_counts
  target_g_per_raw_count_matrix × 9.80665

gyroscope:
  controlled-turn bias_raw_counts
  target_rad_s_per_raw_count_matrix
```

The gyro matrix must come from a controlled-rotation experiment with a trusted angle reference. If absolute scale is unavailable, dynamic preparation fails instead of falling back to the DECXIN demo's nominal range.

The conversion equation is recorded in the adapter manifest:

```text
target_si = matrix * (raw_counts - bias_raw_counts)
```

## Kalibr timestamp construction

Kalibr's image and IMU dataset readers at the pinned revision sort/read sensor time from ROS `data.header.stamp`.

The staged export maps:

```text
camera exposure_start:
    t_ns = ES_us * 1000

camera exposure_midpoint:
    t_ns = (ES_us + EE_us) * 500

camera exposure_end:
    t_ns = EE_us * 1000

IMU:
    t_ns = imu_extended_time_us * 1000
```

`host_receive_monotonic_ns` remains acquisition provenance and is never silently substituted as camera/IMU measurement time.

## ROS bag boundary

Kalibr's IMU-camera CLI requires `--bag`. `tools/write_kalibr_rosbag.py` is an optional external adapter that publishes:

```text
/cam0/image_raw   sensor_msgs/Image (mono8)
/cam1/image_raw   sensor_msgs/Image (mono8)
/imu0             sensor_msgs/Imu
```

The adapter imports ROS1 modules lazily; normal Bividi CI and Bividi Core do not depend on ROS1. Header stamp and bag record time use the same staged sensor timestamp. Camera/IMU indexes are streamed/merged, so the bag writer does not need to load an entire high-rate recording into memory.

See `docs/calibration/kalibr-dynamic-session.md` for the operational workflow and exact source-contract audit.

## Validation

Use:

```bash
python tools/validate_calibration_artifact.py <promoted-artifact.json>
python tools/prepare_kalibr_dynamic_session.py --self-test
python tools/write_kalibr_rosbag.py --self-test
```

The promoted-artifact validator checks geometry/provenance/time-sign invariants. Dynamic-session tooling independently re-checks upstream hashes, specimen serial consistency, absolute raw→SI conversion availability, camera topics, and timestamp monotonicity.

The dynamic-session/export slice was merged through PR #48. The merge commit and its normal `main` workflow both passed Ubuntu core, Windows core, and OpenCV/viewer/web jobs.

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
six-position + controlled-rotation frame/scale evidence
    ↓
IMU provenance/config-consistency review
    ↓
measured IMU artifact
    ↓
measured #8 camera chain
    ↓
dynamic stereo+IMU recording
    ↓
Kalibr dynamic-session staging + ROS bag
    ↓
Kalibr spatial + temporal solve
    ↓
protocol/timestamp cross-check + solver-quality review
    ↓
imported/measured camera↔IMU artifact
    ↓
#46 VIO
```

No physical AR0234 calibration values are present in the repository yet.

Related: #35, #8, #47, #46.
