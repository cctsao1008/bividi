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
export_kalibr_target_observations.py   exact pinned-Kalibr AprilGrid corner export
analyze_kalibr_target_coverage.py      target-ID/image-plane/stereo visual coverage evidence
import_kalibr_camera_imu.py            T_cam_imu + timeshift import
analyze_kalibr_solver_quality.py       normalized/physical optimizer residual evidence
review_camera_imu_time_offset.py       device-time temporal sanity evidence
compare_camera_imu_calibrations.py     independent-session repeatability evidence
camera_imu_calibration_provenance.py   final hash-bound integrity/review/promotion gate
plan_camera_imu_physical_campaign.py   specimen-specific physical campaign plan + artifact audit
```

The target-observation exporter is the only one of the two visual-coverage tools that requires the external Kalibr runtime; the coverage analyzer is standard-library-only. The exporter deliberately reuses Kalibr's `GridDetector` observation surface rather than introducing an independent AprilTag detector with potentially different corner semantics.

Inertial excitation, target/image-plane coverage, residual fit, temporal plausibility, and repeatability are related but are not interchangeable claims. The excitation and coverage analyzers report evidence/proxies rather than claiming formal estimator observability.

The final provenance gate does not invent or duplicate numeric limits. Component analyzers own their explicit thresholds; the `promotion` profile only accepts evidence that is hash-consistent, explicitly gated, `PASS`, and tied to a named lab/product acceptance policy.

The physical campaign planner sits one level above those tools. It orders the live-hardware workflow and audits expected artifact presence/schema, but deliberately does not duplicate hashes, quality thresholds, external solver logic, or promotion decisions.