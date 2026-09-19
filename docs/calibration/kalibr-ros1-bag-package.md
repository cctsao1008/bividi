# Package-native Kalibr ROS1 bag compatibility transport

`bividi-calib camera-imu ros1-bag` is the installed-package entry point for the legacy ROS1 bag transport required by the authoritative upstream `ethz-asl/kalibr` solver path.

This packaging does **not** make ROS1 part of Bividi Core. Bividi's staged session, evidence, calibration artifacts, and promotion contracts remain ROS-independent. The ROS1 bag exists only at the external Kalibr compatibility boundary. ROS2/MCAP remains the modern interoperability transport for replay, inspection, and future backend cross-checks.

## Installed command

The dependency-free characterization path is:

```text
bividi-calib camera-imu ros1-bag --self-test
```

A real export is invoked as:

```text
bividi-calib camera-imu ros1-bag <prepared-bundle> [--output kalibr_dynamic.bag]
```

The legacy `tools/write_kalibr_rosbag.py` path remains as a thin compatibility wrapper around the installed implementation.

## Input contract

The writer consumes an already-prepared dynamic-session bundle. It requires:

- `session.json` with schema `bividi.calibration.kalibr_dynamic_session.v1`;
- `rosbag-recipe.json` with schema `bividi.calibration.kalibr_rosbag_recipe.v1`;
- staged camera A and camera B CSV indexes containing `timestamp_ns,image_path`;
- staged IMU CSV containing `timestamp_ns,omega_x,omega_y,omega_z,alpha_x,alpha_y,alpha_z`.

Per-stream timestamps must be strictly increasing. IMU values must be finite. These structural checks are performed before the external ROS1 writer runtime is required.

## Timestamp and merge semantics

The staged device-domain timestamp is authoritative for transport. For every emitted ROS message, the writer uses the same timestamp for both:

```text
message.header.stamp
bag record timestamp
```

Host arrival time is not substituted. Nanoseconds are converted with an exact `divmod(timestamp_ns, 1_000_000_000)` split, and negative timestamps are rejected.

The three staged streams are merged deterministically by timestamp. Equal timestamps retain the declared stream order used by the existing implementation: camera A, camera B, then IMU. The transport layer does not estimate or adjust camera↔IMU time offset.

## ROS message transport

Camera frames are decoded as grayscale and emitted as `sensor_msgs/Image` with `mono8` encoding. IMU rows are emitted as `sensor_msgs/Imu` using the already-staged SI-unit angular velocity and linear acceleration values.

Because orientation and covariance estimates are not supplied by this transport, the existing compatibility behavior is preserved: element zero of orientation, angular-velocity, and linear-acceleration covariance arrays is set to `-1.0`.

## External runtime boundary

Real bag generation requires ROS1 `rosbag`, `rospy`, `sensor_msgs`, and OpenCV Python bindings. Those imports remain lazy. Ordinary Bividi installation, package tests, and native CI intentionally do not install ROS1.

A missing ROS1/OpenCV runtime is therefore an external-runtime/domain error. It is not evidence that a calibration failed, and it is not an evaluated quality disposition.

The package-native self-test remains dependency-free because it exercises timestamp splitting, CSV parsing, strict monotonicity, and deterministic stream merging without opening a ROS bag.

## Exit vocabulary

The package adapter follows the frozen calibration command vocabulary:

```text
0  successful self-test or completed transport export
2  usage, input/schema/CSV, external-runtime/dependency, read, or write error
```

This transport command never returns `3`. Exit `3` is reserved for a completed explicit evidence/policy evaluation that returns FAIL, and ROS bag generation performs no such evaluation.

## Policy and architecture boundary

The command contract records:

```text
output_role = interop-transport-artifact
policy_role = external-runtime-transport-no-acceptance-gate
evaluated_fail_exit = none
```

No calibration threshold, transform, time offset, noise parameter, or promotion state is created by this adapter. The prepared Bividi session/evidence remains the source of truth; ROS message and bag metadata are interoperability representations only.

## Validation scope

The package migration is covered by sandbox and native-CI checks for source-independent CLI routing, package and legacy-wrapper self-tests, frozen schemas, timestamp splitting, strict per-stream ordering, deterministic cross-stream merge order, non-finite IMU rejection, schema failure before ROS1 import, and `0/2` exit normalization.

Those tests validate the package and transport contract. They do **not** claim that a real ROS1 installation, a physical Nori capture, or an upstream Kalibr solve was executed in CI.
