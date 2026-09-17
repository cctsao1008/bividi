#!/usr/bin/env python3
"""Analyze ETH Zurich Kalibr IMU-camera solver residuals as explicit quality evidence.

The tool parses the text report emitted by Kalibr's printErrorStatistics() at the
pinned backend revision used by Bividi. It binds the report to one prepared
Bividi dynamic-session manifest, preserves normalized and physical residuals,
and applies only operator-supplied gates. Solver fit quality is evidence; it is
not by itself proof of calibration accuracy, observability, or repeatability.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "bividi.calibration.kalibr_solver_quality.v1"
SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
TOOL_VERSION = "1"
BACKEND = "ethz-asl/kalibr"
PINNED_REVISION = "1f60227442d25e36365ef5f72cd80b9666d73467"
SOURCE_CONTRACT = (
    "aslam_offline_calibration/kalibr/python/"
    "kalibr_imu_camera_calibration/IccUtil.py::printErrorStatistics"
)

_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_STATS_RE = re.compile(
    rf"^mean\s+({_FLOAT}),\s*median\s+({_FLOAT}),\s*std:\s*({_FLOAT})\s*$"
)
_CAM_NORM_RE = re.compile(r"^Reprojection error \((cam\d+)\):\s*(.*)$")
_CAM_PHYS_RE = re.compile(r"^Reprojection error \((cam\d+)\) \[px\]:\s*(.*)$")
_GYRO_NORM_RE = re.compile(r"^Gyroscope error \((imu\d+)\):\s*(.*)$")
_GYRO_PHYS_RE = re.compile(r"^Gyroscope error \((imu\d+)\) \[rad/s\]:\s*(.*)$")
_ACCEL_NORM_RE = re.compile(r"^Accelerometer error \((imu\d+)\):\s*(.*)$")
_ACCEL_PHYS_RE = re.compile(r"^Accelerometer error \((imu\d+)\) \[m/s\^2\]:\s*(.*)$")


class QualityError(ValueError):
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
        raise QualityError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualityError(f"{path}: expected JSON object")
    return value


def parse_stats(text: str, source: str) -> dict[str, float]:
    match = _STATS_RE.match(text.strip())
    if not match:
        raise QualityError(f"{source}: expected 'mean <x>, median <y>, std: <z>'")
    mean, median, std = (float(match.group(index)) for index in range(1, 4))
    if not all(math.isfinite(value) for value in (mean, median, std)):
        raise QualityError(f"{source}: non-finite residual statistic")
    if mean < 0 or median < 0 or std < 0:
        raise QualityError(f"{source}: residual norm statistics must be non-negative")
    return {
        "mean": mean,
        "median": median,
        "std": std,
        "derived_rms": math.hypot(mean, std),
    }


def _empty_section(unit_camera: str, unit_gyro: str, unit_accel: str) -> dict[str, Any]:
    return {
        "camera_unit": unit_camera,
        "gyroscope_unit": unit_gyro,
        "accelerometer_unit": unit_accel,
        "cameras": {},
        "imus": {},
    }


def _put_unique(mapping: dict[str, Any], key: str, value: Any, source: str) -> None:
    if key in mapping:
        raise QualityError(f"{source}: duplicate metric for {key}")
    mapping[key] = value


def parse_kalibr_results_text(text: str, *, source: str = "<memory>") -> dict[str, Any]:
    sections = {
        "normalized": _empty_section("normalized", "normalized", "normalized"),
        "physical": _empty_section("px", "rad/s", "m/s^2"),
    }
    section: str | None = None
    seen_headers: set[str] = set()

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped == "Normalized Residuals":
            section = "normalized"
            seen_headers.add(section)
            continue
        if stripped == "Residuals":
            section = "physical"
            seen_headers.add(section)
            continue
        if not stripped or stripped.startswith("-") or section is None:
            continue

        location = f"{source}:{line_no}"
        if section == "normalized":
            cam_match = _CAM_NORM_RE.match(stripped)
            gyro_match = _GYRO_NORM_RE.match(stripped)
            accel_match = _ACCEL_NORM_RE.match(stripped)
        else:
            cam_match = _CAM_PHYS_RE.match(stripped)
            gyro_match = _GYRO_PHYS_RE.match(stripped)
            accel_match = _ACCEL_PHYS_RE.match(stripped)

        if cam_match:
            camera, tail = cam_match.groups()
            value: dict[str, Any]
            if tail.strip() == "no corners":
                value = {"status": "no_corners"}
            else:
                value = {"status": "ok", **parse_stats(tail, location)}
            _put_unique(sections[section]["cameras"], camera, value, location)
            continue

        if gyro_match:
            imu, tail = gyro_match.groups()
            imu_entry = sections[section]["imus"].setdefault(imu, {})
            _put_unique(imu_entry, "gyroscope", parse_stats(tail, location), location)
            continue

        if accel_match:
            imu, tail = accel_match.groups()
            imu_entry = sections[section]["imus"].setdefault(imu, {})
            _put_unique(imu_entry, "accelerometer", parse_stats(tail, location), location)
            continue

    if seen_headers != {"normalized", "physical"}:
        missing = sorted({"normalized", "physical"} - seen_headers)
        raise QualityError(f"{source}: missing Kalibr residual section(s): {', '.join(missing)}")

    if not sections["physical"]["cameras"] or not sections["physical"]["imus"]:
        raise QualityError(f"{source}: physical residual section has no camera or IMU statistics")
    if not sections["normalized"]["cameras"] or not sections["normalized"]["imus"]:
        raise QualityError(f"{source}: normalized residual section has no camera or IMU statistics")

    return sections


def expected_sensors(session: Mapping[str, Any], session_path: Path) -> tuple[list[str], list[str]]:
    mapping = session.get("camera_mapping")
    if not isinstance(mapping, dict):
        raise QualityError(f"{session_path}: missing camera_mapping")
    cameras: list[str] = []
    for key in ("camera_a", "camera_b"):
        value = mapping.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"cam\d+", value):
            raise QualityError(f"{session_path}: camera_mapping.{key} must name a Kalibr camera")
        cameras.append(value)
    if len(set(cameras)) != len(cameras):
        raise QualityError(f"{session_path}: camera mapping contains duplicate Kalibr camera names")
    return cameras, ["imu0"]


def structural_findings(
    sections: Mapping[str, Any],
    expected_cameras: Sequence[str],
    expected_imus: Sequence[str],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for section_name in ("normalized", "physical"):
        section = sections[section_name]
        cameras = section["cameras"]
        imus = section["imus"]
        for camera in expected_cameras:
            metric = cameras.get(camera)
            if metric is None:
                findings.append({
                    "severity": "error",
                    "code": "missing_camera_residual",
                    "message": f"{section_name}: missing reprojection residual for {camera}",
                })
            elif metric.get("status") != "ok":
                findings.append({
                    "severity": "error",
                    "code": "camera_no_corners",
                    "message": f"{section_name}: {camera} reports no corners",
                })
        for imu in expected_imus:
            metric = imus.get(imu)
            if not isinstance(metric, dict):
                findings.append({
                    "severity": "error",
                    "code": "missing_imu_residual",
                    "message": f"{section_name}: missing residuals for {imu}",
                })
                continue
            for kind in ("gyroscope", "accelerometer"):
                if kind not in metric:
                    findings.append({
                        "severity": "error",
                        "code": f"missing_{kind}_residual",
                        "message": f"{section_name}: missing {kind} residual for {imu}",
                    })
    return findings


def _max_metric(
    entries: Sequence[tuple[str, Mapping[str, Any]]],
    field: str,
) -> tuple[float, str]:
    candidates: list[tuple[float, str]] = []
    for label, metric in entries:
        if metric.get("status", "ok") != "ok":
            continue
        value = metric.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            candidates.append((float(value), label))
    if not candidates:
        raise QualityError(f"no finite values available for gate field {field!r}")
    return max(candidates, key=lambda item: item[0])


def build_gates(
    sections: Mapping[str, Any],
    thresholds: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    physical = sections["physical"]
    normalized = sections["normalized"]

    cam_phys = [(camera, metric) for camera, metric in physical["cameras"].items()]
    gyro_phys = [
        (f"{imu}.gyroscope", metric["gyroscope"])
        for imu, metric in physical["imus"].items()
        if "gyroscope" in metric
    ]
    accel_phys = [
        (f"{imu}.accelerometer", metric["accelerometer"])
        for imu, metric in physical["imus"].items()
        if "accelerometer" in metric
    ]
    cam_norm = [(camera, metric) for camera, metric in normalized["cameras"].items()]
    gyro_norm = [
        (f"{imu}.gyroscope", metric["gyroscope"])
        for imu, metric in normalized["imus"].items()
        if "gyroscope" in metric
    ]
    accel_norm = [
        (f"{imu}.accelerometer", metric["accelerometer"])
        for imu, metric in normalized["imus"].items()
        if "accelerometer" in metric
    ]

    specs = (
        ("max_reprojection_mean_px", cam_phys, "mean", "px"),
        ("max_reprojection_rms_px", cam_phys, "derived_rms", "px"),
        ("max_gyro_mean_rad_s", gyro_phys, "mean", "rad/s"),
        ("max_gyro_rms_rad_s", gyro_phys, "derived_rms", "rad/s"),
        ("max_accel_mean_m_s2", accel_phys, "mean", "m/s^2"),
        ("max_accel_rms_m_s2", accel_phys, "derived_rms", "m/s^2"),
        ("max_normalized_reprojection_mean", cam_norm, "mean", "normalized"),
        ("max_normalized_gyro_mean", gyro_norm, "mean", "normalized"),
        ("max_normalized_accel_mean", accel_norm, "mean", "normalized"),
    )

    gates: list[dict[str, Any]] = []
    for name, entries, field, unit in specs:
        threshold = thresholds.get(name)
        if threshold is None:
            continue
        if not math.isfinite(float(threshold)) or float(threshold) < 0:
            raise QualityError(f"{name}: threshold must be finite and non-negative")
        observed, worst_source = _max_metric(entries, field)
        gates.append({
            "name": name,
            "field": field,
            "unit": unit,
            "threshold": float(threshold),
            "observed_max": observed,
            "worst_source": worst_source,
            "status": "PASS" if observed <= float(threshold) else "FAIL",
        })
    return gates


def analyze(
    session_path: Path,
    results_path: Path,
    *,
    thresholds: Mapping[str, float | None],
    allow_backend_revision_mismatch: bool = False,
) -> dict[str, Any]:
    session = load_json(session_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise QualityError(f"{session_path}: expected schema {SESSION_SCHEMA!r}")
    kalibr = session.get("kalibr")
    if not isinstance(kalibr, dict) or kalibr.get("backend") != BACKEND:
        raise QualityError(f"{session_path}: expected Kalibr backend {BACKEND!r}")
    revision = kalibr.get("revision")
    if not isinstance(revision, str) or not revision:
        raise QualityError(f"{session_path}: missing kalibr.revision")
    if revision != PINNED_REVISION and not allow_backend_revision_mismatch:
        raise QualityError(
            f"{session_path}: Kalibr revision {revision!r} differs from parser contract "
            f"{PINNED_REVISION!r}; pass --allow-backend-revision-mismatch only after reviewing output format"
        )

    expected_cameras, expected_imus = expected_sensors(session, session_path)
    try:
        text = results_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QualityError(f"cannot read Kalibr results {results_path}: {exc}") from exc
    sections = parse_kalibr_results_text(text, source=str(results_path))
    findings = structural_findings(sections, expected_cameras, expected_imus)
    gates = build_gates(sections, thresholds)

    if any(finding["severity"] == "error" for finding in findings):
        status = "FAIL"
    elif any(gate["status"] == "FAIL" for gate in gates):
        status = "FAIL"
    elif gates:
        status = "PASS"
    else:
        status = "EVIDENCE_ONLY_NO_THRESHOLDS"

    report = {
        "schema": SCHEMA,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_contract": {
            "backend": BACKEND,
            "verified_revision": PINNED_REVISION,
            "session_revision": revision,
            "revision_mismatch_allowed": revision != PINNED_REVISION,
            "source": SOURCE_CONTRACT,
            "statistics_semantics": (
                "Kalibr prints mean/median/population-std of residual norms; "
                "derived_rms = sqrt(mean^2 + std^2)."
            ),
        },
        "source": {
            "dynamic_session": {
                "path": str(session_path),
                "sha256": sha256_file(session_path),
                "session_id": session.get("session_id"),
            },
            "results_imucam_txt": {
                "path": str(results_path),
                "sha256": sha256_file(results_path),
            },
        },
        "expected": {
            "cameras": list(expected_cameras),
            "imus": list(expected_imus),
        },
        "residuals": sections,
        "assessment": {
            "status": status,
            "structural_findings": findings,
            "gates": gates,
            "threshold_policy": (
                "No numeric acceptance threshold is implied by Bividi. "
                "Only explicitly supplied gates affect PASS/FAIL."
            ),
        },
        "provenance": {
            "tool": "analyze_kalibr_solver_quality.py",
            "tool_version": TOOL_VERSION,
        },
        "notes": [
            "Normalized and physical residuals are preserved separately.",
            "A low optimizer residual does not prove calibration accuracy, motion observability, timestamp correctness, or repeatability.",
            "Use camera-IMU temporal review and repeated-session comparison as independent evidence.",
        ],
    }
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    assessment = report["assessment"]
    lines = [
        "# Kalibr IMU-Camera Solver Quality",
        "",
        f"Status: **{assessment['status']}**",
        "",
        "## Provenance",
        "",
        f"- Session: `{report['source']['dynamic_session']['path']}`",
        f"- Session SHA-256: `{report['source']['dynamic_session']['sha256']}`",
        f"- Kalibr results: `{report['source']['results_imucam_txt']['path']}`",
        f"- Results SHA-256: `{report['source']['results_imucam_txt']['sha256']}`",
        f"- Session Kalibr revision: `{report['source_contract']['session_revision']}`",
        "",
    ]

    for section_name, title in (("physical", "Physical residuals"), ("normalized", "Normalized residuals")):
        section = report["residuals"][section_name]
        lines.extend([f"## {title}", "", "| Sensor | Quantity | Unit | Mean | Median | Std | Derived RMS |", "|---|---|---:|---:|---:|---:|---:|"])
        for camera, metric in sorted(section["cameras"].items()):
            if metric.get("status") != "ok":
                lines.append(f"| {camera} | reprojection | {section['camera_unit']} | no corners | — | — | — |")
            else:
                lines.append(
                    f"| {camera} | reprojection | {section['camera_unit']} | "
                    f"{metric['mean']:.9g} | {metric['median']:.9g} | {metric['std']:.9g} | {metric['derived_rms']:.9g} |"
                )
        for imu, metric in sorted(section["imus"].items()):
            for quantity, unit_key in (("gyroscope", "gyroscope_unit"), ("accelerometer", "accelerometer_unit")):
                if quantity not in metric:
                    continue
                values = metric[quantity]
                lines.append(
                    f"| {imu} | {quantity} | {section[unit_key]} | "
                    f"{values['mean']:.9g} | {values['median']:.9g} | {values['std']:.9g} | {values['derived_rms']:.9g} |"
                )
        lines.append("")

    findings = assessment["structural_findings"]
    lines.extend(["## Structural findings", ""])
    if findings:
        for finding in findings:
            lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}` — {finding['message']}")
    else:
        lines.append("- None.")
    lines.append("")

    gates = assessment["gates"]
    lines.extend(["## Explicit gates", ""])
    if gates:
        lines.extend(["| Gate | Observed max | Threshold | Unit | Worst source | Status |", "|---|---:|---:|---|---|---|"])
        for gate in gates:
            lines.append(
                f"| `{gate['name']}` | {gate['observed_max']:.9g} | {gate['threshold']:.9g} | "
                f"{gate['unit']} | {gate['worst_source']} | **{gate['status']}** |"
            )
    else:
        lines.append("- No numeric gates supplied; this report is evidence-only.")
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "- Solver residuals measure optimizer fit, not absolute calibration truth.",
        "- Good residuals do not establish motion observability, correct timestamp semantics, or cross-session repeatability.",
        "- Bividi does not convert the vendor synchronization claim into an automatic solver-quality threshold.",
        "",
    ])
    return "\n".join(lines)


def write_fixture(root: Path, *, revision: str = PINNED_REVISION, no_corners: bool = False) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    session = root / "session.json"
    session.write_text(json.dumps({
        "schema": SESSION_SCHEMA,
        "session_id": "synthetic-kalibr-quality",
        "camera_mapping": {"camera_a": "cam0", "camera_b": "cam1", "guardrail": "synthetic"},
        "kalibr": {"backend": BACKEND, "revision": revision},
    }), encoding="utf-8")
    cam1_norm = "no corners" if no_corners else "mean 0.9, median 0.8, std: 0.3"
    cam1_phys = "no corners" if no_corners else "mean 0.24, median 0.2, std: 0.1"
    result = root / "synthetic-results-imucam.txt"
    result.write_text(
        "Calibration results\n"
        "===================\n"
        "Normalized Residuals\n"
        "----------------------------\n"
        "Reprojection error (cam0):     mean 0.8, median 0.7, std: 0.2\n"
        f"Reprojection error (cam1):     {cam1_norm}\n"
        "Gyroscope error (imu0):        mean 0.6, median 0.5, std: 0.1\n"
        "Accelerometer error (imu0):    mean 0.7, median 0.6, std: 0.2\n"
        "\n"
        "Residuals\n"
        "----------------------------\n"
        "Reprojection error (cam0) [px]:     mean 0.2, median 0.18, std: 0.08\n"
        f"Reprojection error (cam1) [px]:     {cam1_phys}\n"
        "Gyroscope error (imu0) [rad/s]:     mean 0.01, median 0.009, std: 0.004\n"
        "Accelerometer error (imu0) [m/s^2]: mean 0.08, median 0.07, std: 0.03\n",
        encoding="utf-8",
    )
    return session, result


def self_test() -> None:
    empty_thresholds = {
        "max_reprojection_mean_px": None,
        "max_reprojection_rms_px": None,
        "max_gyro_mean_rad_s": None,
        "max_gyro_rms_rad_s": None,
        "max_accel_mean_m_s2": None,
        "max_accel_rms_m_s2": None,
        "max_normalized_reprojection_mean": None,
        "max_normalized_gyro_mean": None,
        "max_normalized_accel_mean": None,
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        session, result = write_fixture(root)
        report = analyze(session, result, thresholds=empty_thresholds)
        assert report["assessment"]["status"] == "EVIDENCE_ONLY_NO_THRESHOLDS"
        cam0 = report["residuals"]["physical"]["cameras"]["cam0"]
        assert abs(cam0["derived_rms"] - math.hypot(0.2, 0.08)) < 1e-15

        passing = dict(empty_thresholds)
        passing["max_reprojection_mean_px"] = 0.25
        passing["max_gyro_rms_rad_s"] = 0.02
        report = analyze(session, result, thresholds=passing)
        assert report["assessment"]["status"] == "PASS"

        failing = dict(empty_thresholds)
        failing["max_reprojection_mean_px"] = 0.21
        report = analyze(session, result, thresholds=failing)
        assert report["assessment"]["status"] == "FAIL"
        assert report["assessment"]["gates"][0]["worst_source"] == "cam1"

        bad_session, bad_result = write_fixture(root / "no-corners", no_corners=True)
        report = analyze(bad_session, bad_result, thresholds=empty_thresholds)
        assert report["assessment"]["status"] == "FAIL"
        assert any(item["code"] == "camera_no_corners" for item in report["assessment"]["structural_findings"])

        mismatch_root = root / "mismatch"
        mismatch_root.mkdir()
        mismatch_session, mismatch_result = write_fixture(mismatch_root, revision="different")
        try:
            analyze(mismatch_session, mismatch_result, thresholds=empty_thresholds)
        except QualityError:
            pass
        else:
            raise AssertionError("backend revision mismatch was not rejected")
        allowed = analyze(
            mismatch_session,
            mismatch_result,
            thresholds=empty_thresholds,
            allow_backend_revision_mismatch=True,
        )
        assert allowed["source_contract"]["revision_mismatch_allowed"] is True

        malformed = root / "malformed.txt"
        malformed.write_text("Normalized Residuals\n", encoding="utf-8")
        try:
            parse_kalibr_results_text(malformed.read_text(encoding="utf-8"), source=str(malformed))
        except QualityError:
            pass
        else:
            raise AssertionError("missing physical section was not rejected")

        markdown = render_markdown(analyze(session, result, thresholds=passing))
        assert "Physical residuals" in markdown
        assert "cam1" in markdown
        assert "PASS" in markdown

    print("Kalibr IMU-camera solver quality self-test: PASS")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("results_imucam", nargs="?", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--allow-backend-revision-mismatch", action="store_true")
    parser.add_argument("--max-reprojection-mean-px", type=float)
    parser.add_argument("--max-reprojection-rms-px", type=float)
    parser.add_argument("--max-gyro-mean-rad-s", type=float)
    parser.add_argument("--max-gyro-rms-rad-s", type=float)
    parser.add_argument("--max-accel-mean-m-s2", type=float)
    parser.add_argument("--max-accel-rms-m-s2", type=float)
    parser.add_argument("--max-normalized-reprojection-mean", type=float)
    parser.add_argument("--max-normalized-gyro-mean", type=float)
    parser.add_argument("--max-normalized-accel-mean", type=float)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.session is None or args.results_imucam is None:
        print("session and results_imucam are required", file=sys.stderr)
        return 2

    thresholds = {
        "max_reprojection_mean_px": args.max_reprojection_mean_px,
        "max_reprojection_rms_px": args.max_reprojection_rms_px,
        "max_gyro_mean_rad_s": args.max_gyro_mean_rad_s,
        "max_gyro_rms_rad_s": args.max_gyro_rms_rad_s,
        "max_accel_mean_m_s2": args.max_accel_mean_m_s2,
        "max_accel_rms_m_s2": args.max_accel_rms_m_s2,
        "max_normalized_reprojection_mean": args.max_normalized_reprojection_mean,
        "max_normalized_gyro_mean": args.max_normalized_gyro_mean,
        "max_normalized_accel_mean": args.max_normalized_accel_mean,
    }
    try:
        session = args.session.resolve()
        results = args.results_imucam.resolve()
        report = analyze(
            session,
            results,
            thresholds=thresholds,
            allow_backend_revision_mismatch=args.allow_backend_revision_mismatch,
        )
        prefix = args.output_prefix
        if prefix is None:
            stem = results.name
            if stem.endswith(".txt"):
                stem = stem[:-4]
            prefix = results.parent / f"{stem}.solver-quality"
        json_path = Path(f"{prefix}.json")
        md_path = Path(f"{prefix}.md")
        json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(render_markdown(report), encoding="utf-8")
    except (QualityError, OSError) as exc:
        print(f"Kalibr solver quality analysis failed: {exc}", file=sys.stderr)
        return 3

    print(json.dumps({
        "json": str(json_path),
        "markdown": str(md_path),
        "status": report["assessment"]["status"],
    }, indent=2))
    return 7 if report["assessment"]["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())