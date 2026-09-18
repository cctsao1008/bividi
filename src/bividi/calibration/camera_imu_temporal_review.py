#!/usr/bin/env python3
"""Review a Kalibr camera-IMU time shift against DECXIN device-time evidence.

This tool does not reinterpret nearest IMU samples as a calibrated time offset.
It verifies provenance, applies the imported Kalibr shift to the exact camera
timestamp semantic used by the staged session, and reports nearest-sample
geometry before/after that shift. Optional explicit thresholds can catch gross
sign/unit/semantic mistakes without inventing default acceptance criteria.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import artifact_validator as validate_calibration_artifact
from . import imu_timing as audit_imu_timing

SESSION_SCHEMA = "bividi.calibration.kalibr_dynamic_session.v1"
ARTIFACT_SCHEMA = "bividi.calibration.camera_imu.v1"
REPORT_SCHEMA = "bividi.calibration.camera_imu_time_review.v1"
TIME_OFFSET_DEFINITION = "t_imu_s = t_camera_reference_s + offset_s"


class ReviewError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError(f"{path}: expected JSON object")
    return data


def source_path(session: dict[str, Any], session_path: Path, key: str) -> Path:
    sources = session.get("sources")
    if not isinstance(sources, dict) or not isinstance(sources.get(key), dict):
        raise ReviewError(f"{session_path}: missing sources.{key}")
    entry = sources[key]
    raw = entry.get("path")
    expected = entry.get("sha256")
    if not isinstance(raw, str) or not isinstance(expected, str):
        raise ReviewError(f"{session_path}: sources.{key} requires path and sha256")
    path = Path(raw)
    if not path.is_absolute():
        path = (session_path.parent / path).resolve()
    if not path.is_file():
        raise ReviewError(f"missing source: {path}")
    if sha256_file(path) != expected:
        raise ReviewError(f"{session_path}: sources.{key} SHA-256 mismatch")
    return path


def nearest_delta_float(sorted_timestamps: list[int], reference_us: float) -> float | None:
    if not sorted_timestamps:
        return None
    index = bisect.bisect_left(sorted_timestamps, reference_us)
    candidates: list[int] = []
    if index < len(sorted_timestamps):
        candidates.append(sorted_timestamps[index])
    if index > 0:
        candidates.append(sorted_timestamps[index - 1])
    nearest = min(candidates, key=lambda value: (abs(float(value) - reference_us), value))
    return float(nearest) - reference_us


def distribution(values: Iterable[float]) -> dict[str, Any]:
    return audit_imu_timing.asdict(audit_imu_timing.summarize(values))


def camera_reference(frame: audit_imu_timing.FrameTiming, kind: str) -> float:
    if kind == "exposure_start":
        return float(frame.es_us)
    if kind == "exposure_end":
        return float(frame.ee_us)
    if kind == "exposure_midpoint":
        return 0.5 * (float(frame.es_us) + float(frame.ee_us))
    raise ReviewError(f"unsupported camera timestamp semantic {kind!r}")


def analyze(
    session_path: Path,
    artifact_path: Path,
    *,
    max_abs_shift_us: float | None,
    max_shifted_nearest_p95_us: float | None,
) -> dict[str, Any]:
    session = load_json(session_path)
    artifact = load_json(artifact_path)
    if session.get("schema") != SESSION_SCHEMA:
        raise ReviewError(f"{session_path}: expected {SESSION_SCHEMA!r}")
    if artifact.get("schema") != ARTIFACT_SCHEMA:
        raise ReviewError(f"{artifact_path}: expected {ARTIFACT_SCHEMA!r}")
    findings = validate_calibration_artifact.validate(artifact)
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        raise ReviewError("camera-IMU artifact fails validation: " + "; ".join(f"{f.path}: {f.message}" for f in errors))

    provenance = artifact.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("source_hash") != sha256_file(session_path):
        raise ReviewError("camera-IMU artifact provenance.source_hash does not match supplied dynamic session")
    session_time = session.get("camera_time_reference")
    artifact_time = artifact.get("time_offset")
    if not isinstance(session_time, dict) or not isinstance(artifact_time, dict):
        raise ReviewError("session/artifact time-offset metadata missing")
    if artifact_time.get("definition") != TIME_OFFSET_DEFINITION:
        raise ReviewError("camera-IMU artifact uses incompatible time-offset definition")
    semantic = artifact_time.get("camera_time_reference")
    if semantic != session_time.get("kind"):
        raise ReviewError(
            f"timestamp semantic mismatch: session={session_time.get('kind')!r}, artifact={semantic!r}"
        )
    try:
        shift_s = float(artifact_time["offset_s"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewError("camera-IMU artifact has invalid offset_s") from exc
    if not math.isfinite(shift_s):
        raise ReviewError("camera-IMU offset must be finite")
    shift_us = shift_s * 1_000_000.0

    raw_imu = source_path(session, session_path, "raw_imu_csv")
    frames, sample_pairs, invalid_samples = audit_imu_timing.load_trace(raw_imu)
    if not frames or not sample_pairs:
        raise ReviewError("dynamic session has no camera/IMU timing evidence")
    imu_times_file_order = [item[0] for item in sample_pairs]
    sorted_imu = sorted(set(imu_times_file_order))
    intervals = [after - before for before, after in zip(imu_times_file_order, imu_times_file_order[1:])]
    positive_intervals = [float(value) for value in intervals if value > 0]

    references = [camera_reference(frame, str(semantic)) for frame in frames]
    before = [nearest_delta_float(sorted_imu, reference) for reference in references]
    after = [nearest_delta_float(sorted_imu, reference + shift_us) for reference in references]
    before_values = [value for value in before if value is not None]
    after_values = [value for value in after if value is not None]
    exposure = [float(frame.ee_us - frame.es_us) for frame in frames]

    gates: list[dict[str, Any]] = []
    failed = False
    if max_abs_shift_us is not None:
        passed = abs(shift_us) <= max_abs_shift_us
        gates.append({"name": "max_abs_shift_us", "limit": max_abs_shift_us, "observed": abs(shift_us), "passed": passed})
        failed |= not passed
    shifted_abs = distribution(abs(value) for value in after_values)
    if max_shifted_nearest_p95_us is not None:
        observed = shifted_abs.get("p95")
        passed = observed is not None and float(observed) <= max_shifted_nearest_p95_us
        gates.append({"name": "max_shifted_nearest_p95_us", "limit": max_shifted_nearest_p95_us, "observed": observed, "passed": passed})
        failed |= not passed

    status = "FAIL" if failed else ("PASS" if gates else "EVIDENCE_ONLY_NO_THRESHOLDS")
    return {
        "schema": REPORT_SCHEMA,
        "status": status,
        "dynamic_session": {"path": str(session_path), "sha256": sha256_file(session_path)},
        "camera_imu_artifact": {"path": str(artifact_path), "sha256": sha256_file(artifact_path)},
        "source_trace": {"path": str(raw_imu), "sha256": sha256_file(raw_imu)},
        "clock_domain": "DECXIN extended device microseconds",
        "camera_time_reference": semantic,
        "time_offset": {
            "definition": TIME_OFFSET_DEFINITION,
            "kalibr_offset_s": shift_s,
            "kalibr_offset_us": shift_us,
        },
        "samples": {
            "camera_frames": len(frames),
            "valid_imu_samples": len(sample_pairs),
            "invalid_imu_samples": invalid_samples,
        },
        "imu_interval_us": distribution(positive_intervals),
        "exposure_duration_us": distribution(exposure),
        "nearest_imu_before_shift": {
            "signed_imu_minus_camera_us": distribution(before_values),
            "absolute_us": distribution(abs(value) for value in before_values),
        },
        "nearest_imu_after_applying_kalibr_shift": {
            "signed_imu_minus_shifted_camera_us": distribution(after_values),
            "absolute_us": shifted_abs,
        },
        "gates": gates,
        "interpretation": [
            "Kalibr offset is applied using exactly the camera timestamp semantic recorded by the dynamic-session export.",
            "Nearest-sample residuals are discrete sampling geometry, not an independent estimator of the physical camera-IMU time offset.",
            "A small shifted nearest-sample residual can catch gross sign/unit/semantic errors but cannot prove the Kalibr offset because sample-period aliases are possible.",
            "No vendor synchronization claim is used as a default pass/fail threshold.",
            "Review Kalibr solver quality, target detection, motion excitation, protocol timing evidence, and repeatability before promotion to a VIO accuracy claim.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    before = report["nearest_imu_before_shift"]["absolute_us"]
    after = report["nearest_imu_after_applying_kalibr_shift"]["absolute_us"]
    lines = [
        "# Camera↔IMU Temporal Evidence Review",
        "",
        f"Status: `{report['status']}`",
        f"Camera timestamp semantic: `{report['camera_time_reference']}`",
        f"Kalibr shift: {fmt(report['time_offset']['kalibr_offset_us'])} us",
        "",
        "| Evidence | P50 (us) | P95 (us) | P99 (us) | Max (us) |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| IMU interval | {fmt(report['imu_interval_us']['p50'])} | {fmt(report['imu_interval_us']['p95'])} | {fmt(report['imu_interval_us']['p99'])} | {fmt(report['imu_interval_us']['maximum'])} |",
        f"| Nearest IMU before shift | {fmt(before['p50'])} | {fmt(before['p95'])} | {fmt(before['p99'])} | {fmt(before['maximum'])} |",
        f"| Nearest IMU after shift | {fmt(after['p50'])} | {fmt(after['p95'])} | {fmt(after['p99'])} | {fmt(after['maximum'])} |",
        "",
        "## Explicit gates",
        "",
    ]
    if report["gates"]:
        for gate in report["gates"]:
            lines.append(f"- `{gate['name']}`: observed={fmt(gate['observed'])}, limit={fmt(gate['limit'])}, passed={gate['passed']}")
    else:
        lines.append("- None. Report is evidence-only.")
    lines += ["", "## Interpretation guardrails", ""]
    lines.extend(f"- {item}" for item in report["interpretation"])
    return "\n".join(lines)


def write_fixture(root: Path) -> tuple[Path, Path]:
    trace = root / "imu.csv"
    audit_imu_timing.write_fixture(trace)
    session = root / "session.json"
    session.write_text(json.dumps({
        "schema": SESSION_SCHEMA,
        "session_id": "synthetic",
        "camera_time_reference": {"kind": "exposure_midpoint", "time_shift_definition": TIME_OFFSET_DEFINITION},
        "sources": {"raw_imu_csv": {"path": str(trace), "sha256": sha256_file(trace)}},
    }), encoding="utf-8")
    artifact = root / "camera-imu.json"
    artifact.write_text(json.dumps({
        "schema": ARTIFACT_SCHEMA,
        "calibration_id": "synthetic",
        "created_utc": "2026-09-17T00:00:00+00:00",
        "device": {"model": "synthetic", "serial": "SYNTHETIC"},
        "camera_reference": {"camera_id": "camera_a", "frame": "camera_a"},
        "imu_reference": {"model": "synthetic", "frame": "imu"},
        "transform": {"from_frame": "imu", "to_frame": "camera_a", "matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]], "translation_unit": "m"},
        "time_offset": {"definition": TIME_OFFSET_DEFINITION, "camera_time_reference": "exposure_midpoint", "offset_s": 0.00025},
        "frames": {"handedness": "right", "camera_axes": "synthetic", "imu_axes": "synthetic"},
        "provenance": {"kind": "imported", "tool": "synthetic", "source_hash": sha256_file(session), "external_backend": "ethz-asl/kalibr"},
    }), encoding="utf-8")
    return session, artifact


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session, artifact = write_fixture(Path(tmp))
        report = analyze(session, artifact, max_abs_shift_us=None, max_shifted_nearest_p95_us=None)
        assert report["status"] == "EVIDENCE_ONLY_NO_THRESHOLDS"
        assert abs(report["time_offset"]["kalibr_offset_us"] - 250.0) < 1e-12
        failed = analyze(session, artifact, max_abs_shift_us=100.0, max_shifted_nearest_p95_us=None)
        assert failed["status"] == "FAIL"
    print("Camera-IMU temporal evidence review self-test: PASS")


def positive_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError("value must be finite and > 0")
    return value


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("artifact", nargs="?", type=Path)
    parser.add_argument("--max-abs-shift-us", type=positive_float)
    parser.add_argument("--max-shifted-nearest-p95-us", type=positive_float)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.session is None or args.artifact is None:
        print("review_camera_imu_time_offset: session and artifact paths are required", file=sys.stderr)
        return 2
    try:
        report = analyze(
            args.session.resolve(),
            args.artifact.resolve(),
            max_abs_shift_us=args.max_abs_shift_us,
            max_shifted_nearest_p95_us=args.max_shifted_nearest_p95_us,
        )
    except ReviewError as exc:
        print(f"review_camera_imu_time_offset: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(report, indent=2) + "\n"
    markdown = render_markdown(report) + "\n"
    if args.output_prefix is None:
        print(text, end="")
        print(markdown, end="")
    else:
        args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        args.output_prefix.with_suffix(".json").write_text(text, encoding="utf-8")
        args.output_prefix.with_suffix(".md").write_text(markdown, encoding="utf-8")
    return 3 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
