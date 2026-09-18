"""Package-native command adapter for the camera/IMU evidence promotion gate.

The implementation preserves the characterized manifest/profile semantics. This
adapter only normalizes historical process exits onto the frozen calibration
command vocabulary: successful create/non-failing verify -> 0, usage/input/
schema/hash/cross-link/domain/write failures -> 2, and a completed verification
or promotion disposition FAIL -> 3.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import camera_imu_calibration_provenance as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (OSError, ValueError) as exc:
        print(f"camera-IMU evidence gate failed: {exc}", file=impl.sys.stderr)
        return 2

    if rc == 0:
        return 0
    if rc == 4:
        # Historical verifier uses 4 for a completed policy/profile FAIL.
        return 3
    if rc == 3:
        # Historical create/verify paths use 3 for input/domain/hash/write errors.
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
