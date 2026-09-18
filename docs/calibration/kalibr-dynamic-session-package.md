# Package-native Kalibr dynamic-session preparation

Owner: Issue #47  
Packaging slice: Issue #103

`bividi-calib camera-imu prepare` is the installed entry point for the existing Kalibr dynamic-session staging workflow. The characterized staging math and artifact semantics remain in `bividi.calibration.kalibr_dynamic_session`; `bividi.calibration.kalibr_dynamic_session_command` only normalizes command-level exit behavior. `tools/prepare_kalibr_dynamic_session.py` remains a thin compatibility wrapper.

The command is a **staging/provenance adapter**, not a camera↔IMU solver or promotion gate. It verifies the dynamic capture, IMU calibration-session manifest, Bividi IMU calibration artifact, hash-bound six-position and known-angle gyro-rotation analyses, specimen identity, camera topics, AprilGrid definition, and timestamp convention. It then stages the camera/IMU indexes, calibrated IMU CSV, `camchain.yaml`, `imu.yaml`, `target.yaml`, ROS1 bag recipe, Kalibr command, and `bividi.calibration.kalibr_dynamic_session.v1` manifest.

The raw-to-SI contract remains:

```text
target_si = matrix * (raw_counts - bias_raw_counts)
```

Accelerometer conversion comes from the six-position affine gravity model. Gyroscope conversion requires the controlled-rotation report to contain an absolute `target_rad_s_per_raw_count_matrix`; nominal vendor sensitivity is never substituted.

The camera time reference remains explicit and is one of `exposure_start`, `exposure_midpoint`, or `exposure_end`. The staged manifest keeps the sign convention `t_imu_s = t_camera_reference_s + offset_s`. Successful preparation does not claim that the offset or `T_cam_imu` has been solved.

Camera identities remain `camera_a -> cam0` and `camera_b -> cam1`; the preparer does not infer physical left/right ordering. Measured provenance is required by default, while `--allow-synthetic` remains an explicit test-only opt-in.

The installed path has no ROS or Kalibr runtime dependency. ROS1 bag creation (`write_kalibr_rosbag.py`) and the Kalibr solve remain downstream external steps; ROS2/MCAP remains a separate interoperability transport.

Frozen command exits are:

```text
0  preparation completed
2  usage/input/schema/hash/domain/read/write failure
```

The command does not use exit `3` because staging owns no evaluated PASS/FAIL quality disposition.

For the full capture, timestamp, transform, AprilGrid, ROS1, and ROS2/MCAP workflow, see `docs/calibration/kalibr-dynamic-session.md`.
