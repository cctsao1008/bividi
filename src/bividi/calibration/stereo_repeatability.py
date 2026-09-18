"""Compare independent Bividi stereo calibration artifacts for repeatability.

No universal tolerance is invented. Without explicit gates the report remains
``EVIDENCE_ONLY_NO_THRESHOLDS``. With gates, a named policy source is required.

This is the installed implementation for the legacy
``tools/compare_stereo_calibrations.py`` compatibility entry point. Package
migration must not change the artifact schema, identity checks, metric
semantics, policy-source requirement, provenance, or exit-code contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "bividi.calibration.stereo.v1"
REPORT_SCHEMA = "bividi.calibration.stereo_repeatability.v1"
TOOL_VERSION = "1"
COMPATIBILITY_TOOL_NAME = "compare_stereo_calibrations.py"
CAMERAS = ("camera_a", "camera_b")


class CompareError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompareError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise CompareError(f"{path}: expected {SCHEMA}")
    return value


def vec_norm(value: Sequence[Any]) -> float:
    return math.sqrt(sum(float(item) ** 2 for item in value))


def dot(a: Sequence[Any], b: Sequence[Any]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def rotation_delta_deg(a: Sequence[Sequence[Any]], b: Sequence[Sequence[Any]]) -> float:
    rotation = [
        [
            sum(float(a[i][k]) * float(b[j][k]) for k in range(3))
            for j in range(3)
        ]
        for i in range(3)
    ]
    cosine = max(
        -1.0,
        min(
            1.0,
            (rotation[0][0] + rotation[1][1] + rotation[2][2] - 1.0) / 2.0,
        ),
    )
    return math.degrees(math.acos(cosine))


def direction_delta_deg(a: Sequence[Any], b: Sequence[Any]) -> float:
    norm_a = vec_norm(a)
    norm_b = vec_norm(b)
    if norm_a <= 0 or norm_b <= 0:
        raise CompareError("zero stereo translation")
    cosine = max(-1.0, min(1.0, dot(a, b) / (norm_a * norm_b)))
    return math.degrees(math.acos(cosine))


def percent_delta(a: Any, b: Any) -> float:
    denominator = max(abs(float(a)), abs(float(b)))
    return 0.0 if denominator == 0 else abs(float(a) - float(b)) / denominator * 100.0


def identity_key(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "device_model": data.get("device", {}).get("model"),
        "device_serial": data.get("device", {}).get("serial"),
        "mode_index": data.get("capture", {}).get("mode_index"),
        "pixel_format": data.get("capture", {}).get("pixel_format"),
        "width": data.get("image", {}).get("width"),
        "height": data.get("image", {}).get("height"),
        "target_id": data.get("target", {}).get("target_id"),
        "target_sha256": data.get("target", {}).get("sha256"),
        "camera_model": data.get("camera_model"),
    }


def compare(paths: Sequence[Path], args: argparse.Namespace) -> dict[str, Any]:
    if len(paths) < 2:
        raise CompareError("at least two calibration artifacts are required")

    documents = [load(path.resolve()) for path in paths]
    identity = identity_key(documents[0])
    for path, document in zip(paths[1:], documents[1:]):
        if identity_key(document) != identity:
            raise CompareError(
                f"{path}: incompatible device/mode/target/camera-model identity"
            )

    pair_reports: list[dict[str, Any]] = []
    for (index_a, document_a), (index_b, document_b) in combinations(
        list(enumerate(documents)), 2
    ):
        translation_a = document_a["stereo"]["T_camera_b_from_camera_a_m"]
        translation_b = document_b["stereo"]["T_camera_b_from_camera_a_m"]
        pair_reports.append(
            {
                "a_index": index_a,
                "b_index": index_b,
                "rotation_delta_deg": rotation_delta_deg(
                    document_a["stereo"]["R_camera_b_from_camera_a"],
                    document_b["stereo"]["R_camera_b_from_camera_a"],
                ),
                "baseline_delta_mm": abs(
                    vec_norm(translation_a) - vec_norm(translation_b)
                )
                * 1000.0,
                "translation_direction_delta_deg": direction_delta_deg(
                    translation_a, translation_b
                ),
                "camera_a_fx_delta_percent": percent_delta(
                    document_a["cameras"]["camera_a"]["K"][0][0],
                    document_b["cameras"]["camera_a"]["K"][0][0],
                ),
                "camera_a_fy_delta_percent": percent_delta(
                    document_a["cameras"]["camera_a"]["K"][1][1],
                    document_b["cameras"]["camera_a"]["K"][1][1],
                ),
                "camera_b_fx_delta_percent": percent_delta(
                    document_a["cameras"]["camera_b"]["K"][0][0],
                    document_b["cameras"]["camera_b"]["K"][0][0],
                ),
                "camera_b_fy_delta_percent": percent_delta(
                    document_a["cameras"]["camera_b"]["K"][1][1],
                    document_b["cameras"]["camera_b"]["K"][1][1],
                ),
                "camera_a_principal_point_delta_px": math.hypot(
                    float(document_a["cameras"]["camera_a"]["K"][0][2])
                    - float(document_b["cameras"]["camera_a"]["K"][0][2]),
                    float(document_a["cameras"]["camera_a"]["K"][1][2])
                    - float(document_b["cameras"]["camera_a"]["K"][1][2]),
                ),
                "camera_b_principal_point_delta_px": math.hypot(
                    float(document_a["cameras"]["camera_b"]["K"][0][2])
                    - float(document_b["cameras"]["camera_b"]["K"][0][2]),
                    float(document_a["cameras"]["camera_b"]["K"][1][2])
                    - float(document_b["cameras"]["camera_b"]["K"][1][2]),
                ),
            }
        )

    def maximum(key: str) -> float:
        return max(float(item[key]) for item in pair_reports)

    summary = {
        "artifact_count": len(documents),
        "pair_count": len(pair_reports),
        "max_rotation_delta_deg": maximum("rotation_delta_deg"),
        "max_baseline_delta_mm": maximum("baseline_delta_mm"),
        "max_translation_direction_delta_deg": maximum(
            "translation_direction_delta_deg"
        ),
        "max_focal_delta_percent": max(
            maximum("camera_a_fx_delta_percent"),
            maximum("camera_a_fy_delta_percent"),
            maximum("camera_b_fx_delta_percent"),
            maximum("camera_b_fy_delta_percent"),
        ),
        "max_principal_point_delta_px": max(
            maximum("camera_a_principal_point_delta_px"),
            maximum("camera_b_principal_point_delta_px"),
        ),
    }

    gates: dict[str, dict[str, float | bool]] = {}
    for name, limit, key in (
        (
            "max_rotation_delta_deg",
            args.max_rotation_delta_deg,
            "max_rotation_delta_deg",
        ),
        (
            "max_baseline_delta_mm",
            args.max_baseline_delta_mm,
            "max_baseline_delta_mm",
        ),
        (
            "max_translation_direction_delta_deg",
            args.max_translation_direction_delta_deg,
            "max_translation_direction_delta_deg",
        ),
        (
            "max_focal_delta_percent",
            args.max_focal_delta_percent,
            "max_focal_delta_percent",
        ),
        (
            "max_principal_point_delta_px",
            args.max_principal_point_delta_px,
            "max_principal_point_delta_px",
        ),
    ):
        if limit is not None:
            gates[name] = {
                "limit": limit,
                "observed": summary[key],
                "pass": summary[key] <= limit,
            }

    status = "EVIDENCE_ONLY_NO_THRESHOLDS"
    if gates:
        if not args.policy_source:
            raise CompareError("explicit repeatability gates require --policy-source")
        status = "PASS" if all(value["pass"] for value in gates.values()) else "FAIL"

    return {
        "schema": REPORT_SCHEMA,
        "provenance": {
            "tool": COMPATIBILITY_TOOL_NAME,
            "tool_version": TOOL_VERSION,
        },
        "identity": identity,
        "artifacts": [
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path.resolve()),
                "calibration_id": document.get("calibration_id"),
                "provenance_kind": document.get("provenance", {}).get("kind"),
            }
            for path, document in zip(paths, documents)
        ],
        "pairs": pair_reports,
        "summary": summary,
        "gates": gates,
        "policy_source": args.policy_source,
        "status": status,
        "guardrails": [
            "Repeatability is consistency evidence, not independent calibration truth.",
            "Independent captures/solves are required; copied artifacts do not establish repeatability.",
        ],
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        def document(calibration_id: str, baseline_m: float) -> dict[str, Any]:
            return {
                "schema": SCHEMA,
                "calibration_id": calibration_id,
                "device": {"model": "S", "serial": "1"},
                "capture": {"mode_index": 0, "pixel_format": "GRAY8"},
                "image": {"width": 1280, "height": 720},
                "target": {"target_id": "t", "sha256": "abc"},
                "camera_model": {"projection": "pinhole", "distortion": "opencv5"},
                "provenance": {"kind": "synthetic"},
                "cameras": {
                    "camera_a": {"K": [[700, 0, 640], [0, 700, 360], [0, 0, 1]]},
                    "camera_b": {"K": [[701, 0, 640], [0, 701, 360], [0, 0, 1]]},
                },
                "stereo": {
                    "R_camera_b_from_camera_a": [
                        [1.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0],
                        [0.0, 0.0, 1.0],
                    ],
                    "T_camera_b_from_camera_a_m": [-baseline_m, 0.0, 0.0],
                },
            }

        first = document("a", 0.080)
        second = document("b", 0.0805)
        angle = math.radians(0.2)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        second["stereo"]["R_camera_b_from_camera_a"] = [
            [cosine, -sine, 0.0],
            [sine, cosine, 0.0],
            [0.0, 0.0, 1.0],
        ]

        first_path = root / "a.json"
        second_path = root / "b.json"
        first_path.write_text(json.dumps(first), encoding="utf-8")
        second_path.write_text(json.dumps(second), encoding="utf-8")
        args = argparse.Namespace(
            max_rotation_delta_deg=None,
            max_baseline_delta_mm=None,
            max_translation_direction_delta_deg=None,
            max_focal_delta_percent=None,
            max_principal_point_delta_px=None,
            policy_source=None,
        )
        result = compare([first_path, second_path], args)
        assert 0.49 < result["summary"]["max_baseline_delta_mm"] < 0.51
        assert result["status"].startswith("EVIDENCE")
        assert result["provenance"]["tool"] == COMPATIBILITY_TOOL_NAME
    print("Stereo calibration repeatability comparator self-test: PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy-source")
    parser.add_argument("--max-rotation-delta-deg", type=float)
    parser.add_argument("--max-baseline-delta-mm", type=float)
    parser.add_argument("--max-translation-direction-delta-deg", type=float)
    parser.add_argument("--max-focal-delta-percent", type=float)
    parser.add_argument("--max-principal-point-delta-px", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    report = compare(args.artifacts, args)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report["status"] != "FAIL" else 3


def entrypoint(argv: Sequence[str] | None = None) -> int:
    """CLI wrapper preserving the historical error/exit-code contract."""

    try:
        return main(argv)
    except CompareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
