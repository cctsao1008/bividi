# ROS2 / MCAP Calibration Transport

Owner: Issue #47  
Status: ROS2/MCAP interoperability adapter implemented; physical AR0234 validation pending

## Purpose

Bividi calibration is **not** a ROS1 architecture.

The authoritative data contract remains the provenance-bound Bividi calibration session:

```text
lossless camera images
frames.csv with explicit ES/EE-derived camera timestamp semantic
raw/calibrated IMU evidence
session.json + SHA-256 provenance
```

Transport formats are adapters around that evidence:

```text
Bividi calibration session
        |
        +--> ROS2 rosbag2 / MCAP
        |       modern robotics transport / replay / inspection
        |
        +--> ROS1 .bag
                compatibility adapter for upstream ethz-asl/kalibr
```

ROS1 therefore exists only at the legacy external-solver boundary. It is not the Bividi core model, preferred robotics runtime, or long-term recording contract.

## Why keep the ROS1 adapter?

The pinned authoritative backend for #47 remains upstream `ethz-asl/kalibr`. Its IMU-camera workflow consumes ROS1 bag input. Replacing the solver merely to remove ROS1 from the transport boundary would trade a known reference implementation for an insufficiently validated backend change.

The correct separation is:

```text
solver authority != transport preference
```

Bividi can use modern ROS2/MCAP transport while retaining a small ROS1 conversion adapter specifically for the upstream solver.

## ROS2 / MCAP writer

`tools/write_ros2_calibration_mcap.py` consumes the same staged bundle produced by `tools/prepare_kalibr_dynamic_session.py`:

```text
session.json
camera_a.csv
camera_b.csv
imu0.csv
lossless mono camera images
```

The writer uses ROS2 `rosbag2_py` with explicit storage id:

```text
mcap
```

and emits standard ROS2 message types:

```text
/cam0/image_raw   sensor_msgs/msg/Image   mono8
/cam1/image_raw   sensor_msgs/msg/Image   mono8
/imu0             sensor_msgs/msg/Imu
```

Topic names may be overridden explicitly.

Example:

```bash
python tools/write_ros2_calibration_mcap.py \
  ar0234_kalibr_001 \
  --output-uri ar0234_kalibr_001/ros2_calibration
```

The output URI is a rosbag2 storage URI. The MCAP storage plugin owns the exact on-disk file/layout convention.

A sidecar is also written:

```text
<output-uri>.bividi-export.json
```

It records the source session hash, transport/storage identity, topics, timestamp contract, and message counts. It intentionally does not replace the source `session.json` provenance.

## Timestamp contract

The adapter preserves the staged Bividi sensor timestamp numerically:

```text
camera message header.stamp
    = staged camera timestamp chosen during Kalibr session preparation

IMU message header.stamp
    = extended DECXIN IMU device timestamp

rosbag2 record timestamp
    = the same numeric timestamp used in header.stamp
```

Host-arrival time is not substituted for device timing.

The camera timestamp semantic remains whichever was explicitly selected during staging:

```text
exposure_start
exposure_midpoint
exposure_end
```

This matters because camera↔IMU time-offset sign and value are meaningful only relative to the exact camera time reference.

## Dependency boundary

ROS2 dependencies are loaded lazily by the writer:

```text
rosbag2_py
rclpy serialization
sensor_msgs
OpenCV Python bindings
rosbag2 MCAP storage plugin
```

Normal Bividi CI does not install a full ROS2 distribution. Instead, the dependency-free self-test validates staged-input parsing, topic rules, and deterministic merged sensor ordering on Linux and Windows.

A real MCAP write is a platform/environment integration test and must be run inside an installed ROS2 environment.

## Relationship to the ROS1 writer

`tools/write_kalibr_rosbag.py` remains intentionally narrow:

```text
Bividi staged bundle
        -> ROS1 .bag
        -> upstream ethz-asl/kalibr
```

Treat it as a **legacy solver transport adapter**, not a general recording architecture.

The preferred modern interoperability path is:

```text
Bividi staged/native evidence
        -> ROS2 rosbag2 / MCAP
```

The general Bividi recording contract also prefers MCAP while keeping the logical observation model container-independent.

## Future solver/backend equivalence

A ROS2-native Kalibr port may be evaluated later, but it must not silently replace the current reference backend.

Use the **same Bividi source session** to generate both transport/backend paths, then compare at least:

```text
T_cam_imu translation
T_cam_imu rotation
timeshift_cam_imu
camera reprojection residuals
gyroscope residuals
accelerometer residuals
multi-session repeatability
```

Only after backend equivalence is demonstrated should a ROS2-native solver be considered for promotion from experimental cross-check to reference backend.

## Non-goals

- ROS2 messages do not become the Bividi core calibration schema.
- MCAP does not become semantic truth.
- A successful ROS2 export does not validate camera/IMU synchronization.
- A successful ROS2-native solver run would not by itself establish equivalence with upstream Kalibr.
- The ROS1 compatibility adapter is not removed until the authoritative solver no longer requires it or an equivalent backend is validated.

Related: #11, #35, #47, #46.
