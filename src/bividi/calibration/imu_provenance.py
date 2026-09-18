#!/usr/bin/env python3
"""Build and verify Bividi IMU calibration-session provenance manifests.

This tool prevents accidental mixing of calibration evidence captured with
incompatible device/firmware/mode/IMU settings. It is dependency-free so the
provenance gate can run in normal Linux/Windows CI.

The gate does not prove that operator-declared IMU register settings are true.
It makes those settings explicit, binds every capture/report by SHA-256, checks
Nori recorder summaries for device/mode consistency, and can enforce the full
stationary/Allan/six-position/gyro-rotation evidence set before promotion.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

MANIFEST_SCHEMA = "bividi.calibration.imu_session_manifest.v1"
RECORDER_SCHEMA = "bividi.nori.imu_trace.v1"
TOOL_VERSION = "1"

PLACEHOLDERS = {"", "unknown", "n/a", "na", "tbd", "unset", "none", "?"}

FULL_CAPTURE_ROLES = {
    "stationary",
    "allan_stationary",
    "sixpos_plus_x",
    "sixpos_minus_x",
    "sixpos_plus_y",
    "sixpos_minus_y",
    "sixpos_plus_z",
    "sixpos_minus_z",
    "gyro_stationary",
    "gyro_plus_x",
    "gyro_minus_x",
    "gyro_plus_y",
    "gyro_minus_y",
    "gyro_plus_z",
    "gyro_minus_z",
}

EXPECTED_ANALYSIS_SCHEMAS = {
    "stationary": "bividi.calibration.imu_stationary_analysis.v1",
    "allan": "bividi.calibration.imu_allan_analysis.v1",
    "six_position": "bividi.calibration.imu_six_position_analysis.v1",
    "gyro_rotation": "bividi.calibration.imu_gyro_rotation_analysis.v1",
    "timing_audit": "bividi.calibration.camera_imu_timing_audit.v1",
}
FULL_ANALYSIS_ROLES = {"stationary", "allan", "six_position", "gyro_rotation"}


class ManifestError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def placeholder(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{path}: expected a JSON object")
    return value


def parse_role_path(text: str, option: str) -> tuple[str, Path]:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"{option} must use ROLE=PATH")
    role, raw_path = text.split("=", 1)
    role = role.strip()
    raw_path = raw_path.strip()
    if not role or not raw_path:
        raise argparse.ArgumentTypeError(f"{option} must use non-empty ROLE=PATH")
    return role, Path(raw_path)


def manifest_relpath(path: Path, manifest_path: Path) -> str:
    absolute = path.resolve()
    base = manifest_path.parent.resolve()
    try:
        return os.path.relpath(absolute, base).replace(os.sep, "/")
    except ValueError:
        return str(absolute).replace(os.sep, "/")


def resolve_manifest_path(text: str, manifest_path: Path, base_dir: Path | None) -> Path:
    path = Path(text)
    if path.is_absolute():
        return path
    if base_dir is not None:
        return (base_dir / path).resolve()
    return (manifest_path.parent / path).resolve()


def resolve_trace_from_summary(summary_path: Path, artifact: Any) -> Path:
    if not nonempty_string(artifact):
        raise ManifestError(f"{summary_path}: recorder summary has no artifact path")
    raw = Path(str(artifact))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend([
            raw,
            summary_path.parent / raw,
            summary_path.parent / raw.name,
        ])
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate.resolve()
    rendered = ", ".join(str(path) for path in candidates)
    raise ManifestError(f"{summary_path}: referenced trace does not exist; tried: {rendered}")


def observed_device(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    device = summary.get("device")
    if not isinstance(device, dict):
        raise ManifestError(f"{summary_path}: recorder summary has no device object")
    keys = ("serial", "sdk_version", "device_type", "isp_version", "fpga_version")
    result: dict[str, Any] = {}
    for key in keys:
        value = device.get(key)
        if not nonempty_string(value):
            raise ManifestError(f"{summary_path}: device.{key} is missing/empty")
        result[key] = value
    return result


def observed_mode(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    mode = summary.get("mode")
    if not isinstance(mode, dict):
        raise ManifestError(f"{summary_path}: recorder summary has no mode object")
    result = {
        "index": mode.get("index"),
        "width": mode.get("width"),
        "height": mode.get("height"),
        "nominal_fps": mode.get("nominal_fps"),
        "transport": mode.get("transport"),
    }
    for key in ("index", "width", "height"):
        value = result[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < (0 if key == "index" else 1):
            raise ManifestError(f"{summary_path}: mode.{key} is invalid")
    if not is_number(result["nominal_fps"]) or float(result["nominal_fps"]) <= 0.0:
        raise ManifestError(f"{summary_path}: mode.nominal_fps is invalid")
    if not nonempty_string(result["transport"]):
        raise ManifestError(f"{summary_path}: mode.transport is missing/empty")
    return result


def capture_from_summary(role: str, summary_path: Path, manifest_path: Path) -> dict[str, Any]:
    if not summary_path.is_file():
        raise ManifestError(f"capture summary does not exist: {summary_path}")
    summary = load_json(summary_path)
    if summary.get("schema") != RECORDER_SCHEMA:
        raise ManifestError(
            f"{summary_path}: expected recorder schema {RECORDER_SCHEMA!r}, observed {summary.get('schema')!r}"
        )
    trace_path = resolve_trace_from_summary(summary_path, summary.get("artifact"))
    return {
        "role": role,
        "summary_path": manifest_relpath(summary_path, manifest_path),
        "summary_sha256": sha256_file(summary_path),
        "summary_bytes": summary_path.stat().st_size,
        "summary_schema": RECORDER_SCHEMA,
        "trace_path": manifest_relpath(trace_path, manifest_path),
        "trace_sha256": sha256_file(trace_path),
        "trace_bytes": trace_path.stat().st_size,
        "observed_device": observed_device(summary, summary_path),
        "observed_mode": observed_mode(summary, summary_path),
    }


def analysis_from_json(role: str, path: Path, manifest_path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"analysis JSON does not exist: {path}")
    data = load_json(path)
    schema = data.get("schema")
    if not nonempty_string(schema):
        raise ManifestError(f"{path}: analysis report has no non-empty schema")
    expected = EXPECTED_ANALYSIS_SCHEMAS.get(role)
    if expected is not None and schema != expected:
        raise ManifestError(f"{path}: role {role!r} requires schema {expected!r}, observed {schema!r}")
    return {
        "role": role,
        "path": manifest_relpath(path, manifest_path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "schema": schema,
    }


def require_unique_roles(entries: Sequence[dict[str, Any]], label: str) -> None:
    seen: set[str] = set()
    for entry in entries:
        role = entry.get("role")
        if role in seen:
            raise ManifestError(f"duplicate {label} role: {role}")
        seen.add(str(role))


def assert_capture_consistency(captures: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not captures:
        raise ManifestError("at least one capture is required")
    reference_device = captures[0]["observed_device"]
    reference_mode = captures[0]["observed_mode"]
    for capture in captures[1:]:
        role = capture["role"]
        if capture["observed_device"] != reference_device:
            raise ManifestError(
                f"capture {role!r} device provenance differs from the first capture; do not mix specimens/firmware/SDK"
            )
        if capture["observed_mode"] != reference_mode:
            raise ManifestError(
                f"capture {role!r} camera mode differs from the first capture; split the calibration session"
            )
    return dict(reference_device), dict(reference_mode)


def validate_structure(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_top = {
        "schema", "session_id", "created_utc", "device", "imu_configuration", "camera_mode",
        "captures", "analysis", "quality", "provenance",
    }
    unknown = sorted(set(data) - allowed_top)
    if unknown:
        errors.append("unknown top-level field(s): " + ", ".join(unknown))
    if data.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"schema must be {MANIFEST_SCHEMA!r}")
    if not nonempty_string(data.get("session_id")):
        errors.append("session_id must be a non-empty string")
    created = data.get("created_utc")
    if not nonempty_string(created):
        errors.append("created_utc must be a non-empty ISO-8601 date-time")
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                errors.append("created_utc must include timezone/UTC offset")
        except ValueError:
            errors.append("created_utc is not valid ISO-8601")

    device = data.get("device")
    device_keys = {"model", "serial", "sdk_version", "device_type", "isp_version", "fpga_version"}
    if not isinstance(device, dict):
        errors.append("device must be an object")
    else:
        extra = sorted(set(device) - device_keys)
        if extra:
            errors.append("device has unknown field(s): " + ", ".join(extra))
        for key in device_keys:
            if not nonempty_string(device.get(key)):
                errors.append(f"device.{key} must be a non-empty string")

    imu = data.get("imu_configuration")
    imu_keys = {
        "model", "frame", "accelerometer_range_g", "gyroscope_range_dps", "output_data_rate_hz",
        "accelerometer_filter", "gyroscope_filter", "configuration_source", "notes",
    }
    if not isinstance(imu, dict):
        errors.append("imu_configuration must be an object")
    else:
        extra = sorted(set(imu) - imu_keys)
        if extra:
            errors.append("imu_configuration has unknown field(s): " + ", ".join(extra))
        for key in ("model", "frame", "accelerometer_filter", "gyroscope_filter", "configuration_source"):
            if not nonempty_string(imu.get(key)):
                errors.append(f"imu_configuration.{key} must be a non-empty string")
        for key in ("accelerometer_range_g", "gyroscope_range_dps", "output_data_rate_hz"):
            if not is_number(imu.get(key)) or float(imu[key]) <= 0.0:
                errors.append(f"imu_configuration.{key} must be finite and > 0")
        if "notes" in imu and (
            not isinstance(imu["notes"], list) or not all(isinstance(item, str) for item in imu["notes"])
        ):
            errors.append("imu_configuration.notes must be an array of strings")

    mode = data.get("camera_mode")
    if mode is not None:
        expected_mode_keys = {"index", "width", "height", "nominal_fps", "transport"}
        if not isinstance(mode, dict):
            errors.append("camera_mode must be an object")
        else:
            extra = sorted(set(mode) - expected_mode_keys)
            if extra:
                errors.append("camera_mode has unknown field(s): " + ", ".join(extra))
            for key in ("index", "width", "height"):
                value = mode.get(key)
                minimum = 0 if key == "index" else 1
                if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                    errors.append(f"camera_mode.{key} is invalid")
            if not is_number(mode.get("nominal_fps")) or float(mode["nominal_fps"]) <= 0.0:
                errors.append("camera_mode.nominal_fps must be finite and > 0")
            if not nonempty_string(mode.get("transport")):
                errors.append("camera_mode.transport must be a non-empty string")

    captures = data.get("captures")
    if not isinstance(captures, list) or not captures:
        errors.append("captures must be a non-empty array")
        captures = []
    capture_roles: set[str] = set()
    for index, capture in enumerate(captures):
        prefix = f"captures[{index}]"
        if not isinstance(capture, dict):
            errors.append(f"{prefix} must be an object")
            continue
        role = capture.get("role")
        if not nonempty_string(role):
            errors.append(f"{prefix}.role must be a non-empty string")
        elif role in capture_roles:
            errors.append(f"duplicate capture role {role!r}")
        else:
            capture_roles.add(str(role))
        for key in ("summary_path", "summary_sha256", "summary_schema", "trace_path", "trace_sha256"):
            if not nonempty_string(capture.get(key)):
                errors.append(f"{prefix}.{key} must be a non-empty string")
        for key in ("summary_sha256", "trace_sha256"):
            value = capture.get(key)
            if isinstance(value, str) and (len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)):
                errors.append(f"{prefix}.{key} must be lowercase SHA-256 hex")
        for key in ("summary_bytes", "trace_bytes"):
            value = capture.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"{prefix}.{key} must be a positive integer")
        if capture.get("summary_schema") != RECORDER_SCHEMA:
            errors.append(f"{prefix}.summary_schema must be {RECORDER_SCHEMA!r}")
        if not isinstance(capture.get("observed_device"), dict):
            errors.append(f"{prefix}.observed_device must be an object")
        if not isinstance(capture.get("observed_mode"), dict):
            errors.append(f"{prefix}.observed_mode must be an object")

    analysis = data.get("analysis")
    if not isinstance(analysis, list):
        errors.append("analysis must be an array")
        analysis = []
    analysis_roles: set[str] = set()
    for index, item in enumerate(analysis):
        prefix = f"analysis[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        role = item.get("role")
        if not nonempty_string(role):
            errors.append(f"{prefix}.role must be a non-empty string")
        elif role in analysis_roles:
            errors.append(f"duplicate analysis role {role!r}")
        else:
            analysis_roles.add(str(role))
        for key in ("path", "sha256", "schema"):
            if not nonempty_string(item.get(key)):
                errors.append(f"{prefix}.{key} must be a non-empty string")
        value = item.get("sha256")
        if isinstance(value, str) and (len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)):
            errors.append(f"{prefix}.sha256 must be lowercase SHA-256 hex")
        if not isinstance(item.get("bytes"), int) or isinstance(item.get("bytes"), bool) or item.get("bytes", 0) < 1:
            errors.append(f"{prefix}.bytes must be a positive integer")
        expected = EXPECTED_ANALYSIS_SCHEMAS.get(str(role))
        if expected is not None and item.get("schema") != expected:
            errors.append(f"{prefix}.schema for role {role!r} must be {expected!r}")

    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
    else:
        if provenance.get("kind") not in {"synthetic", "measured"}:
            errors.append("provenance.kind must be 'synthetic' or 'measured'")
        if not nonempty_string(provenance.get("tool")):
            errors.append("provenance.tool must be a non-empty string")

    return errors


def validate_cross_consistency(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    captures = data.get("captures")
    if not isinstance(captures, list) or not captures:
        return errors
    expected_device = data.get("device") if isinstance(data.get("device"), dict) else {}
    expected_mode = data.get("camera_mode") if isinstance(data.get("camera_mode"), dict) else None
    reference_observed_device = captures[0].get("observed_device")
    reference_observed_mode = captures[0].get("observed_mode")
    for capture in captures:
        role = capture.get("role", "?")
        observed_device_value = capture.get("observed_device")
        observed_mode_value = capture.get("observed_mode")
        if observed_device_value != reference_observed_device:
            errors.append(f"capture {role!r} observed device provenance differs from the first capture")
        if observed_mode_value != reference_observed_mode:
            errors.append(f"capture {role!r} observed camera mode differs from the first capture")
        if isinstance(observed_device_value, dict):
            for key in ("serial", "sdk_version", "device_type", "isp_version", "fpga_version"):
                if expected_device.get(key) != observed_device_value.get(key):
                    errors.append(f"capture {role!r} observed_device.{key} differs from manifest device.{key}")
        if expected_mode is not None and observed_mode_value != expected_mode:
            errors.append(f"capture {role!r} observed_mode differs from manifest camera_mode")
    return errors


def validate_files(data: dict[str, Any], manifest_path: Path, base_dir: Path | None) -> list[str]:
    errors: list[str] = []
    for capture in data.get("captures", []):
        role = capture.get("role", "?")
        for prefix in ("summary", "trace"):
            path = resolve_manifest_path(str(capture.get(f"{prefix}_path", "")), manifest_path, base_dir)
            if not path.is_file():
                errors.append(f"capture {role!r} {prefix} file missing: {path}")
                continue
            expected_bytes = capture.get(f"{prefix}_bytes")
            if path.stat().st_size != expected_bytes:
                errors.append(
                    f"capture {role!r} {prefix} size changed: expected {expected_bytes}, observed {path.stat().st_size}"
                )
            expected_hash = capture.get(f"{prefix}_sha256")
            observed_hash = sha256_file(path)
            if observed_hash != expected_hash:
                errors.append(
                    f"capture {role!r} {prefix} SHA-256 mismatch: expected {expected_hash}, observed {observed_hash}"
                )
            if prefix == "summary":
                try:
                    summary = load_json(path)
                    if summary.get("schema") != RECORDER_SCHEMA:
                        errors.append(f"capture {role!r} summary schema changed/invalid")
                    if observed_device(summary, path) != capture.get("observed_device"):
                        errors.append(f"capture {role!r} summary device provenance no longer matches manifest")
                    if observed_mode(summary, path) != capture.get("observed_mode"):
                        errors.append(f"capture {role!r} summary camera mode no longer matches manifest")
                except ManifestError as exc:
                    errors.append(str(exc))
    for item in data.get("analysis", []):
        role = item.get("role", "?")
        path = resolve_manifest_path(str(item.get("path", "")), manifest_path, base_dir)
        if not path.is_file():
            errors.append(f"analysis {role!r} file missing: {path}")
            continue
        if path.stat().st_size != item.get("bytes"):
            errors.append(
                f"analysis {role!r} size changed: expected {item.get('bytes')}, observed {path.stat().st_size}"
            )
        observed_hash = sha256_file(path)
        if observed_hash != item.get("sha256"):
            errors.append(
                f"analysis {role!r} SHA-256 mismatch: expected {item.get('sha256')}, observed {observed_hash}"
            )
        try:
            report = load_json(path)
            if report.get("schema") != item.get("schema"):
                errors.append(f"analysis {role!r} schema no longer matches manifest")
        except ManifestError as exc:
            errors.append(str(exc))
    return errors


def validate_profile(data: dict[str, Any], profile: str) -> list[str]:
    if profile == "basic":
        return []
    errors: list[str] = []
    capture_roles = {str(item.get("role")) for item in data.get("captures", []) if isinstance(item, dict)}
    analysis_roles = {str(item.get("role")) for item in data.get("analysis", []) if isinstance(item, dict)}
    missing_captures = sorted(FULL_CAPTURE_ROLES - capture_roles)
    missing_analysis = sorted(FULL_ANALYSIS_ROLES - analysis_roles)
    if missing_captures:
        errors.append("missing full-IMU capture role(s): " + ", ".join(missing_captures))
    if missing_analysis:
        errors.append("missing full-IMU analysis role(s): " + ", ".join(missing_analysis))

    imu = data.get("imu_configuration", {})
    if isinstance(imu, dict):
        for key in ("model", "frame", "accelerometer_filter", "gyroscope_filter", "configuration_source"):
            if placeholder(imu.get(key)):
                errors.append(f"imu_configuration.{key} is unknown/placeholder; full-IMU evidence is not promotable")

    if profile == "promotion":
        provenance = data.get("provenance", {})
        if not isinstance(provenance, dict) or provenance.get("kind") != "measured":
            errors.append("promotion profile requires provenance.kind='measured'")
        device = data.get("device", {})
        if isinstance(device, dict):
            for key in ("model", "serial", "sdk_version", "device_type", "isp_version", "fpga_version"):
                if placeholder(device.get(key)):
                    errors.append(f"device.{key} is unknown/placeholder; promotion is blocked")
    return errors


def verify_manifest(
    data: dict[str, Any],
    manifest_path: Path,
    *,
    profile: str,
    verify_file_hashes: bool,
    base_dir: Path | None = None,
) -> list[str]:
    errors = validate_structure(data)
    errors.extend(validate_cross_consistency(data))
    errors.extend(validate_profile(data, profile))
    if verify_file_hashes:
        errors.extend(validate_files(data, manifest_path, base_dir))
    return errors


def create_manifest(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.output.resolve()
    captures: list[dict[str, Any]] = []
    for text in args.capture:
        role, path = parse_role_path(text, "--capture")
        captures.append(capture_from_summary(role, path.resolve(), manifest_path))
    require_unique_roles(captures, "capture")
    observed, mode = assert_capture_consistency(captures)

    analysis: list[dict[str, Any]] = []
    for text in args.analysis:
        role, path = parse_role_path(text, "--analysis")
        analysis.append(analysis_from_json(role, path.resolve(), manifest_path))
    require_unique_roles(analysis, "analysis")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "session_id": args.session_id,
        "created_utc": utc_now(),
        "device": {
            "model": args.device_model,
            "serial": observed["serial"],
            "sdk_version": observed["sdk_version"],
            "device_type": observed["device_type"],
            "isp_version": observed["isp_version"],
            "fpga_version": observed["fpga_version"],
        },
        "imu_configuration": {
            "model": args.imu_model,
            "frame": args.imu_frame,
            "accelerometer_range_g": args.accel_range_g,
            "gyroscope_range_dps": args.gyro_range_dps,
            "output_data_rate_hz": args.odr_hz,
            "accelerometer_filter": args.accel_filter,
            "gyroscope_filter": args.gyro_filter,
            "configuration_source": args.configuration_source,
        },
        "camera_mode": mode,
        "captures": captures,
        "analysis": analysis,
        "provenance": {
            "tool": "tools/imu_calibration_provenance.py",
            "tool_version": TOOL_VERSION,
            "kind": args.kind,
        },
    }
    if args.note:
        manifest["imu_configuration"]["notes"] = list(args.note)
    return manifest


def print_result(errors: Sequence[str], profile: str) -> None:
    if errors:
        print(f"IMU calibration provenance gate: FAIL ({profile})")
        for error in errors:
            print(f"  - {error}")
    else:
        print(f"IMU calibration provenance gate: PASS ({profile})")


def write_fake_capture(root: Path, name: str, serial: str = "SYNTH-001") -> Path:
    trace = root / f"{name}.imu.csv"
    trace.write_text(
        "sample_valid,imu_extended_time_us,accel_raw_x,accel_raw_y,accel_raw_z,gyro_raw_x,gyro_raw_y,gyro_raw_z\n"
        "true,1000000,0,0,8192,1,-2,3\n"
        "true,1005000,0,0,8192,1,-2,3\n",
        encoding="utf-8",
    )
    summary = root / f"{name}.json"
    summary.write_text(json.dumps({
        "schema": RECORDER_SCHEMA,
        "device": {
            "serial": serial,
            "sdk_version": "synthetic-sdk",
            "device_type": "synthetic-decXin",
            "isp_version": "synthetic-isp",
            "fpga_version": "synthetic-fpga",
        },
        "mode": {
            "index": 0,
            "width": 4000,
            "height": 1200,
            "nominal_fps": 30,
            "transport": "YUYV",
        },
        "artifact": str(trace),
    }, indent=2) + "\n", encoding="utf-8")
    return summary


def write_fake_analysis(root: Path, role: str) -> Path:
    path = root / f"{role}.json"
    path.write_text(json.dumps({
        "schema": EXPECTED_ANALYSIS_SCHEMAS[role],
        "status": "synthetic-self-test",
    }, indent=2) + "\n", encoding="utf-8")
    return path


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        summary = write_fake_capture(root, "capture")
        manifest_path = root / "manifest.json"
        args = argparse.Namespace(
            output=manifest_path,
            capture=[f"{role}={summary}" for role in sorted(FULL_CAPTURE_ROLES)],
            analysis=[f"{role}={write_fake_analysis(root, role)}" for role in sorted(FULL_ANALYSIS_ROLES)],
            session_id="synthetic-session",
            device_model="DECXIN AR0234 synthetic fixture",
            imu_model="ICM-42688-P",
            imu_frame="bividi_imu",
            accel_range_g=4.0,
            gyro_range_dps=1000.0,
            odr_hz=200.0,
            accel_filter="synthetic-filter-A",
            gyro_filter="synthetic-filter-G",
            configuration_source="synthetic self-test fixture",
            note=[],
            kind="synthetic",
        )
        manifest = create_manifest(args)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        loaded = load_json(manifest_path)
        errors = verify_manifest(loaded, manifest_path, profile="full-imu", verify_file_hashes=True)
        assert not errors, errors
        promotion_errors = verify_manifest(loaded, manifest_path, profile="promotion", verify_file_hashes=True)
        assert any("provenance.kind='measured'" in item for item in promotion_errors)

        measured = json.loads(json.dumps(loaded))
        measured["provenance"]["kind"] = "measured"
        assert not verify_manifest(measured, manifest_path, profile="promotion", verify_file_hashes=True)

        trace_path = resolve_manifest_path(loaded["captures"][0]["trace_path"], manifest_path, None)
        trace_path.write_text(trace_path.read_text(encoding="utf-8") + "true,1010000,0,0,8192,1,-2,3\n", encoding="utf-8")
        hash_errors = verify_manifest(loaded, manifest_path, profile="full-imu", verify_file_hashes=True)
        assert any("SHA-256 mismatch" in item or "size changed" in item for item in hash_errors)

        bad_summary = write_fake_capture(root, "bad", serial="OTHER-SERIAL")
        bad_args = argparse.Namespace(**vars(args))
        bad_args.capture = [f"stationary={summary}", f"allan_stationary={bad_summary}"]
        try:
            create_manifest(bad_args)
        except ManifestError as exc:
            assert "device provenance differs" in str(exc)
        else:
            raise AssertionError("device mismatch was not rejected")

    print("IMU calibration provenance gate self-test: PASS")
    return 0


def positive_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build/verify Bividi IMU calibration provenance manifests")
    sub = parser.add_subparsers(dest="command")

    create = sub.add_parser("create", help="create a hash-bound manifest from Nori recorder summaries and analysis JSON")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--session-id", required=True)
    create.add_argument("--device-model", required=True)
    create.add_argument("--imu-model", required=True)
    create.add_argument("--imu-frame", required=True)
    create.add_argument("--accel-range-g", type=positive_float, required=True)
    create.add_argument("--gyro-range-dps", type=positive_float, required=True)
    create.add_argument("--odr-hz", type=positive_float, required=True)
    create.add_argument("--accel-filter", required=True)
    create.add_argument("--gyro-filter", required=True)
    create.add_argument("--configuration-source", required=True,
                        help="how the IMU range/ODR/filter configuration was established")
    create.add_argument("--kind", choices=("synthetic", "measured"), default="measured")
    create.add_argument("--capture", action="append", default=[], metavar="ROLE=SUMMARY_JSON",
                        help="Nori imu-record summary; repeat for every evidence capture")
    create.add_argument("--analysis", action="append", default=[], metavar="ROLE=REPORT_JSON",
                        help="analysis report JSON; known roles validate expected report schema")
    create.add_argument("--note", action="append", default=[])
    create.add_argument("--profile", choices=("basic", "full-imu", "promotion"), default="basic")

    verify = sub.add_parser("verify", help="validate manifest, compatibility, roles and SHA-256 bindings")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--profile", choices=("basic", "full-imu", "promotion"), default="basic")
    verify.add_argument("--base-dir", type=Path,
                        help="override manifest-relative path base for relocated evidence bundles")
    verify.add_argument("--skip-file-hashes", action="store_true",
                        help="structural review only; promotion should not use this")

    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.command == "create":
        try:
            manifest = create_manifest(args)
            errors = verify_manifest(
                manifest,
                args.output.resolve(),
                profile=args.profile,
                verify_file_hashes=True,
            )
            if errors:
                print_result(errors, args.profile)
                return 3
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print_result([], args.profile)
            print(f"  manifest={args.output}")
            print(f"  captures={len(manifest['captures'])} analysis={len(manifest['analysis'])}")
            return 0
        except (ManifestError, OSError, argparse.ArgumentTypeError) as exc:
            print(f"imu_calibration_provenance: {exc}", file=sys.stderr)
            return 3
    if args.command == "verify":
        try:
            manifest_path = args.manifest.resolve()
            data = load_json(manifest_path)
            errors = verify_manifest(
                data,
                manifest_path,
                profile=args.profile,
                verify_file_hashes=not args.skip_file_hashes,
                base_dir=args.base_dir.resolve() if args.base_dir else None,
            )
            print_result(errors, args.profile)
            return 0 if not errors else 3
        except (ManifestError, OSError) as exc:
            print(f"imu_calibration_provenance: {exc}", file=sys.stderr)
            return 3
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
