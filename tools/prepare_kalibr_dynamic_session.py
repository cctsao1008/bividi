#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`bividi.calibration.kalibr_dynamic_session`."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.kalibr_dynamic_session import *  # noqa: F401,F403
    from bividi.calibration.kalibr_dynamic_session_command import entrypoint
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.kalibr_dynamic_session import *  # noqa: F401,F403
    from bividi.calibration.kalibr_dynamic_session_command import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
