"""Package-native command adapter for camera/IMU temporal evidence review.

The underlying reviewer preserves its characterized evidence/report semantics.
This adapter only normalizes process exits onto the frozen calibration command
vocabulary: successful/evidence-only/PASS completion -> 0, usage/input/schema/
hash/validation/domain/write failures -> 2, and completed explicit-gate FAIL ->
3.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys

from . import camera_imu_temporal_review as impl


def _prefer_utf8_console() -> None:
    """Avoid Windows legacy-codepage failures on the report's ↔/Δ text.

    This changes only process text encoding; report/artifact strings and evidence
    semantics remain unchanged. Redirected StringIO/test streams have no
    ``reconfigure`` method and are left untouched.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def entrypoint(argv: Sequence[str] | None = None) -> int:
    _prefer_utf8_console()
    try:
        rc = int(impl.main(argv))
    except SystemExit as exc:
        code = exc.code
        return 0 if code == 0 else 2
    except (OSError, ValueError) as exc:
        # File-system failures outside the historical analyze() try block and
        # parser/statistics domain failures are command-domain errors, not an
        # evaluated evidence FAIL.
        print(f"review_camera_imu_time_offset: {exc}", file=sys.stderr)
        return 2
    if rc == 0:
        return 0
    if rc == 3:
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
