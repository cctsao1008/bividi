#!/usr/bin/env python3
"""Compare two Bividi Nori characterization v2 summaries.

The comparator is deliberately offline and dependency-free. It treats the
characterizer JSON as measurement evidence, preserves provenance differences,
and avoids inventing performance acceptance limits. Optional numeric gates are
only applied when the caller explicitly supplies thresholds.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_SCHEMA = "bividi.nori.characterization.v2"
REPORT_SCHEMA = "bividi.nori.comparison.v1"


@dataclass
class Finding:
    severity: str
    code: str
    message: str


@dataclass
class Metric:
    name: str
    baseline: float | int | None
    candidate: float | int | None
    delta: float | None
    delta_pct: float | None
    interpretation: str


def nested(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def number(data: dict[str, Any], path: str) -> float | None:
    value = nested(data, path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def integer(data: dict[str, Any], path: str) -> int | None:
    value = nested(data, path)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def metric(name: str, baseline: float | int | None, candidate: float | int | None,
           interpretation: str) -> Metric:
    delta: float | None = None
    delta_pct: float | None = None
    if baseline is not None and candidate is not None:
        delta = float(candidate) - float(baseline)
        if float(baseline) != 0.0:
            delta_pct = delta / abs(float(baseline)) * 100.0
    return Metric(name, baseline, candidate, delta, delta_pct, interpretation)


def load_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    schema = data.get("schema")
    if schema != SUPPORTED_SCHEMA:
        raise ValueError(
            f"{path} schema is {schema!r}; expected {SUPPORTED_SCHEMA!r}"
        )
    return data


def same_mode(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, list[str]]:
    fields = ("width", "height", "nominal_fps", "transport", "bottom_up")
    mismatches: list[str] = []
    for field in fields:
        av = nested(a, f"mode.{field}")
        bv = nested(b, f"mode.{field}")
        if av != bv:
            mismatches.append(f"{field}: {av!r} -> {bv!r}")
    return not mismatches, mismatches


def add_counter_regression(
    findings: list[Finding], baseline: dict[str, Any], candidate: dict[str, Any],
    path: str, label: str,
) -> None:
    before = integer(baseline, path)
    after = integer(candidate, path)
    if before is None or after is None:
        findings.append(Finding("warn", "missing_counter", f"{label}: missing numeric evidence"))
        return
    if after > before:
        findings.append(Finding(
            "warn", "correctness_regression",
            f"{label} increased from {before} to {after}",
        ))


def pct_drop(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before <= 0.0:
        return None
    return max(0.0, (before - after) / before * 100.0)


def pct_increase(before: float | None, after: float | None) -> float | None:
    if before is None or after is None or before <= 0.0:
        return None
    return max(0.0, (after - before) / before * 100.0)


def apply_optional_gate(
    findings: list[Finding], code: str, label: str,
    observed: float | None, limit: float | None, unit: str = "%",
) -> None:
    if limit is None:
        return
    if observed is None:
        findings.append(Finding("warn", "gate_missing_evidence", f"{label}: cannot evaluate configured gate"))
        return
    if observed > limit:
        findings.append(Finding(
            "fail", code,
            f"{label} is {observed:.3f}{unit}, exceeding configured limit {limit:.3f}{unit}",
        ))


def compare(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allow_mode_change: bool = False,
    max_fps_drop_pct: float | None = None,
    max_host_p99_increase_pct: float | None = None,
    max_es_p99_increase_pct: float | None = None,
    max_imu_p99_increase_pct: float | None = None,
    max_recovery_p95_increase_pct: float | None = None,
    max_rss_growth_delta_mib_per_hour: float | None = None,
) -> dict[str, Any]:
    findings: list[Finding] = []

    comparable, mode_mismatches = same_mode(baseline, candidate)
    if not comparable:
        severity = "warn" if allow_mode_change else "fail"
        findings.append(Finding(
            severity,
            "mode_mismatch",
            "mode differs: " + "; ".join(mode_mismatches),
        ))

    baseline_assessment = nested(baseline, "assessment", "unknown")
    candidate_assessment = nested(candidate, "assessment", "unknown")
    if candidate_assessment == "fail":
        findings.append(Finding("fail", "candidate_failed", "candidate characterizer assessment is fail"))
    elif candidate_assessment == "warn":
        findings.append(Finding("warn", "candidate_warn", "candidate characterizer assessment is warn"))
    elif candidate_assessment != "pass":
        findings.append(Finding("warn", "unknown_assessment", f"candidate assessment is {candidate_assessment!r}"))

    if nested(candidate, "run.fatal_fault", False) is True:
        findings.append(Finding("fail", "fatal_fault", "candidate run recorded fatal_fault=true"))

    for path, label in (
        ("fault_injection.operation_failures", "fault operation failures"),
        ("fault_injection.recovery_failures", "fault recovery failures"),
        ("fault_injection.unrecovered_events", "unrecovered fault events"),
    ):
        value = integer(candidate, path)
        if value is None:
            findings.append(Finding("warn", "missing_fault_evidence", f"{label}: missing numeric evidence"))
        elif value != 0:
            findings.append(Finding("fail", "fault_failure", f"{label}={value}"))

    for path, label in (
        ("run.timeouts", "timeouts"),
        ("run.max_timeout_streak", "maximum timeout streak"),
        ("run.decode_errors", "decode errors"),
        ("run.max_decode_error_streak", "maximum decode-error streak"),
        ("run.mode_mismatches", "mode mismatches"),
        ("run.sdk_timestamp_encoding_changes", "SDK timestamp-encoding changes"),
        ("sequence_within_active_epochs.drops", "spontaneous sequence drops"),
        ("sequence_within_active_epochs.duplicates", "duplicate sequence observations"),
        ("sequence_within_active_epochs.out_of_order", "out-of-order sequence observations"),
    ):
        add_counter_regression(findings, baseline, candidate, path, label)

    provenance_fields = (
        "device.vendor_id", "device.product_id", "device.serial", "device.sdk_version",
        "device.device_type", "device.isp_version", "device.fpga_version",
    )
    provenance_changes: dict[str, dict[str, Any]] = {}
    for path in provenance_fields:
        before = nested(baseline, path)
        after = nested(candidate, path)
        if before != after:
            provenance_changes[path] = {"baseline": before, "candidate": after}

    metric_specs = (
        ("measured_fps", "run.measured_fps", "higher is generally better"),
        ("host_interval_p99_us", "distributions.host_interval_us.p99", "lower is generally better"),
        ("sdk_interval_p99_us", "distributions.sdk_interval_us.p99", "lower is generally better"),
        ("exposure_start_interval_p99_us", "distributions.exposure_start_interval_us.p99", "lower jitter is generally better"),
        ("exposure_end_interval_p99_us", "distributions.exposure_end_interval_us.p99", "lower jitter is generally better"),
        ("imu_interval_p99_us", "distributions.imu_interval_us.p99", "lower jitter is generally better"),
        ("recovery_p95_ms", "fault_injection.recovery_latency_ms.p95", "lower is better when comparable fault trials exist"),
        ("rss_growth_mib_per_hour", "memory.growth_mib_per_hour", "descriptive until an explicit limit is configured"),
    )
    metrics = [
        metric(name, number(baseline, path), number(candidate, path), interpretation)
        for name, path, interpretation in metric_specs
    ]

    fps_before = number(baseline, "run.measured_fps")
    fps_after = number(candidate, "run.measured_fps")
    host_before = number(baseline, "distributions.host_interval_us.p99")
    host_after = number(candidate, "distributions.host_interval_us.p99")
    es_before = number(baseline, "distributions.exposure_start_interval_us.p99")
    es_after = number(candidate, "distributions.exposure_start_interval_us.p99")
    imu_before = number(baseline, "distributions.imu_interval_us.p99")
    imu_after = number(candidate, "distributions.imu_interval_us.p99")
    rec_before = number(baseline, "fault_injection.recovery_latency_ms.p95")
    rec_after = number(candidate, "fault_injection.recovery_latency_ms.p95")
    rss_before = number(baseline, "memory.growth_mib_per_hour")
    rss_after = number(candidate, "memory.growth_mib_per_hour")

    apply_optional_gate(findings, "fps_gate", "measured FPS drop",
                        pct_drop(fps_before, fps_after), max_fps_drop_pct)
    apply_optional_gate(findings, "host_p99_gate", "host interval p99 increase",
                        pct_increase(host_before, host_after), max_host_p99_increase_pct)
    apply_optional_gate(findings, "es_p99_gate", "ES interval p99 increase",
                        pct_increase(es_before, es_after), max_es_p99_increase_pct)
    apply_optional_gate(findings, "imu_p99_gate", "IMU interval p99 increase",
                        pct_increase(imu_before, imu_after), max_imu_p99_increase_pct)

    baseline_recovery_count = integer(baseline, "fault_injection.recovery_latency_ms.count")
    candidate_recovery_count = integer(candidate, "fault_injection.recovery_latency_ms.count")
    if max_recovery_p95_increase_pct is not None:
        if not baseline_recovery_count or not candidate_recovery_count:
            findings.append(Finding(
                "warn", "recovery_gate_not_comparable",
                "recovery p95 gate configured but one run has no recovered fault samples",
            ))
        else:
            apply_optional_gate(
                findings, "recovery_p95_gate", "recovery latency p95 increase",
                pct_increase(rec_before, rec_after), max_recovery_p95_increase_pct,
            )

    rss_delta = None
    if rss_before is not None and rss_after is not None:
        rss_delta = rss_after - rss_before
    apply_optional_gate(
        findings, "rss_growth_gate", "RSS growth-slope delta",
        rss_delta, max_rss_growth_delta_mib_per_hour, " MiB/h",
    )

    severity_rank = {"pass": 0, "warn": 1, "fail": 2}
    verdict = "pass"
    for finding in findings:
        if severity_rank[finding.severity] > severity_rank[verdict]:
            verdict = finding.severity

    return {
        "schema": REPORT_SCHEMA,
        "verdict": verdict,
        "comparable_mode": comparable,
        "baseline_assessment": baseline_assessment,
        "candidate_assessment": candidate_assessment,
        "mode_mismatches": mode_mismatches,
        "provenance_changes": provenance_changes,
        "findings": [asdict(item) for item in findings],
        "metrics": [asdict(item) for item in metrics],
        "policy": {
            "note": "No performance limit is invented by default. Numeric gates only apply when explicitly configured.",
            "max_fps_drop_pct": max_fps_drop_pct,
            "max_host_p99_increase_pct": max_host_p99_increase_pct,
            "max_es_p99_increase_pct": max_es_p99_increase_pct,
            "max_imu_p99_increase_pct": max_imu_p99_increase_pct,
            "max_recovery_p95_increase_pct": max_recovery_p95_increase_pct,
            "max_rss_growth_delta_mib_per_hour": max_rss_growth_delta_mib_per_hour,
        },
    }


def fmt_value(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{value:.6g}"


def render_markdown(report: dict[str, Any], baseline_name: str, candidate_name: str) -> str:
    lines = [
        "# Nori Characterization Comparison",
        "",
        f"- Baseline: `{baseline_name}`",
        f"- Candidate: `{candidate_name}`",
        f"- Verdict: **{str(report['verdict']).upper()}**",
        f"- Comparable mode: **{'yes' if report['comparable_mode'] else 'no'}**",
        "",
        "## Findings",
        "",
    ]
    findings = report["findings"]
    if not findings:
        lines.append("No correctness or configured-gate regression was detected.")
    else:
        for item in findings:
            lines.append(f"- **{item['severity'].upper()}** `{item['code']}` — {item['message']}")

    lines += [
        "",
        "## Key metrics",
        "",
        "| Metric | Baseline | Candidate | Delta | Delta % | Interpretation |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["metrics"]:
        delta_pct = "n/a" if item["delta_pct"] is None else f"{item['delta_pct']:+.3f}%"
        delta = "n/a" if item["delta"] is None else f"{item['delta']:+.6g}"
        lines.append(
            f"| {item['name']} | {fmt_value(item['baseline'])} | {fmt_value(item['candidate'])} | "
            f"{delta} | {delta_pct} | {item['interpretation']} |"
        )

    lines += ["", "## Provenance changes", ""]
    changes = report["provenance_changes"]
    if not changes:
        lines.append("No tracked device/firmware provenance field changed.")
    else:
        for key, values in changes.items():
            lines.append(f"- `{key}`: `{values['baseline']}` → `{values['candidate']}`")

    lines += [
        "",
        "## Policy",
        "",
        report["policy"]["note"],
        "",
    ]
    return "\n".join(lines)


def sample_summary() -> dict[str, Any]:
    return {
        "schema": SUPPORTED_SCHEMA,
        "assessment": "pass",
        "device": {
            "vendor_id": 1, "product_id": 2, "serial": "A", "sdk_version": "1",
            "device_type": "AR0234", "isp_version": "I1", "fpga_version": "F1",
        },
        "mode": {
            "width": 4000, "height": 1200, "nominal_fps": 60,
            "transport": "MJPEG", "bottom_up": False,
        },
        "run": {
            "measured_fps": 59.9, "timeouts": 0, "max_timeout_streak": 0,
            "decode_errors": 0, "max_decode_error_streak": 0,
            "mode_mismatches": 0, "sdk_timestamp_encoding_changes": 0,
            "fatal_fault": False,
        },
        "sequence_within_active_epochs": {
            "drops": 0, "duplicates": 0, "out_of_order": 0,
        },
        "fault_injection": {
            "operation_failures": 0, "recovery_failures": 0, "unrecovered_events": 0,
            "recovery_latency_ms": {"count": 2, "p95": 40.0},
        },
        "memory": {"growth_mib_per_hour": 0.5},
        "distributions": {
            "host_interval_us": {"p99": 17000.0},
            "sdk_interval_us": {"p99": 16700.0},
            "exposure_start_interval_us": {"p99": 16700.0},
            "exposure_end_interval_us": {"p99": 16700.0},
            "imu_interval_us": {"p99": 1600.0},
        },
    }


def self_test() -> None:
    baseline = sample_summary()
    same = copy.deepcopy(baseline)
    assert compare(baseline, same)["verdict"] == "pass"

    warn = copy.deepcopy(baseline)
    warn["run"]["timeouts"] = 1
    assert compare(baseline, warn)["verdict"] == "warn"

    failed = copy.deepcopy(baseline)
    failed["assessment"] = "fail"
    failed["fault_injection"]["recovery_failures"] = 1
    assert compare(baseline, failed)["verdict"] == "fail"

    mode = copy.deepcopy(baseline)
    mode["mode"]["transport"] = "YUYV"
    assert compare(baseline, mode)["verdict"] == "fail"
    assert compare(baseline, mode, allow_mode_change=True)["verdict"] == "warn"

    perf = copy.deepcopy(baseline)
    perf["run"]["measured_fps"] = 50.0
    assert compare(baseline, perf, max_fps_drop_pct=5.0)["verdict"] == "fail"

    with tempfile.TemporaryDirectory() as tmp:
        base_path = Path(tmp) / "base.json"
        cand_path = Path(tmp) / "cand.json"
        base_path.write_text(json.dumps(baseline), encoding="utf-8")
        cand_path.write_text(json.dumps(same), encoding="utf-8")
        assert load_summary(base_path)["schema"] == SUPPORTED_SCHEMA
        assert load_summary(cand_path)["assessment"] == "pass"

    print("compare_nori_characterization self-test: PASS")


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two bividi.nori.characterization.v2 JSON summaries",
    )
    parser.add_argument("baseline", nargs="?", type=Path)
    parser.add_argument("candidate", nargs="?", type=Path)
    parser.add_argument("--allow-mode-change", action="store_true",
                        help="downgrade mode mismatch from FAIL to WARN")
    parser.add_argument("--max-fps-drop-pct", type=nonnegative_float)
    parser.add_argument("--max-host-p99-increase-pct", type=nonnegative_float)
    parser.add_argument("--max-es-p99-increase-pct", type=nonnegative_float)
    parser.add_argument("--max-imu-p99-increase-pct", type=nonnegative_float)
    parser.add_argument("--max-recovery-p95-increase-pct", type=nonnegative_float)
    parser.add_argument("--max-rss-growth-delta-mib-per-hour", type=nonnegative_float)
    parser.add_argument("--json-out", type=Path, help="write machine-readable comparison JSON")
    parser.add_argument("--markdown-out", type=Path, help="write Markdown comparison report")
    parser.add_argument("--fail-on-warn", action="store_true",
                        help="return non-zero for WARN as well as FAIL")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        self_test()
        return 0
    if args.baseline is None or args.candidate is None:
        print("baseline and candidate JSON files are required", file=sys.stderr)
        return 3

    try:
        baseline = load_summary(args.baseline)
        candidate = load_summary(args.candidate)
        report = compare(
            baseline,
            candidate,
            allow_mode_change=args.allow_mode_change,
            max_fps_drop_pct=args.max_fps_drop_pct,
            max_host_p99_increase_pct=args.max_host_p99_increase_pct,
            max_es_p99_increase_pct=args.max_es_p99_increase_pct,
            max_imu_p99_increase_pct=args.max_imu_p99_increase_pct,
            max_recovery_p95_increase_pct=args.max_recovery_p95_increase_pct,
            max_rss_growth_delta_mib_per_hour=args.max_rss_growth_delta_mib_per_hour,
        )
    except ValueError as exc:
        print(f"compare_nori_characterization: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report, str(args.baseline), str(args.candidate))
    print(markdown)

    if args.json_out is not None:
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown_out is not None:
        args.markdown_out.write_text(markdown + "\n", encoding="utf-8")

    if report["verdict"] == "fail":
        return 2
    if report["verdict"] == "warn" and args.fail_on_warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
