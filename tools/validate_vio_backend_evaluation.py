#!/usr/bin/env python3
"""Compatibility entry point for the packaged VIO backend evaluation validator."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.vio_backend_evaluation import main
except ModuleNotFoundError:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from bividi.vio_backend_evaluation import main


if __name__ == "__main__":
    raise SystemExit(main())
