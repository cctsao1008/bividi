#!/usr/bin/env python3
"""Validate Bividi IMU and camera-IMU calibration artifacts.

The repository keeps JSON Schema files as the durable machine-readable contract,
but normal CI intentionally has no jsonschema dependency. This validator checks
the same high-value structural rules plus rigid-transform invariants that plain
JSON Schema cannot express conveniently.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

IMU_SCHEMA = "bividi.calibration.imu.v1"
CAMERA_IMU_SCHEMA = "bividi.calibration.camera_imu.v1"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"
PROVENANCE_KINDS = {"synthetic", "measured", "imported"}
CAMERA_TIME_REFERENCES = {
    "exposure_start",
    "exposure_midpoint",
    "exposure_end",
    "frame_timestamp",
}


@dataclass
class Finding:
    severity: str
    path: str
    message: str


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def require_object(parent: dict[str, Any], key: str, findings: list[Finding], path: str = "") -> dict[str, Any] | None:
    value = parent.get(key)
    full = f"{path}.{key}" if path else key
    if not isinstance(value, dict):
        findings.append(Finding("error", full, "required object is missing or not an object"))
        return None
    return value


def require_string(parent: dict[str, Any], key: str, findings: list[Finding], path: str = "") -> str | None:
    value = parent.get(key)
    full = f"{path}.{key}" if path else key
    if not isinstance(value, str) or not value:
        findings.append(Finding("error", full, "required non-empty string is missing"))
        return None
    return value


def reject_unknown(obj: dict[str, Any], allowed: set[str], findings: list[Finding], path: str) -> None:
    for key in obj:
        if key not in allowed:
            findings.append(Finding("error", f"{path}.{key}" if path else key, "unknown field"))


def check_datetime(value: Any, findings: list[Finding], path: str) -> None:
    if not isinstance(value, str) or not value:
        findings.append(Finding("error", path, "required date-time string is missing"))
        return
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        findings.append(Finding("error", path, "invalid ISO-8601 date-time"))
        return
    if parsed.tzinfo is None:
        findings.append(Finding("error", path, "date-time must include a timezone/UTC offset"))


def check_vector3(value: Any, findings: list[Finding], path: str, *, nonnegative: bool = False) -> None:
    if not isinstance(value, list) or len(value) != 3:
        findings.append(Finding("error", path, "expected exactly three numeric elements"))
        return
    for index, item in enumerate(value):
        if not is_number(item):
            findings.append(Finding("error", f"{path}[{index}]", "value must be finite numeric"))
        elif nonnegative and float(item) < 0.0:
            findings.append(Finding("error", f"{path}[{index}]", "value must be non-negative"))


def check_matrix3(value: Any, findings: list[Finding], path: str) -> None:
    if not isinstance(value, list) or len(value) != 3:
        findings.append(Finding("error", path, "expected a 3x3 numeric matrix"))
        return
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 3:
            findings.append(Finding("error", f"{path}[{row_index}]", "expected three numeric elements"))
            continue
        for col_index, item in enumerate(row):
            if not is_number(item):
                findings.append(Finding("error", f"{path}[{row_index}][{col_index}]", "value must be finite numeric"))


def check_matrix4(value: Any, findings: list[Finding], path: str) -> list[list[float]] | None:
    if not isinstance(value, list) or len(value) != 4:
        findings.append(Finding("error", path, "expected a 4x4 numeric matrix"))
        return None
    matrix: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 4:
            findings.append(Finding("error", f"{path}[{row_index}]", "expected four numeric elements"))
            return None
        converted: list[float] = []
        for col_index, item in enumerate(row):
            if not is_number(item):
                findings.append(Finding("error", f"{path}[{row_index}][{col_index}]", "value must be finite numeric"))
                return None
            converted.append(float(item))
        matrix.append(converted)
    return matrix


def det3(r: list[list[float]]) -> float:
    return (
        r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
        - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
        + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
    )


def check_rigid_transform(matrix: list[list[float]], findings: list[Finding], path: str) -> None:
    tol = 1e-3
    last_tol = 1e-6
    expected_last = [0.0, 0.0, 0.0, 1.0]
    for i, expected in enumerate(expected_last):
        if abs(matrix[3][i] - expected) > last_tol:
            findings.append(Finding("error", f"{path}[3]", "homogeneous transform last row must be [0,0,0,1]"))
            break

    r = [row[:3] for row in matrix[:3]]
    for i in range(3):
        norm = sum(r[k][i] * r[k][i] for k in range(3))
        if abs(norm - 1.0) > tol:
            findings.append(Finding("error", path, f"rotation column {i} is not unit length"))
        for j in range(i + 1, 3):
            dot = sum(r[k][i] * r[k][j] for k in range(3))
            if abs(dot) > tol:
                findings.append(Finding("error", path, f"rotation columns {i}/{j} are not orthogonal"))
    determinant = det3(r)
    if abs(determinant - 1.0) > tol:
        findings.append(Finding("error", path, f"rotation determinant must be +1; observed {determinant:.6g}"))


def check_device(data: dict[str, Any], findings: list[Finding]) -> None:
    device = require_object(data, "device", findings)
    if device is None:
        return
    reject_unknown(device, {"model", "serial", "firmware", "sdk_version"}, findings, "device")
    require_string(device, "model", findings, "device")
    require_string(device, "serial", findings, "device")
    for key in ("firmware", "sdk_version"):
        if key in device and not isinstance(device[key], str):
            findings.append(Finding("error", f"device.{key}", "must be a string"))


def check_provenance(data: dict[str, Any], findings: list[Finding]) -> None:
    provenance = require_object(data, "provenance", findings)
    if provenance is None:
        return
    allowed = {
        "kind", "tool", "tool_version", "tool_revision", "source_session", "source_hash",
        "external_backend", "external_backend_revision", "external_backend_container",
    }
    reject_unknown(provenance, allowed, findings, "provenance")
    kind = require_string(provenance, "kind", findings, "provenance")
    require_string(provenance, "tool", findings, "provenance")
    if kind is not None and kind not in PROVENANCE_KINDS:
        findings.append(Finding("error", "provenance.kind", f"must be one of {sorted(PROVENANCE_KINDS)}"))
    if kind == "imported" and not provenance.get("external_backend"):
        findings.append(Finding("error", "provenance.external_backend", "imported artifacts must identify the external backend"))
    for key in allowed - {"kind", "tool"}:
        if key in provenance and not isinstance(provenance[key], str):
            findings.append(Finding("error", f"provenance.{key}", "must be a string"))


def validate_imu(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    allowed_top = {
        "schema", "calibration_id", "created_utc", "device", "imu", "frames", "timing",
        "stationary", "noise", "scale_misalignment", "quality", "provenance",
    }
    reject_unknown(data, allowed_top, findings, "")
    require_string(data, "calibration_id", findings)
    check_datetime(data.get("created_utc"), findings, "created_utc")
    check_device(data, findings)
    check_provenance(data, findings)

    imu = require_object(data, "imu", findings)
    if imu is not None:
        allowed = {
            "model", "frame", "sample_rate_hz_nominal", "sample_rate_hz_measured",
            "accelerometer_range_g", "gyroscope_range_dps",
        }
        reject_unknown(imu, allowed, findings, "imu")
        require_string(imu, "model", findings, "imu")
        require_string(imu, "frame", findings, "imu")
        for key in allowed - {"model", "frame"}:
            if key in imu and (not is_number(imu[key]) or float(imu[key]) <= 0.0):
                findings.append(Finding("error", f"imu.{key}", "must be finite and > 0"))

    frames = require_object(data, "frames", findings)
    if frames is not None:
        reject_unknown(frames, {"handedness", "imu_axes"}, findings, "frames")
        if frames.get("handedness") != "right":
            findings.append(Finding("error", "frames.handedness", "must be 'right'"))
        require_string(frames, "imu_axes", findings, "frames")

    timing = data.get("timing")
    if timing is not None:
        if not isinstance(timing, dict):
            findings.append(Finding("error", "timing", "must be an object"))
        else:
            allowed = {"timestamp_unit", "timestamp_counter_bits", "effective_rate_hz", "gap_count", "duplicate_count"}
            reject_unknown(timing, allowed, findings, "timing")
            if "timestamp_unit" in timing and timing["timestamp_unit"] != "us":
                findings.append(Finding("error", "timing.timestamp_unit", "v1 device timestamp unit must be 'us'"))
            if "timestamp_counter_bits" in timing and (
                not isinstance(timing["timestamp_counter_bits"], int)
                or isinstance(timing["timestamp_counter_bits"], bool)
                or timing["timestamp_counter_bits"] < 1
            ):
                findings.append(Finding("error", "timing.timestamp_counter_bits", "must be a positive integer"))
            if "effective_rate_hz" in timing and (
                not is_number(timing["effective_rate_hz"]) or float(timing["effective_rate_hz"]) <= 0.0
            ):
                findings.append(Finding("error", "timing.effective_rate_hz", "must be finite and > 0"))
            for key in ("gap_count", "duplicate_count"):
                if key in timing and (
                    not isinstance(timing[key], int) or isinstance(timing[key], bool) or timing[key] < 0
                ):
                    findings.append(Finding("error", f"timing.{key}", "must be a non-negative integer"))

    stationary = data.get("stationary")
    if stationary is not None:
        if not isinstance(stationary, dict):
            findings.append(Finding("error", "stationary", "must be an object"))
        else:
            allowed = {
                "sample_count", "duration_s", "gyroscope_bias_rad_s", "gyroscope_stddev_rad_s",
                "accelerometer_mean_m_s2", "accelerometer_stddev_m_s2",
            }
            reject_unknown(stationary, allowed, findings, "stationary")
            if "sample_count" in stationary and (
                not isinstance(stationary["sample_count"], int)
                or isinstance(stationary["sample_count"], bool)
                or stationary["sample_count"] < 1
            ):
                findings.append(Finding("error", "stationary.sample_count", "must be a positive integer"))
            if "duration_s" in stationary and (
                not is_number(stationary["duration_s"]) or float(stationary["duration_s"]) <= 0.0
            ):
                findings.append(Finding("error", "stationary.duration_s", "must be finite and > 0"))
            for key in ("gyroscope_bias_rad_s", "accelerometer_mean_m_s2"):
                if key in stationary:
                    check_vector3(stationary[key], findings, f"stationary.{key}")
            for key in ("gyroscope_stddev_rad_s", "accelerometer_stddev_m_s2"):
                if key in stationary:
                    check_vector3(stationary[key], findings, f"stationary.{key}", nonnegative=True)

    noise = data.get("noise")
    if noise is not None:
        if not isinstance(noise, dict):
            findings.append(Finding("error", "noise", "must be an object"))
        else:
            allowed = {
                "gyroscope_noise_density_rad_s_sqrt_hz",
                "accelerometer_noise_density_m_s2_sqrt_hz",
                "gyroscope_bias_random_walk_rad_s2_sqrt_hz",
                "accelerometer_bias_random_walk_m_s3_sqrt_hz",
                "method",
            }
            reject_unknown(noise, allowed, findings, "noise")
            for key in allowed - {"method"}:
                if key in noise and (not is_number(noise[key]) or float(noise[key]) <= 0.0):
                    findings.append(Finding("error", f"noise.{key}", "must be finite and > 0"))
            if "method" in noise and (not isinstance(noise["method"], str) or not noise["method"]):
                findings.append(Finding("error", "noise.method", "must be a non-empty string"))

    scale = data.get("scale_misalignment")
    if scale is not None:
        if not isinstance(scale, dict):
            findings.append(Finding("error", "scale_misalignment", "must be an object"))
        else:
            allowed = {"accelerometer_matrix", "gyroscope_matrix", "method"}
            reject_unknown(scale, allowed, findings, "scale_misalignment")
            for key in ("accelerometer_matrix", "gyroscope_matrix"):
                if key in scale:
                    check_matrix3(scale[key], findings, f"scale_misalignment.{key}")

    return findings


def validate_camera_imu(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    allowed_top = {
        "schema", "calibration_id", "created_utc", "device", "camera_reference",
        "imu_reference", "transform", "time_offset", "frames", "quality", "provenance",
    }
    reject_unknown(data, allowed_top, findings, "")
    require_string(data, "calibration_id", findings)
    check_datetime(data.get("created_utc"), findings, "created_utc")
    check_device(data, findings)
    check_provenance(data, findings)

    camera = require_object(data, "camera_reference", findings)
    camera_frame: str | None = None
    if camera is not None:
        allowed = {"camera_id", "frame", "width", "height", "mode_id"}
        reject_unknown(camera, allowed, findings, "camera_reference")
        require_string(camera, "camera_id", findings, "camera_reference")
        camera_frame = require_string(camera, "frame", findings, "camera_reference")
        for key in ("width", "height"):
            if key in camera and (
                not isinstance(camera[key], int) or isinstance(camera[key], bool) or camera[key] < 1
            ):
                findings.append(Finding("error", f"camera_reference.{key}", "must be a positive integer"))
        if "mode_id" in camera and not isinstance(camera["mode_id"], str):
            findings.append(Finding("error", "camera_reference.mode_id", "must be a string"))

    imu = require_object(data, "imu_reference", findings)
    imu_frame: str | None = None
    if imu is not None:
        allowed = {"model", "frame", "imu_calibration_id"}
        reject_unknown(imu, allowed, findings, "imu_reference")
        require_string(imu, "model", findings, "imu_reference")
        imu_frame = require_string(imu, "frame", findings, "imu_reference")
        if "imu_calibration_id" in imu and (
            not isinstance(imu["imu_calibration_id"], str) or not imu["imu_calibration_id"]
        ):
            findings.append(Finding("error", "imu_reference.imu_calibration_id", "must be a non-empty string"))

    transform = require_object(data, "transform", findings)
    if transform is not None:
        allowed = {"from_frame", "to_frame", "matrix", "translation_unit"}
        reject_unknown(transform, allowed, findings, "transform")
        from_frame = require_string(transform, "from_frame", findings, "transform")
        to_frame = require_string(transform, "to_frame", findings, "transform")
        if transform.get("translation_unit") != "m":
            findings.append(Finding("error", "transform.translation_unit", "must be 'm'"))
        matrix = check_matrix4(transform.get("matrix"), findings, "transform.matrix")
        if matrix is not None:
            check_rigid_transform(matrix, findings, "transform.matrix")
        if imu_frame is not None and from_frame is not None and from_frame != imu_frame:
            findings.append(Finding("error", "transform.from_frame", "must match imu_reference.frame"))
        if camera_frame is not None and to_frame is not None and to_frame != camera_frame:
            findings.append(Finding("error", "transform.to_frame", "must match camera_reference.frame"))
        if from_frame is not None and to_frame is not None and from_frame == to_frame:
            findings.append(Finding("error", "transform", "from_frame and to_frame must be distinct"))

    frames = require_object(data, "frames", findings)
    if frames is not None:
        allowed = {"handedness", "camera_axes", "imu_axes"}
        reject_unknown(frames, allowed, findings, "frames")
        if frames.get("handedness") != "right":
            findings.append(Finding("error", "frames.handedness", "must be 'right'"))
        require_string(frames, "camera_axes", findings, "frames")
        require_string(frames, "imu_axes", findings, "frames")

    time_offset = data.get("time_offset")
    if time_offset is not None:
        if not isinstance(time_offset, dict):
            findings.append(Finding("error", "time_offset", "must be an object"))
        else:
            allowed = {"definition", "camera_time_reference", "offset_s", "method"}
            reject_unknown(time_offset, allowed, findings, "time_offset")
            if time_offset.get("definition") != TIME_OFFSET_DEFINITION:
                findings.append(Finding("error", "time_offset.definition", f"must be exactly: {TIME_OFFSET_DEFINITION}"))
            reference = time_offset.get("camera_time_reference")
            if reference not in CAMERA_TIME_REFERENCES:
                findings.append(Finding("error", "time_offset.camera_time_reference", f"must be one of {sorted(CAMERA_TIME_REFERENCES)}"))
            if not is_number(time_offset.get("offset_s")):
                findings.append(Finding("error", "time_offset.offset_s", "must be finite numeric"))
            if "method" in time_offset and (
                not isinstance(time_offset["method"], str) or not time_offset["method"]
            ):
                findings.append(Finding("error", "time_offset.method", "must be a non-empty string"))

    return findings


def validate(data: Any) -> list[Finding]:
    if not isinstance(data, dict):
        return [Finding("error", "", "artifact root must be a JSON object")]
    schema = data.get("schema")
    if schema == IMU_SCHEMA:
        return validate_imu(data)
    if schema == CAMERA_IMU_SCHEMA:
        return validate_camera_imu(data)
    return [Finding("error", "schema", f"unsupported schema {schema!r}")]


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def synthetic_imu() -> dict[str, Any]:
    return {
        "schema": IMU_SCHEMA,
        "calibration_id": "synthetic-imu-001",
        "created_utc": "2026-09-16T00:00:00+00:00",
        "device": {"model": "synthetic-rig", "serial": "SYNTHETIC"},
        "imu": {
            "model": "ICM-42688-P",
            "frame": "imu",
            "sample_rate_hz_nominal": 600.0,
            "sample_rate_hz_measured": 599.8
        },
        "frames": {"handedness": "right", "imu_axes": "+X forward, +Y left, +Z up (synthetic convention)"},
        "timing": {"timestamp_unit": "us", "timestamp_counter_bits": 32, "effective_rate_hz": 599.8},
        "stationary": {
            "sample_count": 60000,
            "duration_s": 100.0,
            "gyroscope_bias_rad_s": [0.001, -0.002, 0.0005],
            "gyroscope_stddev_rad_s": [0.01, 0.01, 0.011],
            "accelerometer_mean_m_s2": [0.0, 0.0, 9.80665],
            "accelerometer_stddev_m_s2": [0.02, 0.02, 0.025]
        },
        "noise": {
            "gyroscope_noise_density_rad_s_sqrt_hz": 0.0002,
            "accelerometer_noise_density_m_s2_sqrt_hz": 0.002,
            "gyroscope_bias_random_walk_rad_s2_sqrt_hz": 0.00002,
            "accelerometer_bias_random_walk_m_s3_sqrt_hz": 0.0002,
            "method": "synthetic fixture"
        },
        "provenance": {"kind": "synthetic", "tool": "validate_calibration_artifact.py"}
    }


def synthetic_camera_imu() -> dict[str, Any]:
    return {
        "schema": CAMERA_IMU_SCHEMA,
        "calibration_id": "synthetic-camera-imu-001",
        "created_utc": "2026-09-16T00:00:00+00:00",
        "device": {"model": "synthetic-rig", "serial": "SYNTHETIC"},
        "camera_reference": {
            "camera_id": "camera_a",
            "frame": "camera_a_optical",
            "width": 1920,
            "height": 1200
        },
        "imu_reference": {
            "model": "ICM-42688-P",
            "frame": "imu",
            "imu_calibration_id": "synthetic-imu-001"
        },
        "transform": {
            "from_frame": "imu",
            "to_frame": "camera_a_optical",
            "matrix": [
                [1.0, 0.0, 0.0, 0.03],
                [0.0, 1.0, 0.0, 0.00],
                [0.0, 0.0, 1.0, 0.01],
                [0.0, 0.0, 0.0, 1.0]
            ],
            "translation_unit": "m"
        },
        "time_offset": {
            "definition": TIME_OFFSET_DEFINITION,
            "camera_time_reference": "exposure_end",
            "offset_s": 0.00001,
            "method": "synthetic fixture"
        },
        "frames": {
            "handedness": "right",
            "camera_axes": "+X right, +Y down, +Z forward (synthetic convention)",
            "imu_axes": "+X forward, +Y left, +Z up (synthetic convention)"
        },
        "provenance": {"kind": "synthetic", "tool": "validate_calibration_artifact.py"}
    }


def self_test() -> int:
    for artifact in (synthetic_imu(), synthetic_camera_imu()):
        findings = validate(artifact)
        assert not [item for item in findings if item.severity == "error"], findings

    bad_transform = copy.deepcopy(synthetic_camera_imu())
    bad_transform["transform"]["matrix"][0][0] = 2.0
    assert any(item.path == "transform.matrix" for item in validate(bad_transform))

    bad_direction = copy.deepcopy(synthetic_camera_imu())
    bad_direction["transform"]["from_frame"] = "camera_a_optical"
    assert any(item.path == "transform.from_frame" for item in validate(bad_direction))

    bad_offset = copy.deepcopy(synthetic_camera_imu())
    bad_offset["time_offset"]["definition"] = "t_camera = t_imu + offset"
    assert any(item.path == "time_offset.definition" for item in validate(bad_offset))

    imported = copy.deepcopy(synthetic_camera_imu())
    imported["provenance"] = {"kind": "imported", "tool": "adapter"}
    assert any(item.path == "provenance.external_backend" for item in validate(imported))

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "artifact.json"
        path.write_text(json.dumps(synthetic_imu()), encoding="utf-8")
        assert load(path)["schema"] == IMU_SCHEMA

    print("calibration artifact validator self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Bividi calibration artifact")
    parser.add_argument("artifact", nargs="?", type=Path)
    parser.add_argument("--json-out", type=Path, help="write machine-readable validation report")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.artifact is None:
        print("artifact JSON path is required", file=sys.stderr)
        return 3

    try:
        data = load(args.artifact)
    except ValueError as exc:
        print(f"validate_calibration_artifact: {exc}", file=sys.stderr)
        return 3

    findings = validate(data)
    valid = not any(item.severity == "error" for item in findings)
    report = {
        "schema": "bividi.calibration.validation.v1",
        "artifact": str(args.artifact),
        "artifact_schema": data.get("schema"),
        "valid": valid,
        "findings": [asdict(item) for item in findings],
    }

    if findings:
        for item in findings:
            location = item.path or "<root>"
            print(f"{item.severity.upper()}: {location}: {item.message}")
    else:
        print(f"PASS: {args.artifact} ({data.get('schema')})")

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
