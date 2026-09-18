"""Package-native command adapter for camera/IMU repeatability evidence.

The implementation preserves the characterized report, compatibility checks,
SE(3) math, and explicit-gate semantics. This adapter only normalizes historical
process exits onto the frozen calibration command vocabulary: evidence-only/PASS
-> 0, usage/input/schema/hash/compatibility/domain/write failures -> 2, and a
completed explicit-gate FAIL -> 3.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import camera_imu_repeatability as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (OSError, ValueError) as exc:
        print(f"camera-IMU repeatability comparison failed: {exc}", file=impl.sys.stderr)
        return 2

    if rc == 0:
        return 0
    if rc == 1:
        # Historical implementation uses 1 for a completed explicit-gate FAIL.
        return 3
    if rc == 3:
        # Historical implementation uses 3 for input/domain/write failures.
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
