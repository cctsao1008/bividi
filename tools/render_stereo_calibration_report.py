#!/usr/bin/env python3
"""Compatibility wrapper for the installed stereo evidence report renderer."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    from bividi.calibration.stereo_report import entrypoint
except ModuleNotFoundError:
    # Preserve direct source-checkout invocation before an editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.stereo_report import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
