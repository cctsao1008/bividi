"""Dependency-light command-line interface for the Bividi host API."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from .decxin import DecxinDecodeError, DecxinDecoder
from .host import BividiHost
from .mock import MockStereoProvider


def build_host() -> BividiHost:
    """Build the current development host.

    Until a measured physical provider is implemented, the CLI intentionally
    exposes only the synthetic provider.
    """

    return BividiHost([MockStereoProvider()])


def _emit(value: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
        return

    if isinstance(value, list):
        for item in value:
            print(json.dumps(item, sort_keys=True))
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bividi",
        description="Bividi host inspection CLI",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("about", help="show host implementation information")
    sub.add_parser("sources", help="list available sensor sources")

    status = sub.add_parser("status", help="show source status")
    status.add_argument("source_id")

    modes = sub.add_parser("modes", help="list source capture modes")
    modes.add_argument("source_id")

    inspect = sub.add_parser("inspect", help="inspect an offline sensor capture")
    inspect.add_argument("capture", help="path to a supported capture file")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        if args.command == "inspect":
            payload = DecxinDecoder().decode_bmp(args.capture).summary()
        else:
            host = build_host()
            if args.command == "about":
                payload = {
                    "project": "bividi",
                    "host_api": "reference-python",
                    "hardware_provider": False,
                    "note": "current live path is synthetic; offline DECXIN inspection is available",
                }
            elif args.command == "sources":
                payload = [source.to_dict() for source in host.list_sources()]
            elif args.command == "status":
                payload = host.get_source_status(args.source_id).to_dict()
            elif args.command == "modes":
                payload = [mode.to_dict() for mode in host.list_modes(args.source_id)]
            else:  # pragma: no cover - argparse keeps this unreachable
                raise AssertionError(args.command)
    except (KeyError, OSError, DecxinDecodeError) as exc:
        parser = _parser()
        parser.error(str(exc))
        return 2

    _emit(payload, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
