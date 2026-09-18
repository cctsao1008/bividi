"""Package-native command adapter for the IMU Allan/noise laboratory.

The estimator/report implementation lives in :mod:`bividi.calibration.imu_allan`
and is intentionally kept byte-for-byte compatible with the characterized legacy
implementation during Issue #91. This adapter applies only the command-level
exit-code contract frozen by Issue #60: analysis/domain failures are exit 2,
while exit 3 is reserved for an explicit evaluated evidence FAIL. The Allan
laboratory has no PASS/FAIL disposition.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import imu_allan


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """Run the characterized Allan implementation under the package CLI contract."""

    try:
        result = int(imu_allan.main(argv))
    except SystemExit as exc:
        # argparse owns usage errors and already uses exit 2. Preserve that
        # behavior for direct package invocation rather than turning it into a
        # traceback.
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    # The historical tool used 3 for missing/invalid analysis input. Under the
    # frozen package-native contract, 3 means a completed evidence evaluation
    # explicitly produced FAIL. Allan analysis has no such disposition.
    return 2 if result == 3 else result


if __name__ == "__main__":
    raise SystemExit(entrypoint())
