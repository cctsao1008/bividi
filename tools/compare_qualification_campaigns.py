#!/usr/bin/env python3
"""Compare two AR0234 qualification campaign manifests stage-by-stage.

This tool composes the existing per-run Nori characterization comparator. It
adds campaign-level provenance and stage coverage checks without changing the
measurement semantics or inventing acceptance thresholds.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import compare_nori_characterization as run_compare

CAMPAIGN_SCHEMA = "bividi.nori.qualification_campaign.v1"
REPORT_SCHEMA = "bividi.nori.qualification_comparison.v1"
SEVERITY_RANK = {"pass": 0, "warn": 1, "fail": 2}


@dataclass
class Finding:
    severity: str
    code: str
    message: str


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if data.get("schema") != CAMPAIGN_SCHEMA:
        raise ValueError(
            f"{path} schema is {data.get('schema')!r}; expected {CAMPAIGN_SCHEMA!r}"
        )
    if not isinstance(data.get("stages"), list):
        raise ValueError(f"{path} has no stage list")
    return data


def stage_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in manifest.get("stages", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            result[name] = item
    return result


def resolve_artifact(manifest_path: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    # Campaigns are intended to be portable as directories. If the runner
    # recorded a repository-relative path, the basename still identifies the
    # stage summary next to campaign.json after the directory is moved.
    sibling = manifest_path.parent / path.name
    if sibling.exists():
        return sibling
    return path


def campaign_provenance(manifest: dict[str, Any]) -> dict[str, Any]:
    host = manifest.get("host") if isinstance(manifest.get("host"), dict) else {}
    repository = (
        manifest.get("repository") if isinstance(manifest.get("repository"), dict) else {}
    )
    selection = (
        manifest.get("selection") if isinstance(manifest.get("selection"), dict) else {}
    )
    return {
        "campaign_id": manifest.get("campaign_id"),
        "created_utc": manifest.get("created_utc"),
        "git_revision": repository.get("git_revision"),
        "hostname": host.get("hostname"),
        "platform": host.get("platform"),
        "system": host.get("system"),
        "release": host.get("release"),
        "machine": host.get("machine"),
        "device_index": selection.get("device"),
        "mode_index": selection.get("mode"),
        "nominal_fps": selection.get("nominal_fps"),
        "fault_period_s": selection.get("fault_period_s"),
    }


def compare_campaigns(
    baseline_path: Path,
    candidate_path: Path,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    requested_stages: list[str] | None,
    allow_missing_stages: bool,
    allow_mode_change: bool,
    max_fps_drop_pct: float | None,
    max_host_p99_increase_pct: float | None,
    max_es_p99_increase_pct: float | None,
    max_imu_p99_increase_pct: float | None,
    max_recovery_p95_increase_pct: float | None,
    max_rss_growth_delta_mib_per_hour: float | None,
) -> dict[str, Any]:
    findings: list[Finding] = []
    baseline_stages = stage_index(baseline)
    candidate_stages = stage_index(candidate)

    if requested_stages is None:
        names = sorted(set(baseline_stages) | set(candidate_stages))
    else:
        names = requested_stages

    stage_reports: dict[str, Any] = {}
    overall = "pass"

    for name in names:
        before = baseline_stages.get(name)
        after = candidate_stages.get(name)
        if before is None or after is None:
            severity = "warn" if allow_missing_stages else "fail"
            missing = []
            if before is None:
                missing.append("baseline")
            if after is None:
                missing.append("candidate")
            finding = Finding(
                severity,
                "missing_stage",
                f"stage {name} missing from {', '.join(missing)} campaign",
            )
            findings.append(finding)
            if SEVERITY_RANK[severity] > SEVERITY_RANK[overall]:
                overall = severity
            stage_reports[name] = {
                "verdict": severity,
                "status": "missing",
                "missing_from": missing,
            }
            continue

        baseline_summary = resolve_artifact(baseline_path, before.get("summary_json"))
        candidate_summary = resolve_artifact(candidate_path, after.get("summary_json"))
        if baseline_summary is None or candidate_summary is None:
            severity = "warn" if allow_missing_stages else "fail"
            findings.append(Finding(
                severity,
                "missing_summary_path",
                f"stage {name} does not record both summary JSON paths",
            ))
            if SEVERITY_RANK[severity] > SEVERITY_RANK[overall]:
                overall = severity
            stage_reports[name] = {
                "verdict": severity,
                "status": "missing_summary_path",
            }
            continue

        try:
            baseline_run = run_compare.load_summary(baseline_summary)
            candidate_run = run_compare.load_summary(candidate_summary)
            report = run_compare.compare(
                baseline_run,
                candidate_run,
                allow_mode_change=allow_mode_change,
                max_fps_drop_pct=max_fps_drop_pct,
                max_host_p99_increase_pct=max_host_p99_increase_pct,
                max_es_p99_increase_pct=max_es_p99_increase_pct,
                max_imu_p99_increase_pct=max_imu_p99_increase_pct,
                max_recovery_p95_increase_pct=max_recovery_p95_increase_pct,
                max_rss_growth_delta_mib_per_hour=max_rss_growth_delta_mib_per_hour,
            )
        except ValueError as exc:
            findings.append(Finding("fail", "invalid_stage_evidence", f"stage {name}: {exc}"))
            stage_reports[name] = {
                "verdict": "fail",
                "status": "invalid_stage_evidence",
                "error": str(exc),
                "baseline_summary": str(baseline_summary),
                "candidate_summary": str(candidate_summary),
            }
            overall = "fail"
            continue

        stage_reports[name] = {
            "status": "compared",
            "baseline_summary": str(baseline_summary),
            "candidate_summary": str(candidate_summary),
            "report": report,
            "verdict": report["verdict"],
        }
        if SEVERITY_RANK[report["verdict"]] > SEVERITY_RANK[overall]:
            overall = report["verdict"]

    baseline_provenance = campaign_provenance(baseline)
    candidate_provenance = campaign_provenance(candidate)
    provenance_changes: dict[str, dict[str, Any]] = {}
    for key in baseline_provenance:
        before = baseline_provenance[key]
        after = candidate_provenance.get(key)
        if before != after:
            provenance_changes[key] = {"baseline": before, "candidate": after}

    # Campaign host/revision changes are evidence, not automatic failures.
    if provenance_changes:
        findings.append(Finding(
            "warn",
            "campaign_provenance_changed",
            "campaign provenance differs; interpret stage deltas with the recorded host/revision changes",
        ))
        if overall == "pass":
            overall = "warn"

    return {
        "schema": REPORT_SCHEMA,
        "verdict": overall,
        "baseline_manifest": str(baseline_path),
        "candidate_manifest": str(candidate_path),
        "baseline_provenance": baseline_provenance,
        "candidate_provenance": candidate_provenance,
        "provenance_changes": provenance_changes,
        "findings": [asdict(item) for item in findings],
        "stages": stage_reports,
        "policy": {
            "allow_missing_stages": allow_missing_stages,
            "allow_mode_change": allow_mode_change,
            "note": (
                "Per-stage numeric gates are delegated to compare_nori_characterization; "
                "no additional campaign-level performance limit is invented."
            ),
            "max_fps_drop_pct": max_fps_drop_pct,
            "max_host_p99_increase_pct": max_host_p99_increase_pct,
            "max_es_p99_increase_pct": max_es_p99_increase_pct,
            "max_imu_p99_increase_pct": max_imu_p99_increase_pct,
            "max_recovery_p95_increase_pct": max_recovery_p95_increase_pct,
            "max_rss_growth_delta_mib_per_hour": max_rss_growth_delta_mib_per_hour,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AR0234 Qualification Campaign Comparison",
        "",
        f"- Baseline: `{report['baseline_manifest']}`",
        f"- Candidate: `{report['candidate_manifest']}`",
        f"- Verdict: **{str(report['verdict']).upper()}**",
        "",
        "## Stage verdicts",
        "",
        "| Stage | Verdict | Baseline | Candidate |",
        "| --- | --- | --- | --- |",
    ]
    for name, item in sorted(report["stages"].items()):
        lines.append(
            f"| {name} | **{str(item.get('verdict', 'unknown')).upper()}** | "
            f"`{item.get('baseline_summary', 'n/a')}` | `{item.get('candidate_summary', 'n/a')}` |"
        )

    lines += ["", "## Campaign findings", ""]
    if not report["findings"]:
        lines.append("No campaign-level structural/provenance finding was detected.")
    else:
        for item in report["findings"]:
            lines.append(f"- **{item['severity'].upper()}** `{item['code']}` — {item['message']}")

    lines += ["", "## Provenance changes", ""]
    if not report["provenance_changes"]:
        lines.append("No tracked campaign provenance field changed.")
    else:
        for key, values in sorted(report["provenance_changes"].items()):
            lines.append(f"- `{key}`: `{values['baseline']}` → `{values['candidate']}`")

    lines += ["", "## Per-stage details", ""]
    for name, item in sorted(report["stages"].items()):
        lines += [f"### {name.upper()}", ""]
        if item.get("status") != "compared":
            lines.append(f"Stage was not compared: `{item.get('status', 'unknown')}`.")
            lines.append("")
            continue
        child = item["report"]
        findings = child.get("findings", [])
        if findings:
            for finding in findings:
                lines.append(
                    f"- **{finding['severity'].upper()}** `{finding['code']}` — {finding['message']}"
                )
        else:
            lines.append("No per-run correctness or configured-gate regression was detected.")
        lines.append("")
        lines.append("| Metric | Baseline | Candidate | Delta % |")
        lines.append("| --- | ---: | ---: | ---: |")
        for metric in child.get("metrics", []):
            pct = "n/a" if metric.get("delta_pct") is None else f"{metric['delta_pct']:+.3f}%"
            lines.append(
                f"| {metric['name']} | {run_compare.fmt_value(metric.get('baseline'))} | "
                f"{run_compare.fmt_value(metric.get('candidate'))} | {pct} |"
            )
        lines.append("")

    return "\n".join(lines)


def parse_stage_filter(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError("stage filter must not be empty")
    if len(names) != len(set(names)):
        raise argparse.ArgumentTypeError("duplicate stages are not allowed")
    return names


def sample_manifest(summary_paths: dict[str, Path], *, revision: str = "abc") -> dict[str, Any]:
    return {
        "schema": CAMPAIGN_SCHEMA,
        "campaign_id": "sample",
        "created_utc": "2026-09-16T00:00:00+00:00",
        "host": {
            "hostname": "host",
            "platform": "test-platform",
            "system": "TestOS",
            "release": "1",
            "machine": "x86_64",
        },
        "repository": {"git_revision": revision},
        "selection": {"device": 0, "mode": 0, "nominal_fps": 60.0, "fault_period_s": 60.0},
        "stages": [
            {
                "name": name,
                "purpose": name,
                "summary_json": str(path),
                "return_code": 0,
                "assessment": "pass",
            }
            for name, path in summary_paths.items()
        ],
    }


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base_summary = root / "base_q1.json"
        cand_summary = root / "cand_q1.json"
        base_summary.write_text(json.dumps(run_compare.sample_summary()), encoding="utf-8")
        cand_summary.write_text(json.dumps(run_compare.sample_summary()), encoding="utf-8")

        base_manifest = sample_manifest({"q1": base_summary})
        cand_manifest = sample_manifest({"q1": cand_summary})
        base_path = root / "base_campaign.json"
        cand_path = root / "cand_campaign.json"
        base_path.write_text(json.dumps(base_manifest), encoding="utf-8")
        cand_path.write_text(json.dumps(cand_manifest), encoding="utf-8")

        report = compare_campaigns(
            base_path,
            cand_path,
            load_manifest(base_path),
            load_manifest(cand_path),
            requested_stages=None,
            allow_missing_stages=False,
            allow_mode_change=False,
            max_fps_drop_pct=None,
            max_host_p99_increase_pct=None,
            max_es_p99_increase_pct=None,
            max_imu_p99_increase_pct=None,
            max_recovery_p95_increase_pct=None,
            max_rss_growth_delta_mib_per_hour=None,
        )
        assert report["verdict"] == "pass"
        assert report["stages"]["q1"]["verdict"] == "pass"

        degraded = copy.deepcopy(run_compare.sample_summary())
        degraded["run"]["timeouts"] = 2
        cand_summary.write_text(json.dumps(degraded), encoding="utf-8")
        report = compare_campaigns(
            base_path,
            cand_path,
            load_manifest(base_path),
            load_manifest(cand_path),
            requested_stages=["q1"],
            allow_missing_stages=False,
            allow_mode_change=False,
            max_fps_drop_pct=None,
            max_host_p99_increase_pct=None,
            max_es_p99_increase_pct=None,
            max_imu_p99_increase_pct=None,
            max_recovery_p95_increase_pct=None,
            max_rss_growth_delta_mib_per_hour=None,
        )
        assert report["verdict"] == "warn"

        different_revision = sample_manifest({"q1": cand_summary}, revision="def")
        cand_path.write_text(json.dumps(different_revision), encoding="utf-8")
        report = compare_campaigns(
            base_path,
            cand_path,
            load_manifest(base_path),
            load_manifest(cand_path),
            requested_stages=["q1"],
            allow_missing_stages=False,
            allow_mode_change=False,
            max_fps_drop_pct=None,
            max_host_p99_increase_pct=None,
            max_es_p99_increase_pct=None,
            max_imu_p99_increase_pct=None,
            max_recovery_p95_increase_pct=None,
            max_rss_growth_delta_mib_per_hour=None,
        )
        assert report["verdict"] == "warn"
        assert "git_revision" in report["provenance_changes"]

    print("AR0234 qualification campaign comparator self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compare two AR0234 qualification campaign manifests")
    p.add_argument("baseline", nargs="?", type=Path)
    p.add_argument("candidate", nargs="?", type=Path)
    p.add_argument("--stages", type=parse_stage_filter,
                   help="optional comma-separated stage subset")
    p.add_argument("--allow-missing-stages", action="store_true",
                   help="downgrade missing-stage FAIL to WARN")
    p.add_argument("--allow-mode-change", action="store_true")
    p.add_argument("--max-fps-drop-pct", type=run_compare.nonnegative_float)
    p.add_argument("--max-host-p99-increase-pct", type=run_compare.nonnegative_float)
    p.add_argument("--max-es-p99-increase-pct", type=run_compare.nonnegative_float)
    p.add_argument("--max-imu-p99-increase-pct", type=run_compare.nonnegative_float)
    p.add_argument("--max-recovery-p95-increase-pct", type=run_compare.nonnegative_float)
    p.add_argument("--max-rss-growth-delta-mib-per-hour", type=run_compare.nonnegative_float)
    p.add_argument("--json-out", type=Path)
    p.add_argument("--markdown-out", type=Path)
    p.add_argument("--fail-on-warn", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.self_test:
        return self_test()
    if args.baseline is None or args.candidate is None:
        print("baseline and candidate campaign manifests are required", file=sys.stderr)
        return 3

    try:
        baseline = load_manifest(args.baseline)
        candidate = load_manifest(args.candidate)
        report = compare_campaigns(
            args.baseline,
            args.candidate,
            baseline,
            candidate,
            requested_stages=args.stages,
            allow_missing_stages=args.allow_missing_stages,
            allow_mode_change=args.allow_mode_change,
            max_fps_drop_pct=args.max_fps_drop_pct,
            max_host_p99_increase_pct=args.max_host_p99_increase_pct,
            max_es_p99_increase_pct=args.max_es_p99_increase_pct,
            max_imu_p99_increase_pct=args.max_imu_p99_increase_pct,
            max_recovery_p95_increase_pct=args.max_recovery_p95_increase_pct,
            max_rss_growth_delta_mib_per_hour=args.max_rss_growth_delta_mib_per_hour,
        )
    except ValueError as exc:
        print(f"compare_qualification_campaigns: {exc}", file=sys.stderr)
        return 3

    markdown = render_markdown(report)
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
