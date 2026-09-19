"""Package-native command adapter for the ROS2/MCAP calibration transport.

The implementation preserves the characterized ROS2 interoperability semantics.
This adapter only normalizes process exits onto the frozen calibration command
vocabulary: success -> 0 and usage/input/schema/topic/runtime/dependency/read/
write failures -> 2. Transport generation has no evaluated quality-policy FAIL
state and therefore never returns 3.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import write_ros2_calibration_mcap as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 2
    except (OSError, ValueError, KeyError) as exc:
        print(f"ROS2/MCAP calibration transport failed: {exc}", file=sys.stderr)
        return 2

    return 0 if rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
