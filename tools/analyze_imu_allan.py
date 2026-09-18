#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`bividi.calibration.imu_allan`.

The implementation moved into the installed package under Issue #91. Public
symbols are re-exported so source-tree users that historically imported this
module continue to reach the same characterized estimator/report functions.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.imu_allan import *  # noqa: F401,F403
    from bividi.calibration.imu_allan_command import entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.imu_allan import *  # noqa: F401,F403
    from bividi.calibration.imu_allan_command import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
