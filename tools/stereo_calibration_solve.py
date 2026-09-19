#!/usr/bin/env python3
"""Compatibility re-export for the package-native stereo calibration solve helpers."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.stereo_calibration_solve import *  # noqa: F401,F403
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.stereo_calibration_solve import *  # noqa: F401,F403
