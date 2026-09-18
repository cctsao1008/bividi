"""Package-native command adapter for Kalibr IMU export.

The characterized field mapping lives in :mod:`bividi.calibration.kalibr_imu_export`.
This adapter applies the common command-level exit vocabulary and does not alter
validation, mapping, provenance, or measured-cadence semantics.
"""

from __future__ import annotations

from collections.abc import Sequence
import json
import sys

from . import kalibr_imu_export as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    try:
        args = impl.build_parser().parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if args.self_test:
        return impl.self_test()
    if args.artifact is None:
        print("IMU calibration artifact path is required", file=sys.stderr)
        return 2

    try:
        data = impl.calibration_validator.load(args.artifact)
        yaml_text, manifest = impl.build_export(
            data,
            args.rostopic,
            allow_synthetic=args.allow_synthetic,
        )
        manifest["source_artifact"] = str(args.artifact)
        manifest["source_sha256"] = impl.source_hash(args.artifact)
        args.output.write_text(yaml_text, encoding="utf-8")
        if args.manifest_out is not None:
            args.manifest_out.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (ValueError, OSError) as exc:
        print(f"export_kalibr_imu: {exc}", file=sys.stderr)
        return 2

    print(f"wrote Kalibr IMU config: {args.output}")
    if args.manifest_out is not None:
        print(f"wrote export manifest: {args.manifest_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(entrypoint())
