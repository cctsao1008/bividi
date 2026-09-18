"""Package-native command adapter for Kalibr solver-quality evidence.

The historical tool used exit 3 for parser/domain failures and exit 7 for a
completed report FAIL.  The package adapter preserves report/evidence semantics
while mapping process exits onto the frozen calibration vocabulary: domain and
usage failures -> 2, completed evaluated FAIL -> 3, non-failing completion -> 0.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from . import kalibr_solver_quality as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (ValueError, OSError) as exc:
        print(f"Kalibr solver quality analysis failed: {exc}", file=sys.stderr)
        return 2
    if rc == 7:
        return 3
    if rc == 0:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
