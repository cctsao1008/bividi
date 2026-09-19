# Package-native ROS2/MCAP calibration interoperability transport

`bividi-calib camera-imu ros2-mcap` is the installed-package entry point for exporting a prepared Bividi camera↔IMU dynamic session into ROS2 `rosbag2` with MCAP storage.

ROS2/MCAP is an interoperability and replay transport. It is not a Bividi calibration/evidence schema and it is not the authoritative input to upstream `ethz-asl/kalibr`. The upstream Kalibr solver boundary remains the separate ROS1 compatibility transport; Bividi's staged session and evidence remain authoritative in both cases.

## Installed command

The dependency-free characterization path is:

```text
bividi-calib camera-imu ros2-mcap --self-test
```

A real export is invoked as:

```text
bividi-calib camera-imu ros2-mcap <prepared-bundle> \
  [--output-uri <rosbag2-uri>] \
  [--camera-a-topic /cam0/image_raw] \
  [--camera-b-topic /cam1/image_raw] \
  [--imu-topic /imu0] \
  [--manifest-out <path>]
```

The legacy `tools/write_ros2_calibration_mcap.py` path remains a thin compatibility wrapper around the installed implementation.

## Input and shared staging contract

The exporter requires `session.json` with schema:

```text
bividi.calibration.kalibr_dynamic_session.v1
```

The session's staged map must resolve camera A, camera B, and IMU CSV files. The package implementation reuses the package-native ROS1 compatibility module only for the common staged-data primitives:

- camera CSV parsing and strict per-stream timestamp monotonicity;
- IMU CSV parsing, finite-value checks, and strict monotonicity;
- deterministic cross-stream merge ordering;
- nanosecond timestamp splitting.

This is code reuse, not a ROS1 dependency. ROS1 is not imported when the ROS2/MCAP path runs.

## Topic and storage semantics

Default topics remain:

```text
/cam0/image_raw
/cam1/image_raw
/imu0
```

Topic names are normalized to a leading slash, must be non-empty, and the two camera topics plus IMU topic must be distinct. Existing output is never overwritten: the exporter rejects either an existing output URI or an existing `<uri>.mcap` path.

The rosbag2 writer uses:

```text
storage_id = mcap
serialization_format = cdr
```

The implementation preserves compatibility with multiple common `rosbag2_py.TopicMetadata` constructor revisions.

## Timestamp contract

The staged device-domain timestamp remains authoritative. Each ROS2 message header and each rosbag2 record use the same numeric timestamp. The export manifest records:

```text
message_timestamp = Bividi staged device-domain timestamp in nanoseconds
rosbag2_record_timestamp = same numeric timestamp as message header.stamp
host_arrival_time_used = false
```

The transport performs no camera↔IMU time-offset estimation or correction.

## Message transport

Camera frames are decoded as grayscale and emitted as `sensor_msgs/msg/Image` with `mono8` encoding. IMU values are emitted as `sensor_msgs/msg/Imu` using the staged SI-unit angular velocity and linear acceleration values. Existing covariance sentinel behavior is preserved: element zero of unavailable orientation, angular-velocity, and linear-acceleration covariance arrays is `-1.0`.

All three streams must produce at least one message. An empty exported stream is a transport/domain error.

## Versioned export manifest

A successful export writes a Bividi sidecar manifest with schema:

```text
bividi.calibration.ros2_mcap_export.v1
```

Historical provenance remains:

```text
tool = write_ros2_calibration_mcap.py
tool_version = 1
```

The manifest preserves the source-session SHA-256, rosbag2/MCAP storage description, topic/type metadata, timestamp contract, per-stream message counts, and status:

```text
written_for_ros2_interoperability_not_authoritative_kalibr_input
```

Its architecture note explicitly states that ROS2/MCAP is interoperability transport while official upstream Kalibr uses the separate ROS1 compatibility adapter.

## External runtime boundary

Real export requires OpenCV Python bindings, `rosbag2_py`, `rclpy`, `sensor_msgs`, and the rosbag2 MCAP storage plugin. Those dependencies remain lazy and external. Normal Bividi CI intentionally does not install ROS2.

Missing ROS2/OpenCV/plugin runtime, writer-open failures, serialization/write failures, schema/topic/input errors, and output write failures are transport/domain failures. They are not calibration-quality FAIL states.

## Exit vocabulary

The package adapter follows the frozen command vocabulary:

```text
0  successful self-test or completed ROS2/MCAP export
2  usage, input/schema/topic, external-runtime/dependency, read, or write error
```

The command never returns evaluated-fail `3`, because transport generation does not apply an evidence acceptance policy.

## Command contract

The package contract records:

```text
output_role = interop-transport-and-machine-manifest
policy_role = external-runtime-transport-no-acceptance-gate
emits_versioned_provenance = true
tool_version = 1
evaluated_fail_exit = none
```

No calibration transform, time offset, IMU parameter, threshold, quality disposition, or promotion state is created by this adapter.

## Validation scope

Sandbox preflight validates the pure transport boundary before PR: topic normalization/rejection, staged-session/schema/file resolution, common stream merge behavior, TopicMetadata API compatibility, and dependency-independent semantics. Package tests also use a fake ROS2 runtime to exercise the real writer path through message creation, timestamp ordering, storage/topic setup, source-session hashing, message counts, and export-manifest fields without installing ROS2.

Native Ubuntu and Windows CI remain the second validation layer. Neither sandbox nor ordinary CI claims execution of a physical Nori capture or a real ROS2/MCAP installation.
