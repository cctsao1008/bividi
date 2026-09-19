"""Package-native command adapter for the Kalibr ROS1 bag transport.

The underlying writer preserves the characterized ROS1/Kalibr compatibility
semantics. This adapter only normalizes historical process exits onto the frozen
calibration vocabulary: success -> 0 and usage/input/schema/CSV/runtime/
dependency/read/write failures -> 2. Transport generation has no evaluated
quality-policy FAIL state and therefore never returns 3.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import write_kalibr_rosbag as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"Kalibr ROS1 bag transport failed: {exc}", file=sys.stderr)
        return 2

    return 0 if rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
