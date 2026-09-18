"""Package-native command adapter for camera/IMU excitation evidence.

The characterized evaluator keeps its historical report/status semantics.  This
adapter only maps process exits onto the frozen calibration command vocabulary:
domain/usage failures -> 2, completed report FAIL -> 3, non-failing completion
-> 0.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import camera_imu_excitation as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return 0 if code == 0 else 2
        return 2
    if rc == 7:
        return 3
    if rc == 3:
        return 2
    return rc


if __name__ == "__main__":
    raise SystemExit(entrypoint())
