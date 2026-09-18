"""Analyze a stationary Bividi IMU trace without assuming sensor full-scale.

This is the installed implementation for the legacy
``tools/analyze_imu_stationary.py`` compatibility entry point.

Raw-count statistics are always reported. SI conversion is optional and only
performed when the operator supplies explicit per-count scales plus a provenance
label; vendor-demo scale assumptions are never applied silently.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from . import imu_timing

REPORT_SCHEMA = "bividi.calibration.imu_stationary_analysis.v1"
COMPATIBILITY_TOOL_NAME = "analyze_imu_stationary.py"
GRAVITY_M_S2 = 9.80665
REQUIRED_COLUMNS = {
    "sample_valid",
    "imu_extended_time_us",
    "accel_raw_x",
    "accel_raw_y",
    "accel_raw_z",
    "gyro_raw_x",
    "gyro_raw_y",
    "gyro_raw_z",
}


@dataclass
class AxisStats:
    count: int
    mean: float
    stddev_population: float
    minimum: float
    maximum: float


def axis_stats(values: list[float]) -> AxisStats:
    if not values:
        raise ValueError("cannot summarize an empty axis")
    return AxisStats(
        count=len(values),
        mean=statistics.fmean(values),
        stddev_population=statistics.pstdev(values),
        minimum=min(values),
        maximum=max(values),
    )


def vector_stats(
    samples: list[tuple[float, float, float]],
) -> dict[str, dict[str, Any]]:
    if not samples:
        raise ValueError("no samples")
    axes = list(zip(*samples))
    return {
        name: asdict(axis_stats(list(axis)))
        for name, axis in zip(("x", "y", "z"), axes)
    }


def load_raw(
    path: Path,
) -> tuple[
    list[int],
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    int,
]:
    timestamps: list[int] = []
    accel: list[tuple[float, float, float]] = []
    gyro: list[tuple[float, float, float]] = []
    invalid = 0
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
            valid_text = row["sample_valid"].strip().lower()
            if valid_text not in {"true", "false"}:
                raise ValueError(
                    f"line {line}: invalid sample_valid {row['sample_valid']!r}"
                )
            if valid_text == "false":
                invalid += 1
                continue
            try:
                timestamps.append(int(row["imu_extended_time_us"], 10))
                accel.append(
                    tuple(float(row[f"accel_raw_{axis}"]) for axis in "xyz")
                )
                gyro.append(
                    tuple(float(row[f"gyro_raw_{axis}"]) for axis in "xyz")
                )
            except ValueError as exc:
                raise ValueError(f"line {line}: invalid numeric IMU field") from exc
    return timestamps, accel, gyro, invalid


def scale_vector(
    samples: list[tuple[float, float, float]], factor: float
) -> list[tuple[float, float, float]]:
    return [tuple(value * factor for value in sample) for sample in samples]


def analyze(
    path: Path,
    *,
    accel_g_per_count: float | None,
    gyro_dps_per_count: float | None,
    scale_source: str | None,
) -> dict[str, Any]:
    timestamps, accel_raw, gyro_raw, invalid = load_raw(path)
    if not timestamps:
        raise ValueError("trace contains no valid IMU samples")

    if (
        accel_g_per_count is not None or gyro_dps_per_count is not None
    ) and not scale_source:
        raise ValueError(
            "--scale-source is required whenever an SI conversion scale is supplied"
        )

    duration_s = 0.0
    effective_rate_hz = None
    if len(timestamps) > 1 and timestamps[-1] > timestamps[0]:
        duration_s = (timestamps[-1] - timestamps[0]) / 1_000_000.0
        effective_rate_hz = (len(timestamps) - 1) / duration_s

    timing = imu_timing.audit(path)
    result: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "source_trace": str(path),
        "stationary_assumption": (
            "The operator declares this recording stationary. This analyzer reports statistics but "
            "does not independently prove the rig was motionless."
        ),
        "sample_count": len(timestamps),
        "invalid_sample_count": invalid,
        "duration_s": duration_s,
        "effective_rate_hz": effective_rate_hz,
        "raw_counts": {
            "accelerometer": vector_stats(accel_raw),
            "gyroscope": vector_stats(gyro_raw),
        },
        "timing": {
            "interval_us": timing["imu"]["interval_us"],
            "duplicate_timestamp_intervals": timing["imu"][
                "duplicate_timestamp_intervals"
            ],
            "backward_timestamp_intervals": timing["imu"][
                "backward_timestamp_intervals"
            ],
            "raw_counter_wraps": timing["imu"]["raw_counter_wraps"],
        },
        "scale_conversion": None,
        "interpretation_note": (
            "Gyroscope stationary mean is a candidate bias statistic. Accelerometer stationary mean "
            "contains gravity and is not by itself accelerometer bias."
        ),
    }

    conversion: dict[str, Any] = {"source": scale_source} if scale_source else {}
    if accel_g_per_count is not None:
        factor = accel_g_per_count * GRAVITY_M_S2
        conversion["accelerometer_g_per_count"] = accel_g_per_count
        conversion["accelerometer_m_s2_per_count"] = factor
        conversion["accelerometer_m_s2"] = vector_stats(
            scale_vector(accel_raw, factor)
        )
    if gyro_dps_per_count is not None:
        factor = gyro_dps_per_count * math.pi / 180.0
        conversion["gyroscope_dps_per_count"] = gyro_dps_per_count
        conversion["gyroscope_rad_s_per_count"] = factor
        conversion["gyroscope_rad_s"] = vector_stats(scale_vector(gyro_raw, factor))
    if conversion:
        result["scale_conversion"] = conversion
    return result


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Stationary IMU Analysis",
        "",
        f"- Source: `{report['source_trace']}`",
        f"- Valid samples: {report['sample_count']}",
        f"- Invalid samples: {report['invalid_sample_count']}",
        f"- Duration: {fmt(report['duration_s'])} s",
        f"- Effective rate: {fmt(report['effective_rate_hz'])} Hz",
        "",
        "## Raw-count statistics",
        "",
        "| Sensor | Axis | Mean | Population stddev | Min | Max |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for sensor in ("accelerometer", "gyroscope"):
        for axis in "xyz":
            stats = report["raw_counts"][sensor][axis]
            lines.append(
                f"| {sensor} | {axis} | {fmt(stats['mean'])} | {fmt(stats['stddev_population'])} | "
                f"{fmt(stats['minimum'])} | {fmt(stats['maximum'])} |"
            )
    if report["scale_conversion"] is not None:
        lines += [
            "",
            "## Explicit SI conversion",
            "",
            f"Scale source: `{report['scale_conversion'].get('source')}`",
            "",
        ]
        for sensor, key, unit in (
            ("accelerometer", "accelerometer_m_s2", "m/s^2"),
            ("gyroscope", "gyroscope_rad_s", "rad/s"),
        ):
            if key not in report["scale_conversion"]:
                continue
            lines.append(f"### {sensor} ({unit})")
            lines.append("")
            lines.append("| Axis | Mean | Population stddev |")
            lines.append("| --- | ---: | ---: |")
            for axis in "xyz":
                stats = report["scale_conversion"][key][axis]
                lines.append(
                    f"| {axis} | {fmt(stats['mean'])} | {fmt(stats['stddev_population'])} |"
                )
            lines.append("")
    lines += [
        "",
        report["interpretation_note"],
        "",
        report["stationary_assumption"],
    ]
    return "\n".join(lines)


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return result


def write_fixture(path: Path) -> None:
    header = [
        "frame_index",
        "frame_sequence",
        "host_receive_monotonic_ns",
        "exposure_start_raw_us",
        "exposure_end_raw_us",
        "exposure_start_extended_us",
        "exposure_end_extended_us",
        "sample_index",
        "sample_valid",
        "imu_raw_time_us",
        "imu_extended_time_us",
        "accel_raw_x",
        "accel_raw_y",
        "accel_raw_z",
        "gyro_raw_x",
        "gyro_raw_y",
        "gyro_raw_z",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        for index in range(8):
            frame = index // 4
            t = 1_000_000 + index * 2_500
            es = 1_000_000 + frame * 10_000
            ee = es + 2_000
            writer.writerow(
                [
                    frame,
                    100 + frame,
                    0,
                    es,
                    ee,
                    es,
                    ee,
                    index % 4,
                    "true",
                    t,
                    t,
                    0 + (index % 2),
                    1,
                    8192,
                    10 + (index % 2),
                    -20,
                    5,
                ]
            )


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "stationary.csv"
        write_fixture(path)
        report = analyze(
            path,
            accel_g_per_count=1.0 / 8192.0,
            gyro_dps_per_count=1.0 / 32.768,
            scale_source="synthetic test scale",
        )
        assert report["sample_count"] == 8
        assert report["raw_counts"]["accelerometer"]["z"]["mean"] == 8192.0
        accel_z = report["scale_conversion"]["accelerometer_m_s2"]["z"]["mean"]
        assert abs(accel_z - GRAVITY_M_S2) < 1e-9
        assert report["timing"]["interval_us"]["p50"] == 2500.0
        assert "Stationary IMU Analysis" in render_markdown(report)

        try:
            analyze(
                path,
                accel_g_per_count=1.0 / 8192.0,
                gyro_dps_per_count=None,
                scale_source=None,
            )
        except ValueError as exc:
            assert "scale-source" in str(exc)
        else:
            raise AssertionError("explicit scale provenance must be required")
    print("stationary IMU analyzer self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze a stationary Bividi Nori IMU raw-count trace"
    )
    parser.add_argument("trace", nargs="?", type=Path)
    parser.add_argument(
        "--accel-g-per-count",
        type=positive_float,
        help="explicit accelerometer scale; never inferred from vendor demo",
    )
    parser.add_argument(
        "--gyro-dps-per-count",
        type=positive_float,
        help="explicit gyroscope scale; never inferred from vendor demo",
    )
    parser.add_argument(
        "--scale-source",
        help="required provenance label when either explicit scale is supplied",
    )
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
        return 2
    try:
        report = analyze(
            args.trace,
            accel_g_per_count=args.accel_g_per_count,
            gyro_dps_per_count=args.gyro_dps_per_count,
            scale_source=args.scale_source,
        )
    except ValueError as exc:
        print(f"analyze_imu_stationary: {exc}", file=sys.stderr)
        return 2

    markdown = render_markdown(report)
    print(markdown)
    if args.json_out is not None:
        args.json_out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.markdown_out is not None:
        args.markdown_out.write_text(markdown + "\n", encoding="utf-8")
    return 0


def entrypoint(argv: Iterable[str] | None = None) -> int:
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
