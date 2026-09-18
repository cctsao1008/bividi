#!/usr/bin/env python3
"""Compatibility wrapper for the installed stationary IMU analyzer."""

from __future__ import annotations

from pathlib import Path
import sys

try:
    from bividi.calibration.imu_stationary import entrypoint
except ModuleNotFoundError:
    # Preserve direct source-checkout invocation before an editable install.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.imu_stationary import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
