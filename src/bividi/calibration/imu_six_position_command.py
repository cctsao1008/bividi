"""Package-native command adapter for the IMU six-position laboratory.

The characterized gravity/axis implementation lives in
:mod:`bividi.calibration.imu_six_position`. This adapter only applies the
command-level exit-code contract frozen by Issue #60: usage/input/domain errors
are exit 2, while exit 3 is reserved for an explicit evaluated evidence FAIL.
The six-position laboratory reports candidate evidence and owns no PASS/FAIL
disposition.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import imu_six_position


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """Run the characterized six-position implementation under the package CLI contract."""

    try:
        result = int(imu_six_position.main(argv))
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2
    return 2 if result == 3 else result


if __name__ == "__main__":
    raise SystemExit(entrypoint())
