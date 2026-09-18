#!/usr/bin/env python3
"""Compatibility wrapper for :mod:`bividi.calibration.artifact_validator`."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.calibration.artifact_validator import *  # noqa: F401,F403
    from bividi.calibration.artifact_validator import main
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.calibration.artifact_validator import *  # noqa: F401,F403
    from bividi.calibration.artifact_validator import main


if __name__ == "__main__":
    raise SystemExit(main())
