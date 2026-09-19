#!/usr/bin/env python3
"""Compatibility wrapper for the installed stereo camera-model comparator."""
from __future__ import annotations

from bividi.calibration.stereo_model_compare import *  # noqa: F401,F403
from bividi.calibration.stereo_model_compare import entrypoint


if __name__ == "__main__":
    raise SystemExit(entrypoint())
