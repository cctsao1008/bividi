#!/usr/bin/env python3
"""Compatibility wrapper for the package-native Kalibr ROS1 bag transport."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.write_kalibr_rosbag import *  # noqa: F401,F403
    from bividi.calibration.kalibr_rosbag_command import entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.write_kalibr_rosbag import *  # noqa: F401,F403
    from bividi.calibration.kalibr_rosbag_command import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
