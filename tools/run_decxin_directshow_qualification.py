#!/usr/bin/env python3
"""Run a bounded DECXIN AR0234 timing qualification through Windows DirectShow.

This is a physical bring-up cross-check for Issue #35. FFmpeg owns the Windows
DirectShow transport/decode step. Only the 160x1200 encoded metadata strip is
streamed to Python as BGR24, then Bividi's existing DECXIN/Nori decoder
primitives recover exposure and IMU timing.

The tool deliberately preserves raw transport behavior, including the repeated
IMU endpoint observed at adjacent video-frame boundaries. It does not normalize
or deduplicate samples for downstream VIO.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from bividi.decxin import (
    BgrFrame,
    DECXIN_METADATA_WIDTH,
    DECXIN_TRANSPORT_HEIGHT,
    ICM42688_DEVICE_TYPE,
    NORI_GROUP_SIZE,
    TimestampExtender32,
    decode_icm42688_group,
    decode_nori_payload,
)

SCHEMA = "bividi.decxin.directshow_qualification.v1"
TRANSPORT_WIDTH = 4000
TRANSPORT_HEIGHT = DECXIN_TRANSPORT_HEIGHT
METADATA_WIDTH = DECXIN_METADATA_WIDTH
BYTES_PER_PIXEL = 3
FRAME_BYTES = METADATA_WIDTH * TRANSPORT_HEIGHT * BYTES_PER_PIXEL


@dataclass(frozen=True)
class ImuBoundarySample:
    time_us: int
    accel_raw: tuple[int, int, int]
    gyro_raw: tuple[int, int, int]
    valid: bool


def positive_int(value: str) -> int:
    parsed = int(value, 10)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not parsed > 0.0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def ffmpeg_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = completed.stdout.splitlines()
    return first[0].strip() if first else None


def read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def series_summary(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def adjacent_deltas(values: list[int]) -> list[int]:
    return [right - left for left, right in zip(values, values[1:])]


def classify_frame_delta_events(deltas: list[int]) -> list[dict[str, Any]]:
    positive = [value for value in deltas if value > 0]
    median = statistics.median(positive) if positive else None
    events: list[dict[str, Any]] = []
    for boundary, value in enumerate(deltas, start=2):
        if value < 0:
            kind = "backward"
        elif value == 0:
            kind = "duplicate"
        elif median is not None and value > median * 1.5:
            kind = "large_gap"
        else:
            continue
        events.append({"frame": boundary, "delta_us": value, "kind": kind})
    return events


def build_ffmpeg_command(args: argparse.Namespace) -> list[str]:
    return [
        args.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "dshow",
        "-video_size",
        f"{TRANSPORT_WIDTH}x{TRANSPORT_HEIGHT}",
        "-framerate",
        f"{args.framerate:g}",
        "-vcodec",
        "mjpeg",
        "-i",
        f"video={args.device_name}",
        "-frames:v",
        str(args.frames),
        "-vf",
        f"crop={METADATA_WIDTH}:{TRANSPORT_HEIGHT}:0:0",
        "-pix_fmt",
        "bgr24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]


def decode_metadata_frame(
    raw: bytes,
    exposure_clock: TimestampExtender32,
    imu_clock: TimestampExtender32,
) -> tuple[Any, int, int, list[Any]]:
    frame = BgrFrame(
        width=METADATA_WIDTH,
        height=TRANSPORT_HEIGHT,
        data=raw,
        row_stride=METADATA_WIDTH * BYTES_PER_PIXEL,
    )
    header, payload = decode_nori_payload(frame)
    exposure_start_us = exposure_clock.extend(header.exposure_start_raw_us)
    exposure_end_us = exposure_clock.extend(header.exposure_end_raw_us)

    samples: list[Any] = []
    group_index = 1
    for device_group in header.device_groups:
        for _ in range(device_group.group_count):
            begin = group_index * NORI_GROUP_SIZE
            group = payload[begin : begin + NORI_GROUP_SIZE]
            if device_group.device_type == ICM42688_DEVICE_TYPE:
                samples.append(decode_icm42688_group(group, imu_clock))
            group_index += 1
    return header, exposure_start_us, exposure_end_us, samples


def boundary_sample(sample: Any) -> ImuBoundarySample:
    return ImuBoundarySample(
        time_us=sample.extended_time_us,
        accel_raw=sample.accel_raw,
        gyro_raw=sample.gyro_raw,
        valid=sample.valid,
    )


def run(args: argparse.Namespace) -> int:
    command = build_ffmpeg_command(args)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(json.dumps({"command": command, "output": str(output_path)}, indent=2))
        return 0

    if platform.system() != "Windows":
        print("DirectShow qualification requires Windows; use --self-test for CI.", file=sys.stderr)
        return 2
    if shutil.which(args.ffmpeg) is None and not Path(args.ffmpeg).exists():
        print(f"FFmpeg executable not found: {args.ffmpeg}", file=sys.stderr)
        return 2

    exposure_clock = TimestampExtender32()
    imu_clock = TimestampExtender32()

    exposure_starts: list[int] = []
    exposure_ends: list[int] = []
    exposure_durations: list[int] = []
    imu_counts: list[int] = []
    imu_deltas: list[int] = []
    imu_bridges: list[int] = []
    all_imu_times: list[int] = []
    protocol_types: set[int] = set()
    device_group_shapes: set[tuple[tuple[int, int], ...]] = set()
    decode_errors: list[dict[str, Any]] = []
    boundary_payload_mismatches: list[dict[str, Any]] = []
    invalid_imu_samples = 0
    previous_last_imu: ImuBoundarySample | None = None

    stderr_lines: list[str] = []

    started_wall = time.monotonic()
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        print(f"failed to execute FFmpeg: {exc}", file=sys.stderr)
        return 2

    assert proc.stdout is not None
    assert proc.stderr is not None

    def drain_stderr() -> None:
        for line in iter(proc.stderr.readline, b""):
            stderr_lines.append(line.decode(errors="replace").rstrip())

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()

    received_frames = 0
    truncated_bytes = 0

    while received_frames < args.frames:
        raw = read_exact(proc.stdout, FRAME_BYTES)
        if not raw:
            break
        if len(raw) != FRAME_BYTES:
            truncated_bytes = len(raw)
            decode_errors.append(
                {
                    "frame": received_frames + 1,
                    "error": f"truncated raw frame: {len(raw)} of {FRAME_BYTES} bytes",
                }
            )
            break

        received_frames += 1
        try:
            header, exposure_start_us, exposure_end_us, samples = decode_metadata_frame(
                raw, exposure_clock, imu_clock
            )
        except Exception as exc:  # evidence path: preserve exact decode failure text
            decode_errors.append({"frame": received_frames, "error": str(exc)})
            continue

        protocol_types.add(header.protocol_type)
        device_group_shapes.add(
            tuple((group.device_type, group.group_count) for group in header.device_groups)
        )
        exposure_starts.append(exposure_start_us)
        exposure_ends.append(exposure_end_us)
        exposure_durations.append(exposure_end_us - exposure_start_us)
        imu_counts.append(len(samples))

        times = [sample.extended_time_us for sample in samples]
        all_imu_times.extend(times)
        imu_deltas.extend(adjacent_deltas(times))
        invalid_imu_samples += sum(not sample.valid for sample in samples)

        if samples:
            first = boundary_sample(samples[0])
            last = boundary_sample(samples[-1])
            if previous_last_imu is not None:
                bridge = first.time_us - previous_last_imu.time_us
                imu_bridges.append(bridge)
                if bridge == 0 and first != previous_last_imu:
                    boundary_payload_mismatches.append(
                        {
                            "frame": received_frames,
                            "timestamp_us": first.time_us,
                            "previous": {
                                "accel_raw": list(previous_last_imu.accel_raw),
                                "gyro_raw": list(previous_last_imu.gyro_raw),
                                "valid": previous_last_imu.valid,
                            },
                            "current": {
                                "accel_raw": list(first.accel_raw),
                                "gyro_raw": list(first.gyro_raw),
                                "valid": first.valid,
                            },
                        }
                    )
            previous_last_imu = last

    if proc.poll() is None:
        proc.stdout.close()
    return_code = proc.wait()
    stderr_thread.join(timeout=2.0)

    finished_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    wall_seconds = time.monotonic() - started_wall

    es_deltas = adjacent_deltas(exposure_starts)
    ee_deltas = adjacent_deltas(exposure_ends)
    frame_events = classify_frame_delta_events(es_deltas)

    unique_imu_times = sorted(set(all_imu_times))
    device_fps = None
    if len(exposure_starts) >= 2:
        duration_s = (exposure_starts[-1] - exposure_starts[0]) / 1_000_000.0
        if duration_s > 0:
            device_fps = (len(exposure_starts) - 1) / duration_s

    effective_imu_hz = None
    if len(unique_imu_times) >= 2:
        duration_s = (unique_imu_times[-1] - unique_imu_times[0]) / 1_000_000.0
        if duration_s > 0:
            effective_imu_hz = (len(unique_imu_times) - 1) / duration_s

    bridge_summary = {
        "count": len(imu_bridges),
        "zero_count": sum(value == 0 for value in imu_bridges),
        "positive_count": sum(value > 0 for value in imu_bridges),
        "negative_count": sum(value < 0 for value in imu_bridges),
        **series_summary(imu_bridges),
    }

    completed = (
        return_code == 0
        and received_frames == args.frames
        and len(exposure_starts) == args.frames
        and not decode_errors
        and truncated_bytes == 0
    )

    evidence = {
        "schema": SCHEMA,
        "assessment": "completed" if completed else "incomplete",
        "evidence_boundary": (
            "Windows DirectShow/FFmpeg physical transport timing cross-check only; "
            "does not replace Nori SDK qualification or prove stereo synchronization accuracy."
        ),
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "repository": {"git_revision": git_revision()},
        "ffmpeg": {
            "executable": args.ffmpeg,
            "resolved_path": shutil.which(args.ffmpeg),
            "version": ffmpeg_version(args.ffmpeg),
            "command": command,
            "return_code": return_code,
            "stderr": stderr_lines,
        },
        "source": {
            "device_name": args.device_name,
            "transport": "DirectShow",
            "input_mode": f"MJPEG {TRANSPORT_WIDTH}x{TRANSPORT_HEIGHT} @ {args.framerate:g} nominal fps",
            "metadata_crop": {
                "x": 0,
                "width": METADATA_WIDTH,
                "height": TRANSPORT_HEIGHT,
                "pixel_format": "bgr24",
            },
            "target_frames": args.frames,
        },
        "result": {
            "received_frames": received_frames,
            "decoded_frames": len(exposure_starts),
            "decode_errors": decode_errors,
            "truncated_raw_frame_bytes": truncated_bytes,
            "wall_seconds": wall_seconds,
            "protocol_types": sorted(protocol_types),
            "device_group_shapes": [
                [list(entry) for entry in shape] for shape in sorted(device_group_shapes)
            ],
            "exposure_duration_us": series_summary(exposure_durations),
            "exposure_start_delta_us": series_summary(es_deltas),
            "exposure_end_delta_us": series_summary(ee_deltas),
            "frame_timing_events": frame_events,
            "device_fps": device_fps,
            "imu_samples_per_frame": series_summary(imu_counts),
            "imu_intra_frame_delta_us": series_summary(imu_deltas),
            "imu_boundary_bridge_us": bridge_summary,
            "boundary_payload_mismatches": boundary_payload_mismatches,
            "unique_imu_samples": len(unique_imu_times),
            "effective_imu_hz": effective_imu_hz,
            "invalid_imu_samples": invalid_imu_samples,
        },
    }

    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("=== DECXIN DirectShow qualification ===")
    print(f"assessment           : {evidence['assessment']}")
    print(f"frames               : {received_frames}/{args.frames}")
    print(f"decoded              : {len(exposure_starts)}")
    print(f"decode errors        : {len(decode_errors)}")
    print(f"wall seconds         : {wall_seconds:.3f}")
    print(f"protocol types       : {sorted(protocol_types)}")
    print(f"dES us               : {series_summary(es_deltas)}")
    print(f"dEE us               : {series_summary(ee_deltas)}")
    print(f"exposure us          : {series_summary(exposure_durations)}")
    print(f"device FPS           : {device_fps}")
    print(f"IMU/frame            : {series_summary(imu_counts)}")
    print(f"IMU dt us            : {series_summary(imu_deltas)}")
    print(f"IMU bridge           : {bridge_summary}")
    print(f"boundary mismatches  : {len(boundary_payload_mismatches)}")
    print(f"unique IMU samples   : {len(unique_imu_times)}")
    print(f"effective IMU Hz     : {effective_imu_hz}")
    print(f"invalid IMU          : {invalid_imu_samples}")
    print(f"frame timing events  : {len(frame_events)}")
    print(f"ffmpeg return        : {return_code}")
    print(f"evidence             : {output_path}")
    return 0 if completed else 1


def self_test() -> int:
    assert adjacent_deltas([100, 133, 166]) == [33, 33]
    assert series_summary([33, 34, 33]) == {"min": 33, "median": 33, "max": 34}

    events = classify_frame_delta_events([33, 33, 66, 0, -2, 34])
    assert events == [
        {"frame": 4, "delta_us": 66, "kind": "large_gap"},
        {"frame": 5, "delta_us": 0, "kind": "duplicate"},
        {"frame": 6, "delta_us": -2, "kind": "backward"},
    ]

    namespace = argparse.Namespace(
        ffmpeg="ffmpeg",
        framerate=30.0,
        frames=900,
        device_name="DECXIN Camera",
    )
    command = build_ffmpeg_command(namespace)
    assert "dshow" in command
    assert "video=DECXIN Camera" in command
    assert "crop=160:1200:0:0" in command
    assert command[-1] == "pipe:1"

    same = ImuBoundarySample(100, (1, 2, 3), (4, 5, 6), True)
    assert same == ImuBoundarySample(100, (1, 2, 3), (4, 5, 6), True)
    assert same != ImuBoundarySample(100, (9, 2, 3), (4, 5, 6), True)

    print("DECXIN DirectShow qualification self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run bounded DECXIN timing qualification through Windows DirectShow/FFmpeg."
    )
    p.add_argument("--device-name", default="DECXIN Camera")
    p.add_argument("--frames", type=positive_int, default=900)
    p.add_argument("--framerate", type=positive_float, default=30.0)
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument(
        "--output",
        default="artifacts/physical/ar0234-directshow-900f.json",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
