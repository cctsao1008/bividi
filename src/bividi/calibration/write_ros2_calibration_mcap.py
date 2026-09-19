#!/usr/bin/env python3
"""Write a ROS2 rosbag2/MCAP recording from a prepared Bividi calibration bundle.

This is a transport/interoperability adapter. Bividi's staged camera/IMU evidence
and session manifest remain the source of truth; ROS2 and MCAP are not core
calibration schemas. ROS2 dependencies are imported lazily so normal Bividi CI
remains dependency-free.

The authoritative ETH Zurich Kalibr backend still consumes a ROS1 bag. Use
write_kalibr_rosbag.py only at that legacy solver boundary. This adapter exists
for modern ROS2/rosbag2 tooling, replay, inspection, and future backend
cross-checks without making ROS1 the Bividi architecture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from . import write_kalibr_rosbag as staged

SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
EXPORT_SCHEMA = "bividi.calibration.ros2_mcap_export.v1"
TOOL_VERSION = "1"
DEFAULT_CAMERA_A_TOPIC = "/cam0/image_raw"
DEFAULT_CAMERA_B_TOPIC = "/cam1/image_raw"
DEFAULT_IMU_TOPIC = "/imu0"


class Ros2McapExportError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Ros2McapExportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise Ros2McapExportError(f"{path}: expected JSON object")
    return data


def normalize_topic(topic: str) -> str:
    value = topic.strip()
    if not value or value == "/":
        raise Ros2McapExportError("ROS2 topic must be non-empty")
    return value if value.startswith("/") else "/" + value


def resolve_staged_inputs(bundle: Path) -> tuple[Path, dict[str, Any], Path, Path, Path]:
    session_path = bundle / "session.json"
    session = load_json(session_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise Ros2McapExportError(f"{session_path}: unsupported schema {session.get('schema')!r}")
    staged_map = session.get("staged")
    if not isinstance(staged_map, dict):
        raise Ros2McapExportError(f"{session_path}: missing staged artifact map")

    def staged_path(key: str) -> Path:
        raw = staged_map.get(key)
        if not isinstance(raw, str) or not raw:
            raise Ros2McapExportError(f"{session_path}: staged.{key} is required")
        path = (bundle / raw).resolve()
        if not path.is_file():
            raise Ros2McapExportError(f"{session_path}: staged.{key} file does not exist: {path}")
        return path

    return (
        session_path,
        session,
        staged_path("camera_a_csv"),
        staged_path("camera_b_csv"),
        staged_path("imu_csv"),
    )


def topic_metadata(rosbag2_py: Any, name: str, type_name: str) -> Any:
    """Construct TopicMetadata across common rosbag2 Python API revisions."""
    variants = [
        {"name": name, "type": type_name, "serialization_format": "cdr"},
        {
            "name": name,
            "type": type_name,
            "serialization_format": "cdr",
            "offered_qos_profiles": "",
        },
        {
            "id": 0,
            "name": name,
            "type": type_name,
            "serialization_format": "cdr",
            "offered_qos_profiles": "",
            "type_description_hash": "",
        },
    ]
    errors: list[str] = []
    for kwargs in variants:
        try:
            return rosbag2_py.TopicMetadata(**kwargs)
        except TypeError as exc:
            errors.append(str(exc))
    raise Ros2McapExportError("unsupported rosbag2_py.TopicMetadata API: " + " | ".join(errors))


def write_ros2_mcap(
    bundle: Path,
    output_uri: Path,
    *,
    camera_a_topic: str,
    camera_b_topic: str,
    imu_topic: str,
) -> dict[str, Any]:
    session_path, session, camera_a_csv, camera_b_csv, imu_csv = resolve_staged_inputs(bundle)
    camera_a_topic = normalize_topic(camera_a_topic)
    camera_b_topic = normalize_topic(camera_b_topic)
    imu_topic = normalize_topic(imu_topic)
    if len({camera_a_topic, camera_b_topic, imu_topic}) != 3:
        raise Ros2McapExportError("camera_a, camera_b, and IMU topics must be distinct")

    if output_uri.exists() or Path(str(output_uri) + ".mcap").exists():
        raise Ros2McapExportError(f"refusing to overwrite existing rosbag2/MCAP output: {output_uri}")

    try:
        import cv2  # type: ignore
        import rosbag2_py  # type: ignore
        from rclpy.serialization import serialize_message  # type: ignore
        from sensor_msgs.msg import Image, Imu  # type: ignore
    except ImportError as exc:
        raise Ros2McapExportError(
            "ROS2 rosbag2_py/rclpy/sensor_msgs, the rosbag2 MCAP storage plugin, and OpenCV Python "
            "bindings are required. Run this adapter in a ROS2 environment; normal Bividi CI "
            "intentionally does not install ROS2."
        ) from exc

    writer = rosbag2_py.SequentialWriter()
    try:
        storage_options = rosbag2_py.StorageOptions(uri=str(output_uri), storage_id="mcap")
        converter_options = rosbag2_py.ConverterOptions("", "")
        writer.open(storage_options, converter_options)
        writer.create_topic(topic_metadata(rosbag2_py, camera_a_topic, "sensor_msgs/msg/Image"))
        writer.create_topic(topic_metadata(rosbag2_py, camera_b_topic, "sensor_msgs/msg/Image"))
        writer.create_topic(topic_metadata(rosbag2_py, imu_topic, "sensor_msgs/msg/Imu"))
    except Exception as exc:  # rosbag2_py exposes backend/plugin failures as RuntimeError variants.
        raise Ros2McapExportError(f"cannot open ROS2 MCAP writer at {output_uri}: {exc}") from exc

    topics = {
        "camera_a": camera_a_topic,
        "camera_b": camera_b_topic,
        "imu": imu_topic,
    }
    counts = {"camera_a": 0, "camera_b": 0, "imu": 0}
    streams = [
        iter(staged.image_rows(camera_a_csv, "camera_a")),
        iter(staged.image_rows(camera_b_csv, "camera_b")),
        iter(staged.imu_rows(imu_csv)),
    ]

    for stamp_ns, kind, row in staged.merge_streams(streams):
        sec, nanosec = staged.split_ns(stamp_ns)
        if kind in ("camera_a", "camera_b"):
            image_path = Path(row["image_path"])
            image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
            if image is None or len(image.shape) != 2:
                raise Ros2McapExportError(f"cannot decode mono image {image_path}")
            msg = Image()
            msg.header.stamp.sec = int(sec)
            msg.header.stamp.nanosec = int(nanosec)
            msg.header.frame_id = kind
            msg.height = int(image.shape[0])
            msg.width = int(image.shape[1])
            msg.encoding = "mono8"
            msg.is_bigendian = 0
            msg.step = msg.width
            msg.data = image.tobytes()
        else:
            msg = Imu()
            msg.header.stamp.sec = int(sec)
            msg.header.stamp.nanosec = int(nanosec)
            msg.header.frame_id = "imu"
            msg.angular_velocity.x = float(row["omega_x"])
            msg.angular_velocity.y = float(row["omega_y"])
            msg.angular_velocity.z = float(row["omega_z"])
            msg.linear_acceleration.x = float(row["alpha_x"])
            msg.linear_acceleration.y = float(row["alpha_y"])
            msg.linear_acceleration.z = float(row["alpha_z"])
            msg.orientation_covariance[0] = -1.0
            msg.angular_velocity_covariance[0] = -1.0
            msg.linear_acceleration_covariance[0] = -1.0
        try:
            writer.write(topics[kind], serialize_message(msg), stamp_ns)
        except Exception as exc:
            raise Ros2McapExportError(f"rosbag2 write failed for {kind} at {stamp_ns} ns: {exc}") from exc
        counts[kind] += 1

    if any(value == 0 for value in counts.values()):
        raise Ros2McapExportError(f"empty ROS2 stream after export: {counts}")

    camera_time = session.get("camera_time_reference")
    return {
        "schema": EXPORT_SCHEMA,
        "tool": "write_ros2_calibration_mcap.py",
        "tool_version": TOOL_VERSION,
        "status": "written_for_ros2_interoperability_not_authoritative_kalibr_input",
        "source_session": {"path": str(session_path), "sha256": sha256_file(session_path)},
        "storage": {
            "framework": "ROS2 rosbag2",
            "storage_id": "mcap",
            "uri": str(output_uri),
            "serialization_format": "cdr",
        },
        "topics": {
            "camera_a": {"name": camera_a_topic, "type": "sensor_msgs/msg/Image", "encoding": "mono8"},
            "camera_b": {"name": camera_b_topic, "type": "sensor_msgs/msg/Image", "encoding": "mono8"},
            "imu": {"name": imu_topic, "type": "sensor_msgs/msg/Imu", "units": "rad/s, m/s^2"},
        },
        "timestamp_contract": {
            "camera_reference": camera_time.get("kind") if isinstance(camera_time, dict) else None,
            "message_timestamp": "Bividi staged device-domain timestamp in nanoseconds",
            "rosbag2_record_timestamp": "same numeric timestamp as message header.stamp",
            "host_arrival_time_used": False,
        },
        "messages": counts,
        "architecture_note": (
            "ROS2/MCAP is an interoperability transport. Bividi session evidence remains authoritative; "
            "official ethz-asl/kalibr currently uses the separate ROS1 compatibility adapter."
        ),
    }


def write_fixture(root: Path) -> Path:
    bundle = root / "bundle"
    bundle.mkdir()
    (bundle / "camera_a.csv").write_text(
        "timestamp_ns,image_path,frame_index,frame_sequence\n100,a.png,0,10\n300,a2.png,1,11\n",
        encoding="utf-8",
    )
    (bundle / "camera_b.csv").write_text(
        "timestamp_ns,image_path,frame_index,frame_sequence\n100,b.png,0,10\n300,b2.png,1,11\n",
        encoding="utf-8",
    )
    (bundle / "imu0.csv").write_text(
        "timestamp_ns,omega_x,omega_y,omega_z,alpha_x,alpha_y,alpha_z\n"
        "200,0,0,0,0,0,9.8\n400,0,0,0,0,0,9.8\n",
        encoding="utf-8",
    )
    (bundle / "session.json").write_text(
        json.dumps(
            {
                "schema": SESSION_SCHEMA,
                "camera_time_reference": {
                    "kind": "exposure_midpoint",
                    "time_shift_definition": "t_imu_s = t_camera_reference_s + offset_s",
                },
                "staged": {
                    "camera_a_csv": "camera_a.csv",
                    "camera_b_csv": "camera_b.csv",
                    "imu_csv": "imu0.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    return bundle


def self_test() -> None:
    assert normalize_topic("cam0/image_raw") == "/cam0/image_raw"
    assert normalize_topic("/imu0") == "/imu0"
    try:
        normalize_topic(" ")
    except Ros2McapExportError:
        pass
    else:
        raise AssertionError("empty topic was not rejected")

    with tempfile.TemporaryDirectory() as tmp:
        bundle = write_fixture(Path(tmp))
        _, _, camera_a, camera_b, imu = resolve_staged_inputs(bundle)
        merged = [
            (stamp, kind)
            for stamp, kind, _ in staged.merge_streams(
                [
                    iter(staged.image_rows(camera_a, "camera_a")),
                    iter(staged.image_rows(camera_b, "camera_b")),
                    iter(staged.imu_rows(imu)),
                ]
            )
        ]
        assert merged == [
            (100, "camera_a"),
            (100, "camera_b"),
            (200, "imu"),
            (300, "camera_a"),
            (300, "camera_b"),
            (400, "imu"),
        ]
    print("ROS2 calibration MCAP adapter self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", nargs="?", type=Path)
    parser.add_argument("--output-uri", type=Path)
    parser.add_argument("--camera-a-topic", default=DEFAULT_CAMERA_A_TOPIC)
    parser.add_argument("--camera-b-topic", default=DEFAULT_CAMERA_B_TOPIC)
    parser.add_argument("--imu-topic", default=DEFAULT_IMU_TOPIC)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.bundle is None:
        print("bundle directory is required", file=sys.stderr)
        return 2
    bundle = args.bundle.resolve()
    output_uri = (args.output_uri or (bundle / "ros2_calibration")).resolve()
    try:
        report = write_ros2_mcap(
            bundle,
            output_uri,
            camera_a_topic=args.camera_a_topic,
            camera_b_topic=args.camera_b_topic,
            imu_topic=args.imu_topic,
        )
        manifest_out = args.manifest_out or Path(str(output_uri) + ".bividi-export.json")
        manifest_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (Ros2McapExportError, OSError, KeyError, ValueError) as exc:
        print(f"ROS2 calibration MCAP export failed: {exc}", file=sys.stderr)
        return 3
    print(
        json.dumps(
            {
                "status": report["status"],
                "storage_uri": report["storage"]["uri"],
                "storage_id": report["storage"]["storage_id"],
                "messages": report["messages"],
                "manifest": str(manifest_out.resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
