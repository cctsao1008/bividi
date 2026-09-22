#!/usr/bin/env python3
"""Feature-first physical qualification for the DECXIN AR0234/Nori path.

This runner is intentionally separate from the long-duration Q1..Q7 campaign.
It answers a different question first: do all implemented functions work on the
physical specimen?  Long soak/stability remains a later phase.

The runner uses existing Bividi executables as measurement engines and emits:

  feature-results.json   machine-readable evidence/index
  report.md              human-readable feature matrix
  *.stdout.log / *.stderr.log and tool-native artifacts

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

SCHEMA = "bividi.ar0234.feature_qualification.v1"

AUTOMATED_TESTS: dict[str, str] = {
    "A00": "Probe device identity, firmware/SDK provenance, and advertised modes",
    "A01": "MJPEG raw acquisition and source sequence continuity",
    "A02": "MJPEG compressed-packet JPEG/restart-marker integrity",
    "A03": "MJPEG decoupled acquisition + decode pipeline",
    "A04": "YUYV raw acquisition and payload geometry",
    "A05": "YUYV -> BGR -> DECXIN metadata/stereo decode",
    "A06": "IMU recorder artifact, sample validity, and device timing continuity",
    "A07": "Calibration recorder stereo-image + frame/IMU artifact generation",
    "A08": "VideoStop/VideoStart lifecycle recovery",
    "A09": "SDK stream destroy/reopen recovery",
}

MANUAL_TESTS: dict[str, str] = {
    "M01": "Physical camera_a/camera_b mapping and image orientation",
    "M02": "Exposure control set/readback and visible image response",
    "M03": "Gain control set/readback and visible image response",
    "M04": "Trigger-mode control/readback; external-trigger behavior where applicable",
    "M05": "NoriCaptureSession preview + SensorObservation live boundary",
    "M06": "Engineering viewer live preview and controls",
    "M07": "Web engineering console live preview and controls",
    "M08": "Actual USB/device/audio enumeration on the delivered specimen",
    "M09": "Physical USB unplug/replug behavior and recovery outcome",
    "M10": "Hardware synchronization electrical/timing measurement",
    "M11": "100-degree SKU optics / calibration evidence hand-off to calibration workflow",
}

DEFERRED_TESTS: dict[str, str] = {
    "S01": "10-minute sustained capture / timing / RSS run",
    "S02": "One-hour soak / memory stability run",
}

ALL_IDS = tuple(AUTOMATED_TESTS) + tuple(MANUAL_TESTS) + tuple(DEFERRED_TESTS)


@dataclass
class TestResult:
    test_id: str
    name: str
    kind: str
    status: str = "NOT_RUN"
    command: list[str] = field(default_factory=list)
    return_code: int | None = None
    elapsed_s: float | None = None
    started_utc: str | None = None
    artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    note: str = ""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_token(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return value or "unknown"


def default_session_id() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{safe_token(socket.gethostname())}"


def git_revision() -> str | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            timeout=5,
        )
        return cp.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def exe_name(base: str) -> str:
    return base + (".exe" if os.name == "nt" else "")


def parse_test_selection(value: str) -> list[str]:
    value = value.strip().lower()
    if value in {"all", "automated", "functional"}:
        return list(AUTOMATED_TESTS)
    ids = [item.strip().upper() for item in value.split(",") if item.strip()]
    unknown = [item for item in ids if item not in AUTOMATED_TESTS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown automated test id(s): {', '.join(unknown)}; choose from {', '.join(AUTOMATED_TESTS)}"
        )
    return ids


def sequence_metrics(values: Sequence[int]) -> dict[str, Any]:
    gap_events = 0
    missing = 0
    duplicates = 0
    out_of_order = 0
    examples: list[list[int]] = []
    for index in range(1, len(values)):
        delta = values[index] - values[index - 1]
        if delta == 1:
            continue
        if delta == 0:
            duplicates += 1
        elif delta > 1:
            gap_events += 1
            missing += delta - 1
        else:
            out_of_order += 1
        if len(examples) < 10:
            examples.append([index, values[index - 1], values[index], delta])
    return {
        "count": len(values),
        "first": values[0] if values else None,
        "last": values[-1] if values else None,
        "gap_events": gap_events,
        "missing": missing,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "examples": examples,
    }


def command_text(command: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(command)) if os.name == "nt" else " ".join(command)


def run_command(
    *,
    result: TestResult,
    command: list[str],
    log_prefix: Path,
    dry_run: bool,
) -> tuple[int | None, str, str]:
    result.command = command
    stdout_path = log_prefix.with_suffix(".stdout.log")
    stderr_path = log_prefix.with_suffix(".stderr.log")
    result.artifacts.extend([str(stdout_path), str(stderr_path)])
    if dry_run:
        result.status = "DRY_RUN"
        result.note = command_text(command)
        return None, "", ""

    result.started_utc = utc_now()
    started = time.monotonic()
    try:
        cp = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        rc, out, err = cp.returncode, cp.stdout, cp.stderr
    except OSError as exc:
        rc, out, err = 127, "", f"execution failed: {exc}\n"
    result.return_code = rc
    result.elapsed_s = time.monotonic() - started
    stdout_path.write_text(out, encoding="utf-8")
    stderr_path.write_text(err, encoding="utf-8")
    return rc, out, err


def discover_modes(probe_text: str) -> dict[str, int]:
    modes: dict[str, int] = {}
    rx = re.compile(r"^\s*(\d+):\s+(\d+)x(\d+)@([0-9.]+)\s+(\S+)", re.MULTILINE)
    for match in rx.finditer(probe_text):
        index = int(match.group(1))
        width = int(match.group(2))
        height = int(match.group(3))
        transport = match.group(5).lower()
        if width == 4000 and height == 1200 and transport in {"mjpeg", "yuyv"}:
            modes.setdefault(transport, index)
    return modes


def parse_grab(text: str) -> list[dict[str, Any]]:
    rx = re.compile(
        r"frame sequence=(\d+)\s+bytes=(\d+)\s+host_ns=(\d+).*?"
        r"actual=(\d+)x(\d+)@([0-9.]+)\s+(\S+)"
    )
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = rx.search(line)
        if not match:
            continue
        rows.append({
            "sequence": int(match.group(1)),
            "bytes": int(match.group(2)),
            "host_ns": int(match.group(3)),
            "width": int(match.group(4)),
            "height": int(match.group(5)),
            "actual_fps": float(match.group(6)),
            "transport": match.group(7).lower(),
        })
    return rows


def pass_fail(result: TestResult, ok: bool, note: str = "") -> None:
    result.status = "PASS" if ok else "FAIL"
    if note:
        result.note = note


def test_probe(ctx: dict[str, Any], result: TestResult) -> None:
    rc, out, _ = run_command(
        result=result,
        command=[ctx["probe"]],
        log_prefix=ctx["session_dir"] / "A00_probe",
        dry_run=ctx["dry_run"],
    )
    if ctx["dry_run"]:
        return
    modes = discover_modes(out)
    ctx["discovered_modes"] = modes
    result.metrics = {"modes": modes, "device_lines": len(re.findall(r"^\[\d+\] ", out, re.MULTILINE))}
    pass_fail(result, rc == 0 and result.metrics["device_lines"] >= 1 and "mjpeg" in modes and "yuyv" in modes,
              "requires the delivered 4000x1200 MJPEG and YUYV modes")


def selected_mode(ctx: dict[str, Any], transport: str) -> int:
    explicit = ctx[f"{transport}_mode"]
    if explicit is not None:
        return explicit
    if transport in ctx.get("discovered_modes", {}):
        return int(ctx["discovered_modes"][transport])
    raise RuntimeError(f"cannot determine {transport} mode index; pass --{transport}-mode explicitly")


def run_grab_test(ctx: dict[str, Any], result: TestResult, transport: str, frames: int) -> list[dict[str, Any]]:
    mode = selected_mode(ctx, transport)
    command = [ctx["grab"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--frames", str(frames), "--timeout-ms", str(ctx["timeout_ms"])]
    rc, out, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / f"{result.test_id}_{transport}_grab",
        dry_run=ctx["dry_run"],
    )
    if ctx["dry_run"]:
        return []
    rows = parse_grab(out)
    seq = sequence_metrics([row["sequence"] for row in rows])
    sizes = [row["bytes"] for row in rows]
    result.metrics = {
        "mode_index": mode,
        "frames": len(rows),
        "sequence": seq,
        "bytes_min": min(sizes) if sizes else None,
        "bytes_max": max(sizes) if sizes else None,
        "actual_fps_last": rows[-1]["actual_fps"] if rows else None,
    }
    geometry_ok = all(row["width"] == 4000 and row["height"] == 1200 for row in rows)
    transport_ok = all(row["transport"] == transport for row in rows)
    size_ok = bool(sizes) and (all(size == 9_600_000 for size in sizes) if transport == "yuyv" else min(sizes) > 0)
    ok = (
        rc == 0 and len(rows) == frames and geometry_ok and transport_ok and size_ok and
        seq["missing"] == 0 and seq["duplicates"] == 0 and seq["out_of_order"] == 0
    )
    pass_fail(result, ok)
    return rows


def test_mjpeg_raw(ctx: dict[str, Any], result: TestResult) -> None:
    run_grab_test(ctx, result, "mjpeg", ctx["smoke_frames"])


def test_mjpeg_integrity(ctx: dict[str, Any], result: TestResult) -> None:
    mode = selected_mode(ctx, "mjpeg")
    dump_dir = ctx["session_dir"] / "A02_mjpeg_packets"
    dump_dir.mkdir(parents=True, exist_ok=True)
    command = [ctx["grab"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--frames", str(ctx["integrity_frames"]), "--timeout-ms", str(ctx["timeout_ms"]),
               "--dump-mjpeg-dir", str(dump_dir)]
    rc, out, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / "A02_mjpeg_dump",
        dry_run=ctx["dry_run"],
    )
    result.artifacts.append(str(dump_dir))
    if ctx["dry_run"]:
        return
    rows = parse_grab(out)
    scan_cmd = [sys.executable, str(ctx["jpeg_checker"]), str(dump_dir)]
    scan_result = TestResult("A02-scan", "internal JPEG scan", "support")
    scan_rc, scan_out, scan_err = run_command(
        result=scan_result,
        command=scan_cmd,
        log_prefix=ctx["session_dir"] / "A02_jpeg_integrity",
        dry_run=False,
    )
    result.artifacts.extend(scan_result.artifacts)
    match = re.search(
        r"summary:\s+files=(\d+)\s+clean=(\d+)\s+anomalies=(\d+)\s+DRI=\[([^]]*)\]\s+RST_counts=\[([^]]*)\]",
        scan_out,
    )
    metrics: dict[str, Any] = {"captured_frames": len(rows), "scanner_return_code": scan_rc}
    if match:
        metrics.update({
            "files": int(match.group(1)), "clean": int(match.group(2)), "anomalies": int(match.group(3)),
            "dri": match.group(4), "restart_counts": match.group(5),
        })
    result.metrics = metrics
    ok = (
        rc == 0 and scan_rc == 0 and match is not None and
        int(match.group(1)) == ctx["integrity_frames"] and int(match.group(3)) == 0
    )
    pass_fail(result, ok, scan_err.strip() if not ok and scan_err.strip() else "")


def test_mjpeg_pipeline(ctx: dict[str, Any], result: TestResult) -> None:
    mode = selected_mode(ctx, "mjpeg")
    command = [ctx["decode"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--frames", str(ctx["decode_frames"]), "--timeout-ms", str(ctx["timeout_ms"]),
               "--queue-depth", str(ctx["queue_depth"])]
    rc, out, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / "A03_mjpeg_pipeline",
        dry_run=ctx["dry_run"],
    )
    if ctx["dry_run"]:
        return
    summary = re.search(
        r"pipeline summary raw_frames=(\d+) decoded_frames=(\d+) timeouts=(\d+) "
        r"decode_errors=(\d+) queue_overflow_drops=(\d+) max_queue_occupancy=(\d+)/(\d+)", out)
    source = re.search(r"source observations=(\d+).*?missing=(\d+).*?duplicates=(\d+).*?out_of_order=(\d+)", out)
    decoded = re.search(r"decoded observations=(\d+).*?missing=(\d+).*?duplicates=(\d+).*?out_of_order=(\d+)", out)
    latency = re.search(r"decode_ms count=(\d+) min=([0-9.]+) p50=([0-9.]+) p95=([0-9.]+) p99=([0-9.]+) max=([0-9.]+) mean=([0-9.]+)", out)
    metrics: dict[str, Any] = {}
    if summary:
        metrics.update({
            "raw_frames": int(summary.group(1)), "decoded_frames": int(summary.group(2)),
            "timeouts": int(summary.group(3)), "decode_errors": int(summary.group(4)),
            "queue_overflow_drops": int(summary.group(5)), "max_queue_occupancy": int(summary.group(6)),
            "queue_depth": int(summary.group(7)),
        })
    if source:
        metrics["source"] = {"observations": int(source.group(1)), "missing": int(source.group(2)),
                             "duplicates": int(source.group(3)), "out_of_order": int(source.group(4))}
    if decoded:
        metrics["decoded"] = {"observations": int(decoded.group(1)), "missing": int(decoded.group(2)),
                              "duplicates": int(decoded.group(3)), "out_of_order": int(decoded.group(4))}
    if latency:
        metrics["decode_ms"] = {"count": int(latency.group(1)), "min": float(latency.group(2)),
                                "p50": float(latency.group(3)), "p95": float(latency.group(4)),
                                "p99": float(latency.group(5)), "max": float(latency.group(6)),
                                "mean": float(latency.group(7))}
    result.metrics = metrics
    ok = bool(summary and source and decoded) and rc == 0
    if ok:
        ok = (
            metrics["raw_frames"] == ctx["decode_frames"] == metrics["decoded_frames"] and
            metrics["timeouts"] == 0 and metrics["decode_errors"] == 0 and metrics["queue_overflow_drops"] == 0 and
            metrics["source"]["missing"] == 0 and metrics["source"]["duplicates"] == 0 and metrics["source"]["out_of_order"] == 0 and
            metrics["decoded"]["missing"] == 0 and metrics["decoded"]["duplicates"] == 0 and metrics["decoded"]["out_of_order"] == 0
        )
    pass_fail(result, ok)


def test_yuyv_raw(ctx: dict[str, Any], result: TestResult) -> None:
    run_grab_test(ctx, result, "yuyv", ctx["smoke_frames"])


def test_yuyv_decode(ctx: dict[str, Any], result: TestResult) -> None:
    mode = selected_mode(ctx, "yuyv")
    frames = ctx["yuyv_decode_frames"]
    command = [ctx["decode"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--frames", str(frames), "--timeout-ms", str(ctx["timeout_ms"])]
    rc, out, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / "A05_yuyv_decode",
        dry_run=ctx["dry_run"],
    )
    if ctx["dry_run"]:
        return
    rx = re.compile(
        r"frame sequence=(\d+) source=yuyv .*? ES=(\d+) EE=(\d+) exposure_us=(\d+) "
        r"imu_samples=(\d+) camera_a=(\d+)x(\d+) camera_b=(\d+)x(\d+)"
    )
    rows = [tuple(map(int, match.groups())) for match in rx.finditer(out)]
    seq = sequence_metrics([row[0] for row in rows])
    result.metrics = {
        "frames": len(rows), "sequence": seq,
        "exposure_us_values": sorted(set(row[3] for row in rows)),
        "imu_samples_per_frame": sorted(set(row[4] for row in rows)),
        "camera_a_geometries": sorted({f"{row[5]}x{row[6]}" for row in rows}),
        "camera_b_geometries": sorted({f"{row[7]}x{row[8]}" for row in rows}),
    }
    ok = (
        rc == 0 and len(rows) == frames and seq["missing"] == 0 and seq["duplicates"] == 0 and seq["out_of_order"] == 0 and
        all(row[3] > 0 and row[4] > 0 for row in rows) and
        all((row[5], row[6], row[7], row[8]) == (1920, 1200, 1920, 1200) for row in rows)
    )
    pass_fail(result, ok)


def test_imu_record(ctx: dict[str, Any], result: TestResult) -> None:
    mode = selected_mode(ctx, "mjpeg")
    prefix = ctx["session_dir"] / "A06_imu"
    command = [ctx["imu_record"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--duration-s", "30", "--frames", str(ctx["imu_frames"]), "--warmup-frames", "10",
               "--timeout-ms", str(ctx["timeout_ms"]), "--output-prefix", str(prefix)]
    rc, _, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / "A06_imu_record",
        dry_run=ctx["dry_run"],
    )
    json_path = Path(str(prefix) + ".json")
    csv_path = Path(str(prefix) + ".imu.csv")
    result.artifacts.extend([str(json_path), str(csv_path)])
    if ctx["dry_run"]:
        return
    try:
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        run = summary["run"]
        by_frame: dict[str, int] = {}
        invalid = 0
        imu_times: list[int] = []
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                by_frame[row["frame_sequence"]] = by_frame.get(row["frame_sequence"], 0) + 1
                invalid += 0 if row["sample_valid"].lower() == "true" else 1
                imu_times.append(int(row["imu_extended_time_us"]))
        counts = sorted(set(by_frame.values()))
        monotonic = all(b >= a for a, b in zip(imu_times, imu_times[1:]))
        result.metrics = {
            "decoded_frames": run["decoded_frames"], "imu_samples": run["imu_samples"],
            "valid_imu_samples": run["valid_imu_samples"], "timeouts": run["timeouts"],
            "decode_errors": run["decode_errors"], "samples_per_frame": counts,
            "invalid_samples": invalid, "imu_extended_time_monotonic_non_decreasing": monotonic,
        }
        ok = (
            rc == 0 and run["decoded_frames"] == ctx["imu_frames"] and run["decode_errors"] == 0 and
            run["timeouts"] == 0 and run["imu_samples"] > 0 and invalid == 0 and len(counts) == 1 and counts[0] > 0 and monotonic
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        ok = False
        result.note = f"artifact parse failed: {exc}"
    pass_fail(result, ok, result.note)


def test_calib_record(ctx: dict[str, Any], result: TestResult) -> None:
    mode = selected_mode(ctx, "mjpeg")
    out_dir = ctx["session_dir"] / "A07_calib_session"
    command = [ctx["calib_record"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--duration-s", "30", "--frames", str(ctx["calib_frames"]), "--warmup-frames", "10",
               "--frame-stride", str(ctx["calib_stride"]), "--png-compression", "1",
               "--timeout-ms", str(ctx["timeout_ms"]), "--output-dir", str(out_dir)]
    rc, _, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / "A07_calib_record",
        dry_run=ctx["dry_run"],
    )
    result.artifacts.append(str(out_dir))
    if ctx["dry_run"]:
        return
    a_png = sorted((out_dir / "camera_a").glob("*.png"))
    b_png = sorted((out_dir / "camera_b").glob("*.png"))
    frames_csv = out_dir / "frames.csv"
    imu_csv = out_dir / "imu.csv"
    capture_json = out_dir / "capture.json"
    try:
        with frames_csv.open(newline="", encoding="utf-8") as handle:
            frame_rows = list(csv.DictReader(handle))
        with imu_csv.open(newline="", encoding="utf-8") as handle:
            imu_rows = list(csv.DictReader(handle))
        json.loads(capture_json.read_text(encoding="utf-8"))
        nonempty_png = all(path.stat().st_size > 0 for path in a_png + b_png)
        result.metrics = {
            "camera_a_png": len(a_png), "camera_b_png": len(b_png),
            "frames_csv_rows": len(frame_rows), "imu_csv_rows": len(imu_rows),
            "nonempty_png": nonempty_png,
        }
        ok = rc == 0 and len(a_png) > 0 and len(a_png) == len(b_png) == len(frame_rows) and len(imu_rows) > 0 and nonempty_png
    except (OSError, json.JSONDecodeError) as exc:
        ok = False
        result.note = f"artifact parse failed: {exc}"
    pass_fail(result, ok, result.note)


def run_recovery_test(ctx: dict[str, Any], result: TestResult, kind: str) -> None:
    mode = selected_mode(ctx, "mjpeg")
    prefix = ctx["session_dir"] / f"{result.test_id}_{kind}"
    every = ctx["recovery_every_frames"]
    command = [ctx["characterize"], "--device", str(ctx["device"]), "--mode", str(mode),
               "--duration-s", str(ctx["recovery_duration_s"]), "--warmup-frames", "10",
               "--timeout-ms", str(ctx["timeout_ms"]), "--rss-sample-ms", "0",
               "--recovery-timeout-ms", "5000", "--output-prefix", str(prefix)]
    if kind == "stop_start":
        command += ["--stop-start-every-frames", str(every), "--stop-start-pause-ms", "250"]
    else:
        command += ["--reconnect-every-frames", str(every), "--reconnect-pause-ms", "500"]
    rc, _, _ = run_command(
        result=result,
        command=command,
        log_prefix=ctx["session_dir"] / f"{result.test_id}_{kind}_runner",
        dry_run=ctx["dry_run"],
    )
    events_path = Path(str(prefix) + ".events.csv")
    summary_path = Path(str(prefix) + ".json")
    result.artifacts.extend([str(events_path), str(summary_path)])
    if ctx["dry_run"]:
        return
    try:
        with events_path.open(newline="", encoding="utf-8") as handle:
            events = list(csv.DictReader(handle))
        operation_failures = [e for e in events if e["operation_succeeded"].lower() != "true"]
        recovery_failures = [e for e in events if e["recovered"].lower() != "true"]
        result.metrics = {
            "events": len(events), "operation_failures": len(operation_failures),
            "recovery_failures": len(recovery_failures),
            "recovery_ms": [float(e["recovery_ms"]) for e in events if e.get("recovery_ms")],
        }
        ok = rc == 0 and len(events) >= 1 and not operation_failures and not recovery_failures
    except (OSError, KeyError, ValueError) as exc:
        ok = False
        result.note = f"recovery artifact parse failed: {exc}"
    pass_fail(result, ok, result.note)


def test_stop_start(ctx: dict[str, Any], result: TestResult) -> None:
    run_recovery_test(ctx, result, "stop_start")


def test_reconnect(ctx: dict[str, Any], result: TestResult) -> None:
    run_recovery_test(ctx, result, "reconnect")


TEST_FUNCS: dict[str, Callable[[dict[str, Any], TestResult], None]] = {
    "A00": test_probe,
    "A01": test_mjpeg_raw,
    "A02": test_mjpeg_integrity,
    "A03": test_mjpeg_pipeline,
    "A04": test_yuyv_raw,
    "A05": test_yuyv_decode,
    "A06": test_imu_record,
    "A07": test_calib_record,
    "A08": test_stop_start,
    "A09": test_reconnect,
}


def load_manual(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": "bividi.ar0234.manual_checks.v1", "checks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"checks": {}}
    except (OSError, json.JSONDecodeError):
        return {"checks": {}}


def overall_status(results: Iterable[TestResult], manual: dict[str, Any]) -> str:
    automated = list(results)
    if any(r.status in {"FAIL", "ERROR"} for r in automated):
        return "FAIL"
    if any(r.status not in {"PASS"} for r in automated):
        return "INCOMPLETE"
    checks = manual.get("checks", {}) if isinstance(manual, dict) else {}
    for test_id in MANUAL_TESTS:
        status = str(checks.get(test_id, {}).get("status", "PENDING")).upper()
        if status == "FAIL":
            return "FAIL"
        if status not in {"PASS", "N/A"}:
            return "INCOMPLETE"
    return "PASS"


def render_report(payload: dict[str, Any], manual: dict[str, Any] | None = None) -> str:
    manual = manual or {"checks": {}}
    results = [TestResult(**item) for item in payload.get("automated_results", [])]
    overall = overall_status(results, manual)
    lines = [
        "# DECXIN AR0234 Feature Qualification Report",
        "",
        f"- Session: `{payload.get('session_id', 'unknown')}`",
        f"- Created: `{payload.get('created_utc', 'unknown')}`",
        f"- Git revision: `{payload.get('repository', {}).get('git_revision') or 'unknown'}`",
        f"- Host: `{payload.get('host', {}).get('hostname', 'unknown')}` / `{payload.get('host', {}).get('platform', 'unknown')}`",
        f"- Functional overall: **{overall}**",
        "- Long-duration stability: **DEFERRED by test order**",
        "",
        "## Automated functional checks",
        "",
        "| ID | Test | Status | Key evidence |",
        "|---|---|---|---|",
    ]
    by_id = {r.test_id: r for r in results}
    for test_id, name in AUTOMATED_TESTS.items():
        r = by_id.get(test_id, TestResult(test_id, name, "automated"))
        key = []
        if r.metrics:
            for k, v in list(r.metrics.items())[:4]:
                if isinstance(v, (dict, list)):
                    key.append(f"{k}={json.dumps(v, separators=(',', ':'))[:120]}")
                else:
                    key.append(f"{k}={v}")
        if r.note:
            key.append(r.note)
        lines.append(f"| {test_id} | {name} | **{r.status}** | {'; '.join(key).replace('|', '/') or '-'} |")

    checks = manual.get("checks", {}) if isinstance(manual, dict) else {}
    lines += [
        "",
        "## Operator-assisted / physical checks",
        "",
        "These remain first-class tests. They are not silently treated as PASS when software cannot perform the physical observation.",
        "",
        "| ID | Test | Status | Note |",
        "|---|---|---|---|",
    ]
    for test_id, name in MANUAL_TESTS.items():
        entry = checks.get(test_id, {}) if isinstance(checks, dict) else {}
        status = str(entry.get("status", "PENDING")).upper()
        note = str(entry.get("note", "")).replace("|", "/")
        lines.append(f"| {test_id} | {name} | **{status}** | {note or '-'} |")

    lines += [
        "",
        "## Deferred stability phase",
        "",
        "| ID | Test | Status |",
        "|---|---|---|",
    ]
    for test_id, name in DEFERRED_TESTS.items():
        lines.append(f"| {test_id} | {name} | **DEFERRED** |")

    lines += [
        "",
        "## Interpretation boundary",
        "",
        "- Functional PASS means the exercised interface behaved correctly in this bounded test; it is not a long-run reliability claim.",
        "- Host arrival timing does not replace embedded ES/EE/IMU device timing.",
        "- Camera A/B identity is not promoted to stereo left/right until M01 is physically established and calibration conventions are frozen.",
        "- Q2/Q3 stability runs are intentionally deferred until the functional matrix is complete.",
        "",
    ]
    return "\n".join(lines)


def write_payload(session_dir: Path, payload: dict[str, Any]) -> None:
    path = session_dir / "feature-results.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manual = load_manual(session_dir / "manual-results.json")
    (session_dir / "report.md").write_text(render_report(payload, manual), encoding="utf-8")


def self_test() -> int:
    seq = sequence_metrics([1, 2, 4, 4, 3])
    assert seq["gap_events"] == 1 and seq["missing"] == 1
    assert seq["duplicates"] == 1 and seq["out_of_order"] == 1
    probe = """[0] DECXIN Camera\n  modes: 2\n    0: 4000x1200@60  mjpeg  raw=0x47504a4d\n    1: 4000x1200@30  yuyv  raw=0x32595559\n"""
    assert discover_modes(probe) == {"mjpeg": 0, "yuyv": 1}
    grab = "frame sequence=1 bytes=9600000 host_ns=1 sdk_time=x actual=4000x1200@0 yuyv\n"
    rows = parse_grab(grab)
    assert rows[0]["bytes"] == 9_600_000 and rows[0]["transport"] == "yuyv"
    payload = {
        "session_id": "self-test", "created_utc": utc_now(),
        "repository": {"git_revision": "deadbeef"},
        "host": {"hostname": "test", "platform": "test"},
        "automated_results": [asdict(TestResult(test_id, name, "automated", "PASS")) for test_id, name in AUTOMATED_TESTS.items()],
    }
    report = render_report(payload, {"checks": {k: {"status": "PASS"} for k in MANUAL_TESTS}})
    assert "Functional overall: **PASS**" in report
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        write_payload(root, payload)
        assert (root / "feature-results.json").exists() and (root / "report.md").exists()
    print("AR0234 feature qualification self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run feature-first DECXIN AR0234/Nori physical qualification.")
    p.add_argument("--build-dir", default="build-nori-opencv/Release",
                   help="directory containing bividi-nori-* executables")
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--mjpeg-mode", type=int)
    p.add_argument("--yuyv-mode", type=int)
    p.add_argument("--tests", type=parse_test_selection, default=list(AUTOMATED_TESTS),
                   help="automated IDs, comma-separated; default: all")
    p.add_argument("--smoke-frames", type=int, default=60)
    p.add_argument("--integrity-frames", type=int, default=120)
    p.add_argument("--decode-frames", type=int, default=600)
    p.add_argument("--yuyv-decode-frames", type=int, default=30)
    p.add_argument("--imu-frames", type=int, default=120)
    p.add_argument("--calib-frames", type=int, default=10)
    p.add_argument("--calib-stride", type=int, default=2)
    p.add_argument("--queue-depth", type=int, default=256)
    p.add_argument("--timeout-ms", type=int, default=2000)
    p.add_argument("--recovery-duration-s", type=float, default=8.0)
    p.add_argument("--recovery-every-frames", type=int, default=120)
    p.add_argument("--output-dir", default="artifacts/physical/nori/feature-qualification")
    p.add_argument("--session-id", default=default_session_id())
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list-tests", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if args.list_tests:
        for title, catalog in (("automated", AUTOMATED_TESTS), ("manual", MANUAL_TESTS), ("deferred stability", DEFERRED_TESTS)):
            print(f"[{title}]")
            for test_id, name in catalog.items():
                print(f"  {test_id}  {name}")
        return 0

    build_dir = Path(args.build_dir)
    session_dir = Path(args.output_dir) / safe_token(args.session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent
    ctx: dict[str, Any] = {
        "session_dir": session_dir,
        "dry_run": args.dry_run,
        "device": args.device,
        "mjpeg_mode": args.mjpeg_mode,
        "yuyv_mode": args.yuyv_mode,
        "smoke_frames": args.smoke_frames,
        "integrity_frames": args.integrity_frames,
        "decode_frames": args.decode_frames,
        "yuyv_decode_frames": args.yuyv_decode_frames,
        "imu_frames": args.imu_frames,
        "calib_frames": args.calib_frames,
        "calib_stride": args.calib_stride,
        "queue_depth": args.queue_depth,
        "timeout_ms": args.timeout_ms,
        "recovery_duration_s": args.recovery_duration_s,
        "recovery_every_frames": args.recovery_every_frames,
        "discovered_modes": {},
        "jpeg_checker": repo_root / "tools" / "check_jpeg_restart_integrity.py",
    }
    for key, base in {
        "probe": "bividi-nori-probe", "grab": "bividi-nori-grab", "decode": "bividi-nori-decode",
        "imu_record": "bividi-nori-imu-record", "calib_record": "bividi-nori-calib-record",
        "characterize": "bividi-nori-characterize",
    }.items():
        ctx[key] = str((build_dir / exe_name(base)).resolve())

    selected = list(args.tests)
    if any(test_id != "A00" for test_id in selected) and "A00" not in selected:
        selected.insert(0, "A00")

    created = utc_now()
    results: list[TestResult] = []
    for test_id, name in AUTOMATED_TESTS.items():
        result = TestResult(test_id, name, "automated")
        if test_id not in selected:
            result.status = "NOT_RUN"
            results.append(result)
            continue
        print(f"[{test_id}] {name}")
        try:
            TEST_FUNCS[test_id](ctx, result)
        except Exception as exc:  # runner must preserve later evidence when requested
            result.status = "ERROR"
            result.note = f"{type(exc).__name__}: {exc}"
        results.append(result)
        print(f"  -> {result.status}")
        if result.status in {"FAIL", "ERROR"} and not args.continue_on_failure:
            print("stopping on first failure; use --continue-on-failure to collect later evidence")
            break

    # Preserve catalog rows that were not reached because execution stopped early.
    have = {r.test_id for r in results}
    for test_id, name in AUTOMATED_TESTS.items():
        if test_id not in have:
            results.append(TestResult(test_id, name, "automated", "NOT_RUN", note="not reached after earlier failure"))
    results.sort(key=lambda r: list(AUTOMATED_TESTS).index(r.test_id))

    payload = {
        "schema": SCHEMA,
        "session_id": args.session_id,
        "created_utc": created,
        "updated_utc": utc_now(),
        "host": {
            "hostname": socket.gethostname(), "platform": platform.platform(),
            "system": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
        },
        "repository": {"git_revision": git_revision()},
        "selection": {
            "device": args.device, "mjpeg_mode": args.mjpeg_mode, "yuyv_mode": args.yuyv_mode,
            "discovered_modes": ctx.get("discovered_modes", {}), "tests": selected,
        },
        "settings": {
            "build_dir": str(build_dir), "smoke_frames": args.smoke_frames,
            "integrity_frames": args.integrity_frames, "decode_frames": args.decode_frames,
            "queue_depth": args.queue_depth, "timeout_ms": args.timeout_ms,
        },
        "automated_results": [asdict(r) for r in results],
        "manual_catalog": MANUAL_TESTS,
        "deferred_stability_catalog": DEFERRED_TESTS,
        "session_directory": str(session_dir),
    }
    write_payload(session_dir, payload)
    manual = load_manual(session_dir / "manual-results.json")
    overall = overall_status(results, manual)
    print(f"feature report: {session_dir / 'report.md'}")
    print(f"machine result: {session_dir / 'feature-results.json'}")
    print(f"functional overall: {overall}")
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
