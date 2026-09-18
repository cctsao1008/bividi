"""Package-native command adapter for pinned-Kalibr target observations.

The implementation keeps the reviewed external Kalibr detector/runtime boundary
and its historical artifact semantics.  This adapter only normalizes process
failures onto the calibration command vocabulary: success/help -> 0 and
usage/input/runtime/domain/write failures -> 2.  This command owns no evaluated
PASS/FAIL disposition, so it never manufactures exit 3.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from . import export_kalibr_target_observations as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0 if rc == 0 else 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
