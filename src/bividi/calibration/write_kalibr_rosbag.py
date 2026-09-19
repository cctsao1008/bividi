#!/usr/bin/env python3
"""Write a ROS1 bag from a prepared Bividi Kalibr dynamic-session bundle.

ROS1 dependencies are imported lazily so normal Bividi CI remains dependency-free.
Kalibr's readers consume sensor_msgs/Image and sensor_msgs/Imu header.stamp; this
writer deliberately uses the same timestamp as both header.stamp and bag record
time. Images are emitted as mono8. IMU values are already staged in SI units.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator, Sequence

SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
RECIPE_SCHEMA = "bividi.calibration.kalibr_rosbag_recipe.v1"


class BagExportError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BagExportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BagExportError(f"{path}: expected JSON object")
    return data


def split_ns(timestamp_ns: int) -> tuple[int, int]:
    if timestamp_ns < 0:
        raise BagExportError("negative ROS timestamp")
    return divmod(timestamp_ns, 1_000_000_000)


def image_rows(path: Path, stream_name: str) -> Iterator[tuple[int, str, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp_ns", "image_path"}
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise BagExportError(f"{path}: missing timestamp_ns/image_path")
        previous = None
        for line, row in enumerate(reader, start=2):
            try:
                stamp = int(row["timestamp_ns"], 10)
            except ValueError as exc:
                raise BagExportError(f"{path}:{line}: invalid timestamp_ns") from exc
            if previous is not None and stamp <= previous:
                raise BagExportError(f"{path}:{line}: non-increasing timestamp")
            previous = stamp
            yield stamp, stream_name, row


def imu_rows(path: Path) -> Iterator[tuple[int, str, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"timestamp_ns", "omega_x", "omega_y", "omega_z", "alpha_x", "alpha_y", "alpha_z"}
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise BagExportError(f"{path}: missing staged IMU columns")
        previous = None
        for line, row in enumerate(reader, start=2):
            try:
                stamp = int(row["timestamp_ns"], 10)
                values = [float(row[key]) for key in ("omega_x", "omega_y", "omega_z", "alpha_x", "alpha_y", "alpha_z")]
            except ValueError as exc:
                raise BagExportError(f"{path}:{line}: invalid numeric field") from exc
            if not all(math.isfinite(value) for value in values):
                raise BagExportError(f"{path}:{line}: non-finite IMU value")
            if previous is not None and stamp <= previous:
                raise BagExportError(f"{path}:{line}: non-increasing timestamp")
            previous = stamp
            yield stamp, "imu", row


def merge_streams(iterators: Sequence[Iterator[tuple[int, str, dict[str, str]]]]) -> Iterator[tuple[int, str, dict[str, str]]]:
    heap: list[tuple[int, int, str, dict[str, str], Iterator[tuple[int, str, dict[str, str]]]]] = []
    for order, iterator in enumerate(iterators):
        try:
            stamp, kind, row = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(heap, (stamp, order, kind, row, iterator))
    while heap:
        stamp, order, kind, row, iterator = heapq.heappop(heap)
        yield stamp, kind, row
        try:
            next_stamp, next_kind, next_row = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(heap, (next_stamp, order, next_kind, next_row, iterator))


def write_bag(bundle: Path, output: Path) -> dict[str, int]:
    session_path = bundle / "session.json"
    recipe_path = bundle / "rosbag-recipe.json"
    session = load_json(session_path)
    recipe = load_json(recipe_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise BagExportError(f"{session_path}: unsupported schema")
    if recipe.get("schema") != RECIPE_SCHEMA:
        raise BagExportError(f"{recipe_path}: unsupported schema")

    try:
        import cv2  # type: ignore
        import rosbag  # type: ignore
        import rospy  # type: ignore
        from sensor_msgs.msg import Image, Imu  # type: ignore
    except ImportError as exc:
        raise BagExportError(
            "ROS1 rosbag/rospy/sensor_msgs and OpenCV Python bindings are required. "
            "Run this adapter inside a ROS1/Kalibr environment; normal Bividi CI intentionally does not install them."
        ) from exc

    topics = recipe["topics"]
    camera_a_csv = bundle / topics["camera_a"]["index_csv"]
    camera_b_csv = bundle / topics["camera_b"]["index_csv"]
    imu_csv = bundle / topics["imu"]["csv"]
    counts = {"camera_a": 0, "camera_b": 0, "imu": 0}

    def ros_time(ns: int):
        sec, nsec = split_ns(ns)
        return rospy.Time(sec, nsec)

    with rosbag.Bag(str(output), "w") as bag:
        streams = [iter(image_rows(camera_a_csv, "camera_a")), iter(image_rows(camera_b_csv, "camera_b")), iter(imu_rows(imu_csv))]
        for stamp_ns, kind, row in merge_streams(streams):
            stamp = ros_time(stamp_ns)
            if kind in ("camera_a", "camera_b"):
                image_path = Path(row["image_path"])
                image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
                if image is None or len(image.shape) != 2:
                    raise BagExportError(f"cannot decode mono image {image_path}")
                msg = Image()
                msg.header.stamp = stamp
                msg.header.frame_id = kind
                msg.height = int(image.shape[0])
                msg.width = int(image.shape[1])
                msg.encoding = "mono8"
                msg.is_bigendian = 0
                msg.step = msg.width
                msg.data = image.tobytes()
                bag.write(topics[kind]["topic"], msg, stamp)
            else:
                msg = Imu()
                msg.header.stamp = stamp
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
                bag.write(topics["imu"]["topic"], msg, stamp)
            counts[kind] += 1
    return counts


def self_test() -> None:
    assert split_ns(1_234_567_890) == (1, 234_567_890)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = root / "a.csv"
        b = root / "b.csv"
        imu = root / "imu.csv"
        a.write_text("timestamp_ns,image_path\n100,a.png\n300,a2.png\n", encoding="utf-8")
        b.write_text("timestamp_ns,image_path\n100,b.png\n300,b2.png\n", encoding="utf-8")
        imu.write_text("timestamp_ns,omega_x,omega_y,omega_z,alpha_x,alpha_y,alpha_z\n200,0,0,0,0,0,9.8\n400,0,0,0,0,0,9.8\n", encoding="utf-8")
        merged = [(stamp, kind) for stamp, kind, _ in merge_streams([iter(image_rows(a, "camera_a")), iter(image_rows(b, "camera_b")), iter(imu_rows(imu))])]
        assert merged == [(100, "camera_a"), (100, "camera_b"), (200, "imu"), (300, "camera_a"), (300, "camera_b"), (400, "imu")]
    print("Kalibr ROS1 bag writer self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
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
    output = args.output or (args.bundle / "kalibr_dynamic.bag")
    try:
        counts = write_bag(args.bundle.resolve(), output.resolve())
    except (BagExportError, OSError, KeyError) as exc:
        print(f"Kalibr ROS bag export failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"bag": str(output.resolve()), "messages": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
