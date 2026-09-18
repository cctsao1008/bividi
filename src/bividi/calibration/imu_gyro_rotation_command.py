"""Package-native command adapter for the controlled gyroscope rotation laboratory.

The characterized integration/axis/sensitivity implementation lives in
:mod:`bividi.calibration.imu_gyro_rotation`. This adapter only applies the
command-level exit-code contract frozen by Issue #60: usage/input/domain errors
are exit 2, while exit 3 is reserved for an explicit evaluated evidence FAIL.
The gyro-rotation laboratory reports candidate evidence and owns no PASS/FAIL
disposition.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import imu_gyro_rotation


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """Run the characterized gyro-rotation implementation under the package CLI contract."""

    try:
        result = int(imu_gyro_rotation.main(argv))
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2
    return 2 if result == 3 else result


if __name__ == "__main__":
    raise SystemExit(entrypoint())
