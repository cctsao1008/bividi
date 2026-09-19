"""Frozen command adapter for the package-native stereo calibration workbench."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import stereo_calibration_workbench as implementation
from .contract import EXIT_EVALUATED_FAIL, EXIT_OK, EXIT_USAGE_OR_DOMAIN_ERROR

_QUALITY_COMMANDS = {"inspect", "solve"}
_QUALITY_STATUSES = {"EVIDENCE_ONLY_NO_THRESHOLDS", "PASS", "FAIL"}


def _completed_quality_status(parsed) -> str | None:
    """Read a completed leaf-owned quality result without inventing policy."""

    if getattr(parsed, "cmd", None) not in _QUALITY_COMMANDS:
        return None
    output = getattr(parsed, "output", None)
    if not isinstance(output, Path):
        raise ValueError("completed quality command did not expose an output path")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read completed quality output {output}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"completed quality output {output} must be a JSON object")

    if parsed.cmd == "inspect":
        status = payload.get("status")
    else:
        quality = payload.get("quality")
        status = quality.get("status") if isinstance(quality, dict) else None
    if status not in _QUALITY_STATUSES:
        raise ValueError(f"completed quality output {output} has invalid status {status!r}")
    return str(status)


def entrypoint(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        parsed = implementation.args(raw)
        rc = implementation.main(raw)
        if rc not in (None, 0):
            return EXIT_USAGE_OR_DOMAIN_ERROR
        status = _completed_quality_status(parsed)
    except SystemExit as exc:
        return EXIT_OK if exc.code in (None, 0) else EXIT_USAGE_OR_DOMAIN_ERROR
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"stereo calibration workbench failed: {exc}", file=sys.stderr)
        return EXIT_USAGE_OR_DOMAIN_ERROR

    if status == "FAIL":
        return EXIT_EVALUATED_FAIL
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    return entrypoint(argv)


if __name__ == "__main__":
    raise SystemExit(entrypoint())
