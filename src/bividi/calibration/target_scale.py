"""Record print-scale evidence for a Bividi stereo calibration target.

This is the installed implementation for the legacy
``tools/review_calibration_target_scale.py`` compatibility entry point.
Moving the implementation into the package must not change the artifact schema,
status/gate semantics, policy-source requirement, or exit-code contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

TARGET_SCHEMA = "bividi.calibration.stereo_target.v1"
REPORT_SCHEMA = "bividi.calibration.stereo_target_scale_review.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "review_calibration_target_scale.py"


class TargetScaleError(ValueError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TargetScaleError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != TARGET_SCHEMA:
        raise TargetScaleError(f"{path}: expected {TARGET_SCHEMA}")
    return value


def review(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    data = load(path)
    design = data.get("physical_size_mm", {})
    dimensions: dict[str, dict[str, float]] = {}
    gates: dict[str, dict[str, float | bool]] = {}

    for key, measured in (
        ("width", args.measured_width_mm),
        ("height", args.measured_height_mm),
    ):
        if measured is None:
            continue
        expected = design.get(key)
        if not isinstance(expected, (int, float)) or float(expected) <= 0:
            raise TargetScaleError(f"target has no valid design {key}")
        if measured <= 0:
            raise TargetScaleError(f"measured {key} must be >0")

        delta = float(measured) - float(expected)
        percent = abs(delta) / float(expected) * 100.0
        dimensions[key] = {
            "designed_mm": float(expected),
            "measured_mm": float(measured),
            "signed_delta_mm": delta,
            "absolute_delta_percent": percent,
        }
        if args.max_abs_delta_percent is not None:
            gates[f"{key}_max_abs_delta_percent"] = {
                "limit": args.max_abs_delta_percent,
                "observed": percent,
                "pass": percent <= args.max_abs_delta_percent,
            }

    if not dimensions:
        raise TargetScaleError(
            "measure at least one of --measured-width-mm/--measured-height-mm"
        )

    status = "EVIDENCE_ONLY_NO_THRESHOLDS"
    if gates:
        if not args.policy_source:
            raise TargetScaleError("explicit print-scale gates require --policy-source")
        status = "PASS" if all(value["pass"] for value in gates.values()) else "FAIL"

    return {
        "schema": REPORT_SCHEMA,
        "target": {
            "path": str(path.resolve()),
            "sha256": sha(path.resolve()),
            "target_id": data.get("target_id"),
        },
        "measurements": dimensions,
        "measurement_source": args.measurement_source,
        "method": args.method,
        "gates": gates,
        "policy_source": args.policy_source,
        "status": status,
        "provenance": {
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
        },
        "guardrails": [
            "Printer DPI/fit-to-page settings are not accepted as physical scale proof; a physical measurement is required."
        ],
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "t.json"
        path.write_text(
            json.dumps(
                {
                    "schema": TARGET_SCHEMA,
                    "target_id": "t",
                    "physical_size_mm": {"width": 240.0, "height": 180.0},
                }
            ),
            encoding="utf-8",
        )
        args = argparse.Namespace(
            measured_width_mm=239.5,
            measured_height_mm=None,
            max_abs_delta_percent=None,
            policy_source=None,
            measurement_source="synthetic",
            method="caliper",
        )
        result = review(path, args)
        assert 0.2 < result["measurements"]["width"]["absolute_delta_percent"] < 0.21
        assert result["provenance"]["tool"] == COMPATIBILITY_TOOL_NAME
    print("Calibration target print-scale review self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("target", nargs="?", type=Path)
    parser.add_argument("--measured-width-mm", type=float)
    parser.add_argument("--measured-height-mm", type=float)
    parser.add_argument("--measurement-source")
    parser.add_argument("--method")
    parser.add_argument("--max-abs-delta-percent", type=float)
    parser.add_argument("--policy-source")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.target or not args.measurement_source or not args.method:
        raise TargetScaleError(
            "target, --measurement-source, and --method are required"
        )

    result = review(args.target.resolve(), args)
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
    except TargetScaleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
