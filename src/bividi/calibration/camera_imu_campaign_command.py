"""Package-native command adapter for the camera/IMU physical campaign planner.

The implementation preserves the characterized campaign/runbook/audit semantics.
This adapter only normalizes process exits onto the frozen calibration command
vocabulary: successful self-test/init/audit -> 0, usage/input/domain/read/write
failures -> 2. The orchestration planner never emits evaluated policy FAIL (3).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import plan_camera_imu_physical_campaign as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code in (None, 0) else 2
    except (OSError, ValueError) as exc:
        print(f"camera-IMU campaign planner failed: {exc}", file=sys.stderr)
        return 2

    return 0 if rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
