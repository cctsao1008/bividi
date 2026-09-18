#!/usr/bin/env python3
"""Compare declared IMU configuration against measured calibration evidence.

The analyzer consumes a Bividi IMU calibration-session manifest plus the analysis
JSON files already bound into that manifest. It does not read sensor registers
and therefore does not claim hardware configuration readback. Instead it checks
whether independently measured response is consistent with operator-declared
accelerometer range, gyroscope range, and output-data rate.

No pass/fail tolerance is invented by default. Optional explicit thresholds can
turn the evidence report into a gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

MANIFEST_SCHEMA = "bividi.calibration.imu_session_manifest.v1"
SIXPOS_SCHEMA = "bividi.calibration.imu_six_position_analysis.v1"
GYRO_SCHEMA = "bividi.calibration.imu_gyro_rotation_analysis.v1"
STATIONARY_SCHEMA = "bividi.calibration.imu_stationary_analysis.v1"
ALLAN_SCHEMA = "bividi.calibration.imu_allan_analysis.v1"
REPORT_SCHEMA = "bividi.calibration.imu_config_consistency.v1"
SIGNED_RAW_FULL_SCALE_COUNTS = 32768.0
AXES = ("x", "y", "z")


class ConsistencyError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConsistencyError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConsistencyError(f"{path}: expected a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConsistencyError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ConsistencyError(f"{label} must be finite and > 0")
    return result


def resolve_bound_analysis(
    manifest: dict[str, Any],
    manifest_path: Path,
    role: str,
    expected_schema: str,
) -> tuple[Path, dict[str, Any]] | None:
    entries = manifest.get("analysis")
    if not isinstance(entries, list):
        raise ConsistencyError("manifest.analysis must be an array")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("role") == role]
    if not matches:
        return None
    if len(matches) != 1:
        raise ConsistencyError(f"manifest has multiple analysis entries for role {role!r}")
    entry = matches[0]
    path_text = entry.get("path")
    digest = entry.get("sha256")
    if not isinstance(path_text, str) or not path_text:
        raise ConsistencyError(f"analysis role {role!r} has no path")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ConsistencyError(f"analysis role {role!r} has invalid SHA-256")
    path = Path(path_text)
    if not path.is_absolute():
        path = (manifest_path.parent / path).resolve()
    if not path.is_file():
        raise ConsistencyError(f"bound analysis for role {role!r} does not exist: {path}")
    observed_hash = sha256_file(path)
    if observed_hash != digest:
        raise ConsistencyError(
            f"bound analysis hash mismatch for role {role!r}: expected {digest}, observed {observed_hash}"
        )
    data = load_json(path)
    if data.get("schema") != expected_schema:
        raise ConsistencyError(
            f"analysis role {role!r} expected schema {expected_schema!r}, observed {data.get('schema')!r}"
        )
    return path, data


def pct_error(measured: float, expected: float) -> float:
    return 100.0 * (measured - expected) / expected


def summarize_values(values: Sequence[float]) -> dict[str, Any] | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return {
        "count": len(clean),
        "minimum": min(clean),
        "maximum": max(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "spread_pct_of_mean": (
            100.0 * (max(clean) - min(clean)) / statistics.fmean(clean)
            if statistics.fmean(clean) != 0.0 else None
        ),
    }


def accelerometer_scale_evidence(sixpos: dict[str, Any], declared_range_g: float) -> dict[str, Any]:
    mapping = sixpos.get("accelerometer_axis_mapping")
    if not isinstance(mapping, dict):
        raise ConsistencyError("six-position report lacks accelerometer_axis_mapping")
    values = mapping.get("counts_per_g_column_l2")
    if not isinstance(values, dict):
        raise ConsistencyError("six-position report lacks counts_per_g_column_l2")
    measured: dict[str, float] = {}
    for axis in AXES:
        measured[axis] = finite_positive(values.get(axis), f"six-position counts/g {axis}")

    expected = SIGNED_RAW_FULL_SCALE_COUNTS / declared_range_g
    per_axis = {
        axis: {
            "measured_counts_per_g": measured[axis],
            "expected_counts_per_g_from_declared_range": expected,
            "signed_error_pct": pct_error(measured[axis], expected),
            "absolute_error_pct": abs(pct_error(measured[axis], expected)),
        }
        for axis in AXES
    }
    errors = [per_axis[axis]["absolute_error_pct"] for axis in AXES]
    return {
        "available": True,
        "declared_accelerometer_range_g": declared_range_g,
        "quantizer_model": "signed 16-bit raw field: 32768 magnitude counts at declared full-scale",
        "expected_counts_per_g": expected,
        "measured_counts_per_g": measured,
        "per_axis": per_axis,
        "maximum_absolute_error_pct": max(errors),
        "measured_summary": summarize_values(list(measured.values())),
        "interpretation": (
            "This is a response-consistency check, not register readback. Fixture alignment, sensor scale error, "
            "and cross-axis coupling contribute to the measured six-position result."
        ),
    }


def gyro_scale_evidence(gyro: dict[str, Any], declared_range_dps: float) -> dict[str, Any]:
    model = gyro.get("rotation_model")
    if not isinstance(model, dict):
        raise ConsistencyError("gyro-rotation report lacks rotation_model")
    sensitivity = model.get("sensitivity_raw_counts_per_rad_s_matrix")
    if sensitivity is None:
        return {
            "available": False,
            "declared_gyroscope_range_dps": declared_range_dps,
            "reason": (
                "gyro report has no absolute sensitivity matrix; rerun controlled rotation with a trusted "
                "--expected-angle-deg reference before judging declared range"
            ),
        }
    if not isinstance(sensitivity, list) or len(sensitivity) != 3:
        raise ConsistencyError("gyro sensitivity matrix must be 3x3")
    matrix: list[list[float]] = []
    for row_index, row in enumerate(sensitivity):
        if not isinstance(row, list) or len(row) != 3:
            raise ConsistencyError("gyro sensitivity matrix must be 3x3")
        converted: list[float] = []
        for col_index, value in enumerate(row):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ConsistencyError(f"gyro sensitivity[{row_index}][{col_index}] must be finite numeric")
            converted.append(float(value))
        matrix.append(converted)

    # Column L2 is invariant to axis permutation/sign and is therefore a useful
    # scale magnitude check even before the target/raw frame mapping is frozen.
    measured = {
        axis: math.sqrt(sum(matrix[row][col] ** 2 for row in range(3)))
        for col, axis in enumerate(AXES)
    }
    expected_counts_per_rad_s = (
        SIGNED_RAW_FULL_SCALE_COUNTS / declared_range_dps * (180.0 / math.pi)
    )
    per_axis = {
        axis: {
            "measured_counts_per_rad_s": measured[axis],
            "expected_counts_per_rad_s_from_declared_range": expected_counts_per_rad_s,
            "signed_error_pct": pct_error(measured[axis], expected_counts_per_rad_s),
            "absolute_error_pct": abs(pct_error(measured[axis], expected_counts_per_rad_s)),
        }
        for axis in AXES
    }
    errors = [per_axis[axis]["absolute_error_pct"] for axis in AXES]
    return {
        "available": True,
        "declared_gyroscope_range_dps": declared_range_dps,
        "quantizer_model": "signed 16-bit raw field: 32768 magnitude counts at declared full-scale",
        "expected_counts_per_rad_s": expected_counts_per_rad_s,
        "measured_counts_per_rad_s": measured,
        "per_axis": per_axis,
        "maximum_absolute_error_pct": max(errors),
        "measured_summary": summarize_values(list(measured.values())),
        "interpretation": (
            "Absolute gyro scale is only available because the controlled-rotation analysis used an explicit "
            "trusted commanded-angle reference. This remains a response-consistency check, not register readback."
        ),
    }


def append_rate(values: list[dict[str, Any]], label: str, value: Any, declared_hz: float) -> None:
    if value is None:
        return
    measured = finite_positive(value, f"{label} effective rate")
    error = pct_error(measured, declared_hz)
    values.append({
        "source": label,
        "measured_hz": measured,
        "declared_hz": declared_hz,
        "signed_error_pct": error,
        "absolute_error_pct": abs(error),
    })


def odr_evidence(
    declared_hz: float,
    stationary: dict[str, Any] | None,
    allan: dict[str, Any] | None,
    sixpos: dict[str, Any] | None,
    gyro: dict[str, Any] | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if stationary is not None:
        append_rate(entries, "stationary", stationary.get("effective_rate_hz"), declared_hz)
    if allan is not None:
        sample_period = allan.get("sample_period")
        if isinstance(sample_period, dict):
            append_rate(entries, "allan", sample_period.get("rate_hz"), declared_hz)
    if sixpos is not None:
        poses = sixpos.get("poses")
        if isinstance(poses, dict):
            for pose, summary in poses.items():
                timing = summary.get("timing") if isinstance(summary, dict) else None
                if isinstance(timing, dict):
                    append_rate(entries, f"six_position:{pose}", timing.get("effective_rate_hz"), declared_hz)
    if gyro is not None:
        baseline = gyro.get("stationary_baseline")
        timing = baseline.get("timing") if isinstance(baseline, dict) else None
        if isinstance(timing, dict):
            append_rate(entries, "gyro_rotation:stationary", timing.get("effective_rate_hz"), declared_hz)
        runs = gyro.get("runs")
        if isinstance(runs, dict):
            for run, summary in runs.items():
                timing = summary.get("timing") if isinstance(summary, dict) else None
                if isinstance(timing, dict):
                    append_rate(entries, f"gyro_rotation:{run}", timing.get("effective_rate_hz"), declared_hz)

    if not entries:
        return {
            "available": False,
            "declared_output_data_rate_hz": declared_hz,
            "reason": "no bound analysis report contained an effective-rate measurement",
        }
    measured_values = [float(entry["measured_hz"]) for entry in entries]
    return {
        "available": True,
        "declared_output_data_rate_hz": declared_hz,
        "measurements": entries,
        "measured_summary_hz": summarize_values(measured_values),
        "maximum_absolute_error_pct": max(float(entry["absolute_error_pct"]) for entry in entries),
        "interpretation": (
            "ODR evidence is derived from extended device IMU timestamps. It does not use host receive cadence "
            "or camera FPS as a substitute for IMU sample rate."
        ),
    }


def threshold_finding(name: str, evidence: dict[str, Any], threshold: float | None) -> dict[str, Any] | None:
    if threshold is None:
        return None
    if not evidence.get("available"):
        return {
            "severity": "incomplete",
            "check": name,
            "message": f"explicit {name} threshold supplied but required measured evidence is unavailable",
        }
    observed = float(evidence["maximum_absolute_error_pct"])
    if observed > threshold:
        return {
            "severity": "fail",
            "check": name,
            "observed_max_error_pct": observed,
            "limit_pct": threshold,
            "message": f"{name} maximum absolute error exceeds explicit limit",
        }
    return {
        "severity": "pass",
        "check": name,
        "observed_max_error_pct": observed,
        "limit_pct": threshold,
        "message": f"{name} maximum absolute error is within explicit limit",
    }


def analyze(
    manifest_path: Path,
    *,
    max_accel_scale_error_pct: float | None,
    max_gyro_scale_error_pct: float | None,
    max_odr_error_pct: float | None,
    require_gyro_scale: bool,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ConsistencyError(
            f"manifest schema must be {MANIFEST_SCHEMA!r}; observed {manifest.get('schema')!r}"
        )
    imu = manifest.get("imu_configuration")
    if not isinstance(imu, dict):
        raise ConsistencyError("manifest has no imu_configuration object")
    accel_range = finite_positive(imu.get("accelerometer_range_g"), "declared accelerometer range")
    gyro_range = finite_positive(imu.get("gyroscope_range_dps"), "declared gyroscope range")
    odr = finite_positive(imu.get("output_data_rate_hz"), "declared output data rate")

    sixpos_bound = resolve_bound_analysis(manifest, manifest_path, "six_position", SIXPOS_SCHEMA)
    gyro_bound = resolve_bound_analysis(manifest, manifest_path, "gyro_rotation", GYRO_SCHEMA)
    stationary_bound = resolve_bound_analysis(manifest, manifest_path, "stationary", STATIONARY_SCHEMA)
    allan_bound = resolve_bound_analysis(manifest, manifest_path, "allan", ALLAN_SCHEMA)

    if sixpos_bound is None:
        raise ConsistencyError("manifest has no bound six_position analysis; accelerometer range cannot be checked")

    sixpos_path, sixpos = sixpos_bound
    gyro_path, gyro = gyro_bound if gyro_bound is not None else (None, None)
    stationary_path, stationary = stationary_bound if stationary_bound is not None else (None, None)
    allan_path, allan = allan_bound if allan_bound is not None else (None, None)

    accel_evidence = accelerometer_scale_evidence(sixpos, accel_range)
    gyro_evidence = (
        gyro_scale_evidence(gyro, gyro_range)
        if gyro is not None
        else {
            "available": False,
            "declared_gyroscope_range_dps": gyro_range,
            "reason": "manifest has no bound gyro_rotation analysis",
        }
    )
    odr_result = odr_evidence(odr, stationary, allan, sixpos, gyro)

    findings = [
        item for item in (
            threshold_finding("accelerometer_scale", accel_evidence, max_accel_scale_error_pct),
            threshold_finding("gyroscope_scale", gyro_evidence, max_gyro_scale_error_pct),
            threshold_finding("output_data_rate", odr_result, max_odr_error_pct),
        ) if item is not None
    ]
    if require_gyro_scale and not gyro_evidence.get("available"):
        findings.append({
            "severity": "fail",
            "check": "gyroscope_scale",
            "message": "--require-gyro-scale was requested but absolute gyro scale evidence is unavailable",
        })

    if any(item["severity"] == "fail" for item in findings):
        status = "FAIL"
    elif any(item["severity"] == "incomplete" for item in findings):
        status = "INCOMPLETE"
    elif findings:
        status = "PASS"
    else:
        status = "EVIDENCE_ONLY_NO_THRESHOLDS"

    bound_sources = {
        "six_position": str(sixpos_path),
        "gyro_rotation": str(gyro_path) if gyro_path is not None else None,
        "stationary": str(stationary_path) if stationary_path is not None else None,
        "allan": str(allan_path) if allan_path is not None else None,
    }
    return {
        "schema": REPORT_SCHEMA,
        "manifest": str(manifest_path),
        "session_id": manifest.get("session_id"),
        "declared_configuration": {
            "accelerometer_range_g": accel_range,
            "gyroscope_range_dps": gyro_range,
            "output_data_rate_hz": odr,
            "accelerometer_filter": imu.get("accelerometer_filter"),
            "gyroscope_filter": imu.get("gyroscope_filter"),
            "configuration_source": imu.get("configuration_source"),
        },
        "bound_analysis": bound_sources,
        "accelerometer_range_consistency": accel_evidence,
        "gyroscope_range_consistency": gyro_evidence,
        "output_data_rate_consistency": odr_result,
        "filter_configuration": {
            "physically_verified": False,
            "accelerometer_filter_declared": imu.get("accelerometer_filter"),
            "gyroscope_filter_declared": imu.get("gyroscope_filter"),
            "note": (
                "These experiments do not uniquely identify filter register settings. Filter values remain "
                "configuration provenance unless a hardware/API readback or separate transfer-function experiment is added."
            ),
        },
        "thresholds": {
            "max_accel_scale_error_pct": max_accel_scale_error_pct,
            "max_gyro_scale_error_pct": max_gyro_scale_error_pct,
            "max_odr_error_pct": max_odr_error_pct,
            "require_gyro_scale": require_gyro_scale,
        },
        "findings": findings,
        "status": status,
        "guardrails": [
            "This tool checks declared configuration against measured physical response; it is not sensor-register readback.",
            "The 32768-count expectation follows the signed 16-bit raw packet representation used by the DECXIN decoder.",
            "No tolerance is invented by default; PASS/FAIL only occurs when the operator supplies an explicit threshold or requirement.",
            "Accelerometer scale evidence inherits six-position fixture/alignment uncertainty.",
            "Gyroscope scale evidence requires a trusted commanded-angle reference and inherits turntable/fixture uncertainty.",
            "IMU ODR is evaluated from device timestamps, not host arrival time or camera FPS.",
            "Filter settings are not claimed physically verified by scale/ODR experiments.",
        ],
    }


def fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    accel = report["accelerometer_range_consistency"]
    gyro = report["gyroscope_range_consistency"]
    odr = report["output_data_rate_consistency"]
    lines = [
        "# IMU Configuration Consistency Laboratory",
        "",
        f"Status: **{report['status']}**",
        f"Session: `{report.get('session_id')}`",
        "",
        "## Declared configuration",
        "",
        f"- Accelerometer range: ±{fmt(report['declared_configuration']['accelerometer_range_g'])} g",
        f"- Gyroscope range: ±{fmt(report['declared_configuration']['gyroscope_range_dps'])} dps",
        f"- Output data rate: {fmt(report['declared_configuration']['output_data_rate_hz'])} Hz",
        f"- Accelerometer filter: `{report['declared_configuration'].get('accelerometer_filter')}`",
        f"- Gyroscope filter: `{report['declared_configuration'].get('gyroscope_filter')}`",
        "",
        "## Accelerometer scale consistency",
        "",
        f"Expected from declared range: {fmt(accel['expected_counts_per_g'])} counts/g",
        "",
        "| Target axis | measured counts/g | error (%) |",
        "| --- | ---: | ---: |",
    ]
    for axis in AXES:
        item = accel["per_axis"][axis]
        lines.append(f"| {axis} | {fmt(item['measured_counts_per_g'])} | {fmt(item['signed_error_pct'])} |")

    lines += ["", "## Gyroscope scale consistency", ""]
    if gyro.get("available"):
        lines += [
            f"Expected from declared range: {fmt(gyro['expected_counts_per_rad_s'])} counts/(rad/s)",
            "",
            "| Target axis | measured counts/(rad/s) | error (%) |",
            "| --- | ---: | ---: |",
        ]
        for axis in AXES:
            item = gyro["per_axis"][axis]
            lines.append(
                f"| {axis} | {fmt(item['measured_counts_per_rad_s'])} | {fmt(item['signed_error_pct'])} |"
            )
    else:
        lines.append(f"Unavailable: {gyro.get('reason')}")

    lines += ["", "## Output-data-rate consistency", ""]
    if odr.get("available"):
        lines += [
            "| Evidence source | measured Hz | error (%) |",
            "| --- | ---: | ---: |",
        ]
        for item in odr["measurements"]:
            lines.append(
                f"| {item['source']} | {fmt(item['measured_hz'])} | {fmt(item['signed_error_pct'])} |"
            )
    else:
        lines.append(f"Unavailable: {odr.get('reason')}")

    lines += [
        "",
        "## Filter configuration boundary",
        "",
        report["filter_configuration"]["note"],
        "",
        "## Explicit gate findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- **{finding['severity'].upper()}** `{finding['check']}` — {finding['message']}")
    else:
        lines.append("- No numeric gate thresholds were supplied; this report is evidence-only.")
    lines += ["", "## Guardrails", ""]
    lines.extend(f"- {item}" for item in report["guardrails"])
    return "\n".join(lines)


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be numeric") from exc
    if not math.isfinite(value) or value <= 0.0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        accel_range = 4.0
        gyro_range = 1000.0
        odr = 200.0
        expected_accel = SIGNED_RAW_FULL_SCALE_COUNTS / accel_range
        expected_gyro = SIGNED_RAW_FULL_SCALE_COUNTS / gyro_range * 180.0 / math.pi

        sixpos = {
            "schema": SIXPOS_SCHEMA,
            "accelerometer_axis_mapping": {
                "counts_per_g_column_l2": {axis: expected_accel for axis in AXES}
            },
            "poses": {
                pose: {"timing": {"effective_rate_hz": odr}}
                for pose in ("plus_x", "minus_x", "plus_y", "minus_y", "plus_z", "minus_z")
            },
        }
        gyro_matrix = [
            [expected_gyro, 0.0, 0.0],
            [0.0, expected_gyro, 0.0],
            [0.0, 0.0, expected_gyro],
        ]
        gyro = {
            "schema": GYRO_SCHEMA,
            "stationary_baseline": {"timing": {"effective_rate_hz": odr}},
            "runs": {
                run: {"timing": {"effective_rate_hz": odr}}
                for run in ("plus_x", "minus_x", "plus_y", "minus_y", "plus_z", "minus_z")
            },
            "rotation_model": {"sensitivity_raw_counts_per_rad_s_matrix": gyro_matrix},
        }
        stationary = {"schema": STATIONARY_SCHEMA, "effective_rate_hz": odr}
        allan = {"schema": ALLAN_SCHEMA, "sample_period": {"rate_hz": odr}}

        reports = {
            "six_position": (root / "sixpos.json", sixpos),
            "gyro_rotation": (root / "gyro.json", gyro),
            "stationary": (root / "stationary.json", stationary),
            "allan": (root / "allan.json", allan),
        }
        for path, data in reports.values():
            write_json(path, data)

        manifest_path = root / "manifest.json"
        analysis = []
        for role, (path, data) in reports.items():
            analysis.append({
                "role": role,
                "path": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "schema": data["schema"],
            })
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "session_id": "synthetic-config-consistency",
            "imu_configuration": {
                "model": "synthetic-imu",
                "frame": "imu",
                "accelerometer_range_g": accel_range,
                "gyroscope_range_dps": gyro_range,
                "output_data_rate_hz": odr,
                "accelerometer_filter": "synthetic",
                "gyroscope_filter": "synthetic",
                "configuration_source": "synthetic fixture",
            },
            "analysis": analysis,
        }
        write_json(manifest_path, manifest)

        report = analyze(
            manifest_path,
            max_accel_scale_error_pct=0.01,
            max_gyro_scale_error_pct=0.01,
            max_odr_error_pct=0.01,
            require_gyro_scale=True,
        )
        assert report["status"] == "PASS"
        assert report["accelerometer_range_consistency"]["maximum_absolute_error_pct"] < 1e-10
        assert report["gyroscope_range_consistency"]["maximum_absolute_error_pct"] < 1e-10
        assert report["output_data_rate_consistency"]["maximum_absolute_error_pct"] < 1e-10
        assert "IMU Configuration Consistency" in render_markdown(report)

        manifest["imu_configuration"]["output_data_rate_hz"] = 100.0
        write_json(manifest_path, manifest)
        failed = analyze(
            manifest_path,
            max_accel_scale_error_pct=None,
            max_gyro_scale_error_pct=None,
            max_odr_error_pct=5.0,
            require_gyro_scale=False,
        )
        assert failed["status"] == "FAIL"

        # Hash binding must catch a post-manifest analysis mutation.
        stationary["effective_rate_hz"] = 199.0
        write_json(reports["stationary"][0], stationary)
        try:
            analyze(
                manifest_path,
                max_accel_scale_error_pct=None,
                max_gyro_scale_error_pct=None,
                max_odr_error_pct=None,
                require_gyro_scale=False,
            )
            raise AssertionError("hash mutation was not rejected")
        except ConsistencyError as exc:
            assert "hash mismatch" in str(exc)

    print("IMU configuration consistency laboratory self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare declared IMU range/ODR against bound six-position, gyro-rotation, and timestamp evidence"
    )
    parser.add_argument("manifest", nargs="?", type=Path, help="bividi.calibration.imu_session_manifest.v1 JSON")
    parser.add_argument("--max-accel-scale-error-pct", type=positive_float)
    parser.add_argument("--max-gyro-scale-error-pct", type=positive_float)
    parser.add_argument("--max-odr-error-pct", type=positive_float)
    parser.add_argument("--require-gyro-scale", action="store_true")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.manifest is None:
        print("manifest path is required", file=sys.stderr)
        return 3
    try:
        report = analyze(
            args.manifest,
            max_accel_scale_error_pct=args.max_accel_scale_error_pct,
            max_gyro_scale_error_pct=args.max_gyro_scale_error_pct,
            max_odr_error_pct=args.max_odr_error_pct,
            require_gyro_scale=args.require_gyro_scale,
        )
    except ConsistencyError as exc:
        print(f"analyze_imu_config_consistency: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report)
    print(markdown)
    json_out = args.json_out
    markdown_out = args.markdown_out
    if args.output_prefix is not None:
        json_out = json_out or Path(str(args.output_prefix) + ".config.json")
        markdown_out = markdown_out or Path(str(args.output_prefix) + ".config.md")
    if json_out is not None:
        write_json(json_out, report)
    if markdown_out is not None:
        markdown_out.write_text(markdown + "\n", encoding="utf-8")
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
