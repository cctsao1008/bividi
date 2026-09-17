#!/usr/bin/env python3
"""Analyze camera/IMU dynamic-session excitation and time coverage evidence.

This tool consumes a prepared Bividi Kalibr dynamic-session bundle. It measures
stream coverage, camera/IMU cadence, per-axis angular/specific-force activity,
integrated angular motion, and directionality proxies. It deliberately does not
claim formal calibration observability: good excitation proxies are necessary
engineering evidence, not a mathematical proof that every Kalibr parameter is
observable or accurately estimated.

All numeric acceptance gates are opt-in. Without explicit gates, a structurally
valid run is reported as EVIDENCE_ONLY_NO_THRESHOLDS.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "bividi.calibration.camera_imu_excitation.v1"
SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
TOOL_VERSION = "1"
AXES = ("x", "y", "z")


class ExcitationError(ValueError):
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
        raise ExcitationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExcitationError(f"{path}: expected JSON object")
    return value


def staged_file(session: Mapping[str, Any], session_path: Path, key: str) -> Path:
    staged = session.get("staged")
    if not isinstance(staged, dict):
        raise ExcitationError(f"{session_path}: missing staged map")
    raw = staged.get(key)
    if not isinstance(raw, str) or not raw:
        raise ExcitationError(f"{session_path}: staged.{key} is required")
    path = Path(raw)
    if not path.is_absolute():
        path = session_path.parent / path
    path = path.resolve()
    if not path.is_file():
        raise ExcitationError(f"{session_path}: staged.{key} file does not exist: {path}")
    return path


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ExcitationError("cannot compute percentile of empty values")
    if not 0.0 <= fraction <= 1.0:
        raise ExcitationError("percentile fraction must be in [0,1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def scalar_summary(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ExcitationError("cannot summarize empty values")
    data = [float(value) for value in values]
    if not all(math.isfinite(value) for value in data):
        raise ExcitationError("non-finite value in summary input")
    mean = statistics.fmean(data)
    variance = statistics.fmean((value - mean) ** 2 for value in data)
    return {
        "count": len(data),
        "min": min(data),
        "max": max(data),
        "mean": mean,
        "std": math.sqrt(max(0.0, variance)),
        "rms": math.sqrt(statistics.fmean(value * value for value in data)),
        "p50": percentile(data, 0.50),
        "p95": percentile(data, 0.95),
        "p99": percentile(data, 0.99),
    }


def absolute_summary(values: Sequence[float]) -> dict[str, float | int]:
    return scalar_summary([abs(float(value)) for value in values])


def vector_norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in vector))


def read_camera_index(path: Path) -> dict[str, Any]:
    stamps: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or "timestamp_ns" not in reader.fieldnames:
            raise ExcitationError(f"{path}: missing timestamp_ns")
        previous = None
        for line, row in enumerate(reader, start=2):
            try:
                stamp = int(row["timestamp_ns"], 10)
            except (TypeError, ValueError) as exc:
                raise ExcitationError(f"{path}:{line}: invalid timestamp_ns") from exc
            if stamp < 0:
                raise ExcitationError(f"{path}:{line}: negative timestamp")
            if previous is not None and stamp <= previous:
                raise ExcitationError(f"{path}:{line}: camera timestamp is not strictly increasing")
            stamps.append(stamp)
            previous = stamp
    if len(stamps) < 2:
        raise ExcitationError(f"{path}: fewer than two camera samples")
    intervals_s = [(b - a) / 1e9 for a, b in zip(stamps, stamps[1:])]
    duration_s = (stamps[-1] - stamps[0]) / 1e9
    return {
        "timestamps_ns": stamps,
        "count": len(stamps),
        "first_timestamp_ns": stamps[0],
        "last_timestamp_ns": stamps[-1],
        "duration_s": duration_s,
        "effective_rate_hz": (len(stamps) - 1) / duration_s if duration_s > 0 else None,
        "interval_s": scalar_summary(intervals_s),
    }


def read_imu(path: Path) -> dict[str, Any]:
    stamps: list[int] = []
    gyro: list[tuple[float, float, float]] = []
    accel: list[tuple[float, float, float]] = []
    required = {
        "timestamp_ns", "omega_x", "omega_y", "omega_z",
        "alpha_x", "alpha_y", "alpha_z",
    }
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or required - set(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ExcitationError(f"{path}: missing columns: {', '.join(missing)}")
        previous = None
        for line, row in enumerate(reader, start=2):
            try:
                stamp = int(row["timestamp_ns"], 10)
                omega = tuple(float(row[f"omega_{axis}"]) for axis in AXES)
                alpha = tuple(float(row[f"alpha_{axis}"]) for axis in AXES)
            except (TypeError, ValueError) as exc:
                raise ExcitationError(f"{path}:{line}: invalid IMU numeric field") from exc
            if stamp < 0:
                raise ExcitationError(f"{path}:{line}: negative timestamp")
            if previous is not None and stamp <= previous:
                raise ExcitationError(f"{path}:{line}: IMU timestamp is not strictly increasing")
            if not all(math.isfinite(value) for value in (*omega, *alpha)):
                raise ExcitationError(f"{path}:{line}: non-finite IMU value")
            stamps.append(stamp)
            gyro.append(omega)
            accel.append(alpha)
            previous = stamp
    if len(stamps) < 2:
        raise ExcitationError(f"{path}: fewer than two IMU samples")
    intervals_s = [(b - a) / 1e9 for a, b in zip(stamps, stamps[1:])]
    duration_s = (stamps[-1] - stamps[0]) / 1e9
    return {
        "timestamps_ns": stamps,
        "gyro": gyro,
        "accel": accel,
        "count": len(stamps),
        "first_timestamp_ns": stamps[0],
        "last_timestamp_ns": stamps[-1],
        "duration_s": duration_s,
        "effective_rate_hz": (len(stamps) - 1) / duration_s if duration_s > 0 else None,
        "interval_s": scalar_summary(intervals_s),
    }


def axis_values(vectors: Sequence[Sequence[float]], index: int) -> list[float]:
    return [float(vector[index]) for vector in vectors]


def axis_activity(vectors: Sequence[Sequence[float]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    total_energy = 0.0
    energies: dict[str, float] = {}
    for index, axis in enumerate(AXES):
        values = axis_values(vectors, index)
        energy = sum(value * value for value in values)
        energies[axis] = energy
        total_energy += energy
        result[axis] = {
            "signed": scalar_summary(values),
            "absolute": absolute_summary(values),
        }
    for axis in AXES:
        result[axis]["energy_fraction"] = energies[axis] / total_energy if total_energy > 0 else 0.0
    return result


def second_moment(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    if not vectors:
        raise ExcitationError("cannot compute second moment of empty vectors")
    matrix = [[0.0] * 3 for _ in range(3)]
    for vector in vectors:
        for row in range(3):
            for col in range(3):
                matrix[row][col] += float(vector[row]) * float(vector[col])
    scale = 1.0 / len(vectors)
    return [[value * scale for value in row] for row in matrix]


def covariance(vectors: Sequence[Sequence[float]]) -> tuple[list[float], list[list[float]]]:
    if not vectors:
        raise ExcitationError("cannot compute covariance of empty vectors")
    mean = [statistics.fmean(float(vector[index]) for vector in vectors) for index in range(3)]
    centered = [tuple(float(vector[index]) - mean[index] for index in range(3)) for vector in vectors]
    return mean, second_moment(centered)


def determinant3(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def symmetric_eigenvalues3(matrix: Sequence[Sequence[float]]) -> list[float]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ExcitationError("expected 3x3 matrix")
    a = [[float(value) for value in row] for row in matrix]
    if not all(math.isfinite(value) for row in a for value in row):
        raise ExcitationError("non-finite matrix")
    tolerance = 1e-12
    for row in range(3):
        for col in range(3):
            if abs(a[row][col] - a[col][row]) > tolerance * max(1.0, abs(a[row][col]), abs(a[col][row])):
                raise ExcitationError("matrix is not symmetric")
    p1 = a[0][1] ** 2 + a[0][2] ** 2 + a[1][2] ** 2
    if p1 <= 1e-30:
        values = [a[0][0], a[1][1], a[2][2]]
    else:
        q = (a[0][0] + a[1][1] + a[2][2]) / 3.0
        p2 = (
            (a[0][0] - q) ** 2 + (a[1][1] - q) ** 2 + (a[2][2] - q) ** 2
            + 2.0 * p1
        )
        p = math.sqrt(max(0.0, p2 / 6.0))
        if p <= 1e-30:
            values = [q, q, q]
        else:
            b = [[(a[row][col] - (q if row == col else 0.0)) / p for col in range(3)] for row in range(3)]
            r = max(-1.0, min(1.0, determinant3(b) / 2.0))
            phi = math.acos(r) / 3.0
            eig0 = q + 2.0 * p * math.cos(phi)
            eig2 = q + 2.0 * p * math.cos(phi + 2.0 * math.pi / 3.0)
            eig1 = 3.0 * q - eig0 - eig2
            values = [eig0, eig1, eig2]
    scale = max(1.0, max(abs(value) for value in values))
    values = [0.0 if value < 0 and abs(value) <= 1e-12 * scale else value for value in values]
    return sorted(values, reverse=True)


def tensor_summary(matrix: Sequence[Sequence[float]]) -> dict[str, Any]:
    eigenvalues = symmetric_eigenvalues3(matrix)
    trace = sum(eigenvalues)
    fractions = [value / trace if trace > 0 else 0.0 for value in eigenvalues]
    smallest = eigenvalues[-1]
    condition = eigenvalues[0] / smallest if smallest > max(1e-18, 1e-12 * max(1.0, eigenvalues[0])) else None
    return {
        "matrix": [[float(value) for value in row] for row in matrix],
        "eigenvalues_descending": eigenvalues,
        "energy_fractions_descending": fractions,
        "smallest_energy_fraction": fractions[-1],
        "condition_number": condition,
    }


def integrate_gyro(stamps_ns: Sequence[int], gyro: Sequence[Sequence[float]]) -> dict[str, Any]:
    if len(stamps_ns) != len(gyro) or len(stamps_ns) < 2:
        raise ExcitationError("gyro integration requires matching timestamp/vector arrays")
    signed = [0.0, 0.0, 0.0]
    absolute = [0.0, 0.0, 0.0]
    norm_integral = 0.0
    for index in range(1, len(stamps_ns)):
        delta_s = (stamps_ns[index] - stamps_ns[index - 1]) / 1e9
        if delta_s <= 0:
            raise ExcitationError("gyro timestamps are not increasing")
        previous = gyro[index - 1]
        current = gyro[index]
        for axis in range(3):
            signed[axis] += 0.5 * (float(previous[axis]) + float(current[axis])) * delta_s
            absolute[axis] += 0.5 * (abs(float(previous[axis])) + abs(float(current[axis]))) * delta_s
        norm_integral += 0.5 * (vector_norm(previous) + vector_norm(current)) * delta_s
    return {
        "signed_rotation_rad": {axis: signed[index] for index, axis in enumerate(AXES)},
        "integrated_abs_rotation_rad": {axis: absolute[index] for index, axis in enumerate(AXES)},
        "integrated_angular_speed_norm_rad": norm_integral,
    }


def coverage_summary(camera_a: Mapping[str, Any], camera_b: Mapping[str, Any], imu: Mapping[str, Any]) -> dict[str, Any]:
    starts = [int(camera_a["first_timestamp_ns"]), int(camera_b["first_timestamp_ns"]), int(imu["first_timestamp_ns"])]
    ends = [int(camera_a["last_timestamp_ns"]), int(camera_b["last_timestamp_ns"]), int(imu["last_timestamp_ns"])]
    union_start = min(starts)
    union_end = max(ends)
    shared_start = max(starts)
    shared_end = min(ends)
    union_s = max(0.0, (union_end - union_start) / 1e9)
    shared_s = max(0.0, (shared_end - shared_start) / 1e9)
    return {
        "union_start_ns": union_start,
        "union_end_ns": union_end,
        "union_duration_s": union_s,
        "shared_start_ns": shared_start,
        "shared_end_ns": shared_end,
        "shared_duration_s": shared_s,
        "shared_fraction_of_union": shared_s / union_s if union_s > 0 else 0.0,
    }


def gate_result(name: str, observed: float, threshold: float, comparison: str, unit: str, source: str | None = None) -> dict[str, Any]:
    if not math.isfinite(threshold) or threshold < 0:
        raise ExcitationError(f"{name}: threshold must be finite and non-negative")
    if comparison == ">=":
        passed = observed >= threshold
    elif comparison == "<=":
        passed = observed <= threshold
    else:
        raise ExcitationError(f"unsupported gate comparison {comparison}")
    result = {
        "name": name,
        "observed": observed,
        "threshold": threshold,
        "comparison": comparison,
        "unit": unit,
        "status": "PASS" if passed else "FAIL",
    }
    if source is not None:
        result["limiting_source"] = source
    return result


def build_gates(report: Mapping[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    coverage = report["coverage"]
    imu = report["imu"]
    gyro_axes = imu["gyroscope"]["axes"]
    accel_axes = imu["specific_force_variation"]["axes"]

    if args.min_shared_duration_s is not None:
        gates.append(gate_result("min_shared_duration_s", float(coverage["shared_duration_s"]), args.min_shared_duration_s, ">=", "s"))
    if args.min_shared_fraction is not None:
        gates.append(gate_result("min_shared_fraction", float(coverage["shared_fraction_of_union"]), args.min_shared_fraction, ">=", "fraction"))

    if args.min_abs_rotation_rad_per_axis is not None:
        values = imu["gyroscope"]["integrals"]["integrated_abs_rotation_rad"]
        limiting = min(AXES, key=lambda axis: float(values[axis]))
        gates.append(gate_result(
            "min_abs_rotation_rad_per_axis", float(values[limiting]), args.min_abs_rotation_rad_per_axis,
            ">=", "rad", limiting,
        ))
    if args.min_gyro_rms_rad_s_per_axis is not None:
        limiting = min(AXES, key=lambda axis: float(gyro_axes[axis]["signed"]["rms"]))
        gates.append(gate_result(
            "min_gyro_rms_rad_s_per_axis", float(gyro_axes[limiting]["signed"]["rms"]), args.min_gyro_rms_rad_s_per_axis,
            ">=", "rad/s", limiting,
        ))
    if args.min_accel_variation_std_m_s2_per_axis is not None:
        limiting = min(AXES, key=lambda axis: float(accel_axes[axis]["signed"]["std"]))
        gates.append(gate_result(
            "min_accel_variation_std_m_s2_per_axis", float(accel_axes[limiting]["signed"]["std"]), args.min_accel_variation_std_m_s2_per_axis,
            ">=", "m/s^2", limiting,
        ))
    if args.max_gyro_axis_energy_fraction is not None:
        limiting = max(AXES, key=lambda axis: float(gyro_axes[axis]["energy_fraction"]))
        gates.append(gate_result(
            "max_gyro_axis_energy_fraction", float(gyro_axes[limiting]["energy_fraction"]), args.max_gyro_axis_energy_fraction,
            "<=", "fraction", limiting,
        ))
    if args.min_gyro_smallest_energy_fraction is not None:
        observed = float(imu["gyroscope"]["second_moment"]["smallest_energy_fraction"])
        gates.append(gate_result("min_gyro_smallest_energy_fraction", observed, args.min_gyro_smallest_energy_fraction, ">=", "fraction"))
    if args.min_accel_variation_smallest_energy_fraction is not None:
        observed = float(imu["specific_force_variation"]["covariance"]["smallest_energy_fraction"])
        gates.append(gate_result("min_accel_variation_smallest_energy_fraction", observed, args.min_accel_variation_smallest_energy_fraction, ">=", "fraction"))
    return gates


def analyze(session_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    session = load_json(session_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise ExcitationError(f"{session_path}: expected schema {SESSION_SCHEMA!r}")

    camera_a_path = staged_file(session, session_path, "camera_a_csv")
    camera_b_path = staged_file(session, session_path, "camera_b_csv")
    imu_path = staged_file(session, session_path, "imu_csv")
    camera_a = read_camera_index(camera_a_path)
    camera_b = read_camera_index(camera_b_path)
    imu = read_imu(imu_path)

    structural: list[dict[str, str]] = []
    if camera_a["timestamps_ns"] != camera_b["timestamps_ns"]:
        structural.append({
            "severity": "error",
            "code": "stereo_timestamp_mismatch",
            "message": "camera_a and camera_b staged timestamps are not identical",
        })

    coverage = coverage_summary(camera_a, camera_b, imu)
    if coverage["shared_duration_s"] <= 0:
        structural.append({
            "severity": "error",
            "code": "no_common_time_coverage",
            "message": "camera_a, camera_b, and imu0 have no positive common time interval",
        })

    gyro = imu["gyro"]
    accel = imu["accel"]
    gyro_norms = [vector_norm(vector) for vector in gyro]
    accel_norms = [vector_norm(vector) for vector in accel]
    accel_mean, accel_covariance = covariance(accel)
    accel_centered = [tuple(float(vector[index]) - accel_mean[index] for index in range(3)) for vector in accel]
    accel_variation_norms = [vector_norm(vector) for vector in accel_centered]

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "dynamic_session": {"path": str(session_path), "sha256": sha256_file(session_path), "session_id": session.get("session_id")},
            "camera_a_csv": {"path": str(camera_a_path), "sha256": sha256_file(camera_a_path)},
            "camera_b_csv": {"path": str(camera_b_path), "sha256": sha256_file(camera_b_path)},
            "imu_csv": {"path": str(imu_path), "sha256": sha256_file(imu_path)},
        },
        "session_context": {
            "device": session.get("device"),
            "camera_mapping": session.get("camera_mapping"),
            "camera_time_reference": session.get("camera_time_reference"),
            "kalibr": session.get("kalibr"),
        },
        "coverage": coverage,
        "cameras": {
            "camera_a": {key: value for key, value in camera_a.items() if key != "timestamps_ns"},
            "camera_b": {key: value for key, value in camera_b.items() if key != "timestamps_ns"},
            "stereo_timestamp_identity": camera_a["timestamps_ns"] == camera_b["timestamps_ns"],
        },
        "imu": {
            "count": imu["count"],
            "first_timestamp_ns": imu["first_timestamp_ns"],
            "last_timestamp_ns": imu["last_timestamp_ns"],
            "duration_s": imu["duration_s"],
            "effective_rate_hz": imu["effective_rate_hz"],
            "interval_s": imu["interval_s"],
            "gyroscope": {
                "unit": "rad/s",
                "axes": axis_activity(gyro),
                "vector_norm": scalar_summary(gyro_norms),
                "integrals": integrate_gyro(imu["timestamps_ns"], gyro),
                "second_moment": tensor_summary(second_moment(gyro)),
            },
            "specific_force": {
                "unit": "m/s^2",
                "axes": axis_activity(accel),
                "vector_norm": scalar_summary(accel_norms),
                "mean_vector_m_s2": accel_mean,
            },
            "specific_force_variation": {
                "definition": "sample specific force minus whole-session mean specific-force vector",
                "unit": "m/s^2",
                "axes": axis_activity(accel_centered),
                "vector_norm": scalar_summary(accel_variation_norms),
                "covariance": tensor_summary(accel_covariance),
            },
        },
        "interpretation": {
            "claim": "excitation_and_coverage_proxy_evidence_not_formal_observability_proof",
            "target_detection_coverage": "not_evaluated_from_staged_index_csv",
            "notes": [
                "Gyroscope second-moment eigenvalue balance is a directionality proxy, not a Kalibr parameter-observability proof.",
                "Specific-force variation includes gravity-vector changes from orientation as well as linear acceleration; it is not pure translational acceleration.",
                "Camera indexes contain timestamps/image references but not AprilGrid corner geometry, so target image-plane coverage requires separate evidence.",
                "Good excitation evidence does not replace solver residual quality, temporal review, independent-session repeatability, or downstream VIO validation.",
            ],
        },
        "assessment": {
            "status": "PENDING",
            "structural_findings": structural,
            "gates": [],
            "threshold_policy": "No numeric excitation threshold is implied by Bividi; only explicit operator-supplied gates affect PASS/FAIL.",
        },
        "provenance": {"tool": "analyze_camera_imu_excitation.py", "tool_version": TOOL_VERSION},
    }

    gates = build_gates(report, args)
    report["assessment"]["gates"] = gates
    if any(item["severity"] == "error" for item in structural) or any(gate["status"] == "FAIL" for gate in gates):
        status = "FAIL"
    elif gates:
        status = "PASS"
    else:
        status = "EVIDENCE_ONLY_NO_THRESHOLDS"
    report["assessment"]["status"] = status
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    assessment = report["assessment"]
    cameras = report["cameras"]
    coverage = report["coverage"]
    imu = report["imu"]
    gyro_axes = imu["gyroscope"]["axes"]
    accel_var_axes = imu["specific_force_variation"]["axes"]
    rotations = imu["gyroscope"]["integrals"]["integrated_abs_rotation_rad"]

    lines = [
        "# Camera-IMU Dynamic Excitation Evidence",
        "",
        f"Status: **{assessment['status']}**",
        "",
        "## Time coverage",
        "",
        f"- Shared camera_a/camera_b/IMU duration: `{coverage['shared_duration_s']:.6g} s`",
        f"- Shared fraction of union: `{coverage['shared_fraction_of_union']:.6g}`",
        f"- Stereo timestamp identity: `{cameras['stereo_timestamp_identity']}`",
        f"- camera_a frames/rate: `{cameras['camera_a']['count']}` / `{cameras['camera_a']['effective_rate_hz']:.6g} Hz`",
        f"- camera_b frames/rate: `{cameras['camera_b']['count']}` / `{cameras['camera_b']['effective_rate_hz']:.6g} Hz`",
        f"- IMU samples/rate: `{imu['count']}` / `{imu['effective_rate_hz']:.6g} Hz`",
        "",
        "## Angular excitation",
        "",
        "| Axis | RMS [rad/s] | P95 | Max | Energy fraction | Integrated |ω| [rad] |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for axis in AXES:
        signed = gyro_axes[axis]["signed"]
        absolute = gyro_axes[axis]["absolute"]
        lines.append(
            f"| {axis.upper()} | {signed['rms']:.9g} | {absolute['p95']:.9g} | {absolute['max']:.9g} | "
            f"{gyro_axes[axis]['energy_fraction']:.9g} | {rotations[axis]:.9g} |"
        )
    gyro_tensor = imu["gyroscope"]["second_moment"]
    lines.extend([
        "",
        f"Gyro second-moment eigenvalue energy fractions: `{gyro_tensor['energy_fractions_descending']}`",
        f"Smallest gyro directionality fraction: `{gyro_tensor['smallest_energy_fraction']:.9g}`",
        "",
        "## Specific-force variation",
        "",
        "Definition: sample specific force minus whole-session mean specific-force vector. This includes gravity-direction change and linear acceleration.",
        "",
        "| Axis | Std [m/s²] | RMS [m/s²] | P95 | Max | Energy fraction |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for axis in AXES:
        signed = accel_var_axes[axis]["signed"]
        absolute = accel_var_axes[axis]["absolute"]
        lines.append(
            f"| {axis.upper()} | {signed['std']:.9g} | {signed['rms']:.9g} | {absolute['p95']:.9g} | "
            f"{absolute['max']:.9g} | {accel_var_axes[axis]['energy_fraction']:.9g} |"
        )
    accel_tensor = imu["specific_force_variation"]["covariance"]
    lines.extend([
        "",
        f"Specific-force variation covariance eigenvalue fractions: `{accel_tensor['energy_fractions_descending']}`",
        f"Smallest variation directionality fraction: `{accel_tensor['smallest_energy_fraction']:.9g}`",
        "",
        "## Structural findings",
        "",
    ])
    findings = assessment["structural_findings"]
    if findings:
        for finding in findings:
            lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}` — {finding['message']}")
    else:
        lines.append("- None.")

    lines.extend(["", "## Explicit gates", ""])
    gates = assessment["gates"]
    if gates:
        lines.extend(["| Gate | Observed | Requirement | Unit | Limiting source | Status |", "|---|---:|---:|---|---|---|"])
        for gate in gates:
            lines.append(
                f"| `{gate['name']}` | {gate['observed']:.9g} | {gate['comparison']} {gate['threshold']:.9g} | "
                f"{gate['unit']} | {gate.get('limiting_source', '—')} | **{gate['status']}** |"
            )
    else:
        lines.append("- No numeric gates supplied; this report is evidence-only.")

    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "- These metrics characterize motion excitation and common time coverage; they are not a formal observability proof.",
        "- Specific-force variation is not pure translational acceleration because gravity rotates in the sensor frame.",
        "- AprilGrid corner/image-plane coverage is not available from the staged camera index and is not evaluated here.",
        "- Solver residual quality, temporal correctness, repeated-session stability, protocol timing evidence, and downstream VIO remain separate evidence classes.",
        "",
    ])
    return "\n".join(lines)


def write_fixture(root: Path, *, one_axis_gyro: bool = False) -> Path:
    bundle = root / "bundle"
    bundle.mkdir(parents=True)
    camera_a = bundle / "camera_a.csv"
    camera_b = bundle / "camera_b.csv"
    imu = bundle / "imu0.csv"
    for camera, prefix in ((camera_a, "a"), (camera_b, "b")):
        with camera.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["timestamp_ns", "image_path", "frame_index", "frame_sequence"])
            for index in range(5):
                writer.writerow([1_000_000_000 + index * 20_000_000, f"{prefix}{index}.png", index, index])
    with imu.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_ns", "omega_x", "omega_y", "omega_z", "alpha_x", "alpha_y", "alpha_z"])
        for index in range(41):
            phase = index * 0.2
            if one_axis_gyro:
                omega = (math.sin(phase), 0.0, 0.0)
            else:
                omega = (math.sin(phase), math.cos(phase * 0.7), math.sin(phase * 1.3 + 0.4))
            alpha = (
                2.0 * math.sin(phase * 0.8),
                3.0 * math.cos(phase * 0.5),
                9.80665 + 1.5 * math.sin(phase * 1.1),
            )
            writer.writerow([1_000_000_000 + index * 2_000_000, *omega, *alpha])
    session = bundle / "session.json"
    session.write_text(json.dumps({
        "schema": SESSION_SCHEMA,
        "session_id": "synthetic-excitation",
        "device": {"serial": "SYNTHETIC"},
        "camera_mapping": {"camera_a": "cam0", "camera_b": "cam1", "guardrail": "synthetic"},
        "camera_time_reference": {"kind": "exposure_midpoint", "time_shift_definition": "t_imu_s = t_camera_reference_s + offset_s"},
        "kalibr": {"backend": "ethz-asl/kalibr", "revision": "synthetic"},
        "staged": {"camera_a_csv": "camera_a.csv", "camera_b_csv": "camera_b.csv", "imu_csv": "imu0.csv"},
    }), encoding="utf-8")
    return session


def empty_args() -> argparse.Namespace:
    return argparse.Namespace(
        min_shared_duration_s=None,
        min_shared_fraction=None,
        min_abs_rotation_rad_per_axis=None,
        min_gyro_rms_rad_s_per_axis=None,
        min_accel_variation_std_m_s2_per_axis=None,
        max_gyro_axis_energy_fraction=None,
        min_gyro_smallest_energy_fraction=None,
        min_accel_variation_smallest_energy_fraction=None,
    )


def self_test() -> None:
    assert symmetric_eigenvalues3([[3.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]]) == [3.0, 2.0, 1.0]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session = write_fixture(root)
        args = empty_args()
        report = analyze(session, args)
        assert report["assessment"]["status"] == "EVIDENCE_ONLY_NO_THRESHOLDS"
        assert report["cameras"]["stereo_timestamp_identity"] is True
        assert report["coverage"]["shared_duration_s"] > 0
        assert report["imu"]["gyroscope"]["integrals"]["integrated_abs_rotation_rad"]["x"] > 0
        assert report["imu"]["gyroscope"]["second_moment"]["smallest_energy_fraction"] > 0

        passing = empty_args()
        passing.min_shared_duration_s = 0.05
        passing.min_shared_fraction = 0.9
        passing.min_abs_rotation_rad_per_axis = 0.01
        report = analyze(session, passing)
        assert report["assessment"]["status"] == "PASS"
        assert len(report["assessment"]["gates"]) == 3

        one_axis = write_fixture(root / "one-axis", one_axis_gyro=True)
        failing = empty_args()
        failing.min_gyro_smallest_energy_fraction = 0.01
        report = analyze(one_axis, failing)
        assert report["assessment"]["status"] == "FAIL"
        assert report["imu"]["gyroscope"]["second_moment"]["smallest_energy_fraction"] == 0.0

        bad_bundle = root / "bad-stereo"
        bad_session = write_fixture(bad_bundle)
        camera_b = bad_session.parent / "camera_b.csv"
        rows = list(csv.reader(camera_b.open("r", encoding="utf-8", newline="")))
        rows[2][0] = str(int(rows[2][0]) + 1)
        with camera_b.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows(rows)
        report = analyze(bad_session, empty_args())
        assert report["assessment"]["status"] == "FAIL"
        assert any(item["code"] == "stereo_timestamp_mismatch" for item in report["assessment"]["structural_findings"])

        markdown = render_markdown(analyze(session, passing))
        assert "Angular excitation" in markdown
        assert "Specific-force variation" in markdown
        assert "PASS" in markdown

    print("Camera-IMU dynamic excitation laboratory self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--min-shared-duration-s", type=float)
    parser.add_argument("--min-shared-fraction", type=float)
    parser.add_argument("--min-abs-rotation-rad-per-axis", type=float)
    parser.add_argument("--min-gyro-rms-rad-s-per-axis", type=float)
    parser.add_argument("--min-accel-variation-std-m-s2-per-axis", type=float)
    parser.add_argument("--max-gyro-axis-energy-fraction", type=float)
    parser.add_argument("--min-gyro-smallest-energy-fraction", type=float)
    parser.add_argument("--min-accel-variation-smallest-energy-fraction", type=float)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.session is None:
        print("session is required", file=sys.stderr)
        return 2
    try:
        session = args.session.resolve()
        report = analyze(session, args)
        prefix = args.output_prefix or session.with_name(f"{session.stem}.excitation")
        json_path = Path(f"{prefix}.json")
        md_path = Path(f"{prefix}.md")
        json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(render_markdown(report), encoding="utf-8")
    except (ExcitationError, OSError) as exc:
        print(f"Camera-IMU excitation analysis failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "status": report["assessment"]["status"]}, indent=2))
    return 7 if report["assessment"]["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())