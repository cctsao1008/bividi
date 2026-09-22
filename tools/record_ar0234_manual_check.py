#!/usr/bin/env python3
"""Record operator-assisted AR0234 physical checks and refresh the feature report."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Sequence

import run_ar0234_feature_qualification as feature

SCHEMA = "bividi.ar0234.manual_checks.v1"
VALID = {"PASS", "FAIL", "BLOCKED", "N/A", "PENDING"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load(path: Path) -> dict:
    if not path.exists():
        return {"schema": SCHEMA, "updated_utc": utc_now(), "checks": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unexpected manual-check schema: {data.get('schema')!r}")
    data.setdefault("checks", {})
    return data


def save(path: Path, data: dict) -> None:
    data["updated_utc"] = utc_now()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refresh_report(session_dir: Path, manual: dict) -> None:
    results_path = session_dir / "feature-results.json"
    if not results_path.exists():
        return
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    (session_dir / "report.md").write_text(feature.render_report(payload, manual), encoding="utf-8")


def prompt_status(test_id: str, name: str, current: str) -> tuple[str, str]:
    print(f"\n{test_id} — {name}")
    print(f"current: {current}")
    while True:
        raw = input("status [p=PASS/f=FAIL/b=BLOCKED/n=N/A/s=skip]: ").strip().lower()
        mapping = {"p": "PASS", "f": "FAIL", "b": "BLOCKED", "n": "N/A", "s": "PENDING", "": current}
        if raw in mapping:
            status = mapping[raw]
            break
        print("invalid status")
    note = input("note/evidence (optional): ").strip()
    return status, note


def self_test() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        path = root / "manual-results.json"
        data = load(path)
        data["checks"]["M01"] = {"status": "PASS", "note": "self-test", "updated_utc": utc_now()}
        save(path, data)
        again = load(path)
        assert again["checks"]["M01"]["status"] == "PASS"
    print("AR0234 manual check recorder self-test: PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Record manual/physical AR0234 qualification checks.")
    p.add_argument("session_dir", nargs="?", help="feature-qualification session directory")
    p.add_argument("--id", dest="test_id", choices=feature.MANUAL_TESTS)
    p.add_argument("--status", choices=["pass", "fail", "blocked", "na", "pending"])
    p.add_argument("--note", default="")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--show", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if args.list:
        for test_id, name in feature.MANUAL_TESTS.items():
            print(f"{test_id}  {name}")
        return 0
    if not args.session_dir:
        parser().error("session_dir is required unless --list or --self-test is used")

    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "manual-results.json"
    data = load(path)

    if args.interactive:
        for test_id, name in feature.MANUAL_TESTS.items():
            current = str(data["checks"].get(test_id, {}).get("status", "PENDING")).upper()
            status, note = prompt_status(test_id, name, current)
            data["checks"][test_id] = {"status": status, "note": note, "updated_utc": utc_now()}
        save(path, data)
        refresh_report(session_dir, data)
    elif args.test_id:
        if not args.status:
            parser().error("--status is required with --id")
        mapped = {"pass": "PASS", "fail": "FAIL", "blocked": "BLOCKED", "na": "N/A", "pending": "PENDING"}[args.status]
        data["checks"][args.test_id] = {"status": mapped, "note": args.note, "updated_utc": utc_now()}
        save(path, data)
        refresh_report(session_dir, data)
    elif not args.show:
        parser().error("choose --interactive, --id/--status, or --show")

    if args.show or args.interactive or args.test_id:
        for test_id, name in feature.MANUAL_TESTS.items():
            entry = data["checks"].get(test_id, {})
            status = str(entry.get("status", "PENDING")).upper()
            note = str(entry.get("note", ""))
            print(f"{test_id} {status:8} {name}" + (f" — {note}" if note else ""))
        print(f"manual evidence: {path}")
        if (session_dir / "report.md").exists():
            print(f"report: {session_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
