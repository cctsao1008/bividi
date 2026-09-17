# Kalibr Dynamic Camera↔IMU Session Laboratory

Owner: Issue #47  
Upstream: #35 live capture, #8 measured camera chain, measured #47 IMU evidence  
Downstream: external ETH Zurich Kalibr solve, then `bividi.calibration.camera_imu.v1` import/review  
Status: hardware-independent recorder/export contract implemented; physical AR0234 dynamic dataset pending hardware

## Purpose

This laboratory turns one synchronized Bividi stereo+IMU motion recording into a provenance-bound Kalibr input bundle without making ROS1 or Kalibr a Bividi Core/runtime dependency.

```text
Nori live stereo + embedded IMU
            ↓
bividi-nori-calib-record
            ↓
lossless dynamic capture
  frames.csv + mono PNG camera_a/camera_b
  imu.csv raw counts
  capture.json
            ↓
prepare_kalibr_dynamic_session.py
            ↓
verified raw→SI mapping
explicit camera timestamp semantic
camera_a/camera_b → cam0/cam1 mapping
            ↓
camchain.yaml + imu.yaml + target.yaml
camera indexes + calibrated imu0.csv
rosbag-recipe.json + session.json
            ↓
write_kalibr_rosbag.py   (external ROS1 environment)
            ↓
kalibr_dynamic.bag
            ↓
kalibr_calibrate_imu_camera
            ↓
T_ci + timeshift_cam_imu evidence
```

The staged bundle is **input evidence**, not a calibration result.

## Why the timestamp contract is explicit

Kalibr revision `1f60227442d25e36365ef5f72cd80b9666d73467` reads both image and IMU time from the ROS message `header.stamp` and sorts messages by that header time. The bag record timestamp is not the primary sensor timestamp used by the dataset readers.

Bividi therefore never maps host arrival time into Kalibr image/IMU time.

For each recorded stereo frame DECXIN preserves:

```text
exposure_start_extended_us
exposure_end_extended_us
```

The preparer requires one explicit image timestamp semantic:

```text
exposure_start
exposure_midpoint
exposure_end
```

Mapping to ROS header time is:

```text
start:      t_ns = ES_us * 1000
midpoint:   t_ns = (ES_us + EE_us) * 500
end:        t_ns = EE_us * 1000
```

The midpoint formula preserves half-microsecond resolution in integer nanoseconds.

Kalibr reports camera→IMU time shift using:

```text
t_imu = t_cam + shift
```

Bividi `bividi.calibration.camera_imu.v1` uses the same sign equation, but numeric import is only valid when the artifact records the same camera timestamp semantic used by the exported session.

## Transform convention

Kalibr's result text calls `T_ci` the transform **imu0 → cam_i**. Bividi can map this into a camera↔IMU artifact only when:

```text
transform.from_frame = imu frame
transform.to_frame   = matching camera frame
```

The exporter keeps DECXIN identities:

```text
camera_a → cam0
camera_b → cam1
```

It does **not** rename them left/right. Physical A/B ↔ left/right mapping remains a #35 measurement.

## Live recorder

When built with both the Nori SDK and OpenCV:

```bash
bividi-nori-calib-record \
  --device 0 \
  --mode 0 \
  --duration-s 120 \
  --warmup-frames 30 \
  --frame-stride 1 \
  --output-dir ar0234_dynamic_001
```

`device 0 / mode 0` are examples only; use `bividi-nori-probe` first.

The recorder writes:

```text
ar0234_dynamic_001/
  capture.json
  frames.csv
  imu.csv
  camera_a/*.png
  camera_b/*.png
```

Images are lossless `mono8` PNGs derived from the normalized BGR24 camera subviews. `frames.csv` keeps sequence, host receive provenance, SDK timestamp provenance, raw/extended ES+EE, and image paths. `imu.csv` keeps the full raw IMU stream with extended device timestamps and raw counts.

`--frame-stride N` may reduce camera disk volume while retaining every decoded IMU sample. The chosen stride is recorded in `capture.json`.

The recorder deliberately **does not choose** ES/midpoint/EE and **does not scale IMU raw counts**.

## Raw IMU → SI conversion

Kalibr expects:

```text
sensor_msgs/Imu.angular_velocity     rad/s
sensor_msgs/Imu.linear_acceleration  m/s^2
```

The preparer does not reuse DECXIN demo full-scale constants. Instead it requires the supplied IMU calibration-session manifest to bind:

```text
six_position
gyro_rotation
```

The six-position report provides:

```text
accelerometer bias_raw_counts
3×3 target_g_per_raw_count_matrix
```

The controlled-rotation report must have been created with a trusted angle reference so it provides:

```text
gyroscope bias_raw_counts
3×3 target_rad_s_per_raw_count_matrix
```

