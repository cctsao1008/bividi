#!/usr/bin/env python3
"""Compatibility entry point for the package-native stereo calibration workbench."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.stereo_calibration_workbench import *  # noqa: F401,F403
    from bividi.calibration.stereo_workbench_command import entrypoint as _entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.stereo_calibration_workbench import *  # noqa: F401,F403
    from bividi.calibration.stereo_workbench_command import entrypoint as _entrypoint


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
