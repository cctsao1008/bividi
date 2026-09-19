#!/usr/bin/env python3
"""Compatibility wrapper for the package-native ROS2/MCAP calibration transport."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.write_ros2_calibration_mcap import *  # noqa: F401,F403
    from bividi.calibration.ros2_mcap_command import entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.write_ros2_calibration_mcap import *  # noqa: F401,F403
    from bividi.calibration.ros2_mcap_command import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
