#!/usr/bin/env python3
"""Compatibility wrapper for the installed stereo target-scale implementation."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    from bividi.calibration.target_scale import entrypoint
except ModuleNotFoundError:
    # Preserve direct source-checkout invocation before an editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.target_scale import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
