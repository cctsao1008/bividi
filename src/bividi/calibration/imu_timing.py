"""Audit camera/IMU timing from a lossless Bividi IMU trace CSV.

This is the installed implementation for the legacy
``tools/audit_imu_timing.py`` compatibility entry point.

The tool works only within the DECXIN device timestamp domain. It never
subtracts host arrival time from device time and it does not interpret a nearest
sample delta as a calibrated camera↔IMU offset.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

REPORT_SCHEMA = "bividi.calibration.camera_imu_timing_audit.v1"
COMPATIBILITY_TOOL_NAME = "audit_imu_timing.py"
REQUIRED_COLUMNS = {
    "frame_index",
    "frame_sequence",
    "exposure_start_raw_us",
    "exposure_end_raw_us",
    "exposure_start_extended_us",
    "exposure_end_extended_us",
    "sample_index",
    "sample_valid",
    "imu_raw_time_us",
    "imu_extended_time_us",
}
UINT32_MODULUS = 1 << 32
UINT32_HALF = 1 << 31


@dataclass
class Distribution:
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None


@dataclass
class FrameTiming:
    frame_index: int
    sequence: int
    es_raw_us: int
    ee_raw_us: int
    es_us: int
    ee_us: int
    valid_samples: int = 0


def percentile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def summarize(values: Iterable[float]) -> Distribution:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return Distribution()
    return Distribution(
        count=len(finite),
        minimum=finite[0],
        maximum=finite[-1],
        mean=sum(finite) / len(finite),
        p50=percentile(finite, 0.50),
        p95=percentile(finite, 0.95),
        p99=percentile(finite, 0.99),
    )


def parse_int(row: dict[str, str], key: str, line: int) -> int:
    try:
        return int(row[key], 10)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"line {line}: invalid integer field {key!r}") from exc


def parse_bool(value: str, line: int, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"line {line}: invalid boolean field {key!r}: {value!r}")


def load_trace(path: Path) -> tuple[list[FrameTiming], list[tuple[int, int]], int]:
    frames: dict[int, FrameTiming] = {}
    samples: list[tuple[int, int]] = []
    invalid_samples = 0

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
            frame_index = parse_int(row, "frame_index", line)
            sequence = parse_int(row, "frame_sequence", line)
            es_raw = parse_int(row, "exposure_start_raw_us", line)
            ee_raw = parse_int(row, "exposure_end_raw_us", line)
            es = parse_int(row, "exposure_start_extended_us", line)
            ee = parse_int(row, "exposure_end_extended_us", line)
            valid = parse_bool(row["sample_valid"], line, "sample_valid")
            imu_raw = parse_int(row, "imu_raw_time_us", line)
            imu_extended = parse_int(row, "imu_extended_time_us", line)

            frame = frames.get(frame_index)
            if frame is None:
                frame = FrameTiming(frame_index, sequence, es_raw, ee_raw, es, ee)
                frames[frame_index] = frame
            else:
                expected = (
                    frame.sequence,
                    frame.es_raw_us,
                    frame.ee_raw_us,
                    frame.es_us,
                    frame.ee_us,
                )
                actual = (sequence, es_raw, ee_raw, es, ee)
                if expected != actual:
                    raise ValueError(
                        f"line {line}: inconsistent frame timing repeated for frame {frame_index}"
                    )

            if valid:
                frame.valid_samples += 1
                samples.append((imu_extended, imu_raw))
            else:
                invalid_samples += 1

    ordered_frames = [frames[key] for key in sorted(frames)]
    return ordered_frames, samples, invalid_samples


def count_raw_wraps(raw_values: list[int]) -> int:
    wraps = 0
    for before, after in zip(raw_values, raw_values[1:]):
        if before > after and before - after > UINT32_HALF:
            wraps += 1
    return wraps


def nearest_delta(sorted_timestamps: list[int], reference: int) -> int | None:
    if not sorted_timestamps:
        return None
    index = bisect.bisect_left(sorted_timestamps, reference)
    candidates: list[int] = []
    if index < len(sorted_timestamps):
        candidates.append(sorted_timestamps[index])
    if index > 0:
        candidates.append(sorted_timestamps[index - 1])
    nearest = min(candidates, key=lambda value: (abs(value - reference), value))
    return nearest - reference


def audit(path: Path, gap_threshold_us: float | None = None) -> dict[str, Any]:
    frames, sample_pairs, invalid_samples = load_trace(path)
    if not frames:
        raise ValueError("trace contains no frames")
    if not sample_pairs:
        raise ValueError("trace contains no valid IMU samples")

    # Preserve file order for continuity checks; use a sorted unique timeline
    # only for nearest-sample queries around camera timestamps.
    imu_times = [item[0] for item in sample_pairs]
    imu_raw = [item[1] for item in sample_pairs]
    intervals = [after - before for before, after in zip(imu_times, imu_times[1:])]
    positive_intervals = [float(value) for value in intervals if value > 0]
    duplicate_intervals = sum(1 for value in intervals if value == 0)
    backward_intervals = sum(1 for value in intervals if value < 0)
    gap_count = None
    if gap_threshold_us is not None:
        gap_count = sum(1 for value in intervals if value > gap_threshold_us)

    sorted_imu = sorted(set(imu_times))
    nearest_es = [nearest_delta(sorted_imu, frame.es_us) for frame in frames]
    nearest_ee = [nearest_delta(sorted_imu, frame.ee_us) for frame in frames]
    nearest_es_values = [float(value) for value in nearest_es if value is not None]
    nearest_ee_values = [float(value) for value in nearest_ee if value is not None]
    nearest_es_abs = [abs(value) for value in nearest_es_values]
    nearest_ee_abs = [abs(value) for value in nearest_ee_values]

    es_intervals = [
        float(after.es_us - before.es_us)
        for before, after in zip(frames, frames[1:])
        if after.es_us > before.es_us
    ]
    ee_intervals = [
        float(after.ee_us - before.ee_us)
        for before, after in zip(frames, frames[1:])
        if after.ee_us > before.ee_us
    ]
    exposure_duration = [float(frame.ee_us - frame.es_us) for frame in frames]
    valid_per_frame = [float(frame.valid_samples) for frame in frames]

    effective_rate_hz = None
    if len(imu_times) > 1 and imu_times[-1] > imu_times[0]:
        effective_rate_hz = (
            (len(imu_times) - 1) * 1_000_000.0 / (imu_times[-1] - imu_times[0])
        )

    return {
        "schema": REPORT_SCHEMA,
        "source_trace": str(path),
        "clock_domain": "DECXIN extended device microseconds",
        "frames": len(frames),
        "imu": {
            "valid_samples": len(imu_times),
            "invalid_samples": invalid_samples,
            "effective_rate_hz": effective_rate_hz,
            "interval_us": asdict(summarize(positive_intervals)),
            "duplicate_timestamp_intervals": duplicate_intervals,
            "backward_timestamp_intervals": backward_intervals,
            "raw_counter_wraps": count_raw_wraps(imu_raw),
            "gap_threshold_us": gap_threshold_us,
            "gaps_over_threshold": gap_count,
            "valid_samples_per_frame": asdict(summarize(valid_per_frame)),
        },
        "camera": {
            "exposure_start_interval_us": asdict(summarize(es_intervals)),
            "exposure_end_interval_us": asdict(summarize(ee_intervals)),
            "exposure_duration_us": asdict(summarize(exposure_duration)),
            "exposure_start_raw_counter_wraps": count_raw_wraps(
                [frame.es_raw_us for frame in frames]
            ),
            "exposure_end_raw_counter_wraps": count_raw_wraps(
                [frame.ee_raw_us for frame in frames]
            ),
        },
        "nearest_imu_to_exposure_start": {
            "signed_imu_minus_camera_us": asdict(summarize(nearest_es_values)),
            "absolute_us": asdict(summarize(nearest_es_abs)),
        },
        "nearest_imu_to_exposure_end": {
            "signed_imu_minus_camera_us": asdict(summarize(nearest_ee_values)),
            "absolute_us": asdict(summarize(nearest_ee_abs)),
        },
        "interpretation_note": (
            "Nearest-sample deltas quantify timestamp geometry inside the shared DECXIN device-time domain. "
            "They are not by themselves a calibrated camera-IMU temporal offset."
        ),
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    imu = report["imu"]
    camera = report["camera"]
    es = report["nearest_imu_to_exposure_start"]
    ee = report["nearest_imu_to_exposure_end"]
    lines = [
        "# Camera↔IMU Timestamp Audit",
        "",
        f"- Source: `{report['source_trace']}`",
        f"- Frames: {report['frames']}",
        f"- Valid IMU samples: {imu['valid_samples']}",
        f"- Invalid IMU samples: {imu['invalid_samples']}",
        f"- Effective IMU rate: {fmt(imu['effective_rate_hz'])} Hz",
        f"- Duplicate IMU timestamp intervals: {imu['duplicate_timestamp_intervals']}",
        f"- Backward IMU timestamp intervals: {imu['backward_timestamp_intervals']}",
        f"- IMU raw counter wraps: {imu['raw_counter_wraps']}",
        "",
        "## Timing distributions",
        "",
        "| Metric | P50 | P95 | P99 | Max |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    metrics = [
        ("IMU interval us", imu["interval_us"]),
        ("Exposure-start interval us", camera["exposure_start_interval_us"]),
        ("Exposure-end interval us", camera["exposure_end_interval_us"]),
        ("Exposure duration us", camera["exposure_duration_us"]),
        ("Nearest IMU |Δ| to ES us", es["absolute_us"]),
        ("Nearest IMU |Δ| to EE us", ee["absolute_us"]),
    ]
    for name, stats in metrics:
        lines.append(
            f"| {name} | {fmt(stats['p50'])} | {fmt(stats['p95'])} | "
            f"{fmt(stats['p99'])} | {fmt(stats['maximum'])} |"
        )
    lines += [
        "",
        "## Signed nearest-sample evidence",
        "",
        f"- ES: IMU - camera p50 = {fmt(es['signed_imu_minus_camera_us']['p50'])} us",
        f"- EE: IMU - camera p50 = {fmt(ee['signed_imu_minus_camera_us']['p50'])} us",
        "",
        report["interpretation_note"],
    ]
    if imu["gap_threshold_us"] is not None:
        lines += [
            "",
            f"Explicit gap threshold: {fmt(imu['gap_threshold_us'])} us; "
            f"intervals over threshold: {imu['gaps_over_threshold']}",
        ]
    return "\n".join(lines)


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
    rows: list[list[Any]] = []
    # 3 frames at 10 ms, four 2.5 ms IMU samples per frame. Exposure end is
    # intentionally 500 us after the closest sample to exercise signed deltas.
    for frame in range(3):
        es = 1_000_000 + frame * 10_000
        ee = es + 2_000
        for sample_index in range(4):
            imu = es - 2_500 + sample_index * 2_500
            rows.append(
                [
                    frame,
                    100 + frame,
                    0,
                    es,
                    ee,
                    es,
                    ee,
                    sample_index,
                    "true",
                    imu & 0xFFFFFFFF,
                    imu,
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                ]
            )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "imu.csv"
        write_fixture(path)
        report = audit(path, gap_threshold_us=3000.0)
        assert report["frames"] == 3
        assert report["imu"]["valid_samples"] == 12
        assert report["imu"]["interval_us"]["p50"] == 2500.0
        assert report["imu"]["gaps_over_threshold"] == 0
        assert report["nearest_imu_to_exposure_start"]["absolute_us"]["p50"] == 0.0
        assert report["nearest_imu_to_exposure_end"]["absolute_us"]["p50"] == 500.0
        assert "Timestamp Audit" in render_markdown(report)
    print("camera-IMU timestamp audit self-test: PASS")
    return 0


def nonnegative_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit camera/IMU device-time relationships from a Nori IMU trace"
    )
    parser.add_argument("trace", nargs="?", type=Path)
    parser.add_argument(
        "--gap-threshold-us",
        type=nonnegative_float,
        help="optional explicit threshold for counting long IMU intervals",
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
        report = audit(args.trace, gap_threshold_us=args.gap_threshold_us)
    except ValueError as exc:
        print(f"audit_imu_timing: {exc}", file=sys.stderr)
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
