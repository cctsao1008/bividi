#!/usr/bin/env python3
"""Import one Kalibr camera-IMU result into Bividi's versioned artifact.

The importer is intentionally narrow and dependency-free. It consumes the
provenance-bound dynamic-session manifest produced by
prepare_kalibr_dynamic_session.py plus Kalibr's resulting camchain YAML. It
preserves Bividi frame/timestamp semantics, verifies source hashes, parses
T_cam_imu and timeshift_cam_imu for one camera, validates the resulting Bividi
artifact, and writes a machine-readable import sidecar.

It does not infer camera axes or silently rename camera_a/camera_b as left/right.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import validate_calibration_artifact

SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
IMU_ARTIFACT_SCHEMA = "bividi.calibration.imu.v1"
CAPTURE_SCHEMA = "bividi.nori.camera_imu_dynamic_trace.v1"
OUTPUT_SCHEMA = "bividi.calibration.camera_imu.v1"
IMPORT_SCHEMA = "bividi.calibration.kalibr_camera_imu_import.v1"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"
TOOL_VERSION = "1"
CAMERA_MAP = {"cam0": "camera_a", "cam1": "camera_b"}


class ImportError(ValueError):
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
        raise ImportError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ImportError(f"{path}: expected JSON object")
    return value


def source_path(session: dict[str, Any], session_path: Path, key: str) -> Path:
    sources = session.get("sources")
    if not isinstance(sources, dict) or not isinstance(sources.get(key), dict):
        raise ImportError(f"{session_path}: missing sources.{key}")
    entry = sources[key]
    raw = entry.get("path")
    expected = entry.get("sha256")
    if not isinstance(raw, str) or not isinstance(expected, str):
        raise ImportError(f"{session_path}: sources.{key} requires path and sha256")
    path = Path(raw)
    if not path.is_absolute():
        path = (session_path.parent / path).resolve()
    if not path.is_file():
        raise ImportError(f"{session_path}: source file does not exist: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ImportError(f"{session_path}: sources.{key} SHA-256 mismatch")
    return path


def parse_matrix_row(text: str, source: Path, line_no: int) -> list[float]:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        raise ImportError(f"{source}:{line_no}: invalid matrix row") from exc
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ImportError(f"{source}:{line_no}: T_cam_imu row must contain four values")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ImportError(f"{source}:{line_no}: T_cam_imu contains non-finite/non-numeric value")
        result.append(float(item))
    return result


def parse_kalibr_camera(path: Path, camera: str) -> tuple[list[list[float]], float]:
    if camera not in CAMERA_MAP:
        raise ImportError(f"unsupported Kalibr camera {camera!r}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ImportError(f"cannot read Kalibr result {path}: {exc}") from exc

    start = None
    end = len(lines)
    camera_re = re.compile(r"^(cam\d+)\s*:\s*$")
    for index, raw in enumerate(lines):
        match = camera_re.match(raw.strip())
        if match and match.group(1) == camera:
            start = index + 1
            break
    if start is None:
        raise ImportError(f"{path}: camera section {camera!r} not found")
    for index in range(start, len(lines)):
        if camera_re.match(lines[index].strip()):
            end = index
            break

    matrix: list[list[float]] | None = None
    shift: float | None = None
    index = start
    while index < end:
        stripped = lines[index].strip()
        if stripped.startswith("timeshift_cam_imu:"):
            text = stripped.split(":", 1)[1].strip()
            try:
                shift = float(text)
            except ValueError as exc:
                raise ImportError(f"{path}:{index + 1}: invalid timeshift_cam_imu") from exc
            if not math.isfinite(shift):
                raise ImportError(f"{path}:{index + 1}: non-finite timeshift_cam_imu")
        elif stripped == "T_cam_imu:":
            rows: list[list[float]] = []
            probe = index + 1
            while probe < end and len(rows) < 4:
                candidate = lines[probe].strip()
                if not candidate or candidate.startswith("#"):
                    probe += 1
                    continue
                if not candidate.startswith("-"):
                    break
                row_text = candidate[1:].strip()
                rows.append(parse_matrix_row(row_text, path, probe + 1))
                probe += 1
            if len(rows) != 4:
                raise ImportError(f"{path}:{index + 1}: T_cam_imu must have four rows")
            matrix = rows
            index = probe - 1
        index += 1

    if matrix is None:
        raise ImportError(f"{path}: {camera}.T_cam_imu missing")
    if shift is None:
        raise ImportError(f"{path}: {camera}.timeshift_cam_imu missing")
    return matrix, shift


def build_artifact(
    session_path: Path,
    result_path: Path,
    *,
    camera: str,
    camera_frame: str | None,
    camera_axes: str,
    calibration_id: str,
    external_container: str | None,
    solver_report: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = load_json(session_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise ImportError(f"{session_path}: expected schema {SESSION_SCHEMA!r}")
    if camera not in CAMERA_MAP:
        raise ImportError(f"camera must be one of {sorted(CAMERA_MAP)}")
    camera_id = CAMERA_MAP[camera]

    mapping = session.get("camera_mapping")
    if not isinstance(mapping, dict) or mapping.get(camera_id) != camera:
        raise ImportError(f"{session_path}: camera mapping does not bind {camera_id} -> {camera}")
    time_ref = session.get("camera_time_reference")
    if not isinstance(time_ref, dict) or time_ref.get("time_shift_definition") != TIME_OFFSET_DEFINITION:
        raise ImportError(f"{session_path}: incompatible camera time-shift contract")
    camera_time_reference = time_ref.get("kind")
    if camera_time_reference not in {"exposure_start", "exposure_midpoint", "exposure_end"}:
        raise ImportError(f"{session_path}: unsupported camera time reference {camera_time_reference!r}")

    imu_path = source_path(session, session_path, "imu_calibration")
    capture_path = source_path(session, session_path, "dynamic_capture")
    imu = load_json(imu_path)
    capture = load_json(capture_path)
    if imu.get("schema") != IMU_ARTIFACT_SCHEMA:
        raise ImportError(f"{imu_path}: expected {IMU_ARTIFACT_SCHEMA!r}")
    if capture.get("schema") != CAPTURE_SCHEMA:
        raise ImportError(f"{capture_path}: expected {CAPTURE_SCHEMA!r}")

    matrix, shift = parse_kalibr_camera(result_path, camera)
    imu_ref = imu.get("imu")
    imu_frames = imu.get("frames")
    imu_device = imu.get("device")
    mode = capture.get("mode")
    if not all(isinstance(value, dict) for value in (imu_ref, imu_frames, imu_device, mode)):
        raise ImportError("IMU artifact/dynamic capture lacks required metadata")
    if session.get("device", {}).get("serial") != imu_device.get("serial"):
        raise ImportError("dynamic session and IMU artifact serial do not match")
    if not isinstance(camera_axes, str) or not camera_axes.strip():
        raise ImportError("camera_axes must be explicit and non-empty")
    resolved_camera_frame = camera_frame or camera_id

    quality_notes = [
        f"Kalibr result YAML SHA-256: {sha256_file(result_path)}",
        "Imported T_cam_imu is interpreted as imu0 -> selected Kalibr camera according to the pinned Kalibr source contract.",
        f"timeshift_cam_imu is interpreted with camera timestamp semantic {camera_time_reference!r} from the staged session.",
        "Solver quality/covariance is not inferred from the YAML transform alone; review the Kalibr report before final acceptance.",
    ]
    solver_report_hash = None
    if solver_report is not None:
        if not solver_report.is_file():
            raise ImportError(f"solver report does not exist: {solver_report}")
        solver_report_hash = sha256_file(solver_report)
        quality_notes.append(f"Kalibr solver report SHA-256: {solver_report_hash}")

    kalibr = session.get("kalibr")
    if not isinstance(kalibr, dict) or kalibr.get("backend") != "ethz-asl/kalibr":
        raise ImportError(f"{session_path}: missing Kalibr backend provenance")
    provenance = {
        "kind": "imported",
        "tool": "import_kalibr_camera_imu.py",
        "tool_version": TOOL_VERSION,
        "source_session": str(session.get("session_id", session_path.name)),
        "source_hash": sha256_file(session_path),
        "external_backend": "ethz-asl/kalibr",
        "external_backend_revision": str(kalibr.get("revision", "")),
    }
    if external_container:
        provenance["external_backend_container"] = external_container

    artifact = {
        "schema": OUTPUT_SCHEMA,
        "calibration_id": calibration_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "device": {
            "model": str(imu_device.get("model", capture.get("device", {}).get("product", "unknown"))),
            "serial": str(imu_device.get("serial")),
            **({"sdk_version": str(imu_device["sdk_version"])} if isinstance(imu_device.get("sdk_version"), str) else {}),
        },
        "camera_reference": {
            "camera_id": camera_id,
            "frame": resolved_camera_frame,
            "width": int(mode["width"]),
            "height": int(mode["height"]),
            "mode_id": f"nori-mode-{mode.get('index')}-{mode.get('width')}x{mode.get('height')}-{mode.get('transport')}",
        },
        "imu_reference": {
            "model": str(imu_ref.get("model")),
            "frame": str(imu_ref.get("frame")),
            "imu_calibration_id": str(imu.get("calibration_id")),
        },
        "transform": {
            "from_frame": str(imu_ref.get("frame")),
            "to_frame": resolved_camera_frame,
            "matrix": matrix,
            "translation_unit": "m",
        },
        "time_offset": {
            "definition": TIME_OFFSET_DEFINITION,
            "camera_time_reference": camera_time_reference,
            "offset_s": shift,
            "method": "ethz-asl/kalibr imu-camera calibration",
        },
        "frames": {
            "handedness": "right",
            "camera_axes": camera_axes.strip(),
            "imu_axes": str(imu_frames.get("imu_axes")),
        },
        "quality": {
            "warnings": ["Imported solver result requires physical/solver-quality review before downstream accuracy claims."],
            "notes": quality_notes,
        },
        "provenance": provenance,
    }

    findings = validate_calibration_artifact.validate(artifact)
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        rendered = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise ImportError(f"constructed artifact failed Bividi validation: {rendered}")

    sidecar = {
        "schema": IMPORT_SCHEMA,
        "created_utc": artifact["created_utc"],
        "camera": camera,
        "camera_id": camera_id,
        "dynamic_session": {"path": str(session_path), "sha256": sha256_file(session_path)},
        "kalibr_result": {"path": str(result_path), "sha256": sha256_file(result_path)},
        "solver_report": None if solver_report is None else {"path": str(solver_report), "sha256": solver_report_hash},
        "kalibr_revision": provenance["external_backend_revision"],
        "external_container": external_container,
        "camera_time_reference": camera_time_reference,
        "time_shift_definition": TIME_OFFSET_DEFINITION,
        "transform_definition": f"T_cam_imu: {imu_ref.get('frame')} -> {resolved_camera_frame}",
        "artifact_calibration_id": calibration_id,
        "status": "imported_candidate_requires_review",
    }
    return artifact, sidecar


def write_fixture(root: Path) -> tuple[Path, Path]:
    capture = root / "capture.json"
    capture.write_text(json.dumps({
        "schema": CAPTURE_SCHEMA,
        "device": {"serial": "SYNTHETIC", "product": "synthetic-rig"},
        "mode": {"index": 0, "width": 1920, "height": 1200, "transport": "BGR24"},
    }), encoding="utf-8")
    imu = root / "imu.json"
    imu.write_text(json.dumps({
        "schema": IMU_ARTIFACT_SCHEMA,
        "calibration_id": "imu-synth",
        "device": {"model": "synthetic-rig", "serial": "SYNTHETIC"},
        "imu": {"model": "ICM-42688-P", "frame": "imu"},
        "frames": {"handedness": "right", "imu_axes": "+X forward, +Y left, +Z up"},
    }), encoding="utf-8")
    session = root / "session.json"
    session.write_text(json.dumps({
        "schema": SESSION_SCHEMA,
        "session_id": "synth-session",
        "device": {"serial": "SYNTHETIC"},
        "camera_mapping": {"camera_a": "cam0", "camera_b": "cam1", "guardrail": "synthetic"},
        "camera_time_reference": {"kind": "exposure_midpoint", "time_shift_definition": TIME_OFFSET_DEFINITION},
        "kalibr": {"backend": "ethz-asl/kalibr", "revision": "test"},
        "sources": {
            "dynamic_capture": {"path": str(capture), "sha256": sha256_file(capture)},
            "imu_calibration": {"path": str(imu), "sha256": sha256_file(imu)},
        },
    }), encoding="utf-8")
    result = root / "camchain-imucam.yaml"
    result.write_text(
        "cam0:\n"
        "  T_cam_imu:\n"
        "  - [1.0, 0.0, 0.0, 0.01]\n"
        "  - [0.0, 1.0, 0.0, -0.02]\n"
        "  - [0.0, 0.0, 1.0, 0.03]\n"
        "  - [0.0, 0.0, 0.0, 1.0]\n"
        "  timeshift_cam_imu: -0.0015\n"
        "cam1:\n"
        "  T_cam_imu:\n"
        "  - [1.0, 0.0, 0.0, 0.07]\n"
        "  - [0.0, 1.0, 0.0, -0.02]\n"
        "  - [0.0, 0.0, 1.0, 0.03]\n"
        "  - [0.0, 0.0, 0.0, 1.0]\n"
        "  timeshift_cam_imu: -0.0014\n",
        encoding="utf-8",
    )
    return session, result


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session, result = write_fixture(root)
        artifact, sidecar = build_artifact(
            session, result, camera="cam0", camera_frame=None,
            camera_axes="explicit synthetic right-handed camera convention",
            calibration_id="camera-imu-synth", external_container=None, solver_report=None,
        )
        assert artifact["transform"]["from_frame"] == "imu"
        assert artifact["transform"]["to_frame"] == "camera_a"
        assert abs(artifact["transform"]["matrix"][0][3] - 0.01) < 1e-12
        assert abs(artifact["time_offset"]["offset_s"] + 0.0015) < 1e-12
        assert artifact["time_offset"]["camera_time_reference"] == "exposure_midpoint"
        assert sidecar["status"] == "imported_candidate_requires_review"

        bad = root / "bad.yaml"
        bad.write_text("cam0:\n  timeshift_cam_imu: 0.0\n", encoding="utf-8")
        try:
            parse_kalibr_camera(bad, "cam0")
        except ImportError:
            pass
        else:
            raise AssertionError("missing T_cam_imu was not rejected")
    print("Kalibr camera-IMU result importer self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("result_yaml", nargs="?", type=Path)
    parser.add_argument("--camera", choices=sorted(CAMERA_MAP), default="cam0")
    parser.add_argument("--camera-frame")
    parser.add_argument("--camera-axes")
    parser.add_argument("--calibration-id")
    parser.add_argument("--external-container")
    parser.add_argument("--solver-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    required = (args.session, args.result_yaml, args.camera_axes, args.calibration_id, args.output)
    if any(value is None for value in required):
        print("session, result_yaml, --camera-axes, --calibration-id and --output are required", file=sys.stderr)
        return 2
    try:
        artifact, sidecar = build_artifact(
            args.session.resolve(), args.result_yaml.resolve(), camera=args.camera,
            camera_frame=args.camera_frame, camera_axes=args.camera_axes,
            calibration_id=args.calibration_id, external_container=args.external_container,
            solver_report=None if args.solver_report is None else args.solver_report.resolve(),
        )
        args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        manifest_out = args.manifest_out or args.output.with_suffix(args.output.suffix + ".import.json")
        sidecar["output_artifact"] = {"path": str(args.output.resolve()), "sha256": sha256_file(args.output)}
        manifest_out.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    except (ImportError, OSError) as exc:
        print(f"Kalibr camera-IMU import failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"artifact": str(args.output), "import_manifest": str(manifest_out), "status": sidecar["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
