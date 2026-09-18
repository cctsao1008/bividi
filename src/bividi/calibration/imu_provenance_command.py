"""Package-native command adapter for the IMU calibration provenance gate.

The characterized manifest/provenance implementation lives in
:mod:`bividi.calibration.imu_provenance`. This adapter changes only command-level
exit classification to the contract frozen by Issue #60: usage/input/domain
errors are exit 2, while a completed gate evaluation with errors is exit 3.
"""

from __future__ import annotations

from collections.abc import Sequence
import argparse
import json
import sys

from . import imu_provenance as impl


def entrypoint(argv: Sequence[str] | None = None) -> int:
    parser = impl.build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if args.self_test:
        return impl.self_test()

    if args.command == "create":
        try:
            manifest = impl.create_manifest(args)
            errors = impl.verify_manifest(
                manifest,
                args.output.resolve(),
                profile=args.profile,
                verify_file_hashes=True,
            )
        except (impl.ManifestError, OSError, argparse.ArgumentTypeError) as exc:
            print(f"imu_calibration_provenance: {exc}", file=sys.stderr)
            return 2

        if errors:
            impl.print_result(errors, args.profile)
            return 3
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"imu_calibration_provenance: {exc}", file=sys.stderr)
            return 2
        impl.print_result([], args.profile)
        print(f"  manifest={args.output}")
        print(f"  captures={len(manifest['captures'])} analysis={len(manifest['analysis'])}")
        return 0

    if args.command == "verify":
        try:
            manifest_path = args.manifest.resolve()
            data = impl.load_json(manifest_path)
            errors = impl.verify_manifest(
                data,
                manifest_path,
                profile=args.profile,
                verify_file_hashes=not args.skip_file_hashes,
                base_dir=args.base_dir.resolve() if args.base_dir else None,
            )
        except (impl.ManifestError, OSError) as exc:
            print(f"imu_calibration_provenance: {exc}", file=sys.stderr)
            return 2
        impl.print_result(errors, args.profile)
        return 0 if not errors else 3

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
