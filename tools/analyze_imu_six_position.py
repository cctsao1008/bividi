#!/usr/bin/env python3
"""Six-position gravity / accelerometer-axis laboratory for Bividi IMU traces.

Consumes six stationary lossless Nori IMU traces with the target Bividi IMU
frame placed +X/-X/+Y/-Y/+Z/-Z upward.  Pose labels refer to accelerometer
specific force: a correctly mapped target +X-up pose is expected to measure
approximately +1 g on target X while stationary.

The tool works in raw counts and does not reuse the DECXIN demo full-scale.
From the six pose means it estimates an evidence-only affine gravity model:

    raw_counts ~= bias_raw + A_raw_per_g * target_specific_force_g

It also infers the best signed raw-axis permutation, reports cross-axis coupling,
scale consistency, pair-center residuals, and static gyro-bias evidence.  The
result is a calibration candidate / sanity report, not an automatically promoted
Bividi calibration artifact.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPORT_SCHEMA = "bividi.calibration.imu_six_position_analysis.v1"
AXES = ("x", "y", "z")
POSES = ("plus_x", "minus_x", "plus_y", "minus_y", "plus_z", "minus_z")
POSE_VECTOR = {
    "plus_x": (1.0, 0.0, 0.0),
    "minus_x": (-1.0, 0.0, 0.0),
    "plus_y": (0.0, 1.0, 0.0),
    "minus_y": (0.0, -1.0, 0.0),
    "plus_z": (0.0, 0.0, 1.0),
    "minus_z": (0.0, 0.0, -1.0),
}
REQUIRED_COLUMNS = {
    "sample_valid",
    "imu_extended_time_us",
    "accel_raw_x", "accel_raw_y", "accel_raw_z",
    "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
}


@dataclass
class RunningStats:
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: float) -> None:
        if not math.isfinite(value):
            raise ValueError("non-finite sample")
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def report(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": self.mean,
            "stddev_population": math.sqrt(self.m2 / self.count) if self.count else None,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass
class TimingStats:
    valid_samples: int = 0
    invalid_samples: int = 0
    first_us: int | None = None
    last_us: int | None = None
    previous_us: int | None = None
    duplicates: int = 0
    backwards: int = 0
    interval_count: int = 0
    interval_sum_us: float = 0.0
    interval_min_us: int | None = None
    interval_max_us: int | None = None

    def add(self, timestamp_us: int) -> None:
        if self.first_us is None:
            self.first_us = timestamp_us
        if self.previous_us is not None:
            dt = timestamp_us - self.previous_us
            self.interval_count += 1
            self.interval_sum_us += dt
            self.interval_min_us = dt if self.interval_min_us is None else min(self.interval_min_us, dt)
            self.interval_max_us = dt if self.interval_max_us is None else max(self.interval_max_us, dt)
            if dt == 0:
                self.duplicates += 1
            elif dt < 0:
                self.backwards += 1
        self.previous_us = timestamp_us
        self.last_us = timestamp_us
        self.valid_samples += 1

    def report(self) -> dict[str, Any]:
        duration_s = None
        rate_hz = None
        if (
            self.valid_samples > 1
            and self.first_us is not None
            and self.last_us is not None
            and self.last_us > self.first_us
        ):
            duration_s = (self.last_us - self.first_us) / 1_000_000.0
            rate_hz = (self.valid_samples - 1) / duration_s
        return {
            "valid_samples": self.valid_samples,
            "invalid_samples": self.invalid_samples,
            "duration_s": duration_s,
            "effective_rate_hz": rate_hz,
            "duplicate_timestamp_intervals": self.duplicates,
            "backward_timestamp_intervals": self.backwards,
            "interval_us": {
                "count": self.interval_count,
                "mean": self.interval_sum_us / self.interval_count if self.interval_count else None,
                "minimum": self.interval_min_us,
                "maximum": self.interval_max_us,
            },
        }


def summarize_trace(
    path: Path,
    *,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    accel = [RunningStats() for _ in AXES]
    gyro = [RunningStats() for _ in AXES]
    timing = TimingStats()
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: trace CSV has no header")
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")
        for line, row in enumerate(reader, start=2):
            valid_text = row["sample_valid"].strip().lower()
            if valid_text not in {"true", "false"}:
                raise ValueError(f"{path}:{line}: invalid sample_valid {row['sample_valid']!r}")
            if valid_text == "false":
                timing.invalid_samples += 1
                if not allow_invalid_samples:
                    raise ValueError(
                        f"{path}:{line}: invalid IMU sample; use --allow-invalid-samples only for exploratory analysis"
                    )
                continue
            try:
                timestamp = int(row["imu_extended_time_us"], 10)
                accel_values = [float(row[f"accel_raw_{axis}"]) for axis in AXES]
                gyro_values = [float(row[f"gyro_raw_{axis}"]) for axis in AXES]
            except ValueError as exc:
                raise ValueError(f"{path}:{line}: invalid numeric IMU field") from exc
            if not all(math.isfinite(value) for value in accel_values + gyro_values):
                raise ValueError(f"{path}:{line}: non-finite IMU value")
            if timing.previous_us is not None and timestamp <= timing.previous_us and not allow_timing_anomalies:
                kind = "duplicate" if timestamp == timing.previous_us else "backward"
                raise ValueError(
                    f"{path}:{line}: {kind} timestamp; use --allow-timing-anomalies only for exploratory analysis"
                )
            timing.add(timestamp)
            for index in range(3):
                accel[index].add(accel_values[index])
                gyro[index].add(gyro_values[index])

    if timing.valid_samples < 2:
        raise ValueError(f"{path}: fewer than two valid IMU samples")
    return {
        "source": str(path),
        "timing": timing.report(),
        "accelerometer_raw": {axis: accel[index].report() for index, axis in enumerate(AXES)},
        "gyroscope_raw": {axis: gyro[index].report() for index, axis in enumerate(AXES)},
    }


def mean_vector(summary: dict[str, Any], sensor: str) -> list[float]:
    return [float(summary[sensor][axis]["mean"]) for axis in AXES]


def vector_add(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(x) + float(y) for x, y in zip(a, b)]


def vector_sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(x) - float(y) for x, y in zip(a, b)]


def vector_scale(a: Sequence[float], factor: float) -> list[float]:
    return [float(x) * factor for x in a]


def vector_norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in a))


def mat_vec(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> list[float]:
    return [sum(float(value) * float(component) for value, component in zip(row, vector)) for row in matrix]


def determinant3(matrix: Sequence[Sequence[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def inverse3(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    det = determinant3(matrix)
    scale = max(abs(float(value)) for row in matrix for value in row)
    if scale == 0.0 or abs(det) <= (scale ** 3) * 1e-12:
        raise ValueError("six-position gravity matrix is singular or numerically degenerate")
    a, b, c = matrix
    cofactors = [
        [b[1] * c[2] - b[2] * c[1], -(b[0] * c[2] - b[2] * c[0]), b[0] * c[1] - b[1] * c[0]],
        [-(a[1] * c[2] - a[2] * c[1]), a[0] * c[2] - a[2] * c[0], -(a[0] * c[1] - a[1] * c[0])],
        [a[1] * b[2] - a[2] * b[1], -(a[0] * b[2] - a[2] * b[0]), a[0] * b[1] - a[1] * b[0]],
    ]
    # inverse = transpose(cofactor) / det
    return [[cofactors[col][row] / det for col in range(3)] for row in range(3)]


def matrix_inf_norm(matrix: Sequence[Sequence[float]]) -> float:
    return max(sum(abs(float(value)) for value in row) for row in matrix)


def build_gravity_model(pose_summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    means = {pose: mean_vector(summary, "accelerometer_raw") for pose, summary in pose_summaries.items()}
    pair_centers: dict[str, list[float]] = {}
    columns: list[list[float]] = []
    for axis in AXES:
        plus = means[f"plus_{axis}"]
        minus = means[f"minus_{axis}"]
        pair_centers[axis] = vector_scale(vector_add(plus, minus), 0.5)
        columns.append(vector_scale(vector_sub(plus, minus), 0.5))

    bias = [statistics.fmean(pair_centers[axis][row] for axis in AXES) for row in range(3)]
    # rows = raw axes; columns = target Bividi axes
    raw_per_g = [[columns[col][row] for col in range(3)] for row in range(3)]
    raw_to_target_g = inverse3(raw_per_g)
    condition_inf = matrix_inf_norm(raw_per_g) * matrix_inf_norm(raw_to_target_g)

    center_residuals = {
        axis: vector_sub(pair_centers[axis], bias)
        for axis in AXES
    }
    center_rms = math.sqrt(
        statistics.fmean(value * value for residual in center_residuals.values() for value in residual)
    )

    pose_fit: dict[str, Any] = {}
    for pose in POSES:
        expected = list(POSE_VECTOR[pose])
        predicted_raw = vector_add(bias, mat_vec(raw_per_g, expected))
        raw_residual = vector_sub(means[pose], predicted_raw)
        calibrated = mat_vec(raw_to_target_g, vector_sub(means[pose], bias))
        target_residual = vector_sub(calibrated, expected)
        pose_fit[pose] = {
            "raw_mean": means[pose],
            "predicted_raw_mean": predicted_raw,
            "raw_residual": raw_residual,
            "raw_residual_l2_counts": vector_norm(raw_residual),
            "calibrated_target_specific_force_g": calibrated,
            "expected_target_specific_force_g": expected,
            "target_residual_g": target_residual,
            "target_residual_l2_g": vector_norm(target_residual),
            "calibrated_gravity_magnitude_g": vector_norm(calibrated),
        }

    return {
        "bias_raw_counts": bias,
        "pair_centers_raw_counts": pair_centers,
        "pair_center_residuals_raw_counts": center_residuals,
        "pair_center_rms_counts": center_rms,
        "raw_counts_per_target_g_matrix": raw_per_g,
        "target_g_per_raw_count_matrix": raw_to_target_g,
        "matrix_determinant": determinant3(raw_per_g),
        "matrix_condition_inf": condition_inf,
        "pose_fit": pose_fit,
    }


def infer_signed_axis_mapping(raw_per_g: Sequence[Sequence[float]]) -> dict[str, Any]:
    # permutation[col] = raw row assigned to target column
    best_perm: tuple[int, int, int] | None = None
    best_score = -1.0
    for permutation in itertools.permutations(range(3)):
        score = sum(abs(float(raw_per_g[permutation[col]][col])) for col in range(3))
        if score > best_score:
            best_score = score
            best_perm = permutation
    assert best_perm is not None

    signed_matrix = [[0.0] * 3 for _ in range(3)]  # target rows <- raw cols
    target_mapping: dict[str, Any] = {}
    scales: list[float] = []
    for col, target_axis in enumerate(AXES):
        raw_row = best_perm[col]
        component = float(raw_per_g[raw_row][col])
        sign = 1.0 if component >= 0.0 else -1.0
        signed_matrix[col][raw_row] = sign
        others = [float(raw_per_g[row][col]) for row in range(3) if row != raw_row]
        off_l2 = vector_norm(others)
        dominant = abs(component)
        second = max((abs(value) for value in others), default=0.0)
        scale_l2 = vector_norm([float(raw_per_g[row][col]) for row in range(3)])
        scales.append(scale_l2)
        target_mapping[target_axis] = {
            "raw_axis": AXES[raw_row],
            "sign": "+" if sign > 0 else "-",
            "expression": f"target_{target_axis} ~= {'+' if sign > 0 else '-'}raw_{AXES[raw_row]}",
            "assigned_component_counts_per_g": component,
            "column_l2_counts_per_g": scale_l2,
            "g_per_count_from_column_l2": 1.0 / scale_l2 if scale_l2 > 0.0 else None,
            "off_axis_l2_ratio": off_l2 / dominant if dominant > 0.0 else None,
            "dominance_ratio_to_second": dominant / second if second > 0.0 else None,
        }

    raw_mapping: dict[str, Any] = {}
    for target_col, raw_row in enumerate(best_perm):
        sign = signed_matrix[target_col][raw_row]
        raw_mapping[AXES[raw_row]] = {
            "target_axis": AXES[target_col],
            "sign": "+" if sign > 0 else "-",
            "expression": f"raw_{AXES[raw_row]} ~= {'+' if sign > 0 else '-'}target_{AXES[target_col]} (ignoring scale/coupling)",
        }

    scale_mean = statistics.fmean(scales)
    scale_spread_pct = None
    if scale_mean > 0.0:
        scale_spread_pct = 100.0 * (max(scales) - min(scales)) / scale_mean

    return {
        "target_from_raw": target_mapping,
        "raw_to_target": raw_mapping,
        "signed_permutation_target_from_raw": signed_matrix,
        "signed_permutation_determinant": determinant3(signed_matrix),
        "assignment_score_counts_per_g": best_score,
        "counts_per_g_column_l2": {axis: scales[index] for index, axis in enumerate(AXES)},
        "counts_per_g_scale_spread_pct": scale_spread_pct,
        "handedness_note": (
            "A signed-permutation determinant of +1 preserves handedness and -1 flips handedness, "
            "provided the raw XYZ basis and target Bividi basis are each independently defined as right-handed."
        ),
    }


def gyro_static_summary(pose_summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for axis in AXES:
        entries = [
            (
                int(pose_summaries[pose]["gyroscope_raw"][axis]["count"]),
                float(pose_summaries[pose]["gyroscope_raw"][axis]["mean"]),
            )
            for pose in POSES
        ]
        total = sum(count for count, _ in entries)
        weighted = sum(count * mean for count, mean in entries) / total
        pose_means = [mean for _, mean in entries]
        result[axis] = {
            "weighted_stationary_mean_raw_counts": weighted,
            "pose_mean_min_raw_counts": min(pose_means),
            "pose_mean_max_raw_counts": max(pose_means),
            "pose_mean_range_raw_counts": max(pose_means) - min(pose_means),
        }
    return result


def analyze(
    pose_paths: dict[str, Path],
    *,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    summaries = {
        pose: summarize_trace(
            pose_paths[pose],
            allow_invalid_samples=allow_invalid_samples,
            allow_timing_anomalies=allow_timing_anomalies,
        )
        for pose in POSES
    }
    model = build_gravity_model(summaries)
    mapping = infer_signed_axis_mapping(model["raw_counts_per_target_g_matrix"])
    return {
        "schema": REPORT_SCHEMA,
        "pose_convention": {
            "meaning": (
                "plus_x means target Bividi IMU +X axis physically points upward while stationary; "
                "the expected accelerometer specific-force vector is therefore approximately [+1,0,0] g. "
                "The same convention applies to the other five poses."
            ),
            "vectors_g": {pose: list(POSE_VECTOR[pose]) for pose in POSES},
        },
        "poses": summaries,
        "accelerometer_gravity_model": model,
        "accelerometer_axis_mapping": mapping,
        "gyroscope_static_evidence": gyro_static_summary(summaries),
        "status": "candidate_evidence_only_not_promoted_to_calibration_artifact",
        "guardrails": [
            "The six-position method assumes each labelled pose is mechanically stationary and accurately aligned with gravity.",
            "The affine accelerometer matrix is a sanity/calibration candidate; pose fixture error and sensor misalignment are not separable from six means alone.",
            "Static gravity does not identify gyroscope axis permutation or sign. Controlled rotations are required for gyro-axis validation.",
            "No DECXIN vendor-demo accelerometer full-scale is reused as truth.",
            "No pass/fail threshold for cross-axis coupling, scale spread, matrix condition, or pair-center error is invented by default.",
            "A signed-permutation handedness result is meaningful only after the raw and target coordinate bases are independently defined.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    mapping = report["accelerometer_axis_mapping"]
    model = report["accelerometer_gravity_model"]
    lines = [
        "# Six-Position IMU Gravity / Axis Laboratory",
        "",
        f"Status: `{report['status']}`",
        "",
        "## Inferred accelerometer axis mapping",
        "",
        "| Target axis | Raw axis | Sign | Assigned counts/g | Column L2 counts/g | Cross-axis L2 ratio | Dominance ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for axis in AXES:
        item = mapping["target_from_raw"][axis]
        lines.append(
            f"| {axis} | {item['raw_axis']} | {item['sign']} | {fmt(item['assigned_component_counts_per_g'])} | "
            f"{fmt(item['column_l2_counts_per_g'])} | {fmt(item['off_axis_l2_ratio'])} | "
            f"{fmt(item['dominance_ratio_to_second'])} |"
        )
    lines += [
        "",
        f"- Signed-permutation determinant: {fmt(mapping['signed_permutation_determinant'])}",
        f"- Counts/g scale spread: {fmt(mapping['counts_per_g_scale_spread_pct'])}%",
        f"- Gravity matrix condition number (inf): {fmt(model['matrix_condition_inf'])}",
        f"- Pair-center RMS disagreement: {fmt(model['pair_center_rms_counts'])} raw counts",
        "",
        mapping["handedness_note"],
        "",
        "## Candidate affine gravity model",
        "",
        "`raw_counts ~= bias + A * target_specific_force_g`",
        "",
        f"- Bias raw counts: `{[fmt(value) for value in model['bias_raw_counts']]}`",
        "",
        "A (raw counts per target g):",
        "",
        "```text",
    ]
    for row in model["raw_counts_per_target_g_matrix"]:
        lines.append("[ " + ", ".join(fmt(value) for value in row) + " ]")
    lines += ["```", "", "Inverse A (target g per raw count):", "", "```text"]
    for row in model["target_g_per_raw_count_matrix"]:
        lines.append("[ " + ", ".join(fmt(value) for value in row) + " ]")
    lines += [
        "```",
        "",
        "## Pose fit evidence",
        "",
        "| Pose | raw residual L2 (counts) | target residual L2 (g) | calibrated magnitude (g) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for pose in POSES:
        item = model["pose_fit"][pose]
        lines.append(
            f"| {pose} | {fmt(item['raw_residual_l2_counts'])} | {fmt(item['target_residual_l2_g'])} | "
            f"{fmt(item['calibrated_gravity_magnitude_g'])} |"
        )
    lines += [
        "",
        "## Static gyroscope evidence",
        "",
        "Static poses can estimate stationary gyro mean stability, but cannot establish gyro axis/sign mapping.",
        "",
        "| Raw gyro axis | weighted mean | pose-mean range |",
        "| --- | ---: | ---: |",
    ]
    for axis in AXES:
        item = report["gyroscope_static_evidence"][axis]
        lines.append(
            f"| {axis} | {fmt(item['weighted_stationary_mean_raw_counts'])} | "
            f"{fmt(item['pose_mean_range_raw_counts'])} |"
        )
    lines += ["", "## Guardrails", ""]
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines)


def write_pose_csv(report: dict[str, Any], path: Path) -> None:
    fields = [
        "pose", "source", "samples", "duration_s", "rate_hz",
        "accel_mean_x", "accel_mean_y", "accel_mean_z",
        "accel_std_x", "accel_std_y", "accel_std_z",
        "gyro_mean_x", "gyro_mean_y", "gyro_mean_z",
        "gyro_std_x", "gyro_std_y", "gyro_std_z",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for pose in POSES:
            summary = report["poses"][pose]
            row: dict[str, Any] = {
                "pose": pose,
                "source": summary["source"],
                "samples": summary["timing"]["valid_samples"],
                "duration_s": summary["timing"]["duration_s"],
                "rate_hz": summary["timing"]["effective_rate_hz"],
            }
            for axis in AXES:
                row[f"accel_mean_{axis}"] = summary["accelerometer_raw"][axis]["mean"]
                row[f"accel_std_{axis}"] = summary["accelerometer_raw"][axis]["stddev_population"]
                row[f"gyro_mean_{axis}"] = summary["gyroscope_raw"][axis]["mean"]
                row[f"gyro_std_{axis}"] = summary["gyroscope_raw"][axis]["stddev_population"]
            writer.writerow(row)


def write_fixture(path: Path, raw_mean: Sequence[float], gyro_bias: Sequence[float], pose_seed: int) -> None:
    header = [
        "frame_index", "frame_sequence", "host_receive_monotonic_ns",
        "exposure_start_raw_us", "exposure_end_raw_us",
        "exposure_start_extended_us", "exposure_end_extended_us",
        "sample_index", "sample_valid", "imu_raw_time_us", "imu_extended_time_us",
        "accel_raw_x", "accel_raw_y", "accel_raw_z", "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for index in range(64):
            t = 1_000_000 + index * 5_000
            jitter = ((index * 13 + pose_seed * 7) % 5) - 2
            accel = [raw_mean[i] + jitter * (i + 1) * 0.25 for i in range(3)]
            gyro = [gyro_bias[i] + jitter * 0.05 * (i + 1) for i in range(3)]
            writer.writerow([
                index // 4, 100 + index // 4, 0, t, t + 1000, t, t + 1000,
                index % 4, "true", t & 0xFFFFFFFF, t,
                *accel, *gyro,
            ])


def self_test() -> int:
    # Synthetic target-g -> raw-count model with a nontrivial signed axis map:
    # target X ~= +raw Y, target Y ~= -raw Z, target Z ~= -raw X.
    bias = [120.0, -75.0, 30.0]
    matrix = [
        [80.0, 50.0, -8200.0],
        [8192.0, -70.0, 40.0],
        [-60.0, -8100.0, 90.0],
    ]
    gyro_bias = [8.0, -11.0, 3.0]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        pose_paths: dict[str, Path] = {}
        for seed, pose in enumerate(POSES):
            expected = POSE_VECTOR[pose]
            raw_mean = vector_add(bias, mat_vec(matrix, expected))
            path = root / f"{pose}.csv"
            write_fixture(path, raw_mean, gyro_bias, seed)
            pose_paths[pose] = path
        report = analyze(
            pose_paths,
            allow_invalid_samples=False,
            allow_timing_anomalies=False,
        )
        mapping = report["accelerometer_axis_mapping"]["target_from_raw"]
        assert mapping["x"]["raw_axis"] == "y" and mapping["x"]["sign"] == "+"
        assert mapping["y"]["raw_axis"] == "z" and mapping["y"]["sign"] == "-"
        assert mapping["z"]["raw_axis"] == "x" and mapping["z"]["sign"] == "-"
        assert abs(report["accelerometer_axis_mapping"]["signed_permutation_determinant"] - 1.0) < 1e-12
        recovered_bias = report["accelerometer_gravity_model"]["bias_raw_counts"]
        for actual, expected_value in zip(recovered_bias, bias):
            assert abs(actual - expected_value) < 0.2
        inverse = report["accelerometer_gravity_model"]["target_g_per_raw_count_matrix"]
        probe_target = [0.2, -0.3, 0.9]
        probe_raw = vector_add(bias, mat_vec(matrix, probe_target))
        reconstructed = mat_vec(inverse, vector_sub(probe_raw, recovered_bias))
        for actual, expected_value in zip(reconstructed, probe_target):
            assert abs(actual - expected_value) < 1e-4
        assert "Six-Position IMU" in render_markdown(report)
        csv_path = root / "poses.csv"
        write_pose_csv(report, csv_path)
        assert csv_path.exists() and csv_path.stat().st_size > 0
    print("six-position IMU laboratory self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze six stationary +/-X +/-Y +/-Z Bividi IMU gravity traces"
    )
    for pose in POSES:
        parser.add_argument(f"--{pose.replace('_', '-')}", type=Path, dest=pose)
    parser.add_argument("--allow-invalid-samples", action="store_true",
                        help="exploratory only: skip invalid samples instead of rejecting a pose")
    parser.add_argument("--allow-timing-anomalies", action="store_true",
                        help="exploratory only: permit duplicate/backward device timestamps")
    parser.add_argument("--output-prefix", type=Path,
                        help="write PREFIX.sixpos.csv, PREFIX.sixpos.json, and PREFIX.sixpos.md")
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    pose_paths = {pose: getattr(args, pose) for pose in POSES}
    missing = [pose for pose, path in pose_paths.items() if path is None]
    if missing:
        print("missing required pose trace(s): " + ", ".join(missing), file=sys.stderr)
        return 3
    try:
        report = analyze(
            pose_paths,
            allow_invalid_samples=args.allow_invalid_samples,
            allow_timing_anomalies=args.allow_timing_anomalies,
        )
    except ValueError as exc:
        print(f"analyze_imu_six_position: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report)
    print(markdown)
    csv_out = args.csv_out
    json_out = args.json_out
    markdown_out = args.markdown_out
    if args.output_prefix is not None:
        csv_out = csv_out or Path(str(args.output_prefix) + ".sixpos.csv")
        json_out = json_out or Path(str(args.output_prefix) + ".sixpos.json")
        markdown_out = markdown_out or Path(str(args.output_prefix) + ".sixpos.md")
    if csv_out is not None:
        write_pose_csv(report, csv_out)
    if json_out is not None:
        json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_out is not None:
        markdown_out.write_text(markdown + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
