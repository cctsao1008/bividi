#!/usr/bin/env python3
"""Run a repeatable DECXIN AR0234 / Nori qualification campaign.

The runner is intentionally an orchestration layer, not a measurement engine.
`bividi-nori-characterize` remains authoritative for per-run capture evidence.
This tool makes staged runs reproducible, records host/revision provenance, and
keeps software recovery trials distinct from physical USB/power fault tests.

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

CAMPAIGN_SCHEMA = "bividi.nori.qualification_campaign.v1"
CHARACTERIZATION_SCHEMA = "bividi.nori.characterization.v2"
DEFAULT_FAULT_PERIOD_S = 60.0


@dataclass(frozen=True)
class StageSpec:
    name: str
    purpose: str
    duration_s: float
    fault_kind: str | None = None


STAGES: dict[str, StageSpec] = {
    "q1": StageSpec("q1", "60-second baseline smoke", 60.0),
    "q2": StageSpec("q2", "10-minute sustained baseline", 600.0),
    "q3": StageSpec("q3", "one-hour soak / RSS stability", 3600.0),
    "q4": StageSpec("q4", "controlled VideoStop/VideoStart recovery", 600.0, "stop_start"),
    "q5": StageSpec("q5", "controlled SDK stream close/reopen recovery", 600.0, "reconnect"),
}


@dataclass
class StageResult:
    name: str
    purpose: str
    output_prefix: str
    command: list[str]
    started_utc: str | None = None
    finished_utc: str | None = None
    elapsed_s: float | None = None
    return_code: int | None = None
    assessment: str | None = None
    summary_json: str | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    note: str = ""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_token(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = value.strip("-._")
    return value or "unknown"


def default_campaign_id() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{safe_token(socket.gethostname())}"


def parse_stages(value: str) -> list[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError("at least one stage is required")
    unknown = [name for name in names if name not in STAGES]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown stage(s): {', '.join(unknown)}; choose from {', '.join(STAGES)}"
        )
    if len(names) != len(set(names)):
        raise argparse.ArgumentTypeError("duplicate stages are not allowed")
    return names


def positive_float(value: str) -> float:
    parsed = float(value)
    if not (parsed > 0.0):
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value, 10)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def git_revision() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def build_stage_command(
    *,
    characterizer: str,
    stage: StageSpec,
    device: int,
    mode: int,
    output_prefix: Path,
    warmup_frames: int,
    rss_sample_ms: int,
    timeout_ms: int,
    recovery_timeout_ms: int,
    nominal_fps: float | None,
    fault_period_s: float,
    stop_start_pause_ms: int,
    reconnect_pause_ms: int,
    no_trigger_config: bool,
) -> list[str]:
    command = [
        characterizer,
        "--device", str(device),
        "--mode", str(mode),
        "--duration-s", f"{stage.duration_s:g}",
        "--warmup-frames", str(warmup_frames),
        "--timeout-ms", str(timeout_ms),
        "--rss-sample-ms", str(rss_sample_ms),
        "--recovery-timeout-ms", str(recovery_timeout_ms),
        "--output-prefix", str(output_prefix),
    ]
    if no_trigger_config:
        command.append("--no-trigger-config")

    if stage.fault_kind is not None:
        if nominal_fps is None:
            raise ValueError(
                f"{stage.name} requires --nominal-fps so a time-like fault cadence can be "
                "converted to the characterizer's frame-based injection interval"
            )
        every_frames = max(1, int(round(nominal_fps * fault_period_s)))
        if stage.fault_kind == "stop_start":
            command += [
                "--stop-start-every-frames", str(every_frames),
                "--stop-start-pause-ms", str(stop_start_pause_ms),
            ]
        elif stage.fault_kind == "reconnect":
            command += [
                "--reconnect-every-frames", str(every_frames),
                "--reconnect-pause-ms", str(reconnect_pause_ms),
            ]
        else:
            raise ValueError(f"unsupported fault kind: {stage.fault_kind}")
    return command


def load_assessment(summary_path: Path) -> tuple[str | None, str]:
    if not summary_path.exists():
        return None, "summary JSON not produced"
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot parse summary JSON: {exc}"
    if not isinstance(data, dict):
        return None, "summary JSON root is not an object"
    if data.get("schema") != CHARACTERIZATION_SCHEMA:
        return None, f"unexpected summary schema: {data.get('schema')!r}"
    assessment = data.get("assessment")
    if assessment not in {"pass", "warn", "fail"}:
        return None, f"unexpected assessment: {assessment!r}"
    return assessment, ""


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_text(command: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(command))
    return shlex.join(command)


def make_manifest(
    *,
    campaign_id: str,
    created_utc: str,
    status: str,
    git_rev: str | None,
    args: argparse.Namespace,
    stage_results: list[StageResult],
    campaign_dir: Path,
    probe_result: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "schema": CAMPAIGN_SCHEMA,
        "campaign_id": campaign_id,
        "created_utc": created_utc,
        "updated_utc": utc_now(),
        "status": status,
        "dry_run": dry_run,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "repository": {"git_revision": git_rev},
        "selection": {
            "device": args.device,
            "mode": args.mode,
            "stages": args.stages,
            "nominal_fps": args.nominal_fps,
            "fault_period_s": args.fault_period_s,
        },
        "settings": {
            "warmup_frames": args.warmup_frames,
            "timeout_ms": args.timeout_ms,
            "rss_sample_ms": args.rss_sample_ms,
            "recovery_timeout_ms": args.recovery_timeout_ms,
            "stop_start_pause_ms": args.stop_start_pause_ms,
            "reconnect_pause_ms": args.reconnect_pause_ms,
            "no_trigger_config": args.no_trigger_config,
            "continue_on_failure": args.continue_on_failure,
        },
        "executables": {
            "probe": args.probe,
            "characterizer": args.characterizer,
        },
        "probe": probe_result,
        "stages": [asdict(result) for result in stage_results],
        "physical_faults": {
            "automated": False,
            "pending": [
                "Q6 physical USB unplug/replug",
                "Q7 optional hub reset / USB bus reset / device power cycle",
            ],
            "note": (
                "Physical transport/power faults are intentionally not emulated by the SDK "
                "close/reopen stage. Execute them under the documented operator protocol."
            ),
        },
        "campaign_directory": str(campaign_dir),
    }


def run_probe(executable: str, output_path: Path, dry_run: bool) -> dict[str, Any]:
    command = [executable]
    result: dict[str, Any] = {
        "command": command,
        "output": str(output_path),
        "started_utc": None,
        "finished_utc": None,
        "elapsed_s": None,
    }
    if dry_run:
        result.update({"return_code": None, "note": "dry-run; probe not executed"})
        return result

    result["started_utc"] = utc_now()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        text = completed.stdout
        result["return_code"] = completed.returncode
    except OSError as exc:
        text = f"failed to execute probe: {exc}\n"
        result["return_code"] = 127
    result["elapsed_s"] = time.monotonic() - started
    result["finished_utc"] = utc_now()
    output_path.write_text(text, encoding="utf-8")
    return result


def execute_stage(result: StageResult, dry_run: bool) -> None:
    summary_path = Path(result.output_prefix + ".json")
    stdout_path = Path(result.output_prefix + ".stdout.log")
    stderr_path = Path(result.output_prefix + ".stderr.log")
    result.summary_json = str(summary_path)
    result.stdout_log = str(stdout_path)
    result.stderr_log = str(stderr_path)

    if dry_run:
        result.note = "dry-run; stage not executed"
        return

    result.started_utc = utc_now()
    started = time.monotonic()
    try:
        completed = subprocess.run(
            result.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        result.return_code = completed.returncode
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
    except OSError as exc:
        result.return_code = 127
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(f"failed to execute characterizer: {exc}\n", encoding="utf-8")
    result.elapsed_s = time.monotonic() - started
    result.finished_utc = utc_now()
    result.assessment, result.note = load_assessment(summary_path)


def stage_failed(result: StageResult, dry_run: bool) -> bool:
    if dry_run:
        return False
    return result.return_code not in (0, None) or result.assessment is None


def self_test() -> int:
    q1 = build_stage_command(
        characterizer="characterizer",
        stage=STAGES["q1"],
        device=2,
        mode=3,
        output_prefix=Path("out/q1"),
        warmup_frames=30,
        rss_sample_ms=1000,
        timeout_ms=2000,
        recovery_timeout_ms=10000,
        nominal_fps=None,
        fault_period_s=60.0,
        stop_start_pause_ms=250,
        reconnect_pause_ms=500,
        no_trigger_config=False,
    )
    assert "--stop-start-every-frames" not in q1
    assert "--reconnect-every-frames" not in q1
    assert q1[q1.index("--device") + 1] == "2"
    assert q1[q1.index("--mode") + 1] == "3"

    q4 = build_stage_command(
        characterizer="characterizer",
        stage=STAGES["q4"],
        device=0,
        mode=1,
        output_prefix=Path("out/q4"),
        warmup_frames=30,
        rss_sample_ms=1000,
        timeout_ms=2000,
        recovery_timeout_ms=10000,
        nominal_fps=59.94,
        fault_period_s=60.0,
        stop_start_pause_ms=250,
        reconnect_pause_ms=500,
        no_trigger_config=True,
    )
    assert q4[q4.index("--stop-start-every-frames") + 1] == str(round(59.94 * 60.0))
    assert "--reconnect-every-frames" not in q4
    assert "--no-trigger-config" in q4

    try:
        build_stage_command(
            characterizer="characterizer",
            stage=STAGES["q5"],
            device=0,
            mode=0,
            output_prefix=Path("out/q5"),
            warmup_frames=30,
            rss_sample_ms=1000,
            timeout_ms=2000,
            recovery_timeout_ms=10000,
            nominal_fps=None,
            fault_period_s=60.0,
            stop_start_pause_ms=250,
            reconnect_pause_ms=500,
            no_trigger_config=False,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("fault stages must require nominal_fps")

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "summary.json"
        path.write_text(
            json.dumps({"schema": CHARACTERIZATION_SCHEMA, "assessment": "warn"}),
            encoding="utf-8",
        )
        assessment, note = load_assessment(path)
        assert assessment == "warn" and not note

        missing = StageResult("q1", "test", "missing", ["characterizer"])
        missing.return_code = 0
        missing.assessment = None
        assert stage_failed(missing, False)
        assert not stage_failed(missing, True)

    assert parse_stages("q1,q3,q5") == ["q1", "q3", "q5"]
    print("AR0234 qualification runner self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run staged AR0234/Nori qualification and write a campaign manifest."
    )
    p.add_argument("--device", type=nonnegative_int)
    p.add_argument("--mode", type=nonnegative_int)
    p.add_argument("--stages", type=parse_stages, default=["q1"],
                   help="comma-separated q1..q5 stages (default: q1)")
    p.add_argument("--nominal-fps", type=positive_float,
                   help="explicit probed nominal FPS; required for q4/q5 fault cadence")
    p.add_argument("--fault-period-s", type=positive_float, default=DEFAULT_FAULT_PERIOD_S,
                   help="desired q4/q5 fault cadence in seconds; converted to frames using --nominal-fps")
    p.add_argument("--warmup-frames", type=nonnegative_int, default=30)
    p.add_argument("--timeout-ms", type=nonnegative_int, default=2000)
    p.add_argument("--rss-sample-ms", type=nonnegative_int, default=1000)
    p.add_argument("--recovery-timeout-ms", type=nonnegative_int, default=10000)
    p.add_argument("--stop-start-pause-ms", type=nonnegative_int, default=250)
    p.add_argument("--reconnect-pause-ms", type=nonnegative_int, default=500)
    p.add_argument("--probe", default="bividi-nori-probe")
    p.add_argument("--characterizer", default="bividi-nori-characterize")
    p.add_argument("--skip-probe", action="store_true")
    p.add_argument("--no-trigger-config", action="store_true")
    p.add_argument("--continue-on-failure", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="write the plan/manifest without executing vendor tools")
    p.add_argument("--output-dir", type=Path, default=Path("qualification-runs"))
    p.add_argument("--campaign-id", default=None)
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()

    if args.device is None or args.mode is None:
        parser().error("--device and --mode are required outside --self-test")
    if args.recovery_timeout_ms == 0:
        parser().error("--recovery-timeout-ms must be greater than zero")
    if any(STAGES[name].fault_kind for name in args.stages) and args.nominal_fps is None:
        parser().error("--nominal-fps is required when q4 or q5 is selected")

    campaign_id = safe_token(args.campaign_id or default_campaign_id())
    campaign_dir = args.output_dir.expanduser().resolve() / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = campaign_dir / "campaign.json"
    campaign_created_utc = utc_now()
    git_rev = git_revision()

    probe_result: dict[str, Any] = {"status": "pending"}
    stage_results: list[StageResult] = []
    write_manifest(
        manifest_path,
        make_manifest(
            campaign_id=campaign_id,
            created_utc=campaign_created_utc,
            status="planned" if args.dry_run else "running",
            git_rev=git_rev,
            args=args,
            stage_results=stage_results,
            campaign_dir=campaign_dir,
            probe_result=probe_result,
            dry_run=args.dry_run,
        ),
    )

    if args.skip_probe:
        probe_result = {"skipped": True, "note": "operator explicitly requested --skip-probe"}
    else:
        probe_result = run_probe(args.probe, campaign_dir / "probe.txt", args.dry_run)

    if not args.dry_run and not args.skip_probe and probe_result.get("return_code") != 0:
        write_manifest(
            manifest_path,
            make_manifest(
                campaign_id=campaign_id,
                created_utc=campaign_created_utc,
                status="failed_probe",
                git_rev=git_rev,
                args=args,
                stage_results=stage_results,
                campaign_dir=campaign_dir,
                probe_result=probe_result,
                dry_run=False,
            ),
        )
        print(
            f"qualification runner: probe failed with return_code={probe_result.get('return_code')}; "
            "campaign aborted before Q1",
            file=sys.stderr,
        )
        print(f"campaign manifest: {manifest_path}")
        return 7

    for stage_name in args.stages:
        stage = STAGES[stage_name]
        output_prefix = campaign_dir / stage.name
        try:
            command = build_stage_command(
                characterizer=args.characterizer,
                stage=stage,
                device=args.device,
                mode=args.mode,
                output_prefix=output_prefix,
                warmup_frames=args.warmup_frames,
                rss_sample_ms=args.rss_sample_ms,
                timeout_ms=args.timeout_ms,
                recovery_timeout_ms=args.recovery_timeout_ms,
                nominal_fps=args.nominal_fps,
                fault_period_s=args.fault_period_s,
                stop_start_pause_ms=args.stop_start_pause_ms,
                reconnect_pause_ms=args.reconnect_pause_ms,
                no_trigger_config=args.no_trigger_config,
            )
        except ValueError as exc:
            print(f"qualification runner: {exc}", file=sys.stderr)
            return 2

        result = StageResult(
            name=stage.name,
            purpose=stage.purpose,
            output_prefix=str(output_prefix),
            command=command,
        )
        stage_results.append(result)
        write_manifest(
            manifest_path,
            make_manifest(
                campaign_id=campaign_id,
                created_utc=campaign_created_utc,
                status="planned" if args.dry_run else "running",
                git_rev=git_rev,
                args=args,
                stage_results=stage_results,
                campaign_dir=campaign_dir,
                probe_result=probe_result,
                dry_run=args.dry_run,
            ),
        )

        print(f"[{stage.name}] {stage.purpose}")
        print(f"  {command_text(command)}")
        execute_stage(result, args.dry_run)

        write_manifest(
            manifest_path,
            make_manifest(
                campaign_id=campaign_id,
                created_utc=campaign_created_utc,
                status="planned" if args.dry_run else "running",
                git_rev=git_rev,
                args=args,
                stage_results=stage_results,
                campaign_dir=campaign_dir,
                probe_result=probe_result,
                dry_run=args.dry_run,
            ),
        )

        if stage_failed(result, args.dry_run):
            print(
                f"  stage failed/incomplete: return_code={result.return_code} "
                f"assessment={result.assessment} note={result.note}",
                file=sys.stderr,
            )
            if not args.continue_on_failure:
                break

    failed = [result for result in stage_results if stage_failed(result, args.dry_run)]
    if args.dry_run:
        final_status = "dry_run"
    elif failed:
        final_status = "failed_stage"
    elif len(stage_results) != len(args.stages):
        final_status = "incomplete"
    else:
        final_status = "completed"

    write_manifest(
        manifest_path,
        make_manifest(
            campaign_id=campaign_id,
            created_utc=campaign_created_utc,
            status=final_status,
            git_rev=git_rev,
            args=args,
            stage_results=stage_results,
            campaign_dir=campaign_dir,
            probe_result=probe_result,
            dry_run=args.dry_run,
        ),
    )

    print(f"campaign manifest: {manifest_path}")
    if args.dry_run:
        print("dry-run complete; no hardware commands were executed")
        return 0
    return 7 if failed or len(stage_results) != len(args.stages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
