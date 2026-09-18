#!/usr/bin/env python3
"""Controlled-rotation gyroscope axis/sign laboratory for Bividi IMU traces.

Consumes one stationary baseline plus six dynamic lossless Nori IMU traces:
positive/negative right-hand-rule rotations about target Bividi +X/+Y/+Z.

The default analysis stays in raw gyro counts. It estimates stationary bias,
integrates bias-corrected raw rate over device time, infers the best signed raw
axis permutation, reports pair symmetry/cross-axis coupling, and optionally
estimates a 3x3 gyro sensitivity matrix when the experiment supplies a known
common rotation angle.

No DECXIN demo full-scale, nominal sample rate, rotation angle, or axis mapping
is inferred silently. Results are evidence candidates, not automatically
promoted calibration artifacts.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPORT_SCHEMA = "bividi.calibration.imu_gyro_rotation_analysis.v1"
ACCEL_REPORT_SCHEMA = "bividi.calibration.imu_six_position_analysis.v1"
AXES = ("x", "y", "z")
RUNS = ("plus_x", "minus_x", "plus_y", "minus_y", "plus_z", "minus_z")
RUN_VECTOR = {
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
    positive_interval_count: int = 0
    interval_sum_us: float = 0.0
    interval_min_us: int | None = None
    interval_max_us: int | None = None

    def observe(self, timestamp_us: int) -> int | None:
        dt: int | None = None
        if self.first_us is None:
            self.first_us = timestamp_us
        if self.previous_us is not None:
            dt = timestamp_us - self.previous_us
            if dt == 0:
                self.duplicates += 1
            elif dt < 0:
                self.backwards += 1
            else:
                self.positive_interval_count += 1
                self.interval_sum_us += dt
                self.interval_min_us = dt if self.interval_min_us is None else min(self.interval_min_us, dt)
                self.interval_max_us = dt if self.interval_max_us is None else max(self.interval_max_us, dt)
        self.previous_us = timestamp_us
        self.last_us = timestamp_us
        self.valid_samples += 1
        return dt

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
            "positive_interval_us": {
                "count": self.positive_interval_count,
                "mean": self.interval_sum_us / self.positive_interval_count if self.positive_interval_count else None,
                "minimum": self.interval_min_us,
                "maximum": self.interval_max_us,
            },
        }


def vector_add(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(x) + float(y) for x, y in zip(a, b)]


def vector_sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(x) - float(y) for x, y in zip(a, b)]


def vector_scale(a: Sequence[float], factor: float) -> list[float]:
    return [float(value) * factor for value in a]


def vector_norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in a))


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
        raise ValueError("gyro response matrix is singular or numerically degenerate")
    a, b, c = matrix
    cofactors = [
        [b[1] * c[2] - b[2] * c[1], -(b[0] * c[2] - b[2] * c[0]), b[0] * c[1] - b[1] * c[0]],
        [-(a[1] * c[2] - a[2] * c[1]), a[0] * c[2] - a[2] * c[0], -(a[0] * c[1] - a[1] * c[0])],
        [a[1] * b[2] - a[2] * b[1], -(a[0] * b[2] - a[2] * b[0]), a[0] * b[1] - a[1] * b[0]],
    ]
    return [[cofactors[col][row] / det for col in range(3)] for row in range(3)]


def matrix_inf_norm(matrix: Sequence[Sequence[float]]) -> float:
    return max(sum(abs(float(value)) for value in row) for row in matrix)


def read_rows(path: Path) -> Iterable[tuple[int, bool, list[float]]]:
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
            try:
                timestamp_us = int(row["imu_extended_time_us"], 10)
            except ValueError as exc:
                raise ValueError(f"{path}:{line}: invalid imu_extended_time_us") from exc
            if valid_text == "false":
                yield timestamp_us, False, []
                continue
            try:
                gyro = [float(row[f"gyro_raw_{axis}"]) for axis in AXES]
            except ValueError as exc:
                raise ValueError(f"{path}:{line}: invalid raw gyro value") from exc
            if not all(math.isfinite(value) for value in gyro):
                raise ValueError(f"{path}:{line}: non-finite raw gyro value")
            yield timestamp_us, True, gyro


def stationary_baseline(
    path: Path,
    *,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    timing = TimingStats()
    stats = [RunningStats() for _ in AXES]
    for timestamp_us, valid, gyro in read_rows(path):
        if not valid:
            timing.invalid_samples += 1
            if not allow_invalid_samples:
                raise ValueError(
                    f"{path}: invalid IMU sample; use --allow-invalid-samples only for exploratory analysis"
                )
            continue
        if timing.previous_us is not None and timestamp_us <= timing.previous_us and not allow_timing_anomalies:
            kind = "duplicate" if timestamp_us == timing.previous_us else "backward"
            raise ValueError(f"{path}: {kind} timestamp; use --allow-timing-anomalies only for exploratory analysis")
        timing.observe(timestamp_us)
        for index in range(3):
            stats[index].add(gyro[index])
    if timing.valid_samples < 2:
        raise ValueError(f"{path}: fewer than two valid stationary samples")
    return {
        "source": str(path),
        "timing": timing.report(),
        "gyroscope_raw": {axis: stats[index].report() for index, axis in enumerate(AXES)},
        "bias_raw_counts": [stats[index].mean for index in range(3)],
    }


def integrate_rotation(
    path: Path,
    bias: Sequence[float],
    *,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    timing = TimingStats()
    corrected_stats = [RunningStats() for _ in AXES]
    peak_abs = [0.0, 0.0, 0.0]
    integral = [0.0, 0.0, 0.0]
    previous_corrected: list[float] | None = None
    previous_time: int | None = None
    skipped_nonpositive_intervals = 0

    for timestamp_us, valid, gyro in read_rows(path):
        if not valid:
            timing.invalid_samples += 1
            if not allow_invalid_samples:
                raise ValueError(
                    f"{path}: invalid IMU sample; use --allow-invalid-samples only for exploratory analysis"
                )
            continue
        if previous_time is not None and timestamp_us <= previous_time and not allow_timing_anomalies:
            kind = "duplicate" if timestamp_us == previous_time else "backward"
            raise ValueError(f"{path}: {kind} timestamp; use --allow-timing-anomalies only for exploratory analysis")

        corrected = vector_sub(gyro, bias)
        dt_us = timing.observe(timestamp_us)
        for index in range(3):
            corrected_stats[index].add(corrected[index])
            peak_abs[index] = max(peak_abs[index], abs(corrected[index]))

        if previous_corrected is not None and previous_time is not None:
            actual_dt_us = timestamp_us - previous_time
            if actual_dt_us > 0:
                dt_s = actual_dt_us / 1_000_000.0
                for index in range(3):
                    integral[index] += 0.5 * (previous_corrected[index] + corrected[index]) * dt_s
            else:
                skipped_nonpositive_intervals += 1
        previous_corrected = corrected
        previous_time = timestamp_us

    if timing.valid_samples < 2:
        raise ValueError(f"{path}: fewer than two valid rotation samples")
    return {
        "source": str(path),
        "timing": timing.report(),
        "bias_corrected_gyro_raw": {
            axis: corrected_stats[index].report() for index, axis in enumerate(AXES)
        },
        "peak_abs_bias_corrected_raw_counts": {
            axis: peak_abs[index] for index, axis in enumerate(AXES)
        },
        "integral_raw_count_s": integral,
        "integral_l2_raw_count_s": vector_norm(integral),
        "skipped_nonpositive_intervals": skipped_nonpositive_intervals,
    }


def infer_signed_axis_mapping(response: Sequence[Sequence[float]]) -> dict[str, Any]:
    # response rows are raw axes; columns are target rotation axes.
    best_perm: tuple[int, int, int] | None = None
    best_score = -1.0
    for permutation in itertools.permutations(range(3)):
        score = sum(abs(float(response[permutation[col]][col])) for col in range(3))
        if score > best_score:
            best_score = score
            best_perm = permutation
    assert best_perm is not None

    signed = [[0.0] * 3 for _ in range(3)]  # target rows <- raw columns
    target_from_raw: dict[str, Any] = {}
    for col, target_axis in enumerate(AXES):
        raw_row = best_perm[col]
        component = float(response[raw_row][col])
        sign = 1.0 if component >= 0.0 else -1.0
        signed[col][raw_row] = sign
        others = [float(response[row][col]) for row in range(3) if row != raw_row]
        dominant = abs(component)
        second = max((abs(value) for value in others), default=0.0)
        target_from_raw[target_axis] = {
            "raw_axis": AXES[raw_row],
            "sign": "+" if sign > 0.0 else "-",
            "expression": f"target_gyro_{target_axis} ~= {'+' if sign > 0.0 else '-'}raw_gyro_{AXES[raw_row]}",
            "assigned_response_raw_count_s": component,
            "column_l2_raw_count_s": vector_norm([float(response[row][col]) for row in range(3)]),
            "off_axis_l2_ratio": vector_norm(others) / dominant if dominant > 0.0 else None,
            "dominance_ratio_to_second": dominant / second if second > 0.0 else None,
        }
    return {
        "target_from_raw": target_from_raw,
        "signed_permutation_target_from_raw": signed,
        "signed_permutation_determinant": determinant3(signed),
        "assignment_score_raw_count_s": best_score,
        "handedness_note": (
            "A determinant of +1 preserves handedness and -1 flips handedness, assuming both raw and target "
            "bases have independently established handedness. The controlled-turn data alone does not define "
            "the vendor raw basis."
        ),
    }


def build_rotation_model(runs: dict[str, dict[str, Any]], expected_angle_rad: float | None) -> dict[str, Any]:
    pair_centers: dict[str, list[float]] = {}
    columns: list[list[float]] = []
    pair_symmetry: dict[str, Any] = {}
    for axis in AXES:
        plus = runs[f"plus_{axis}"]["integral_raw_count_s"]
        minus = runs[f"minus_{axis}"]["integral_raw_count_s"]
        center = vector_scale(vector_add(plus, minus), 0.5)
        response = vector_scale(vector_sub(plus, minus), 0.5)
        pair_centers[axis] = center
        columns.append(response)
        response_l2 = vector_norm(response)
        pair_symmetry[axis] = {
            "pair_center_raw_count_s": center,
            "pair_center_l2_raw_count_s": vector_norm(center),
            "response_l2_raw_count_s": response_l2,
            "pair_center_to_response_ratio": vector_norm(center) / response_l2 if response_l2 > 0.0 else None,
        }

    response_matrix = [[columns[col][row] for col in range(3)] for row in range(3)]
    result: dict[str, Any] = {
        "raw_integral_response_matrix": response_matrix,
        "matrix_semantics": (
            "rows=raw gyro X/Y/Z; columns=target Bividi +X/+Y/+Z commanded rotation; each column is "
            "0.5*(integral_plus - integral_minus) after stationary-bias subtraction"
        ),
        "pair_centers_raw_count_s": pair_centers,
        "pair_symmetry": pair_symmetry,
        "axis_mapping": infer_signed_axis_mapping(response_matrix),
        "expected_common_angle_rad": expected_angle_rad,
        "sensitivity_raw_counts_per_rad_s_matrix": None,
        "target_rad_s_per_raw_count_matrix": None,
        "sensitivity_condition_inf": None,
        "run_angle_fit": None,
    }

    if expected_angle_rad is not None:
        sensitivity = [
            [float(value) / expected_angle_rad for value in row]
            for row in response_matrix
        ]
        inverse = inverse3(sensitivity)
        result["sensitivity_raw_counts_per_rad_s_matrix"] = sensitivity
        result["target_rad_s_per_raw_count_matrix"] = inverse
        result["sensitivity_condition_inf"] = matrix_inf_norm(sensitivity) * matrix_inf_norm(inverse)
        fit: dict[str, Any] = {}
        for run in RUNS:
            target_angle = mat_vec(inverse, runs[run]["integral_raw_count_s"])
            expected = vector_scale(RUN_VECTOR[run], expected_angle_rad)
            residual = vector_sub(target_angle, expected)
            fit[run] = {
                "estimated_target_angle_rad": target_angle,
                "estimated_target_angle_deg": [value * 180.0 / math.pi for value in target_angle],
                "expected_target_angle_rad": expected,
                "expected_target_angle_deg": [value * 180.0 / math.pi for value in expected],
                "residual_rad": residual,
                "residual_l2_deg": vector_norm(residual) * 180.0 / math.pi,
            }
        result["run_angle_fit"] = fit
    return result


def compare_accelerometer_mapping(path: Path, gyro_mapping: dict[str, Any]) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read accelerometer six-position report {path}: {exc}") from exc
    if report.get("schema") != ACCEL_REPORT_SCHEMA:
        raise ValueError(
            f"accelerometer report schema must be {ACCEL_REPORT_SCHEMA!r}; got {report.get('schema')!r}"
        )
    try:
        accel_mapping = report["accelerometer_axis_mapping"]
        accel_matrix = accel_mapping["signed_permutation_target_from_raw"]
        accel_det = float(accel_mapping["signed_permutation_determinant"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("accelerometer report lacks signed axis-mapping evidence") from exc
    gyro_matrix = gyro_mapping["signed_permutation_target_from_raw"]
    matrix_match = all(
        abs(float(accel_matrix[row][col]) - float(gyro_matrix[row][col])) < 1e-12
        for row in range(3) for col in range(3)
    )
    return {
        "source": str(path),
        "accelerometer_signed_permutation_target_from_raw": accel_matrix,
        "gyroscope_signed_permutation_target_from_raw": gyro_matrix,
        "mapping_match": matrix_match,
        "accelerometer_signed_permutation_determinant": accel_det,
        "gyroscope_signed_permutation_determinant": gyro_mapping["signed_permutation_determinant"],
        "interpretation": (
            "Matching signed permutations are evidence that accelerometer and gyroscope packet axes use the same "
            "target-frame convention. A mismatch must be investigated; neither mapping is silently preferred."
        ),
    }


def analyze(
    stationary_path: Path,
    run_paths: dict[str, Path],
    *,
    expected_angle_deg: float | None,
    accelerometer_sixpos_json: Path | None,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    baseline = stationary_baseline(
        stationary_path,
        allow_invalid_samples=allow_invalid_samples,
        allow_timing_anomalies=allow_timing_anomalies,
    )
    bias = baseline["bias_raw_counts"]
    runs = {
        run: integrate_rotation(
            run_paths[run],
            bias,
            allow_invalid_samples=allow_invalid_samples,
            allow_timing_anomalies=allow_timing_anomalies,
        )
        for run in RUNS
    }
    expected_angle_rad = None if expected_angle_deg is None else expected_angle_deg * math.pi / 180.0
    model = build_rotation_model(runs, expected_angle_rad)
    comparison = None
    if accelerometer_sixpos_json is not None:
        comparison = compare_accelerometer_mapping(accelerometer_sixpos_json, model["axis_mapping"])
    return {
        "schema": REPORT_SCHEMA,
        "rotation_convention": {
            "meaning": (
                "plus_x/plus_y/plus_z are positive right-hand-rule rotations about the target Bividi +X/+Y/+Z "
                "axis respectively; minus_* are equal-magnitude opposite rotations."
            ),
            "common_expected_angle_deg": expected_angle_deg,
            "angle_note": (
                "When no expected angle is supplied, only axis/sign/coupling/symmetry evidence is reported; "
                "absolute gyro sensitivity is not inferred."
            ),
        },
        "stationary_baseline": baseline,
        "runs": runs,
        "rotation_model": model,
        "accelerometer_gyroscope_mapping_comparison": comparison,
        "status": "candidate_evidence_only_not_promoted_to_calibration_artifact",
        "guardrails": [
            "The stationary baseline and all six rotation traces must use the same IMU configuration, firmware, and range.",
            "Positive rotation is the target-frame right-hand rule; incorrect physical labelling flips the inferred sign.",
            "No DECXIN vendor-demo gyroscope full-scale or nominal scale is reused as truth.",
            "Absolute gyro sensitivity is produced only when --expected-angle-deg is explicitly supplied.",
            "The common-angle model assumes the six commanded rotations have equal magnitude; turntable/fixture error remains experiment error.",
            "Invalid samples or timestamp anomalies can bias numerical integration; permissive flags are exploratory only.",
            "No pass/fail threshold for coupling, pair symmetry, condition number, bias stability, or angle residual is invented by default.",
            "Accelerometer and gyroscope signed mappings are compared when a six-position report is supplied; disagreement is not auto-corrected.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    model = report["rotation_model"]
    mapping = model["axis_mapping"]
    lines = [
        "# Controlled Gyroscope Rotation / Axis Laboratory",
        "",
        f"Status: `{report['status']}`",
        f"Expected common angle: {fmt(report['rotation_convention']['common_expected_angle_deg'])} deg",
        "",
        "## Stationary gyro bias",
        "",
        "| Raw axis | Mean bias | Population stddev |",
        "| --- | ---: | ---: |",
    ]
    for axis in AXES:
        item = report["stationary_baseline"]["gyroscope_raw"][axis]
        lines.append(f"| {axis} | {fmt(item['mean'])} | {fmt(item['stddev_population'])} |")
    lines += [
        "",
        "## Inferred gyroscope axis mapping",
        "",
        "| Target axis | Raw axis | Sign | Assigned response | Column L2 | Cross-axis L2 ratio | Dominance ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for axis in AXES:
        item = mapping["target_from_raw"][axis]
        lines.append(
            f"| {axis} | {item['raw_axis']} | {item['sign']} | {fmt(item['assigned_response_raw_count_s'])} | "
            f"{fmt(item['column_l2_raw_count_s'])} | {fmt(item['off_axis_l2_ratio'])} | "
            f"{fmt(item['dominance_ratio_to_second'])} |"
        )
    lines += [
        "",
        f"- Signed-permutation determinant: {fmt(mapping['signed_permutation_determinant'])}",
        "",
        mapping["handedness_note"],
        "",
        "## +/- pair symmetry",
        "",
        "| Target axis | pair-center L2 (raw count*s) | response L2 | center/response |",
        "| --- | ---: | ---: | ---: |",
    ]
    for axis in AXES:
        item = model["pair_symmetry"][axis]
        lines.append(
            f"| {axis} | {fmt(item['pair_center_l2_raw_count_s'])} | "
            f"{fmt(item['response_l2_raw_count_s'])} | {fmt(item['pair_center_to_response_ratio'])} |"
        )

    sensitivity = model["sensitivity_raw_counts_per_rad_s_matrix"]
    if sensitivity is not None:
        lines += [
            "",
            "## Candidate gyro sensitivity",
            "",
            "`raw_gyro_counts ~= bias + S * target_angular_rate_rad_s`",
            "",
            "S (raw counts per rad/s):",
            "",
            "```text",
        ]
        for row in sensitivity:
            lines.append("[ " + ", ".join(fmt(value) for value in row) + " ]")
        lines += ["```", "", "Inverse S (target rad/s per raw count):", "", "```text"]
        for row in model["target_rad_s_per_raw_count_matrix"]:
            lines.append("[ " + ", ".join(fmt(value) for value in row) + " ]")
        lines += [
            "```",
            "",
            f"Sensitivity condition number (inf): {fmt(model['sensitivity_condition_inf'])}",
            "",
            "### Integrated-angle fit",
            "",
            "| Run | X deg | Y deg | Z deg | residual L2 deg |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for run in RUNS:
            fit = model["run_angle_fit"][run]
            angle = fit["estimated_target_angle_deg"]
            lines.append(
                f"| {run} | {fmt(angle[0])} | {fmt(angle[1])} | {fmt(angle[2])} | {fmt(fit['residual_l2_deg'])} |"
            )

    comparison = report["accelerometer_gyroscope_mapping_comparison"]
    if comparison is not None:
        lines += [
            "",
            "## Accelerometer ↔ gyroscope mapping comparison",
            "",
            f"- Six-position report: `{comparison['source']}`",
            f"- Signed mapping match: `{comparison['mapping_match']}`",
            f"- Accelerometer determinant: {fmt(comparison['accelerometer_signed_permutation_determinant'])}",
            f"- Gyroscope determinant: {fmt(comparison['gyroscope_signed_permutation_determinant'])}",
            "",
            comparison["interpretation"],
        ]
    lines += ["", "## Guardrails", ""]
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines)


def write_run_csv(report: dict[str, Any], path: Path) -> None:
    fields = [
        "run", "source", "samples", "duration_s", "rate_hz",
        "integral_raw_x_count_s", "integral_raw_y_count_s", "integral_raw_z_count_s",
        "integral_l2_raw_count_s", "skipped_nonpositive_intervals",
        "estimated_target_x_deg", "estimated_target_y_deg", "estimated_target_z_deg", "angle_residual_l2_deg",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        fit = report["rotation_model"]["run_angle_fit"]
        for run in RUNS:
            item = report["runs"][run]
            integral = item["integral_raw_count_s"]
            row: dict[str, Any] = {
                "run": run,
                "source": item["source"],
                "samples": item["timing"]["valid_samples"],
                "duration_s": item["timing"]["duration_s"],
                "rate_hz": item["timing"]["effective_rate_hz"],
                "integral_raw_x_count_s": integral[0],
                "integral_raw_y_count_s": integral[1],
                "integral_raw_z_count_s": integral[2],
                "integral_l2_raw_count_s": item["integral_l2_raw_count_s"],
                "skipped_nonpositive_intervals": item["skipped_nonpositive_intervals"],
            }
            if fit is not None:
                angles = fit[run]["estimated_target_angle_deg"]
                row.update({
                    "estimated_target_x_deg": angles[0],
                    "estimated_target_y_deg": angles[1],
                    "estimated_target_z_deg": angles[2],
                    "angle_residual_l2_deg": fit[run]["residual_l2_deg"],
                })
            writer.writerow(row)


def write_fixture(
    path: Path,
    *,
    bias: Sequence[float],
    sensitivity: Sequence[Sequence[float]],
    target_axis: int | None,
    sign: float,
    angle_rad: float,
) -> None:
    header = [
        "frame_index", "frame_sequence", "host_receive_monotonic_ns",
        "exposure_start_raw_us", "exposure_end_raw_us",
        "exposure_start_extended_us", "exposure_end_extended_us",
        "sample_index", "sample_valid", "imu_raw_time_us", "imu_extended_time_us",
        "accel_raw_x", "accel_raw_y", "accel_raw_z", "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
    ]
    count = 202
    dt_s = 0.005
    omega = 0.0 if target_axis is None else angle_rad / ((count - 2) * dt_s)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for index in range(count):
            t = 1_000_000 + int(index * dt_s * 1_000_000)
            target_rate = [0.0, 0.0, 0.0]
            if target_axis is not None and 0 < index < count - 1:
                target_rate[target_axis] = sign * omega
            raw_dynamic = mat_vec(sensitivity, target_rate)
            gyro = vector_add(bias, raw_dynamic)
            writer.writerow([
                index // 4, 100 + index // 4, 0, t, t + 1000, t, t + 1000,
                index % 4, "true", t & 0xFFFFFFFF, t,
                0.0, 0.0, 8192.0, *gyro,
            ])


def self_test() -> int:
    bias = [9.0, -13.0, 4.0]
    # target X ~= +raw Y, target Y ~= -raw Z, target Z ~= -raw X.
    sensitivity = [
        [12.0, 18.0, -1000.0],
        [1024.0, -15.0, 10.0],
        [-20.0, -980.0, 14.0],
    ]
    angle_deg = 90.0
    angle_rad = angle_deg * math.pi / 180.0
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        stationary = root / "stationary.csv"
        write_fixture(
            stationary, bias=bias, sensitivity=sensitivity,
            target_axis=None, sign=0.0, angle_rad=angle_rad,
        )
        run_paths: dict[str, Path] = {}
        for run in RUNS:
            axis = AXES.index(run[-1])
            sign = 1.0 if run.startswith("plus") else -1.0
            path = root / f"{run}.csv"
            write_fixture(
                path, bias=bias, sensitivity=sensitivity,
                target_axis=axis, sign=sign, angle_rad=angle_rad,
            )
            run_paths[run] = path

        accel_report = root / "sixpos.json"
        accel_report.write_text(json.dumps({
            "schema": ACCEL_REPORT_SCHEMA,
            "accelerometer_axis_mapping": {
                "signed_permutation_target_from_raw": [
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, -1.0],
                    [-1.0, 0.0, 0.0],
                ],
                "signed_permutation_determinant": 1.0,
            },
        }), encoding="utf-8")

        report = analyze(
            stationary,
            run_paths,
            expected_angle_deg=angle_deg,
            accelerometer_sixpos_json=accel_report,
            allow_invalid_samples=False,
            allow_timing_anomalies=False,
        )
        mapping = report["rotation_model"]["axis_mapping"]["target_from_raw"]
        assert mapping["x"]["raw_axis"] == "y" and mapping["x"]["sign"] == "+"
        assert mapping["y"]["raw_axis"] == "z" and mapping["y"]["sign"] == "-"
        assert mapping["z"]["raw_axis"] == "x" and mapping["z"]["sign"] == "-"
        assert abs(report["rotation_model"]["axis_mapping"]["signed_permutation_determinant"] - 1.0) < 1e-12
        assert report["accelerometer_gyroscope_mapping_comparison"]["mapping_match"] is True
        recovered = report["rotation_model"]["sensitivity_raw_counts_per_rad_s_matrix"]
        for row_actual, row_expected in zip(recovered, sensitivity):
            for actual, expected in zip(row_actual, row_expected):
                assert abs(actual - expected) < 1e-8
        for run in RUNS:
            assert report["rotation_model"]["run_angle_fit"][run]["residual_l2_deg"] < 1e-8
        assert "Controlled Gyroscope Rotation" in render_markdown(report)
        csv_path = root / "gyro.csv"
        write_run_csv(report, csv_path)
        assert csv_path.exists() and csv_path.stat().st_size > 0

    print("controlled gyro rotation laboratory self-test: PASS")
    return 0


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze stationary baseline plus +/-X +/-Y +/-Z controlled gyroscope rotation traces"
    )
    parser.add_argument("--stationary", type=Path)
    for run in RUNS:
        parser.add_argument(f"--{run.replace('_', '-')}", type=Path, dest=run)
    parser.add_argument("--expected-angle-deg", type=positive_float,
                        help="common commanded angle magnitude for all six turns; omit for axis/sign-only analysis")
    parser.add_argument("--accelerometer-sixpos-json", type=Path,
                        help="optional analyze_imu_six_position JSON for accel-vs-gyro signed mapping comparison")
    parser.add_argument("--allow-invalid-samples", action="store_true",
                        help="exploratory only: skip invalid samples instead of rejecting a trace")
    parser.add_argument("--allow-timing-anomalies", action="store_true",
                        help="exploratory only: permit duplicate/backward timestamps; nonpositive intervals are not integrated")
    parser.add_argument("--output-prefix", type=Path,
                        help="write PREFIX.gyro.csv, PREFIX.gyro.json, and PREFIX.gyro.md")
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.stationary is None:
        print("--stationary is required", file=sys.stderr)
        return 3
    run_paths = {run: getattr(args, run) for run in RUNS}
    missing = [run for run, path in run_paths.items() if path is None]
    if missing:
        print("missing required rotation trace(s): " + ", ".join(missing), file=sys.stderr)
        return 3
    try:
        report = analyze(
            args.stationary,
            run_paths,
            expected_angle_deg=args.expected_angle_deg,
            accelerometer_sixpos_json=args.accelerometer_sixpos_json,
            allow_invalid_samples=args.allow_invalid_samples,
            allow_timing_anomalies=args.allow_timing_anomalies,
        )
    except ValueError as exc:
        print(f"analyze_imu_gyro_rotation: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report)
    print(markdown)
    csv_out = args.csv_out
    json_out = args.json_out
    markdown_out = args.markdown_out
    if args.output_prefix is not None:
        csv_out = csv_out or Path(str(args.output_prefix) + ".gyro.csv")
        json_out = json_out or Path(str(args.output_prefix) + ".gyro.json")
        markdown_out = markdown_out or Path(str(args.output_prefix) + ".gyro.md")
    if csv_out is not None:
        write_run_csv(report, csv_out)
    if json_out is not None:
        json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_out is not None:
        markdown_out.write_text(markdown + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
