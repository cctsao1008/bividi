#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bividi.replay_artifact_faults import apply_recipe, load_recipe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy a replay-artifact tree and apply deterministic integrity faults."
    )
    parser.add_argument("--source", required=True, type=Path, help="Source session/container directory")
    parser.add_argument("--output", required=True, type=Path, help="New mutated output directory")
    parser.add_argument("--recipe", required=True, type=Path, help="bividi.replay_artifact_fault_recipe.v1 JSON")
    parser.add_argument("--manifest", type=Path, help="Optional application-manifest JSON path")
    args = parser.parse_args()

    recipe = load_recipe(args.recipe)
    manifest = apply_recipe(args.source, args.output, recipe)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.manifest is not None:
        if args.manifest.exists():
            raise SystemExit(f"refusing to overwrite manifest: {args.manifest}")
        args.manifest.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
