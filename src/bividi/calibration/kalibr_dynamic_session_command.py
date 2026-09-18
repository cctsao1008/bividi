"""Package-native command adapter for Kalibr dynamic-session preparation.

The characterized staging/provenance implementation lives in
:mod:`bividi.calibration.kalibr_dynamic_session`.  This adapter only applies the
common command exit vocabulary: preparation/input/domain failures are command
errors (2), not evaluated evidence failures (3).
"""

from __future__ import annotations

from collections.abc import Sequence

from . import kalibr_dynamic_session as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return 0 if code == 0 else 2
        return 2
    return 2 if rc == 3 else rc


if __name__ == "__main__":
    raise SystemExit(entrypoint())
