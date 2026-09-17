#!/usr/bin/env python3
"""Prepare a provenance-bound Bividi camera+IMU session for ETH Zurich Kalibr.

The tool remains dependency-free and does not write a ROS bag itself. It verifies
source hashes/specimen identity, converts raw IMU counts with hash-bound measured
axis/scale evidence, chooses one explicit camera timestamp semantic, and stages
Kalibr imu.yaml / target.yaml plus camera and IMU indexes for an external ROS1
bag writer.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

CAPTURE_SCHEMA = "bividi.nori.camera_imu_dynamic_trace.v1"
IMU_SESSION_SCHEMA = "bividi.calibration.imu_session_manifest.v1"
IMU_ARTIFACT_SCHEMA = "bividi.calibration.imu.v1"
SIXPOS_SCHEMA = "bividi.calibration.imu_six_position_analysis.v1"
GYRO_SCHEMA = "bividi.calibration.imu_gyro_rotation_analysis.v1"
OUTPUT_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
GRAVITY_M_S2 = 9.80665
TOOL_VERSION = "1"
TIME_SHIFT_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"
CAMERA_TIME_REFERENCES = ("exposure_start", "exposure_midpoint", "exposure_end")


class ExportError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExportError(f"{path}: expected a JSON object")
    return value


def require_schema(data: dict[str, Any], schema: str, path: Path) -> None:
    if data.get("schema") != schema:
        raise ExportError(f"{path}: expected schema {schema!r}; got {data.get('schema')!r}")


def resolve(text: str, owner: Path) -> Path:
    path = Path(text)
    return path if path.is_absolute() else (owner.parent / path).resolve()


def require_measured(data: dict[str, Any], path: Path, allow_synthetic: bool) -> None:
    provenance = data.get("provenance")
    kind = provenance.get("kind") if isinstance(provenance, dict) else None
    if kind != "measured" and not allow_synthetic:
        raise ExportError(f"{path}: provenance.kind must be 'measured'; got {kind!r}")


def bound_analysis(manifest: dict[str, Any], manifest_path: Path, role: str, schema: str) -> tuple[Path, dict[str, Any]]:
    entries = manifest.get("analysis")
    if not isinstance(entries, list):
        raise ExportError(f"{manifest_path}: analysis must be an array")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("role") == role]
    if len(matches) != 1:
        raise ExportError(f"{manifest_path}: expected exactly one analysis role {role!r}; found {len(matches)}")
    entry = matches[0]
    if not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
        raise ExportError(f"{manifest_path}: analysis {role!r} lacks path/SHA-256")
    path = resolve(entry["path"], manifest_path)
    if not path.is_file():
        raise ExportError(f"{manifest_path}: missing analysis file {path}")
    if sha256_file(path) != entry["sha256"]:
        raise ExportError(f"{manifest_path}: analysis {role!r} SHA-256 mismatch")
    data = load_json(path)
    require_schema(data, schema, path)
    return path, data


def mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix) or len(vector) != 3:
        raise ExportError("expected a 3x3 matrix and 3-vector")
    result = [sum(float(a) * float(b) for a, b in zip(row, vector)) for row in matrix]
    if not all(math.isfinite(value) for value in result):
        raise ExportError("non-finite matrix result")
    return result


def raw_to_si_model(six: dict[str, Any], gyro: dict[str, Any]) -> dict[str, Any]:
    try:
        accel = six["accelerometer_gravity_model"]
        accel_bias = [float(v) for v in accel["bias_raw_counts"]]
        accel_g_matrix = [[float(v) for v in row] for row in accel["target_g_per_raw_count_matrix"]]
        gyro_bias = [float(v) for v in gyro["stationary_baseline"]["bias_raw_counts"]]
        gyro_matrix_raw = gyro["rotation_model"]["target_rad_s_per_raw_count_matrix"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ExportError("analysis reports lack required raw->target conversion evidence") from exc
    if gyro_matrix_raw is None:
        raise ExportError(
            "gyro report has no absolute target_rad_s_per_raw_count_matrix; rerun controlled rotation "
            "with a trusted --expected-angle-deg reference"
        )
    gyro_matrix = [[float(v) for v in row] for row in gyro_matrix_raw]
    accel_matrix = [[GRAVITY_M_S2 * v for v in row] for row in accel_g_matrix]
    mat_vec(accel_matrix, [0.0, 0.0, 0.0])
    mat_vec(gyro_matrix, [0.0, 0.0, 0.0])
    if len(accel_bias) != 3 or len(gyro_bias) != 3:
        raise ExportError("raw bias vectors must have three elements")
    return {
        "equation": "target_si = matrix * (raw_counts - bias_raw_counts)",
        "accelerometer_bias_raw_counts": accel_bias,
        "accelerometer_target_m_s2_per_raw_count_matrix": accel_matrix,
        "gyroscope_bias_raw_counts": gyro_bias,
        "gyroscope_target_rad_s_per_raw_count_matrix": gyro_matrix,
        "source": "hash-bound six_position + known-angle gyro_rotation analyses",
    }


def camera_timestamp_ns(row: dict[str, str], reference: str) -> int:
    try:
        start = int(row["exposure_start_extended_us"], 10)
        end = int(row["exposure_end_extended_us"], 10)
    except (KeyError, ValueError) as exc:
        raise ExportError("invalid exposure timestamp in frames CSV") from exc
    if end < start:
        raise ExportError("exposure end precedes exposure start")
    if reference == "exposure_start":
        return start * 1000
    if reference == "exposure_end":
        return end * 1000
    if reference == "exposure_midpoint":
        return (start + end) * 500
    raise ExportError(f"unsupported camera time reference {reference!r}")


def parse_camchain_topics(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        match = re.match(r"^(cam\d+)\s*:\s*$", line)
        if match:
            current = match.group(1)
            continue
        if current is not None:
            match = re.match(r"^\s+rostopic\s*:\s*(.+?)\s*$", line)
            if match:
                result[current] = match.group(1).strip().strip("'\"")
    return result


def write_imu_yaml(artifact: dict[str, Any], topic: str, output: Path) -> dict[str, Any]:
    try:
        noise = artifact["noise"]
        values = {
            "accelerometer_noise_density": float(noise["accelerometer_noise_density_m_s2_sqrt_hz"]),
            "accelerometer_random_walk": float(noise["accelerometer_bias_random_walk_m_s3_sqrt_hz"]),
            "gyroscope_noise_density": float(noise["gyroscope_noise_density_rad_s_sqrt_hz"]),
            "gyroscope_random_walk": float(noise["gyroscope_bias_random_walk_rad_s2_sqrt_hz"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ExportError("IMU artifact lacks all four Kalibr noise parameters") from exc
    timing = artifact.get("timing")
    imu = artifact.get("imu")
    if isinstance(timing, dict) and isinstance(timing.get("effective_rate_hz"), (int, float)):
        rate = float(timing["effective_rate_hz"])
        rate_source = "timing.effective_rate_hz"
    elif isinstance(imu, dict) and isinstance(imu.get("sample_rate_hz_measured"), (int, float)):
        rate = float(imu["sample_rate_hz_measured"])
        rate_source = "imu.sample_rate_hz_measured"
    else:
        raise ExportError("IMU artifact has no measured update rate")
    if rate <= 0 or not math.isfinite(rate) or any(v <= 0 or not math.isfinite(v) for v in values.values()):
        raise ExportError("Kalibr noise/rate values must be finite and > 0")
    output.write_text(
        "".join(f"{key}: {value:.17g}\n" for key, value in values.items())
        + f"rostopic: {topic}\nupdate_rate: {rate:.17g}\n",
        encoding="utf-8",
    )
    return {"update_rate_hz": rate, "update_rate_source": rate_source}


def write_target_yaml(output: Path, cols: int, rows: int, size_m: float, spacing: float) -> None:
    if cols < 1 or rows < 1 or size_m <= 0 or spacing < 0:
        raise ExportError("invalid AprilGrid dimensions/size/spacing")
    output.write_text(
        "target_type: 'aprilgrid'\n"
        f"tagCols: {cols}\n"
        f"tagRows: {rows}\n"
        f"tagSize: {size_m:.17g}\n"
        f"tagSpacing: {spacing:.17g}\n",
        encoding="utf-8",
    )


def source_csvs(capture: dict[str, Any], capture_path: Path) -> tuple[Path, Path]:
    artifacts = capture.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ExportError(f"{capture_path}: missing artifacts")
    if not isinstance(artifacts.get("frames_csv"), str) or not isinstance(artifacts.get("imu_csv"), str):
        raise ExportError(f"{capture_path}: frames_csv/imu_csv paths are required")
    frames = resolve(artifacts["frames_csv"], capture_path)
    imu = resolve(artifacts["imu_csv"], capture_path)
    if not frames.is_file() or not imu.is_file():
        raise ExportError("dynamic capture frames/IMU CSV is missing")
    return frames, imu


def write_camera_indexes(frames_csv: Path, capture_path: Path, output_dir: Path, reference: str) -> int:
    outputs = {"camera_a": output_dir / "camera_a.csv", "camera_b": output_dir / "camera_b.csv"}
    streams = {key: path.open("w", encoding="utf-8", newline="") for key, path in outputs.items()}
    try:
        writers = {key: csv.writer(stream) for key, stream in streams.items()}
        for writer in writers.values():
            writer.writerow(["timestamp_ns", "image_path", "frame_index", "frame_sequence"])
        previous = None
        count = 0
        with frames_csv.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"frame_index", "frame_sequence", "exposure_start_extended_us", "exposure_end_extended_us", "camera_a_path", "camera_b_path"}
            if reader.fieldnames is None or required - set(reader.fieldnames):
                raise ExportError(f"{frames_csv}: missing required frame columns")
            for line, row in enumerate(reader, start=2):
                stamp = camera_timestamp_ns(row, reference)
                if previous is not None and stamp <= previous:
                    raise ExportError(f"{frames_csv}:{line}: non-increasing camera timestamp")
                previous = stamp
                for key, column in (("camera_a", "camera_a_path"), ("camera_b", "camera_b_path")):
                    image = resolve(row[column], capture_path)
                    if not image.is_file():
                        raise ExportError(f"{frames_csv}:{line}: missing image {image}")
                    writers[key].writerow([stamp, str(image.resolve()).replace(os.sep, "/"), row["frame_index"], row["frame_sequence"]])
                count += 1
    finally:
        for stream in streams.values():
            stream.close()
    if count < 2:
        raise ExportError("dynamic capture contains fewer than two stereo frames")
    return count


def write_calibrated_imu(raw_csv: Path, output: Path, model: dict[str, Any]) -> dict[str, Any]:
    accel_bias = model["accelerometer_bias_raw_counts"]
    accel_matrix = model["accelerometer_target_m_s2_per_raw_count_matrix"]
    gyro_bias = model["gyroscope_bias_raw_counts"]
    gyro_matrix = model["gyroscope_target_rad_s_per_raw_count_matrix"]
    count = invalid = 0
    first = last = previous = None
    with raw_csv.open("r", encoding="utf-8", newline="") as src, output.open("w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        required = {"sample_valid", "imu_extended_time_us", "accel_raw_x", "accel_raw_y", "accel_raw_z", "gyro_raw_x", "gyro_raw_y", "gyro_raw_z"}
        if reader.fieldnames is None or required - set(reader.fieldnames):
            raise ExportError(f"{raw_csv}: missing required IMU columns")
        writer = csv.writer(dst)
        writer.writerow(["timestamp_ns", "omega_x", "omega_y", "omega_z", "alpha_x", "alpha_y", "alpha_z"])
        for line, row in enumerate(reader, start=2):
            valid = row["sample_valid"].strip().lower()
            if valid == "false":
                invalid += 1
                continue
            if valid != "true":
                raise ExportError(f"{raw_csv}:{line}: invalid sample_valid")
            try:
                stamp = int(row["imu_extended_time_us"], 10) * 1000
                accel_raw = [float(row[f"accel_raw_{axis}"]) for axis in "xyz"]
                gyro_raw = [float(row[f"gyro_raw_{axis}"]) for axis in "xyz"]
            except ValueError as exc:
                raise ExportError(f"{raw_csv}:{line}: invalid numeric field") from exc
            if previous is not None and stamp <= previous:
                raise ExportError(f"{raw_csv}:{line}: duplicate/backward IMU timestamp")
            previous = stamp
            first = stamp if first is None else first
            last = stamp
            accel = mat_vec(accel_matrix, [a - b for a, b in zip(accel_raw, accel_bias)])
            gyro = mat_vec(gyro_matrix, [a - b for a, b in zip(gyro_raw, gyro_bias)])
            writer.writerow([stamp, *[f"{v:.17g}" for v in gyro], *[f"{v:.17g}" for v in accel]])
            count += 1
    if count < 2:
        raise ExportError("dynamic capture contains fewer than two valid IMU samples")
    duration = (last - first) / 1e9 if first is not None and last is not None and last > first else None
    return {"valid_samples": count, "invalid_samples_skipped": invalid, "effective_rate_hz": (count - 1) / duration if duration else None}


def build(args: argparse.Namespace) -> dict[str, Any]:
    capture_path = args.capture_json.resolve()
    imu_session_path = args.imu_session.resolve()
    imu_artifact_path = args.imu_calibration.resolve()
    camchain_path = args.camchain.resolve()
    output_dir = args.output_dir.resolve()

    capture = load_json(capture_path)
    session = load_json(imu_session_path)
    artifact = load_json(imu_artifact_path)
    require_schema(capture, CAPTURE_SCHEMA, capture_path)
    require_schema(session, IMU_SESSION_SCHEMA, imu_session_path)
    require_schema(artifact, IMU_ARTIFACT_SCHEMA, imu_artifact_path)
    require_measured(session, imu_session_path, args.allow_synthetic)
    require_measured(artifact, imu_artifact_path, args.allow_synthetic)

    capture_device = capture.get("device")
    session_device = session.get("device")
    artifact_device = artifact.get("device")
    if not all(isinstance(value, dict) for value in (capture_device, session_device, artifact_device)):
        raise ExportError("capture/session/artifact device objects are required")
    serials = {str(capture_device.get("serial")), str(session_device.get("serial")), str(artifact_device.get("serial"))}
    if len(serials) != 1 or "" in serials or "None" in serials:
        raise ExportError(f"device serial mismatch: {sorted(serials)}")

    session_hash = sha256_file(imu_session_path)
    provenance = artifact.get("provenance")
    if isinstance(provenance, dict) and provenance.get("kind") == "measured" and provenance.get("source_hash") != session_hash:
        raise ExportError("measured IMU artifact source_hash does not match supplied IMU session manifest")

    six_path, six = bound_analysis(session, imu_session_path, "six_position", SIXPOS_SCHEMA)
    gyro_path, gyro = bound_analysis(session, imu_session_path, "gyro_rotation", GYRO_SCHEMA)
    conversion = raw_to_si_model(six, gyro)
    frames_csv, raw_imu_csv = source_csvs(capture, capture_path)

    camchain_text = camchain_path.read_text(encoding="utf-8")
    topics = parse_camchain_topics(camchain_text)
    for cam, expected in (("cam0", args.camera_a_topic), ("cam1", args.camera_b_topic)):
        if topics.get(cam) != expected:
            raise ExportError(f"{camchain_path}: {cam}.rostopic must be {expected!r}; observed {topics.get(cam)!r}")

    output_dir.mkdir(parents=True, exist_ok=False)
    camera_count = write_camera_indexes(frames_csv, capture_path, output_dir, args.camera_time_reference)
    imu_info = write_calibrated_imu(raw_imu_csv, output_dir / "imu0.csv", conversion)
    shutil.copyfile(camchain_path, output_dir / "camchain.yaml")
    imu_yaml_info = write_imu_yaml(artifact, args.imu_topic, output_dir / "imu.yaml")
    write_target_yaml(output_dir / "target.yaml", args.tag_cols, args.tag_rows, args.tag_size_m, args.tag_spacing)

    recipe = {
        "schema": "bividi.calibration.kalibr_rosbag_recipe.v1",
        "bag_output": "kalibr_dynamic.bag",
        "topics": {
            "camera_a": {"topic": args.camera_a_topic, "type": "sensor_msgs/Image", "encoding": "mono8", "index_csv": "camera_a.csv"},
            "camera_b": {"topic": args.camera_b_topic, "type": "sensor_msgs/Image", "encoding": "mono8", "index_csv": "camera_b.csv"},
            "imu": {"topic": args.imu_topic, "type": "sensor_msgs/Imu", "csv": "imu0.csv"},
        },
        "timestamp_contract": {
            "kalibr_reader_uses": "ROS message header.stamp for image and IMU time",
            "camera_reference": args.camera_time_reference,
            "imu_reference": "imu_extended_time_us * 1000 -> header.stamp ns",
            "bag_record_time": "same as header.stamp",
        },
        "units": {"angular_velocity": "rad/s", "linear_acceleration": "m/s^2"},
    }
    (output_dir / "rosbag-recipe.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    command = "kalibr_calibrate_imu_camera --bag kalibr_dynamic.bag --cams camchain.yaml --imu imu.yaml --target target.yaml\n"
    (output_dir / "kalibr-command.txt").write_text(command, encoding="utf-8")

    manifest = {
        "schema": OUTPUT_SCHEMA,
        "session_id": output_dir.name,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "device": {"serial": next(iter(serials))},
        "sources": {
            "dynamic_capture": {"path": str(capture_path), "sha256": sha256_file(capture_path)},
            "frames_csv": {"path": str(frames_csv), "sha256": sha256_file(frames_csv)},
            "raw_imu_csv": {"path": str(raw_imu_csv), "sha256": sha256_file(raw_imu_csv)},
            "imu_session": {"path": str(imu_session_path), "sha256": session_hash},
            "imu_calibration": {"path": str(imu_artifact_path), "sha256": sha256_file(imu_artifact_path)},
            "six_position": {"path": str(six_path), "sha256": sha256_file(six_path)},
            "gyro_rotation": {"path": str(gyro_path), "sha256": sha256_file(gyro_path)},
            "camchain": {"path": str(camchain_path), "sha256": sha256_file(camchain_path)},
        },
        "camera_mapping": {"camera_a": "cam0", "camera_b": "cam1", "guardrail": "camera_a/camera_b are not assumed left/right"},
        "camera_time_reference": {"kind": args.camera_time_reference, "time_shift_definition": TIME_SHIFT_DEFINITION},
        "raw_to_si": conversion,
        "aprilgrid": {"tag_cols": args.tag_cols, "tag_rows": args.tag_rows, "tag_size_m": args.tag_size_m, "tag_spacing_ratio": args.tag_spacing},
        "kalibr": {
            "backend": "ethz-asl/kalibr",
            "revision": args.kalibr_revision,
            "transform_definition": "T_ci transforms imu0 coordinates into cam_i coordinates",
            "time_shift_definition": TIME_SHIFT_DEFINITION,
        },
        "staged": {"camera_a_csv": "camera_a.csv", "camera_b_csv": "camera_b.csv", "imu_csv": "imu0.csv", "imu_yaml": "imu.yaml", "target_yaml": "target.yaml", "camchain_yaml": "camchain.yaml", "rosbag_recipe": "rosbag-recipe.json"},
        "statistics": {"camera_frames_per_camera": camera_count, "imu": imu_info, "imu_yaml": imu_yaml_info},
        "status": "prepared_for_external_ros1_bag_writer_and_kalibr",
        "provenance": {"tool": "prepare_kalibr_dynamic_session.py", "tool_version": TOOL_VERSION},
    }
    (output_dir / "session.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def fixture(root: Path) -> argparse.Namespace:
    src = root / "src"
    src.mkdir()
    (src / "images").mkdir()
    for name in ("a0.png", "a1.png", "b0.png", "b1.png"):
        (src / "images" / name).write_bytes(b"synthetic")
    with (src / "frames.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frame_index", "frame_sequence", "exposure_start_extended_us", "exposure_end_extended_us", "camera_a_path", "camera_b_path"])
        writer.writerow([0, 10, 1_000_000, 1_001_000, "images/a0.png", "images/b0.png"])
        writer.writerow([1, 11, 1_010_000, 1_011_000, "images/a1.png", "images/b1.png"])
    with (src / "imu.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["sample_valid", "imu_extended_time_us", "accel_raw_x", "accel_raw_y", "accel_raw_z", "gyro_raw_x", "gyro_raw_y", "gyro_raw_z"])
        for i in range(6):
            writer.writerow(["true", 1_000_000 + i * 2000, 0, 0, 8192, 10 + i, 20 + i, 30 + i])
    capture = src / "capture.json"
    capture.write_text(json.dumps({"schema": CAPTURE_SCHEMA, "device": {"serial": "SYNTHETIC"}, "artifacts": {"frames_csv": "frames.csv", "imu_csv": "imu.csv"}}), encoding="utf-8")
    six = src / "six.json"
    six.write_text(json.dumps({"schema": SIXPOS_SCHEMA, "accelerometer_gravity_model": {"bias_raw_counts": [0, 0, 0], "target_g_per_raw_count_matrix": [[1/8192, 0, 0], [0, 1/8192, 0], [0, 0, 1/8192]]}}), encoding="utf-8")
    gyro = src / "gyro.json"
    gyro.write_text(json.dumps({"schema": GYRO_SCHEMA, "stationary_baseline": {"bias_raw_counts": [10, 20, 30]}, "rotation_model": {"target_rad_s_per_raw_count_matrix": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 0.001]]}}), encoding="utf-8")
    session = src / "session.json"
    session.write_text(json.dumps({"schema": IMU_SESSION_SCHEMA, "device": {"serial": "SYNTHETIC"}, "analysis": [{"role": "six_position", "path": "six.json", "sha256": sha256_file(six)}, {"role": "gyro_rotation", "path": "gyro.json", "sha256": sha256_file(gyro)}], "provenance": {"kind": "synthetic"}}), encoding="utf-8")
    artifact = src / "artifact.json"
    artifact.write_text(json.dumps({"schema": IMU_ARTIFACT_SCHEMA, "device": {"serial": "SYNTHETIC"}, "imu": {"sample_rate_hz_measured": 500.0}, "timing": {"effective_rate_hz": 500.0}, "noise": {"accelerometer_noise_density_m_s2_sqrt_hz": 0.01, "accelerometer_bias_random_walk_m_s3_sqrt_hz": 0.001, "gyroscope_noise_density_rad_s_sqrt_hz": 0.001, "gyroscope_bias_random_walk_rad_s2_sqrt_hz": 0.0001}, "provenance": {"kind": "synthetic"}}), encoding="utf-8")
    camchain = src / "camchain.yaml"
    camchain.write_text("cam0:\n  rostopic: /cam0/image_raw\ncam1:\n  rostopic: /cam1/image_raw\n", encoding="utf-8")
    return argparse.Namespace(capture_json=capture, imu_session=session, imu_calibration=artifact, camchain=camchain, output_dir=root / "out", camera_time_reference="exposure_midpoint", camera_a_topic="/cam0/image_raw", camera_b_topic="/cam1/image_raw", imu_topic="/imu0", tag_cols=6, tag_rows=6, tag_size_m=0.088, tag_spacing=0.3, kalibr_revision="test", allow_synthetic=True)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args = fixture(Path(tmp))
        report = build(args)
        assert report["statistics"]["camera_frames_per_camera"] == 2
        assert report["statistics"]["imu"]["valid_samples"] == 6
        with (args.output_dir / "camera_a.csv").open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert int(rows[0]["timestamp_ns"]) == 1_000_500_000
        with (args.output_dir / "imu0.csv").open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert abs(float(rows[0]["omega_x"])) < 1e-12
        assert abs(float(rows[0]["alpha_z"]) - GRAVITY_M_S2) < 1e-9
    print("Kalibr dynamic-session preparation self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_json", nargs="?", type=Path)
    parser.add_argument("--imu-session", type=Path)
    parser.add_argument("--imu-calibration", type=Path)
    parser.add_argument("--camchain", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--camera-time-reference", choices=CAMERA_TIME_REFERENCES)
    parser.add_argument("--camera-a-topic", default="/cam0/image_raw")
    parser.add_argument("--camera-b-topic", default="/cam1/image_raw")
    parser.add_argument("--imu-topic", default="/imu0")
    parser.add_argument("--tag-cols", type=int)
    parser.add_argument("--tag-rows", type=int)
    parser.add_argument("--tag-size-m", type=float)
    parser.add_argument("--tag-spacing", type=float)
    parser.add_argument("--kalibr-revision", default="1f60227442d25e36365ef5f72cd80b9666d73467")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    required = (args.capture_json, args.imu_session, args.imu_calibration, args.camchain, args.output_dir, args.camera_time_reference, args.tag_cols, args.tag_rows, args.tag_size_m, args.tag_spacing)
    if any(value is None for value in required):
        print("capture_json, --imu-session, --imu-calibration, --camchain, --output-dir, --camera-time-reference and AprilGrid parameters are required", file=sys.stderr)
        return 2
    try:
        report = build(args)
    except (ExportError, OSError) as exc:
        print(f"Kalibr dynamic-session preparation failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"status": report["status"], "output_dir": str(args.output_dir.resolve()), "camera_frames_per_camera": report["statistics"]["camera_frames_per_camera"], "imu_valid_samples": report["statistics"]["imu"]["valid_samples"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
