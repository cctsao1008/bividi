#!/usr/bin/env python3
"""Dependency-free Allan-deviation laboratory for Bividi Nori IMU traces.

The default estimator is a streaming, dyadic, non-overlapping Allan deviation.
It is deliberately designed for very long stationary recordings without loading
millions of samples into RAM.  It keeps the calibration boundary conservative:
raw-count Allan curves are always available, while Kalibr-unit candidates are
only produced when the operator supplies explicit raw->SI scale provenance and
explicit fit windows.

No sensor full-scale, noise density, random walk, or fit region is inferred from
vendor demo code or datasheet defaults.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

REPORT_SCHEMA = "bividi.calibration.imu_allan_analysis.v1"
GRAVITY_M_S2 = 9.80665
AXIS_NAMES = (
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
)
REQUIRED_COLUMNS = {
    "sample_valid",
    "imu_extended_time_us",
    "accel_raw_x", "accel_raw_y", "accel_raw_z",
    "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
}


@dataclass
class AllanLevel:
    block_size: int
    block_count: int = 0
    pair_count: int = 0
    last_block: list[float] | None = None
    pending_for_parent: list[float] | None = None
    sum_sq_diff: list[float] | None = None

    def __post_init__(self) -> None:
        if self.sum_sq_diff is None:
            self.sum_sq_diff = [0.0] * len(AXIS_NAMES)


class StreamingDyadicAllan:
    """Streaming non-overlapping Allan variance for power-of-two cluster sizes.

    Each completed cluster average contributes a difference against the prior
    adjacent cluster at the same level. Pairs of cluster averages are averaged
    recursively into the next dyadic level. This yields O(log N) storage and
    amortized O(1) level propagation per input sample.
    """

    def __init__(self) -> None:
        self.levels: list[AllanLevel] = [AllanLevel(block_size=1)]
        self.sample_count = 0

    def add(self, values: Sequence[float]) -> None:
        if len(values) != len(AXIS_NAMES):
            raise ValueError(f"expected {len(AXIS_NAMES)} axes, got {len(values)}")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("non-finite IMU sample")
        self.sample_count += 1
        self._push_block(0, vector)

    def _push_block(self, level_index: int, block: list[float]) -> None:
        if level_index == len(self.levels):
            self.levels.append(AllanLevel(block_size=1 << level_index))
        level = self.levels[level_index]
        level.block_count += 1

        if level.last_block is not None:
            for axis in range(len(AXIS_NAMES)):
                delta = block[axis] - level.last_block[axis]
                level.sum_sq_diff[axis] += delta * delta
            level.pair_count += 1
        level.last_block = block

        if level.pending_for_parent is None:
            level.pending_for_parent = block
            return

        parent = [
            0.5 * (level.pending_for_parent[axis] + block[axis])
            for axis in range(len(AXIS_NAMES))
        ]
        level.pending_for_parent = None
        self._push_block(level_index + 1, parent)

    def curve(self, sample_period_s: float, min_pairs: int) -> list[dict[str, Any]]:
        if not math.isfinite(sample_period_s) or sample_period_s <= 0.0:
            raise ValueError("sample period must be finite and positive")
        result: list[dict[str, Any]] = []
        for level in self.levels:
            if level.pair_count < min_pairs:
                continue
            adev: dict[str, float] = {}
            for axis, name in enumerate(AXIS_NAMES):
                variance = 0.5 * level.sum_sq_diff[axis] / level.pair_count
                adev[name] = math.sqrt(max(0.0, variance))
            result.append({
                "block_size": level.block_size,
                "tau_s": level.block_size * sample_period_s,
                "cluster_count": level.block_count,
                "pair_count": level.pair_count,
                "raw_adev": adev,
            })
        return result


@dataclass
class TimingSummary:
    sample_count: int = 0
    invalid_sample_count: int = 0
    first_time_us: int | None = None
    last_time_us: int | None = None
    previous_time_us: int | None = None
    interval_count: int = 0
    interval_sum_us: float = 0.0
    interval_min_us: int | None = None
    interval_max_us: int | None = None
    duplicate_intervals: int = 0
    backward_intervals: int = 0

    def add_valid_time(self, timestamp_us: int) -> None:
        if self.first_time_us is None:
            self.first_time_us = timestamp_us
        if self.previous_time_us is not None:
            interval = timestamp_us - self.previous_time_us
            self.interval_count += 1
            self.interval_sum_us += interval
            self.interval_min_us = interval if self.interval_min_us is None else min(self.interval_min_us, interval)
            self.interval_max_us = interval if self.interval_max_us is None else max(self.interval_max_us, interval)
            if interval == 0:
                self.duplicate_intervals += 1
            elif interval < 0:
                self.backward_intervals += 1
        self.previous_time_us = timestamp_us
        self.last_time_us = timestamp_us
        self.sample_count += 1

    def final(self) -> dict[str, Any]:
        duration_s: float | None = None
        effective_rate_hz: float | None = None
        sample_period_s: float | None = None
        if (
            self.sample_count > 1
            and self.first_time_us is not None
            and self.last_time_us is not None
            and self.last_time_us > self.first_time_us
        ):
            duration_s = (self.last_time_us - self.first_time_us) / 1_000_000.0
            effective_rate_hz = (self.sample_count - 1) / duration_s
            sample_period_s = 1.0 / effective_rate_hz
        interval_mean_us = None
        if self.interval_count:
            interval_mean_us = self.interval_sum_us / self.interval_count
        return {
            "sample_count": self.sample_count,
            "invalid_sample_count": self.invalid_sample_count,
            "first_time_us": self.first_time_us,
            "last_time_us": self.last_time_us,
            "duration_s": duration_s,
            "effective_rate_hz": effective_rate_hz,
            "sample_period_s": sample_period_s,
            "interval_us": {
                "count": self.interval_count,
                "mean": interval_mean_us,
                "minimum": self.interval_min_us,
                "maximum": self.interval_max_us,
                "duplicates": self.duplicate_intervals,
                "backwards": self.backward_intervals,
            },
        }


@dataclass
class LogFit:
    point_count: int
    tau_min_s: float
    tau_max_s: float
    expected_slope: float
    free_slope: float
    free_intercept_ln: float
    free_r_squared: float | None
    fixed_intercept_ln: float
    reference_tau_s: float
    reference_value: float


def parse_window(text: str) -> tuple[float, float]:
    try:
        left, right = text.split(":", 1)
        minimum = float(left)
        maximum = float(right)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("window must be MIN:MAX seconds") from exc
    if not (math.isfinite(minimum) and math.isfinite(maximum) and 0.0 < minimum < maximum):
        raise argparse.ArgumentTypeError("window bounds must satisfy 0 < MIN < MAX")
    return minimum, maximum


def log_fit(
    points: Sequence[tuple[float, float]],
    *,
    tau_window: tuple[float, float],
    expected_slope: float,
    reference_tau_s: float,
) -> LogFit:
    selected = [
        (tau, value)
        for tau, value in points
        if tau_window[0] <= tau <= tau_window[1]
        and tau > 0.0
        and value > 0.0
        and math.isfinite(tau)
        and math.isfinite(value)
    ]
    if len(selected) < 2:
        raise ValueError(
            f"fit window {tau_window[0]:g}:{tau_window[1]:g}s contains fewer than two positive Allan points"
        )

    xs = [math.log(tau) for tau, _ in selected]
    ys = [math.log(value) for _, value in selected]
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    ss_xx = sum((x - x_mean) ** 2 for x in xs)
    if ss_xx <= 0.0:
        raise ValueError("fit window has no logarithmic tau spread")
    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    free_slope = ss_xy / ss_xx
    free_intercept = y_mean - free_slope * x_mean
    predicted = [free_intercept + free_slope * x for x in xs]
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, predicted))
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    r_squared = None if ss_tot <= 0.0 else 1.0 - ss_res / ss_tot

    fixed_intercept = statistics.fmean(
        y - expected_slope * x for x, y in zip(xs, ys)
    )
    reference_value = math.exp(
        fixed_intercept + expected_slope * math.log(reference_tau_s)
    )
    return LogFit(
        point_count=len(selected),
        tau_min_s=min(tau for tau, _ in selected),
        tau_max_s=max(tau for tau, _ in selected),
        expected_slope=expected_slope,
        free_slope=free_slope,
        free_intercept_ln=free_intercept,
        free_r_squared=r_squared,
        fixed_intercept_ln=fixed_intercept,
        reference_tau_s=reference_tau_s,
        reference_value=reference_value,
    )


def scale_factors(
    accel_g_per_count: float | None,
    gyro_dps_per_count: float | None,
    scale_source: str | None,
) -> tuple[dict[str, float], dict[str, Any] | None]:
    if (accel_g_per_count is not None or gyro_dps_per_count is not None) and not scale_source:
        raise ValueError("--scale-source is required whenever an SI conversion scale is supplied")

    factors: dict[str, float] = {}
    provenance: dict[str, Any] | None = None
    if accel_g_per_count is not None or gyro_dps_per_count is not None:
        provenance = {"source": scale_source}
    if accel_g_per_count is not None:
        factor = accel_g_per_count * GRAVITY_M_S2
        factors.update({"accel_x": factor, "accel_y": factor, "accel_z": factor})
        assert provenance is not None
        provenance["accelerometer_g_per_count"] = accel_g_per_count
        provenance["accelerometer_m_s2_per_count"] = factor
    if gyro_dps_per_count is not None:
        factor = gyro_dps_per_count * math.pi / 180.0
        factors.update({"gyro_x": factor, "gyro_y": factor, "gyro_z": factor})
        assert provenance is not None
        provenance["gyroscope_dps_per_count"] = gyro_dps_per_count
        provenance["gyroscope_rad_s_per_count"] = factor
    return factors, provenance


def parse_sample(row: dict[str, str], line: int) -> tuple[int, list[float], bool]:
    valid_text = row["sample_valid"].strip().lower()
    if valid_text not in {"true", "false"}:
        raise ValueError(f"line {line}: invalid sample_valid {row['sample_valid']!r}")
    try:
        timestamp = int(row["imu_extended_time_us"], 10)
    except ValueError as exc:
        raise ValueError(f"line {line}: invalid imu_extended_time_us") from exc
    if valid_text == "false":
        return timestamp, [], False
    try:
        values = [
            float(row["accel_raw_x"]), float(row["accel_raw_y"]), float(row["accel_raw_z"]),
            float(row["gyro_raw_x"]), float(row["gyro_raw_y"]), float(row["gyro_raw_z"]),
        ]
    except ValueError as exc:
        raise ValueError(f"line {line}: invalid raw IMU value") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"line {line}: non-finite raw IMU value")
    return timestamp, values, True


def read_trace(
    path: Path,
    *,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> tuple[StreamingDyadicAllan, TimingSummary]:
    analyzer = StreamingDyadicAllan()
    timing = TimingSummary()
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("trace CSV has no header")
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise ValueError(f"trace CSV missing required columns: {', '.join(missing)}")
        for line, row in enumerate(reader, start=2):
            timestamp, values, valid = parse_sample(row, line)
            if not valid:
                timing.invalid_sample_count += 1
                if not allow_invalid_samples:
                    raise ValueError(
                        f"line {line}: invalid IMU sample; Allan analysis requires a contiguous valid series "
                        "unless --allow-invalid-samples is explicit"
                    )
                continue
            if timing.previous_time_us is not None and timestamp <= timing.previous_time_us:
                if not allow_timing_anomalies:
                    kind = "duplicate" if timestamp == timing.previous_time_us else "backward"
                    raise ValueError(
                        f"line {line}: {kind} IMU timestamp; use --allow-timing-anomalies only for exploratory analysis"
                    )
            timing.add_valid_time(timestamp)
            analyzer.add(values)
    return analyzer, timing


def add_scaled_curve(curve: list[dict[str, Any]], factors: dict[str, float]) -> None:
    for point in curve:
        scaled: dict[str, float] = {}
        for axis, factor in factors.items():
            scaled[axis] = point["raw_adev"][axis] * abs(factor)
        point["si_adev"] = scaled if scaled else None


def local_slopes(curve: list[dict[str, Any]], field: str, axis: str) -> list[dict[str, float]]:
    result: list[dict[str, float]] = []
    prior: tuple[float, float] | None = None
    for point in curve:
        values = point.get(field)
        if not isinstance(values, dict) or axis not in values:
            continue
        tau = float(point["tau_s"])
        value = float(values[axis])
        if tau <= 0.0 or value <= 0.0:
            prior = (tau, value)
            continue
        if prior is not None and prior[0] > 0.0 and prior[1] > 0.0:
            slope = math.log(value / prior[1]) / math.log(tau / prior[0])
            result.append({"tau_s": tau, "slope": slope})
        prior = (tau, value)
    return result


def choose_scalar(values: Sequence[float], policy: str) -> float:
    if not values:
        raise ValueError("cannot aggregate an empty candidate set")
    if policy == "max":
        return max(values)
    if policy == "mean":
        return statistics.fmean(values)
    if policy == "median":
        return statistics.median(values)
    raise ValueError(f"unsupported scalar policy: {policy}")


def fit_sensor(
    curve: list[dict[str, Any]],
    *,
    axes: Sequence[str],
    field: str,
    window: tuple[float, float] | None,
    expected_slope: float,
    reference_tau_s: float,
) -> dict[str, Any] | None:
    if window is None:
        return None
    axis_fits: dict[str, Any] = {}
    for axis in axes:
        points = [
            (float(point["tau_s"]), float(point[field][axis]))
            for point in curve
            if isinstance(point.get(field), dict) and axis in point[field]
        ]
        axis_fits[axis] = asdict(log_fit(
            points,
            tau_window=window,
            expected_slope=expected_slope,
            reference_tau_s=reference_tau_s,
        ))
    return {
        "requested_window_s": [window[0], window[1]],
        "expected_slope": expected_slope,
        "reference_tau_s": reference_tau_s,
        "axes": axis_fits,
    }


def analyze(
    path: Path,
    *,
    min_pairs: int,
    accel_g_per_count: float | None,
    gyro_dps_per_count: float | None,
    scale_source: str | None,
    white_window: tuple[float, float] | None,
    random_walk_window: tuple[float, float] | None,
    kalibr_axis_policy: str | None,
    sample_rate_hz: float | None,
    allow_invalid_samples: bool,
    allow_timing_anomalies: bool,
) -> dict[str, Any]:
    factors, scale_info = scale_factors(accel_g_per_count, gyro_dps_per_count, scale_source)
    allan, timing_state = read_trace(
        path,
        allow_invalid_samples=allow_invalid_samples,
        allow_timing_anomalies=allow_timing_anomalies,
    )
    timing = timing_state.final()
    if timing["sample_count"] < 4:
        raise ValueError("trace contains fewer than four valid IMU samples")

    measured_period = timing["sample_period_s"]
    if sample_rate_hz is not None:
        period_s = 1.0 / sample_rate_hz
        period_source = "explicit --sample-rate-hz"
    else:
        if measured_period is None:
            raise ValueError("cannot derive sample period from timestamps")
        period_s = float(measured_period)
        period_source = "measured first-to-last effective rate"

    curve = allan.curve(period_s, min_pairs)
    if len(curve) < 2:
        raise ValueError(
            "insufficient Allan levels after --min-pairs filtering; use a longer trace or lower --min-pairs explicitly"
        )
    add_scaled_curve(curve, factors)

    for point in curve:
        point["local_slope_raw"] = {
            axis: next(
                (entry["slope"] for entry in local_slopes(curve, "raw_adev", axis)
                 if entry["tau_s"] == point["tau_s"]),
                None,
            )
            for axis in AXIS_NAMES
        }
        if point["si_adev"] is not None:
            point["local_slope_si"] = dict(point["local_slope_raw"])
        else:
            point["local_slope_si"] = None

    raw_fits = {
        "white_noise": {
            "accelerometer": fit_sensor(
                curve, axes=("accel_x", "accel_y", "accel_z"), field="raw_adev",
                window=white_window, expected_slope=-0.5, reference_tau_s=1.0,
            ),
            "gyroscope": fit_sensor(
                curve, axes=("gyro_x", "gyro_y", "gyro_z"), field="raw_adev",
                window=white_window, expected_slope=-0.5, reference_tau_s=1.0,
            ),
        },
        "random_walk": {
            "accelerometer": fit_sensor(
                curve, axes=("accel_x", "accel_y", "accel_z"), field="raw_adev",
                window=random_walk_window, expected_slope=0.5, reference_tau_s=3.0,
            ),
            "gyroscope": fit_sensor(
                curve, axes=("gyro_x", "gyro_y", "gyro_z"), field="raw_adev",
                window=random_walk_window, expected_slope=0.5, reference_tau_s=3.0,
            ),
        },
    }

    si_fits: dict[str, Any] | None = None
    if factors:
        si_fits = {
            "white_noise": {
                "accelerometer": fit_sensor(
                    curve, axes=("accel_x", "accel_y", "accel_z"), field="si_adev",
                    window=white_window, expected_slope=-0.5, reference_tau_s=1.0,
                ) if accel_g_per_count is not None else None,
                "gyroscope": fit_sensor(
                    curve, axes=("gyro_x", "gyro_y", "gyro_z"), field="si_adev",
                    window=white_window, expected_slope=-0.5, reference_tau_s=1.0,
                ) if gyro_dps_per_count is not None else None,
            },
            "random_walk": {
                "accelerometer": fit_sensor(
                    curve, axes=("accel_x", "accel_y", "accel_z"), field="si_adev",
                    window=random_walk_window, expected_slope=0.5, reference_tau_s=3.0,
                ) if accel_g_per_count is not None else None,
                "gyroscope": fit_sensor(
                    curve, axes=("gyro_x", "gyro_y", "gyro_z"), field="si_adev",
                    window=random_walk_window, expected_slope=0.5, reference_tau_s=3.0,
                ) if gyro_dps_per_count is not None else None,
            },
        }

    kalibr_candidate: dict[str, Any] | None = None
    if kalibr_axis_policy is not None:
        if si_fits is None:
            raise ValueError("--kalibr-axis-policy requires explicit SI conversion scales")
        if white_window is None or random_walk_window is None:
            raise ValueError("--kalibr-axis-policy requires both --white-window and --random-walk-window")
        required = [
            si_fits["white_noise"]["accelerometer"],
            si_fits["white_noise"]["gyroscope"],
            si_fits["random_walk"]["accelerometer"],
            si_fits["random_walk"]["gyroscope"],
        ]
        if any(item is None for item in required):
            raise ValueError("--kalibr-axis-policy requires both accelerometer and gyroscope SI scales")

        def refs(section: str, sensor: str) -> list[float]:
            fit = si_fits[section][sensor]
            return [float(fit["axes"][axis]["reference_value"]) for axis in fit["axes"]]

        kalibr_candidate = {
            "status": "candidate_only_not_promoted_to_calibration_artifact",
            "axis_policy": kalibr_axis_policy,
            "accelerometer_noise_density_m_s2_sqrt_hz": choose_scalar(
                refs("white_noise", "accelerometer"), kalibr_axis_policy
            ),
            "gyroscope_noise_density_rad_s_sqrt_hz": choose_scalar(
                refs("white_noise", "gyroscope"), kalibr_axis_policy
            ),
            "accelerometer_random_walk_m_s3_sqrt_hz": choose_scalar(
                refs("random_walk", "accelerometer"), kalibr_axis_policy
            ),
            "gyroscope_random_walk_rad_s2_sqrt_hz": choose_scalar(
                refs("random_walk", "gyroscope"), kalibr_axis_policy
            ),
            "update_rate_hz": 1.0 / period_s,
            "interpretation": (
                "White-noise candidates are fixed -1/2-slope fits evaluated at tau=1 s. "
                "Random-walk candidates are fixed +1/2-slope fits evaluated at tau=3 s. "
                "The axis reduction policy was explicitly selected by the operator."
            ),
        }

    return {
        "schema": REPORT_SCHEMA,
        "source_trace": str(path),
        "method": {
            "name": "streaming_dyadic_nonoverlapping_allan_deviation",
            "cluster_sizes": "powers_of_two",
            "min_adjacent_cluster_pairs": min_pairs,
            "memory_model": "O(log N) estimator state; source CSV is streamed",
            "note": (
                "Non-overlapping Allan deviation has lower statistical efficiency than overlapping Allan deviation, "
                "but preserves the same canonical log-log process slopes and is practical for multi-hour dependency-free runs."
            ),
        },
        "stationary_assumption": (
            "The operator declares this recording stationary and approximately constant-temperature. "
            "The tool does not independently prove either condition."
        ),
        "timing": timing,
        "sample_period": {
            "seconds": period_s,
            "rate_hz": 1.0 / period_s,
            "source": period_source,
        },
        "scale_conversion": scale_info,
        "curve": curve,
        "fits_raw_counts": raw_fits,
        "fits_si": si_fits,
        "kalibr_candidate": kalibr_candidate,
        "guardrails": [
            "No vendor-demo full-scale is inferred.",
            "No Allan fit window is selected automatically.",
            "No per-axis Kalibr scalar is chosen unless --kalibr-axis-policy is explicit.",
            "A candidate noise model is evidence, not a promoted Bividi calibration artifact.",
            "Timestamp gaps and invalid samples can bias Allan results; permissive flags are exploratory only.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# IMU Allan Deviation / Noise Laboratory",
        "",
        f"- Source: `{report['source_trace']}`",
        f"- Method: `{report['method']['name']}`",
        f"- Valid samples: {report['timing']['sample_count']}",
        f"- Invalid samples skipped: {report['timing']['invalid_sample_count']}",
        f"- Duration: {fmt(report['timing']['duration_s'])} s",
        f"- Analysis rate: {fmt(report['sample_period']['rate_hz'])} Hz ({report['sample_period']['source']})",
        "",
        "## Allan curve",
        "",
        "| tau (s) | block | pairs | accel x | accel y | accel z | gyro x | gyro y | gyro z |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for point in report["curve"]:
        values = point["si_adev"] or point["raw_adev"]
        lines.append(
            "| {tau} | {block} | {pairs} | {ax} | {ay} | {az} | {gx} | {gy} | {gz} |".format(
                tau=fmt(point["tau_s"]), block=point["block_size"], pairs=point["pair_count"],
                ax=fmt(values["accel_x"]), ay=fmt(values["accel_y"]), az=fmt(values["accel_z"]),
                gx=fmt(values["gyro_x"]), gy=fmt(values["gyro_y"]), gz=fmt(values["gyro_z"]),
            )
        )
    if report["scale_conversion"] is None:
        lines += [
            "",
            "Values above are raw-count Allan deviation because no explicit SI scale was supplied.",
        ]
    else:
        lines += [
            "",
            f"Values above are SI Allan deviation using explicit scale provenance: `{report['scale_conversion']['source']}`.",
        ]

    lines += ["", "## Explicit fit evidence", ""]
    for domain, fits in (("raw", report["fits_raw_counts"]), ("SI", report["fits_si"])):
        if fits is None:
            continue
        for section in ("white_noise", "random_walk"):
            for sensor in ("accelerometer", "gyroscope"):
                fit = fits[section][sensor]
                if fit is None:
                    continue
                lines.append(f"### {domain} {sensor} — {section}")
                lines.append("")
                lines.append("| Axis | points | free slope | R² | fixed-slope reference tau | reference value |")
                lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
                for axis, axis_fit in fit["axes"].items():
                    lines.append(
                        f"| {axis} | {axis_fit['point_count']} | {fmt(axis_fit['free_slope'])} | "
                        f"{fmt(axis_fit['free_r_squared'])} | {fmt(axis_fit['reference_tau_s'])} | "
                        f"{fmt(axis_fit['reference_value'])} |"
                    )
                lines.append("")

    candidate = report["kalibr_candidate"]
    if candidate is not None:
        lines += [
            "## Kalibr candidate parameters",
            "",
            f"Axis policy: `{candidate['axis_policy']}`",
            "",
            f"- `accelerometer_noise_density`: {fmt(candidate['accelerometer_noise_density_m_s2_sqrt_hz'])}",
            f"- `gyroscope_noise_density`: {fmt(candidate['gyroscope_noise_density_rad_s_sqrt_hz'])}",
            f"- `accelerometer_random_walk`: {fmt(candidate['accelerometer_random_walk_m_s3_sqrt_hz'])}",
            f"- `gyroscope_random_walk`: {fmt(candidate['gyroscope_random_walk_rad_s2_sqrt_hz'])}",
            f"- `update_rate`: {fmt(candidate['update_rate_hz'])}",
            "",
            "These are candidate fit results only; they are not automatically promoted into a calibration artifact.",
        ]
    lines += ["", "## Guardrails", ""]
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines)


def write_curve_csv(report: dict[str, Any], path: Path) -> None:
    fields = ["tau_s", "block_size", "cluster_count", "pair_count"]
    fields += [f"{axis}_raw_adev" for axis in AXIS_NAMES]
    fields += [f"{axis}_si_adev" for axis in AXIS_NAMES]
    fields += [f"{axis}_local_slope" for axis in AXIS_NAMES]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for point in report["curve"]:
            row: dict[str, Any] = {
                "tau_s": point["tau_s"],
                "block_size": point["block_size"],
                "cluster_count": point["cluster_count"],
                "pair_count": point["pair_count"],
            }
            for axis in AXIS_NAMES:
                row[f"{axis}_raw_adev"] = point["raw_adev"][axis]
                row[f"{axis}_si_adev"] = "" if point["si_adev"] is None else point["si_adev"].get(axis, "")
                row[f"{axis}_local_slope"] = point["local_slope_raw"].get(axis)
            writer.writerow(row)


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return result


def positive_int(value: str) -> int:
    result = int(value, 10)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return result


def naive_nonoverlap(values: Sequence[float], block_size: int) -> tuple[float, int]:
    blocks = [
        statistics.fmean(values[start:start + block_size])
        for start in range(0, len(values) - block_size + 1, block_size)
    ]
    diffs = [(blocks[index] - blocks[index - 1]) ** 2 for index in range(1, len(blocks))]
    if not diffs:
        return 0.0, 0
    return math.sqrt(0.5 * statistics.fmean(diffs)), len(diffs)


def write_fixture(path: Path) -> None:
    header = [
        "frame_index", "frame_sequence", "host_receive_monotonic_ns",
        "exposure_start_raw_us", "exposure_end_raw_us",
        "exposure_start_extended_us", "exposure_end_extended_us",
        "sample_index", "sample_valid", "imu_raw_time_us", "imu_extended_time_us",
        "accel_raw_x", "accel_raw_y", "accel_raw_z", "gyro_raw_x", "gyro_raw_y", "gyro_raw_z",
    ]
    series = [float(((index * 17) % 29) - 14) for index in range(256)]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for index, value in enumerate(series):
            timestamp = 1_000_000 + index * 10_000
            writer.writerow([
                index // 4, 100 + index // 4, 0,
                timestamp, timestamp + 1000, timestamp, timestamp + 1000,
                index % 4, "true", timestamp & 0xFFFFFFFF, timestamp,
                value, value * 2.0, value * -0.5,
                value * 0.1, value * -0.2, value * 0.3,
            ])


def self_test() -> int:
    # Exact streaming estimator check against the direct definition.
    source = [float(((index * 17) % 29) - 14) for index in range(256)]
    stream = StreamingDyadicAllan()
    for value in source:
        stream.add([value, value * 2, value * -0.5, value * 0.1, value * -0.2, value * 0.3])
    curve = stream.curve(0.01, min_pairs=2)
    for point in curve:
        expected, pairs = naive_nonoverlap(source, point["block_size"])
        assert pairs == point["pair_count"]
        assert abs(point["raw_adev"]["accel_x"] - expected) < 1e-12

    # Fixed/free log fit semantics used for Kalibr candidate extraction.
    white_points = [(tau, 2.0 / math.sqrt(tau)) for tau in (0.25, 0.5, 1.0, 2.0)]
    white_fit = log_fit(
        white_points, tau_window=(0.2, 2.1), expected_slope=-0.5, reference_tau_s=1.0
    )
    assert abs(white_fit.free_slope + 0.5) < 1e-12
    assert abs(white_fit.reference_value - 2.0) < 1e-12

    rw_points = [(tau, 3.0 * math.sqrt(tau / 3.0)) for tau in (1.0, 2.0, 4.0, 8.0)]
    rw_fit = log_fit(
        rw_points, tau_window=(0.9, 8.1), expected_slope=0.5, reference_tau_s=3.0
    )
    assert abs(rw_fit.free_slope - 0.5) < 1e-12
    assert abs(rw_fit.reference_value - 3.0) < 1e-12

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "imu.csv"
        write_fixture(path)
        report = analyze(
            path,
            min_pairs=2,
            accel_g_per_count=1.0 / 8192.0,
            gyro_dps_per_count=1.0 / 32.768,
            scale_source="synthetic verified scale",
            white_window=None,
            random_walk_window=None,
            kalibr_axis_policy=None,
            sample_rate_hz=None,
            allow_invalid_samples=False,
            allow_timing_anomalies=False,
        )
        assert report["timing"]["sample_count"] == 256
        assert abs(report["sample_period"]["rate_hz"] - 100.0) < 1e-9
        assert report["curve"][0]["block_size"] == 1
        curve_path = Path(temporary) / "curve.csv"
        write_curve_csv(report, curve_path)
        assert curve_path.exists() and curve_path.stat().st_size > 0
        assert "IMU Allan Deviation" in render_markdown(report)

        try:
            analyze(
                path, min_pairs=2,
                accel_g_per_count=1.0 / 8192.0, gyro_dps_per_count=None, scale_source=None,
                white_window=None, random_walk_window=None, kalibr_axis_policy=None,
                sample_rate_hz=None, allow_invalid_samples=False, allow_timing_anomalies=False,
            )
        except ValueError as exc:
            assert "scale-source" in str(exc)
        else:
            raise AssertionError("scale provenance must be explicit")

    print("IMU Allan laboratory self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute streaming dyadic Allan deviation from a Bividi Nori IMU raw-count trace"
    )
    parser.add_argument("trace", nargs="?", type=Path)
    parser.add_argument("--min-pairs", type=positive_int, default=8,
                        help="minimum adjacent cluster pairs retained per tau (default 8)")
    parser.add_argument("--sample-rate-hz", type=positive_float,
                        help="explicit analysis rate; otherwise derive first-to-last effective rate from device timestamps")
    parser.add_argument("--accel-g-per-count", type=positive_float,
                        help="explicit accelerometer scale; never inferred from vendor demo")
    parser.add_argument("--gyro-dps-per-count", type=positive_float,
                        help="explicit gyroscope scale; never inferred from vendor demo")
    parser.add_argument("--scale-source",
                        help="required provenance label whenever an SI conversion scale is supplied")
    parser.add_argument("--white-window", type=parse_window,
                        help="explicit Allan tau fit window MIN:MAX seconds for the -1/2 white-noise line")
    parser.add_argument("--random-walk-window", type=parse_window,
                        help="explicit Allan tau fit window MIN:MAX seconds for the +1/2 random-walk line")
    parser.add_argument("--kalibr-axis-policy", choices=("max", "mean", "median"),
                        help="explicitly reduce per-axis SI fit candidates to Kalibr scalar parameters")
    parser.add_argument("--allow-invalid-samples", action="store_true",
                        help="exploratory only: skip invalid samples instead of rejecting the trace")
    parser.add_argument("--allow-timing-anomalies", action="store_true",
                        help="exploratory only: permit duplicate/backward timestamps")
    parser.add_argument("--output-prefix", type=Path,
                        help="write PREFIX.allan.csv, PREFIX.allan.json, and PREFIX.allan.md")
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.trace is None:
        print("IMU trace CSV path is required", file=sys.stderr)
        return 3
    try:
        report = analyze(
            args.trace,
            min_pairs=args.min_pairs,
            accel_g_per_count=args.accel_g_per_count,
            gyro_dps_per_count=args.gyro_dps_per_count,
            scale_source=args.scale_source,
            white_window=args.white_window,
            random_walk_window=args.random_walk_window,
            kalibr_axis_policy=args.kalibr_axis_policy,
            sample_rate_hz=args.sample_rate_hz,
            allow_invalid_samples=args.allow_invalid_samples,
            allow_timing_anomalies=args.allow_timing_anomalies,
        )
    except ValueError as exc:
        print(f"analyze_imu_allan: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report)
    print(markdown)

    csv_out = args.csv_out
    json_out = args.json_out
    markdown_out = args.markdown_out
    if args.output_prefix is not None:
        csv_out = csv_out or Path(str(args.output_prefix) + ".allan.csv")
        json_out = json_out or Path(str(args.output_prefix) + ".allan.json")
        markdown_out = markdown_out or Path(str(args.output_prefix) + ".allan.md")
    if csv_out is not None:
        write_curve_csv(report, csv_out)
    if json_out is not None:
        json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_out is not None:
        markdown_out.write_text(markdown + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
