#!/usr/bin/env python3
"""Import a lossless #35/Nori calibration recording into the #8 stereo session contract.

This module is intentionally dependency-free. It preserves the recorder's frame
sequence and device/exposure timing metadata instead of rebuilding a measured
session from image filenames alone.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

from stereo_calibration_common import Error, SESSION, TARGET, load, now, rel, save, sha

RECORDER_SCHEMA = "bividi.nori.camera_imu_dynamic_trace.v1"
TOOL_VERSION = "1"


def png_size(path: Path) -> tuple[int, int]:
    try:
        data = path.read_bytes()[:24]
    except OSError as exc:
        raise Error(f"cannot read PNG header {path}: {exc}") from exc
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise Error(f"invalid PNG header: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise Error(f"invalid PNG geometry: {path}")
    return int(width), int(height)


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key)
    if value is None or value == "":
        raise Error(f"frames.csv missing required value {key!r}")
    return value


def _u64(row: dict[str, str], key: str) -> int:
    try:
        value = int(_required(row, key), 10)
    except ValueError as exc:
        raise Error(f"frames.csv invalid integer {key!r}: {row.get(key)!r}") from exc
    if value < 0:
        raise Error(f"frames.csv negative integer {key!r}: {value}")
    return value


def session_from_recorder(args) -> dict:
    root = args.recorder_dir.resolve()
    capture_path = root / "capture.json"
    frames_path = root / "frames.csv"
    if not capture_path.is_file() or not frames_path.is_file():
        raise Error("recorder directory must contain capture.json and frames.csv")

    capture = load(capture_path)
    if capture.get("schema") != RECORDER_SCHEMA:
        raise Error(f"capture.json must use {RECORDER_SCHEMA}")

    target_path = args.target.resolve()
    target = load(target_path)
    if target.get("schema") != TARGET:
        raise Error("target schema mismatch")

    device = capture.get("device")
    mode = capture.get("mode")
    if not isinstance(device, dict) or not isinstance(mode, dict):
        raise Error("capture.json missing device/mode provenance")
    serial = str(device.get("serial", "")).strip()
    if not serial:
        raise Error("capture.json does not contain a non-empty device serial")

    output = args.output.resolve()
    pairs: list[dict] = []
    geometry: tuple[int, int] | None = None
    with frames_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {
            "frame_index", "frame_sequence", "host_receive_monotonic_ns",
            "sdk_timestamp_encoding", "sdk_seconds", "sdk_microseconds",
            "sdk_filetime_100ns", "exposure_start_raw_us", "exposure_end_raw_us",
            "exposure_start_extended_us", "exposure_end_extended_us",
            "camera_a_path", "camera_b_path",
        }
        if reader.fieldnames is None or not required_columns.issubset(set(reader.fieldnames)):
            missing = sorted(required_columns - set(reader.fieldnames or []))
            raise Error("frames.csv missing columns: " + ", ".join(missing))
        for index, row in enumerate(reader):
            camera_a = (root / _required(row, "camera_a_path")).resolve()
            camera_b = (root / _required(row, "camera_b_path")).resolve()
            if not camera_a.is_file() or not camera_b.is_file():
                raise Error(f"missing recorded stereo pair: {camera_a} / {camera_b}")
            size_a = png_size(camera_a)
            size_b = png_size(camera_b)
            if size_a != size_b:
                raise Error(f"stereo PNG geometry mismatch: {camera_a}={size_a}, {camera_b}={size_b}")
            if geometry is None:
                geometry = size_a
            elif size_a != geometry:
                raise Error(f"recorded PNG geometry changed within one session: {size_a} != {geometry}")
            frame_index = _u64(row, "frame_index")
            pairs.append({
                "pair_id": f"pair-{index:06d}",
                "source_frame_index": frame_index,
                "frame_sequence": _u64(row, "frame_sequence"),
                "host_receive_monotonic_ns": _u64(row, "host_receive_monotonic_ns"),
                "sdk_timestamp": {
                    "encoding": _required(row, "sdk_timestamp_encoding"),
                    "seconds": _u64(row, "sdk_seconds"),
                    "microseconds": _u64(row, "sdk_microseconds"),
                    "filetime_100ns": _u64(row, "sdk_filetime_100ns"),
                },
                "exposure_start_raw_us": _u64(row, "exposure_start_raw_us"),
                "exposure_end_raw_us": _u64(row, "exposure_end_raw_us"),
                "exposure_start_extended_us": _u64(row, "exposure_start_extended_us"),
                "exposure_end_extended_us": _u64(row, "exposure_end_extended_us"),
                "camera_a": rel(camera_a, output),
                "camera_b": rel(camera_b, output),
                "camera_a_sha256": sha(camera_a),
                "camera_b_sha256": sha(camera_b),
            })
    if not pairs or geometry is None:
        raise Error("frames.csv contains no recorded stereo image pairs")

    width, height = geometry
    result = {
        "schema": SESSION,
        "session_id": args.session_id,
        "created_utc": now(),
        "provenance": {
            "kind": "measured",
            "tool": Path(__file__).name,
            "tool_version": TOOL_VERSION,
        },
        "device": {
            "model": args.model,
            "serial": serial,
            "vendor_id": device.get("vendor_id"),
            "product_id": device.get("product_id"),
            "product": device.get("product"),
            "sdk_version": device.get("sdk_version"),
            "device_type": device.get("device_type"),
            "isp_version": device.get("isp_version"),
            "fpga_version": device.get("fpga_version"),
        },
        "capture": {
            "device_index": device.get("index"),
            "mode_index": mode.get("index"),
            "pixel_format": "mono8_png",
            "source_transport": mode.get("transport"),
            "nominal_fps": mode.get("nominal_fps"),
            "width": width,
            "height": height,
            "camera_a_identity": "camera_a",
            "camera_b_identity": "camera_b",
            "camera_mapping_evidence": args.camera_mapping_evidence,
        },
        "target": {
            "path": rel(target_path, output),
            "sha256": sha(target_path),
            "target_id": target.get("target_id"),
        },
        "source_trace": {
            "kind": "bividi-nori-calib-record",
            "artifacts": [
                {
                    "role": "capture_manifest",
                    "path": rel(capture_path, output),
                    "sha256": sha(capture_path),
                    "schema": RECORDER_SCHEMA,
                },
                {
                    "role": "frames_csv",
                    "path": rel(frames_path, output),
                    "sha256": sha(frames_path),
                },
            ],
        },
        "pairs": pairs,
    }
    save(output, result)
    return result


def _fake_png(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height))


def recorder_self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rec = root / "recording"
        rec.mkdir()
        _fake_png(rec / "camera_a" / "0000000000.png", 640, 480)
        _fake_png(rec / "camera_b" / "0000000000.png", 640, 480)
        (rec / "capture.json").write_text(json.dumps({
            "schema": RECORDER_SCHEMA,
            "device": {"index": 0, "serial": "SER1", "product": "Nori", "vendor_id": 1, "product_id": 2},
            "mode": {"index": 3, "nominal_fps": 60, "transport": "MJPEG"},
        }), encoding="utf-8")
        fields = [
            "frame_index", "frame_sequence", "host_receive_monotonic_ns", "sdk_timestamp_encoding",
            "sdk_seconds", "sdk_microseconds", "sdk_filetime_100ns", "exposure_start_raw_us",
            "exposure_end_raw_us", "exposure_start_extended_us", "exposure_end_extended_us",
            "camera_a_path", "camera_b_path",
        ]
        with (rec / "frames.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({
                "frame_index": 0, "frame_sequence": 42, "host_receive_monotonic_ns": 123,
                "sdk_timestamp_encoding": "seconds_microseconds", "sdk_seconds": 1,
                "sdk_microseconds": 2, "sdk_filetime_100ns": 0, "exposure_start_raw_us": 100,
                "exposure_end_raw_us": 110, "exposure_start_extended_us": 100,
                "exposure_end_extended_us": 110, "camera_a_path": "camera_a/0000000000.png",
                "camera_b_path": "camera_b/0000000000.png",
            })
        target = root / "target.json"
        target.write_text(json.dumps({"schema": TARGET, "target_id": "t", "family": "charuco"}), encoding="utf-8")
        out = root / "session.json"
        session = session_from_recorder(SimpleNamespace(
            recorder_dir=rec, target=target, output=out, session_id="s", model="DECXIN-AR0234",
            camera_mapping_evidence="#35 physical mapping",
        ))
        assert session["pairs"][0]["frame_sequence"] == 42
        assert session["pairs"][0]["exposure_end_extended_us"] == 110
        assert session["capture"]["width"] == 640 and session["capture"]["height"] == 480
        assert len(session["pairs"][0]["camera_a_sha256"]) == 64
        assert len(session["source_trace"]["artifacts"]) == 2
