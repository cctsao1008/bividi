#!/usr/bin/env python3
"""Compatibility wrapper for the installed stereo fisheye candidate evaluator."""
from __future__ import annotations

from bividi.calibration.stereo_fisheye_candidate import *  # noqa: F401,F403
from bividi.calibration.stereo_fisheye_candidate import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