The export equation is recorded explicitly:

```text
target_si = matrix * (raw_counts - bias_raw_counts)
```

Accelerometer `g/count` is multiplied by `9.80665` to produce `m/s²/count`.

If the gyro report has no absolute matrix, preparation fails rather than falling back to a nominal range.

## Measured IMU artifact

A promoted measured `bividi.calibration.imu.v1` artifact supplies Kalibr's noise model:

```text
accelerometer_noise_density
accelerometer_random_walk
gyroscope_noise_density
gyroscope_random_walk
update_rate
```

The preparer also verifies that a measured artifact's `provenance.source_hash` matches the supplied IMU calibration-session manifest. This prevents a numerically valid noise artifact from being combined silently with a different specimen/session.

## AprilGrid

The dynamic session uses an explicit AprilGrid definition:

```text
tagCols
tagRows
tagSize      metres
tagSpacing   gap/tag-size ratio
```

Example syntax only:

```bash
--tag-cols 6 \
--tag-rows 6 \
--tag-size-m 0.088 \
--tag-spacing 0.3
```

Those numbers are not a Bividi recommendation; use the actual printed/measured target.

## Prepare the bundle

```bash
python tools/prepare_kalibr_dynamic_session.py \
  ar0234_dynamic_001/capture.json \
  --imu-session ar0234_imu_session.json \
  --imu-calibration ar0234_imu_calibration.json \
  --camchain ar0234_camchain.yaml \
  --camera-time-reference exposure_midpoint \
  --tag-cols 6 \
  --tag-rows 6 \
  --tag-size-m 0.088 \
  --tag-spacing 0.3 \
  --output-dir ar0234_kalibr_001
```

The supplied `camchain.yaml` must contain:

```text
cam0.rostopic = /cam0/image_raw
cam1.rostopic = /cam1/image_raw
```

unless matching topic overrides are passed explicitly.

The prepared directory contains:

```text
session.json
camera_a.csv
camera_b.csv
imu0.csv
camchain.yaml
imu.yaml
target.yaml
rosbag-recipe.json
kalibr-command.txt
```

`session.json` is `bividi.calibration.kalibr_dynamic_session.v1` and hashes all critical upstream evidence.

## ROS1 bag adapter

Kalibr's IMU-camera CLI requires a ROS bag. Bividi keeps bag creation external:

```bash
python tools/write_kalibr_rosbag.py ar0234_kalibr_001
```

This script lazily imports:

```text
rosbag
rospy
sensor_msgs
cv2
```

Normal Bividi CI does not install those packages. Run the adapter in a ROS1/Kalibr environment.

The writer publishes:

```text
/cam0/image_raw   sensor_msgs/Image mono8
/cam1/image_raw   sensor_msgs/Image mono8
/imu0             sensor_msgs/Imu
```

`header.stamp` and bag record time are set to the same prepared sensor timestamp. The bag writer streams/merges the three CSV indexes rather than loading the entire high-rate session into memory.

## Run Kalibr

The bundle records the exact command:

```bash
kalibr_calibrate_imu_camera \
  --bag kalibr_dynamic.bag \
  --cams camchain.yaml \
  --imu imu.yaml \
  --target target.yaml
```

Temporal calibration remains enabled unless the operator explicitly disables it in Kalibr.

## Guardrails

- `host_receive_monotonic_ns` is provenance, not the Kalibr sensor timestamp.
- ES/EE are preserved independently before the operator selects one image-time semantic.
- `camera_a`/`camera_b` do not imply left/right.
- Raw IMU conversion requires measured/hash-bound experiment evidence; vendor-demo scale constants are not accepted.
- A staged bundle is not a successful Kalibr solve.
- A successful Kalibr solve is not automatically a promoted Bividi artifact; transform direction, timestamp semantic, protocol timing evidence, target extraction quality, solver report, and provenance still require review.
- ROS1/Kalibr remain outside Bividi Core and normal runtime/CI.

## Source-contract audit

The adapter contract was checked against Kalibr revision `1f60227442d25e36365ef5f72cd80b9666d73467`:

```text
kalibr_calibrate_imu_camera
  requires --bag and camera/IMU/target YAML inputs

kalibr_common/ImageDatasetReader.py
  sorts/reads image time from data.header.stamp
  accepts sensor_msgs/Image / CompressedImage

kalibr_common/ImuDatasetReader.py
  sorts/reads IMU time from data.header.stamp
  reads angular_velocity and linear_acceleration

kalibr_imu_camera_calibration/IccUtil.py
  T_ci = imu0 → cam_i
  timeshift: t_imu = t_cam + shift
```

If a future Kalibr revision changes these contracts, update the adapter before changing Bividi's persistent calibration semantics.

Related: #35, #8, #47, #46.
