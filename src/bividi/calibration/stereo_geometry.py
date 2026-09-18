"""Review calibrated stereo baseline against an explicit physical measurement.

This is the installed implementation for the legacy
``tools/review_stereo_geometry.py`` compatibility entry point. Moving the
implementation into the package must not change the artifact schema,
status/gate semantics, policy-source requirement, or exit-code contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "bividi.calibration.stereo.v1"
REPORT_SCHEMA = "bividi.calibration.stereo_geometry_review.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "review_stereo_geometry.py"


class ReviewError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ReviewError(f"{path}: expected {SCHEMA}")
    return value


def review(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    data = load(path)
    translation = data.get("stereo", {}).get("T_camera_b_from_camera_a_m")
    if not isinstance(translation, list) or len(translation) != 3:
        raise ReviewError("calibration translation missing")

    baseline_mm = math.sqrt(sum(float(value) ** 2 for value in translation)) * 1000.0
    measured_mm = float(args.physical_baseline_mm)
    if measured_mm <= 0:
        raise ReviewError("--physical-baseline-mm must be > 0")

    delta_mm = baseline_mm - measured_mm
    absolute_delta_mm = abs(delta_mm)
    absolute_delta_percent = absolute_delta_mm / measured_mm * 100.0

    gates: dict[str, dict[str, float | bool]] = {}
    if args.max_abs_delta_mm is not None:
        gates["max_abs_delta_mm"] = {
            "limit": args.max_abs_delta_mm,
            "observed": absolute_delta_mm,
            "pass": absolute_delta_mm <= args.max_abs_delta_mm,
        }
    if args.max_abs_delta_percent is not None:
        gates["max_abs_delta_percent"] = {
            "limit": args.max_abs_delta_percent,
            "observed": absolute_delta_percent,
            "pass": absolute_delta_percent <= args.max_abs_delta_percent,
        }

    status = "EVIDENCE_ONLY_NO_THRESHOLDS"
    if gates:
        if not args.policy_source:
            raise ReviewError("explicit geometry gates require --policy-source")
        status = "PASS" if all(value["pass"] for value in gates.values()) else "FAIL"

    return {
        "schema": REPORT_SCHEMA,
        "calibration": {
            "path": str(path.resolve()),
            "sha256": sha256_file(path.resolve()),
            "calibration_id": data.get("calibration_id"),
        },
        "physical_measurement": {
            "baseline_mm": measured_mm,
            "measurement_source": args.measurement_source,
            "method": args.method,
        },
        "calibrated": {
            "baseline_mm": baseline_mm,
            "translation_m": translation,
        },
        "comparison": {
            "signed_delta_mm": delta_mm,
            "absolute_delta_mm": absolute_delta_mm,
            "absolute_delta_percent": absolute_delta_percent,
        },
        "gates": gates,
        "policy_source": args.policy_source,
        "status": status,
        "provenance": {
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
        },
        "guardrails": [
            "A mechanical baseline check is a sanity check, not an independent full extrinsic calibration.",
            "Measurement method/fixture uncertainty should be retained outside this scalar comparison when it is material.",
        ],
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "c.json"
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "calibration_id": "x",
                    "stereo": {"T_camera_b_from_camera_a_m": [-0.08, 0, 0]},
                }
            ),
            encoding="utf-8",
        )
        args = argparse.Namespace(
            physical_baseline_mm=80.5,
            measurement_source="synthetic",
            method="synthetic",
            max_abs_delta_mm=None,
            max_abs_delta_percent=None,
            policy_source=None,
        )
        result = review(path, args)
        assert abs(result["comparison"]["absolute_delta_mm"] - 0.5) < 1e-9
        assert result["provenance"]["tool"] == COMPATIBILITY_TOOL_NAME
    print("Stereo geometry review self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("calibration", nargs="?", type=Path)
    parser.add_argument("--physical-baseline-mm", type=float)
    parser.add_argument("--measurement-source")
    parser.add_argument("--method")
    parser.add_argument("--max-abs-delta-mm", type=float)
    parser.add_argument("--max-abs-delta-percent", type=float)
    parser.add_argument("--policy-source")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if (
        not args.calibration
        or args.physical_baseline_mm is None
        or not args.measurement_source
        or not args.method
    ):
        raise ReviewError(
            "calibration, physical baseline, measurement source, and method are required"
        )

    result = review(args.calibration.resolve(), args)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if result["status"] != "FAIL" else 3


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """CLI wrapper preserving the historical error/exit-code contract."""

    try:
        return main(argv)
    except ReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
