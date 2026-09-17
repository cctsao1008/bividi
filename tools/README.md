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
