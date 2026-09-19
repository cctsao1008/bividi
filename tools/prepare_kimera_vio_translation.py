#!/usr/bin/env python3
"""Compatibility entry point for the packaged Kimera translation-plan tool."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from bividi.vio_kimera_config import main
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from bividi.vio_kimera_config import main


if __name__ == "__main__":
    raise SystemExit(main())
