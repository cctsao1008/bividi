#!/usr/bin/env python3
"""Compare repeated Bividi camera-IMU calibration artifacts.

The comparator is intentionally dependency-free and threshold-free by default.
It verifies that repeated solves describe the same physical/device/frame contract,
rejects duplicate artifacts, computes all pairwise SE(3) disagreement and time-
offset disagreement, and optionally applies explicit requirement/baseline gates.

This is a repeatability/consistency laboratory, not a consensus estimator. It
never averages rotations or silently promotes one run as the final calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import validate_calibration_artifact

ARTIFACT_SCHEMA = "bividi.calibration.camera_imu.v1"
REPORT_SCHEMA = "bividi.calibration.camera_imu_repeatability.v1"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"


class CompareError(ValueError):
    pass


@dataclass
class LoadedArtifact:
    path: Path
    sha256: str
    data: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_artifact(path: Path) -> LoadedArtifact:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompareError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CompareError(f"{path}: expected JSON object")
    if data.get("schema") != ARTIFACT_SCHEMA:
        raise CompareError(f"{path}: expected schema {ARTIFACT_SCHEMA!r}")
    findings = validate_calibration_artifact.validate(data)
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        text = "; ".join(f"{finding.path}: {finding.message}" for finding in errors)
        raise CompareError(f"{path}: validation failed: {text}")
    return LoadedArtifact(path.resolve(), sha256_file(path), data)


def nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def compatibility_key(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_model": nested(data, "device", "model"),
        "device_serial": nested(data, "device", "serial"),
        "camera_id": nested(data, "camera_reference", "camera_id"),
        "camera_frame": nested(data, "camera_reference", "frame"),
        "camera_width": nested(data, "camera_reference", "width"),
        "camera_height": nested(data, "camera_reference", "height"),
        "camera_mode_id": nested(data, "camera_reference", "mode_id"),
        "imu_model": nested(data, "imu_reference", "model"),
        "imu_frame": nested(data, "imu_reference", "frame"),
        "transform_from": nested(data, "transform", "from_frame"),
        "transform_to": nested(data, "transform", "to_frame"),
        "translation_unit": nested(data, "transform", "translation_unit"),
        "handedness": nested(data, "frames", "handedness"),
        "camera_axes": nested(data, "frames", "camera_axes"),
        "imu_axes": nested(data, "frames", "imu_axes"),
        "time_definition": nested(data, "time_offset", "definition"),
        "camera_time_reference": nested(data, "time_offset", "camera_time_reference"),
        "external_backend": nested(data, "provenance", "external_backend"),
    }


def backend_revision(data: dict[str, Any]) -> Any:
    return nested(data, "provenance", "external_backend_revision")


def require_compatible(artifacts: Sequence[LoadedArtifact], allow_backend_revision_mismatch: bool) -> dict[str, Any]:
    reference = compatibility_key(artifacts[0].data)
    for item in artifacts[1:]:
        current = compatibility_key(item.data)
        differences = [key for key in reference if current.get(key) != reference.get(key)]
        if differences:
            rendered = ", ".join(
                f"{key}: {reference.get(key)!r} != {current.get(key)!r}" for key in differences
            )
            raise CompareError(f"incompatible artifact {item.path}: {rendered}")
    revisions = [backend_revision(item.data) for item in artifacts]
    if not allow_backend_revision_mismatch and any(value != revisions[0] for value in revisions[1:]):
        raise CompareError(
            "external_backend_revision differs across runs; use --allow-backend-revision-mismatch "
            "only when intentionally studying solver-version effects"
        )
    return {**reference, "backend_revisions": revisions}


def matrix4(data: dict[str, Any]) -> list[list[float]]:
    raw = nested(data, "transform", "matrix")
    if not isinstance(raw, list) or len(raw) != 4:
        raise CompareError("validated artifact unexpectedly lacks a 4x4 transform")
    return [[float(value) for value in row] for row in raw]


def rigid_inverse(t: Sequence[Sequence[float]]) -> list[list[float]]:
    r = [[float(t[i][j]) for j in range(3)] for i in range(3)]
    p = [float(t[i][3]) for i in range(3)]
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    pinv = [-sum(rt[i][j] * p[j] for j in range(3)) for i in range(3)]
    return [
        [rt[0][0], rt[0][1], rt[0][2], pinv[0]],
        [rt[1][0], rt[1][1], rt[1][2], pinv[1]],
        [rt[2][0], rt[2][1], rt[2][2], pinv[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def matmul4(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> list[list[float]]:
    return [
        [sum(float(a[i][k]) * float(b[k][j]) for k in range(4)) for j in range(4)]
        for i in range(4)
    ]


def rotation_angle_deg(t: Sequence[Sequence[float]]) -> float:
    trace = float(t[0][0]) + float(t[1][1]) + float(t[2][2])
    cosine = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
    return math.degrees(math.acos(cosine))


def translation_norm_mm(t: Sequence[Sequence[float]]) -> float:
    return 1000.0 * math.sqrt(sum(float(t[i][3]) ** 2 for i in range(3)))


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def distribution(values: Iterable[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "minimum": None, "maximum": None, "mean": None, "p50": None, "p95": None, "p99": None}
    return {
        "count": len(finite),
        "minimum": min(finite),
        "maximum": max(finite),
        "mean": statistics.fmean(finite),
        "p50": percentile(finite, 0.50),
        "p95": percentile(finite, 0.95),
        "p99": percentile(finite, 0.99),
    }


def compare(
    paths: Sequence[Path],
    *,
    allow_backend_revision_mismatch: bool,
    max_pairwise_translation_mm: float | None,
    max_pairwise_rotation_deg: float | None,
    max_pairwise_time_offset_us: float | None,
) -> dict[str, Any]:
    if len(paths) < 2:
        raise CompareError("at least two camera-IMU artifacts are required")
    artifacts = [load_artifact(path) for path in paths]
    hashes = [item.sha256 for item in artifacts]
    if len(set(hashes)) != len(hashes):
        raise CompareError("duplicate artifact content detected; repeatability requires distinct solve outputs")
    contract = require_compatible(artifacts, allow_backend_revision_mismatch)

    pairs: list[dict[str, Any]] = []
    translations: list[float] = []
    rotations: list[float] = []
    time_deltas: list[float] = []
    per_artifact = [
        {"path": str(item.path), "sha256": item.sha256, "calibration_id": item.data.get("calibration_id"),
         "source_session": nested(item.data, "provenance", "source_session"),
         "backend_revision": backend_revision(item.data),
         "worst_translation_mm": 0.0, "worst_rotation_deg": 0.0, "worst_time_offset_us": 0.0}
        for item in artifacts
    ]

    for i in range(len(artifacts)):
        ti = matrix4(artifacts[i].data)
        shift_i_us = float(nested(artifacts[i].data, "time_offset", "offset_s")) * 1_000_000.0
        for j in range(i + 1, len(artifacts)):
            tj = matrix4(artifacts[j].data)
            shift_j_us = float(nested(artifacts[j].data, "time_offset", "offset_s")) * 1_000_000.0
            delta = matmul4(ti, rigid_inverse(tj))
            translation_mm = translation_norm_mm(delta)
            rotation_deg = rotation_angle_deg(delta)
            time_us = abs(shift_i_us - shift_j_us)
            translations.append(translation_mm)
            rotations.append(rotation_deg)
            time_deltas.append(time_us)
            per_artifact[i]["worst_translation_mm"] = max(per_artifact[i]["worst_translation_mm"], translation_mm)
            per_artifact[j]["worst_translation_mm"] = max(per_artifact[j]["worst_translation_mm"], translation_mm)
            per_artifact[i]["worst_rotation_deg"] = max(per_artifact[i]["worst_rotation_deg"], rotation_deg)
            per_artifact[j]["worst_rotation_deg"] = max(per_artifact[j]["worst_rotation_deg"], rotation_deg)
            per_artifact[i]["worst_time_offset_us"] = max(per_artifact[i]["worst_time_offset_us"], time_us)
            per_artifact[j]["worst_time_offset_us"] = max(per_artifact[j]["worst_time_offset_us"], time_us)
            pairs.append({
                "a": i,
                "b": j,
                "translation_delta_mm": translation_mm,
                "rotation_delta_deg": rotation_deg,
                "time_offset_delta_us": time_us,
            })

    summaries = {
        "pairwise_translation_mm": distribution(translations),
        "pairwise_rotation_deg": distribution(rotations),
        "pairwise_time_offset_us": distribution(time_deltas),
    }
    gates: list[dict[str, Any]] = []
    failed = False
    specs = [
        ("max_pairwise_translation_mm", max_pairwise_translation_mm, summaries["pairwise_translation_mm"]["maximum"]),
        ("max_pairwise_rotation_deg", max_pairwise_rotation_deg, summaries["pairwise_rotation_deg"]["maximum"]),
        ("max_pairwise_time_offset_us", max_pairwise_time_offset_us, summaries["pairwise_time_offset_us"]["maximum"]),
    ]
    for name, limit, observed in specs:
        if limit is None:
            continue
        passed = observed is not None and float(observed) <= limit
        gates.append({"name": name, "limit": limit, "observed": observed, "passed": passed})
        failed |= not passed
    status = "FAIL" if failed else ("PASS" if gates else "EVIDENCE_ONLY_NO_THRESHOLDS")

    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "run_count": len(artifacts),
        "pair_count": len(pairs),
        "compatibility_contract": contract,
        "artifacts": per_artifact,
        "pairwise": pairs,
        "summary": summaries,
        "gates": gates,
        "interpretation": [
            "Pairwise SE(3) deltas quantify solve-to-solve repeatability; they do not identify which run is physically correct.",
            "No transform averaging or consensus calibration is produced by this tool.",
            "Time-offset repeatability is evaluated only after camera timestamp semantic/sign compatibility is verified.",
            "Default mode is evidence-only; acceptance thresholds must come from requirements or measured baselines.",
            "A backend revision mismatch is rejected by default because it confounds physical repeatability with solver-version effects.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Camera↔IMU Calibration Repeatability",
        "",
        f"Status: `{report['status']}`",
        f"Runs: {report['run_count']}; pairwise comparisons: {report['pair_count']}",
        "",
        "| Metric | P50 | P95 | P99 | Max |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, key in (
        ("Translation delta (mm)", "pairwise_translation_mm"),
        ("Rotation delta (deg)", "pairwise_rotation_deg"),
        ("Time-offset delta (us)", "pairwise_time_offset_us"),
    ):
        item = summary[key]
        lines.append(f"| {label} | {fmt(item['p50'])} | {fmt(item['p95'])} | {fmt(item['p99'])} | {fmt(item['maximum'])} |")
    lines += ["", "## Runs", ""]
    for index, item in enumerate(report["artifacts"]):
        lines.append(
            f"- run {index}: `{item['calibration_id']}` — worst Δt={fmt(item['worst_translation_mm'])} mm, "
            f"ΔR={fmt(item['worst_rotation_deg'])} deg, Δtime={fmt(item['worst_time_offset_us'])} us"
        )
    lines += ["", "## Explicit gates", ""]
    if report["gates"]:
        for gate in report["gates"]:
            lines.append(f"- `{gate['name']}`: observed={fmt(gate['observed'])}, limit={fmt(gate['limit'])}, passed={gate['passed']}")
    else:
        lines.append("- None. Report is evidence-only.")
    lines += ["", "## Interpretation guardrails", ""]
    lines.extend(f"- {item}" for item in report["interpretation"])
    return "\n".join(lines)


def rotation_z(deg: float) -> list[list[float]]:
    angle = math.radians(deg)
    c = math.cos(angle)
    s = math.sin(angle)
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def fixture_artifact(path: Path, calibration_id: str, tx_m: float, rz_deg: float, shift_us: float, *, serial: str = "SYNTHETIC") -> None:
    r = rotation_z(rz_deg)
    matrix = [
        [r[0][0], r[0][1], r[0][2], tx_m],
        [r[1][0], r[1][1], r[1][2], 0.0],
        [r[2][0], r[2][1], r[2][2], 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    data = {
        "schema": ARTIFACT_SCHEMA,
        "calibration_id": calibration_id,
        "created_utc": "2026-09-17T00:00:00+00:00",
        "device": {"model": "synthetic", "serial": serial},
        "camera_reference": {"camera_id": "camera_a", "frame": "camera_a", "width": 1920, "height": 1200, "mode_id": "mode0"},
        "imu_reference": {"model": "synthetic-imu", "frame": "imu", "imu_calibration_id": "imu-1"},
        "transform": {"from_frame": "imu", "to_frame": "camera_a", "matrix": matrix, "translation_unit": "m"},
        "time_offset": {"definition": TIME_OFFSET_DEFINITION, "camera_time_reference": "exposure_midpoint", "offset_s": shift_us / 1_000_000.0},
        "frames": {"handedness": "right", "camera_axes": "+X right +Y down +Z forward", "imu_axes": "+X forward +Y left +Z up"},
        "provenance": {"kind": "imported", "tool": "fixture", "source_session": calibration_id, "source_hash": "a" * 64, "external_backend": "ethz-asl/kalibr", "external_backend_revision": "test"},
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = [root / f"run{i}.json" for i in range(3)]
        fixture_artifact(paths[0], "run0", 0.0100, 0.00, -1500.0)
        fixture_artifact(paths[1], "run1", 0.0104, 0.05, -1480.0)
        fixture_artifact(paths[2], "run2", 0.0098, -0.04, -1525.0)
        evidence = compare(paths, allow_backend_revision_mismatch=False,
                           max_pairwise_translation_mm=None, max_pairwise_rotation_deg=None,
                           max_pairwise_time_offset_us=None)
        assert evidence["status"] == "EVIDENCE_ONLY_NO_THRESHOLDS"
        assert evidence["pair_count"] == 3
        passed = compare(paths, allow_backend_revision_mismatch=False,
                         max_pairwise_translation_mm=2.0, max_pairwise_rotation_deg=0.2,
                         max_pairwise_time_offset_us=100.0)
        assert passed["status"] == "PASS"
        failed = compare(paths, allow_backend_revision_mismatch=False,
                         max_pairwise_translation_mm=0.1, max_pairwise_rotation_deg=None,
                         max_pairwise_time_offset_us=None)
        assert failed["status"] == "FAIL"
        incompatible = root / "other.json"
        fixture_artifact(incompatible, "other", 0.01, 0.0, -1500.0, serial="OTHER")
        try:
            compare([paths[0], incompatible], allow_backend_revision_mismatch=False,
                    max_pairwise_translation_mm=None, max_pairwise_rotation_deg=None,
                    max_pairwise_time_offset_us=None)
        except CompareError:
            pass
        else:
            raise AssertionError("incompatible serial was not rejected")
    print("Camera-IMU repeatability comparator self-test: PASS")


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected numeric value") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError("value must be finite and > 0")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--allow-backend-revision-mismatch", action="store_true")
    parser.add_argument("--max-pairwise-translation-mm", type=positive_float)
    parser.add_argument("--max-pairwise-rotation-deg", type=positive_float)
    parser.add_argument("--max-pairwise-time-offset-us", type=positive_float)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if len(args.artifacts) < 2:
        print("at least two camera-IMU artifact paths are required", file=sys.stderr)
        return 2
    try:
        report = compare(
            [path.resolve() for path in args.artifacts],
            allow_backend_revision_mismatch=args.allow_backend_revision_mismatch,
            max_pairwise_translation_mm=args.max_pairwise_translation_mm,
            max_pairwise_rotation_deg=args.max_pairwise_rotation_deg,
            max_pairwise_time_offset_us=args.max_pairwise_time_offset_us,
        )
        prefix = args.output_prefix
        if prefix is not None:
            prefix = prefix.resolve()
            prefix.parent.mkdir(parents=True, exist_ok=True)
            Path(str(prefix) + ".repeatability.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            Path(str(prefix) + ".repeatability.md").write_text(render_markdown(report) + "\n", encoding="utf-8")
    except (CompareError, OSError, ValueError) as exc:
        print(f"camera-IMU repeatability comparison failed: {exc}", file=sys.stderr)
        return 3
    print(json.dumps({"status": report["status"], "runs": report["run_count"], "pairs": report["pair_count"], "summary": report["summary"]}, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
