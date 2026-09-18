"""Package-native command adapter for Kalibr target-coverage evidence.

The dependency-free evaluator keeps its historical report/status semantics.  The
adapter preserves completed explicit-gate FAIL as exit 3 while mapping usage,
input, schema, hash, domain, and write failures to exit 2.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from . import analyze_kalibr_target_coverage as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if rc == 3:
        return 3
    if rc == 0:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
