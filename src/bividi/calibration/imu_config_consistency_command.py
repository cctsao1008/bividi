"""Package-native command adapter for IMU configuration-consistency analysis.

The characterized response-consistency implementation lives in
:mod:`bividi.calibration.imu_config_consistency`. This adapter applies the
command-level exit contract frozen by Issue #60 without changing analysis math:
usage/input/domain errors are exit 2, completed explicit evidence FAIL is exit 3,
and non-failing completion is exit 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys

from . import imu_config_consistency as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        args = impl.build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if args.self_test:
        return impl.self_test()
    if args.manifest is None:
        print("manifest path is required", file=sys.stderr)
        return 2

    try:
        report = impl.analyze(
            args.manifest,
            max_accel_scale_error_pct=args.max_accel_scale_error_pct,
            max_gyro_scale_error_pct=args.max_gyro_scale_error_pct,
            max_odr_error_pct=args.max_odr_error_pct,
            require_gyro_scale=args.require_gyro_scale,
        )
    except impl.ConsistencyError as exc:
        print(f"analyze_imu_config_consistency: {exc}", file=sys.stderr)
        return 2

    markdown = impl.render_markdown(report)
    print(markdown)
    json_out = args.json_out
    markdown_out = args.markdown_out
    if args.output_prefix is not None:
        json_out = json_out or Path(str(args.output_prefix) + ".config.json")
        markdown_out = markdown_out or Path(str(args.output_prefix) + ".config.md")
    if json_out is not None:
        impl.write_json(json_out, report)
    if markdown_out is not None:
        markdown_out.write_text(markdown + "\n", encoding="utf-8")

    return 3 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(entrypoint())
