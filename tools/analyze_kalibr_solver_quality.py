#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`bividi.calibration.kalibr_solver_quality`."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.kalibr_solver_quality import *  # noqa: F401,F403
    from bividi.calibration.kalibr_solver_quality_command import entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.kalibr_solver_quality import *  # noqa: F401,F403
    from bividi.calibration.kalibr_solver_quality_command import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
