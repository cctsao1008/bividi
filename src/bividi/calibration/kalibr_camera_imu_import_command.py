"""Package-native command adapter for Kalibr camera/IMU candidate import.

The importer preserves its historical artifact and sidecar semantics. This
adapter only maps process exits onto the frozen calibration command vocabulary:
usage/input/schema/hash/domain/validation/write failures -> 2 and successful
candidate import -> 0. The importer owns no evaluated PASS/FAIL disposition, so
it never manufactures exit 3.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from . import kalibr_camera_imu_import as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (ValueError, OSError) as exc:
        print(f"Kalibr camera-IMU import failed: {exc}", file=sys.stderr)
        return 2
    if rc == 0:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
