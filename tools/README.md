# Tools

Host-side probes, capture utilities, calibration helpers, visualization, and characterization scripts belong here.

Tools may depend on platform-specific backends. Core observation semantics must not.

A tool is not authoritative evidence by itself; its output must identify enough context to reproduce the measurement it reports.

Calibration transport follows the same boundary:

```text
Bividi staged/native evidence
  -> write_ros2_calibration_mcap.py   modern ROS2/rosbag2 + MCAP interoperability
  -> write_kalibr_rosbag.py           legacy ROS1 compatibility for upstream ethz-asl/kalibr
```

Neither ROS1 nor ROS2 message types are Bividi's persistent calibration schema. Solver/backend changes must be evaluated separately from transport-format changes.

Camera↔IMU dynamic review is split by evidence class:

```text
analyze_camera_imu_excitation.py       common-time + multi-axis motion excitation evidence
import_kalibr_camera_imu.py            T_cam_imu + timeshift import
analyze_kalibr_solver_quality.py       normalized/physical optimizer residual evidence
review_camera_imu_time_offset.py       device-time temporal sanity evidence
compare_camera_imu_calibrations.py     independent-session repeatability evidence
```

Excitation, residual fit, temporal plausibility, and repeatability are related but are not interchangeable claims. In particular, the excitation analyzer reports directionality proxies rather than claiming formal estimator observability.