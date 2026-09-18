"""Package-native command adapter for camera/IMU temporal evidence review.

The underlying reviewer preserves its characterized evidence/report semantics.
This adapter only normalizes process exits onto the frozen calibration command
vocabulary: successful/evidence-only/PASS completion -> 0, usage/input/schema/
hash/validation/domain/write failures -> 2, and completed explicit-gate FAIL ->
3.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import camera_imu_temporal_review as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (OSError, ValueError) as exc:
        # File-system failures outside the historical analyze() try block and
        # parser/statistics domain failures are command-domain errors, not an
        # evaluated evidence FAIL.
        print(f"review_camera_imu_time_offset: {exc}", file=impl.sys.stderr)
        return 2
    if rc == 0:
        return 0
    if rc == 3:
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
